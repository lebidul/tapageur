"""
Connecteur web : fetch chaque URL configurée et yield le texte brut.

Stratégie trois niveaux :
- Page agenda (index) : parsée juste pour extraire les liens vers les pages
  event individuelles (sous-chemins stricts de l'URL d'agenda).
- Pré-filtrage Claude : sur la liste candidate (souvent ~30-50 URLs sur 6
  mois), demande à Claude lesquelles correspondent à des events DU MOIS
  CIBLE depuis le texte d'agenda. Économise ~80% des fetch détail et
  autant de calls Claude downstream. Désactivable avec
  `prefilter_by_month: false` ou si `ANTHROPIC_API_KEY` absente.
- Pages event retenues : 1 CollectedItem par page (raw text dump). Claude
  extrait au moment de la normalisation. Pas de selector content-spécifique.

Beaucoup de sites n'affichent les horaires/prix que sur les pages détaillées,
pas sur l'agenda d'aperçu — d'où le suivi des liens.

Désactivable par site avec `follow_event_links: false` dans la config.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Iterator
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from tapageur.connectors.base import Connector, register
from tapageur.schema import CollectedItem


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# Sonnet 4.5 : router URL→mois est une tâche simple sur du texte d'agenda
# court (quelques KB). Pas besoin d'Opus ici, ×5 moins cher.
PREFILTER_MODEL = "claude-sonnet-4-5"
PREFILTER_SYSTEM = """\
Tu es un router d'URLs. On te donne une liste de liens candidats d'un site, et pour \
chaque lien le texte de sa CARTE d'agenda (le petit bloc qui l'entoure sur la page \
liste, souvent avec une date). Certaines cartes sont vides (date/texte uniquement sur \
la page détail).

Retourne UNIQUEMENT les URLs qui pointent vers une PAGE D'ÉVÉNEMENT (concert, \
spectacle, date programmée), et PAS vers une page de menu/navigation (accueil, \
à-propos, contact, mentions légales, presse, cours, stages génériques…).

