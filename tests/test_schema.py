"""Tests basiques sur le schéma."""
from tapageur.schema import Act, CollectedItem, Event, Genre


def test_collected_item_accepts_text_kind():
    item = CollectedItem(
        source_kind="text", source_ref="texte #1",
        fetched_at="2026-01-01T00:00:00Z", raw_text="concert demain",
        raw_metadata={},
    )
    assert item.source_kind == "text"


def test_event_fingerprint():
    ev = Event(
        tapeur_email="lebidul@live.fr",
        date_label="Vendredi 22",
        date_iso="2026-05-22",
        times=["18h30", "20h30"],
        venue="Le Chapiteau",
        city="Le Mans",
        price="5 à 10€",
        acts=[Act(genre=Genre.SPECTACLE_VIVANT, performer="Les élèves du Plongeoir")],
        source_kind="web",
        source_ref="https://leplongeoir-cirque.fr/agenda/eclats-de-cirque-0",
    )
    assert ev.fingerprint() == "2026-05-22|18h30|le chapiteau|les élèves du plongeoir"
    assert ev.time_str() == "18h30 & 20h30"


def test_event_at_least_one_act():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Event(
            tapeur_email="x@y.z", date_label="L1", date_iso="2026-05-01",
            times=["20h"], venue="X", city="Y", price="?",
            acts=[],
            source_kind="web", source_ref="x",
        )
