"""Orchestration GUI : build items → pipeline → alertes → export."""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from tapageur.dedup import (canonicalize, convert_to_onliner, dedup,
                            group_events, load_mappings)
from tapageur.gui import export_xlsx as _xlsx
from tapageur.gui.inputs import (TextInput, UrlInput, items_from_files,
                                 items_from_texts, items_from_urls)
from tapageur.normalize import normalize_items
from tapageur.schema import Event
from tapageur.validate import export_csv


@dataclass
class RunRequest:
    file_paths: list[Path]
    url_inputs: list[UrlInput]
    months: list[str]
    no_month_filter: bool
    formats: list[str]            # sous-ensemble de {"xlsx", "csv", "json"}
    out_dir: Path
    tapeur_email: str
    append: bool = False
    text_inputs: list[TextInput] = field(default_factory=list)


@dataclass
class MonthResult:
    month: str | None
    n_events: int
    files: list[Path] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)


def build_alerts(events: list[Event], ref_cities: set[str], ref_venues: set[str]) -> list[str]:
    """Signale prix/performer manquants et lieux/villes hors listes de référence."""
    alerts: list[str] = []
    for ev in events:
        if ev.price == "?":
            alerts.append(f"Prix manquant : {ev.date_label} — {ev.acts[0].performer}")
        for act in ev.acts:
            if act.performer == "?":
                alerts.append(f"Artiste/performer inconnu : {ev.date_label} @ {ev.venue}")
        if ref_cities and ev.city and ev.city not in ref_cities:
            alerts.append(f"Ville hors liste de référence : {ev.city}")
        if ref_venues and ev.venue and ev.venue not in ref_venues:
            alerts.append(f"Lieu hors liste de référence : {ev.venue}")
    return alerts


def _reference_lists() -> tuple[set[str], set[str]]:
    """Lit communes / salles_lieux depuis le template embarqué."""
    import openpyxl
    wb = openpyxl.load_workbook(_xlsx.TEMPLATE_PATH, read_only=True)
    try:
        cities = {r[0] for r in wb["communes"].iter_rows(values_only=True) if r and r[0]}
        venues = {r[0] for r in wb["salles_lieux"].iter_rows(values_only=True) if r and r[0]}
    finally:
        wb.close()
    return cities, venues


def _pipeline(items, month: str, month_filter: bool, cache_out: Path, progress=None) -> list[Event]:
    events = normalize_items(items, month, cache_out, model=None, month_filter=month_filter, progress=progress)
    events = canonicalize(events, load_mappings())
    events = dedup(events)
    events = group_events(events)
    onliner_names = [ev.festival for ev in events if ev.is_festival and ev.festival]
    events = convert_to_onliner(events, onliner_names)
    return events


def _export(events: list[Event], out_dir: Path, label: str, formats: list[str],
            append: bool = False) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if "json" in formats:
        p = out_dir / f"tapage_{label}.json"
        p.write_text(json.dumps([e.model_dump() for e in events], indent=2, ensure_ascii=False),
                     encoding="utf-8")
        written.append(p)
    if "csv" in formats:
        p = out_dir / f"tapage_{label}.csv"
        export_csv(events, p)
        written.append(p)
    if "xlsx" in formats:
        p = out_dir / f"tapage_{label}.xlsx"
        _xlsx.export_xlsx(events, p, append=append)
        written.append(p)
    return written


def run(req: RunRequest, progress: Callable[[str], None] | None = None) -> list[MonthResult]:
    def _emit(msg):
        progress and progress(msg)

    os.environ["TAPEUR_EMAIL"] = req.tapeur_email
    ref_cities, ref_venues = _reference_lists()

    if req.no_month_filter:
        passes = [("", "tous", False)]
    else:
        passes = [(m, m, True) for m in req.months]

    _emit("Collecte des sources…")
    url_month = "" if req.no_month_filter else (req.months[0] if req.months else "")
    items = list(items_from_files(req.file_paths, progress=progress))
    items += list(items_from_urls(req.url_inputs, url_month, progress=progress))
    items += list(items_from_texts(req.text_inputs, progress=progress))

    results: list[MonthResult] = []
    for month, label, month_filter in passes:
        cache_out = Path("cache") / (label or "tous") / "gui_normalized.json"
        _emit(f"{label} : extraction…")
        events = _pipeline(items, month, month_filter, cache_out, progress=progress)
        _emit(f"{label} : {len(events)} events, export…")
        files = _export(events, req.out_dir, label, req.formats, append=req.append)
        alerts = build_alerts(events, ref_cities, ref_venues)
        if req.append and "xlsx" not in req.formats:
            alerts.append("Append ignoré : xlsx non sélectionné.")
        results.append(MonthResult(
            month=(month or None), n_events=len(events), files=files, alerts=alerts,
        ))
    _emit("Terminé.")
    return results
