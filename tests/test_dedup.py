"""Tests du dedup amélioré (normalisation horaires + 2 passes strict/weak)."""
from __future__ import annotations

import pytest

from tapageur.dedup import canonicalize, dedup, group_events
from tapageur.schema import Act, Event, Genre, _normalize_time


# ---------- _normalize_time ----------

@pytest.mark.parametrize("raw,expected", [
    ("20h", "20h00"),
    ("20h00", "20h00"),
    ("9h30", "09h30"),
    ("21 h 00", "21h00"),
    ("21H", "21h00"),
    ("8h05", "08h05"),
    ("", ""),
    ("à 20h30 ou 22h", "à 20h30 ou 22h"),  # format inconnu : passthrough
])
def test_normalize_time(raw, expected):
    assert _normalize_time(raw) == expected


# ---------- Helpers ----------

def _make_event(time: str = "20h30", venue: str = "Le Chapiteau",
                performer: str = "Artist X", date_iso: str = "2026-08-20",
                source_ref: str = "src1") -> Event:
    return Event(
        tapeur_email="lebidul@live.fr",
        date_label="Jeudi 20",
        date_iso=date_iso,
        times=[time],
        venue=venue,
        city="Le Mans",
        price="gratuit",
        acts=[Act(genre=Genre.SPECTACLE_VIVANT, performer=performer)],
        source_kind="web",
        source_ref=source_ref,
    )


# ---------- Dedup pass 1 (strict) ----------

def test_dedup_strict_keeps_first():
    a = _make_event(source_ref="A")
    b = _make_event(source_ref="B")  # tout identique
    result = dedup([a, b])
    assert len(result) == 1
    assert result[0].source_ref == "A"


def test_dedup_strict_distinguishes_different_performers():
    a = _make_event(performer="X", source_ref="A")
    b = _make_event(performer="Y", source_ref="B")
    result = dedup([a, b])
    assert len(result) == 2


def test_dedup_time_normalization_catches_format_difference():
    """20h vs 20h00 doivent matcher après normalisation."""
    a = _make_event(time="20h", source_ref="A")
    b = _make_event(time="20h00", source_ref="B")
    result = dedup([a, b])
    assert len(result) == 1


# ---------- Dedup pass 2 (weak / performer=?) ----------

def test_dedup_weak_drops_unknown_performer_if_strict_exists():
    """Event avec performer=? matche un event strict identique (date/time/venue)
    avec performer connu → drop le weak."""
    strict = _make_event(performer="Théâtre en actes", source_ref="of_course")
    weak = _make_event(performer="?", source_ref="les_soirs")
    result = dedup([weak, strict])
    assert len(result) == 1
    # Le strict est gardé, pas le weak
    assert result[0].acts[0].performer == "Théâtre en actes"


def test_dedup_weak_dropped_even_if_processed_first():
    """L'ordre ne compte pas : que le weak soit avant ou après le strict,
    c'est lui qui est dropé."""
    strict = _make_event(performer="Théâtre en actes", source_ref="of_course")
    weak = _make_event(performer="?", source_ref="les_soirs")
    result = dedup([strict, weak])  # ordre inverse
    assert len(result) == 1
    assert result[0].acts[0].performer == "Théâtre en actes"


def test_dedup_weak_kept_if_no_strict_match():
    """Si aucun event strict ne matche (date/time/venue), le weak est gardé."""
    weak = _make_event(performer="?", source_ref="W")
    other = _make_event(time="21h00", performer="Y", source_ref="Other")  # heure différente
    result = dedup([weak, other])
    assert len(result) == 2


def test_dedup_two_weak_events_both_kept():
    """2 events avec performer=? mais venue différent → ne se matchent pas
    entre eux et n'ont pas de strict à matcher → tous les 2 gardés."""
    w1 = _make_event(performer="?", venue="Venue A", source_ref="W1")
    w2 = _make_event(performer="?", venue="Venue B", source_ref="W2")
    result = dedup([w1, w2])
    assert len(result) == 2


# ---------- Cas concret du user (Andromaque) ----------

# ---------- group_events ----------

def _make_event_full(time: str, title: str, performer: str,
                     festival: str = "Of course Le Mans",
                     festival_style: str = "Arts de rue",
                     venue: str = "Parc de Verdigné",
                     date_iso: str = "2026-08-13",
                     price: str = "?",
                     source_ref: str = "x") -> Event:
    return Event(
        tapeur_email="lebidul@live.fr",
        festival=festival,
        festival_style=festival_style,
        date_label="Jeudi 13",
        date_iso=date_iso,
        times=[time],
        venue=venue,
        city="Le Mans",
        price=price,
        acts=[Act(genre=Genre.SPECTACLE_VIVANT, title=title, performer=performer,
                  style="Clown / Arts de rue")],
        source_kind="web",
        source_ref=source_ref,
    )


