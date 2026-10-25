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
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from pydantic import BaseModel, Field
from rich.console import Console

from tapageur.cache import get_cached, set_cached
from tapageur.schema import Act, CollectedItem, Event, Genre


# Modèle Claude par type de source.
#
# Sonnet 4.5 ($3/$15 per MTok) suffit largement pour les sources simples :
# pages event individuelles (texte court, format standard), emails de
# newsletter (HTML stripped), FB reposts (déjà semi-structuré via Graph API).
#
# Opus 4.7 ($15/$75 per MTok) reste utile pour :
# - PDFs saison : volume dense, paragraphes avec distinction subtile
#   auteur/interprètes, regroupement multi-dates par spectacle.
# - Images flyers : vision + OCR sur compositions chargées, typo créative.
#
# Économie attendue : ~80% sur les 3 sources passées en Sonnet (×5 moins cher).
# Si une régression apparaît côté Sonnet, override possible via `model` param.
MODEL_BY_KIND: dict[str, str] = {
    "web": "claude-sonnet-4-5",
    "outlook": "claude-sonnet-4-5",
    "fb": "claude-sonnet-4-5",
    "pdf": "claude-opus-4-7",
    "image": "claude-opus-4-7",
    "text": "claude-sonnet-4-5",
}
DEFAULT_MODEL = "claude-opus-4-7"  # fallback si source_kind inconnu

# Garde anti-confabulation : un item SANS image dont le texte est quasi vide
# (page JS non rendue, mur de cookies, fetch raté) ne contient aucun event
# réel. L'envoyer au modèle ne peut produire que des hallucinations (il
# « remplit » depuis ses connaissances). En-dessous de ce seuil de caractères
# utiles, on saute l'appel API et on retourne []. Les items image (flyers,
# pages PDF rendues) ont raw_text="" mais portent une image → jamais concernés.
_MIN_TEXT_CHARS = 40


def _supports_adaptive_thinking(model: str) -> bool:
    """Adaptive thinking est une feature Opus 4.x. Sonnet 4.5 ne le supporte
    pas (l'API renvoie 400 "adaptive thinking is not supported on this model").
    Pour les sources routées sur Sonnet (web/outlook/fb), thinking n'apporte
    pas grand-chose de toute façon — extraction de texte structuré simple."""
    return "opus" in model.lower()


