"""
Push vers Google Sheets via gspread.

Setup une fois :
1. Service Account dans Google Cloud Console + clé JSON
2. Partager le sheet cible avec l'email du service account (Editor)
3. Chemin de la clé dans .env (GOOGLE_SHEETS_SERVICE_ACCOUNT)
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import gspread

from tapageur.validate import HEADERS


def push_csv(csv_path: Path, sheet_id: str, worksheet_name: str | None = None) -> int:
    """
    Lit le CSV validé et append les lignes au sheet.
    Si worksheet_name est None, append à la première feuille.
    Retourne le nombre de lignes ajoutées.
    """
    sa_path = os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT"]
    gc = gspread.service_account(filename=sa_path)
    sh = gc.open_by_key(sheet_id)
    ws = sh.worksheet(worksheet_name) if worksheet_name else sh.sheet1

    rows: list[list[str]] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        if header != HEADERS:
            print(f"[push] WARN : en-têtes CSV ne matchent pas le schéma (csv={header[:3]}...)")
        rows = list(reader)

    if not rows:
        print("[push] aucune ligne à pusher")
        return 0

    # Append en bloc (1 appel API)
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    print(f"[push] {len(rows)} lignes ajoutées à {sh.title} / {ws.title}")
    return len(rows)
