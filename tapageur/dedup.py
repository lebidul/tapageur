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

from datetime import date as _date

from tapageur.schema import Act, Event, Genre, _normalize_time


def load_mappings(path: Path = Path("config/mappings.yaml")) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_venue_defaults(path: Path = Path("config/venue_defaults.yaml")) -> dict:
    """Charge les défauts heure/prix par lieu ; {} si absent/illisible."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_venue_defaults(events: list[Event], defaults: dict) -> list[Event]:
    """Complète heure/prix/ville manquants selon le lieu (déjà canonicalisé).
    N'écrase jamais une valeur extraite."""
    for ev in events:
        d = defaults.get(ev.venue)
        if not d:
            continue
        if d.get("time") and (not ev.times or ev.times == ["?"]):
            ev.times = [d["time"]]
        if d.get("price") and (not ev.price or ev.price.strip() in ("", "?")):
            ev.price = d["price"]
        if d.get("city") and (not ev.city or ev.city.strip() in ("", "?")):
            ev.city = d["city"]
    return events


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

    Pas de limite haute sur le nombre d'acts dans le groupe fusionné : tous
    les acts du groupe sont concaténés dans le même Event. Le CSV (cf.
    validate.export_csv) générera dynamiquement autant de colonnes ACT que
    nécessaire — biduleur supporte un nombre de colonnes variable.

    L'event fusionné prend :
    - times = [horaire le plus tôt du groupe]
    - acts = concaténation chronologique de TOUS les acts (sans split)
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
    """Fusionne un groupe (>=2) d'events en 1 seul Event multi-acts.
    Pas de split (le CSV génère autant de colonnes que d'acts)."""
    # Trier chronologiquement par horaire de départ normalisé
    sorted_group = sorted(group, key=lambda ev: _normalize_time(ev.times[0]))

    # Concaténation chronologique de tous les acts
    all_acts = [act for ev in sorted_group for act in ev.acts]

    # Premier prix non-"?" / non-vide dans le groupe
    price = next(
        (ev.price for ev in sorted_group if ev.price not in ("?", "")),
        sorted_group[0].price,
    )

    base = sorted_group[0]
    merged = base.model_copy(update={
        "acts": all_acts,
        "times": [base.times[0]],   # horaire de départ
        "price": price,
    })
    return [merged]


# ============================================================
# Post-conversion en onliner par nom de festival
# ============================================================

_FR_MONTHS_ABBR = [
    "janv.", "fév.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sept.", "oct.", "nov.", "déc.",
]


def _fr_date(iso: str) -> str:
    """'2026-08-11' → '11 août'. Fallback : renvoie iso tel quel si invalide."""
    try:
        d = _date.fromisoformat(iso)
        return f"{d.day} {_FR_MONTHS_ABBR[d.month - 1]}"
    except (ValueError, IndexError):
        return iso


def convert_to_onliner(events: list[Event], target_festival_names: list[str]) -> list[Event]:
    """Convertit en 1 Event onliner unique les events partageant un nom de festival cible.

    Cas d'usage : un festival est extrait « en pièces détachées » par le
    pipeline (ex. Les Mardis de la Chanson = 3 concerts séparés extraits du
    LeMans_Guide-ete-2026.pdf) et on veut le rendre en 1 ligne 'Festivals'
    au CSV, comme si sa source avait été `mode: festival_onliner`. On ne
    peut pas mettre le PDF entier en onliner car il contient plein d'autres
    events indépendants.

    Matching des noms : case-insensitive, whitespace-stripped. La casse
    du groupe (préservée depuis les données) sert de nom pour l'onliner.

    Chaque event dont `festival` matche un des noms cibles est extrait
    et regroupé. Chaque groupe produit 1 Event onliner qui remplace tous
    les events du groupe. Les events non-cibles sont conservés tels quels.
    """
    if not target_festival_names or not events:
        return events

    targets = {name.lower().strip() for name in target_festival_names}

    to_convert: dict[str, list[Event]] = {}
    kept: list[Event] = []

    for ev in events:
        fest = (ev.festival or "").lower().strip()
        if fest and fest in targets:
            # utilise la casse originale comme clé (préserve "Les Mardis…")
            to_convert.setdefault(ev.festival, []).append(ev)
        else:
            kept.append(ev)

    if not to_convert:
        return events

    onliners: list[Event] = []
    for fest_name, group in to_convert.items():
        onliner = _build_onliner_from_group(fest_name, group)
        onliners.append(onliner)
        print(f"[onliner] {fest_name} : {len(group)} events → 1 ligne Festivals")

    return kept + onliners


def _build_onliner_from_group(festival_name: str, group: list[Event]) -> Event:
    """Construit 1 Event onliner à partir d'un groupe d'events partageant le
    même nom de festival. Choix éditoriaux :

    - date_iso = premier date (chrono) — permet le tri au CSV
    - times = ["?"] — non pertinent en mode onliner
    - venue = "" — convention onliner (biduleur ignore le lieu)
    - city = unique si tous les events convergent, sinon celle du 1er event
    - price = "?" — impossible à consolider raisonnablement
    - festival_style = résumé auto ("N spectacles à Ville, du D1 au D2. Programmation : A, B, C.")
    - acts = 1 Act(sv, performer=f"N spectacles", style=style dominant)
    """
    sorted_group = sorted(group, key=lambda e: (e.date_iso, _normalize_time(e.times[0])))
    base = sorted_group[0]

    cities = [e.city for e in sorted_group if e.city and e.city != "?"]
    unique_cities = list(dict.fromkeys(cities))
    city = unique_cities[0] if len(unique_cities) == 1 else (base.city or "?")

    performers: list[str] = []
    for ev in sorted_group:
        for a in ev.acts:
            p = (a.performer or "").strip()
            if p and p != "?":
                performers.append(p)
    performers_unique = list(dict.fromkeys(performers))

    styles = [a.style for ev in sorted_group for a in ev.acts if a.style]
    styles_unique = list(dict.fromkeys(styles))

    n_events = len(sorted_group)
    first_date = sorted_group[0].date_iso
    last_date = sorted_group[-1].date_iso
    date_bit = (
        f"le {_fr_date(first_date)}"
        if first_date == last_date
        else f"du {_fr_date(first_date)} au {_fr_date(last_date)}"
    )

    parts = [f"{n_events} événements"]
    if city and city != "?":
        parts.append(f"à {city},")
    parts.append(f"{date_bit}.")
    if performers_unique:
        top = performers_unique[:6]
        listing = ", ".join(top)
        if len(performers_unique) > 6:
            listing += f", et {len(performers_unique) - 6} autres"
        parts.append(f"Programmation : {listing}.")
    festival_style = " ".join(parts)

    onliner_act = Act(
        genre=Genre.SPECTACLE_VIVANT,
        title=None,   # URL renseignée manuellement post-preview si dispo
        performer=(f"{n_events} spectacles" if n_events > 1 else base.acts[0].performer),
        style=styles_unique[0] if styles_unique else None,
    )

    return base.model_copy(update={
        "is_festival": True,
        "festival": festival_name,
        "festival_style": festival_style,
        "date_iso": first_date,
        "times": ["?"],
        "venue": "",
        "city": city,
        "price": "?",
        "acts": [onliner_act],
    })
