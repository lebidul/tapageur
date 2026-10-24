"""Tests de l'export CSV (event_to_row + export_csv dynamique)."""
from __future__ import annotations

from pathlib import Path

from tapageur.schema import Act, Event, Genre
from tapageur.validate import (
    FESTIVAL_DATE_MARKER,
    HEADERS,
    _make_headers,
    _source_ref_display,
    _source_type_label,
    event_to_row,
    export_csv,
)


def test_source_type_label_mapping():
    assert _source_type_label("web") == "URL"
    assert _source_type_label("pdf") == "Document"
    assert _source_type_label("image") == "Image"
    assert _source_type_label("text") == "Texte"
    assert _source_type_label("outlook") == "Email"
    assert _source_type_label("fb") == "Facebook"


def test_source_type_label_unknown_falls_back_to_raw():
    assert _source_type_label("inconnu") == "inconnu"


def test_source_ref_display_image_is_basename():
    assert _source_ref_display("image", r"C:\dossier\flyer.png") == "flyer.png"


def test_source_ref_display_pdf_with_page():
    assert _source_ref_display("pdf", r"C:\dossier\prog.pdf#page=2") == "prog.pdf (p.2)"


def test_source_ref_display_pdf_without_page():
    assert _source_ref_display("pdf", r"C:\dossier\prog.pdf") == "prog.pdf"


def test_source_ref_display_web_and_text_unchanged():
    assert _source_ref_display("web", "https://example.com/x") == "https://example.com/x"
    assert _source_ref_display("text", "texte #1") == "texte #1"


def _make_classic_event() -> Event:
    """Event classique (mode normal) — sert de baseline pour les comparaisons."""
    return Event(
        tapeur_email="lebidul@live.fr",
        festival=None,
        date_label="Vendredi 22",
        date_iso="2026-05-22",
        times=["20h30"],
        venue="Le Chapiteau",
        city="Le Mans",
        price="10€",
        acts=[Act(genre=Genre.CONCERT, performer="Artist X")],
        source_kind="web",
        source_ref="https://example.com/x",
    )


def test_classic_event_unchanged():
    """Event classique : provenance en A/B, DATE/HEURE/LIEU remplis normalement."""
    row = event_to_row(_make_classic_event())
    assert row[0] == "URL"                       # TYPE SOURCE
    assert row[1] == "https://example.com/x"     # SOURCE
    assert row[2] == "lebidul@live.fr"           # INFO TAPEUR
    assert row[7] == "Vendredi 22"               # DATE
    assert row[8] == "20h30"                     # HEURE
    assert row[9] == "Le Chapiteau"              # LIEU
    assert row[10] == "Le Mans"                  # VILLE


def test_festival_event_uses_marker():
    """is_festival=True → DATE="Festivals", HEURE/LIEU vides."""
    ev = Event(
        tapeur_email="lebidul@live.fr",
        festival="Festival Kikloche",
        festival_style="Festival de petites formes spectaculaires à la campagne. Du 27 au 28 juin au cœur du village.",
        date_label="27-28 juin",         # ignoré au CSV en mode festival
        date_iso="2026-06-27",            # utilisé en interne (filtrage par mois)
        times=["?"],                      # ignoré au CSV
        venue="",                         # ignoré au CSV
        city="Saint-Aubin-de-Locquenay",
        price="voir site",
        is_festival=True,
        acts=[Act(
            genre=Genre.SPECTACLE_VIVANT,
            title="https://www.facebook.com/kikloche",
            performer="15 spectacles",
        )],
        source_kind="web",
        source_ref="https://example.com/kikloche",
    )
    row = event_to_row(ev)

    # FESTOCHE + STYLE FESTOCHE remplis
    assert row[5] == "Festival Kikloche"  # FESTOCHE
    assert "petites formes" in row[6]     # STYLE FESTOCHE

    # DATE = marqueur magique
    assert row[7] == FESTIVAL_DATE_MARKER  # DATE
    assert row[7] == "Festivals"

    # HEURE + LIEU vides
    assert row[8] == ""                   # HEURE
    assert row[9] == ""                   # LIEU

    # VILLE + PRIX + ACT 1 toujours rendus
    assert row[10] == "Saint-Aubin-de-Locquenay"
    assert row[11] == "voir site"
    assert row[12] == "sv"                # GENRE 1
    assert row[13] == "https://www.facebook.com/kikloche"  # NOM SPECTACLE 1
    assert row[14] == "15 spectacles"     # ARTISTE 1