Si une ligne "Mois cible : YYYY-MM" est fournie, applique EN PLUS ce filtre par date. \
La cible porte un MOIS (MM) ET une ANNÉE (YYYY) : compare TOUJOURS les deux.
- Si la carte du lien porte une date LISIBLE dont le MOIS **et** l'ANNÉE correspondent \
à la cible → garder.
- Si la carte porte une date lisible dont le mois OU l'année diffère clairement de la \
cible → EXCLURE l'URL. ATTENTION : un même nom de mois peut revenir sur plusieurs \
années (un site liste parfois plusieurs saisons / archives sur la même page). Une \
carte « 30 novembre 2024 » est HORS cible pour « 2026-11 » MALGRÉ le mois identique : \
exclus-la. Ne te fie jamais au seul nom du mois : l'année doit aussi coller.
- Si la carte N'A PAS de date lisible (vide, ou aucune date exploitable) → INCLURE : \
la date est peut-être seulement sur la page détail. NE JAMAIS exclure un event faute \
de date. Mieux vaut un fetch inutile qu'un event raté.
- Si la carte porte un jour et un mois mais AUCUNE année lisible → INCLURE (année \
indéterminée, on ne tranche pas sur l'année ; applique seulement le filtre mois).

Heuristiques :
- Le slug d'URL contient souvent le nom de l'artiste/spectacle.
- Une date en toutes lettres (« 16 octobre 2026 ») se mappe sur YYYY-MM = 2026-10.
- En cas d'INCERTITUDE sur la nature event/nav, ou sur le mois quand l'année est bien \
dans la cible : INCLURE l'URL.

Réponds UNIQUEMENT par un JSON valide :
{"urls": ["...", "..."]}

- AUCUN texte avant ou après.
- PAS de markdown.
- Liste vide si aucune URL ne correspond."""


@register
class WebConnector(Connector):
    name = "web"

    def collect(self, month: str, progress=None) -> Iterator[CollectedItem]:
        for site in self.config.get("websites", []):
            url = site["url"]
            site_name = site.get("name", url)
            # Label compact pour le log live : le nom configuré, sinon l'hôte de
            # l'URL (en GUI, site_name == url → on affiche l'hôte).
            src_label = site_name if site_name != url else (urlparse(url).netloc or url)
            needs_browser = site.get("needs_browser", False)
            follow = site.get("follow_event_links", True)
            # mode : flag opt-in propagé jusqu'à normalize via raw_metadata.
            # Valeur supportée pour l'instant : "festival_onliner" (cf. commit
            # festival mode). Absent ou autre = mode classique.
            mode = site.get("mode")
            # model_override : surcharge MODEL_BY_KIND pour ce site spécifique.
            # Utile quand le modèle par défaut (Sonnet pour web) est instable
            # sur un contenu particulier (ex: bonnzik → Opus pour formats
            # date/artiste imbriqués).
            model_override = site.get("model")
            # follow_scope : "subpath" (défaut, rétro-compat) restreint aux
            # sous-chemins stricts de l'agenda ; "domain" découvre les liens
            # frères même-hôte (sites sans sous-arborescence agenda dédiée).
            follow_scope = site.get("follow_scope", "subpath")
            # overrides : lieu/asso saisis par URL dans l'UI (cf. _url_to_site).
            # Propagés dans raw_metadata de chaque item ; appliqués en aval par
            # normalize uniquement si l'event extrait n'a pas déjà l'info.
            overrides = {k: site[k] for k in ("default_venue", "default_festival") if site.get(k)}

            # Détection PDF distant : extension d'URL ou Content-Type via HEAD.
            # Route vers le parsing pdfplumber au lieu du fetch HTML.
            if _is_pdf_url(url):
                try:
                    item = _fetch_pdf_url(url, site_name)
                    if mode:
                        item.raw_metadata["mode"] = mode
                    if model_override:
                        item.raw_metadata["model_override"] = model_override
                    item.raw_metadata.update(overrides)
                    yield item
                except Exception as e:
                    print(f"[web] {site_name}: PDF fetch error: {e}")
                continue

            try:
                html = _fetch(url, needs_browser=needs_browser)
            except Exception as e:
                print(f"[web] {site_name}: {e}")
                continue

            if not follow:
                # Mode mono-page : dump l'agenda lui-même
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
                yield _web_item(url, text, site_name, mode, model_override, extra_meta=overrides)
                continue

            # Mode follow : parcours les pages event individuelles.
            # event_link_pattern (regex) optionnel pour les sites à structure
            # non-standard (ex: msj.world/ofcourselemans/86 → pages event sous
            # /ofcourselemans/card/<slug>, pas sous /ofcourselemans/86/<slug>).
            event_pattern = site.get("event_link_pattern")
            # paginate (défaut True) : suit les pages 2..N de l'agenda et unit la
            # découverte des events. No-op sur un site non paginé (0 lien trouvé)
            # → aucune régression sur les sites mono-page.
            if site.get("paginate", True):
                cards_pairs = _collect_paginated_cards(
                    html, url, lambda u: _fetch(u, needs_browser=needs_browser),
                    pattern=event_pattern, scope=follow_scope)
            else:
                urls0 = _extract_subpages(html, base_url=url, pattern=event_pattern, scope=follow_scope)
                cards_pairs = _extract_card_snippets(html, url, urls0)
            event_urls = [u for u, _ in cards_pairs]
            agenda_text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            print(f"[web] {site_name}: {len(event_urls)} URLs candidates (scope={follow_scope})")

            prefilter_by_month = site.get("prefilter_by_month", True)
            has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
            run_prefilter = bool(event_urls) and has_key and (prefilter_by_month or follow_scope == "domain")

            if run_prefilter:
                pf_month = month if prefilter_by_month else None
                # Approche A (#12) : paires (URL, texte de carte avec date) au
                # lieu du blob d'agenda à plat → le modèle relie slug ↔ date et
                # peut écarter les hors-mois avant le fetch.
                # Cartes déjà extraites page par page (toutes les pages d'agenda),
                # dates des events des pages 2..N incluses.
                cards = cards_pairs
                try:
                    kept = _filter_event_urls(cards, pf_month)
                    print(f"[web]   {len(kept)}/{len(event_urls)} retenues")
                    event_urls = kept
                except Exception as e:
                    print(f"[web]   prefilter échoué ({e})")
                    if follow_scope == "domain":
                        yield _web_item(url, agenda_text, site_name, mode, model_override, extra_meta=overrides)
                        continue
                    # scope subpath : comportement historique = fetch all
                if follow_scope == "domain" and not event_urls:
                    print(f"[web]   0 event retenu → fallback page d'index")
                    yield _web_item(url, agenda_text, site_name, mode, model_override, extra_meta=overrides)
                    continue
            elif follow_scope == "domain":
                # pré-filtre impossible (pas de clé / 0 candidat) : ne pas fetcher
                # tout le domaine → fallback page d'index.
                print(f"[web]   pré-filtre indisponible en scope domaine → fallback index")
                yield _web_item(url, agenda_text, site_name, mode, model_override, extra_meta=overrides)
                continue

            if progress:
                progress(f"{src_label} : {len(event_urls)} pages à récupérer")

            usable_items: list[CollectedItem] = []
            n_error = 0
            for i, ev_url in enumerate(event_urls, 1):
                if progress:
                    slug = [s for s in ev_url.rstrip("/").split("/") if s][-1]
                    progress(f"{src_label} — Page {i}/{len(event_urls)} : {slug}")
                try:
                    ev_html = _fetch(ev_url, needs_browser=needs_browser)
                except Exception as e:
                    print(f"[web]   {ev_url}: {e}")
                    continue
                ev_text = BeautifulSoup(ev_html, "html.parser").get_text("\n", strip=True)
                # Soft-404 : page d'erreur servie en 200 → l'ignorer (elle ne
                # donnerait que 0 event, et risquerait une confabulation).
                if _is_error_page(ev_text):
                    n_error += 1
                    print(f"[web]   {ev_url}: page d'erreur (soft-404), ignorée")
                    continue
                usable_items.append(_web_item(
                    ev_url, ev_text, site_name, mode, model_override,
                    extra_meta={**overrides, "agenda_url": url}))

            if usable_items:
                yield from usable_items
            else:
                # Aucune page suivie exploitable (toutes en soft-404 ou fetch KO)
                # alors qu'on avait des candidats : l'agenda est probablement
                # auto-suffisant (programme inline). Repli : normaliser l'index
                # au lieu de tout perdre.
                print(f"[web]   0 page suivie exploitable ({n_error} erreur·s) → "
                      f"repli sur l'index")
                yield _web_item(url, agenda_text, site_name, mode, model_override,
                                extra_meta=overrides)


# Marqueurs de « soft-404 » : page détail renvoyée en HTTP 200 mais dont le
# corps est en réalité une page d'erreur (fréquent sur les sites PHP/CMS où le
# contenu détail est injecté en JS — un GET direct retombe sur un gabarit 404).
# Sans ça, raise_for_status() ne les écarte pas et le modèle en sort 0 event,
# tandis que l'agenda index (souvent auto-suffisant) n'est jamais normalisé.
_ERROR_PAGE_MARKERS = (
    "erreur 404",
    "page introuvable",
    "page n'a pas été trouvée",
    "page not found",
    "404 not found",
    "error 404",
)


def _is_error_page(text: str) -> bool:
    """True si le texte extrait ressemble à une page d'erreur / 404 (soft-404)."""
    low = text.lower()
    return any(m in low for m in _ERROR_PAGE_MARKERS)


def _web_item(url: str, text: str, site_name: str,
              mode: str | None, model_override: str | None,
              extra_meta: dict | None = None) -> CollectedItem:
    """Construit un CollectedItem web (texte d'une page), métadonnées propagées."""
    meta = {"site": site_name}
    if extra_meta:
        meta.update(extra_meta)
    if mode:
        meta["mode"] = mode
    if model_override:
        meta["model_override"] = model_override
    return CollectedItem(
        source_kind="web",
        source_ref=url,
        fetched_at=datetime.utcnow().isoformat() + "Z",
        raw_text=text,
        raw_metadata=meta,
    )


def _filter_event_urls(
    cards: list[tuple[str, str]],
    month: str | None,
) -> list[str]:
    """Pré-filtrage Claude : quels liens candidats sont des pages d'événement
    (optionnellement dans `month` = 'YYYY-MM').

    `cards` : paires (URL, texte de la carte d'agenda). La carte porte souvent la
    date de l'event (approche A, TODO #12) ; elle peut être vide quand la date
    n'est visible que sur la page détail — dans ce cas, « en doute, inclure ».

    Retourne un sous-ensemble strict des URLs de `cards` (sanity check Python).
    En cas d'erreur API/parse, lève l'exception : le caller décide du fallback."""
    from anthropic import Anthropic

    from tapageur.normalize import _extract_json

    client = Anthropic()
    header = f"Mois cible : {month}\n\n" if month else ""
    no_date = "(aucune date lisible sur l'agenda)"
    lines = []
    for i, (url, snippet) in enumerate(cards, 1):
        card = snippet.strip() if snippet else ""
        lines.append(f"[{i}] {url}\n    carte: {card or no_date}")
    user = (
        header
        + f"=== Liens candidats ({len(cards)}) ===\n"
        + "\n".join(lines)
    )
    response = client.messages.create(
        model=PREFILTER_MODEL,
        max_tokens=4000,
        system=PREFILTER_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise ValueError("réponse Claude sans bloc text")

    raw = _extract_json(text)
    data = json.loads(raw)
    candidates = data.get("urls", [])
    if not isinstance(candidates, list):
        raise ValueError(f"format inattendu : urls={candidates!r}")

    # Sanity : ne garde que les URLs réellement présentes dans l'input
    # (évite les hallucinations / typos qui mèneraient à un 404).
    valid = {u for u, _ in cards}
    return [u for u in candidates if u in valid]


# Date FR sur une carte d'agenda : « 16 octobre 2026 » / « 6 nov » (jour + mois
# en toutes lettres, accents tolérés) ou forme numérique « jj/mm[/aaaa] ». Sert
# UNIQUEMENT à localiser la carte (plus petit ancêtre daté) ; c'est le modèle
# qui lit ensuite la date réelle.
_FR_DATE = re.compile(
    r"\b\d{1,2}\s*(?:er\s+)?"
    r"(?:janv|févr|fevr|mars|avr|mai|juin|juil|ao[ûu]t|sept|oct|nov|déc|dec)"
    r"[a-zéèûô.]*\b"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    re.IGNORECASE,
)


# --- Canonisation query-aware (découverte d'events en paramètre de requête) ---
#
# Certains sites (WordPress custom post type sans permaliens jolis, ex.
# la-ferte-bernard `/?saison_culturelle=<slug>`) identifient CHAQUE event par un
# paramètre de requête sur un même chemin (souvent la racine `/`). Stripper toute
# la query ferait s'effondrer ces events sur une URL unique. On canonise donc en
# PRÉSERVANT la query, après avoir retiré par BLOCKLIST : (1) le tracking (jamais
# distinctif d'un event) et (2) la pagination (déjà gérée en amont par
# `_extract_pagination_urls` — ne pas la re-découvrir comme des events). Tout le
# reste est « signifiant » par défaut (approche générique, pas d'allowlist par
# site) ; le bruit résiduel est trié en aval par le pré-filtre mois.

# Paramètres de tracking exacts à stripper (comparaison en minuscules).
_TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "gclsrc", "dclid", "gbraid", "wbraid",
    "msclkid", "_gl", "igshid", "yclid", "ref", "ref_src", "spm",
})
# Préfixes de tracking (famille entière : utm_source, utm_medium, gad_source,
# mc_cid, mc_eid…).
_TRACKING_PREFIXES = ("utm_", "gad", "mc_")


