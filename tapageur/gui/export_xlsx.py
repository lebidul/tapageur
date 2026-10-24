"""Export xlsx : remplit une copie du template (feuille `lebiduleur`)."""
from __future__ import annotations

from pathlib import Path

import openpyxl

from tapageur.schema import Event
from tapageur.validate import event_to_row

TEMPLATE_PATH = Path(__file__).parent / "assets" / "template.xlsx"
DATA_SHEET = "lebiduleur"
_N_FIXED_COLS = 10  # colonnes A-J


def export_xlsx(events: list[Event], out_path: Path, template_path: Path = TEMPLATE_PATH,
                append: bool = False) -> None:
    """Copie le template et écrit les events dans la feuille `lebiduleur`.

    Blocs ACT dynamiques = max(len(acts)). Les en-têtes des blocs au-delà de 4
    (ceux présents dans le template) sont ajoutés. Les feuilles de référence
    sont laissées intactes.

    append=False (ou fichier absent) : part d'une copie du template (création).
    append=True + fichier existant : ajoute les lignes à la suite, en préservant
    les lignes et feuilles existantes."""
    if append and out_path.exists():
        _append_xlsx(events, out_path)
        return

    wb = openpyxl.load_workbook(template_path)
    ws = wb[DATA_SHEET]

    # Purge d'éventuelles lignes de données résiduelles (garde la ligne 1).
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)

    n_acts = max((len(ev.acts) for ev in events), default=1)

    # En-têtes des blocs ACT supplémentaires (au-delà des 4 du template).
    _write_act_headers(ws, 5, n_acts)

    for r, ev in enumerate(events, start=2):
        for c, value in enumerate(event_to_row(ev, n_acts=n_acts), start=1):
            ws.cell(row=r, column=c, value=value)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def _write_act_headers(ws, first: int, last: int) -> None:
    """Écrit les en-têtes des blocs ACT `first..last` (inclus) sur la ligne 1."""
    for i in range(first, last + 1):
        base = _N_FIXED_COLS + (i - 1) * 4
        ws.cell(row=1, column=base + 1, value=f"GENRE {i}")
        ws.cell(row=1, column=base + 2, value=f"NOM SPECTACLE {i}")
        ws.cell(row=1, column=base + 3, value=f"ARTISTE {i}")
        ws.cell(row=1, column=base + 4, value=f"STYLE {i}")


def _append_xlsx(events: list[Event], out_path: Path) -> None:
    wb = openpyxl.load_workbook(out_path)
    if DATA_SHEET not in wb.sheetnames:
        raise ValueError(
            f"{out_path} n'a pas de feuille '{DATA_SHEET}' : append impossible."
        )
    ws = wb[DATA_SHEET]
    existing_blocks = max(1, (ws.max_column - _N_FIXED_COLS) // 4)
    n_acts = max(existing_blocks, max((len(ev.acts) for ev in events), default=1))
    if n_acts > existing_blocks:
        _write_act_headers(ws, existing_blocks + 1, n_acts)
    start = ws.max_row + 1
    for r, ev in enumerate(events, start=start):
        for c, value in enumerate(event_to_row(ev, n_acts=n_acts), start=1):
            ws.cell(row=r, column=c, value=value)
    wb.save(out_path)
