from pathlib import Path
from tapageur.gui import service
from tapageur.schema import Event, Act


def _event(price="10€", perf="A", city="Le Mans", venue="Le Lieu"):
    return Event(
        tapeur_email="t@b.fr", date_label="Vendredi 2", date_iso="2026-10-02",
        times=["20h00"], venue=venue, city=city, price=price,
        acts=[Act(genre="c", title=None, performer=perf, style=None)],
        source_kind="web", source_ref="https://x.fr",
    )


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
                        lambda items, month, out_path, model=None, month_filter=True: [_event()])
    monkeypatch.setattr(service, "load_mappings", lambda: {})
    monkeypatch.setattr(service, "canonicalize", lambda evs, m: evs)
    monkeypatch.setattr(service, "dedup", lambda evs: evs)
    monkeypatch.setattr(service, "group_events", lambda evs: evs)
    monkeypatch.setattr(service, "convert_to_onliner", lambda evs, names: evs)

    req = service.RunRequest(
        file_paths=[], url_inputs=[], months=["2026-10"], no_month_filter=False,
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