def _is_pagination_key(key: str) -> bool:
    """Vrai si la clé de query est un marqueur de pagination (`page`, `paged`, ou
    préfixe `e-page` — Elementor / WP Grid Builder nomme la sienne
    `e-page-<hash>`). Ces pages sont gérées par `_extract_pagination_urls` ; on ne
    les prend pas pour des events dans la découverte d'URL."""
    k = key.lower()
    return k in ("page", "paged") or k.startswith("e-page")


def _is_tracking_key(key: str) -> bool:
    """Vrai si la clé de query est un paramètre de tracking à stripper."""
    k = key.lower()
    return k in _TRACKING_PARAMS or k.startswith(_TRACKING_PREFIXES)


def _clean_query(query: str) -> str:
    """Query canonique : retire tracking + pagination, garde le reste, trie.

    Le tri (par clé puis valeur) rend la déduplication stable
    (`?a=1&b=2` == `?b=2&a=1`). Retourne `""` s'il ne reste rien de signifiant
    (→ canonical = chemin nu, comme le comportement historique)."""
    from urllib.parse import parse_qsl, urlencode
    kept = [
        (k, v) for k, v in parse_qsl(query, keep_blank_values=True)
        if not _is_tracking_key(k) and not _is_pagination_key(k)
    ]
    kept.sort()
    return urlencode(kept)


