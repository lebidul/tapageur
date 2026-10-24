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
Tu es un router d'URLs. À partir d'un texte d'agenda et d'une liste d'URLs candidates \
(chacune pointant vers une page event détaillée du même site), retourne UNIQUEMENT \
les URLs dont l'event a lieu dans le mois cible.

Heuristiques :
- Chaque URL correspond à un event listé dans le texte d'agenda.
- Le slug d'URL contient souvent un indice (nom artiste/spectacle).
- Le texte d'agenda donne les dates des events (mois, parfois année).
- En cas d'INCERTITUDE (date ambiguë, slug obscur, year manquante) : INCLURE
  l'URL. Mieux vaut payer un fetch inutile qu'oublier un event.

Réponds UNIQUEMENT par un JSON valide :
{"urls": ["...", "..."]}

- AUCUN texte avant ou après.
- PAS de markdown.
- Liste vide si aucune URL ne correspond avec certitude."""


@register
class WebConnector(Connector):
    name = "web"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        for site in self.config.get("websites", []):
            url = site["url"]
            site_name = site.get("name", url)
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

            # Détection PDF distant : extension d'URL ou Content-Type via HEAD.
            # Route vers le parsing pdfplumber au lieu du fetch HTML.
            if _is_pdf_url(url):
                try:
                    item = _fetch_pdf_url(url, site_name)
                    if mode:
                        item.raw_metadata["mode"] = mode
                    if model_override:
                        item.raw_metadata["model_override"] = model_override
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
                meta = {"site": site_name}
                if mode:
                    meta["mode"] = mode
                if model_override:
                    meta["model_override"] = model_override
                yield CollectedItem(
                    source_kind="web",
                    source_ref=url,
                    fetched_at=datetime.utcnow().isoformat() + "Z",
                    raw_text=text,
                    raw_metadata=meta,
                )
                continue

            # Mode follow : parcours les pages event individuelles.
            # event_link_pattern (regex) optionnel pour les sites à structure
            # non-standard (ex: msj.world/ofcourselemans/86 → pages event sous
            # /ofcourselemans/card/<slug>, pas sous /ofcourselemans/86/<slug>).
            event_pattern = site.get("event_link_pattern")
            event_urls = _extract_subpages(html, base_url=url, pattern=event_pattern)
            agenda_text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            print(f"[web] {site_name}: {len(event_urls)} URLs candidates")

            # Pré-filtrage Claude (économise ~80% des fetch + calls downstream)
            if site.get("prefilter_by_month", True) and event_urls:
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    print(f"[web]   prefilter skip (ANTHROPIC_API_KEY absente)")
                else:
                    try:
                        kept = _filter_urls_by_month(agenda_text, event_urls, month)
                        print(f"[web]   {len(kept)}/{len(event_urls)} retenues pour {month}")
                        event_urls = kept
                    except Exception as e:
                        print(f"[web]   prefilter échoué ({e}), fallback fetch all")

            for ev_url in event_urls:
                try:
                    ev_html = _fetch(ev_url, needs_browser=needs_browser)
                except Exception as e:
                    print(f"[web]   {ev_url}: {e}")
                    continue
                ev_text = BeautifulSoup(ev_html, "html.parser").get_text("\n", strip=True)
                meta = {"site": site_name, "agenda_url": url}
                if mode:
                    meta["mode"] = mode
                if model_override:
                    meta["model_override"] = model_override
                yield CollectedItem(
                    source_kind="web",
                    source_ref=ev_url,
                    fetched_at=datetime.utcnow().isoformat() + "Z",
                    raw_text=ev_text,
                    raw_metadata=meta,
                )


def _filter_urls_by_month(
    agenda_text: str,
    urls: list[str],
    month: str,
) -> list[str]:
    """Pré-filtrage Claude : demande lesquelles des URLs candidates pointent
    vers un event en `month` (YYYY-MM) en se basant sur le texte d'agenda.

    Retourne un sous-ensemble strict de `urls` (Claude ne peut pas inventer
    une URL qui n'était pas dans la liste — sanity check côté Python).
    En cas d'erreur API/parse, lève l'exception : le caller décide du
    fallback (typiquement : fetch all)."""
    from anthropic import Anthropic

    from tapageur.normalize import _extract_json

    client = Anthropic()
    user = (
        f"Mois cible : {month}\n\n"
        f"=== Agenda overview ===\n{agenda_text}\n\n"
        f"=== URLs candidates ({len(urls)}) ===\n" + "\n".join(urls)
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
    valid = set(urls)
    return [u for u in candidates if u in valid]


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
        clean = f"{p.scheme}://{p.netloc}{p.path}"
        out.add(clean)
    return sorted(out)


# Cache HTTP in-process pour éviter de re-fetcher la même URL entre 2 mois
# cibles (cas du `collect --month 07 --month 08`). Vidé manuellement entre
# runs si besoin via clear_fetch_cache(). Pas de TTL : valide tant que le
# processus tourne (chaque CLI invocation = 1 process).
_FETCH_CACHE: dict[str, str] = {}


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
