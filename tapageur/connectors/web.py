"""
Connecteur web : un scraper par site. Fallback Playwright pour les sites bloqués.

Pattern :
- Site simple (ex. leplongeoir) → requests + BeautifulSoup
- Site bloqué / dynamique (ex. superforma) → Playwright headless
"""
from __future__ import annotations

from typing import Iterator
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from tapageur.connectors.base import Connector, register
from tapageur.schema import CollectedItem


# === Map nom_scraper → fonction qui retourne (event_url, raw_html_or_text) ===
SCRAPERS: dict[str, callable] = {}


def scraper(name: str):
    """Décorateur pour enregistrer un scraper site-spécifique."""
    def deco(fn):
        SCRAPERS[name] = fn
        return fn
    return deco


@register
class WebConnector(Connector):
    name = "web"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        sites = self.config.get("websites", [])
        for site in sites:
            scraper_name = site["scraper"]
            if scraper_name not in SCRAPERS:
                # TODO : log warning
                continue
            try:
                yield from SCRAPERS[scraper_name](site, month)
            except Exception as e:
                # TODO : log error et continuer
                print(f"[web] scraper {scraper_name} failed: {e}")


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
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


# ============ Scrapers spécifiques ============

@scraper("leplongeoir_v1")
def leplongeoir(site: dict, month: str) -> Iterator[CollectedItem]:
    """
    Le Plongeoir — agenda simple, requests OK.
    Liste les events sur la page principale puis fetche chaque page d'event.
    """
    base_html = _fetch(site["url"], needs_browser=False)
    soup = BeautifulSoup(base_html, "html.parser")

    # TODO : extraire les liens vers chaque page d'event
    # event_links = [urljoin(site["url"], a["href"]) for a in soup.select(...)]
    event_links: list[str] = []

    for url in event_links:
        try:
            html = _fetch(url, needs_browser=False)
            yield CollectedItem(
                source_kind="web",
                source_ref=url,
                fetched_at=__import__("datetime").datetime.utcnow().isoformat() + "Z",
                raw_text=BeautifulSoup(html, "html.parser").get_text("\n", strip=True),
                raw_metadata={"site": site["name"]},
            )
        except Exception as e:
            print(f"[leplongeoir] {url}: {e}")


@scraper("superforma_v1")
def superforma(site: dict, month: str) -> Iterator[CollectedItem]:
    """Superforma — bloque sans bons headers, on passe par Playwright direct."""
    base_html = _fetch(site["url"], needs_browser=True)
    soup = BeautifulSoup(base_html, "html.parser")

    # TODO : extraire les liens /agenda/<slug> du mois
    event_links: list[str] = []

    for url in event_links:
        try:
            html = _fetch(url, needs_browser=True)
            yield CollectedItem(
                source_kind="web",
                source_ref=url,
                fetched_at=__import__("datetime").datetime.utcnow().isoformat() + "Z",
                raw_text=BeautifulSoup(html, "html.parser").get_text("\n", strip=True),
                raw_metadata={"site": site["name"]},
            )
        except Exception as e:
            print(f"[superforma] {url}: {e}")
