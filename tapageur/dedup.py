"""
Dédoublonnage et canonicalisation.

Stratégie :
1. Charger config/mappings.yaml pour avoir les formes canoniques (lieux, artistes, festivals)
2. Pour chaque Event, normaliser venue/performer via les mappings
3. Calculer le fingerprint et fusionner les doublons
"""
from __future__ import annotations

from pathlib import Path

import yaml

from tapageur.schema import Event


def load_mappings(path: Path = Path("config/mappings.yaml")) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _build_lookup(group: dict[str, list[str]]) -> dict[str, str]:
    """Inverse {canonical: [variants]} en {variant_lower: canonical}."""
    out: dict[str, str] = {}
    for canonical, variants in (group or {}).items():
        out[canonical.lower().strip()] = canonical
        for v in variants:
            out[v.lower().strip()] = canonical
    return out


def canonicalize(events: list[Event], mappings: dict) -> list[Event]:
    """Applique les mappings pour normaliser venue + performer."""
    venue_lookup = _build_lookup(mappings.get("venues", {}))
    artist_lookup = _build_lookup(mappings.get("artists", {}))
    fest_lookup = _build_lookup(mappings.get("festivals", {}))

    for ev in events:
        ev.venue = venue_lookup.get(ev.venue.lower().strip(), ev.venue)
        if ev.festival:
            ev.festival = fest_lookup.get(ev.festival.lower().strip(), ev.festival)
        for act in ev.acts:
            act.performer = artist_lookup.get(act.performer.lower().strip(), act.performer)
    return events


def dedup(events: list[Event]) -> list[Event]:
    """
    Fusionne les doublons identifiés par fingerprint.
    Stratégie : si deux events ont le même fingerprint, on garde le premier
    et on log un warning (souvent ça veut dire 2 sources qui parlent du même event).
    """
    seen: dict[str, Event] = {}
    duplicates: list[tuple[Event, Event]] = []

    for ev in events:
        fp = ev.fingerprint()
        if fp in seen:
            duplicates.append((seen[fp], ev))
            continue
        seen[fp] = ev

    if duplicates:
        # TODO : logger via rich
        for kept, dropped in duplicates:
            print(f"[dedup] dropped duplicate from {dropped.source_kind}:{dropped.source_ref}")

    return list(seen.values())
