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

from tapageur.batch import retrieve_batch, submit_batch
from tapageur.connectors import get_connector
# Trigger registry registration via imports
from tapageur.connectors import outlook, web, pdf, fb, docs, mailbox  # noqa: F401
from tapageur.dedup import canonicalize, dedup, load_mappings
from tapageur.normalize import normalize_items
from tapageur.push import push_csv
from tapageur.schema import CollectedItem, Event
from tapageur.validate import export_csv


# override=True : .env est source de vérité pour tapageur. Évite que des
# variables vides héritées du shell parent (ex. ANTHROPIC_API_KEY="" injecté
# par certains harnais) ne masquent les vraies valeurs.
load_dotenv(override=True)
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


DEFAULT_CONFIG_PATH = Path("config/sources.yaml")


def _load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Charge un fichier de config sources YAML. Défaut : config/sources.yaml."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


ALL_CONNECTORS = ("outlook", "mailbox", "web", "pdf", "fb", "docs")


@main.command()
@click.option("--month", "months", multiple=True, default=(),
              help="YYYY-MM (défaut : mois courant). Répétable : "
                   "`--month 2026-07 --month 2026-08` produit 1 raw.json par mois "
                   "et partage les fetches HTTP cross-mois (cache in-process).")
@click.option("-c", "--config", "config_path",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=DEFAULT_CONFIG_PATH,
              show_default=True,
              help="Fichier YAML des sources à utiliser. Convention possible : "
                   "config/sources_<YYYY>_<MM>.yaml pour une config dédiée par mois.")
@click.option("--connector", "selected_connectors", multiple=True,
              type=click.Choice(ALL_CONNECTORS),
              help="Re-collecter uniquement ces connecteurs (répétable). "
                   "Mode merge : items des autres connecteurs préservés dans raw.json.")
@click.option("--site", "selected_sites", multiple=True,
              help="Re-collecter uniquement les entrées websites avec ces `name:` "
                   "(répétable). Implique --connector web,pdf. Mode merge actif.")
def collect(months: tuple[str, ...], config_path: Path,
            selected_connectors: tuple[str, ...], selected_sites: tuple[str, ...]):
    """Collecte les sources → cache/<month>/raw.json

    \b
    Modes :
    1. Full (défaut, sans --connector ni --site) : tous les connecteurs
       actifs sont exécutés et raw.json est ré-écrit complètement.
    2. Sélectif (avec --connector et/ou --site) : seuls les connecteurs/sites
       sélectionnés sont exécutés. Les nouveaux items remplacent les anciens
       (matching par source_ref) ; les items hors sélection restent intacts
       dans raw.json. Utile pour re-fetcher une source précise sans relancer
       les autres (ex : `--site eldorado` après un fix du connecteur web).

    \b
    Multi-mois :
    Passer --month plusieurs fois (ex. `--month 2026-07 --month 2026-08`)
    produit un raw.json par mois ciblé. Les fetches HTTP sont mutualisés
    via un cache in-process : la même URL fetchée pour juillet n'est pas
    re-fetchée pour août. Utile pour le bidul d'été (juillet+août fusionnés
    par biduleur en 1 PDF).
    """
    # --month répétable, défaut = mois courant si rien
    if not months:
        months_validated = (_validate_month(None),)
    else:
        months_validated = tuple(_validate_month(m) for m in months)

    config = _load_config(config_path)
    console.print(f"[dim]config: {config_path}[/dim]")

    for i, m in enumerate(months_validated):
        if len(months_validated) > 1:
            console.print(f"\n[bold cyan]═══ MONTH {m} ({i + 1}/{len(months_validated)}) ═══[/bold cyan]")
        _collect_one_month(m, config, selected_connectors, selected_sites)