SYSTEM_PROMPT = """\
Tu es un extracteur d'événements culturels pour Le Bidul (fanzine + radio Le Mans).

À partir d'un texte (page web, email, OCR, image), extrais les événements
structurés. UN OBJET PAR LIGNE DU TABLEUR.

Schéma des champs à extraire :
- festival : nom du festival/cycle si applicable, sinon null
- festival_style : style du festival si pertinent
- date_label : ignoré pour les events normaux (recalculé côté Python depuis
  date_iso en « Jour N »). date_iso DOIT être exact.
- date_iso : YYYY-MM-DD. Si le contenu ne précise PAS l'année, utilise
  l'année du « Mois cible » (donné dans le user message, ex. 2026-11 → 2026).
  Ne déduis JAMAIS l'année d'un jour de semaine.
- times : liste d'horaires (ex. ["18h30", "20h30"])
- venue : nom du lieu
- city : ville
- price : "gratuit", "7€", "12 à 15€", "?" si inconnu
- acts : liste de 1 à 4 actes ; chaque acte a {genre, title, performer, style}
  - genre : NATURE de l'acte, STRICTEMENT l'une de : "sv" (spectacle vivant),
    "c" (concert), "expo", "autre". Ce n'est PAS le style musical. Un DJ / set
    DJ est un CONCERT → genre="c" (JAMAIS "dj") et mets "DJ" / "DJ set" dans
    style. Dans le doute : "c" pour un concert, "sv" pour du spectacle vivant.
  - title : nom du spectacle (pour SV) ou null (pour concerts)
  - performer : artiste / compagnie
  - style : sous-genre / style musical en TEXTE LIBRE, optionnel (ex. "Rock",
    "Jazz", "Électro", "Chanson"). Les descriptifs de style (« rock », « techno »,
    « DJ »…) vont ICI, JAMAIS dans genre.

Règles importantes :
A. ANCRAGE (CRITIQUE — PRIORITÉ ABSOLUE) :
   - N'extrais QUE des événements littéralement décrits dans le texte fourni.
     Chaque festival, lieu, ville, artiste, spectacle et date que tu produis
     DOIT apparaître explicitement dans le contenu. Tu n'es PAS autorisé à
     compléter, deviner ou remplacer quoi que ce soit avec tes connaissances
     externes (events réels que tu connaîtrais, festivals « typiques » du coin,
     etc.).
   - Si le texte ne décrit AUCUN événement concret et daté (page de
     présentation, édito, « qui sommes-nous », menu de navigation, page
     institutionnelle), retourne events=[]. Mieux vaut ne rien extraire que
     d'inventer. NE FABRIQUE JAMAIS un event pour « remplir » une page qui
     parle de festival sans en lister le programme.
   - Interdiction formelle : produire un nom de festival, de lieu ou d'artiste
     qui n'est pas présent mot pour mot dans le contenu. En cas de doute sur la
     provenance d'une info → ne l'écris pas.
0. DATE (CRITIQUE) :
   - MOIS & JOUR : utilise le mois et le jour RÉELS écrits dans le contenu.
     Le « Mois cible » du user message ne sert QU'À filtrer en aval et à
     fournir l'année manquante — il ne doit JAMAIS changer le mois d'un event.
     Ex. un event « 16 octobre » avec Mois cible 2026-11 → date_iso 2026-10-16
     (il sera filtré ensuite), JAMAIS 2026-11-16. N'écris un event dans le mois
     cible QUE si sa date réelle y tombe.
   - ANNÉE : si le contenu ne précise PAS l'année, utilise l'année du « Mois
     cible » / « année de référence » du user message. Ne déduis JAMAIS l'année
     à partir du seul jour de semaine (plusieurs années partagent le même jour
     — n'invente pas une année passée). N'utilise une autre année que si elle
     est ÉCRITE explicitement dans le contenu.
1. NE JAMAIS inventer un tarif. "?" si non trouvé.
2. NE JAMAIS inventer une heure. Si l'heure est absente, mets times=["?"]
   (même convention que le prix) — ne PAS supprimer l'event. Fréquent pour les
   programmes de festivals : garder l'event, le tapeur complètera l'horaire.
3. Si un spectacle est joué sur PLUSIEURS dates : génère UN Event PAR DATE,
   chacun avec sa propre date_iso et ses propres times. NE JAMAIS regrouper
   plusieurs dates dans un seul Event (même artiste, même lieu).
4. Regrouper les horaires multiples du MÊME artiste/spectacle, MÊME lieu,
   MÊME jour : un seul Event avec times=["16h00", "20h30"] (rendu plus tard
   sous la forme "16h00 & 20h30" dans le CSV).
5. Si plusieurs artistes au MÊME lieu MÊME date MÊME prix : un seul Event avec
   acts=[...] (jusqu'à 4).
6. Filtrer hors mois cible (passé en user message). Retourne events=[] si rien
   ne correspond.
7. Exclure : ateliers, conférences, et TOUT ce qui relève du cinéma —
   projections de films, séances, « nuit du cinéma », festivals de cinéma /
   du film — ainsi que les EXPOSITIONS (genre expo), même avec des dates
   précises. Une mention isolée de « cinéma » dans un programme musical ne
   transforme PAS l'événement en festival de cinéma : n'extrais pas d'event
   cinéma qui ne serait pas réellement décrit comme tel dans le texte.
8. Si l'artiste / compagnie d'un acte n'est pas identifiable dans le contenu,
   mets "?" comme performer (même convention que pour price). NE PAS omettre
   l'event — le tapeur complètera à la main. performer doit toujours être une
   chaîne non vide (jamais null).
9. Si une date apparaît dans une LÉGENDE de photo / illustration plutôt que
   dans une annonce d'event (ex: "Photo prise lors du spectacle X le 14 août",
   "© photo du concert du 21 juillet"), NE PAS la traiter comme un event
   distinct. Les légendes référencent souvent un event déjà listé ailleurs
   dans le document — créer un event séparé causerait un doublon faussement
   placé. Dans le doute, privilégie de NE PAS créer l'event si le contexte
   est manifestement descriptif (légende, crédit photo, rétrospective).

Réponds UNIQUEMENT par un objet JSON valide de la forme :
{"events": [{...}, {...}]}

- AUCUN texte avant ou après le JSON.
- PAS de markdown (pas de ```json…```).
- Liste vide events=[] si rien à extraire.
"""