def _canonical_url(base_url: str, href: str) -> str:
    """URL canonique (scheme://host/path[?query_signifiante]), identique à la
    forme produite par _extract_subpages — pour matcher ses sorties. La query est
    nettoyée (tracking + pagination retirés) via `_clean_query`."""
    p = urlparse(urljoin(base_url, href))
    clean = _clean_query(p.query)
    return f"{p.scheme}://{p.netloc}{p.path}" + (f"?{clean}" if clean else "")


def _extract_card_snippets(
    html: str,
    base_url: str,
    urls: list[str],
    max_len: int = 300,
) -> list[tuple[str, str]]:
    """Pour chaque URL de `urls`, texte de sa CARTE d'agenda (approche A, #12).

    La carte = plus petit ancêtre du `<a>` qui (1) contient une date FR ET (2)
    n'enveloppe aucun AUTRE lien candidat (sinon c'est le conteneur de liste,
    pas une carte). Aucune carte qualifiante → `""` (date pas sur l'agenda →
    le pré-filtre inclura par prudence). Ordre de sortie = ordre de `urls`."""
    target = set(urls)
    soup = BeautifulSoup(html, "html.parser")

    # Map URL canonique -> premier <a> qui la cible.
    anchor_by_url: dict[str, object] = {}
    for a in soup.find_all("a", href=True):
        canon = _canonical_url(base_url, a["href"])
        if canon in target and canon not in anchor_by_url:
            anchor_by_url[canon] = a

    def _candidate_links_in(node) -> int:
        # URLs candidates DISTINCTES (une carte a souvent plusieurs <a> vers le
        # même event : image + titre + bouton → ne compter qu'une fois).
        return len({
            _canonical_url(base_url, a["href"])
            for a in node.find_all("a", href=True)
            if _canonical_url(base_url, a["href"]) in target
        })

    out: list[tuple[str, str]] = []
    for url in urls:
        anchor = anchor_by_url.get(url)
        snippet = ""
        if anchor is not None:
            node = anchor
            for _ in range(10):  # garde-fou : ne pas remonter indéfiniment
                node = node.parent
                if node is None:
                    break
                text = node.get_text(" ", strip=True)
                if _FR_DATE.search(text) and _candidate_links_in(node) <= 1:
                    snippet = text[:max_len]
                    break
        out.append((url, snippet))
    return out


