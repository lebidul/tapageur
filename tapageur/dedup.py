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

from tapageur.schema import Event, _normalize_time


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


# ============================================================
# Groupement d'events partageant festival+date+venue
# ============================================================

MAX_ACTS_PER_EVENT = 4  # nombre de blocs ACT du sheet (cols K-Z)


def group_events(events: list[Event]) -> list[Event]:
    """Fusionne en un seul Event les groupes qui partagent festival+date+venue.

    Cas typique : Of Course Le Mans annonce 4 spectacles successifs au même
    parc le même jour (18h30, 19h30, 20h, 21h). Ils proviennent de 4 sous-pages
    web distinctes mais représentent UNE soirée organisée → 1 ligne dans le
    sheet avec 4 acts, et un horaire de départ = 18h30.

    Critères de groupement (TOUS doivent matcher) :
    - même festival (non-vide)
    - même date_iso
    - même venue (canonisé via canonicalize() en amont)

    Sans festival → pas de groupement (trop risqué de fusionner 2 events
    indépendants au même venue le même jour).

    Si plus de 4 acts cumulés → split en blocs successifs de 4 acts max.

    L'event fusionné prend :
    - times = [horaire le plus tôt du groupe]
    - acts = concaténation chronologique (jusqu'à 4)
    - price = premier non-"?" du groupe (sinon "?")
    - festival_style, city, date_label, festival = ceux de l'event le plus tôt
    """
    groups: dict[tuple, list[Event]] = {}
    ungrouped: list[Event] = []
    order: list[tuple | str] = []  # pour préserver l'ordre relatif

    for ev in events:
        if not ev.festival or not ev.festival.strip():
            ungrouped.append(ev)
            order.append(f"u:{len(ungrouped) - 1}")
            continue
        key = (
            ev.festival.lower().strip(),
            ev.date_iso,
            ev.venue.lower().strip(),
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(ev)

    out: list[Event] = []
    n_merged_events_total = 0  # nb d'events fusionnés depuis l'input
    n_output_groups = 0        # nb de nouveaux events produits par fusion

    for entry in order:
        if isinstance(entry, str) and entry.startswith("u:"):
            idx = int(entry.split(":")[1])
            out.append(ungrouped[idx])
            continue
        group = groups[entry]
        if len(group) == 1:
            out.append(group[0])
            continue
        merged = _merge_event_group(group)
        n_merged_events_total += len(group)
        n_output_groups += len(merged)
        out.extend(merged)

    if n_output_groups:
        print(f"[group] {n_merged_events_total} events fusionnés en {n_output_groups} (acts regroupés par festival/date/venue)")

    return out


def _merge_event_group(group: list[Event]) -> list[Event]:
    """Fusionne un groupe (>=2) d'events. Split en blocs de MAX_ACTS_PER_EVENT
    acts si nécessaire. Retourne 1 ou plusieurs events fusionnés."""
    # Trier chronologiquement par horaire de départ normalisé
    sorted_group = sorted(group, key=lambda ev: _normalize_time(ev.times[0]))

    # Aplatir tous les acts en respectant l'ordre chronologique
    flat_acts: list[tuple[Event, "Act"]] = []  # type: ignore[name-defined]
    for ev in sorted_group:
        for act in ev.acts:
            flat_acts.append((ev, act))

    out: list[Event] = []
    i = 0
    while i < len(flat_acts):
        chunk = flat_acts[i:i + MAX_ACTS_PER_EVENT]
        base_event, _ = chunk[0]
        # Copie de base, on remplace acts + times + price
        merged_acts = [act for _, act in chunk]
        # Premier non-"?" de price dans les events du chunk
        chunk_events = list({id(ev): ev for ev, _ in chunk}.values())  # dedup ev refs
        price = next((ev.price for ev in chunk_events if ev.price not in ("?", "")), base_event.price)
        merged = base_event.model_copy(update={
            "acts": merged_acts,
            "times": [base_event.times[0]],   # horaire de départ
            "price": price,
        })
        out.append(merged)
        i += MAX_ACTS_PER_EVENT

    return out
