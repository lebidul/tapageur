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
