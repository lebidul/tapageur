"""Construit des CollectedItem depuis fichiers déposés et URLs collées."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tapageur.connectors.docs import _route_file
from tapageur.connectors.web import WebConnector
from tapageur.schema import CollectedItem


def items_from_files(paths: list[Path], progress=None) -> list[CollectedItem]:
    """Route chaque fichier via le connecteur docs. Ignore les types non
    gérés et les PDF sans texte (``_route_file`` renvoie ``None``)."""
    items: list[CollectedItem] = []
    n = len(paths)
    for i, p in enumerate(paths, 1):
        if progress:
            progress(f"Fichier {i}/{n} : {Path(p).name}")
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
        "follow_scope": "domain",       # GUI : « suivre les liens » = découverte domaine + pré-filtre
        "prefilter_by_month": False,    # filtrage mois fait en aval par normalize
    }
    if u.is_festival:
        site["mode"] = "festival_onliner"
    return site


def items_from_urls(url_inputs: list[UrlInput], month: str, progress=None) -> list[CollectedItem]:
    """Collecte chaque URL via WebConnector (navigateur, suivi de liens, mode
    festival selon les options de chaque UrlInput)."""
    config = {"websites": [_url_to_site(u) for u in url_inputs]}
    conn = WebConnector(config)
    return list(conn.collect(month, progress=progress))


@dataclass
class TextInput:
    """Un texte collé dans l'UI + ses champs éditables (overrides si absents)."""
    text: str
    venue: str = ""
    info_orga: str = ""


def items_from_texts(text_inputs: list[TextInput], progress=None) -> list[CollectedItem]:
    """Construit un CollectedItem (source_kind='text') par texte non vide.
    venue / info_orga sont portés dans raw_metadata et appliqués en aval par
    normalize uniquement si l'event extrait n'a pas déjà l'info."""
    from datetime import datetime
    kept = [t for t in text_inputs if t.text and t.text.strip()]
    items: list[CollectedItem] = []
    n = len(kept)
    for i, t in enumerate(kept, 1):
        if progress:
            progress(f"Texte {i}/{n}…")
        items.append(CollectedItem(
            source_kind="text",
            source_ref=f"texte #{i}",
            fetched_at=datetime.utcnow().isoformat() + "Z",
            raw_text=t.text,
            raw_metadata={"default_venue": t.venue, "default_festival": t.info_orga},
        ))
    return items
