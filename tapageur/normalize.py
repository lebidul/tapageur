"""
Normalisation : envoie chaque CollectedItem à Claude pour produire des Event[].

Stratégie :
- 1 item par appel API (simple, debug facile, retry granulaire ; le prompt
  caching ne s'active que >= 4096 tokens sur Opus 4.7 donc le surcoût du
  non-batching est minime).
- Les champs métadonnées (source_kind, source_ref, tapeur_email) sont setter
  côté Python en post-processing — Claude n'y touche pas (évite les
  hallucinations sur des champs critiques pour le dédup).
- Filtrage par mois strict côté Python (date_iso doit commencer par YYYY-MM).
- Items avec image : content block image base64 + content block texte (l'OCR
  brut sert de filet pour les flyers chargés).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anthropic import Anthropic
from pydantic import BaseModel
from rich.console import Console

from tapageur.schema import Act, CollectedItem, Event


SYSTEM_PROMPT = """\
Tu es un extracteur d'événements culturels pour Le Bidul (fanzine + radio Le Mans).

À partir d'un texte (page web, email, OCR, image), extrais les événements
structurés. UN OBJET PAR LIGNE DU TABLEUR.

Schéma des champs à extraire :
- festival : nom du festival/cycle si applicable, sinon null
- festival_style : style du festival si pertinent
- date_label : date en français lisible (ex. "Vendredi 22")
- date_iso : YYYY-MM-DD
- times : liste d'horaires (ex. ["18h30", "20h30"])
- venue : nom du lieu
- city : ville
- price : "gratuit", "7€", "12 à 15€", "?" si inconnu
- acts : liste de 1 à 4 actes ; chaque acte a {genre, title, performer, style}
  - genre : "sv" (spectacle vivant), "c" (concert), "expo", "dj", "autre"
  - title : nom du spectacle (pour SV) ou null (pour concerts)
  - performer : artiste / compagnie
  - style : sous-genre / style (optionnel)

Règles importantes :
1. NE JAMAIS inventer un tarif. "?" si non trouvé.
2. NE JAMAIS inventer une heure. Si absent, ne pas créer l'event.
3. Regrouper les horaires multiples du même artiste/spectacle, même lieu, même
   jour : un seul Event avec times=[...].
4. Si plusieurs artistes au MÊME lieu MÊME date MÊME prix : un seul Event avec
   acts=[...] (jusqu'à 4).
5. Filtrer hors mois cible (passé en user message). Retourne events=[] si rien
   ne correspond.
6. Exclure : ateliers, conférences, projections de films, expos sans dates
   précises.

Réponds par un objet {"events": [...]}. Liste vide si rien à extraire.
"""


class _EventDraft(BaseModel):
    """Event sans les champs métadonnées (source_kind, source_ref, tapeur_email).
    Ces champs sont setter côté Python en post-processing."""
    festival: str | None = None
    festival_style: str | None = None
    date_label: str
    date_iso: str
    times: list[str]
    venue: str
    city: str
    price: str
    acts: list[Act]


class _NormalizationOutput(BaseModel):
    """Wrapper : laisse de la place pour des champs annexes (warnings, notes)
    sans casser le parser plus tard."""
    events: list[_EventDraft]


def _build_user_content(item: CollectedItem, month: str) -> list[dict]:
    """Construit les content blocks (image base64 si dispo, puis texte)."""
    blocks: list[dict] = []
    if item.raw_image_b64:
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": item.raw_metadata.get("mime", "image/jpeg"),
                "data": item.raw_image_b64,
            },
        })

    parts = [f"Mois cible : {month}"]
    if item.raw_metadata:
        meta = {k: v for k, v in item.raw_metadata.items() if k != "mime"}
        if meta:
            parts.append(f"Métadonnées source : {json.dumps(meta, ensure_ascii=False)}")
    if item.raw_text:
        parts.append("--- Contenu ---\n" + item.raw_text)
    blocks.append({"type": "text", "text": "\n\n".join(parts)})
    return blocks


def _normalize_one(
    client: Anthropic,
    item: CollectedItem,
    month: str,
    model: str,
    tapeur_email: str,
) -> list[Event]:
    """Appelle Claude, valide, filtre par mois, injecte la métadonnée source."""
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        cache_control={"type": "ephemeral"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_content(item, month)}],
        output_format=_NormalizationOutput,
    )

    events: list[Event] = []
    for draft in response.parsed_output.events:
        if not draft.date_iso.startswith(month):
            continue
        events.append(Event(
            **draft.model_dump(),
            tapeur_email=tapeur_email,
            source_kind=item.source_kind,
            source_ref=item.source_ref,
        ))
    return events


def normalize_items(
    items: list[CollectedItem],
    month: str,
    out_path: Path,
    model: str = "claude-opus-4-7",
) -> list[Event]:
    """
    Normalise les items en Events filtrés sur le mois cible.
    Cache le résultat sur disque (rejouable sans frais Claude).
    """
    if out_path.exists():
        cached = json.loads(out_path.read_text(encoding="utf-8"))
        return [Event.model_validate(d) for d in cached]

    console = Console()
    client = Anthropic()
    tapeur_email = os.environ.get("TAPEUR_EMAIL", "lebidul@live.fr")

    all_events: list[Event] = []
    for i, item in enumerate(items, 1):
        ref_short = item.source_ref[:60] + ("…" if len(item.source_ref) > 60 else "")
        console.print(f"  [{i}/{len(items)}] {item.source_kind}:{ref_short}")
        try:
            events = _normalize_one(client, item, month, model, tapeur_email)
            console.print(f"    → {len(events)} events (mois {month})")
            all_events.extend(events)
        except Exception as e:
            console.print(f"    [red]error: {e}[/red]")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([e.model_dump() for e in all_events], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return all_events
