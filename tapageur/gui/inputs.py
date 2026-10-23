"""Construit des CollectedItem depuis fichiers déposés et URLs collées."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tapageur.connectors.docs import _route_file
from tapageur.connectors.web import WebConnector
from tapageur.schema import CollectedItem


def items_from_files(paths: list[Path]) -> list[CollectedItem]:
    """Route chaque fichier via le connecteur docs. Ignore les types non
    gérés et les PDF sans texte (``_route_file`` renvoie ``None``)."""
    items: list[CollectedItem] = []
    for p in paths:
        item = _route_file(Path(p))
        if item is not None:
            items.append(item)
    return items


@dataclass
class UrlInput:
    """Une URL collée dans l'UI + ses options par-entrée."""
    url: str
    follow_links: bool = False
    is_festival: bool = False


def _url_to_site(u: UrlInput) -> dict:
    """Transforme un UrlInput en entrée `websites:` pour WebConnector."""
    site: dict = {
        "url": u.url,
        "name": u.url,
        "needs_browser": True,          # navigateur embarqué v1 : toute URL lisible
        "follow_event_links": u.follow_links,
        "prefilter_by_month": False,    # filtrage mois fait en aval par normalize
    }
    if u.is_festival:
        site["mode"] = "festival_onliner"
    return site


def items_from_urls(url_inputs: list[UrlInput], month: str) -> list[CollectedItem]:
    """Collecte chaque URL via WebConnector (navigateur, suivi de liens, mode
    festival selon les options de chaque UrlInput)."""
    config = {"websites": [_url_to_site(u) for u in url_inputs]}
    conn = WebConnector(config)
    return list(conn.collect(month))
