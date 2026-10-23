"""Construit des CollectedItem depuis fichiers déposés et URLs collées."""
from __future__ import annotations

from pathlib import Path

from tapageur.connectors.docs import _route_file
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