# Prompt alternatif pour les sources marquées `mode: festival_onliner` dans la
# config. Au lieu d'extraire N events (1 par concert/spectacle), produit UN
# SEUL Event qui résume le festival entier en onliner. Le CSV biduleur le
# rendra dans une section dédiée "Festivals" (cf. PR lebidul/biduleur#106).
FESTIVAL_SYSTEM_PROMPT = """\
Tu es un extracteur d'événements culturels pour Le Bidul (fanzine + radio Le Mans).

MODE FESTIVAL ACTIVÉ : ce contenu décrit UN festival. Au lieu d'extraire
N events (1 par concert/spectacle), produis UN SEUL Event qui résume le
festival entier en onliner.

Champs à renseigner :
- is_festival : true (OBLIGATOIRE)
- festival : nom court du festival (ex. "Festival Eldorado Americana")
- festival_style : description 1-2 phrases incluant le type de festival, la
  fourchette de dates, le lieu, et un résumé de la programmation.
  Ex. "Festival americana, du 26 au 28 juin au Parc du Château de Sablé.
       Charlie Winston, Tiwayo, Keefaz et 4 autres artistes."
- date_label : libre, ex. "27-28 juin" (PAS utilisé par le CSV, pour info)
- date_iso : date du PREMIER jour au format YYYY-MM-DD (utilisé pour
  filtrer par mois cible côté Python)
- times : ["?"] (ignoré par le CSV en mode festival, mais doit être non vide)
- venue : "" (le festival n'a pas de lieu précis ; la VILLE le porte)
- city : ville du festival (obligatoire)
- price : tarif global si dispo, sinon "voir site" ou "?"
- acts : EXACTEMENT 1 acte, structuré comme :
  - genre : "sv" (générique pour festival)
  - title : URL de référence du festival. Cette URL est LUE PAR LE LECTEUR
    du fanzine pour retrouver l'info complète — elle est OBLIGATOIRE si
    disponible. Règle stricte :
      * Si la ligne "Source" ci-dessus commence par "web —" et contient
        une URL (http:// ou https://), TU DOIS mettre cette URL EXACTE
        dans title. Ne PAS résumer, ne PAS traduire, ne PAS null.
      * Si le contenu textuel mentionne un site officiel ou une page
        billetterie du festival, tu peux mettre cette URL à la place.
      * Uniquement si la source est un fichier local (pdf/image) ET que
        le contenu ne mentionne AUCUNE URL, title peut être null.
  - performer : résumé du contenu, ex. "15 spectacles", "8 concerts", ou
    le nom du festival si pas de chiffre. NE JAMAIS null/vide.
  - style : style musical/artistique dominant (ex. "Americana", "Jazz",
    "Cirque", "Pluridisciplinaire")

Règles importantes :
0. ANNÉE : si le contenu ne précise pas l'année, date_iso (1er jour) utilise
   l'année du « Mois cible » du user message (ex. 2026-11 → 2026). Ne déduis
   jamais l'année d'un seul jour de semaine.
1. Filtre par mois cible (passé en user message) sur la base de date_iso.
   Si le festival est entièrement HORS du mois cible, retourne events=[].
2. UN SEUL event dans events=[...] (jamais 0 si dans le mois cible, jamais
   plus de 1).
3. Si tu n'es pas certain que le contenu décrit UN festival (vs un agenda
   de concerts indépendants), retourne quand même 1 event avec is_festival=
   true en faisant de ton mieux pour résumer.
4. Si la source contient des LÉGENDES de photos / crédits visuels qui
   mentionnent des dates (ex: "© photo du concert du 21 juillet"), NE PAS
   les confondre avec des annonces d'event. Une légende est descriptive,
   pas annonciatrice — elle réfère probablement à un event déjà décrit
   ailleurs.

Réponds UNIQUEMENT par un objet JSON valide de la forme :
{"events": [{...}]}

- AUCUN texte avant ou après le JSON.
- PAS de markdown.
- Liste vide events=[] uniquement si le festival est hors mois cible.
"""


