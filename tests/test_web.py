"""Tests du connecteur web — focalisés sur la détection/parsing des URLs PDF.

Le fetch HTML lui-même n'est pas testé ici (requiert un réseau ou des mocks
lourds) ; on teste juste les helpers introduits pour le routage PDF.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from tapageur.connectors.web import (
    _fetch,
    _fetch_pdf_url,
    _is_pdf_url,
    clear_fetch_cache,
)


@pytest.fixture(autouse=True)
def _reset_fetch_cache():
    """Isole les tests : reset le cache HTTP avant chaque test."""
    clear_fetch_cache()
    yield
    clear_fetch_cache()


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

# ---------- HTTP cache ----------

def test_fetch_caches_by_url():
    """2 _fetch successifs sur la même URL → 1 seul appel HTTP."""
    with patch("tapageur.connectors.web._do_fetch", return_value="<html>cached</html>") as mock:
        a = _fetch("https://example.com/agenda", needs_browser=False)
        b = _fetch("https://example.com/agenda", needs_browser=False)
    assert a == b == "<html>cached</html>"
    assert mock.call_count == 1  # 2e fetch sert le cache, pas d'appel réseau


def test_fetch_cache_distinguishes_browser_mode():
    """Même URL en mode requests vs Playwright → entrées cache distinctes."""
    with patch("tapageur.connectors.web._do_fetch", side_effect=["<a/>", "<b/>"]) as mock:
        a = _fetch("https://example.com/x", needs_browser=False)
        b = _fetch("https://example.com/x", needs_browser=True)
    assert a == "<a/>" and b == "<b/>"
    assert mock.call_count == 2


# ---------- _extract_subpages : heuristique + pattern ----------

def test_extract_subpages_heuristic_default():
    """Heuristique par défaut : sous-chemin strict de base_path."""
    from tapageur.connectors.web import _extract_subpages
    html = '''<html><body>
      <a href="/agenda/event-1">e1</a>
      <a href="/agenda/event-2">e2</a>
      <a href="/agenda">agenda root</a>
      <a href="/autre/event-3">autre branche</a>
      <a href="https://external.com/x">external</a>
    </body></html>'''
    subs = _extract_subpages(html, base_url="https://site.fr/agenda")
    assert subs == ["https://site.fr/agenda/event-1", "https://site.fr/agenda/event-2"]


def test_extract_subpages_with_pattern_overrides_heuristic():
    """Pattern regex : capte les liens même hors du sous-chemin de base_path.

    Cas réel msj.world/ofcourselemans/86 : pages event sous /ofcourselemans/card/
    pas sous /86/. Heuristique → 0 ; pattern → toutes.
    """
    from tapageur.connectors.web import _extract_subpages
    html = '''<html><body>
      <a href="https://msj.world/ofcourselemans/card/abc">e1</a>
      <a href="https://msj.world/ofcourselemans/card/def">e2</a>
      <a href="https://msj.world/other/x">hors pattern</a>
      <a href="https://external.com/card/x">cross-domain</a>
    </body></html>'''
    subs = _extract_subpages(
        html,
        base_url="https://msj.world/ofcourselemans/86",
        pattern=r"https://msj\.world/ofcourselemans/card/.+",
    )
    assert subs == [
        "https://msj.world/ofcourselemans/card/abc",
        "https://msj.world/ofcourselemans/card/def",
    ]


def test_extract_subpages_pattern_skips_cross_domain():
    """Le pattern ne contourne pas la sécurité cross-domain."""
    from tapageur.connectors.web import _extract_subpages
    html = '<a href="https://evil.com/ofcourselemans/card/x">trap</a>'
    subs = _extract_subpages(
        html,
        base_url="https://msj.world/ofcourselemans/86",
        pattern=r"https://.*/card/.+",  # pattern volontairement permissif
    )
    assert subs == []  # cross-domain bloqué malgré le match pattern


def test_extract_subpages_domain_scope_keeps_siblings():
    from tapageur.connectors.web import _extract_subpages
    html = '''
      <a href="/festival/">agenda</a>
      <a href="/diphonie-des-steppes/">event A</a>
      <a href="/contact/">menu</a>
      <a href="#top">ancre</a>
      <a href="mailto:x@y.fr">mail</a>
      <a href="https://autre.fr/x/">externe</a>
    '''
    subs = _extract_subpages(html, base_url="https://site.fr/festival/", scope="domain")
    assert "https://site.fr/diphonie-des-steppes/" in subs
    assert "https://site.fr/contact/" in subs          # menu gardé (le pré-filtre triera)
    assert "https://site.fr/festival/" not in subs      # pas l'agenda lui-même
    assert not any("autre.fr" in u for u in subs)        # pas cross-domaine
    assert not any(u.startswith("mailto") or "#" in u for u in subs)


def test_extract_subpages_domain_scope_dedups_fragment_and_query():
    from tapageur.connectors.web import _extract_subpages
    html = '''
      <a href="/a/">x</a>
      <a href="/a/#section">x frag</a>
      <a href="/a/?utm=1">x query</a>
    '''
    subs = _extract_subpages(html, base_url="https://site.fr/festival/", scope="domain")
    assert subs.count("https://site.fr/a/") == 1
    assert len([u for u in subs if u.endswith("/a/")]) == 1


def test_clear_fetch_cache_resets():
    """clear_fetch_cache() invalide le cache."""
    with patch("tapageur.connectors.web._do_fetch", return_value="<html/>") as mock:
        _fetch("https://example.com/y", needs_browser=False)
        clear_fetch_cache()
        _fetch("https://example.com/y", needs_browser=False)
    assert mock.call_count == 2  # 1 avant clear, 1 après


# ---------- PDF fetching ----------

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


# ---------- _filter_event_urls ----------

def test_filter_event_urls_month_none_sanity_filters_hallucinations():
    from unittest.mock import Mock, patch
    import tapageur.connectors.web as web
    urls = ["https://site.fr/a/", "https://site.fr/b/"]
    fake = Mock()
    block = Mock(); block.type = "text"
    block.text = '{"urls": ["https://site.fr/a/", "https://site.fr/HALLUCINE/"]}'
    fake.messages.create.return_value = Mock(content=[block])
    with patch("anthropic.Anthropic", return_value=fake):
        kept = web._filter_event_urls("agenda overview", urls, month=None)
    assert kept == ["https://site.fr/a/"]  # b non choisie, HALLUCINE filtrée


def test_filter_event_urls_month_set_passes_month_in_prompt():
    from unittest.mock import Mock, patch
    import tapageur.connectors.web as web
    urls = ["https://site.fr/a/"]
    fake = Mock()
    block = Mock(); block.type = "text"
    block.text = '{"urls": ["https://site.fr/a/"]}'
    fake.messages.create.return_value = Mock(content=[block])
    with patch("anthropic.Anthropic", return_value=fake):
        kept = web._filter_event_urls("agenda", urls, month="2026-11")
    sent = fake.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "2026-11" in sent
    assert kept == ["https://site.fr/a/"]


# ---------- collect() follow_scope domaine + fallback index ----------

def _html_with_links(hrefs):
    return "".join(f'<a href="{h}">x</a>' for h in hrefs)


def test_collect_follow_domain_prefilters_events(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # index + 1 event + 1 menu, tous même-hôte racine
    index_html = _html_with_links(["/diphonie/", "/contact/"])
    monkeypatch.setattr(web, "_fetch",
                        lambda url, needs_browser=False: index_html if url.endswith("/festival/")
                        else "<p>page event diphonie 20 NOV 20h</p>")
    monkeypatch.setattr(web, "_filter_event_urls",
                        lambda agenda, urls, month: ["https://site.fr/diphonie/"])
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)  # pas de HEAD réseau
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/festival/", "name": "fest",
        "follow_event_links": True, "follow_scope": "domain",
        "prefilter_by_month": False,
    }]})
    items = list(conn.collect("2026-11"))
    refs = [it.source_ref for it in items]
    assert refs == ["https://site.fr/diphonie/"]  # event gardé, menu + index écartés


def test_collect_follow_domain_fallback_index_when_prefilter_empty(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    index_html = _html_with_links(["/contact/", "/a-propos/"])
    monkeypatch.setattr(web, "_fetch", lambda url, needs_browser=False: index_html)
    monkeypatch.setattr(web, "_filter_event_urls", lambda agenda, urls, month: [])
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)  # pas de HEAD réseau
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/festival/", "name": "fest",
        "follow_event_links": True, "follow_scope": "domain",
        "prefilter_by_month": False,
    }]})
    items = list(conn.collect("2026-11"))
    assert len(items) == 1
    assert items[0].source_ref == "https://site.fr/festival/"  # fallback = page d'index
    assert items[0].source_kind == "web"


def test_is_error_page_detects_soft_404():
    from tapageur.connectors.web import _is_error_page
    assert _is_error_page("Musée\nErreur 404\nPage introuvable\nblabla")
    assert _is_error_page("Oops — 404 Not Found")
    assert not _is_error_page("Concert de Lena Haudecoeur, piano, 13 nov 20h30")


def test_collect_follow_domain_soft404_pages_fall_back_to_index(monkeypatch):
    """Toutes les pages suivies sont des soft-404 → repli sur l'index (qui
    porte le programme inline). Cas réel musiquesmagiques.fr."""
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    index_html = (_html_with_links(["Agenda-1281", "Agenda-1282"])
                  + "<p>Murmures au piano 13 NOV 20h30 Lena Haudecoeur</p>")
    soft404 = "<h1>Erreur 404</h1><p>Page introuvable</p>"
    monkeypatch.setattr(web, "_fetch",
                        lambda url, needs_browser=False: index_html if url.endswith("/index.php")
                        else soft404)
    monkeypatch.setattr(web, "_filter_event_urls",
                        lambda a, u, m: ["https://site.fr/Agenda/Agenda-1281",
                                         "https://site.fr/Agenda/Agenda-1282"])
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/Agenda/index.php", "name": "mm",
        "follow_event_links": True, "follow_scope": "domain",
        "prefilter_by_month": False,
    }]})
    items = list(conn.collect("2026-11"))
    assert len(items) == 1
    assert items[0].source_ref == "https://site.fr/Agenda/index.php"  # repli index
    assert "Murmures au piano" in items[0].raw_text


def test_collect_follow_domain_drops_soft404_keeps_usable(monkeypatch):
    """Mix : une page soft-404 écartée, une page exploitable gardée, pas de repli."""
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    index_html = _html_with_links(["Agenda-1281", "Agenda-1282"])
    def fake_fetch(url, needs_browser=False):
        if url.endswith("/index.php"):
            return index_html
        if url.endswith("Agenda-1281"):
            return "<h1>Erreur 404</h1><p>Page introuvable</p>"
        return "<p>Concert réel 14 NOV 21h, Groupe X</p>"
    monkeypatch.setattr(web, "_fetch", fake_fetch)
    monkeypatch.setattr(web, "_filter_event_urls",
                        lambda a, u, m: ["https://site.fr/Agenda/Agenda-1281",
                                         "https://site.fr/Agenda/Agenda-1282"])
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/Agenda/index.php", "name": "mm",
        "follow_event_links": True, "follow_scope": "domain",
        "prefilter_by_month": False,
    }]})
    items = list(conn.collect("2026-11"))
    refs = [it.source_ref for it in items]
    assert refs == ["https://site.fr/Agenda/Agenda-1282"]  # 1281 (soft-404) écartée


def test_collect_follow_domain_fallback_index_when_no_key(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    index_html = _html_with_links(["/diphonie/"])
    monkeypatch.setattr(web, "_fetch", lambda url, needs_browser=False: index_html)
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)  # pas de HEAD réseau
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/festival/", "name": "fest",
        "follow_event_links": True, "follow_scope": "domain",
        "prefilter_by_month": False,
    }]})
    items = list(conn.collect("2026-11"))
    assert len(items) == 1
    assert items[0].source_ref == "https://site.fr/festival/"  # pas de fetch massif du domaine


def test_collect_follow_domain_reports_page_progress(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    index_html = _html_with_links(["/diphonie/", "/polyphonies/", "/contact/"])
    monkeypatch.setattr(web, "_fetch",
                        lambda url, needs_browser=False: index_html if url.endswith("/festival/")
                        else "<p>event</p>")
    monkeypatch.setattr(web, "_filter_event_urls",
                        lambda a, u, m: ["https://site.fr/diphonie/", "https://site.fr/polyphonies/"])
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/festival/", "name": "fest",
        "follow_event_links": True, "follow_scope": "domain", "prefilter_by_month": False,
    }]})
    seen = []
    items = list(conn.collect("2026-11", progress=lambda msg: seen.append(msg)))
    assert len(items) == 2
    # Le nom de la source est préfixé dans le log live (TODO #10).
    assert any("fest" in m and "2 pages" in m for m in seen)
    assert any("fest" in m and "Page 1/2" in m and "diphonie" in m for m in seen)
    assert any("fest" in m and "Page 2/2" in m and "polyphonies" in m for m in seen)


def test_collect_propagates_overrides_to_items(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    monkeypatch.setattr(web, "_fetch", lambda url, needs_browser=False: "<p>concert</p>")
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/p", "name": "p",
        "follow_event_links": False,
        "default_venue": "Le Scarron", "default_festival": "Asso X",
    }]})
    items = list(conn.collect("2026-11"))
    assert items[0].raw_metadata["default_venue"] == "Le Scarron"
    assert items[0].raw_metadata["default_festival"] == "Asso X"


# ---------- hook _BROWSER_FETCH ----------

def test_do_fetch_uses_browser_hook(monkeypatch):
    from tapageur.connectors import web
    monkeypatch.setattr(web, "_BROWSER_FETCH", lambda url: f"<html>{url}</html>")
    out = web._do_fetch("https://exemple.fr/agenda", needs_browser=True)
    assert out == "<html>https://exemple.fr/agenda</html>"


def test_do_fetch_requests_path_without_hook(monkeypatch):
    from tapageur.connectors import web
    monkeypatch.setattr(web, "_BROWSER_FETCH", None)
    class _Resp:
        text = "<html>requests</html>"
        def raise_for_status(self): pass
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _Resp())
    out = web._do_fetch("https://exemple.fr/", needs_browser=False)
    assert out == "<html>requests</html>"
