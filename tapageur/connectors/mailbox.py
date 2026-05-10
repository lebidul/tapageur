"""
Connecteur mailbox : lit les emails exportés à la main dans
`sources/mailbox_export/<YYYY-MM>/`.

Bypass complet de l'API Microsoft Graph (qui requiert un tenant Azure AD que
Microsoft refuse de créer pour les comptes Microsoft personnels sans licence
payante). Utilise un tri humain en amont : l'utilisateur sélectionne dans
Outlook les mails utiles du mois et les drag-and-drop dans le dossier mensuel.

Formats supportés :
- .eml : standard RFC 5322, généré par Outlook Web (clic droit → Télécharger),
  Outlook Mac, Thunderbird, etc. Parsé via stdlib `email`.
- .msg : format binaire Microsoft, généré par Outlook Desktop (Windows) via
  drag-and-drop. Parsé via la lib `extract-msg`.

Pièces jointes : extraites comme CollectedItems séparés.
- Images (jpg/png/webp/gif) → source_kind="image", base64 → Claude vision Opus.
- PDFs → source_kind="pdf", texte via pdfplumber → Claude Opus.
- Autres types (.docx, .xlsx, etc.) → ignorés avec log.

source_kind = "outlook" pour le corps du mail → routé sur Sonnet par
MODEL_BY_KIND (économique, suffisant pour newsletter / annonce d'event).
"""
from __future__ import annotations

import base64
import email
import email.header
import io
from datetime import datetime
from email.message import Message
from pathlib import Path
from typing import Iterator

from bs4 import BeautifulSoup

from tapageur.connectors.base import Connector, register
from tapageur.schema import CollectedItem


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
PDF_EXTS = {".pdf"}
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


@register
class MailboxConnector(Connector):
    name = "mailbox"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        base_dir = Path(
            self.config.get("mailbox", {}).get("base_dir", "sources/mailbox_export")
        )
        month_dir = base_dir / month
        if not month_dir.exists():
            return

        n_mails = 0
        n_attach = 0
        for fp in sorted(month_dir.iterdir()):
            ext = fp.suffix.lower()
            if ext == ".eml":
                items = list(_parse_eml(fp))
            elif ext == ".msg":
                items = list(_parse_msg(fp))
            else:
                continue  # .DS_Store, .gitkeep, etc.

            for it in items:
                if it.source_kind == "outlook":
                    n_mails += 1
                else:
                    n_attach += 1
                yield it

        if n_mails or n_attach:
            print(f"[mailbox] {n_mails} mails, {n_attach} pièces jointes")


# ============================================================
# .eml (stdlib email)
# ============================================================

def _parse_eml(path: Path) -> Iterator[CollectedItem]:
    """Yield le CollectedItem du corps + un par PJ supportée.
    Aucun yield si le mail n'a pas pu être lu OU si corps vide ET aucune PJ."""
    try:
        with path.open("rb") as f:
            msg = email.message_from_binary_file(f)
    except Exception as e:
        print(f"[mailbox] échec lecture {path.name}: {e}")
        return

    mail_ref = _source_ref(msg, path)

    # Corps
    text = _extract_body(msg)
    if text.strip():
        yield CollectedItem(
            source_kind="outlook",
            source_ref=mail_ref,
            fetched_at=datetime.utcnow().isoformat() + "Z",
            raw_text=text,
            raw_metadata={
                "subject": _decode_header(msg.get("Subject", "")),
                "from": _decode_header(msg.get("From", "")),
                "received": msg.get("Date", ""),
                "filename": path.name,
                "format": "eml",
            },
        )
    else:
        print(f"[mailbox] {path.name}: corps vide")

    # Pièces jointes
    if not msg.is_multipart():
        return

    for part in msg.walk():
        disposition = (part.get("Content-Disposition") or "").lower()
        if "attachment" not in disposition:
            continue
        filename = part.get_filename() or "unnamed"
        # Décode le filename si encodé RFC 2047
        filename = _decode_header(filename) or "unnamed"
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        att = _attachment_to_item(
            data=payload,
            filename=filename,
            mail_ref=mail_ref,
            mail_filename=path.name,
            content_type=part.get_content_type(),
        )
        if att is not None:
            yield att


def _extract_body(msg: Message) -> str:
    """Extrait le texte d'un email. Préfère text/plain, fallback text/html (stripé).
    Ignore les pièces jointes."""
    if msg.is_multipart():
        text_part = None
        html_part = None
        for part in msg.walk():
            ctype = part.get_content_type()
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            if ctype == "text/plain" and text_part is None:
                text_part = part
            elif ctype == "text/html" and html_part is None:
                html_part = part
        chosen = text_part or html_part
        if chosen is None:
            return ""
        content = _decode_payload(chosen)
        if chosen.get_content_type() == "text/html":
            content = _strip_html(content)
        return content

    content = _decode_payload(msg)
    if msg.get_content_type() == "text/html":
        content = _strip_html(content)
    return content


