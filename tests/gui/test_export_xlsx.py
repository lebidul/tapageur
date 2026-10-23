import openpyxl
from tapageur.gui import export_xlsx
from tapageur.schema import Event, Act


def _event(perf="Groupe A", n_acts=1, festival=False):
    acts = [Act(genre="c", title=None, performer=f"{perf}{i}", style=None) for i in range(n_acts)]
    return Event(
        tapeur_email="t@b.fr", festival=("Fest" if festival else None),
        date_label="Vendredi 2", date_iso="2026-10-02", times=["20h00"],
        venue="Le Lieu", city="Le Mans", price="10€",
        is_festival=festival, acts=acts, source_kind="web", source_ref="https://x.fr",
    )


def test_export_writes_data_and_keeps_reference_sheets(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event()], out)
    wb = openpyxl.load_workbook(out)
    assert set(["lebiduleur", "communes", "salles_lieux", "date"]).issubset(set(wb.sheetnames))
    ws = wb["lebiduleur"]
    # ligne 1 = en-têtes conservés ; ligne 2 = 1er event
    assert ws.cell(row=2, column=1).value == "t@b.fr"        # col A INFO TAPEUR
    assert ws.cell(row=2, column=8).value == "Le Lieu"        # col H LIEU
    assert ws.cell(row=2, column=9).value == "Le Mans"        # col I VILLE


def test_export_dynamic_act_blocks(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event(n_acts=5)], out)
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    # 10 colonnes fixes + 5 blocs * 4 = 30 colonnes ; en-tête bloc 5 ajouté
    assert ws.cell(row=1, column=11 + 4 * 4).value == "GENRE 5"
    assert ws.cell(row=2, column=11 + 4 * 4).value == "c"     # genre du 5e act