def _collect_one_month(
    month: str,
    config: dict,
    selected_connectors: tuple[str, ...],
    selected_sites: tuple[str, ...],
) -> None:
    """Logique collect pour un seul mois. Extraite pour le multi-mois."""
    out_path = _cache_dir(month) / "raw.json"
    is_selective = bool(selected_connectors or selected_sites)

    if is_selective:
        # Filtre websites par name si --site passé
        if selected_sites:
            selected_sites_set = set(selected_sites)
            kept_websites = [
                w for w in config.get("websites", [])
                if w.get("name") in selected_sites_set
            ]
            missing = selected_sites_set - {w.get("name") for w in config.get("websites", [])}
            if missing:
                console.print(f"  [yellow]sites inconnus dans la config: {sorted(missing)}[/yellow]")
            config = {**config, "websites": kept_websites}
            # --site implique web + pdf (un site peut être un PDF URL)
            selected_connectors = tuple(set(selected_connectors) | {"web", "pdf"})

        connectors_to_run = set(selected_connectors)
        console.print(f"[dim]mode sélectif : connecteurs={sorted(connectors_to_run)}"
                      + (f", sites={list(selected_sites)}" if selected_sites else "")
                      + "[/dim]")
    else:
        connectors_to_run = set(ALL_CONNECTORS)

    new_items: list[CollectedItem] = []
    for connector_name in ALL_CONNECTORS:
        if connector_name not in connectors_to_run:
            continue
        console.print(f"[bold]→ {connector_name}[/bold]")
        try:
            conn = get_connector(connector_name, config)
            items = list(conn.collect(month))
            console.print(f"  collected: {len(items)} items")
            new_items.extend(items)
        except NotImplementedError as e:
            console.print(f"  [yellow]skip ({e})[/yellow]")
        except Exception as e:
            console.print(f"  [red]error: {e}[/red]")

    if is_selective and out_path.exists():
        # Merge : on garde les items existants dont source_ref n'apparait pas
        # dans new_items (= ne pas dupliquer), puis on append les nouveaux.
        existing_raw = json.loads(out_path.read_text(encoding="utf-8"))
        existing = [CollectedItem.model_validate(d) for d in existing_raw]
        new_refs = {it.source_ref for it in new_items}
        preserved = [it for it in existing if it.source_ref not in new_refs]
        all_items = preserved + new_items
        console.print(f"[dim]merge : {len(preserved)} items préservés, "
                      f"{len(new_items)} re-collectés/ajoutés[/dim]")
    else:
        all_items = new_items

    out_path.write_text(
        json.dumps([i.model_dump() for i in all_items], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    console.print(f"[green]✓[/green] {len(all_items)} items → {out_path}")


def _validate_months(months: tuple[str, ...]) -> tuple[str, ...]:
    """Helper commun aux sous-commandes : --month répétable, défaut = mois courant."""
    if not months:
        return (_validate_month(None),)
    return tuple(_validate_month(m) for m in months)


def _print_month_header(m: str, idx: int, total: int) -> None:
    if total > 1:
        console.print(f"\n[bold cyan]═══ MONTH {m} ({idx + 1}/{total}) ═══[/bold cyan]")


@main.command()
@click.option("--month", "months", multiple=True, default=(),
              help="YYYY-MM (défaut : mois courant). Répétable.")
@click.option("--batch", "use_batch", is_flag=True, default=False,
              help="Soumet via la Batch API (50% off, SLA 24h). "
                   "Récupère ensuite avec `tapageur retrieve`.")
def normalize(months: tuple[str, ...], use_batch: bool):
    """Normalise via Claude API → cache/<month>/normalized.json

    Par défaut : mode synchrone (appels immédiats).
    Avec --batch : soumet en différé et exit ; `tapageur retrieve` finalise.
    Multi-mois : --month répétable, traite chaque mois séquentiellement.
    """
    months_validated = _validate_months(months)
    for i, m in enumerate(months_validated):
        _print_month_header(m, i, len(months_validated))
        _normalize_one_month(m, use_batch)


def _normalize_one_month(month: str, use_batch: bool) -> None:
    raw_path = _cache_dir(month) / "raw.json"
    out_path = _cache_dir(month) / "normalized.json"

    if not raw_path.exists():
        raise click.UsageError(f"{raw_path} n'existe pas. Lance `tapageur collect` d'abord.")

    items = [CollectedItem.model_validate(d) for d in json.loads(raw_path.read_text(encoding="utf-8"))]

    if use_batch:
        try:
            submit_batch(items, month)
        except RuntimeError as e:
            raise click.UsageError(str(e))
        return

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
@click.option("--month", "months", multiple=True, default=(),
              help="YYYY-MM (défaut : mois courant). Répétable.")
def retrieve(months: tuple[str, ...]):
    """Finalise un batch soumis avec `normalize --batch` → normalized.json.

    Multi-mois : --month répétable. Si un batch n'est pas encore prêt pour
    un mois, l'erreur est loggée et les autres mois sont traités quand même.
    """
    months_validated = _validate_months(months)
    for i, m in enumerate(months_validated):
        _print_month_header(m, i, len(months_validated))
        try:
            _retrieve_one_month(m)
        except click.UsageError as e:
            console.print(f"[yellow]skip {m}: {e}[/yellow]")


def _retrieve_one_month(month: str) -> None:
    raw_path = _cache_dir(month) / "raw.json"
    out_path = _cache_dir(month) / "normalized.json"

    if not raw_path.exists():
        raise click.UsageError(f"{raw_path} n'existe pas. Lance `tapageur collect` d'abord.")

    items = [CollectedItem.model_validate(d) for d in json.loads(raw_path.read_text(encoding="utf-8"))]

    try:
        events = retrieve_batch(items, month)
    except RuntimeError as e:
        raise click.UsageError(str(e))

    mappings = load_mappings()
    events = canonicalize(events, mappings)
    events = dedup(events)

    out_path.write_text(
        json.dumps([e.model_dump() for e in events], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    console.print(f"[green]✓[/green] {len(events)} events normalisés → {out_path}")


@main.command()
@click.option("--month", "months", multiple=True, default=(),
              help="YYYY-MM (défaut : mois courant). Répétable.")
def preview(months: tuple[str, ...]):
    """Export CSV pour validation manuelle → cache/<month>/preview.csv

    Multi-mois : --month répétable, génère 1 preview.csv par mois.
    """
    months_validated = _validate_months(months)
    for i, m in enumerate(months_validated):
        _print_month_header(m, i, len(months_validated))
        _preview_one_month(m)


def _preview_one_month(month: str) -> None:
    norm_path = _cache_dir(month) / "normalized.json"
    out_path = _cache_dir(month) / "preview.csv"

    if not norm_path.exists():
        raise click.UsageError(f"{norm_path} n'existe pas. Lance `tapageur normalize` d'abord.")

    events = [Event.model_validate(d) for d in json.loads(norm_path.read_text(encoding="utf-8"))]
    export_csv(events, out_path)
    console.print(f"[green]✓[/green] ouvre {out_path} dans LibreOffice pour valider/corriger")


@main.command()
@click.option("--month", "months", multiple=True, default=(),
              help="YYYY-MM (défaut : mois courant). Répétable.")
@click.option("--worksheet", default=None, help="Nom de la feuille cible (défaut : première)")
def push(months: tuple[str, ...], worksheet: str):
    """Push le CSV validé vers Google Sheets.

    Multi-mois : --month répétable, push chaque preview.csv séquentiellement.
    """
    months_validated = _validate_months(months)
    sheet_id = os.environ["TAPAGE_SHEET_ID"]
    for i, m in enumerate(months_validated):
        _print_month_header(m, i, len(months_validated))
        csv_path = _cache_dir(m) / "preview.csv"
        if not csv_path.exists():
            console.print(f"[yellow]skip {m}: {csv_path} n'existe pas[/yellow]")
            continue
        n = push_csv(csv_path, sheet_id, worksheet)
        console.print(f"[green]✓[/green] {n} lignes pushées vers le sheet")


if __name__ == "__main__":
    main()
