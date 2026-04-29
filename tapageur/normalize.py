"""
Normalisation : envoie tous les CollectedItem à Claude pour produire des Event[].

Format de prompt : un message system fixe (schéma + colonnes du sheet),
puis chaque item brut (texte + image base64 si disponible) en user messages.
Sortie attendue : JSON list[Event].
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anthropic import Anthropic

from tapageur.schema import CollectedItem, Event


SYSTEM_PROMPT = """\
Tu es un extracteur d'événements culturels pour Le Bidul (fanzine + radio Le Mans).

À partir d'un texte (page web, email, OCR, transcription d'image), tu extrais des
événements structurés au format JSON suivant — UN OBJET PAR LIGNE DU TABLEUR.

Schéma cible (cols du Google Sheet) :
- festival : nom du festival/cycle si applicable, sinon null
- festival_style : style du festival si pertinent
- date_label : date en français lisible (ex. "Vendredi 22")
- date_iso : YYYY-MM-DD
- times : liste d'horaires (ex. ["18h30", "20h30"]) — REGROUPE les multiples horaires d'un même
  spectacle au même lieu le même jour sur UN SEUL événement
- venue : nom canonique du lieu (forme habituelle)
- city : ville
- price : "gratuit", "7€", "12 à 15€", "?" si inconnu
- acts : liste de 1 à 4 actes ; chaque acte a {genre, title, performer, style}
  - genre : "sv" (spectacle vivant), "c" (concert), "expo", "dj", "autre"
  - title : nom du spectacle (pour SV) ou null (pour concerts)
  - performer : artiste / compagnie
  - style : sous-genre / style (optionnel)
- source_kind, source_ref : reportés tels quels depuis l'item d'entrée

Règles importantes :
1. NE JAMAIS inventer un tarif. "?" si non trouvé.
2. NE JAMAIS inventer une heure. Si absent, ne pas créer l'event.
3. Regrouper les horaires multiples du même artiste/spectacle même lieu même jour : un seul Event
   avec times=[...].
4. Si plusieurs artistes au MÊME lieu MÊME date MÊME prix : un seul Event avec acts=[...].
5. Filtrer hors mois cible (passé en user message).
6. Exclure : ateliers, conférences, projections de films, expos sans dates précises.

Réponds en JSON pur (pas de markdown), une liste d'objets Event.
"""


def normalize_items(
    items: list[CollectedItem],
    month: str,
    out_path: Path,
    model: str = "claude-opus-4-7",
) -> list[Event]:
    """
    Envoie les items à Claude par batchs et retourne la liste des Events normalisés
    pour le mois cible. Cache le résultat sur disque (rejouable sans frais).
    """
    if out_path.exists():
        # TODO : flag --force pour bypass cache
        cached = json.loads(out_path.read_text())
        return [Event.model_validate(d) for d in cached]

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    all_events: list[Event] = []
    # TODO : batcher les items (~10 par appel pour rester sous la limite contexte)
    # Pour chaque batch :
    # - construire les user messages (texte + image base64 si présent)
    # - appel client.messages.create(model=..., system=SYSTEM_PROMPT, messages=[...])
    # - parser la réponse JSON
    # - validation Pydantic des Events
    # - filtrage par month (date_iso commence par month)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([e.model_dump() for e in all_events], indent=2, ensure_ascii=False))
    return all_events
