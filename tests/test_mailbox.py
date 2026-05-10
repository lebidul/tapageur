"""Tests du connecteur mailbox (.eml et .msg)."""
from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest

from tapageur.connectors.mailbox import (
    MailboxConnector,
    _decode_header,
    _extract_body,
    _parse_eml,
    _source_ref,
)


def _write_eml_plain(path: Path, subject: str, body: str, sender: str = "a@b.fr") -> None:
    """Génère un .eml plain text minimal pour les tests."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "lebidul@live.fr"
    msg["Date"] = "Mon, 04 May 2026 10:00:00 +0200"
    msg["Message-ID"] = f"<test-{subject.replace(' ', '_')}@example.com>"
    msg.set_content(body)
    path.write_bytes(bytes(msg))


def _write_eml_multipart(path: Path, text_body: str, html_body: str) -> None:
    """Génère un .eml multipart (text/plain + text/html)."""
    msg = EmailMessage()
    msg["Subject"] = "Multipart test"
    msg["From"] = "x@y.fr"
    msg["To"] = "lebidul@live.fr"
    msg["Date"] = "Mon, 04 May 2026 10:00:00 +0200"
    msg["Message-ID"] = "<multi@example.com>"
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    path.write_bytes(bytes(msg))


def _write_eml_html_only(path: Path, html_body: str) -> None:
    """Génère un .eml avec uniquement du text/html (newsletter typique)."""
    msg = EmailMessage()
    msg["Subject"] = "HTML newsletter"
    msg["From"] = "news@example.com"
    msg["To"] = "lebidul@live.fr"
    msg["Date"] = "Mon, 04 May 2026 10:00:00 +0200"
    msg["Message-ID"] = "<html-only@example.com>"
    msg.set_content(html_body, subtype="html")
    path.write_bytes(bytes(msg))


def test_parse_plain_eml(tmp_path: Path):
    fp = tmp_path / "test1.eml"
    _write_eml_plain(fp, "Concert vendredi", "Le concert aura lieu vendredi 22 mai à 20h30.\n")

    items = list(_parse_eml(fp))
    assert len(items) == 1
    item = items[0]
    assert item.source_kind == "outlook"
    assert "vendredi 22 mai" in item.raw_text
    assert item.raw_metadata["subject"] == "Concert vendredi"
    assert item.raw_metadata["from"] == "a@b.fr"
    assert item.raw_metadata["filename"] == "test1.eml"
    assert item.raw_metadata["format"] == "eml"
    assert "test-Concert_vendredi" in item.source_ref


def test_parse_multipart_prefers_plain(tmp_path: Path):
    """Quand text/plain ET text/html sont présents, on préfère le plain."""
    fp = tmp_path / "multi.eml"
    _write_eml_multipart(
        fp,
        text_body="Plain version: concert vendredi.",
        html_body="<html><body><p>HTML version: concert <b>vendredi</b>.</p></body></html>",
    )

    items = list(_parse_eml(fp))
    assert len(items) == 1
    assert "Plain version" in items[0].raw_text
    assert "<b>" not in items[0].raw_text


def test_parse_html_only_strips_tags(tmp_path: Path):
    """Quand seul text/html est dispo, on strip les balises."""
    fp = tmp_path / "html.eml"
    _write_eml_html_only(
        fp,
        "<html><body><h1>Festival</h1><p>Du 22 au 25 <b>mai</b>.</p></body></html>",
    )

    items = list(_parse_eml(fp))
    assert len(items) == 1
    item = items[0]
    assert "Festival" in item.raw_text
    assert "mai" in item.raw_text
    assert "<h1>" not in item.raw_text
    assert "<b>" not in item.raw_text


def test_skip_empty_body(tmp_path: Path):
    """Mail au corps vide ET sans PJ → 0 items yieldés."""
    fp = tmp_path / "empty.eml"
    _write_eml_plain(fp, "Vide", "")
    items = list(_parse_eml(fp))
    assert items == []


def test_source_ref_falls_back_to_filename(tmp_path: Path):
    """Sans Message-ID, on utilise le nom du fichier comme source_ref."""
    from email import message_from_string
    msg = message_from_string("Subject: x\nFrom: a@b.fr\n\nbody")
    assert "Message-ID" not in msg
    p = tmp_path / "noid.eml"
    assert _source_ref(msg, p) == "noid.eml"


def test_decode_header_handles_rfc2047():
    """Les headers encodés UTF-8 RFC 2047 sont décodés correctement."""
    # =?utf-8?Q?...?=  ou  =?utf-8?B?...?=
    encoded = "=?utf-8?Q?Concert_=C3=A0_Le_Mans?="
    assert _decode_header(encoded) == "Concert à Le Mans"


def test_decode_header_handles_plain():
    assert _decode_header("Plain subject") == "Plain subject"
    assert _decode_header("") == ""


def test_connector_skips_unknown_extensions(tmp_path: Path):
    """Les fichiers non-.eml/.msg dans le dossier sont ignorés."""
    base = tmp_path / "mailbox_export"
    month_dir = base / "2026-05"
    month_dir.mkdir(parents=True)

    # Crée un .eml valide
    _write_eml_plain(month_dir / "real.eml", "Real", "Real body content.")
    # Et des fichiers à ignorer
    (month_dir / ".gitkeep").write_text("")
    (month_dir / "readme.txt").write_text("notes")
    (month_dir / ".DS_Store").write_bytes(b"\x00\x01")

    conn = MailboxConnector({"mailbox": {"base_dir": str(base)}})
    items = list(conn.collect("2026-05"))

    assert len(items) == 1
    assert items[0].raw_metadata["filename"] == "real.eml"


def test_connector_missing_month_dir_is_noop(tmp_path: Path):
    """Si le dossier du mois n'existe pas, le connecteur retourne juste rien."""
    base = tmp_path / "mailbox_export"
    base.mkdir()  # base existe mais pas le sous-dossier 2026-99

    conn = MailboxConnector({"mailbox": {"base_dir": str(base)}})
    items = list(conn.collect("2026-99"))
    assert items == []


