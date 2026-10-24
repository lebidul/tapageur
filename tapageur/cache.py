"""
Cache file-based des résultats de normalisation Claude, indexé par item.

Pourquoi : un même run mensuel peut être relancé plusieurs fois (ajout d'une
source, retry après erreur réseau, debug). Sans cache granulaire, on repaye
tous les appels Claude à chaque relance. Avec ce cache :

- 1 entrée par (source_ref, content_hash, month).
- `content_hash` capture le texte + l'image base64 → si la page change sur le
  site, on invalide automatiquement (re-call Claude).
- `month` dans la clé : un même PDF de saison touché en avril ET en mai
  produit 2 sorties Claude distinctes (filtrage par mois côté Claude actuel).

Stockage : `cache/normalize/<hash>.json` contenant le JSON dumpé des Events
bruts (avant canonicalize/dedup). Gitignored via la règle globale `cache/*`.

Invalidation manuelle : `rm -rf cache/normalize/` pour tout repurger.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tapageur.schema import CollectedItem, Event


CACHE_ROOT = Path("cache") / "normalize"


def _content_hash(item: CollectedItem) -> str:
    """Hash du contenu brut. Si la page change, le hash change → cache miss."""
    h = hashlib.sha256()
    if item.raw_text:
        h.update(item.raw_text.encode("utf-8"))
    if item.raw_image_b64:
        h.update(b"|img|")
        h.update(item.raw_image_b64.encode("ascii"))
    return h.hexdigest()[:16]


def cache_key(item: CollectedItem, month: str) -> str:
    """Clé déterministe : source_ref + hash contenu + mois cible (+ mode si non-classique).

    Le `mode` (ex. "festival_onliner") est ajouté à la clé UNIQUEMENT si
    présent dans raw_metadata. Mode classique (mode absent) garde donc la
    clé historique → préserve les entrées cache déjà calculées avant
    l'introduction du flag mode.
    """
    h = hashlib.sha256()
    h.update(item.source_ref.encode("utf-8"))
    h.update(b"|")
    h.update(_content_hash(item).encode("ascii"))
    h.update(b"|")
    h.update(month.encode("ascii"))
    mode = (item.raw_metadata or {}).get("mode")
    if mode:
        h.update(b"|mode=")
        h.update(str(mode).encode("ascii"))
    model_override = (item.raw_metadata or {}).get("model_override")
    if model_override:
        h.update(b"|model=")
        h.update(str(model_override).encode("ascii"))
    default_venue = (item.raw_metadata or {}).get("default_venue")
    if default_venue:
        h.update(b"|dv=")
        h.update(str(default_venue).encode("utf-8"))
    default_festival = (item.raw_metadata or {}).get("default_festival")
    if default_festival:
        h.update(b"|df=")
        h.update(str(default_festival).encode("utf-8"))
    # PROMPT_VERSION : invalide automatiquement le cache au changement de
    # prompt système (cf. tapageur/version.py). Sans ce bump, modifier les
    # règles dans SYSTEM_PROMPT n'aurait aucun effet visible — les items
    # déjà cachés renverraient l'ancien résultat.
    from tapageur.version import PROMPT_VERSION
    h.update(b"|p=")
    h.update(PROMPT_VERSION.encode("ascii"))
    return h.hexdigest()[:24]


def _cache_path(key: str) -> Path:
    return CACHE_ROOT / f"{key}.json"


def get_cached(item: CollectedItem, month: str) -> list[Event] | None:
    """Retourne les Events cachés pour cet item, ou None si cache miss.

    Robuste aux fichiers corrompus / au schema drift : en cas d'erreur de
    parse, traite comme miss (silencieux). L'appelant re-call Claude et
    écrasera le fichier sain.
    """
    p = _cache_path(cache_key(item, month))
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [Event.model_validate(e) for e in data["events"]]
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def set_cached(item: CollectedItem, month: str, events: list[Event]) -> None:
    """Persiste les Events normalisés pour cet item."""
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    p = _cache_path(cache_key(item, month))
    p.write_text(
        json.dumps(
            {
                "source_ref": item.source_ref,
                "source_kind": item.source_kind,
                "month": month,
                "events": [e.model_dump() for e in events],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
