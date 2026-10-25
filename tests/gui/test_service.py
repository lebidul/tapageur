from datetime import date
from pathlib import Path
from tapageur.gui import service
from tapageur.schema import Event, Act


def _event(price="10€", perf="A", city="Le Mans", venue="Le Lieu", times=None):
    return Event(
        tapeur_email="t@b.fr", date_label="Vendredi 2", date_iso="2026-10-02",
        times=times or ["20h00"], venue=venue, city=city, price=price,
        acts=[Act(genre="c", title=None, performer=perf, style=None)],
        source_kind="web", source_ref="https://x.fr",
    )


def test_build_alerts_flags_missing_time():
    evs = [_event(times=["?"])]
    alerts = service.build_alerts(evs, ref_cities={"Le Mans"}, ref_venues={"Le Lieu"})
    assert any("horaire" in a.lower() for a in alerts)


def test_build_alerts_no_time_alert_when_present():
    evs = [_event(times=["20h00"])]
    alerts = service.build_alerts(evs, ref_cities={"Le Mans"}, ref_venues={"Le Lieu"})
    assert not any("horaire" in a.lower() for a in alerts)


def test_build_alerts_flags_missing_and_unknown():
    evs = [_event(price="?", perf="?", city="Ailleurs", venue="Inconnu")]
    alerts = service.build_alerts(evs, ref_cities={"Le Mans"}, ref_venues={"Le Lieu"})
    joined = " ".join(alerts)
    assert "prix" in joined.lower()
    assert "performer" in joined.lower() or "artiste" in joined.lower()
    assert "Ailleurs" in joined
    assert "Inconnu" in joined


def test_run_exports_requested_formats(tmp_path, monkeypatch):
    # normalize_items mocké : renvoie 1 event, ignore l'appel Claude
    monkeypatch.setattr(service, "normalize_items",
                        lambda items, month, out_path, model=None, month_filter=True, progress=None, reference_year=None: [_event()])
    monkeypatch.setattr(service, "load_mappings", lambda *a, **k: {})
    monkeypatch.setattr(service, "canonicalize", lambda evs, m: evs)
    monkeypatch.setattr(service, "dedup", lambda evs: evs)
    monkeypatch.setattr(service, "group_events", lambda evs: evs)
    monkeypatch.setattr(service, "convert_to_onliner", lambda evs, names: evs)

    req = service.RunRequest(
        file_inputs=[], url_inputs=[], months=["2026-10"], month_mode="specific",
        formats=["json", "csv", "xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
    )
    results = service.run(req)
    assert len(results) == 1
    r = results[0]
    assert r.month == "2026-10"
    assert r.n_events == 1
    exts = {p.suffix for p in r.files}
    assert exts == {".json", ".csv", ".xlsx"}
    for p in r.files:
        assert p.exists()


def test_run_threads_progress_into_normalize(tmp_path, monkeypatch):
    captured = {}
    def fake_normalize(items, month, out_path, model=None, month_filter=True, progress=None, reference_year=None):
        captured["progress"] = progress
        return [_event()]
    monkeypatch.setattr(service, "normalize_items", fake_normalize)
    monkeypatch.setattr(service, "load_mappings", lambda *a, **k: {})
    monkeypatch.setattr(service, "canonicalize", lambda evs, m: evs)
    monkeypatch.setattr(service, "dedup", lambda evs: evs)
    monkeypatch.setattr(service, "group_events", lambda evs: evs)
    monkeypatch.setattr(service, "convert_to_onliner", lambda evs, names: evs)
    req = service.RunRequest(
        file_inputs=[], url_inputs=[], months=["2026-11"], month_mode="specific",
        formats=["json"], out_dir=tmp_path, tapeur_email="t@b.fr",
    )
    cb = lambda m: None
    service.run(req, progress=cb)
    assert captured["progress"] is cb


def test_export_append_adds_to_existing_xlsx(tmp_path):
    import openpyxl
    service._export([_event(perf="Un")], tmp_path, "2026-11", ["xlsx"], append=False)
    service._export([_event(perf="Deux")], tmp_path, "2026-11", ["xlsx"], append=True)
    ws = openpyxl.load_workbook(tmp_path / "tapage_2026-11.xlsx")["lebiduleur"]
    assert ws.max_row == 3   # en-tête + 2 events


def test_run_append_without_xlsx_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "normalize_items",
                        lambda *a, **k: [_event()])
    monkeypatch.setattr(service, "load_mappings", lambda *a, **k: {})
    monkeypatch.setattr(service, "canonicalize", lambda evs, m: evs)
    monkeypatch.setattr(service, "dedup", lambda evs: evs)
    monkeypatch.setattr(service, "group_events", lambda evs: evs)
    monkeypatch.setattr(service, "convert_to_onliner", lambda evs, names: evs)
    req = service.RunRequest(
        file_inputs=[], url_inputs=[], months=["2026-11"], month_mode="specific",
        formats=["json"], out_dir=tmp_path, tapeur_email="t@b.fr", append=True,
    )
    results = service.run(req)
    assert any("xlsx" in a.lower() for a in results[0].alerts)


