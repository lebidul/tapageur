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


_UNKNOWN_PERFORMERS = {"?", "", "inconnu"}


def _has_unknown_performer(ev: Event) -> bool:
    return ev.acts[0].performer.lower().strip() in _UNKNOWN_PERFORMERS


def dedup(events: list[Event]) -> list[Event]:
    """
    Fusionne les doublons identifiés par fingerprint, en 2 passes.

    Pass 1 — STRICT : fingerprint = (date, time_normalisé, venue, performer).
    Garde le premier event de chaque fingerprint, drop les suivants.

    Pass 2 — WEAK : pour chaque event RESTANT après pass 1 dont le performer
    est "?" / inconnu, on calcule fingerprint_weak = (date, time, venue).
    Si ce fingerprint matche un AUTRE event strict de pass 1 (avec performer
    connu, même date+time+venue), on drop l'event weak (= absorbé par
    l'event strict qui a plus d'info).

    Couvre le cas typique : Source A annonce "Andromaque, jeudi 20h, Collège
    Vieux Colombier" avec performer="?", Source B annonce le même event avec
    performer="Théâtre en actes". Sans pass 2, les 2 restent ; avec pass 2,
    seul B est gardé.
    """
    # Pass 1 : dedup strict
    strict_seen: dict[str, Event] = {}
    strict_duplicates: list[tuple[Event, Event]] = []

    for ev in events:
        fp = ev.fingerprint()
        if fp in strict_seen:
            strict_duplicates.append((strict_seen[fp], ev))
            continue
        strict_seen[fp] = ev

    if strict_duplicates:
        for kept, dropped in strict_duplicates:
            print(f"[dedup] strict dup dropped from {dropped.source_kind}:{dropped.source_ref}")

    survivors = list(strict_seen.values())

    # Pass 2 : pour les events weak (performer=?), chercher un strict matching
    # sur fingerprint_weak (date+time+venue). Si trouvé → drop le weak.
    # Index : weak_key → events strict (performer connu) sur cette clé.
    weak_to_strict_events: dict[str, list[Event]] = {}
    for ev in survivors:
        if not _has_unknown_performer(ev):
            weak_to_strict_events.setdefault(ev.fingerprint_weak(), []).append(ev)

    final: list[Event] = []
    weak_duplicates_count = 0
    for ev in survivors:
        if _has_unknown_performer(ev):
            weak_key = ev.fingerprint_weak()
            if weak_to_strict_events.get(weak_key):
                # Un autre event "strict" couvre déjà ce slot → drop celui-ci
                strict_match = weak_to_strict_events[weak_key][0]
                print(f"[dedup] weak dup (performer=?) dropped from {ev.source_kind}:{ev.source_ref}"
                      f" — covered by strict event with performer='{strict_match.acts[0].performer}'")
                weak_duplicates_count += 1
                continue
        final.append(ev)

    if weak_duplicates_count:
        print(f"[dedup] {weak_duplicates_count} weak duplicates dropped (pass 2)")

    return final
