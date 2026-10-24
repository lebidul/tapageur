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


def test_append_preserves_and_adds(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event(perf="Alpha")], out)                 # création
    export_xlsx.export_xlsx([_event(perf="Beta")], out, append=True)     # append
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    # 1 en-tête + 2 lignes de données
    assert ws.cell(row=2, column=13).value == "Alpha0"   # ARTISTE 1, 1re ligne inchangée
    assert ws.cell(row=3, column=13).value == "Beta0"    # ARTISTE 1, ligne ajoutée
    assert ws.max_row == 3


def test_append_widens_act_blocks(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event(n_acts=1)], out)                     # 4 blocs (template)
    export_xlsx.export_xlsx([_event(n_acts=5, perf="X")], out, append=True)
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    assert ws.cell(row=1, column=11 + 4 * 4).value == "GENRE 5"         # en-tête bloc 5 ajouté
    assert ws.cell(row=3, column=11 + 4 * 4).value == "c"               # genre 5e act, ligne ajoutée


def test_append_without_lebiduleur_raises(tmp_path):
    import openpyxl as _ox
    foreign = tmp_path / "foreign.xlsx"
    wb = _ox.Workbook()
    wb.active.title = "autre"
    wb.save(foreign)
    import pytest
    with pytest.raises(ValueError):
        export_xlsx.export_xlsx([_event()], foreign, append=True)


def test_append_on_missing_file_creates(tmp_path):
    out = tmp_path / "nouveau.xlsx"
    export_xlsx.export_xlsx([_event(perf="Solo")], out, append=True)     # fichier absent
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    assert ws.cell(row=2, column=13).value == "Solo0"
    assert ws.max_row == 2