def test_run_includes_text_inputs(tmp_path, monkeypatch):
    captured = {}
    def fake_normalize(items, month, out_path, model=None, month_filter=True, progress=None, reference_year=None):
        captured["items"] = list(items)
        return [_event()]
    monkeypatch.setattr(service, "normalize_items", fake_normalize)
    monkeypatch.setattr(service, "load_mappings", lambda *a, **k: {})
    monkeypatch.setattr(service, "canonicalize", lambda evs, m: evs)
    monkeypatch.setattr(service, "dedup", lambda evs: evs)
    monkeypatch.setattr(service, "group_events", lambda evs: evs)
    monkeypatch.setattr(service, "convert_to_onliner", lambda evs, names: evs)
    from tapageur.gui.inputs import TextInput
    req = service.RunRequest(
        file_inputs=[], url_inputs=[], months=["2026-11"], month_mode="specific",
        formats=["json"], out_dir=tmp_path, tapeur_email="t@b.fr",
        text_inputs=[TextInput(text="concert", venue="Le Scarron")],
    )
    service.run(req)
    kinds = [it.source_kind for it in captured["items"]]
    assert "text" in kinds


def test_default_reference_year_normal_and_december():
    assert service.default_reference_year(date(2026, 11, 1)) == "2026"
    assert service.default_reference_year(date(2026, 1, 5)) == "2026"
    assert service.default_reference_year(date(2026, 12, 10)) == "2027"


def test_run_all_months_one_file_per_month(tmp_path, monkeypatch):
    """Mode all : events sur 2 mois → 2 fichiers groupés par mois."""
    evs = [_event(perf="Nov", times=["20h00"]), _event(perf="Dec", times=["21h00"])]
    evs[0].date_iso = "2026-11-10"
    evs[1].date_iso = "2026-12-05"
    monkeypatch.setattr(service, "normalize_items",
                        lambda items, month, out_path, model=None, month_filter=True,
                               progress=None, reference_year=None: list(evs))
    monkeypatch.setattr(service, "load_mappings", lambda *a, **k: {})
    monkeypatch.setattr(service, "canonicalize", lambda e, m: e)
    monkeypatch.setattr(service, "dedup", lambda e: e)
    monkeypatch.setattr(service, "group_events", lambda e: e)
    monkeypatch.setattr(service, "convert_to_onliner", lambda e, names: e)

    req = service.RunRequest(
        file_inputs=[], url_inputs=[], months=[], month_mode="all",
        reference_year="2026", formats=["xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
    )
    results = service.run(req)
    months = sorted(r.month for r in results)
    assert months == ["2026-11", "2026-12"]
    names = sorted(p.name for r in results for p in r.files)
    assert names == ["tapage_2026-11.xlsx", "tapage_2026-12.xlsx"]
