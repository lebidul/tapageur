"""
Export CSV pour relecture/édition manuelle dans LibreOffice avant push.
Le CSV reproduit les colonnes du Google Sheet exactement.
"""
from __future__ import annotations

import csv
from pathlib import Path

from tapageur.schema import Event


# En-têtes alignés sur le Google Sheet `tapage_biduleur`
HEADERS = [
    "INFO TAPEUR", "DATE TAPAGE", "DATE EMISSION RADIO", "FESTOCHE", "STYLE FESTOCHE",
    "DATE", "HEURE", "LIEU", "VILLE", "PRIX",
    "GENRE 1", "NOM SPECTACLE 1", "ARTISTE 1", "STYLE 1",
    "GENRE 2", "NOM SPECTACLE 2", "ARTISTE 2", "STYLE 2",
    "GENRE 3", "NOM SPECTACLE 3", "ARTISTE 3", "STYLE 3",
    "GENRE 4", "NOM SPECTACLE 4", "ARTISTE 4", "STYLE 4",
]


def event_to_row(ev: Event) -> list[str]:
    """Convertit un Event en row (26 colonnes A-Z)."""
    row = [
        ev.tapeur_email,                  # A
        ev.tapage_iso,                    # B
        "",                               # C — DATE EMISSION RADIO (vide, à remplir manuellement)
        ev.festival or "",                # D
        ev.festival_style or "",          # E
        ev.date_label,                    # F
        ev.time_str(),                    # G ("18h30 & 20h30")
        ev.venue,                         # H
        ev.city,                          # I
        ev.price,                         # J
    ]
    # Acts (jusqu'à 4) : K-N, O-R, S-V, W-Z
    for i in range(4):
        if i < len(ev.acts):
            act = ev.acts[i]
            row.extend([act.genre.value, act.title or "", act.performer, act.style or ""])
        else:
            row.extend(["", "", "", ""])
    return row


def export_csv(events: list[Event], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(HEADERS)
        for ev in events:
            writer.writerow(event_to_row(ev))
    print(f"[validate] {len(events)} lignes → {out_path}")
