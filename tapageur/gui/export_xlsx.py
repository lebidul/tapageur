"""Export xlsx : remplit une copie du template (feuille `lebiduleur`)."""
from __future__ import annotations

from pathlib import Path

import openpyxl

from tapageur.schema import Event
from tapageur.validate import event_to_row

TEMPLATE_PATH = Path(__file__).parent / "assets" / "template.xlsx"
DATA_SHEET = "lebiduleur"
_N_FIXED_COLS = 10  # colonnes A-J


def export_xlsx(events: list[Event], out_path: Path, template_path: Path = TEMPLATE_PATH) -> None:
    """Copie le template et écrit les events dans la feuille `lebiduleur`.

    Blocs ACT dynamiques = max(len(acts)). Les en-têtes des blocs au-delà de 4
    (ceux présents dans le template) sont ajoutés. Les feuilles de référence
    sont laissées intactes."""
    wb = openpyxl.load_workbook(template_path)
    ws = wb[DATA_SHEET]

    # Purge d'éventuelles lignes de données résiduelles (garde la ligne 1).
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)

    n_acts = max((len(ev.acts) for ev in events), default=1)

    # En-têtes des blocs ACT supplémentaires (au-delà des 4 du template).
    for i in range(5, n_acts + 1):
        base = _N_FIXED_COLS + (i - 1) * 4
        ws.cell(row=1, column=base + 1, value=f"GENRE {i}")
        ws.cell(row=1, column=base + 2, value=f"NOM SPECTACLE {i}")
        ws.cell(row=1, column=base + 3, value=f"ARTISTE {i}")
        ws.cell(row=1, column=base + 4, value=f"STYLE {i}")

    for r, ev in enumerate(events, start=2):
        for c, value in enumerate(event_to_row(ev, n_acts=n_acts), start=1):
            ws.cell(row=r, column=c, value=value)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
