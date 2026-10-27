"""Tests du connecteur web — focalisés sur la détection/parsing des URLs PDF.

Le fetch HTML lui-même n'est pas testé ici (requiert un réseau ou des mocks
lourds) ; on teste juste les helpers introduits pour le routage PDF.
"""
from __future__ import annotations

import os
from pathlib import Path
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


def test_extract_subpages_excludes_taxonomy():
    """Les pages de taxonomie/filtre (catégorie, tag, commune…) ne sont pas des
    events et polluaient le comptage des liens par carte → exclues."""
    from tapageur.connectors.web import _extract_subpages
    html = '''
      <a href="/event/giedre-maxi-best-of/">GIÉDRÉ</a>
      <a href="/events/categorie/spectacle-pres-du-mans/">catégorie</a>
      <a href="/event/berengere/">Bérengère</a>
      <a href="/agenda/commune/le-mans/">commune</a>
    '''
    subs = _extract_subpages(html, base_url="https://leo.fr/programme/", scope="domain")
    assert any("giedre" in u for u in subs) and any("berengere" in u for u in subs)
    assert not any("categorie" in u for u in subs)
    assert not any("/commune/" in u for u in subs)


def test_card_snippet_found_despite_taxonomy_link():
    """Une carte avec un lien de catégorie + le lien event garde quand même sa
    date (régression léolienne : la carte était faussement rejetée)."""
    from tapageur.connectors.web import _extract_subpages, _extract_card_snippets
    html = ('<article><div class="badge">'
            '<a href="/events/categorie/spectacle/">SPECTACLE</a>'
            '<span>16 octobre 2026 - 20h00</span>'
            '<a href="/event/giedre/">GIÉDRÉ</a>'
            '<a href="/event/giedre/">Découvrir</a>'
            '</div></article>')
    base = "https://leo.fr/programme/"
    subs = _extract_subpages(html, base_url=base, scope="domain")
    cards = dict(_extract_card_snippets(html, base, subs))
    giedre = next(u for u in subs if "giedre" in u)
    assert "16 octobre 2026" in cards[giedre]


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


# ---------- _extract_card_snippets ----------

# Structure Elementor réelle (leoliennearnage.fr) : dans une carte, la date et
# le lien vivent dans des widgets distincts sous un conteneur commun (e-con).
_GIEDRE = "https://leoliennearnage.fr/event/giedre-maxi-best-of/"
_BERENGERE = "https://leoliennearnage.fr/event/berengere-krief-sexe/"
_LEO_BASE = "https://leoliennearnage.fr/programme-concerts-spectacles/"

_ELEMENTOR_HTML = f'''<html><body>
  <nav><a href="https://leoliennearnage.fr/contact/">Contact</a></nav>
  <div class="e-con">
    <div class="widget datetime">
      <span class="datetime-date">16 octobre 2026</span>
      <span class="datetime-time">20h00</span>
    </div>
    <div class="widget title"><h2>GIÉDRÉ MAXI BEST OF</h2></div>
    <div class="widget button"><a href="{_GIEDRE}">Découvrir</a></div>
  </div>
  <div class="e-con">
    <div class="widget datetime"><span>6 novembre 2026</span><span>20h00</span></div>
    <div class="widget button"><a href="{_BERENGERE}">Découvrir</a></div>
  </div>
</body></html>'''


def test_extract_card_snippets_finds_date_from_sibling_widget():
    """La carte du lien giedre contient la date de son widget frère."""
    from tapageur.connectors.web import _extract_card_snippets
    cards = dict(_extract_card_snippets(_ELEMENTOR_HTML, _LEO_BASE,
                                        [_GIEDRE, _BERENGERE]))
    assert "16 octobre 2026" in cards[_GIEDRE]
    assert "GIÉDRÉ" in cards[_GIEDRE]
    assert "6 novembre 2026" in cards[_BERENGERE]


def test_extract_card_snippets_preserves_order_and_length():
    from tapageur.connectors.web import _extract_card_snippets
    out = _extract_card_snippets(_ELEMENTOR_HTML, _LEO_BASE, [_BERENGERE, _GIEDRE])
    assert [u for u, _ in out] == [_BERENGERE, _GIEDRE]


def test_extract_card_snippets_no_date_link_returns_empty():
    """Un lien dont aucun ancêtre ne porte de date → snippet vide (inclure)."""
    from tapageur.connectors.web import _extract_card_snippets
    html = '''<div class="e-con">
      <div class="title"><h2>Concert</h2></div>
      <div class="button"><a href="https://site.fr/event/nodate/">Découvrir</a></div>
    </div>'''
    out = dict(_extract_card_snippets(html, "https://site.fr/a/",
                                      ["https://site.fr/event/nodate/"]))
    assert out["https://site.fr/event/nodate/"] == ""