# Pages de taxonomie / filtre (catégorie, tag, commune, type…) : ce ne sont pas
# des pages d'event, et elles polluent le comptage des liens par carte (→ cartes
# faussement rejetées par _extract_card_snippets, dates non lues avant fetch).
_TAXONOMY = re.compile(
    r"/(categorie|categories|category|categories|cat|tag|tags|type|types"
    r"|rubrique|rubriques|theme|themes|commune|communes|lieu|lieux|ville|villes)/",
    re.IGNORECASE,
)


def _extract_subpages(html: str, base_url: str, pattern: str | None = None, scope: str = "subpath") -> list[str]:
    """Liens vers les pages event détaillées d'un site agenda.

    Mode par défaut (pattern=None) : heuristique générique, on garde les liens
    dont l'URL est un sous-chemin strict de base_url (`/<agenda_path>/<slug>`).
    Convient à 80% des sites (Superforma, Le Plongeoir, etc.).

    Mode pattern (pattern fourni) : regex appliquée sur l'URL complète. Permet
    de cibler les sites à structure non-standard où les pages event sont
    cousines plutôt qu'enfants. Ex: msj.world/ofcourselemans/86 → events sous
    msj.world/ofcourselemans/card/<slug> ; pattern :
    "https://msj\\.world/ofcourselemans/card/.+"

    Dans les 2 modes : exclut ancres, query strings (déduplique sur path),
    URLs cross-domaine.
    """
    import re

    base = urlparse(base_url.rstrip("/"))
    base_path = base.path.rstrip("/")
    compiled_pattern = re.compile(pattern) if pattern else None

    soup = BeautifulSoup(html, "html.parser")
    out: set[str] = set()
    for a in soup.find_all("a", href=True):
        full = urljoin(base_url, a["href"])
        p = urlparse(full)
        path = p.path.rstrip("/")

        # Mode pattern : on saute l'heuristique standard et on filtre par regex.
        # On garde quand même la contrainte cross-domaine (sécurité).
        if compiled_pattern is not None:
            if p.netloc != base.netloc:
                continue
            # Test sur l'URL canonisée (sans fragment/query) pour cohérence.
            canonical = f"{p.scheme}://{p.netloc}{p.path}"
            if not compiled_pattern.match(canonical):
                continue
            out.add(canonical)
            continue

        # Heuristique par défaut : sous-chemin strict de base_path.
        if p.netloc != base.netloc:
            continue
        if p.scheme not in ("http", "https"):
            continue
        if path == base_path:
            continue  # la page agenda elle-même
        if scope == "subpath" and not path.startswith(base_path + "/"):
            continue
        if _TAXONOMY.search(p.path):
            continue  # page de catégorie/tag/commune… (pas un event)
        clean = f"{p.scheme}://{p.netloc}{p.path}"
        out.add(clean)
    return sorted(out)


