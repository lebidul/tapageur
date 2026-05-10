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
    item = _route_file(fp)
    assert item is not None
    assert item.source_kind == "image"
    assert item.raw_metadata["mime"] == "image/jpeg"


def test_route_file_unsupported_returns_none(tmp_path: Path):
    fp = tmp_path / "rapport.docx"
    fp.write_bytes(b"PK")
    assert _route_file(fp) is None


def test_route_file_gitkeep_returns_none(tmp_path: Path):
    """Le fichier .gitkeep dans un dossier ne doit pas être traité."""
    fp = tmp_path / ".gitkeep"
    fp.write_text("")
    assert _route_file(fp) is None


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

        item = _route_file(fp)

    assert item is not None
    assert item.source_kind == "pdf"
    assert "concert 22 mai" in item.raw_text
    assert item.raw_metadata["n_pages"] == 1


def test_route_file_pdf_empty_returns_none(tmp_path: Path):
    """PDF sans texte extractible (image-only scan) → None."""
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

        assert _route_file(fp) is None


# ---------- Constants ----------

def test_image_exts_have_mime():
    for ext in IMAGE_EXTS:
        assert ext in MIME_BY_EXT, f"{ext} listé sans MIME"
