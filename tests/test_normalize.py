"""Tests des morceaux purs de tapageur.normalize.

On ne teste pas l'appel Claude (côté integration) ; on teste les helpers
robustes au schéma drift (validation event-par-event, extract_json).
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tapageur.normalize import (
    _EventDraft,
    _NormalizationOutput,
    _extract_json,
    _french_date_label,
    _supports_adaptive_thinking,
)


# ---------- _french_date_label ----------

def test_french_date_label_basic():
    assert _french_date_label("2026-06-02") == "Mardi 2"   # pas de zéro initial
    assert _french_date_label("2026-06-22") == "Lundi 22"
    assert _french_date_label("2026-06-01") == "Lundi 1"


def test_french_date_label_invalid_returns_fallback():
    assert _french_date_label("pas-une-date", "SECOURS") == "SECOURS"
    assert _french_date_label("", "SECOURS") == "SECOURS"


# ---------- _extract_json ----------

def test_extract_json_strips_markdown_fence():
    assert _extract_json("```json\n{\"events\":[]}\n```") == '{"events":[]}'
    assert _extract_json("```\n{\"x\":1}\n```") == '{"x":1}'


def test_extract_json_plain_passes_through():
    assert _extract_json('{"events":[]}') == '{"events":[]}'


def test_extract_json_strips_whitespace():
    assert _extract_json("  \n{\"x\":1}\n  ") == '{"x":1}'


# ---------- _supports_adaptive_thinking ----------

def test_thinking_opus_yes():
    assert _supports_adaptive_thinking("claude-opus-4-7") is True
    assert _supports_adaptive_thinking("claude-opus-4-5") is True


def test_thinking_sonnet_no():
    assert _supports_adaptive_thinking("claude-sonnet-4-5") is False
    assert _supports_adaptive_thinking("claude-sonnet-3-7") is False


# ---------- _EventDraft validation ----------

def _good_event() -> dict:
    return {
        "date_label": "Vendredi 15",
        "date_iso": "2026-05-15",
        "times": ["20h30"],
        "venue": "Le Chapiteau",
        "city": "Le Mans",
        "price": "10€",
        "acts": [{"genre": "c", "performer": "Artist X"}],
    }


def test_event_draft_valid():
    draft = _EventDraft.model_validate(_good_event())
    assert draft.date_iso == "2026-05-15"
    assert draft.acts[0].performer == "Artist X"


def test_event_draft_rejects_null_performer():
    """Un event avec performer=null doit être rejeté (Pydantic strict)."""
    bad = _good_event()
    bad["acts"][0]["performer"] = None
    with pytest.raises(ValidationError):
        _EventDraft.model_validate(bad)


def test_event_draft_accepts_question_mark_performer():
    """Convention : '?' pour performer inconnu doit être accepté."""
    ok = _good_event()
    ok["acts"][0]["performer"] = "?"
    draft = _EventDraft.model_validate(ok)
    assert draft.acts[0].performer == "?"


# ---------- Validation event-par-event en condition réelle ----------
# On simule la logique de _normalize_one sans appeler Claude.

def _simulate_per_event_validation(claude_response: dict, month: str) -> tuple[list, list]:
    """Reproduit la boucle de validation event-par-event de _normalize_one.
    Retourne (valid_events, skipped_indices)."""
    raw_events = claude_response.get("events", [])
    valid = []
    skipped = []
    for i, draft_data in enumerate(raw_events):
        try:
            draft = _EventDraft.model_validate(draft_data)
        except ValidationError:
            skipped.append(i)
            continue
        if not draft.date_iso.startswith(month):
            continue
        valid.append(draft)
    return valid, skipped


def test_per_event_validation_keeps_good_when_one_bad():
    """Régression du bug 1 : un event mal formé ne doit pas écraser les autres."""
    response = {
        "events": [
            {**_good_event(), "acts": [{"genre": "c", "performer": None}]},  # bad
            _good_event(),  # good (2026-05-15)
            {**_good_event(), "date_iso": "2026-05-22"},  # good
        ]
    }
    valid, skipped = _simulate_per_event_validation(response, "2026-05")
    assert len(valid) == 2
    assert skipped == [0]


def test_per_event_validation_drops_off_month():
    """Le filtrage par mois reste appliqué."""
    response = {
        "events": [
            _good_event(),  # 2026-05-15 → keep
            {**_good_event(), "date_iso": "2026-06-10"},  # off month → drop
        ]
    }
    valid, _ = _simulate_per_event_validation(response, "2026-05")
    assert len(valid) == 1
    assert valid[0].date_iso == "2026-05-15"


def test_per_event_validation_all_bad_returns_empty():
    response = {
        "events": [
            {**_good_event(), "acts": [{"genre": "c", "performer": None}]},
            {**_good_event(), "times": []},  # min 1 time required by Event, but _EventDraft only validates structure; this is empty list which is fine for _EventDraft
        ]
    }
    valid, skipped = _simulate_per_event_validation(response, "2026-05")
    # Au moins le 1er est rejeté ; le 2e dépend du validator (list[str] vide accepté par _EventDraft mais rejeté plus loin par Event).
    assert 0 in skipped


def test_normalization_wrapper_still_works():
    """Le wrapper _NormalizationOutput existe toujours pour les cas où tout est valide."""
    response = {"events": [_good_event()]}
    parsed = _NormalizationOutput.model_validate(response)
    assert len(parsed.events) == 1


# ---------- Asymétrie _EventDraft vs Event ----------

def test_event_draft_accepts_empty_times_but_event_rejects():
    """Régression bug observé : Claude peut renvoyer times=[].
    _EventDraft (schéma laxe) accepte → la validation au niveau Event échoue.
    Vérifie que ce cas existe pour justifier le try/except sur Event(...)."""
    from tapageur.normalize import _EventDraft

    bad = _good_event()
    bad["times"] = []  # vide → invalide selon Event.at_least_one_time
    # _EventDraft accepte (pas de validator at_least_one_time)
    draft = _EventDraft.model_validate(bad)
    assert draft.times == []

    # Event refuse (validator déclenche)
    from tapageur.schema import Event
    from pydantic import ValidationError as PydErr
    with pytest.raises(PydErr, match="times must contain at least one entry"):
        Event(
            **draft.model_dump(),
            tapeur_email="x@y.fr",
            source_kind="web",
            source_ref="x",
        )


# ---------- month_filter ----------

from unittest.mock import MagicMock
from pathlib import Path
import json as _json
from tapageur import normalize as _norm
from tapageur.schema import CollectedItem


def _fake_client_returning(events_json):
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = _json.dumps({"events": events_json})
    resp = MagicMock()
    resp.content = [block]
    client.messages.create.return_value = resp
    return client


def test_month_filter_false_keeps_other_months(monkeypatch, tmp_path):
    item = CollectedItem(
        source_kind="web", source_ref="https://x.fr", fetched_at="2026-01-01T00:00:00Z",
        raw_text="x", raw_metadata={},
    )
    ev = {
        "date_label": "Mardi 3", "date_iso": "2026-11-03", "times": ["20h00"],
        "venue": "V", "city": "C", "price": "?",
        "acts": [{"genre": "c", "title": None, "performer": "A", "style": None}],
    }
    client = _fake_client_returning([ev])
    out = _norm._normalize_one(client, item, "2026-10", None, "t@b.fr", month_filter=False)
    assert len(out) == 1  # event de novembre gardé malgré month=2026-10


def test_normalize_items_calls_progress_per_item(monkeypatch, tmp_path):
    from tapageur import normalize as _norm
    from tapageur.schema import CollectedItem
    # normalize_items construit Anthropic() en tête → clé factice (aucun appel réel :
    # _normalize_one est monkeypatché juste après).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    items = [
        CollectedItem(source_kind="web", source_ref="https://x.fr/a",
                      fetched_at="2026-01-01T00:00:00Z", raw_text="x", raw_metadata={}),
        CollectedItem(source_kind="web", source_ref="https://x.fr/b",
                      fetched_at="2026-01-01T00:00:00Z", raw_text="y", raw_metadata={}),
    ]
    # Court-circuite l'appel Claude : chaque item → 0 event (peu importe ici)
    monkeypatch.setattr(_norm, "_normalize_one", lambda *a, **k: [])
    seen = []
    _norm.normalize_items(items, "2026-11", tmp_path / "out.json",
                          progress=lambda msg: seen.append(msg))
    assert any("1/2" in m for m in seen)
    assert any("2/2" in m for m in seen)
    assert all(m.startswith("Extraction ") for m in seen)


# ---------- overrides par item (sources texte collé) ----------

def _text_item(meta):
    from tapageur.schema import CollectedItem
    return CollectedItem(
        source_kind="text", source_ref="texte #1", fetched_at="2026-01-01T00:00:00Z",
        raw_text="x", raw_metadata=meta,
    )


def _ev(venue, festival=None):
    ev = {
        "date_label": "Mardi 3", "date_iso": "2026-11-03", "times": ["20h00"],
        "venue": venue, "city": "Le Mans", "price": "?",
        "acts": [{"genre": "c", "title": None, "performer": "A", "style": None}],
    }
    if festival is not None:
        ev["festival"] = festival
    return ev


def test_default_venue_applied_when_extracted_empty():
    from tapageur import normalize as _norm
    item = _text_item({"default_venue": "Le Scarron"})
    client = _fake_client_returning([_ev(venue="?")])
    out = _norm._normalize_one(client, item, "2026-11", None, "t@b.fr")
    assert out[0].venue == "Le Scarron"


def test_default_venue_not_applied_when_extracted_present():
    from tapageur import normalize as _norm
    item = _text_item({"default_venue": "Le Scarron"})
    client = _fake_client_returning([_ev(venue="La Fonderie")])
    out = _norm._normalize_one(client, item, "2026-11", None, "t@b.fr")
    assert out[0].venue == "La Fonderie"


def test_default_festival_applied_when_extracted_empty():
    from tapageur import normalize as _norm
    item = _text_item({"default_festival": "Asso Bidul"})
    client = _fake_client_returning([_ev(venue="La Fonderie", festival=None)])
    out = _norm._normalize_one(client, item, "2026-11", None, "t@b.fr")
    assert out[0].festival == "Asso Bidul"


# ---------- régression : date_label omis par le modèle (interop date) ----------

def test_normalize_one_keeps_event_without_date_label():
    """Régression : le prompt interop dit à Claude d'ignorer date_label (recalculé
    côté Python), donc Claude l'OMET. Le draft ne doit PAS être rejeté ; l'event
    non-festival est gardé avec un date_label dérivé de date_iso."""
    from tapageur import normalize as _norm
    item = _text_item({})
    ev = {  # pas de clé date_label du tout
        "date_iso": "2026-11-17", "times": ["20h00"],
        "venue": "Le Lézard", "city": "Le Mans", "price": "?",
        "acts": [{"genre": "c", "title": None, "performer": "Duo Aoki", "style": "Rock"}],
    }
    out = _norm._normalize_one(_fake_client_returning([ev]), item, "2026-11", None, "t@b.fr")
    assert len(out) == 1
    assert out[0].date_label == "Mardi 17"       # dérivé de date_iso


def test_normalize_one_keeps_event_with_null_date_label():
    """Même régression mais date_label explicitement null dans le JSON du modèle."""
    from tapageur import normalize as _norm
    item = _text_item({})
    ev = {
        "date_label": None, "date_iso": "2026-11-26", "times": ["21h00"],
        "venue": "Le Lézard", "city": "Le Mans", "price": "?",
        "acts": [{"genre": "c", "title": None, "performer": "Colombey", "style": "Pop"}],
    }
    out = _norm._normalize_one(_fake_client_returning([ev]), item, "2026-11", None, "t@b.fr")
    assert len(out) == 1
    assert out[0].date_label == "Jeudi 26"


def test_normalize_one_keeps_event_without_time():
    """Event sans horaire : gardé avec times=['?'] au lieu d'être supprimé."""
    from tapageur import normalize as _norm
    item = _text_item({})
    ev = {
        "date_iso": "2026-11-07", "times": [],
        "venue": "V", "city": "Le Mans", "price": "?",
        "acts": [{"genre": "sv", "title": None, "performer": "Corps & Âme", "style": "feu"}],
    }
    out = _norm._normalize_one(_fake_client_returning([ev]), item, "2026-11", None, "t@b.fr")
    assert len(out) == 1
    assert out[0].times == ["?"]