def test_group_events_user_case():
    """Cas concret donné par l'utilisateur : 4 spectacles successifs Of Course
    au Parc de Verdigné le jeudi 13 → 1 event avec 4 acts à 18h30."""
    events = [
        _make_event_full("18h30", "Pestacle El Chuflini", "Association Artifis",
                         source_ref="card1"),
        _make_event_full("19h30", "Le GOP", "Cie Gorgomar", source_ref="card2"),
        _make_event_full("20h00", "MARGO", "Cie Clinamen", source_ref="card3"),
        _make_event_full("21h00", "Brassens à la folie", "Association Artifis",
                         source_ref="card4"),
    ]
    result = group_events(events)
    assert len(result) == 1
    ev = result[0]
    assert ev.times == ["18h30"]  # horaire de départ
    assert len(ev.acts) == 4
    titles = [a.title for a in ev.acts]
    assert titles == ["Pestacle El Chuflini", "Le GOP", "MARGO", "Brassens à la folie"]


def test_group_events_more_than_4_acts_split_in_blocks():
    """6 events partageant festival/date/venue → 2 events fusionnés (4 + 2)."""
    events = [
        _make_event_full(f"{18 + i}h00", f"Show {i}", f"Artist {i}",
                         source_ref=f"src{i}")
        for i in range(6)
    ]
    result = group_events(events)
    assert len(result) == 2
    assert len(result[0].acts) == 4
    assert len(result[1].acts) == 2
    # 1er bloc : heure de départ du 1er event
    assert result[0].times == ["18h00"]
    # 2e bloc : heure de départ du 5e event (chronologiquement)
    assert result[1].times == ["22h00"]


def test_group_events_different_venues_not_merged():
    """Même festival, même date mais venues différents → pas de groupement."""
    a = _make_event_full("18h00", "X", "Artist1", venue="Venue A")
    b = _make_event_full("19h00", "Y", "Artist2", venue="Venue B")
    result = group_events([a, b])
    assert len(result) == 2


def test_group_events_no_festival_not_grouped():
    """Sans festival, on ne groupe pas (risque de fusion erronée)."""
    a = _make_event_full("18h00", "X", "Artist1", festival="", source_ref="A")
    b = _make_event_full("19h00", "Y", "Artist2", festival="", source_ref="B")
    # festival="" → None côté Event (mais le validator accepte None)
    a.festival = None
    b.festival = None
    result = group_events([a, b])
    assert len(result) == 2


def test_group_events_price_picks_first_non_question_mark():
    """Si un des events a un prix réel, il l'emporte sur '?'."""
    a = _make_event_full("18h00", "X", "Artist1", price="?", source_ref="A")
    b = _make_event_full("19h00", "Y", "Artist2", price="gratuit", source_ref="B")
    result = group_events([a, b])
    assert len(result) == 1
    assert result[0].price == "gratuit"


def test_group_events_single_event_unchanged():
    """Un seul event dans le groupe → renvoyé tel quel."""
    e = _make_event_full("18h00", "X", "Artist1")
    result = group_events([e])
    assert len(result) == 1
    assert result[0] is e or result[0].times == ["18h00"]


def test_group_events_preserves_input_order_for_ungrouped():
    """L'ordre relatif des events non groupés doit être préservé."""
    a = _make_event_full("18h00", "A", "Artist A", festival="Fest1", venue="V1")
    b = _make_event_full("18h00", "B", "Artist B", festival="Fest2", venue="V2")
    c = _make_event_full("18h00", "C", "Artist C", festival="Fest3", venue="V3")
    result = group_events([a, b, c])
    assert [r.acts[0].title for r in result] == ["A", "B", "C"]


# ---------- Test original (Andromaque) ----------

def test_dedup_andromaque_real_case():
    """Cas observé : Andromaque jeudi 20 août au Vieux Colombier.
    Source A (Les Soirs d'été) : performer="?" et heure "20h"
    Source B (Of course Le Mans) : performer="Théâtre en actes" et heure "20h00"
    Doit fusionner en gardant B après canonicalize du venue.
    """
    soirs = Event(
        tapeur_email="x@y.fr",
        festival="Les Soirs d'été",
        date_label="Jeudi 20",
        date_iso="2026-08-20",
        times=["20h"],
        venue="Collège Vieux Colombier",  # forme courte
        city="Le Mans",
        price="gratuit",
        acts=[Act(genre=Genre.SPECTACLE_VIVANT, title="Andromaque", performer="?")],
        source_kind="pdf",
        source_ref="lemans_guide.pdf",
    )
    ofcourse = Event(
        tapeur_email="x@y.fr",
        festival="Of course Le Mans",
        date_label="Jeudi 20 août",
        date_iso="2026-08-20",
        times=["20h00"],
        venue="Collège du Vieux Colombier",  # forme canonique
        city="Le Mans",
        price="?",
        acts=[Act(genre=Genre.SPECTACLE_VIVANT, title="Andromaque",
                  performer="Théâtre en actes")],
        source_kind="web",
        source_ref="msj.world/...",
    )

    # 1) Simule canonicalize du venue via mappings
    mappings = {
        "venues": {
            "Collège du Vieux Colombier": [
                "Collège Vieux Colombier",
                "Cour du Collège du Vieux Colombier",
            ]
        }
    }
    events = canonicalize([soirs, ofcourse], mappings)

    # Vérif : venues alignés après canonicalize
    assert events[0].venue == "Collège du Vieux Colombier"
    assert events[1].venue == "Collège du Vieux Colombier"

    # 2) Dedup
    result = dedup(events)
    assert len(result) == 1
    assert result[0].acts[0].performer == "Théâtre en actes"  # le strict gagne