def test_extract_card_snippets_list_container_not_a_card():
    """Garde anti-liste : si le seul ancêtre daté enveloppe aussi un autre lien
    candidat, ce n'est pas une carte → snippet vide."""
    from tapageur.connectors.web import _extract_card_snippets
    a = "https://site.fr/event/a/"
    b = "https://site.fr/event/b/"
    html = f'''<div class="list">
      <p>Agenda du 5 novembre 2026</p>
      <a href="{a}">A</a>
      <a href="{b}">B</a>
    </div>'''
    out = dict(_extract_card_snippets(html, "https://site.fr/x/", [a, b]))
    assert out[a] == "" and out[b] == ""


def test_extract_card_snippets_matches_subpages_canonicalization():
    """Les URLs à matcher sont celles produites par _extract_subpages (slash
    final conservé) ; un href relatif doit se résoudre pareillement."""
    from tapageur.connectors.web import _extract_card_snippets
    html = '''<div class="e-con">
      <span>12 novembre 2026</span>
      <a href="/event/x/">lien relatif</a>
    </div>'''
    out = dict(_extract_card_snippets(html, "https://site.fr/agenda/",
                                      ["https://site.fr/event/x/"]))
    assert "12 novembre 2026" in out["https://site.fr/event/x/"]


# ---------- _filter_event_urls ----------

def test_filter_event_urls_month_none_sanity_filters_hallucinations():
    from unittest.mock import Mock, patch
    import tapageur.connectors.web as web
    cards = [("https://site.fr/a/", "concert 5 nov 2026"),
             ("https://site.fr/b/", "")]
    fake = Mock()
    block = Mock(); block.type = "text"
    block.text = '{"urls": ["https://site.fr/a/", "https://site.fr/HALLUCINE/"]}'
    fake.messages.create.return_value = Mock(content=[block])
    with patch("anthropic.Anthropic", return_value=fake):
        kept = web._filter_event_urls(cards, month=None)
    assert kept == ["https://site.fr/a/"]  # b non choisie, HALLUCINE filtrée


def test_filter_event_urls_passes_month_and_cards_in_prompt():
    from unittest.mock import Mock, patch
    import tapageur.connectors.web as web
    cards = [("https://site.fr/a/", "spectacle 16 octobre 2026 - 20h00 GIÉDRÉ")]
    fake = Mock()
    block = Mock(); block.type = "text"
    block.text = '{"urls": ["https://site.fr/a/"]}'
    fake.messages.create.return_value = Mock(content=[block])
    with patch("anthropic.Anthropic", return_value=fake):
        kept = web._filter_event_urls(cards, month="2026-11")
    sent = fake.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "2026-11" in sent
    assert "16 octobre 2026" in sent   # la carte (avec date) est transmise
    assert "https://site.fr/a/" in sent
    assert kept == ["https://site.fr/a/"]


def test_prefilter_system_compares_month_and_year():
    """Le pré-filtre doit exclure une carte dont l'ANNÉE diffère de la cible,
    même si le nom de mois correspond (cas theatre-epidaure : saisons 2024-2025
    archivées listées à côté de 2026-2027)."""
    from tapageur.connectors.web import PREFILTER_SYSTEM
    low = PREFILTER_SYSTEM.lower()
    # Compare bien l'année, pas seulement le nom de mois.
    assert "année" in low
    # Garde-fou anti-perte préservé : pas de date lisible → INCLURE.
    assert "ne jamais exclure" in low


# ---------- Cas de référence #12 (live, opt-in) ----------

# Cartes représentatives du cas theatre-epidaure : une page liste plusieurs
# saisons. « novembre » apparaît en 2024 (archive) ET en 2026 (cible) ; seul le
# 2026-11 doit survivre au filtre. Les cartes sans date restent incluses.
_EPIDAURE_CARDS = [
    ("https://www.theatre-epidaure.com/event/archive-nov-2024/",
     "Sam. 30 novembre 2024 - 20h30 SPECTACLE ARCHIVE"),
    ("https://www.theatre-epidaure.com/event/archive-jan-2025/",
     "15 janvier 2025 - 20h00 AUTRE ARCHIVE"),
    ("https://www.theatre-epidaure.com/event/concert-nov-2026/",
     "Ven. 13 novembre 2026 - 20h30 CONCERT CIBLE"),
    ("https://www.theatre-epidaure.com/event/sans-date/", ""),
]