def test_row_length_matches_n_acts_param():
    """event_to_row(ev, n_acts=N) → 12 cols base + 4*N cols acts."""
    ev = _make_classic_event()
    assert len(event_to_row(ev, n_acts=4)) == 12 + 4 * 4
    assert len(event_to_row(ev, n_acts=3)) == 12 + 4 * 3
    assert len(event_to_row(ev, n_acts=1)) == 12 + 4 * 1


def test_row_pads_empty_when_n_acts_exceeds_event_acts():
    """Si on demande 4 blocs mais l'event n'a qu'1 act, les 3 blocs suivants
    sont remplis de cellules vides."""
    ev = _make_classic_event()  # 1 act
    row = event_to_row(ev, n_acts=4)
    assert row[12] == "c"                 # GENRE 1 (act 1)
    assert row[16:20] == ["", "", "", ""]  # act 2 vide
    assert row[20:24] == ["", "", "", ""]  # act 3 vide
    assert row[24:28] == ["", "", "", ""]  # act 4 vide


# ---------- Fingerprint ----------

def test_fingerprint_classic_event():
    """Mode classique : (date, premier horaire, lieu, premier artiste)."""
    ev = _make_classic_event()
    assert ev.fingerprint() == "2026-05-22|20h30|le chapiteau|artist x"


def test_fingerprint_festival_uses_festival_name():
    """Mode festival : (nom du festival, ville) — venue/times ignorés."""
    ev = _make_classic_event()
    ev.is_festival = True
    ev.festival = "Festival Kikloche"
    ev.city = "Saint-Aubin-de-Locquenay"
    assert ev.fingerprint() == "festival:festival kikloche|saint-aubin-de-locquenay"


# ---------- export_csv : nombre de colonnes dynamique ----------

def _make_event_with_n_acts(n: int) -> Event:
    """Helper : event avec exactement n acts pour tester le dynamique."""
    acts = [
        Act(genre=Genre.CONCERT, performer=f"Artist {i}", title=f"Show {i}")
        for i in range(n)
    ]
    return Event(
        tapeur_email="lebidul@live.fr",
        date_label="Vendredi 22",
        date_iso="2026-05-22",
        times=["20h30"],
        venue="Le Chapiteau",
        city="Le Mans",
        price="10€",
        acts=acts,
        source_kind="web",
        source_ref=f"https://example.com/{n}",
    )


def test_make_headers_dynamic_count():
    """_make_headers(n) renvoie 12 cols base + 4*n cols acts."""
    h1 = _make_headers(1)
    assert len(h1) == 12 + 4
    assert h1[12:16] == ["GENRE 1", "NOM SPECTACLE 1", "ARTISTE 1", "STYLE 1"]

    h7 = _make_headers(7)
    assert len(h7) == 12 + 4 * 7
    assert h7[-4:] == ["GENRE 7", "NOM SPECTACLE 7", "ARTISTE 7", "STYLE 7"]


def test_export_csv_uses_max_acts_across_events(tmp_path: Path):
    """Le CSV a max(len(acts) sur events) blocs ACT, toutes les lignes paddées."""
    evs = [
        _make_event_with_n_acts(2),
        _make_event_with_n_acts(7),  # max
        _make_event_with_n_acts(1),
    ]
    out = tmp_path / "preview.csv"
    export_csv(evs, out)

    lines = out.read_text(encoding="utf-8").strip().split("\n")
    header_cols = lines[0].split(";")
    assert len(header_cols) == 12 + 4 * 7  # 7 blocs ACT
    # Toutes les lignes ont le même nombre de colonnes
    for line in lines[1:]:
        assert len(line.split(";")) == len(header_cols)


def test_export_csv_empty_events_uses_min_one_act_block(tmp_path: Path):
    """Liste vide → header avec 1 bloc ACT (cohérent avec sheet biduleur)."""
    out = tmp_path / "preview.csv"
    export_csv([], out)
    header_cols = out.read_text(encoding="utf-8").strip().split(";")
    assert len(header_cols) == 12 + 4 * 1


# ---------- Fingerprints (préservés) ----------

def test_fingerprint_two_different_festivals_same_city_distinct():
    """Deux festivals différents même ville → fingerprints distincts (pas dédupliqués)."""
    a = _make_classic_event()
    a.is_festival = True
    a.festival = "Festival A"
    a.city = "Le Mans"

    b = _make_classic_event()
    b.is_festival = True
    b.festival = "Festival B"
    b.city = "Le Mans"

    assert a.fingerprint() != b.fingerprint()
