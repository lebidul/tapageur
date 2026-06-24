"""Tests du dedup amélioré (normalisation horaires + 2 passes strict/weak)."""
from __future__ import annotations

import pytest

from tapageur.dedup import canonicalize, dedup
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