# Nombre max de pages d'agenda visitées (page 1 incluse) : garde-fou
# anti-emballement sur les paginations longues ou circulaires.
_MAX_AGENDA_PAGES = 10

# Segment de pagination « /page/N/ » (WordPress et consorts).
_PAGE_SEGMENT = re.compile(r"/page/(\d+)/?$")


def _page_param(query: str) -> int | None:
    """N de page depuis une query string si elle porte un marqueur de pagination
    (clé 'page', 'paged', ou clé commençant par 'e-page' — Elementor / WP Grid
    Builder nomme la sienne 'e-page-<hash>'). Sinon None."""
    from urllib.parse import parse_qs
    for key, vals in parse_qs(query).items():
        if _is_pagination_key(key):
            for v in vals:
                if v.isdigit():
                    return int(v)
    return None


def _extract_pagination_urls(html: str, base_url: str) -> list[str]:
    """Liens vers les AUTRES pages du même agenda paginé trouvés dans `html`.

    Un lien est une pagination s'il reste sur le MÊME chemin que l'agenda et
    porte un marqueur de page : query `?page=N`/`?paged=N`/`?e-page*=N`, segment
    `/page/N/`, ou attribut `rel="next"` / classe `…next` (même chemin). N >= 2
    (la page 1 est exclue). Retourne des URLs canoniques (query préservée pour
    les formes query ; chemin `/page/N/` sinon), ordonnées par N croissant, puis
    les cibles « next » sans N numérique. Une page d'event (chemin différent) ou
    cross-domaine n'est jamais prise pour une pagination."""
    base = urlparse(base_url)
    base_path = base.path.rstrip("/")
    soup = BeautifulSoup(html, "html.parser")

    numbered: dict[int, str] = {}
    extra: list[str] = []  # cibles « next » sans N exploitable (sites next-only)
    seen_extra: set[str] = set()

    for tag in soup.find_all(["a", "link"], href=True):
        p = urlparse(urljoin(base_url, tag["href"]))
        if p.netloc != base.netloc or p.scheme not in ("http", "https"):
            continue
        path = p.path.rstrip("/")

        # Forme segment « /page/N/ » (le préfixe doit être le chemin de l'agenda).
        m = _PAGE_SEGMENT.search(p.path)
        if m and path[: m.start()].rstrip("/") == base_path:
            n = int(m.group(1))
            if n >= 2:
                numbered.setdefault(n, f"{p.scheme}://{p.netloc}{p.path}")
            continue

        if path != base_path:
            continue  # pas le chemin de l'agenda → pas une pagination

        # Forme query numérotée.
        if p.query:
            n = _page_param(p.query)
            if n is not None and n >= 2:
                numbered.setdefault(n, f"{p.scheme}://{p.netloc}{p.path}?{p.query}")
                continue

        # rel="next" / classe …next sur le même chemin, sans N exploitable.
        rel = [r.lower() for r in (tag.get("rel") or [])]
        cls = [c.lower() for c in (tag.get("class") or [])]
        is_next = "next" in rel or any("next" in c for c in cls)
        if is_next and p.query:
            u = f"{p.scheme}://{p.netloc}{p.path}?{p.query}"
            if u not in seen_extra:
                seen_extra.add(u)
                extra.append(u)

    out = [numbered[n] for n in sorted(numbered)]
    for u in extra:
        if u not in out:
            out.append(u)
    return out


