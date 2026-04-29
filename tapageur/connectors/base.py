"""
Interface commune pour tous les connecteurs.
Strategy Pattern + Registry, aligné sur le pattern utilisé dans Podcasteur.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Iterator

from tapageur.schema import CollectedItem


class Connector(ABC):
    """Interface commune. Chaque connecteur implémente .collect()."""

    name: ClassVar[str]                    # ex. "outlook", "web", "pdf"

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def collect(self, month: str) -> Iterator[CollectedItem]:
        """
        month : 'YYYY-MM'
        Yield des CollectedItem (un par event candidat trouvé).
        """
        ...


# ===== Registry =====
_REGISTRY: dict[str, type[Connector]] = {}


def register(cls: type[Connector]) -> type[Connector]:
    """Décorateur : enregistre un Connector dans le registry."""
    if not getattr(cls, "name", None):
        raise ValueError(f"{cls.__name__} must define `name` class attribute")
    _REGISTRY[cls.name] = cls
    return cls


def get_connector(name: str, config: dict) -> Connector:
    """Récupère et instancie un connecteur par son nom."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown connector: {name!r}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name](config)


def list_connectors() -> list[str]:
    return list(_REGISTRY)