def _decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _decode_header(raw: str) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    out = []
    for value, charset in parts:
        if isinstance(value, bytes):
            try:
                out.append(value.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                out.append(value.decode("utf-8", errors="replace"))
        else:
            out.append(value)
    return "".join(out).strip()


def _source_ref(msg: Message, path: Path) -> str:
    msg_id = (msg.get("Message-ID") or "").strip()
    if msg_id:
        return msg_id
    return path.name


# ============================================================
# .msg (extract-msg)
# ============================================================

def _parse_msg(path: Path) -> Iterator[CollectedItem]:
    """Yield le CollectedItem du corps + un par PJ supportée."""
    try:
        import extract_msg  # lazy import (dep optionnelle)
    except ImportError:
        print(f"[mailbox] extract-msg non installé, skip {path.name}")
        print("  → pip install extract-msg")
        return

    try:
        m = extract_msg.Message(str(path))
    except Exception as e:
        print(f"[mailbox] échec lecture {path.name}: {e}")
        return

    body = (m.body or "").strip()
    if not body:
        html = m.htmlBody or ""
        if isinstance(html, bytes):
            html = html.decode("utf-8", errors="replace")
        body = _strip_html(html).strip()

    mail_ref = m.messageId or path.name

    if body:
        yield CollectedItem(
            source_kind="outlook",
            source_ref=mail_ref,
            fetched_at=datetime.utcnow().isoformat() + "Z",
            raw_text=body,
            raw_metadata={
                "subject": m.subject or "",
                "from": m.sender or "",
                "received": str(m.date or ""),
                "filename": path.name,
                "format": "msg",
            },
        )
    else:
        print(f"[mailbox] {path.name}: corps vide")

    # Pièces jointes
    for att in (m.attachments or []):
        filename = att.longFilename or att.shortFilename or "unnamed"
        data = att.data
        if not data:
            continue
        att_item = _attachment_to_item(
            data=data,
            filename=filename,
            mail_ref=mail_ref,
            mail_filename=path.name,
            content_type=None,  # extract-msg n'expose pas le content_type fiable
        )
        if att_item is not None:
            yield att_item


# ============================================================
# Attachments → CollectedItem
# ============================================================

def _attachment_to_item(
    data: bytes,
    filename: str,
    mail_ref: str,
    mail_filename: str,
    content_type: str | None,
) -> CollectedItem | None:
    """Route une PJ vers un CollectedItem image ou pdf selon son extension.
    Retourne None pour les types non supportés (.docx, .xlsx, etc.)."""
    ext = Path(filename).suffix.lower()

    if ext in IMAGE_EXTS:
        return CollectedItem(
            source_kind="image",
            source_ref=f"{mail_ref}#{filename}",
            fetched_at=datetime.utcnow().isoformat() + "Z",
            raw_text="",
            raw_image_b64=base64.b64encode(data).decode("ascii"),
            raw_metadata={
                "filename": filename,
                "mime": MIME_BY_EXT.get(ext, content_type or "image/jpeg"),
                "from_mail": mail_filename,
            },
        )

    if ext in PDF_EXTS:
        text = _extract_pdf_text(data, filename)
        if not text or not text.strip():
            print(f"[mailbox]   PJ {filename}: PDF sans texte extractible, skip")
            return None
        return CollectedItem(
            source_kind="pdf",
            source_ref=f"{mail_ref}#{filename}",
            fetched_at=datetime.utcnow().isoformat() + "Z",
            raw_text=text,
            raw_metadata={
                "filename": filename,
                "from_mail": mail_filename,
            },
        )

    # Types non supportés (Word, Excel, ZIP, etc.)
    if ext:  # silencieux pour les .DS_Store et autres
        print(f"[mailbox]   PJ {filename}: type non supporté ({ext}), skip")
    return None


def _extract_pdf_text(data: bytes, filename: str) -> str:
    """Extrait le texte d'un PDF en mémoire via pdfplumber. Robuste aux erreurs."""
    try:
        import pdfplumber  # lazy
    except ImportError:
        print(f"[mailbox]   PJ {filename}: pdfplumber non installé, skip")
        return ""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as e:
        print(f"[mailbox]   PJ {filename}: erreur pdfplumber {e}")
        return ""


def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
