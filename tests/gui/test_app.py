from pathlib import Path
import tapageur.gui.app as app


def test_dropped_paths_extracts_full_paths_filtered():
    """Garde les pywebviewFullPath d'extensions supportées, ignore le reste."""
    event = {"dataTransfer": {"files": [
        {"name": "a.pdf", "pywebviewFullPath": r"C:\x\a.pdf"},
        {"name": "b.txt", "pywebviewFullPath": r"C:\x\b.txt"},   # ext non supportée
        {"name": "c.png"},                                        # pas de chemin
        {"name": "d.JPG", "pywebviewFullPath": r"C:\x\d.JPG"},    # casse ignorée
    ]}}
    assert app._dropped_paths(event) == [r"C:\x\a.pdf", r"C:\x\d.JPG"]


def test_dropped_paths_empty_cases():
    assert app._dropped_paths({}) == []
    assert app._dropped_paths({"dataTransfer": {"files": []}}) == []
    assert app._dropped_paths({"dataTransfer": {}}) == []


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


def test_run_extraction_passes_texts(monkeypatch):
    monkeypatch.setattr(app._settings, "load_settings",
                        lambda: {"anthropic_api_key": "sk-test", "tapeur_email": "t@b.fr"})
    captured = {}
    monkeypatch.setattr(app, "run", lambda req, progress=None: captured.update(req=req) or [])
    app.Api().run_extraction({
        "file_paths": [], "urls": [], "texts": [{"text": "concert", "venue": "Le Scarron", "info_orga": "Asso X"}],
        "months": ["2026-11"], "no_month_filter": False, "formats": ["json"], "out_dir": ".",
    })
    tis = captured["req"].text_inputs
    assert len(tis) == 1
    assert tis[0].text == "concert" and tis[0].venue == "Le Scarron" and tis[0].info_orga == "Asso X"


def test_run_extraction_passes_file_inputs(monkeypatch):
    monkeypatch.setattr(app._settings, "load_settings",
                        lambda: {"anthropic_api_key": "sk-test", "tapeur_email": "t@b.fr"})
    captured = {}
    monkeypatch.setattr(app, "run", lambda req, progress=None: captured.update(req=req) or [])
    app.Api().run_extraction({
        "files": [{"path": "/x/flyer.pdf", "venue": "Le Scarron", "info_orga": "A", "is_festival": True}],
        "urls": [], "texts": [], "months": ["2026-11"], "no_month_filter": False,
        "formats": ["json"], "out_dir": ".",
    })
    fis = captured["req"].file_inputs
    assert len(fis) == 1 and fis[0].venue == "Le Scarron" and fis[0].is_festival is True


def test_get_venues_returns_list(monkeypatch):
    venues = app.Api().get_venues()
    assert isinstance(venues, list)
    assert len(venues) > 0


def test_get_venues_has_no_formula_entries():
    """Régression #3 : le template doit fournir des lieux en clair, pas des
    formules Google Sheets (=IFERROR(__xludf.DUMMYFUNCTION(...))."""
    venues = app.Api().get_venues()
    assert len(venues) > 50
    assert all(not str(v).startswith("=") for v in venues)


def test_run_extraction_passes_month_mode(monkeypatch):
    monkeypatch.setattr(app._settings, "load_settings",
                        lambda: {"anthropic_api_key": "sk-test", "tapeur_email": "t@b.fr"})
    captured = {}
    monkeypatch.setattr(app, "run", lambda req, progress=None: captured.update(req=req) or [])
    app.Api().run_extraction({
        "files": [], "urls": [], "texts": [],
        "month_mode": "all", "reference_year": "2027",
        "formats": ["xlsx"], "out_dir": ".",
    })
    assert captured["req"].month_mode == "all"
    assert captured["req"].reference_year == "2027"


def test_default_reference_year_exposed():
    val = app.Api().default_reference_year()
    assert val.isdigit() and len(val) == 4


def test_debug_config_excludes_api_key():
    payload = {"api_key": "sk-x", "debug": True, "files": [], "months": ["2026-11"],
               "month_mode": "specific", "formats": ["xlsx"], "out_dir": "."}
    cfg = app._debug_config(payload)
    assert "api_key" not in cfg
    assert cfg["debug"] is True            # conservé pour restaurer le mode debug
    assert cfg["months"] == ["2026-11"]
    assert cfg["month_mode"] == "specific"


def test_friendly_error_auth_401():
    class _Auth(Exception):
        status_code = 401
    assert "Clé API" in app._friendly_error(_Auth("401 unauthorized"))
    assert app._friendly_error(ValueError("boom")) == "boom"


def test_events_summary_shape():
    from tapageur.schema import Event, Act
    ev = Event(tapeur_email="t@b.fr", date_label="Mardi 10", date_iso="2026-11-10",
               times=["20h00"], venue="Le Lieu", city="Le Mans", price="10€",
               acts=[Act(genre="c", title=None, performer="Orange Blossom", style=None)],
               source_kind="web", source_ref="https://x.fr")
    s = app._events_summary([ev])
    assert s[0]["date"] == "Mardi 10"
    assert s[0]["artistes"] == "Orange Blossom"
    assert s[0]["lieu"] == "Le Lieu" and s[0]["heure"] == "20h00"


def test_read_config_valid_and_invalid(tmp_path):
    good = tmp_path / "c.json"
    good.write_text('{"months": ["2026-11"], "formats": ["xlsx"]}', encoding="utf-8")
    assert app._read_config(good)["months"] == ["2026-11"]
    bad = tmp_path / "bad.json"
    bad.write_text("pas du json", encoding="utf-8")
    assert app._read_config(bad) == {}
    assert app._read_config(tmp_path / "absent.json") == {}


def test_run_extraction_debug_writes_config_and_log(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setattr(app._settings, "load_settings",
                        lambda: {"anthropic_api_key": "sk-secret", "tapeur_email": "t@b.fr"})

    def fake_run(req, progress=None):
        print("[1/1] text:texte #1")  # doit finir dans run_<ts>.log
        return []
    monkeypatch.setattr(app, "run", fake_run)

    app.Api().run_extraction({
        "files": [], "urls": [], "texts": [], "months": ["2026-11"],
        "month_mode": "specific", "formats": ["xlsx"], "out_dir": str(tmp_path),
        "api_key": "sk-secret", "debug": True,
    })
    dbg = tmp_path / "debug"
    configs = list(dbg.glob("config_*.json"))
    logs = list(dbg.glob("run_*.log"))
    assert len(configs) == 1 and len(logs) == 1
    cfg = _json.loads(configs[0].read_text(encoding="utf-8"))
    assert "api_key" not in cfg          # secret exclu
    assert cfg.get("debug") is True      # flag debug conservé
    assert cfg["months"] == ["2026-11"]
    assert "[1/1] text:texte #1" in logs[0].read_text(encoding="utf-8")


def test_run_extraction_no_debug_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(app._settings, "load_settings",
                        lambda: {"anthropic_api_key": "sk-x", "tapeur_email": "t@b.fr"})
    monkeypatch.setattr(app, "run", lambda req, progress=None: [])
    app.Api().run_extraction({
        "files": [], "urls": [], "texts": [], "months": ["2026-11"],
        "month_mode": "specific", "formats": ["xlsx"], "out_dir": str(tmp_path),
    })
    assert not (tmp_path / "debug").exists()
