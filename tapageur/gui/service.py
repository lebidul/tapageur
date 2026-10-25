"""Orchestration GUI : build items → pipeline → alertes → export."""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from tapageur.dedup import (canonicalize, convert_to_onliner, dedup,
                            group_events, load_mappings)
from tapageur.gui import export_xlsx as _xlsx
from tapageur.gui.inputs import (TextInput, UrlInput, items_from_files,
                                 items_from_texts, items_from_urls)
from tapageur.normalize import normalize_items
from tapageur.schema import Event
from tapageur.validate import export_csv


def default_reference_year(today: date | None = None) -> str:
    """Année de référence pour le mode « tous les mois » : année courante,
    sauf en décembre (on prépare janvier de l'année suivante)."""
    today = today or date.today()
    return str(today.year + 1 if today.month == 12 else today.year)


@dataclass
class RunRequest:
    url_inputs: list[UrlInput]
    months: list[str]
    formats: list[str]            # sous-ensemble de {"xlsx", "csv", "json"}
    out_dir: Path
    tapeur_email: str
    month_mode: str = "specific"          # "specific" | "all"
    reference_year: str = ""              # mode "all" ; vide → default_reference_year()
    append: bool = False
    text_inputs: list[TextInput] = field(default_factory=list)
    file_inputs: list = field(default_factory=list)   # list[FileInput]


@dataclass
class MonthResult:
    month: str | None
    n_events: int
    files: list[Path] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    events: list = field(default_factory=list)   # list[Event] (détail pour l'UI)


def build_alerts(events: list[Event], ref_cities: set[str], ref_venues: set[str]) -> list[str]:
    """Signale prix/performer manquants et lieux/villes hors listes de référence."""
    alerts: list[str] = []
    for ev in events:
        if ev.price == "?":
            alerts.append(f"Prix manquant : {ev.date_label} — {ev.acts[0].performer}")
        if "?" in ev.times:
            alerts.append(f"Horaire manquant : {ev.date_label} — {ev.acts[0].performer}")
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
        cities = {r[0] for r in wb["communes"].iter_rows(values_only=True)
                  if r and r[0] and not str(r[0]).startswith("=")}
        venues = {r[0] for r in wb["salles_lieux"].iter_rows(values_only=True)
                  if r and r[0] and not str(r[0]).startswith("=")}
    finally:
        wb.close()
    return cities, venues


def _mappings_path() -> Path:
    """config/mappings.yaml : embarqué sous sys._MEIPASS dans l'exe figé,
    relatif au CWD sinon (comportement CLI inchangé)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "config" / "mappings.yaml"
    return Path("config/mappings.yaml")


def _pipeline(items, month: str, month_filter: bool, cache_out: Path,
              progress=None, reference_year: str | None = None) -> list[Event]:
    events = normalize_items(items, month, cache_out, model=None,
                             month_filter=month_filter, progress=progress,
                             reference_year=reference_year)
    events = canonicalize(events, load_mappings(_mappings_path()))
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

    _emit("Collecte des sources…")
    url_month = "" if req.month_mode == "all" else (req.months[0] if req.months else "")
    items = list(items_from_files(req.file_inputs, progress=progress))
    items += list(items_from_urls(req.url_inputs, url_month, progress=progress))
    items += list(items_from_texts(req.text_inputs, progress=progress))

    results: list[MonthResult] = []

    if req.month_mode == "all":
        ref_year = req.reference_year or default_reference_year()
        key = f"tous-{ref_year}"
        cache_out = Path("cache") / key / "gui_normalized.json"
        _emit("tous les mois : extraction…")
        events = _pipeline(items, key, False, cache_out, progress=progress,
                           reference_year=ref_year)
        by_month: dict[str, list[Event]] = defaultdict(list)
        for ev in events:
            by_month[ev.date_iso[:7]].append(ev)
        for month in sorted(by_month):
            evs = by_month[month]
            _emit(f"{month} : {len(evs)} events, export…")
            files = _export(evs, req.out_dir, month, req.formats, append=req.append)
            alerts = build_alerts(evs, ref_cities, ref_venues)
            results.append(MonthResult(month=month, n_events=len(evs),
                                       files=files, alerts=alerts, events=evs))
        if not by_month:
            results.append(MonthResult(month=None, n_events=0, files=[],
                                       alerts=["Aucun event extrait."]))
    else:
        for month in req.months:
            cache_out = Path("cache") / month / "gui_normalized.json"
            _emit(f"{month} : extraction…")
            events = _pipeline(items, month, True, cache_out, progress=progress)
            _emit(f"{month} : {len(events)} events, export…")
            files = _export(events, req.out_dir, month, req.formats, append=req.append)
            alerts = build_alerts(events, ref_cities, ref_venues)
            if req.append and "xlsx" not in req.formats:
                alerts.append("Append ignoré : xlsx non sélectionné.")
            results.append(MonthResult(month=month, n_events=len(events),
                                       files=files, alerts=alerts, events=events))

    _emit("Terminé.")
    return results