def _page_key(url: str) -> tuple[str, str, str]:
    """Clé de dédup d'une page d'agenda (host, path sans slash final, query)."""
    p = urlparse(url)
    return (p.netloc, p.path.rstrip("/"), p.query)


def _collect_paginated_cards(
    first_html: str,
    base_url: str,
    fetch,
    pattern: str | None = None,
    scope: str = "subpath",
    max_pages: int = _MAX_AGENDA_PAGES,
) -> list[tuple[str, str]]:
    """Union des paires (URL d'event, texte de carte) sur toutes les pages d'un
    agenda paginé (page 1 + pages 2..N découvertes via `_extract_pagination_urls`).

    `fetch(url) -> html` est injecté (testable ; en prod `lambda u: _fetch(u,
    needs_browser=...)`). Crawl borné : chaque page visitée au plus une fois, au
    plus `max_pages` pages au total (donc <= max_pages-1 fetchs en plus de la
    page 1 déjà en main). Chaque page passe par `_extract_subpages` puis
    `_extract_card_snippets` — les cartes des pages 2..N portent LEUR date, ce que
    le pré-filtre mois exploite. Dédoublonne par URL (1re occurrence gagne, ordre
    de découverte préservé). Un fetch de page en erreur est loggé et ignoré."""
    pairs: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    def _ingest(html: str) -> None:
        urls = _extract_subpages(html, base_url, pattern=pattern, scope=scope)
        for u, snip in _extract_card_snippets(html, base_url, urls):
            if u not in seen_urls:
                seen_urls.add(u)
                pairs.append((u, snip))

    visited: set[tuple[str, str, str]] = {_page_key(base_url)}
    pending: list[str] = []

    def _enqueue(html: str) -> None:
        for pu in _extract_pagination_urls(html, base_url):
            k = _page_key(pu)
            if k not in visited:
                visited.add(k)
                pending.append(pu)

    _ingest(first_html)
    _enqueue(first_html)

    n_fetched = 0
    while pending and n_fetched < max_pages - 1:
        pu = pending.pop(0)
        try:
            phtml = fetch(pu)
        except Exception as e:
            print(f"[web]   pagination {pu}: {e}")
            continue
        n_fetched += 1
        _ingest(phtml)
        _enqueue(phtml)

    return pairs