_JOURS_FR = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi",
             4: "Vendredi", 5: "Samedi", 6: "Dimanche"}


def _french_date_label(date_iso: str, fallback: str = "") -> str:
    """'2026-06-02' -> 'Mardi 2'. Fallback si date_iso non parsable.

    Jour FR capitalisé + numéro sans zéro initial, sans mois ni année.
    Pas de dépendance à la locale système.
    """
    try:
        dt = datetime.strptime(date_iso, "%Y-%m-%d")
    except (ValueError, TypeError):
        return fallback
    return f"{_JOURS_FR[dt.weekday()]} {dt.day}"


class _EventDraft(BaseModel):
    """Event sans les champs métadonnées (source_kind, source_ref, tapeur_email).
    Ces champs sont setter côté Python en post-processing."""
    festival: str | None = None
    festival_style: str | None = None
    # Optionnel : le prompt demande à Claude d'ignorer date_label (recalculé
    # côté Python depuis date_iso pour les events normaux). Claude l'omet donc
    # souvent → ne PAS rejeter le draft pour autant. Recomposé/coercé dans
    # _normalize_one avant la création de l'Event (qui, lui, exige un str).
    date_label: str | None = None
    date_iso: str
    # Défaut [] : ne pas rejeter le draft si le modèle omet times (event sans
    # horaire). Coercé en ["?"] dans _normalize_one avant la création de
    # l'Event (qui exige au moins 1 horaire via at_least_one_time).
    times: list[str] = Field(default_factory=list)
    venue: str
    city: str
    price: str
    is_festival: bool = False
    acts: list[Act]


class _NormalizationOutput(BaseModel):
    """Wrapper : laisse de la place pour des champs annexes (warnings, notes)
    sans casser le parser plus tard."""
    events: list[_EventDraft]


def _build_user_content(item: CollectedItem, month_hint: str) -> list[dict]:
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

    parts = [
        f"Mois cible : {month_hint}",
        # Source ref : URL pour les items web, chemin local pour PDF/image,
        # Message-ID pour mail. Nécessaire pour que Claude renseigne l'URL
        # dans acts[0].title en mode festival_onliner.
        f"Source : {item.source_kind} — {item.source_ref}",
    ]
    if item.raw_metadata:
        meta = {k: v for k, v in item.raw_metadata.items() if k != "mime"}
        if meta:
            parts.append(f"Métadonnées : {json.dumps(meta, ensure_ascii=False)}")
    if item.raw_text:
        parts.append("--- Contenu ---\n" + item.raw_text)
    blocks.append({"type": "text", "text": "\n\n".join(parts)})
    return blocks


