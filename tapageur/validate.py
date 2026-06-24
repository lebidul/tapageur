"""
Export CSV pour relecture/édition manuelle dans LibreOffice avant push.

Le CSV reproduit les colonnes du Google Sheet biduleur. Cols A-J sont fixes.
Cols K..Z (et au-delà) : 4 colonnes par act (GENRE, NOM SPECTACLE, ARTISTE,
STYLE). Le nombre de blocs ACT est calculé dynamiquement = max(len(acts))
sur l'ensemble des events exportés. Les lignes plus courtes sont paddées
avec des cellules vides. biduleur supporte un nombre dynamique de colonnes.
"""
from __future__ import annotations

import csv
from pathlib import Path

from tapageur.schema import Event


# En-têtes fixes (cols A-J)
HEADERS_BASE = [
    "INFO TAPEUR", "DATE TAPAGE", "DATE EMISSION RADIO", "FESTOCHE", "STYLE FESTOCHE",
    "DATE", "HEURE", "LIEU", "VILLE", "PRIX",
]

# Headers historiques exposés pour la compatibilité (tests qui importent HEADERS).
# Correspond à 4 blocs ACT, le nombre minimal que biduleur supportait avant
# l'extension dynamique. Utilisé uniquement comme valeur de référence ; les
# en-têtes réellement écrits par export_csv sont calculés dynamiquement.
HEADERS = HEADERS_BASE + [
    "GENRE 1", "NOM SPECTACLE 1", "ARTISTE 1", "STYLE 1",
    "GENRE 2", "NOM SPECTACLE 2", "ARTISTE 2", "STYLE 2",
    "GENRE 3", "NOM SPECTACLE 3", "ARTISTE 3", "STYLE 3",
    "GENRE 4", "NOM SPECTACLE 4", "ARTISTE 4", "STYLE 4",
]

FESTIVAL_DATE_MARKER = "Festivals"  # marqueur reconnu par biduleur (PR #106)


def _make_headers(n_acts: int) -> list[str]:
    """En-têtes complets pour un export avec n_acts blocs."""
    headers = list(HEADERS_BASE)
    for i in range(1, n_acts + 1):
        headers.extend([f"GENRE {i}", f"NOM SPECTACLE {i}", f"ARTISTE {i}", f"STYLE {i}"])
    return headers


def event_to_row(ev: Event, n_acts: int | None = None) -> list[str]:
    """Convertit un Event en row.

    n_acts : nombre de blocs ACT à émettre (4 colonnes chacun). Si None,
    utilise len(ev.acts) — utile pour les tests à 1 event. En usage normal
    (export_csv), n_acts = max sur tout l'export pour aligner les lignes.
    Les blocs au-delà de len(ev.acts) sont remplis de cellules vides.

    Mode festival (ev.is_festival=True) :
    - DATE = "Festivals" (marqueur magique pour biduleur)
    - HEURE / LIEU vides
    - FESTOCHE = ev.festival, STYLE FESTOCHE = ev.festival_style
    """
    if ev.is_festival:
        date_cell = FESTIVAL_DATE_MARKER
        time_cell = ""
        venue_cell = ""
    else:
        date_cell = ev.date_label
        time_cell = ev.time_str()
        venue_cell = ev.venue

    row = [
        ev.tapeur_email,                  # A
        ev.tapage_iso,                    # B
        "",                               # C — DATE EMISSION RADIO (vide, à remplir manuellement)
        ev.festival or "",                # D
        ev.festival_style or "",          # E
        date_cell,                        # F
        time_cell,                        # G ("18h30 & 20h30")
        venue_cell,                       # H
        ev.city,                          # I
        ev.price,                         # J
    ]

    target = n_acts if n_acts is not None else len(ev.acts)
    for i in range(target):
        if i < len(ev.acts):
            act = ev.acts[i]
            row.extend([act.genre.value, act.title or "", act.performer, act.style or ""])
        else:
            row.extend(["", "", "", ""])
    return row


def export_csv(events: list[Event], out_path: Path) -> None:
    """Écrit un CSV avec un nombre de colonnes ACT dynamique = max d'acts
    sur tous les events exportés. Si la liste est vide, on émet quand même
    les headers de base + 1 bloc ACT (cohérent avec le sheet)."""
    n_acts = max((len(ev.acts) for ev in events), default=1)
    headers = _make_headers(n_acts)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for ev in events:
            writer.writerow(event_to_row(ev, n_acts=n_acts))
    print(f"[validate] {len(events)} lignes ({n_acts} blocs ACT) → {out_path}")
