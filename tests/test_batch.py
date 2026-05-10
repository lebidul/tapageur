"""Tests du pipeline batch (tapageur.batch).

Couvre :
- Persistance batch_state (save/load/clear, atomic write).
- Court-circuit "tout en cache" (submit ne touche pas l'API).
- Construction des requests (model par source_kind, custom_id déterministe).
- Garde-fou anti-doublon (submit avec batch déjà en cours).

Les chemins qui touchent vraiment l'API (submit avec miss / retrieve) ne sont
pas testés ici — ils nécessitent un mock complet d'Anthropic SDK qu'on
préfère reporter à un test d'intégration manuel.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tapageur import batch as batch_mod
from tapageur import cache as cache_mod
from tapageur.schema import Act, CollectedItem, Event, Genre


@pytest.fixture
def tmp_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isole cache + cwd dans tmp pour ne pas polluer le repo."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cache_mod, "CACHE_ROOT", tmp_path / "cache" / "normalize")
    return tmp_path


def _make_item(ref: str = "https://example.com/event/1", text: str = "raw text") -> CollectedItem:
    return CollectedItem(
        source_kind="web",
        source_ref=ref,
        fetched_at="2026-05-10T12:00:00Z",
        raw_text=text,
    )


def _make_event() -> Event:
    return Event(
        tapeur_email="lebidul@live.fr",
        date_label="V15", date_iso="2026-05-15",
        times=["20h30"], venue="Le Chapiteau", city="Le Mans",
        price="10€",
        acts=[Act(genre=Genre.CONCERT, performer="X")],
        source_kind="web", source_ref="https://example.com/event/1",
    )


def test_state_roundtrip(tmp_workspace: Path):
    state = {"batch_id": "msgbatch_abc", "month": "2026-05", "items": []}
    batch_mod.save_batch_state("2026-05", state)

    got = batch_mod.load_batch_state("2026-05")
    assert got == state


def test_load_returns_none_when_absent(tmp_workspace: Path):
    assert batch_mod.load_batch_state("2026-05") is None


def test_clear_state(tmp_workspace: Path):
    batch_mod.save_batch_state("2026-05", {"batch_id": "x", "month": "2026-05"})
    assert batch_mod.load_batch_state("2026-05") is not None

    batch_mod.clear_batch_state("2026-05")
    assert batch_mod.load_batch_state("2026-05") is None


def test_clear_state_when_absent_is_noop(tmp_workspace: Path):
    # Ne doit pas lever.
    batch_mod.clear_batch_state("2026-05")


def test_submit_shortcircuits_when_all_cached(tmp_workspace: Path):
    """Si tous les items sont déjà en cache, pas d'appel API."""
    items = [_make_item("https://a.com/1"), _make_item("https://a.com/2")]
    for it in items:
        cache_mod.set_cached(it, "2026-05", [_make_event()])

    state = batch_mod.submit_batch(items, "2026-05")

    assert state["batch_id"] is None
    assert state["items"] == []
    # State persisté sur disque.
    assert batch_mod.load_batch_state("2026-05") == state


def test_submit_refuses_when_batch_already_pending(tmp_workspace: Path):
    """Garde-fou : ne pas soumettre 2x si un batch est en cours."""
    batch_mod.save_batch_state("2026-05", {"batch_id": "msgbatch_existing", "month": "2026-05", "items": []})

    with pytest.raises(RuntimeError, match="Un batch existe déjà"):
        batch_mod.submit_batch([_make_item()], "2026-05")


def test_submit_allows_when_state_is_shortcircuit(tmp_workspace: Path):
    """Un state {batch_id: None} (court-circuit) ne bloque PAS un nouveau submit
    si le user ajoute des sources : le garde-fou ne kicke que sur batch_id non-null."""
    batch_mod.save_batch_state("2026-05", {
        "batch_id": None, "month": "2026-05", "items": [],
        "note": "all cached, no batch submitted",
    })

    # Re-submit avec tout caché → doit passer (re-court-circuit).
    item = _make_item()
    cache_mod.set_cached(item, "2026-05", [_make_event()])
    state = batch_mod.submit_batch([item], "2026-05")
    assert state["batch_id"] is None


def test_build_request_uses_model_by_kind(tmp_workspace: Path):
    """Une request batch utilise le bon modèle selon source_kind."""
    web_item = CollectedItem(source_kind="web", source_ref="x", fetched_at="t", raw_text="x")
    pdf_item = CollectedItem(source_kind="pdf", source_ref="y", fetched_at="t", raw_text="y")

    req_web = batch_mod._build_request(web_item, "2026-05")
    req_pdf = batch_mod._build_request(pdf_item, "2026-05")

    assert "sonnet" in req_web["params"]["model"]
    assert "opus" in req_pdf["params"]["model"]


def test_build_request_custom_id_matches_cache_key(tmp_workspace: Path):
    """Le custom_id doit être égal à cache_key (sinon retrieve ne retrouve rien)."""
    item = _make_item()
    req = batch_mod._build_request(item, "2026-05")
    assert req["custom_id"] == cache_mod.cache_key(item, "2026-05")


def test_retrieve_raises_when_no_state(tmp_workspace: Path):
    with pytest.raises(RuntimeError, match="Aucun batch en attente"):
        batch_mod.retrieve_batch([_make_item()], "2026-05")


def test_retrieve_shortcircuit_state_uses_cache(tmp_workspace: Path):
    """Si le state indique 'all cached' (batch_id=None), retrieve assemble
    depuis le cache sans toucher l'API."""
    item = _make_item()
    cache_mod.set_cached(item, "2026-05", [_make_event()])
    batch_mod.save_batch_state("2026-05", {
        "batch_id": None, "month": "2026-05", "items": [],
    })

    events = batch_mod.retrieve_batch([item], "2026-05")

    assert len(events) == 1
    assert events[0].date_iso == "2026-05-15"
    # State nettoyé après succès.
    assert batch_mod.load_batch_state("2026-05") is None
