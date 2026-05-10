"""
Connecteur mailbox : lit les emails exportés à la main dans
`cache/mailbox_export/<YYYY-MM>/`.

Bypass complet de l'API Microsoft Graph (qui requiert un tenant Azure AD que
Microsoft refuse de créer pour les comptes Microsoft personnels sans licence
payante). Utilise un tri humain en amont : l'utilisateur sélectionne dans
Outlook les mails utiles du mois et les drag-and-drop dans le dossier mensuel.

Formats supportés :
- .eml : standard RFC 5322, généré par Outlook Web (clic droit → Télécharger),
  Outlook Mac, Thunderbird, etc. Parsé via stdlib `email`.
- .msg : format binaire Microsoft, généré par Outlook Desktop (Windows) via
  drag-and-drop. Parsé via la lib `extract-msg`.

Pièces jointes : ignorées (option (b) du design). Seul le corps du mail va à
Claude. Si l'utilisateur veut traiter un flyer en PJ, qu'il le mette aussi
dans flyers/<month>/ ou season_pdfs/.

source_kind = "outlook" → routé sur Sonnet par MODEL_BY_KIND (économique et
suffisant pour des emails de newsletter / annonce d'event).
"""
from __future__ import annotations

import email
import email.header
from datetime import datetime
from email.message import Message
from pathlib import Path
from typing import Iterator

from bs4 import BeautifulSoup

from tapageur.connectors.base import Connector, register
from tapageur.schema import CollectedItem


@register
class MailboxConnector(Connector):
    name = "mailbox"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        base_dir = Path(
            self.config.get("mailbox", {}).get("base_dir", "cache/mailbox_export")
        )
        month_dir = base_dir / month
        if not month_dir.exists():
            return

        n_eml = 0
        n_msg = 0
        n_err = 0
        for fp in sorted(month_dir.iterdir()):
            ext = fp.suffix.lower()
            if ext == ".eml":
                item = _parse_eml(fp)
                if item is not None:
                    n_eml += 1
                    yield item
                else:
                    n_err += 1
            elif ext == ".msg":
                item = _parse_msg(fp)
                if item is not None:
                    n_msg += 1
                    yield item
                else:
                    n_err += 1
            # ignore .DS_Store, .gitkeep, etc.

        if n_eml or n_msg or n_err:
            print(f"[mailbox] {n_eml} .eml, {n_msg} .msg, {n_err} erreurs")


# ---------- .eml (stdlib email) ----------

def _parse_eml(path: Path) -> CollectedItem | None:
    """Parse un .eml en CollectedItem. Retourne None si parse échoue ou corps vide."""
    try:
        with path.open("rb") as f:
            msg = email.message_from_binary_file(f)
    except Exception as e:
        print(f"[mailbox] échec lecture {path.name}: {e}")
        return None

    text = _extract_body(msg)
    if not text.strip():
        print(f"[mailbox] {path.name}: corps vide, skip")
        return None

    return CollectedItem(
        source_kind="outlook",
        source_ref=_source_ref(msg, path),
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
                continue  # PJ ignorées
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

    # mail non-multipart
    content = _decode_payload(msg)
    if msg.get_content_type() == "text/html":
        content = _strip_html(content)
    return content


def _decode_payload(part: Message) -> str:
    """Décode le payload d'une partie email en str selon son charset."""
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _decode_header(raw: str) -> str:
    """Décode un en-tête email encodé RFC 2047 (=?utf-8?B?...?=)."""
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
    """Préfère le Message-ID (stable cross-export, idempotent pour le cache),
    fallback : nom du fichier."""
    msg_id = (msg.get("Message-ID") or "").strip()
    if msg_id:
        return msg_id
    return path.name


# ---------- .msg (extract-msg) ----------

def _parse_msg(path: Path) -> CollectedItem | None:
    """Parse un .msg (format Outlook Desktop) en CollectedItem."""
    try:
        import extract_msg  # lazy import (dep optionnelle)
    except ImportError:
        print(f"[mailbox] extract-msg non installé, skip {path.name}")
        print("  → pip install extract-msg")
        return None

    try:
        m = extract_msg.Message(str(path))
    except Exception as e:
        print(f"[mailbox] échec lecture {path.name}: {e}")
        return None

    body = (m.body or "").strip()
    if not body:
        # Fallback : strip du HTML body si dispo
        html = m.htmlBody or ""
        if isinstance(html, bytes):
            html = html.decode("utf-8", errors="replace")
        body = _strip_html(html).strip()

    if not body:
        print(f"[mailbox] {path.name}: corps vide, skip")
        return None

    return CollectedItem(
        source_kind="outlook",
        source_ref=(m.messageId or path.name),
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


# ---------- helpers ----------

def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
