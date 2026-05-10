"""Tests du connecteur web — focalisés sur la détection/parsing des URLs PDF.

Le fetch HTML lui-même n'est pas testé ici (requiert un réseau ou des mocks
lourds) ; on teste juste les helpers introduits pour le routage PDF.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

from tapageur.connectors.web import _fetch_pdf_url, _is_pdf_url


# ---------- _is_pdf_url ----------

def test_is_pdf_url_by_extension():
    assert _is_pdf_url("https://example.com/program.pdf") is True
    assert _is_pdf_url("https://example.com/path/file.PDF") is True
    assert _is_pdf_url("https://example.com/program.pdf?v=2") is True
    assert _is_pdf_url("https://example.com/agenda") is False
    assert _is_pdf_url("https://example.com/agenda.html") is False


def test_is_pdf_url_head_content_type_fallback():
    """Sans .pdf dans le path mais Content-Type application/pdf → True."""
    with patch("tapageur.connectors.web.requests.head") as mock_head:
        mock_head.return_value = Mock(headers={"content-type": "application/pdf"})
        assert _is_pdf_url("https://example.com/doc?id=42") is True


def test_is_pdf_url_head_failure_treated_as_html():
    """HEAD échoue → conservateur : on traite comme HTML (False)."""
    with patch("tapageur.connectors.web.requests.head", side_effect=Exception("timeout")):
        assert _is_pdf_url("https://example.com/agenda") is False


def test_is_pdf_url_head_html_content_type():
    """HEAD répond text/html → False."""
    with patch("tapageur.connectors.web.requests.head") as mock_head:
        mock_head.return_value = Mock(headers={"content-type": "text/html; charset=utf-8"})
        assert _is_pdf_url("https://example.com/agenda") is False


# ---------- _fetch_pdf_url ----------

def test_fetch_pdf_url_extracts_text():
    """Mock requests.get + pdfplumber : on doit obtenir un CollectedItem pdf."""
    fake_pdf_bytes = b"%PDF-fake"
    with patch("tapageur.connectors.web.requests.get") as mock_get, \
         patch("pdfplumber.open") as mock_pdf_open:
        mock_get.return_value = Mock(content=fake_pdf_bytes, raise_for_status=lambda: None)

        # Mock le context manager de pdfplumber
        page1 = Mock()
        page1.extract_text = lambda: "Page 1: concert vendredi"
        page2 = Mock()
        page2.extract_text = lambda: "Page 2: prix 10€"
        ctx = Mock()
        ctx.pages = [page1, page2]
        ctx.__enter__ = Mock(return_value=ctx)
        ctx.__exit__ = Mock(return_value=None)
        mock_pdf_open.return_value = ctx

        item = _fetch_pdf_url("https://example.com/prog.pdf", "Example Site")

    assert item.source_kind == "pdf"
    assert item.source_ref == "https://example.com/prog.pdf"
    assert "Page 1: concert vendredi" in item.raw_text
    assert "Page 2: prix 10€" in item.raw_text
    assert item.raw_metadata["url"] == "https://example.com/prog.pdf"
    assert item.raw_metadata["site"] == "Example Site"
    assert item.raw_metadata["n_pages"] == 2
