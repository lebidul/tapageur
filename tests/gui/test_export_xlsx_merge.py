# tests/gui/test_export_xlsx_merge.py
from tapageur.gui import export_xlsx as X
from tapageur.schema import Event, Act


def _ev(perf="Groupe X", venue="Le Lézard", date_label="Mardi 3",
        heure="20h00", price="?", festival=None, is_festival=False):
    return Event(
        tapeur_email="t@b.fr", festival=festival, date_label=date_label,
        date_iso="2026-11-03", times=[heure], venue=venue, city="Le Mans",
        price=price, is_festival=is_festival,
        acts=[Act(genre="c", title=None, performer=perf, style=None)],
        source_kind="web", source_ref="https://a.fr/x",
    )


def test_norm_strips_accents_case_space():
    assert X._norm("  Le Lézard ") == X._norm("le lezard")


def test_is_blank():
    assert X._is_blank(None) and X._is_blank("") and X._is_blank("?") and X._is_blank(" ? ")
    assert not X._is_blank("20h00")


def test_key_from_cells_matches_event_cells():
    ev = _ev()
    cells = X._event_cells(ev, n_acts=1)
    # DATE col8, LIEU col10, ARTISTE1 col15
    assert X._key_from_cells(cells) == ("mardi 3", "le lezard", "groupe x")


def test_key_ignores_heure_price():
    a = X._key_from_cells(X._event_cells(_ev(heure="20h00", price="10€"), 1))
    b = X._key_from_cells(X._event_cells(_ev(heure="21h30", price="?"), 1))
    assert a == b


def test_plan_fill_fills_blanks_only():
    ev_existing = _ev(heure="20h00", price="?", festival=None)
    ev_incoming = _ev(heure="21h00", price="10€", festival="Soirée Beaujolais")
    existing = X._event_cells(ev_existing, 1)
    incoming = X._event_cells(ev_incoming, 1)
    fills, labels = X._plan_fill(existing, incoming, n_cols=len(existing))
    # PRIX (col12) vide → rempli ; FESTOCHE (col6) vide → rempli
    assert fills[X._COL_PRIX] == "10€"
    assert fills[X._COL_FESTOCHE] == "Soirée Beaujolais"
    # HEURE déjà remplie (20h00) → NON touchée
    assert X._COL_HEURE not in fills
    assert "PRIX" in labels and "FESTOCHE" in labels


def test_plan_fill_never_overwrites():
    existing = X._event_cells(_ev(heure="20h00", price="10€"), 1)
    incoming = X._event_cells(_ev(heure="21h00", price="15€"), 1)
    fills, labels = X._plan_fill(existing, incoming, n_cols=len(existing))
    assert fills == {} and labels == []


def test_merge_source_cell_appends_without_dup():
    assert X._merge_source_cell("prog.pdf", "https://a.fr/x") == "prog.pdf ; https://a.fr/x"
    assert X._merge_source_cell("https://a.fr/x", "https://a.fr/x") is None  # déjà présent
