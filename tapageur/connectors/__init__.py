"""Connecteurs : un module par type de source. Tous renvoient des CollectedItem."""

from tapageur.connectors.base import Connector, register, get_connector

__all__ = ["Connector", "register", "get_connector"]
