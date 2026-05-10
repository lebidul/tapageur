"""Tests du cache file-based normalize (tapageur.cache)."""
from __future__ import annotations

from pathlib import Path

import pytest

from tapageur import cache as cache_mod
from tapageur.schema import Act, CollectedItem, Event, Genre


@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirige CACHE_ROOT vers un tmp dir pour isoler les tests."""
    target = tmp_path / "normalize"
    monkeypatch.setattr(cache_mod, "CACHE_ROOT", target)
    return target


def _make_item(text: str = "raw page text", ref: str = "https://example.com/event/1") -> CollectedItem:
    return CollectedItem(
        source_kind="web",
        source_ref=ref,
        fetched_at="2026-05-10T12:00:00Z",
        raw_text=text,
        raw_metadata={"site": "Example"},
    )


def _make_event(date_iso: str = "2026-05-15") -> Event:
    return Event(
        tapeur_email="lebidul@live.fr",
        date_label="Vendredi 15",
        date_iso=date_iso,
        times=["20h30"],
        venue="Le Chapiteau",
        city="Le Mans",
        price="10€",
        acts=[Act(genre=Genre.CONCERT, performer="Artist X")],
        source_kind="web",
        source_ref="https://example.com/event/1",
    )


def test_cache_miss_when_absent(tmp_cache: Path):
    item = _make_item()
    assert cache_mod.get_cached(item, "2026-05") is None


def test_cache_roundtrip(tmp_cache: Path):
    """set puis get → on récupère exactement les events stockés."""
    item = _make_item()
    events = [_make_event("2026-05-15"), _make_event("2026-05-22")]

    cache_mod.set_cached(item, "2026-05", events)
    got = cache_mod.get_cached(item, "2026-05")

    assert got is not None
    assert len(got) == 2
    assert got[0].date_iso == "2026-05-15"
    assert got[1].date_iso == "2026-05-22"
    assert got[0].acts[0].performer == "Artist X"


def test_cache_invalidates_on_content_change(tmp_cache: Path):
    """Si le raw_text change (page mise à jour), c'est un cache miss."""
    item_v1 = _make_item(text="version 1 of the page")
    item_v2 = _make_item(text="version 2 of the page")  # même URL, contenu différent

    cache_mod.set_cached(item_v1, "2026-05", [_make_event()])
    assert cache_mod.get_cached(item_v1, "2026-05") is not None
    assert cache_mod.get_cached(item_v2, "2026-05") is None


def test_cache_separates_by_month(tmp_cache: Path):
    """Même item, mois différent → entrées distinctes (filtrage Claude par mois)."""
    item = _make_item()
    cache_mod.set_cached(item, "2026-05", [_make_event("2026-05-15")])
    cache_mod.set_cached(item, "2026-06", [_make_event("2026-06-10")])

    may = cache_mod.get_cached(item, "2026-05")
    jun = cache_mod.get_cached(item, "2026-06")

    assert may is not None and len(may) == 1 and may[0].date_iso == "2026-05-15"
    assert jun is not None and len(jun) == 1 and jun[0].date_iso == "2026-06-10"


def test_cache_separates_by_source_ref(tmp_cache: Path):
    """Deux URLs différentes ne se mélangent pas."""
    item_a = _make_item(ref="https://example.com/event/1")
    item_b = _make_item(ref="https://example.com/event/2")

    cache_mod.set_cached(item_a, "2026-05", [_make_event("2026-05-01")])
    assert cache_mod.get_cached(item_a, "2026-05") is not None
    assert cache_mod.get_cached(item_b, "2026-05") is None


def test_cache_empty_events_list(tmp_cache: Path):
    """Un item dont Claude n'a rien extrait : on cache quand même []
    (évite de re-call Claude pour rien)."""
    item = _make_item()
    cache_mod.set_cached(item, "2026-05", [])

    got = cache_mod.get_cached(item, "2026-05")
    assert got is not None
    assert got == []


def test_cache_handles_corrupt_file(tmp_cache: Path):
    """Fichier corrompu (JSON invalide) → traité comme miss, pas d'exception."""
    item = _make_item()
    key = cache_mod.cache_key(item, "2026-05")
    tmp_cache.mkdir(parents=True, exist_ok=True)
    (tmp_cache / f"{key}.json").write_text("{not valid json", encoding="utf-8")

    assert cache_mod.get_cached(item, "2026-05") is None


def test_cache_handles_image_items(tmp_cache: Path):
    """raw_image_b64 entre dans le content_hash (différent → miss)."""
    item_a = CollectedItem(
        source_kind="image", source_ref="flyer.jpg",
        fetched_at="2026-05-10T12:00:00Z",
        raw_image_b64="AAAA",
        raw_metadata={"mime": "image/jpeg"},
    )
    item_b = CollectedItem(
        source_kind="image", source_ref="flyer.jpg",
        fetched_at="2026-05-10T12:00:00Z",
        raw_image_b64="BBBB",  # image différente
        raw_metadata={"mime": "image/jpeg"},
    )

    cache_mod.set_cached(item_a, "2026-05", [_make_event()])
    assert cache_mod.get_cached(item_a, "2026-05") is not None
    assert cache_mod.get_cached(item_b, "2026-05") is None