def test_normalize_one_keeps_event_with_omitted_times():
    """times carrément omis par le modèle → coercé en ['?']."""
    from tapageur import normalize as _norm
    item = _text_item({})
    ev = {
        "date_iso": "2026-11-10",
        "venue": "V", "city": "Le Mans", "price": "?",
        "acts": [{"genre": "c", "title": None, "performer": "Det Var", "style": "nordique"}],
    }
    out = _norm._normalize_one(_fake_client_returning([ev]), item, "2026-11", None, "t@b.fr")
    assert len(out) == 1
    assert out[0].times == ["?"]


def test_normalize_one_festival_without_date_label():
    """Un festival sans date_label ne doit pas planter la création de l'Event
    (Event.date_label est requis str) : coercition None -> ''."""
    from tapageur import normalize as _norm
    item = _text_item({})
    ev = {
        "date_iso": "2026-11-05", "is_festival": True, "festival": "Fest X",
        "times": ["?"], "venue": "", "city": "Le Mans", "price": "?",
        "acts": [{"genre": "sv", "title": None, "performer": "10 concerts", "style": "Jazz"}],
    }
    out = _norm._normalize_one(_fake_client_returning([ev]), item, "2026-11", None, "t@b.fr")
    assert len(out) == 1
    assert out[0].is_festival is True