def test_connector_uses_default_base_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Sans config explicite, lit sources/mailbox_export/<month>/."""
    monkeypatch.chdir(tmp_path)
    month_dir = tmp_path / "sources" / "mailbox_export" / "2026-05"
    month_dir.mkdir(parents=True)
    _write_eml_plain(month_dir / "x.eml", "Default", "Default body content.")

    conn = MailboxConnector({})  # config vide
    items = list(conn.collect("2026-05"))
    assert len(items) == 1


# ============================================================
# Pièces jointes (bug 2 — fix : extraction au lieu d'ignorer)
# ============================================================

def _write_eml_with_attachments(
    path: Path,
    body: str,
    attachments: list[tuple[str, str, bytes]],  # (filename, mime, data)
) -> None:
    """Génère un .eml multipart avec body texte + N pièces jointes."""
    msg = EmailMessage()
    msg["Subject"] = "Mail avec PJ"
    msg["From"] = "x@y.fr"
    msg["To"] = "lebidul@live.fr"
    msg["Date"] = "Mon, 04 May 2026 10:00:00 +0200"
    msg["Message-ID"] = "<with-att@example.com>"
    msg.set_content(body)
    for filename, mime, data in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    path.write_bytes(bytes(msg))


def test_attachment_image_yielded_as_image_item(tmp_path: Path):
    """Une PJ .jpg → CollectedItem séparé avec source_kind='image' et base64."""
    fp = tmp_path / "with_img.eml"
    fake_jpg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # JPEG magic + padding
    _write_eml_with_attachments(
        fp,
        body="Voir le flyer en PJ.",
        attachments=[("flyer.jpg", "image/jpeg", fake_jpg_bytes)],
    )

    items = list(_parse_eml(fp))
    # 1 body + 1 image
    assert len(items) == 2

    body_item = items[0]
    assert body_item.source_kind == "outlook"

    img_item = items[1]
    assert img_item.source_kind == "image"
    assert img_item.raw_image_b64 is not None
    assert img_item.raw_metadata["filename"] == "flyer.jpg"
    assert img_item.raw_metadata["mime"] == "image/jpeg"
    assert img_item.raw_metadata["from_mail"] == "with_img.eml"
    # source_ref attachment doit inclure le mail_ref + filename pour cache stable
    assert "#flyer.jpg" in img_item.source_ref


def test_attachment_unsupported_type_ignored(tmp_path: Path):
    """Une PJ .docx/.zip → ignorée silencieusement, n'apparaît pas dans le yield."""
    fp = tmp_path / "with_docx.eml"
    _write_eml_with_attachments(
        fp,
        body="Voir le doc Word en PJ.",
        attachments=[("rapport.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK\x03\x04fake")],
    )

    items = list(_parse_eml(fp))
    # 1 body, 0 attachment (docx ignoré)
    assert len(items) == 1
    assert items[0].source_kind == "outlook"


def test_attachment_multiple_images_all_yielded(tmp_path: Path):
    """3 PJ images → 1 body + 3 image items."""
    fp = tmp_path / "with_3img.eml"
    fake = b"\xff\xd8\xff\xe0" + b"\x00" * 50
    _write_eml_with_attachments(
        fp,
        body="Plusieurs flyers en PJ.",
        attachments=[
            ("f1.jpg", "image/jpeg", fake),
            ("f2.png", "image/png", fake),
            ("f3.webp", "image/webp", fake),
        ],
    )

    items = list(_parse_eml(fp))
    assert len(items) == 4
    images = [i for i in items if i.source_kind == "image"]
    assert len(images) == 3
    mimes = sorted(i.raw_metadata["mime"] for i in images)
    assert mimes == ["image/jpeg", "image/png", "image/webp"]


def test_attachment_only_no_body(tmp_path: Path):
    """Mail avec body vide mais PJ → on yield juste les PJ, pas de mail item."""
    fp = tmp_path / "att_only.eml"
    fake = b"\xff\xd8\xff\xe0" + b"\x00" * 50
    _write_eml_with_attachments(
        fp,
        body="",
        attachments=[("flyer.png", "image/png", fake)],
    )

    items = list(_parse_eml(fp))
    # body vide → seulement l'image
    assert len(items) == 1
    assert items[0].source_kind == "image"


def test_attachment_source_ref_uses_message_id(tmp_path: Path):
    """source_ref d'une PJ = '<Message-ID>#<filename>' pour clé cache stable."""
    fp = tmp_path / "stable.eml"
    fake = b"\xff\xd8\xff\xe0" + b"\x00" * 50
    _write_eml_with_attachments(
        fp,
        body="Flyer.",
        attachments=[("affiche.jpg", "image/jpeg", fake)],
    )

    items = list(_parse_eml(fp))
    img = next(i for i in items if i.source_kind == "image")
    # Message-ID est <with-att@example.com>
    assert img.source_ref == "<with-att@example.com>#affiche.jpg"
