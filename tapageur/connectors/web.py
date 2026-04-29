"""
Connecteur web : fetch chaque URL configurée et yield le texte brut.

Pas de parsing site-spécifique : on laisse Claude extraire les events au moment
de la normalisation. Playwright pour les sites qui bloquent requests, sinon
requests + BeautifulSoup pour récupérer le texte.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator

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
            try:
                html = _fetch(url, needs_browser=site.get("needs_browser", False))
            except Exception as e:
                print(f"[web] {site.get('name', url)}: {e}")
                continue

            text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            yield CollectedItem(
                source_kind="web",
                source_ref=url,
                fetched_at=datetime.utcnow().isoformat() + "Z",
                raw_text=text,
                raw_metadata={"site": site.get("name")},
            )


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
