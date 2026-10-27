from datetime import date
from pathlib import Path
from tapageur.gui import service
from tapageur.gui import service as S
from tapageur.gui.inputs import UrlInput, FileInput
from tapageur.schema import Event, Act


def _event(price="10€", perf="A", city="Le Mans", venue="Le Lieu", times=None,
           source_kind="web", source_ref="https://x.fr"):
    return Event(
        tapeur_email="t@b.fr", date_label="Vendredi 2", date_iso="2026-10-02",
        times=times or ["20h00"], venue=venue, city=city, price=price,
        acts=[Act(genre="c", title=None, performer=perf, style=None)],
        source_kind=source_kind, source_ref=source_ref,
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


def test_build_alerts_tags_each_alert_with_source_image():
    # Fichier image : la source lisible est le basename (cf. _source_ref_display).
    evs = [_event(price="?", times=["?"], perf="?", city="Ailleurs", venue="Inconnu",
                  source_kind="image", source_ref="C:/dl/1.avif")]
    alerts = service.build_alerts(evs, ref_cities={"Le Mans"}, ref_venues={"Le Lieu"})
    assert alerts, "au moins une alerte attendue"
    # Chaque alerte porte la source entre crochets.
    assert all(a.endswith(" [1.avif]") for a in alerts), alerts


def test_build_alerts_source_web_is_full_url():
    evs = [_event(price="?", source_kind="web", source_ref="https://clappin.fr/agenda/x/")]
    alerts = service.build_alerts(evs, ref_cities={"Le Mans"}, ref_venues={"Le Lieu"})
    assert any(a.endswith(" [https://clappin.fr/agenda/x/]") for a in alerts), alerts


def test_build_alerts_no_empty_bracket_when_source_blank():
    evs = [_event(price="?", source_kind="web", source_ref="")]
    alerts = service.build_alerts(evs, ref_cities={"Le Mans"}, ref_venues={"Le Lieu"})
    assert alerts
    assert not any("[]" in a for a in alerts), alerts


def test_format_duration_under_a_minute():
    assert service._format_duration(0) == "0s"
    assert service._format_duration(5) == "5s"
    assert service._format_duration(59.4) == "59s"


def test_format_duration_minutes_and_seconds():
    assert service._format_duration(65) == "1m 05s"
    assert service._format_duration(125) == "2m 05s"
    assert service._format_duration(600) == "10m 00s"


def _patch_pipeline(monkeypatch):
    monkeypatch.setattr(service, "normalize_items",
                        lambda items, month, out_path, model=None, month_filter=True, progress=None, reference_year=None: [_event()])
    monkeypatch.setattr(service, "load_mappings", lambda *a, **k: {})
    monkeypatch.setattr(service, "canonicalize", lambda evs, m: evs)
    monkeypatch.setattr(service, "dedup", lambda evs: evs)
    monkeypatch.setattr(service, "group_events", lambda evs: evs)
    monkeypatch.setattr(service, "convert_to_onliner", lambda evs, names: evs)


def test_run_emits_total_duration_at_end(tmp_path, monkeypatch):
    _patch_pipeline(monkeypatch)
    msgs = []
    req = service.RunRequest(
        file_inputs=[], url_inputs=[], months=["2026-10"], month_mode="specific",
        formats=["json"], out_dir=tmp_path, tapeur_email="t@b.fr",
    )
    service.run(req, progress=msgs.append)
    # Dernière ligne = durée totale, plus le simple « Terminé. » historique.
    assert msgs[-1].startswith("Terminé en "), msgs
    assert msgs[-1].endswith("."), msgs


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
    service._export([_event(perf="Un")], tmp_path, "2026-11", ["xlsx"], write_mode="create")
    service._export([_event(perf="Deux")], tmp_path, "2026-11", ["xlsx"], write_mode="append")
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
        formats=["json"], out_dir=tmp_path, tapeur_email="t@b.fr", write_mode="append",
    )
    results = service.run(req)
    assert any("Mode 'append' ignoré : xlsx non sélectionné." == a for a in results[0].alerts)


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