def _extract_json(text: str) -> str:
    """Extrait le bloc JSON de la réponse, en strippant un éventuel
    fencing markdown ```json ... ```."""
    text = text.strip()
    if text.startswith("```"):
        # ```json\n{...}\n```  ou  ```\n{...}\n```
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def _normalize_one(
    client: Anthropic,
    item: CollectedItem,
    month: str,
    model: str | None,
    tapeur_email: str,
    month_filter: bool = True,
    reference_year: str | None = None,
) -> list[Event]:
    """Appelle Claude, parse, valide, filtre par mois, injecte la métadonnée.

    Si `model` est None : sélectionne automatiquement via MODEL_BY_KIND
    selon `item.source_kind`. Passer un modèle explicite force l'override
    (utile pour debug ou test de non-régression Sonnet→Opus).
    """
    # Override par site/path (raw_metadata["model_override"]) > paramètre
    # explicite > sélection auto via MODEL_BY_KIND. L'override permet à un
    # site ou path de forcer un modèle (ex: Sonnet → Opus pour les sources
    # où le défaut est instable).
    # Garde anti-confabulation : pas d'image + texte quasi vide → aucun event
    # réel possible, on n'appelle pas le modèle (cf. _MIN_TEXT_CHARS).
    if not item.raw_image_b64 and len((item.raw_text or "").strip()) < _MIN_TEXT_CHARS:
        print(f"[normalize] {item.source_kind}:{item.source_ref}: contenu vide "
              f"(<{_MIN_TEXT_CHARS} car.), skip (pas d'appel modèle)")
        return []

    meta = item.raw_metadata or {}
    model_override = meta.get("model_override")
    if model_override:
        model = model_override
    elif model is None:
        model = MODEL_BY_KIND.get(item.source_kind, DEFAULT_MODEL)

    # Sélection du prompt selon le mode déclaré dans raw_metadata (propagé
    # depuis la config YAML par le connecteur). Mode classique (mode absent)
    # = SYSTEM_PROMPT historique. "festival_onliner" = prompt dédié qui
    # demande à Claude de compresser en 1 seul Event avec is_festival=true.
    mode = meta.get("mode")
    if mode == "festival_onliner":
        system_prompt = FESTIVAL_SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPT

    if month_filter:
        month_hint = month
    elif reference_year:
        month_hint = (f"tous les mois (année de référence : {reference_year} — "
                      f"utilise cette année pour les dates sans année)")
    else:
        month_hint = "tous les mois (ne pas filtrer par date)"
    kwargs: dict = {
        "model": model,
        "max_tokens": 16000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": _build_user_content(item, month_hint)}],
    }
    if _supports_adaptive_thinking(model):
        kwargs["thinking"] = {"type": "adaptive"}

    response = client.messages.create(**kwargs)

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise ValueError("Réponse Claude sans bloc text")

    raw = _extract_json(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalide : {e}\n--- début réponse ---\n{raw[:500]}")

    # Validation event-par-event (au lieu du model_validate global) : si un
    # event est mal formé (ex. performer null), on log et on skip CET event,
    # mais on garde les autres. Sinon, un seul event défectueux gâcherait
    # tout le mail/PDF.
    raw_events = data.get("events", [])
    if not isinstance(raw_events, list):
        raise ValueError(f"format inattendu : events={raw_events!r}")

    from pydantic import ValidationError  # local import (eviter dep top-level)

    events: list[Event] = []
    for i, draft_data in enumerate(raw_events):
        try:
            draft = _EventDraft.model_validate(draft_data)
        except ValidationError as e:
            # Log condensé du premier champ fautif (typique : performer null).
            first = e.errors()[0] if e.errors() else {}
            field = ".".join(str(p) for p in first.get("loc", []))
            msg = first.get("msg", str(e))
            print(f"    [warn] event {i + 1} invalide ({field}: {msg}), skip")
            continue
        if month_filter and not draft.date_iso.startswith(month):
            continue
        # Overrides fournis à la main (sources texte collé) : seulement si
        # l'info est absente de l'extraction. `meta` est défini en tête de la
        # fonction (item.raw_metadata or {}).
        if meta.get("default_venue") and (not draft.venue or draft.venue.strip() in ("", "?")):
            draft.venue = meta["default_venue"]
        if meta.get("default_festival") and not (draft.festival and draft.festival.strip()):
            draft.festival = meta["default_festival"]
        # Interop biduleur : la colonne DATE des events non-festival doit être
        # de la forme « Jour N » (ex. « Mardi 2 »), dérivée de date_iso et non
        # du texte libre du LLM. Les festivals gardent leur date_label libre
        # (la colonne DATE porte « Festivals » côté export).
        if not draft.is_festival:
            draft.date_label = _french_date_label(draft.date_iso, draft.date_label or "")
        elif draft.date_label is None:
            # Festival : date_label libre (non utilisé par le CSV), mais Event
            # exige un str → coercition si le modèle l'a omis.
            draft.date_label = ""
        # Event sans horaire : garder (times=["?"]) au lieu de le rejeter via
        # at_least_one_time. Fréquent sur les programmes de festivals.
        if not draft.times:
            draft.times = ["?"]
        # Un acte DJ est un concert pour le bidul : genre="c", le « DJ » va en
        # style (jamais genre="dj"). Coercition déterministe (le prompt seul ne
        # garantit pas).
        for _act in draft.acts:
            if _act.genre.value == "dj":
                _act.genre = Genre.CONCERT
                _s = (_act.style or "").strip()
                _act.style = _s if "dj" in _s.lower() else (f"{_s} / DJ" if _s else "DJ")
        # Expositions exclues du bidul (même datées).
        if draft.acts and all(_a.genre.value == "expo" for _a in draft.acts):
            continue
        # Asymétrie historique : Event a des validators (au moins 1 horaire,
        # au moins 1 act) que _EventDraft n'a pas. Donc un draft validé peut
        # encore échouer à la création Event. On catch event-par-event ici
        # aussi (sinon 1 event invalide ruine l'extraction de tout l'item).
        try:
            events.append(Event(
                **draft.model_dump(),
                tapeur_email=tapeur_email,
                source_kind=item.source_kind,
                source_ref=item.source_ref,
            ))
        except ValidationError as e:
            first = e.errors()[0] if e.errors() else {}
            field = ".".join(str(p) for p in first.get("loc", []))
            msg = first.get("msg", str(e))
            print(f"    [warn] event {i + 1} rejeté par Event ({field}: {msg}), skip")
    return events


def normalize_items(
    items: list[CollectedItem],
    month: str,
    out_path: Path,
    model: str | None = None,
    month_filter: bool = True,
    progress: "Callable[[str], None] | None" = None,
    reference_year: str | None = None,
) -> list[Event]:
    """
    Normalise les items en Events filtrés sur le mois cible.

    Cache à 2 niveaux :
    - Cache item-level (cache/normalize/<hash>.json) : seuls les items nouveaux
      ou modifiés (content_hash) déclenchent un appel Claude. Permet de
      re-run librement (ajout d'une source, retry, debug) sans tout repayer.
    - Le fichier `out_path` (cache/<month>/normalized.json) est toujours
      ré-écrit en sortie par le caller (la CLI ajoute canonicalize+dedup).

    Modèle Claude : si `model=None` (défaut), sélection auto via MODEL_BY_KIND
    selon le source_kind de chaque item (Sonnet pour web/outlook/fb, Opus pour
    pdf/image). Forcer un modèle uniforme pour A/B testing.
    """
    console = Console()
    client = Anthropic()
    tapeur_email = os.environ.get("TAPEUR_EMAIL", "lebidul@live.fr")

    n_hit = 0
    n_miss = 0
    all_events: list[Event] = []
    for i, item in enumerate(items, 1):
        ref_short = item.source_ref[:60] + ("…" if len(item.source_ref) > 60 else "")

        if progress:
            progress(f"Extraction {i}/{len(items)} : {ref_short}")

        def _emit_events(evs):
            # Affiche les events en direct (log live de l'UI), pas seulement au
            # bilan final. Pré-pipeline (avant canonicalize/dedup/onliner).
            if not progress:
                return
            for ev in evs:
                arts = ", ".join(a.performer for a in ev.acts)
                progress(f"    • {ev.date_label} — {arts} @ {ev.venue}")

        cached = get_cached(item, month)
        if cached is not None:
            n_hit += 1
            console.print(f"  [{i}/{len(items)}] [dim]cache hit[/dim] {item.source_kind}:{ref_short} → {len(cached)} events")
            all_events.extend(cached)
            _emit_events(cached)
            continue

        n_miss += 1
        console.print(f"  [{i}/{len(items)}] {item.source_kind}:{ref_short}")
        try:
            events = _normalize_one(client, item, month, model, tapeur_email,
                                    month_filter, reference_year)
            console.print(f"    → {len(events)} events (mois {month})")
            set_cached(item, month, events)
            all_events.extend(events)
            _emit_events(events)
        except Exception as e:
            console.print(f"    [red]error: {e}[/red]")

    console.print(f"[dim]cache: {n_hit} hit, {n_miss} miss[/dim]")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([e.model_dump() for e in all_events], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return all_events
