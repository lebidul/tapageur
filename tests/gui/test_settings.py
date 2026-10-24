import json
from tapageur.gui import settings


def test_load_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings_path", lambda: tmp_path / "settings.json")
    data = settings.load_settings()
    assert data["tapeur_email"] == settings.DEFAULT_TAPEUR_EMAIL
    assert data["anthropic_api_key"] == ""


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "settings_path", lambda: p)
    settings.save_settings({"anthropic_api_key": "sk-test", "tapeur_email": "a@b.fr"})
    assert p.exists()
    data = settings.load_settings()
    assert data["anthropic_api_key"] == "sk-test"
    assert data["tapeur_email"] == "a@b.fr"


def test_load_fills_missing_keys(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"anthropic_api_key": "sk-x"}), encoding="utf-8")
    monkeypatch.setattr(settings, "settings_path", lambda: p)
    data = settings.load_settings()
    assert data["anthropic_api_key"] == "sk-x"
    assert data["tapeur_email"] == settings.DEFAULT_TAPEUR_EMAIL


def test_save_merges_preserves_other_keys(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "settings_path", lambda: p)
    settings.save_settings({"anthropic_api_key": "sk-x", "tapeur_email": "a@b.fr"})
    settings.save_settings({"theme": "light"})          # ne doit PAS effacer la clé
    data = settings.load_settings()
    assert data["anthropic_api_key"] == "sk-x"
    assert data["tapeur_email"] == "a@b.fr"
    assert data["theme"] == "light"


def test_save_key_preserves_existing_theme(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "settings_path", lambda: p)
    settings.save_settings({"theme": "light"})
    settings.save_settings({"anthropic_api_key": "sk-y"})
    data = settings.load_settings()
    assert data["theme"] == "light"
    assert data["anthropic_api_key"] == "sk-y"


def test_default_theme_is_dark(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings_path", lambda: tmp_path / "settings.json")
    assert settings.load_settings()["theme"] == "dark"