# Cache HTTP in-process pour éviter de re-fetcher la même URL entre 2 mois
# cibles (cas du `collect --month 07 --month 08`). Vidé manuellement entre
# runs si besoin via clear_fetch_cache(). Pas de TTL : valide tant que le
# processus tourne (chaque CLI invocation = 1 process).
_FETCH_CACHE: dict[str, str] = {}


# Hook optionnel : le GUI l'installe pour récupérer les pages via le navigateur
# embarqué (WebView2) au lieu de Playwright. None = comportement CLI (Playwright).
_BROWSER_FETCH = None  # type: "Callable[[str], str] | None"


def clear_fetch_cache() -> None:
    """Vide le cache HTTP. Utile pour les tests ou un re-fetch forcé."""
    _FETCH_CACHE.clear()


def _fetch(url: str, needs_browser: bool = False) -> str:
    """Fetch HTML : requests pour le simple, Playwright pour les sites bloqués.

    Mode Playwright :
    - `wait_until="domcontentloaded"` (DOM prêt) plutôt que `networkidle` :
      beaucoup de sites modernes ont des trackers qui ne s'arrêtent jamais et
      networkidle timeout systématiquement.
    - User-Agent navigateur réel + viewport standard.
    - `playwright-stealth` si dispo : patches Chromium pour passer la
      détection bot Cloudflare et consorts.
    - `wait_for_timeout(5s)` après navigation : laisse les challenges JS
      Cloudflare se résoudre (~3-5s en pratique).

    Cache : un GET sur la même URL renvoie le résultat caché (utile pour le
    multi-mois où la même URL est traitée pour chaque mois cible). La clé
    inclut needs_browser (un site peut être fetché en 2 modes différents
    en théorie).
    """
    cache_key = f"{int(needs_browser)}|{url}"
    if cache_key in _FETCH_CACHE:
        return _FETCH_CACHE[cache_key]

    html = _do_fetch(url, needs_browser)
    _FETCH_CACHE[cache_key] = html
    return html


def _do_fetch(url: str, needs_browser: bool = False) -> str:
    """Implémentation pure (non-cachée). Utilisée par _fetch."""
    if needs_browser:
        if _BROWSER_FETCH is not None:
            return _BROWSER_FETCH(url)
        from playwright.sync_api import sync_playwright
        try:
            from playwright_stealth import Stealth
            has_stealth = True
        except ImportError:
            has_stealth = False

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            if has_stealth:
                Stealth().apply_stealth_sync(context)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5000)  # laisse les challenges JS finir
            html = page.content()
            browser.close()
            return html

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    return resp.text


# ---------- PDF distant (la section season_pdfs ne gère plus les URLs) ----------

def _is_pdf_url(url: str) -> bool:
    """Détecte un PDF distant. Priorité : extension .pdf dans le path.
    Fallback : HEAD request pour vérifier Content-Type application/pdf.
    Si HEAD échoue (timeout, 405, etc.), retourne False (traité comme HTML)."""
    if urlparse(url).path.lower().endswith(".pdf"):
        return True
    try:
        h = requests.head(url, headers={"User-Agent": USER_AGENT}, timeout=8, allow_redirects=True)
        return "application/pdf" in h.headers.get("content-type", "").lower()
    except Exception:
        return False


def _fetch_pdf_url(url: str, site_name: str) -> CollectedItem:
    """Télécharge un PDF distant et l'extrait via pdfplumber en mémoire."""
    import io
    import pdfplumber  # lazy import

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        n_pages = len(pdf.pages)
        text = "\n\n".join((p.extract_text() or "") for p in pdf.pages)
    return CollectedItem(
        source_kind="pdf",
        source_ref=url,
        fetched_at=datetime.utcnow().isoformat() + "Z",
        raw_text=text,
        raw_metadata={
            "url": url,
            "site": site_name,
            "n_pages": n_pages,
        },
    )