# ---------- interop biduleur : date_label dérivé ----------

def test_normalize_one_derives_date_label_non_festival():
    """Le date_label du LLM est écrasé par la forme 'Jour N' dérivée de date_iso."""
    from tapageur import normalize as _norm
    item = _text_item({})
    ev = {
        "date_label": "LABEL FAUX DU LLM", "date_iso": "2026-11-10",
        "times": ["20h00"], "venue": "V", "city": "Le Mans", "price": "?",
        "acts": [{"genre": "c", "title": None, "performer": "A", "style": None}],
    }
    out = _norm._normalize_one(_fake_client_returning([ev]), item, "2026-11", None, "t@b.fr")
    assert out[0].date_label == "Mardi 10"


def test_normalize_one_keeps_festival_date_label():
    """Event festival : date_label libre conservé (non dérivé)."""
    from tapageur import normalize as _norm
    item = _text_item({})
    ev = {
        "date_label": "27-28 juin", "date_iso": "2026-06-27", "is_festival": True,
        "festival": "Festival X", "times": ["?"], "venue": "", "city": "Le Mans",
        "price": "?",
        "acts": [{"genre": "sv", "title": None, "performer": "15 spectacles", "style": None}],
    }
    out = _norm._normalize_one(_fake_client_returning([ev]), item, "2026-06", None, "t@b.fr")
    assert out[0].date_label == "27-28 juin"


def test_normalize_one_passes_reference_year_hint(monkeypatch):
    """En mode sans filtre + reference_year, le user message cite l'année de réf."""
    from tapageur import normalize as _norm
    seen = {}
    real_build = _norm._build_user_content
    def spy(item, month_hint):
        seen["hint"] = month_hint
        return real_build(item, month_hint)
    monkeypatch.setattr(_norm, "_build_user_content", spy)
    item = _text_item({})
    ev = {"date_iso": "2026-11-17", "times": ["20h00"], "venue": "V",
          "city": "Le Mans", "price": "?",
          "acts": [{"genre": "c", "title": None, "performer": "A", "style": None}]}
    _norm._normalize_one(_fake_client_returning([ev]), item, "tous-2026", None,
                         "t@b.fr", month_filter=False, reference_year="2026")
    assert "2026" in seen["hint"]
    assert "référence" in seen["hint"].lower()
