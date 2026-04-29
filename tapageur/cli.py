"""CLI : `tapageur collect|normalize|preview|push --month YYYY-MM`"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv
from rich.console import Console

from tapageur.connectors import get_connector
# Trigger registry registration via imports
from tapageur.connectors import outlook, web, pdf, fb, images  # noqa: F401
from tapageur.dedup import canonicalize, dedup, load_mappings
from tapageur.normalize import normalize_items
from tapageur.push import push_csv
from tapageur.schema import CollectedItem, Event
from tapageur.validate import export_csv


load_dotenv()
console = Console()


@click.group()
def main():
    """tapageur : collecte mensuelle pour le tapage biduleur."""
    pass


def _validate_month(month: str) -> str:
    """Parse 'YYYY-MM' ou défaut au mois courant."""
    if not month:
        return datetime.utcnow().strftime("%Y-%m")
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise click.BadParameter(f"month doit être au format YYYY-MM, reçu : {month!r}")
    return month


def _cache_dir(month: str) -> Path:
    p = Path("cache") / month
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_config() -> dict:
    return yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))


@main.command()
@click.option("--month", default=None, help="YYYY-MM (défaut : mois courant)")
def collect(month: str):
    """Collecte les sources → cache/<month>/raw.json"""
    month = _validate_month(month)
    config = _load_config()
    out_path = _cache_dir(month) / "raw.json"

    all_items: list[CollectedItem] = []
    for connector_name in ["outlook", "web", "pdf", "fb", "images"]:
        console.print(f"[bold]→ {connector_name}[/bold]")
        try:
            conn = get_connector(connector_name, config)
            items = list(conn.collect(month))
            console.print(f"  collected: {len(items)} items")
            all_items.extend(items)
        except NotImplementedError as e:
            console.print(f"  [yellow]skip ({e})[/yellow]")
        except Exception as e:
            console.print(f"  [red]error: {e}[/red]")

    out_path.write_text(
        json.dumps([i.model_dump() for i in all_items], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    console.print(f"[green]✓[/green] {len(all_items)} items → {out_path}")


@main.command()
@click.option("--month", default=None)
def normalize(month: str):
    """Normalise via Claude API → cache/<month>/normalized.json"""
    month = _validate_month(month)
    raw_path = _cache_dir(month) / "raw.json"
    out_path = _cache_dir(month) / "normalized.json"

    if not raw_path.exists():
        raise click.UsageError(f"{raw_path} n'existe pas. Lance `tapageur collect` d'abord.")

    items = [CollectedItem.model_validate(d) for d in json.loads(raw_path.read_text(encoding="utf-8"))]
    events = normalize_items(items, month, out_path)

    # Canonicalisation + dédup
    mappings = load_mappings()
    events = canonicalize(events, mappings)
    events = dedup(events)

    out_path.write_text(
        json.dumps([e.model_dump() for e in events], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    console.print(f"[green]✓[/green] {len(events)} events normalisés → {out_path}")


@main.command()
@click.option("--month", default=None)
def preview(month: str):
    """Export CSV pour validation manuelle → cache/<month>/preview.csv"""
    month = _validate_month(month)
    norm_path = _cache_dir(month) / "normalized.json"
    out_path = _cache_dir(month) / "preview.csv"

    if not norm_path.exists():
        raise click.UsageError(f"{norm_path} n'existe pas. Lance `tapageur normalize` d'abord.")

    events = [Event.model_validate(d) for d in json.loads(norm_path.read_text(encoding="utf-8"))]
    export_csv(events, out_path)
    console.print(f"[green]✓[/green] ouvre {out_path} dans LibreOffice pour valider/corriger")


@main.command()
@click.option("--month", default=None)
@click.option("--worksheet", default=None, help="Nom de la feuille cible (défaut : première)")
def push(month: str, worksheet: str):
    """Push le CSV validé vers Google Sheets."""
    month = _validate_month(month)
    csv_path = _cache_dir(month) / "preview.csv"

    if not csv_path.exists():
        raise click.UsageError(f"{csv_path} n'existe pas.")

    sheet_id = os.environ["TAPAGE_SHEET_ID"]
    n = push_csv(csv_path, sheet_id, worksheet)
    console.print(f"[green]✓[/green] {n} lignes pushées vers le sheet")


if __name__ == "__main__":
    main()
