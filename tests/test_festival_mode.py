"""Tests du routage mode festival_onliner — connecteurs, cache, normalize, batch.

Pas d'appel Claude réel : on vérifie juste la sélection du prompt et la clé
cache. Le rendu du prompt en sortie de Claude est testé par la qualité du
résultat au moment des runs réels.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from tapageur import cache as cache_mod
from tapageur.batch import _build_request
from tapageur.connectors.web import WebConnector
from tapageur.normalize import FESTIVAL_SYSTEM_PROMPT, SYSTEM_PROMPT
from tapageur.schema import CollectedItem


def _item(mode: str | None = None) -> CollectedItem:
    meta = {"site": "x"}
    if mode:
        meta["mode"] = mode
    return CollectedItem(
        source_kind="web",
        source_ref="https://example.com/festival",
        fetched_at="2026-06-01T12:00:00Z",
        raw_text="festival eldorado, 26-28 juin",
        raw_metadata=meta,
    )


# ---------- Cache key inclut le mode ----------

def test_cache_key_classic_vs_festival_distinct():
    """Même contenu, même mois, modes différents → clés cache distinctes."""
    classic = _item(mode=None)
    festival = _item(mode="festival_onliner")
    assert cache_mod.cache_key(classic, "2026-06") != cache_mod.cache_key(festival, "2026-06")


def test_cache_key_classic_unchanged_for_compat():
    """Mode classique (mode absent) garde la clé historique.
    Sinon ajouter le flag mode invaliderait tout le cache existant."""
    item_classic = CollectedItem(
        source_kind="web", source_ref="https://x.fr",
        fetched_at="2026-06-01T12:00:00Z", raw_text="hello",
        raw_metadata={"site": "x"},  # pas de "mode"
    )
    item_with_explicit_none = CollectedItem(
        source_kind="web", source_ref="https://x.fr",
        fetched_at="2026-06-01T12:00:00Z", raw_text="hello",
        raw_metadata={"site": "x", "mode": None},  # mode présent mais None
    )
    # Tous deux résolvent à "classique"
    assert cache_mod.cache_key(item_classic, "2026-06") == cache_mod.cache_key(item_with_explicit_none, "2026-06")


# ---------- Connecteur web propage mode ----------

def test_web_connector_propagates_mode_no_follow(monkeypatch):
    """Mode mono-page (follow=False) : raw_metadata['mode'] doit être propagé."""
    fake_html = "<html><body>Festival X, juin 2026</body></html>"
    with patch("tapageur.connectors.web._fetch", return_value=fake_html):
        cfg = {"websites": [{
            "name": "festival_x",
            "url": "https://festx.fr/",
            "follow_event_links": False,
            "mode": "festival_onliner",
        }]}
        conn = WebConnector(cfg)
        items = list(conn.collect("2026-06"))

    assert len(items) == 1
    assert items[0].raw_metadata.get("mode") == "festival_onliner"


def test_web_connector_no_mode_when_absent(monkeypatch):
    """Si pas de mode dans la config, raw_metadata['mode'] absent (pas None)."""
    fake_html = "<html><body>concerts juin</body></html>"
    with patch("tapageur.connectors.web._fetch", return_value=fake_html):
        cfg = {"websites": [{
            "name": "site_classique",
            "url": "https://x.fr/",
            "follow_event_links": False,
            # pas de mode
        }]}
        conn = WebConnector(cfg)
        items = list(conn.collect("2026-06"))

    assert len(items) == 1
    assert "mode" not in items[0].raw_metadata


# ---------- Batch.._build_request route le bon prompt ----------

def test_batch_build_request_uses_festival_prompt():
    """mode='festival_onliner' → system prompt = FESTIVAL_SYSTEM_PROMPT."""
    item = _item(mode="festival_onliner")
    req = _build_request(item, "2026-06")
    assert req["params"]["system"] == FESTIVAL_SYSTEM_PROMPT


def test_batch_build_request_uses_classic_prompt_by_default():
    """Pas de mode → SYSTEM_PROMPT classique."""
    item = _item(mode=None)
    req = _build_request(item, "2026-06")
    assert req["params"]["system"] == SYSTEM_PROMPT


def test_batch_build_request_unknown_mode_falls_back_to_classic():
    """Mode inconnu (ex. typo) → fallback classique (safe default)."""
    item = _item(mode="festival_typo_xxx")
    req = _build_request(item, "2026-06")
    assert req["params"]["system"] == SYSTEM_PROMPT
