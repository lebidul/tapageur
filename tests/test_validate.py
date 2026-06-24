"""Tests de l'export CSV (event_to_row) — focalisés sur le mode festival."""
from __future__ import annotations

from tapageur.schema import Act, Event, Genre
from tapageur.validate import FESTIVAL_DATE_MARKER, HEADERS, event_to_row


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
    """Event classique : DATE/HEURE/LIEU remplis normalement."""
    row = event_to_row(_make_classic_event())
    assert row[5] == "Vendredi 22"      # DATE
    assert row[6] == "20h30"             # HEURE
    assert row[7] == "Le Chapiteau"      # LIEU
    assert row[8] == "Le Mans"           # VILLE


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
    assert row[3] == "Festival Kikloche"  # FESTOCHE
    assert "petites formes" in row[4]     # STYLE FESTOCHE

    # DATE = marqueur magique
    assert row[5] == FESTIVAL_DATE_MARKER  # DATE
    assert row[5] == "Festivals"

    # HEURE + LIEU vides
    assert row[6] == ""                   # HEURE
    assert row[7] == ""                   # LIEU

    # VILLE + PRIX + ACT 1 toujours rendus
    assert row[8] == "Saint-Aubin-de-Locquenay"
    assert row[9] == "voir site"
    assert row[10] == "sv"                # GENRE 1
    assert row[11] == "https://www.facebook.com/kikloche"  # NOM SPECTACLE 1
    assert row[12] == "15 spectacles"     # ARTISTE 1


def test_row_length_matches_headers():
    """Une row a toujours autant de colonnes que HEADERS, mode festival ou pas."""
    assert len(event_to_row(_make_classic_event())) == len(HEADERS)

    fest_event = _make_classic_event()
    fest_event.is_festival = True
    fest_event.festival = "X"
    assert len(event_to_row(fest_event)) == len(HEADERS)


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