def test_pipeline_applies_venue_defaults(tmp_path, monkeypatch):
    """_pipeline complète heure/prix via les défauts par lieu, après canonicalize."""
    ev = _event(times=["?"], price="?", venue="Bistro Broc Café")
    monkeypatch.setattr(service, "normalize_items",
                        lambda *a, **k: [ev])
    monkeypatch.setattr(service, "load_mappings", lambda *a, **k: {})
    monkeypatch.setattr(service, "canonicalize", lambda e, m: e)
    monkeypatch.setattr(service, "dedup", lambda e: e)
    monkeypatch.setattr(service, "group_events", lambda e: e)
    monkeypatch.setattr(service, "convert_to_onliner", lambda e, names: e)
    monkeypatch.setattr(service, "load_venue_defaults",
                        lambda *a, **k: {"Bistro Broc Café": {"time": "20h00", "price": "au chapeau"}})
    out = service._pipeline([], "2026-11", True, tmp_path / "c.json")
    assert out[0].times == ["20h00"]
    assert out[0].price == "au chapeau"


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


def test_write_mode_append_skips_present_sources(monkeypatch, tmp_path):
    # fichier existant contenant déjà la source "https://a.fr/present"
    monkeypatch.setattr(S._xlsx, "existing_sources",
                        lambda p: {"https://a.fr/present"})
    # export réel neutralisé : le fichier cible factice (b"x") n'est pas un xlsx.
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: None)
    monkeypatch.setattr(S._xlsx, "record_processed_sources", lambda *a, **k: None)
    captured = {}
    def fake_items_urls(url_inputs, month, progress=None):
        captured["urls"] = [u.url for u in url_inputs]
        return []
    monkeypatch.setattr(S, "items_from_urls", fake_items_urls)
    monkeypatch.setattr(S, "items_from_files", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    (tmp_path / "tapage_2026-11.xlsx").write_bytes(b"x")  # existe
    req = S.RunRequest(
        url_inputs=[UrlInput(url="https://a.fr/present"), UrlInput(url="https://a.fr/new")],
        months=["2026-11"], formats=["xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
        write_mode="append",
    )
    S.run(req)
    assert captured["urls"] == ["https://a.fr/new"]  # source présente filtrée


def test_write_mode_append_skips_follow_url_by_host(monkeypatch, tmp_path):
    """Interim : un site à suivre dont la colonne SOURCE ne garde que les pages
    détail est reconnu « déjà présent » par son HÔTE ; un nouvel hôte passe."""
    monkeypatch.setattr(S._xlsx, "existing_sources",
                        lambda p: {"https://leo.fr/event/x"})  # page détail stockée
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: None)
    monkeypatch.setattr(S._xlsx, "record_processed_sources", lambda *a, **k: None)
    captured = {}
    monkeypatch.setattr(S, "items_from_urls",
                        lambda url_inputs, month, progress=None: captured.setdefault(
                            "urls", [u.url for u in url_inputs]) or [])
    monkeypatch.setattr(S, "items_from_files", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    (tmp_path / "tapage_2026-11.xlsx").write_bytes(b"x")
    req = S.RunRequest(
        url_inputs=[UrlInput(url="https://leo.fr/programme/", follow_links=True),
                    UrlInput(url="https://clappin.fr/agenda/", follow_links=True)],
        months=["2026-11"], formats=["xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
        write_mode="append",
    )
    S.run(req)
    assert captured["urls"] == ["https://clappin.fr/agenda/"]  # leo.fr (hôte présent) filtré


def test_input_source_ids(tmp_path):
    from tapageur.gui.inputs import FileInput, UrlInput, TextInput
    req = S.RunRequest(
        url_inputs=[UrlInput(url="https://a.fr/x")],
        file_inputs=[FileInput(path=r"C:\d\1.avif")],
        text_inputs=[TextInput(text="coucou")],
        months=["2026-11"], formats=["xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
    )
    ids = S._input_source_ids(req)
    assert ("1.avif", "Fichier") in ids
    assert ("https://a.fr/x", "URL") in ids
    # id texte = hash de contenu (stable), pas « texte #N »
    tid = S._text_id("coucou")
    assert tid.startswith("texte:")
    assert (tid, "Texte") in ids
    assert S._text_id("coucou") == tid and S._text_id("autre") != tid


def test_append_skips_text_already_in_manifest(monkeypatch, tmp_path):
    """Un texte identique déjà traité (hash au manifeste) est skippé → pas de
    doublon ; un texte modifié passe."""
    from tapageur.gui.inputs import TextInput
    seen_id = S._text_id("concert le 3")
    monkeypatch.setattr(S._xlsx, "has_manifest", lambda p: True)
    monkeypatch.setattr(S._xlsx, "read_processed_sources", lambda p: {seen_id})
    monkeypatch.setattr(S._xlsx, "record_processed_sources", lambda *a, **k: None)
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: None)
    captured = {}
    monkeypatch.setattr(S, "items_from_texts",
                        lambda ti, progress=None: captured.setdefault(
                            "texts", [t.text for t in ti]) or [])
    monkeypatch.setattr(S, "items_from_urls", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_files", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    (tmp_path / "tapage_2026-11.xlsx").write_bytes(b"x")
    req = S.RunRequest(
        url_inputs=[],
        text_inputs=[TextInput(text="concert le 3"), TextInput(text="nouveau texte")],
        months=["2026-11"], formats=["xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
        write_mode="append",
    )
    S.run(req)
    assert captured["texts"] == ["nouveau texte"]  # texte déjà traité skippé


def test_append_skips_via_manifest(monkeypatch, tmp_path):
    from tapageur.gui.inputs import UrlInput, FileInput
    monkeypatch.setattr(S._xlsx, "has_manifest", lambda p: True)
    monkeypatch.setattr(S._xlsx, "read_processed_sources",
                        lambda p: {"https://a.fr/present", "1.avif"})
    monkeypatch.setattr(S._xlsx, "record_processed_sources", lambda *a, **k: None)
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: None)
    captured = {}
    monkeypatch.setattr(S, "items_from_urls",
                        lambda ui, m, progress=None: captured.setdefault(
                            "urls", [u.url for u in ui]) or [])
    monkeypatch.setattr(S, "items_from_files",
                        lambda fi, progress=None: captured.setdefault(
                            "files", [__import__("pathlib").Path(f.path).name for f in fi]) or [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    (tmp_path / "tapage_2026-11.xlsx").write_bytes(b"x")
    req = S.RunRequest(
        url_inputs=[UrlInput(url="https://a.fr/present"), UrlInput(url="https://a.fr/new")],
        file_inputs=[FileInput(path=r"C:\d\1.avif"), FileInput(path=r"C:\d\2.avif")],
        months=["2026-11"], formats=["xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
        write_mode="append",
    )
    S.run(req)
    assert captured["urls"] == ["https://a.fr/new"]
    assert captured["files"] == ["2.avif"]       # 1.avif (au manifeste) skippé


def test_append_falls_back_without_manifest(monkeypatch, tmp_path):
    """Pas de feuille manifeste → repli sur l'heuristique SOURCE + hôte."""
    from tapageur.gui.inputs import UrlInput
    monkeypatch.setattr(S._xlsx, "has_manifest", lambda p: False)
    called = {}
    monkeypatch.setattr(S, "_filter_present_sources",
                        lambda req, target, emit: called.setdefault("fallback", True) or 0)
    monkeypatch.setattr(S._xlsx, "record_processed_sources", lambda *a, **k: None)
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: None)
    monkeypatch.setattr(S, "items_from_urls", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_files", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    (tmp_path / "tapage_2026-11.xlsx").write_bytes(b"x")
    req = S.RunRequest(url_inputs=[UrlInput(url="https://a.fr/x")],
                       months=["2026-11"], formats=["xlsx"], out_dir=tmp_path,
                       tapeur_email="t@b.fr", write_mode="append")
    S.run(req)
    assert called.get("fallback")


def test_run_records_manifest_after_pass(monkeypatch, tmp_path):
    from tapageur.gui.inputs import UrlInput
    rec = {}
    monkeypatch.setattr(S._xlsx, "record_processed_sources",
                        lambda path, sources: rec.setdefault("sources", sources))
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: None)
    monkeypatch.setattr(S, "items_from_urls", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_files", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    monkeypatch.setattr(S, "build_alerts", lambda *a, **k: [])
    req = S.RunRequest(url_inputs=[UrlInput(url="https://a.fr/x")],
                       months=["2026-11"], formats=["xlsx"], out_dir=tmp_path,
                       tapeur_email="t@b.fr", write_mode="create")
    S.run(req)
    assert ("https://a.fr/x", "URL") in rec["sources"]


def test_write_mode_merge_routes_to_merge(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(S._xlsx, "_merge_xlsx",
                        lambda evs, p: calls.update(merge=True) or S._xlsx.MergeReport(added=1))
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: calls.setdefault("create", True))
    monkeypatch.setattr(S, "items_from_urls", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_files", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [object()])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    monkeypatch.setattr(S, "build_alerts", lambda *a, **k: [])
    req = S.RunRequest(url_inputs=[], months=["2026-11"], formats=["xlsx"],
                       out_dir=tmp_path, tapeur_email="t@b.fr", write_mode="merge")
    res = S.run(req)
    assert calls.get("merge") and res[0].added == 1
