"""Réglages locaux persistants (clé API, email tapeur)."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_TAPEUR_EMAIL = "lebidul@live.fr"
_DEFAULTS = {"anthropic_api_key": "", "tapeur_email": DEFAULT_TAPEUR_EMAIL, "theme": "dark"}


def settings_path() -> Path:
    """Chemin du fichier de réglages, par OS."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / "tapageur"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tapageur"
    return base / "settings.json"


def load_settings() -> dict:
    """Charge les réglages ; complète les clés manquantes par les défauts."""
    p = settings_path()
    data = dict(_DEFAULTS)
    if p.exists():
        try:
            data.update(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return data


def save_settings(data: dict) -> None:
    """Écrit les réglages (crée le dossier au besoin).

    Fusionne avec l'existant : seules les clés fournies dans `data` sont
    modifiées (sauver {theme} ne touche pas la clé API, et inversement)."""
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    merged = load_settings()
    merged.update(data)
    p.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
