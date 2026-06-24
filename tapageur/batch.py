"""
Pipeline normalize en mode Message Batches API (50% discount, SLA 24h).

Workflow en 2 phases :

- `submit_batch` (jour J-3) :
  - Filtre les items déjà cachés (cache item-level — économise 100%, pas 50%).
  - Construit une request par item miss avec custom_id = cache_key(item, month).
  - Soumet via client.messages.batches.create() et persiste l'état sur disque
    (`cache/<month>/batch_state.json`).

- `retrieve_batch` (jour J-2) :
  - Charge l'état persisté, vérifie que le batch est `ended`.
  - Stream les résultats, parse chaque message, alimente le cache item-level.
  - Re-assemble la liste complète d'Events (résultats batch + cache hits).
  - Idempotent : re-run = relit le cache, n'appelle plus l'API.

Si TOUS les items sont déjà cachés au moment du submit, on court-circuite
sans créer de batch (l'API rejette les batches vides de toute façon).

Sources d'erreur gérées :
- Batch pas encore prêt → exception claire, l'utilisateur réessaie plus tard.
- Item individuel en échec dans le batch → log, on continue les autres.
- Re-run de submit alors qu'un batch existe déjà → exception (éviter doublons).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from rich.console import Console

from tapageur.cache import cache_key, get_cached, set_cached
from tapageur.normalize import (
    DEFAULT_MODEL,
    FESTIVAL_SYSTEM_PROMPT,
    MODEL_BY_KIND,
    SYSTEM_PROMPT,
    _NormalizationOutput,
    _build_user_content,
    _extract_json,
    _supports_adaptive_thinking,
)
from tapageur.schema import CollectedItem, Event


def _state_path(month: str) -> Path:
    return Path("cache") / month / "batch_state.json"


def load_batch_state(month: str) -> dict | None:
    """Charge l'état batch persisté, ou None s'il n'existe pas."""
    p = _state_path(month)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_batch_state(month: str, state: dict) -> None:
    """Persiste l'état batch (atomic write : tmp + rename)."""
    p = _state_path(month)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def clear_batch_state(month: str) -> None:
    """Supprime l'état batch (post-retrieve réussi)."""
    p = _state_path(month)
    if p.exists():
        p.unlink()


def _build_request(item: CollectedItem, month: str) -> dict[str, Any]:
    """Construit une request batch pour un item donné. Route le prompt selon
    item.raw_metadata['mode'] et le modèle selon raw_metadata['model_override']
    (cf. normalize._normalize_one)."""
    meta = item.raw_metadata or {}
    model = meta.get("model_override") or MODEL_BY_KIND.get(item.source_kind, DEFAULT_MODEL)
    mode = meta.get("mode")
    system_prompt = FESTIVAL_SYSTEM_PROMPT if mode == "festival_onliner" else SYSTEM_PROMPT
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": 16000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": _build_user_content(item, month)}],
    }
    if _supports_adaptive_thinking(model):
        params["thinking"] = {"type": "adaptive"}
    return {"custom_id": cache_key(item, month), "params": params}


def submit_batch(items: list[CollectedItem], month: str) -> dict:
    """
    Soumet un batch pour les items en cache miss.

    Retourne l'état batch (batch_id, items, etc.) ou un état "no-op" si tous
    les items étaient déjà cachés.

    Lève une exception si un batch existe déjà pour ce mois (éviter doublons).
    """
    console = Console()

    existing = load_batch_state(month)
    if existing is not None and existing.get("batch_id"):
        raise RuntimeError(
            f"Un batch existe déjà pour {month} : {existing['batch_id']}. "
            f"Lance `tapageur retrieve --month {month}` ou supprime "
            f"{_state_path(month)} pour re-soumettre."
        )

    # Filtre les cache hits (économie 100% vs 50% du batch).
    miss_items: list[CollectedItem] = []
    n_hit = 0
    for item in items:
        if get_cached(item, month) is not None:
            n_hit += 1
        else:
            miss_items.append(item)

    console.print(f"[dim]cache: {n_hit} hit, {len(miss_items)} miss à soumettre[/dim]")

    if not miss_items:
        # Court-circuit : tout est déjà en cache, pas besoin de batch.
        state = {
            "batch_id": None,
            "submitted_at": datetime.utcnow().isoformat() + "Z",
            "month": month,
            "items": [],
            "note": "all cached, no batch submitted",
        }
        save_batch_state(month, state)
        console.print("[green]✓[/green] tous les items sont déjà cachés, rien à soumettre")
        return state

    client = Anthropic()
    requests = [_build_request(item, month) for item in miss_items]
    batch = client.messages.batches.create(requests=requests)

    state = {
        "batch_id": batch.id,
        "submitted_at": datetime.utcnow().isoformat() + "Z",
        "month": month,
        "items": [
            {
                "custom_id": req["custom_id"],
                "source_ref": item.source_ref,
                "source_kind": item.source_kind,
            }
            for req, item in zip(requests, miss_items)
        ],
    }
    save_batch_state(month, state)

    console.print(f"[green]✓[/green] batch soumis : {batch.id} ({len(miss_items)} items)")
    console.print(f"  SLA Anthropic : 24h max. Lance `tapageur retrieve --month {month}` plus tard.")
    return state