# Cartes réelles extraites de leoliennearnage.fr/programme-concerts-spectacles/
# (validées par _extract_card_snippets sur le HTML live). Seul berengere est en
# novembre 2026 ; giedre (16 oct) et les autres sont hors cible.
_LEO_CARDS_2026 = [
    ("https://leoliennearnage.fr/event/soiree-ouverture-saison-avec-spectacle-on-netait-que-deux/",
     "spectacle 25 septembre 2026 - 19h00 SOIRÉE OUVERTURE SAISON"),
    ("https://leoliennearnage.fr/event/jazz-magic/",
     "spectacle 10 octobre 2026 - 15h30 JAZZ MAGIC"),
    ("https://leoliennearnage.fr/event/jazz-magic-18h30/",
     "spectacle 10 octobre 2026 - 18h30 JAZZ MAGIC"),
    ("https://leoliennearnage.fr/event/giedre-maxi-best-of/",
     "spectacle 16 octobre 2026 - 20h00 GIÉDRÉ MAXI BEST OF"),
    ("https://leoliennearnage.fr/event/par-monts-et-par-soi/",
     "projection 28 octobre 2026 - 19h00 PAR MONTS ET PAR SOI"),
    ("https://leoliennearnage.fr/event/berengere-krief-sexe/",
     "spectacle 6 novembre 2026 - 20h00 BÉRENGÈRE KRIEF : SEXE"),
]


# Opt-in explicite : la suite ne fait AUCUN appel modèle réel par défaut (comme
# le reste du repo, tout est mocké). Pour lancer ce cas de référence en vrai :
#   TAPAGEUR_LIVE_TESTS=1 pytest -k drops_giedre   (clé .env requise)
@pytest.mark.skipif(not os.environ.get("TAPAGEUR_LIVE_TESTS"),
                    reason="test live opt-in : exporter TAPAGEUR_LIVE_TESTS=1")
def test_prefilter_drops_giedre_keeps_berengere_live():
    """Cas de référence TODO #12 : pré-filtre mois 2026-11 sur les cartes réelles
    → giedre (16 oct) écarté, berengere (6 nov) gardé."""
    from dotenv import load_dotenv
    load_dotenv(override=True)  # clé API depuis .env, comme l'app (cli.py)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY absente (.env)")
    from tapageur.connectors.web import _filter_event_urls
    kept = _filter_event_urls(_LEO_CARDS_2026, month="2026-11")
    giedre = "https://leoliennearnage.fr/event/giedre-maxi-best-of/"
    berengere = "https://leoliennearnage.fr/event/berengere-krief-sexe/"
    assert berengere in kept, "l'event de novembre doit être gardé"
    assert giedre not in kept, "giedre (16 octobre) doit être écarté avant le fetch"
    # Aucun event d'octobre/septembre ne doit survivre au filtre mois.
    assert kept == [berengere]


@pytest.mark.skipif(not os.environ.get("TAPAGEUR_LIVE_TESTS"),
                    reason="test live opt-in : exporter TAPAGEUR_LIVE_TESTS=1")
def test_prefilter_year_strict_drops_wrong_year_live():
    """Cas theatre-epidaure : cible 2026-11, la carte « 30 novembre 2024 » doit
    être écartée (même mois, mauvaise année) ; le 2026-11 et la carte sans date
    sont gardés."""
    from dotenv import load_dotenv
    load_dotenv(override=True)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY absente (.env)")
    from tapageur.connectors.web import _filter_event_urls
    kept = set(_filter_event_urls(_EPIDAURE_CARDS, month="2026-11"))
    nov_2024 = "https://www.theatre-epidaure.com/event/archive-nov-2024/"
    jan_2025 = "https://www.theatre-epidaure.com/event/archive-jan-2025/"
    nov_2026 = "https://www.theatre-epidaure.com/event/concert-nov-2026/"
    sans_date = "https://www.theatre-epidaure.com/event/sans-date/"
    assert nov_2026 in kept, "l'event de novembre 2026 doit être gardé"
    assert sans_date in kept, "une carte sans date lisible doit rester incluse"
    assert nov_2024 not in kept, "novembre 2024 (mauvaise année) doit être écarté"
    assert jan_2025 not in kept, "janvier 2025 (hors cible) doit être écarté"


# ---------- Régression #12 : vraie page theatre-epidaure (fixture HTML rendu) ----------

# HTML rendu (WebView2/JS, identique à ce que capture le navigateur embarqué du
# GUI) de la page /programmation/ d'epidaure, capturé le 2026-10-27. La page
# liste 58 events sur plusieurs saisons (archives 2024-2025 + saison 2026-2027) ;
# seuls 3 tombent en novembre 2026. C'est le cas qui faisait garder les 58 :
# avant ed24560, _extract_card_snippets rendait des cartes VIDES sur cette
# structure (liens de taxonomie comptés dans l'ancêtre daté → carte rejetée),
# donc « pas de date → inclure » n'écartait aucun hors-mois. Depuis ed24560 les
# cartes ressortent datées et le pré-filtre ne garde que les 3 de novembre.
_EPIDAURE_FIXTURE = Path(__file__).parent / "fixtures" / "epidaure_programmation.html"
_EPIDAURE_URL = "https://www.theatre-epidaure.com/programmation/"
_EPIDAURE_NOV_2026 = {
    "https://www.theatre-epidaure.com/programmation/habiter-ensemble/",
    "https://www.theatre-epidaure.com/programmation/mon-pere-avait-trois-vaches/",
    "https://www.theatre-epidaure.com/programmation/pourparlers/",
}


