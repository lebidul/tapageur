"""
Connecteur web : fetch chaque URL configurée et yield le texte brut.

Stratégie deux niveaux :
- Page agenda (index) : parsée juste pour extraire les liens vers les pages
  event individuelles (sous-chemins stricts de l'URL d'agenda).
- Pages event : 1 CollectedItem par page (raw text dump). Claude extrait au
  moment de la normalisation. Pas de selector content-spécifique.

Beaucoup de sites n'affichent les horaires/prix que sur les pages détaillées,
pas sur l'agenda d'aperçu — d'où le suivi des liens.

Désactivable par site avec `follow_event_links: false` dans la config.
"""
from __future__ import annotations

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


@register
class WebConnector(Connector):
    name = "web"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        for site in self.config.get("websites", []):
            url = site["url"]
            site_name = site.get("name", url)
            needs_browser = site.get("needs_browser", False)
            follow = site.get("follow_event_links", True)

            try:
                html = _fetch(url, needs_browser=needs_browser)
            except Exception as e:
                print(f"[web] {site_name}: {e}")
                continue

            if not follow:
                # Mode mono-page : dump l'agenda lui-même
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
                yield CollectedItem(
                    source_kind="web",
                    source_ref=url,
                    fetched_at=datetime.utcnow().isoformat() + "Z",
                    raw_text=text,
                    raw_metadata={"site": site_name},
                )
                continue

            # Mode follow : parcours les pages event individuelles
            event_urls = _extract_subpages(html, base_url=url)
            print(f"[web] {site_name}: {len(event_urls)} pages event à fetcher")
            for ev_url in event_urls:
                try:
                    ev_html = _fetch(ev_url, needs_browser=needs_browser)
                except Exception as e:
                    print(f"[web]   {ev_url}: {e}")
                    continue
                ev_text = BeautifulSoup(ev_html, "html.parser").get_text("\n", strip=True)
                yield CollectedItem(
                    source_kind="web",
                    source_ref=ev_url,
                    fetched_at=datetime.utcnow().isoformat() + "Z",
                    raw_text=ev_text,
                    raw_metadata={"site": site_name, "agenda_url": url},
                )


def _extract_subpages(html: str, base_url: str) -> list[str]:
    """Liens dont l'URL est un sous-chemin strict de `base_url`.
    Heuristique générique : un event détaillé vit sous /<agenda_path>/<slug>.
    Exclut les ancres, query strings (déduplique), et les URLs cross-domaine.
    """
    base = urlparse(base_url.rstrip("/"))
    base_path = base.path.rstrip("/")

    soup = BeautifulSoup(html, "html.parser")
    out: set[str] = set()
    for a in soup.find_all("a", href=True):
        full = urljoin(base_url, a["href"])
        p = urlparse(full)
        if p.netloc != base.netloc:
            continue
        path = p.path.rstrip("/")
        if path == base_path:
            continue  # la page agenda elle-même
        if not path.startswith(base_path + "/"):
            continue
        # Normalise (strip query/fragment) pour le dédup
        clean = f"{p.scheme}://{p.netloc}{p.path}"
        out.add(clean)
    return sorted(out)


def _fetch(url: str, needs_browser: bool = False) -> str:
    """Fetch HTML : requests pour le simple, Playwright pour les sites bloqués."""
    if needs_browser:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30_000)
            html = page.content()
            browser.close()
            return html

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    return resp.text
