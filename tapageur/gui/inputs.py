"""Construit des CollectedItem depuis fichiers déposés et URLs collées."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tapageur.connectors.docs import _route_file
from tapageur.connectors.web import WebConnector
from tapageur.schema import CollectedItem


@dataclass
class FileInput:
    """Un fichier déposé/choisi + ses champs éditables par élément."""
    path: str
    venue: str = ""
    info_orga: str = ""
    is_festival: bool = False


def items_from_files(file_inputs: list[FileInput], progress=None) -> list[CollectedItem]:
    """Route chaque fichier via le connecteur docs (``_route_file`` renvoie une
    liste : 0, 1 ou N items ; types non gérés → aucun item ; PDF sans texte →
    une image par page), puis applique les overrides par élément dans
    ``raw_metadata`` (lieu/asso si non vides, mode festival si demandé) en
    préservant la metadata d'origine de l'item."""
    items: list[CollectedItem] = []
    n = len(file_inputs)
    for i, fi in enumerate(file_inputs, 1):
        if progress:
            progress(f"Fichier {i}/{n} : {Path(fi.path).name}")
        for item in _route_file(Path(fi.path)):
            if fi.venue:
                item.raw_metadata["default_venue"] = fi.venue
            if fi.info_orga:
                item.raw_metadata["default_festival"] = fi.info_orga
            if fi.is_festival:
                item.raw_metadata["mode"] = "festival_onliner"
            items.append(item)
    return items


@dataclass
class UrlInput:
    """Une URL collée dans l'UI + ses options par-entrée."""
    url: str
    follow_links: bool = False
    is_festival: bool = False
    venue: str = ""
    info_orga: str = ""


def _url_to_site(u: UrlInput) -> dict:
    """Transforme un UrlInput en entrée `websites:` pour WebConnector."""
    site: dict = {
        "url": u.url,
        "name": u.url,
        "needs_browser": True,          # navigateur embarqué v1 : toute URL lisible
        "follow_event_links": u.follow_links,
        "follow_scope": "domain",       # GUI : « suivre les liens » = découverte domaine + pré-filtre
        "prefilter_by_month": True,     # #12 : filtre mois dès l'agenda (date lue sur la carte ;
                                        # « pas de date → inclure » → aucun event perdu)
    }
    if u.is_festival:
        site["mode"] = "festival_onliner"
    if u.venue:
        site["default_venue"] = u.venue
    if u.info_orga:
        site["default_festival"] = u.info_orga
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
    is_festival: bool = False


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
        meta = {"default_venue": t.venue, "default_festival": t.info_orga}
        if t.is_festival:
            meta["mode"] = "festival_onliner"
        items.append(CollectedItem(
            source_kind="text",
            source_ref=f"texte #{i}",
            fetched_at=datetime.utcnow().isoformat() + "Z",
            raw_text=t.text,
            raw_metadata=meta,
        ))
    return items