def test_epidaure_real_page_cards_are_dated_not_empty():
    """Régression #12 (pur Python, aucun appel modèle) : sur la vraie page
    epidaure en scope=domaine (comme le GUI), les cartes des events portent bien
    leur date → snippets NON vides. Ce test échoue sur le code d'avant ed24560
    (toutes les cartes vides) et garde le bug corrigé."""
    from tapageur.connectors.web import _extract_subpages, _extract_card_snippets
    html = _EPIDAURE_FIXTURE.read_text(encoding="utf-8")
    urls = _extract_subpages(html, base_url=_EPIDAURE_URL, scope="domain")
    # Les 3 events de novembre 2026 sont bien découverts comme liens candidats.
    assert _EPIDAURE_NOV_2026 <= set(urls)
    cards = dict(_extract_card_snippets(html, _EPIDAURE_URL, urls))
    # Le cœur du bug : les cartes event doivent être datées, pas vides.
    event_dated = [s for u, s in cards.items()
                   if "/programmation/" in u and s.strip()]
    assert len(event_dated) >= 50, (
        "les cartes event doivent porter leur date (bug #12 : toutes vides)")
    # Dates réelles lisibles, dans la cible comme hors cible.
    assert "novembre 2026" in cards[
        "https://www.theatre-epidaure.com/programmation/habiter-ensemble/"].lower()
    assert "janvier 2027" in cards[
        "https://www.theatre-epidaure.com/programmation/potomitan/"].lower()


@pytest.mark.skipif(not os.environ.get("TAPAGEUR_LIVE_TESTS"),
                    reason="test live opt-in : exporter TAPAGEUR_LIVE_TESTS=1")
def test_epidaure_real_page_prefilter_keeps_only_november_live():
    """Cas #12 bout-en-bout sur la vraie page epidaure (scope=domaine, cible
    2026-11) : parmi les 58 events + pages de nav, le pré-filtre ne retient que
    les 3 events de novembre 2026 (les hors-mois et les pages de navigation sans
    date sont écartés). Opt-in : TAPAGEUR_LIVE_TESTS=1, clé .env requise."""
    from dotenv import load_dotenv
    load_dotenv(override=True)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY absente (.env)")
    from tapageur.connectors.web import (
        _extract_subpages, _extract_card_snippets, _filter_event_urls)
    html = _EPIDAURE_FIXTURE.read_text(encoding="utf-8")
    urls = _extract_subpages(html, base_url=_EPIDAURE_URL, scope="domain")
    cards = _extract_card_snippets(html, _EPIDAURE_URL, urls)
    kept = set(_filter_event_urls(cards, month="2026-11"))
    assert kept == _EPIDAURE_NOV_2026


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
                        lambda cards, month: ["https://site.fr/diphonie/"])
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)  # pas de HEAD réseau
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/festival/", "name": "fest",
        "follow_event_links": True, "follow_scope": "domain",
        "prefilter_by_month": False,
    }]})
    items = list(conn.collect("2026-11"))
    refs = [it.source_ref for it in items]
    assert refs == ["https://site.fr/diphonie/"]  # event gardé, menu + index écartés


def test_collect_passes_card_pairs_and_month_to_prefilter(monkeypatch):
    """Le pré-filtre reçoit des paires (URL, texte de carte) + le mois cible
    quand prefilter_by_month est actif (approche A, TODO #12)."""
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # Agenda : carte datée pour /event/giedre/ (16 oct) + lien nav /contact/.
    giedre = "https://site.fr/event/giedre/"
    index_html = f'''<body>
      <div class="card"><span>16 octobre 2026</span><a href="{giedre}">voir</a></div>
      <a href="https://site.fr/contact/">Contact</a>
    </body>'''
    monkeypatch.setattr(web, "_fetch",
                        lambda url, needs_browser=False: index_html if url.endswith("/agenda/")
                        else "<p>event</p>")
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    captured = {}
    def fake_prefilter(cards, month):
        captured["cards"] = cards
        captured["month"] = month
        return [u for u, _ in cards]  # garde tout
    monkeypatch.setattr(web, "_filter_event_urls", fake_prefilter)
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/agenda/", "name": "a",
        "follow_event_links": True, "follow_scope": "domain",
        "prefilter_by_month": True,
    }]})
    list(conn.collect("2026-11"))
    assert captured["month"] == "2026-11"
    cards = dict(captured["cards"])
    assert "16 octobre 2026" in cards[giedre]              # carte datée transmise
    assert cards["https://site.fr/contact/"] == ""          # nav : pas de carte