def _parse_result_message(message: Any, tapeur_email: str, item_kind: str, item_ref: str, month: str) -> list[Event]:
    """Parse un message Claude (depuis un résultat batch) en list[Event]."""
    text = next((b.text for b in message.content if b.type == "text"), "")
    if not text:
        raise ValueError("Réponse Claude sans bloc text")

    raw = _extract_json(text)
    data = json.loads(raw)
    parsed = _NormalizationOutput.model_validate(data)

    events: list[Event] = []
    for draft in parsed.events:
        if not draft.date_iso.startswith(month):
            continue
        events.append(Event(
            **draft.model_dump(),
            tapeur_email=tapeur_email,
            source_kind=item_kind,
            source_ref=item_ref,
        ))
    return events


def retrieve_batch(items: list[CollectedItem], month: str) -> list[Event]:
    """
    Récupère les résultats du batch + assemble avec les cache hits.

    Doit être appelé avec la même liste `items` que `submit_batch`. Logique :
    - Pour chaque item, vérifier le cache (hits éventuels du run précédent
      OU résultats batch déjà cachés par ce retrieve).
    - Si encore miss → puiser dans les résultats batch tout juste reçus.

    Lève si :
    - aucun batch state pour ce mois (faire submit d'abord)
    - batch pas encore `ended` (réessayer plus tard)
    """
    console = Console()
    tapeur_email = os.environ.get("TAPEUR_EMAIL", "lebidul@live.fr")

    state = load_batch_state(month)
    if state is None:
        raise RuntimeError(
            f"Aucun batch en attente pour {month}. "
            f"Lance `tapageur normalize --month {month} --batch` d'abord."
        )

    # Cas court-circuit : aucun item soumis (tout cache hit au moment du submit).
    if state.get("batch_id") is None:
        console.print("[dim]aucun batch à récupérer (tout en cache au submit)[/dim]")
    else:
        client = Anthropic()
        batch = client.messages.batches.retrieve(state["batch_id"])
        if batch.processing_status != "ended":
            raise RuntimeError(
                f"Batch {state['batch_id']} pas encore terminé "
                f"(statut: {batch.processing_status}). Réessayer plus tard."
            )

        # Index des items soumis par custom_id pour retrouver kind+ref.
        by_custom_id = {it["custom_id"]: it for it in state["items"]}

        n_ok = 0
        n_err = 0
        # Stream des résultats (JSONL). On cache chaque succès via set_cached
        # → retrieve devient idempotent (re-run = relit cache, pas l'API).
        for result in client.messages.batches.results(state["batch_id"]):
            cid = result.custom_id
            meta = by_custom_id.get(cid)
            if meta is None:
                console.print(f"  [yellow]custom_id inconnu : {cid}[/yellow]")
                continue

            if result.result.type != "succeeded":
                err_type = getattr(result.result, "error", None)
                console.print(f"  [red]err {meta['source_kind']}:{meta['source_ref'][:60]} → {result.result.type} {err_type}[/red]")
                n_err += 1
                continue

            try:
                events = _parse_result_message(
                    result.result.message,
                    tapeur_email=tapeur_email,
                    item_kind=meta["source_kind"],
                    item_ref=meta["source_ref"],
                    month=month,
                )
                # Reconstruit un faux CollectedItem juste pour la clé cache.
                # OK car cache_key utilise source_ref + content_hash + month,
                # mais on n'a pas le content original ici. → on stocke
                # directement à la clé custom_id (déjà = cache_key).
                _set_cached_by_key(cid, meta, month, events)
                n_ok += 1
            except Exception as e:
                console.print(f"  [red]parse err {meta['source_ref'][:60]} : {e}[/red]")
                n_err += 1

        console.print(f"[dim]batch results: {n_ok} ok, {n_err} err[/dim]")

    # Assemble : pour chaque item d'origine, lit le cache (peuplé soit par
    # un run antérieur, soit par le batch qu'on vient de retrieve).
    all_events: list[Event] = []
    n_hit = 0
    n_missing = 0
    for item in items:
        cached = get_cached(item, month)
        if cached is None:
            n_missing += 1
            console.print(f"  [yellow]toujours pas en cache : {item.source_ref[:60]}[/yellow]")
            continue
        n_hit += 1
        all_events.extend(cached)

    console.print(f"[dim]assembled: {n_hit}/{len(items)} items, {n_missing} manquants → {len(all_events)} events[/dim]")

    # Cleanup state seulement si tout est OK (sinon on garde pour debug/retry).
    if n_missing == 0:
        clear_batch_state(month)

    return all_events


def _set_cached_by_key(custom_id: str, meta: dict, month: str, events: list[Event]) -> None:
    """Écrit directement au chemin cache/normalize/<custom_id>.json.

    On contourne `cache.set_cached` parce qu'il a besoin d'un CollectedItem
    complet (pour recomputer la clé) — or côté retrieve on n'a plus le
    contenu brut, seulement le custom_id qui EST déjà la clé cache.
    """
    from tapageur.cache import CACHE_ROOT

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    p = CACHE_ROOT / f"{custom_id}.json"
    p.write_text(
        json.dumps(
            {
                "source_ref": meta["source_ref"],
                "source_kind": meta["source_kind"],
                "month": month,
                "events": [e.model_dump() for e in events],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
