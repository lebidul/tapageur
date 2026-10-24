from pathlib import Path
import tapageur.gui.app as app


def test_run_extraction_passes_append(monkeypatch):
    # Clé présente → pas de court-circuit "clé absente".
    monkeypatch.setattr(app._settings, "load_settings",
                        lambda: {"anthropic_api_key": "sk-test", "tapeur_email": "t@b.fr"})
    captured = {}
    # dict.update renvoie None → `None or []` → [] (liste de résultats vide),
    # tout en capturant la RunRequest passée à run.
    monkeypatch.setattr(app, "run", lambda req, progress=None: captured.update(req=req) or [])
    res = app.Api().run_extraction({
        "file_paths": [], "urls": [], "months": ["2026-11"],
        "no_month_filter": False, "formats": ["xlsx"], "out_dir": ".",
        "append": True,
    })
    assert "results" in res
    assert captured["req"].append is True
