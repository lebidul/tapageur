"""
Connecteur Facebook : events de NOTRE page uniquement.

Limite Meta : depuis 2018-2019, les events des autres pages publiques ne sont plus
accessibles via Graph API. Pour suivre d'autres orgas, OCRiser des screenshots.
"""
from __future__ import annotations

from typing import Iterator

import requests

from tapageur.connectors.base import Connector, register
from tapageur.schema import CollectedItem


@register
class FacebookConnector(Connector):
    name = "fb"

    GRAPH_API = "https://graph.facebook.com/v18.0"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        # Lit `facebook:` (et pas le top-level config). On garde l'ancien
        # fallback pour rester souple si la signature change un jour.
        fb_cfg = self.config.get("facebook", self.config)
        if not fb_cfg.get("enabled", False):
            return
            yield  # unreachable — force ce `def` à être un générateur

        page_id = fb_cfg["page_id"]
        token = __import__("os").environ.get("FB_PAGE_ACCESS_TOKEN")
        if not token:
            print("[fb] FB_PAGE_ACCESS_TOKEN absent dans .env, skip")
            return

        # TODO : appel Graph API events
        # url = f"{self.GRAPH_API}/{page_id}/events"
        # params = {"access_token": token, "fields": "name,start_time,end_time,place,description"}
        # resp = requests.get(url, params=params, timeout=10).json()
        # for event in resp.get("data", []):
        #     yield CollectedItem(...)
        raise NotImplementedError("TODO: Graph API events fetch")
