"""Tests du connecteur docs (remplace l'ancien images, accepte PDF + folders + {month})."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tapageur.connectors.docs import (
    DocsConnector,
    IMAGE_EXTS,
    MIME_BY_EXT,
    _image_to_item,
    _route_file,
)


def _fake_jpeg(n: int = 100) -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01" + b"\x00" * n + b"\xff\xd9"


# ---------- _route_file ----------

def test_route_file_image(tmp_path: Path):
    fp = tmp_path / "flyer.jpg"
    fp.write_bytes(_fake_jpeg())
    out = _route_file(fp)
    assert len(out) == 1
    assert out[0].source_kind == "image"
    assert out[0].raw_metadata["mime"] == "image/jpeg"


def test_route_file_unsupported_returns_none(tmp_path: Path):
    fp = tmp_path / "rapport.docx"
    fp.write_bytes(b"PK")
    assert _route_file(fp) == []


def test_route_file_gitkeep_returns_none(tmp_path: Path):
    """Le fichier .gitkeep dans un dossier ne doit pas être traité."""
    fp = tmp_path / ".gitkeep"
    fp.write_text("")
    assert _route_file(fp) == []


def test_route_file_returns_list_for_image(tmp_path):
    from tapageur.connectors.docs import _route_file
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f1e0000000049454e44ae426082"
    )
    f = tmp_path / "x.png"
    f.write_bytes(png)
    out = _route_file(f)
    assert isinstance(out, list) and len(out) == 1
    assert out[0].source_kind == "image"


def test_route_file_unsupported_returns_empty(tmp_path):
    from tapageur.connectors.docs import _route_file
    f = tmp_path / "x.txt"
    f.write_text("rien", encoding="utf-8")
    assert _route_file(f) == []


def test_route_file_pdf_without_text_routes_to_images(tmp_path, monkeypatch):
    import tapageur.connectors.docs as docs
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF-1.4 fake")  # contenu bidon : on monkeypatche le routage
    monkeypatch.setattr(docs, "_pdf_to_item", lambda p: None)      # pas de texte
    sentinel = object()
    monkeypatch.setattr(docs, "_pdf_pages_to_images", lambda p: [sentinel])
    assert docs._route_file(f) == [sentinel]


def test_route_file_pdf_with_text_returns_single(tmp_path, monkeypatch):
    import tapageur.connectors.docs as docs
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    sentinel = object()
    monkeypatch.setattr(docs, "_pdf_to_item", lambda p: sentinel)
    assert docs._route_file(f) == [sentinel]


# ---------- DocsConnector.collect ----------

def test_collect_individual_file(tmp_path: Path):
    """paths: avec 1 fichier individuel → 1 item."""
    fp = tmp_path / "concert.jpg"
    fp.write_bytes(_fake_jpeg())

    conn = DocsConnector({"docs": {"paths": [str(fp)]}})
    items = list(conn.collect("2026-05"))

    assert len(items) == 1
    assert items[0].source_kind == "image"


def test_collect_directory(tmp_path: Path):
    """paths: avec un dossier → tous les fichiers du dossier sont traités."""
    d = tmp_path / "monthly"
    d.mkdir()
    (d / "flyer1.jpg").write_bytes(_fake_jpeg())
    (d / "flyer2.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    (d / ".DS_Store").write_bytes(b"\x00")  # à ignorer

    conn = DocsConnector({"docs": {"paths": [str(d)]}})
    items = list(conn.collect("2026-05"))

    assert len(items) == 2
    mimes = sorted(i.raw_metadata["mime"] for i in items)
    assert mimes == ["image/jpeg", "image/png"]


def test_collect_substitutes_month(tmp_path: Path):
    """`{month}` dans un path est remplacé par le mois cible."""
    d = tmp_path / "docs" / "2026-05"
    d.mkdir(parents=True)
    (d / "x.jpg").write_bytes(_fake_jpeg())

    conn = DocsConnector({"docs": {"paths": [str(tmp_path / "docs" / "{month}")]}})
    items = list(conn.collect("2026-05"))
    assert len(items) == 1


def test_collect_missing_path_skipped(tmp_path: Path):
    """Un path inexistant émet un warning mais ne plante pas."""
    conn = DocsConnector({"docs": {"paths": [str(tmp_path / "nonexistent")]}})
    items = list(conn.collect("2026-05"))
    assert items == []


def test_collect_mixed_files_and_dirs(tmp_path: Path):
    """paths: mélange un dossier et un fichier individuel."""
    d = tmp_path / "monthly"
    d.mkdir()
    (d / "in_dir.jpg").write_bytes(_fake_jpeg())

    standalone = tmp_path / "standalone.jpg"
    standalone.write_bytes(_fake_jpeg())

    conn = DocsConnector({"docs": {"paths": [str(d), str(standalone)]}})
    items = list(conn.collect("2026-05"))
    assert len(items) == 2
    filenames = {i.raw_metadata["filename"] for i in items}
    assert filenames == {"in_dir.jpg", "standalone.jpg"}


def test_collect_no_paths_section(tmp_path: Path):
    """Pas de section docs ni paths → 0 items, pas de crash."""
    conn = DocsConnector({})
    assert list(conn.collect("2026-05")) == []


# ---------- PDF via mock pdfplumber ----------

def test_route_file_pdf_extracts_text(tmp_path: Path):
    """Mock pdfplumber : un .pdf doit donner source_kind='pdf' avec texte."""
    fp = tmp_path / "season.pdf"
    fp.write_bytes(b"%PDF-fake")

    with patch("pdfplumber.open") as mock_pdf_open:
        page = Mock()
        page.extract_text = lambda: "Programme saison concert 22 mai"
        ctx = Mock()
        ctx.pages = [page]
        ctx.__enter__ = Mock(return_value=ctx)
        ctx.__exit__ = Mock(return_value=None)
        mock_pdf_open.return_value = ctx

        out = _route_file(fp)

    assert len(out) == 1
    assert out[0].source_kind == "pdf"
    assert "concert 22 mai" in out[0].raw_text
    assert out[0].raw_metadata["n_pages"] == 1


def test_route_file_pdf_empty_routes_to_images(tmp_path: Path):
    """PDF sans texte extractible (image-only scan) → fallback _pdf_pages_to_images."""
    fp = tmp_path / "scan.pdf"
    fp.write_bytes(b"%PDF-fake")

    with patch("pdfplumber.open") as mock_pdf_open:
        page = Mock()
        page.extract_text = lambda: ""
        ctx = Mock()
        ctx.pages = [page]
        ctx.__enter__ = Mock(return_value=ctx)
        ctx.__exit__ = Mock(return_value=None)
        mock_pdf_open.return_value = ctx

        with patch(
            "tapageur.connectors.docs._pdf_pages_to_images", return_value=[]
        ) as mock_pages:
            out = _route_file(fp)

    assert out == []
    mock_pages.assert_called_once()


# ---------- PDF → images (affiches sans texte) ----------

def _blank_pdf(path):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(200, 200)
    with open(path, "wb") as f:
        pdf.save(f)


def test_pdf_pages_to_images_blank(tmp_path):
    from tapageur.connectors.docs import _pdf_pages_to_images
    p = tmp_path / "blank.pdf"
    _blank_pdf(p)
    items = _pdf_pages_to_images(p)
    assert len(items) == 1
    it = items[0]
    assert it.source_kind == "image"
    assert it.raw_image_b64 and len(it.raw_image_b64) > 100
    assert it.source_ref.endswith("#page=1")
    assert it.raw_metadata["from_pdf"] is True
    assert it.raw_metadata["mime"] == "image/png"


def test_pdf_pages_to_images_skips_on_render_error(tmp_path, monkeypatch):
    import tapageur.connectors.docs as docs
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"not a real pdf")
    class Boom:
        def __init__(self, *a, **k): raise ValueError("corrupt")
    monkeypatch.setattr("pypdfium2.PdfDocument", Boom)
    assert docs._pdf_pages_to_images(f) == []


# ---------- Constants ----------

def test_image_exts_have_mime():
    for ext in IMAGE_EXTS:
        assert ext in MIME_BY_EXT, f"{ext} listé sans MIME"