def test_collect_follow_domain_fallback_index_when_prefilter_empty(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    index_html = _html_with_links(["/contact/", "/a-propos/"])
    monkeypatch.setattr(web, "_fetch", lambda url, needs_browser=False: index_html)
    monkeypatch.setattr(web, "_filter_event_urls", lambda cards, month: [])
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
                        lambda cards, m: ["https://site.fr/Agenda/Agenda-1281",
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
                        lambda cards, m: ["https://site.fr/Agenda/Agenda-1281",
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
                        lambda cards, m: ["https://site.fr/diphonie/", "https://site.fr/polyphonies/"])
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


# ---------- _extract_pagination_urls ----------

_PAGINATION_BASE = "https://site.fr/programme/"


def test_pagination_elementor_e_page_hash():
    from tapageur.connectors.web import _extract_pagination_urls
    html = '''
      <a class="page-numbers" href="https://site.fr/programme/?e-page-5e7f2769=2">2</a>
      <a class="page-numbers" href="https://site.fr/programme/?e-page-5e7f2769=3">3</a>
      <a class="page-numbers next" href="https://site.fr/programme/?e-page-5e7f2769=2">»</a>
    '''
    out = _extract_pagination_urls(html, _PAGINATION_BASE)
    assert out == [
        "https://site.fr/programme/?e-page-5e7f2769=2",
        "https://site.fr/programme/?e-page-5e7f2769=3",
    ]


def test_pagination_query_page_and_paged():
    from tapageur.connectors.web import _extract_pagination_urls
    html = '''<a href="/programme/?page=2">2</a>
              <a href="/programme/?paged=3">3</a>'''
    out = _extract_pagination_urls(html, _PAGINATION_BASE)
    assert out == ["https://site.fr/programme/?page=2",
                   "https://site.fr/programme/?paged=3"]


def test_pagination_path_segment():
    from tapageur.connectors.web import _extract_pagination_urls
    html = '<a href="/programme/page/2/">2</a><a href="/programme/page/3/">3</a>'
    out = _extract_pagination_urls(html, _PAGINATION_BASE)
    assert out == ["https://site.fr/programme/page/2/",
                   "https://site.fr/programme/page/3/"]


def test_pagination_rel_next_same_path_without_number():
    """rel=next sur le même chemin mais query non numérotable -> suivi quand même."""
    from tapageur.connectors.web import _extract_pagination_urls
    html = '<a rel="next" href="/programme/?after=abc123">suivant</a>'
    out = _extract_pagination_urls(html, _PAGINATION_BASE)
    assert out == ["https://site.fr/programme/?after=abc123"]


def test_pagination_excludes_page_one_and_non_page_query():
    from tapageur.connectors.web import _extract_pagination_urls
    html = '''<a href="/programme/?e-page-x=1">1</a>
              <a href="/programme/?lang=en">EN</a>
              <a href="/programme/?utm=foo">x</a>'''
    assert _extract_pagination_urls(html, _PAGINATION_BASE) == []


def test_pagination_ignores_event_pages_and_cross_domain():
    """Un lien d'event (autre chemin) ou cross-domain n'est pas une pagination."""
    from tapageur.connectors.web import _extract_pagination_urls
    html = '''<a href="/event/giedre/?page=2">event</a>
              <a href="https://evil.com/programme/?page=2">evil</a>'''
    assert _extract_pagination_urls(html, _PAGINATION_BASE) == []


def test_page_param_detects_markers():
    from tapageur.connectors.web import _page_param
    assert _page_param("e-page-5e7f2769=4") == 4
    assert _page_param("page=2") == 2
    assert _page_param("paged=3") == 3
    assert _page_param("lang=en") is None
    assert _page_param("") is None


# ---------- _collect_paginated_cards ----------

def test_collect_paginated_cards_unions_pages():
    """Page 1 -> events A + liens vers pages 2,3 ; pages 2,3 -> autres events."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    p1 = f'''
      <div><span>5 novembre 2026</span><a href="/event/a/">A</a></div>
      <a class="page-numbers" href="{base}?e-page-h=2">2</a>
      <a class="page-numbers" href="{base}?e-page-h=3">3</a>'''
    p2 = '<div><span>6 novembre 2026</span><a href="/event/b/">B</a></div>'
    p3 = '<div><span>7 novembre 2026</span><a href="/event/c/">C</a></div>'
    pages = {f"{base}?e-page-h=2": p2, f"{base}?e-page-h=3": p3}
    pairs = _collect_paginated_cards(p1, base, lambda u: pages[u], scope="domain")
    cards = dict(pairs)
    assert set(cards) == {"https://site.fr/event/a/", "https://site.fr/event/b/",
                          "https://site.fr/event/c/"}
    assert "5 novembre 2026" in cards["https://site.fr/event/a/"]
    assert "6 novembre 2026" in cards["https://site.fr/event/b/"]
    assert "7 novembre 2026" in cards["https://site.fr/event/c/"]


def test_collect_paginated_cards_dedups_repeated_events():
    """Un event présent sur 2 pages n'apparaît qu'une fois (1re occurrence)."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    p1 = f'''<div><span>5 novembre 2026</span><a href="/event/a/">A</a></div>
             <a class="page-numbers" href="{base}?page=2">2</a>'''
    p2 = '<div><span>5 novembre 2026</span><a href="/event/a/">A again</a></div>'
    pairs = _collect_paginated_cards(p1, base, lambda u: p2, scope="domain")
    assert [u for u, _ in pairs] == ["https://site.fr/event/a/"]


def test_collect_paginated_cards_next_only_crawl():
    """Site « next-only » : chaque page ne lie que la suivante -> crawl en chaîne."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    p1 = f'<a href="/event/a/">A</a><a class="next" href="{base}?paged=2">></a>'
    p2 = f'<a href="/event/b/">B</a><a class="next" href="{base}?paged=3">></a>'
    p3 = '<a href="/event/c/">C</a>'
    pages = {f"{base}?paged=2": p2, f"{base}?paged=3": p3}
    pairs = _collect_paginated_cards(p1, base, lambda u: pages[u], scope="domain")
    assert {u for u, _ in pairs} == {"https://site.fr/event/a/",
                                     "https://site.fr/event/b/",
                                     "https://site.fr/event/c/"}


def test_collect_paginated_cards_respects_cap():
    """Au plus max_pages pages visitées (page 1 incluse) -> fetchs bornés."""
    from tapageur.connectors.web import _collect_paginated_cards
    from urllib.parse import urlparse, parse_qs
    base = "https://site.fr/programme/"
    p1 = f'<a href="/event/e1/">E1</a><a class="next" href="{base}?paged=2">></a>'
    calls = {"n": 0}
    def counting_fetch(u):
        calls["n"] += 1
        n = int(parse_qs(urlparse(u).query)["paged"][0])
        return f'<a href="/event/e{n}/">E{n}</a><a class="next" href="{base}?paged={n+1}">></a>'
    pairs = _collect_paginated_cards(p1, base, counting_fetch, scope="domain", max_pages=3)
    assert calls["n"] == 2            # page 1 (déjà en main) + 2 fetchs = 3 pages
    assert len(pairs) == 3            # e1, e2, e3


def test_collect_paginated_cards_tolerates_fetch_error():
    """Un fetch de page paginée en erreur est ignoré ; les autres restent."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    p1 = f'''<a href="/event/a/">A</a>
             <a class="page-numbers" href="{base}?page=2">2</a>
             <a class="page-numbers" href="{base}?page=3">3</a>'''
    def fetch(u):
        if u.endswith("page=2"):
            raise RuntimeError("boom")
        return '<a href="/event/c/">C</a>'
    pairs = _collect_paginated_cards(p1, base, fetch, scope="domain")
    urls = {u for u, _ in pairs}
    assert "https://site.fr/event/a/" in urls   # page 1
    assert "https://site.fr/event/c/" in urls   # page 3 (page 2 en erreur, ignorée)


def test_collect_paginated_cards_no_pagination_single_page():
    """Site non paginé : aucune page supplémentaire fetchée."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    p1 = '<div><span>5 novembre 2026</span><a href="/event/a/">A</a></div>'
    calls = []
    pairs = _collect_paginated_cards(p1, base, lambda u: calls.append(u) or "", scope="domain")
    assert calls == []                                   # aucun fetch
    assert [u for u, _ in pairs] == ["https://site.fr/event/a/"]


# ---------- collect() : suivi de la pagination ----------

def test_collect_follows_pagination_unions_events(monkeypatch):
    """collect() en scope domaine suit la pagination et collecte les events des
    pages 2..N (fetch + pré-filtre mockés, pré-filtre garde tout)."""
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    base = "https://site.fr/programme/"
    p1 = (f'<div><span>5 nov 2026</span><a href="/event/a/">A</a></div>'
          f'<a class="page-numbers" href="{base}?e-page-h=2">2</a>')
    p2 = '<div><span>6 nov 2026</span><a href="/event/b/">B</a></div>'
    def fake_fetch(url, needs_browser=False):
        if url == base:
            return p1
        if url == f"{base}?e-page-h=2":
            return p2
        return "<p>Concert detail</p>"
    monkeypatch.setattr(web, "_fetch", fake_fetch)
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    monkeypatch.setattr(web, "_filter_event_urls", lambda cards, m: [u for u, _ in cards])
    conn = web.WebConnector({"websites": [{
        "url": base, "name": "s", "follow_event_links": True,
        "follow_scope": "domain", "prefilter_by_month": False,
    }]})
    refs = {it.source_ref for it in conn.collect("2026-11")}
    assert "https://site.fr/event/a/" in refs
    assert "https://site.fr/event/b/" in refs   # page 2 suivie


def test_collect_paginate_false_single_page(monkeypatch):
    """paginate:false -> page 1 seule (pas de suivi des liens de pagination)."""
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    base = "https://site.fr/programme/"
    p1 = (f'<div><span>5 nov 2026</span><a href="/event/a/">A</a></div>'
          f'<a class="page-numbers" href="{base}?e-page-h=2">2</a>')
    fetched = []
    def fake_fetch(url, needs_browser=False):
        fetched.append(url)
        return p1 if url == base else "<p>detail</p>"
    monkeypatch.setattr(web, "_fetch", fake_fetch)
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    monkeypatch.setattr(web, "_filter_event_urls", lambda cards, m: [u for u, _ in cards])
    conn = web.WebConnector({"websites": [{
        "url": base, "name": "s", "follow_event_links": True,
        "follow_scope": "domain", "prefilter_by_month": False, "paginate": False,
    }]})
    refs = {it.source_ref for it in conn.collect("2026-11")}
    assert refs == {"https://site.fr/event/a/"}
    assert f"{base}?e-page-h=2" not in fetched   # page 2 jamais fetchée


def test_collect_prefilter_receives_cards_from_all_pages(monkeypatch):
    """Le pré-filtre reçoit les cartes (datées) des events de TOUTES les pages."""
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    base = "https://site.fr/programme/"
    p1 = (f'<div><span>16 octobre 2026</span><a href="/event/a/">A</a></div>'
          f'<a class="page-numbers" href="{base}?e-page-h=2">2</a>')
    p2 = '<div><span>6 novembre 2026</span><a href="/event/b/">B</a></div>'
    def fake_fetch(url, needs_browser=False):
        if url == base:
            return p1
        if url == f"{base}?e-page-h=2":
            return p2
        return "<p>detail</p>"
    monkeypatch.setattr(web, "_fetch", fake_fetch)
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    captured = {}
    def fake_prefilter(cards, month):
        captured["cards"] = dict(cards)
        return [u for u, _ in cards]
    monkeypatch.setattr(web, "_filter_event_urls", fake_prefilter)
    conn = web.WebConnector({"websites": [{
        "url": base, "name": "s", "follow_event_links": True,
        "follow_scope": "domain", "prefilter_by_month": True,
    }]})
    list(conn.collect("2026-11"))
    assert "16 octobre 2026" in captured["cards"]["https://site.fr/event/a/"]
    assert "6 novembre 2026" in captured["cards"]["https://site.fr/event/b/"]  # page 2


# ---------- Régression : vraie page léolienne (pagination Elementor) ----------

_LEO_PROG_FIXTURE = Path(__file__).parent / "fixtures" / "leolienne_programme_page1.html"
_LEO_PROG_URL = "https://leoliennearnage.fr/programme-concerts-spectacles/"


def test_leolienne_real_page1_pagination_detected():
    """Sur la vraie page 1 léolienne (markup Elementor `page-numbers`), les 3
    pages suivantes (?e-page-5e7f2769=2/3/4) sont détectées — ni plus, ni moins."""
    from tapageur.connectors.web import _extract_pagination_urls
    html = _LEO_PROG_FIXTURE.read_text(encoding="utf-8")
    out = _extract_pagination_urls(html, _LEO_PROG_URL)
    assert out == [
        f"{_LEO_PROG_URL}?e-page-5e7f2769=2",
        f"{_LEO_PROG_URL}?e-page-5e7f2769=3",
        f"{_LEO_PROG_URL}?e-page-5e7f2769=4",
    ]


# ---------- _clean_query : blocklist tracking + pagination ----------

def test_clean_query_strips_tracking():
    """Les params de tracking (utm_*, fbclid, gclid, gad*, mc_*, ref) sont retirés."""
    from tapageur.connectors.web import _clean_query
    assert _clean_query("utm_source=newsletter&utm_medium=email") == ""
    assert _clean_query("fbclid=abc") == ""
    assert _clean_query("gclid=xyz&gad_source=1") == ""
    assert _clean_query("mc_cid=123&ref=partner") == ""


def test_clean_query_strips_pagination():
    """Les params de pagination (page/paged/e-page*) ne sont pas des events → retirés."""
    from tapageur.connectors.web import _clean_query
    assert _clean_query("page=2") == ""
    assert _clean_query("paged=3") == ""
    assert _clean_query("e-page-5e7f2769=2") == ""


def test_clean_query_keeps_meaningful_params():
    """Les autres params (signifiants par défaut) sont préservés."""
    from tapageur.connectors.web import _clean_query
    assert _clean_query("saison_culturelle=bel-ami") == "saison_culturelle=bel-ami"
    assert _clean_query("event=concert") == "event=concert"
    assert _clean_query("p=42") == "p=42"


def test_clean_query_mixed_keeps_only_meaningful():
    """Query mixte tracking+signifiant : seul le signifiant survit."""
    from tapageur.connectors.web import _clean_query
    assert _clean_query("saison_culturelle=lumiere&utm_source=fb&fbclid=z") == \
        "saison_culturelle=lumiere"


def test_clean_query_sorts_for_stable_dedup():
    """Les clés sont triées → ?a=1&b=2 et ?b=2&a=1 canonisent pareil."""
    from tapageur.connectors.web import _clean_query
    assert _clean_query("b=2&a=1") == _clean_query("a=1&b=2") == "a=1&b=2"


def test_clean_query_empty_and_tracking_only():
    """Query vide ou 100% tracking → chaîne vide (canonical = chemin nu)."""
    from tapageur.connectors.web import _clean_query
    assert _clean_query("") == ""
    assert _clean_query("utm_campaign=x&fbclid=y") == ""


# ---------- _extract_subpages : events en paramètre de requête ----------

def test_extract_subpages_keeps_distinct_query_events():
    """Des events sur le MÊME chemin (racine) distingués par un query param
    signifiant ressortent DISTINCTS (cas WordPress ?saison_culturelle=<slug>)."""
    from tapageur.connectors.web import _extract_subpages
    html = '''
      <a href="/?saison_culturelle=bel-ami">Bel Ami</a>
      <a href="/?saison_culturelle=lumiere">Lumière</a>
      <a href="/?saison_culturelle=modulus">Modulus</a>
    '''
    base = "https://site.fr/culture/centre-culturel/"
    subs = _extract_subpages(html, base_url=base, scope="domain")
    assert "https://site.fr/?saison_culturelle=bel-ami" in subs
    assert "https://site.fr/?saison_culturelle=lumiere" in subs
    assert "https://site.fr/?saison_culturelle=modulus" in subs
    assert len([u for u in subs if "saison_culturelle" in u]) == 3


def test_extract_subpages_merges_tracking_variants():
    """Deux liens même chemin ne différant que par du tracking fusionnent."""
    from tapageur.connectors.web import _extract_subpages
    html = '''
      <a href="/agenda/concert">clean</a>
      <a href="/agenda/concert?utm_source=fb">tracked</a>
      <a href="/agenda/concert?fbclid=xyz">tracked2</a>
    '''
    subs = _extract_subpages(html, base_url="https://site.fr/agenda")
    assert subs == ["https://site.fr/agenda/concert"]


def test_extract_subpages_pagination_param_not_an_event():
    """Un lien distingué seulement par un param de pagination n'est pas un event
    distinct (il retombe sur son chemin nu, pas N candidats fantômes)."""
    from tapageur.connectors.web import _extract_subpages
    html = '''
      <a href="/agenda/concert">event</a>
      <a href="/agenda/concert?page=2">pagination-like</a>
      <a href="/agenda/concert?e-page-abc=3">pagination-like2</a>
    '''
    subs = _extract_subpages(html, base_url="https://site.fr/agenda")
    assert subs == ["https://site.fr/agenda/concert"]


def test_canonical_url_cleans_query():
    """_canonical_url préserve les params signifiants, strippe tracking/pagination."""
    from tapageur.connectors.web import _canonical_url
    base = "https://site.fr/agenda/"
    assert _canonical_url(base, "/?saison_culturelle=bel-ami") == \
        "https://site.fr/?saison_culturelle=bel-ami"
    assert _canonical_url(base, "/x/?utm_source=fb") == "https://site.fr/x/"
    assert _canonical_url(base, "/x/?page=2") == "https://site.fr/x/"


def test_extract_subpages_query_event_card_matches():
    """La carte d'un event query-param est bien retrouvée (même canonical entre
    _extract_subpages et _extract_card_snippets)."""
    from tapageur.connectors.web import _extract_subpages, _extract_card_snippets
    html = ('<article>'
            '<span>16 octobre 2026 - 20h00</span>'
            '<a href="/?saison_culturelle=lumiere">Lumière</a>'
            '</article>')
    base = "https://site.fr/culture/centre-culturel/"
    subs = _extract_subpages(html, base_url=base, scope="domain")
    cards = dict(_extract_card_snippets(html, base, subs))
    url = next(u for u in subs if "lumiere" in u)
    assert "16 octobre 2026" in cards[url]
