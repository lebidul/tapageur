"""
Connecteur Facebook : posts et reposts de la page Le Bidul via Graph API.

Authentification :
- Page Access Token long-lived dans `FB_PAGE_ACCESS_TOKEN` (généré via
  developers.facebook.com → Graph API Explorer → switch user→page +
  Extend Access Token).
- Scopes nécessaires : pages_show_list, pages_read_engagement.

Limite Meta : les events des autres pages ne sont pas accessibles directement,
mais s'ils ont été PARTAGÉS par Le Bidul, le post est dans notre feed avec
typiquement :
- son `message` (commentaire de Le Bidul au moment du share)
- un `attachment` dont Meta cache souvent le contenu ("Ce contenu n'est pas
  disponible actuellement") — on le filtre.

Stratégie : 1 CollectedItem par post (raw text dump), Claude extrait. Pour
les posts dont le seul contenu est une URL d'event sans contexte, Claude
retournera events=[] et c'est OK.

source_kind="fb" → routé sur Sonnet par MODEL_BY_KIND (économique).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Iterator

import requests

from tapageur.connectors.base import Connector, register
from tapageur.schema import CollectedItem


GRAPH_API = "https://graph.facebook.com/v18.0"
POST_FIELDS = (
    "id,created_time,message,story,permalink_url,"
    "attachments{type,title,description,url,target,media_type}"
)
# Préfixe de title qu'on identifie comme "contenu bloqué par Meta".
# Le texte exact varie selon la langue (fr/en), on matche le début.
BLOCKED_PREFIXES = (
    "Ce contenu n",                   # "Ce contenu n'est pas disponible..."
    "This content isn",               # "This content isn't available..."
)
# Patterns de stories qui sont du bruit pur (actions admin sans contenu réel).
# Quand un post a SEULEMENT cette story et rien d'autre d'utile, on le skip
# pour économiser les appels Claude. Empiriquement ~50% des posts d'une page
# active sont de ce type.
NOISE_STORIES = (
    "Le Bidul a actualisé son statut.",
    "Le Bidul a changé sa photo de profil.",
    "Le Bidul a changé sa photo de couverture.",
)


@register
class FacebookConnector(Connector):
    name = "fb"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        fb_cfg = self.config.get("facebook", self.config)
        if not fb_cfg.get("enabled", False):
            return
            yield  # unreachable — force le générateur

        token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
        if not token:
            print("[fb] FB_PAGE_ACCESS_TOKEN absent, skip")
            return

        page_id = fb_cfg.get("page_id", "me")
        since_days = int(fb_cfg.get("since_days", 60))
        since_ts = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp())

        url = f"{GRAPH_API}/{page_id}/feed"
        params: dict | None = {
            "fields": POST_FIELDS,
            "since": since_ts,
            # 25 par page : Meta renvoie "Please reduce the amount of data"
            # après quelques centaines de posts cumulés si limit=50. À 25, on
            # paginie plus mais c'est plus fiable.
            "limit": 25,
            "access_token": token,
        }

        n_yielded = 0
        n_skipped = 0
        n_pages = 0
        while url:
            try:
                resp = requests.get(url, params=params, timeout=20).json()
            except Exception as e:
                print(f"[fb] erreur réseau: {e}")
                break

            if "error" in resp:
                err = resp["error"]
                print(f"[fb] API error: {err.get('message')} (code {err.get('code')})")
                break

            n_pages += 1
            for post in resp.get("data", []):
                item = _post_to_item(post)
                if item is None:
                    n_skipped += 1
                    continue
                n_yielded += 1
                yield item

            # Pagination : suivre paging.next
            url = (resp.get("paging") or {}).get("next")
            params = None  # next URL contient déjà tous les params

        if n_yielded or n_skipped:
            print(f"[fb] {n_yielded} posts utilisables, {n_skipped} sans contenu ({n_pages} pages API)")


def _post_to_item(post: dict) -> CollectedItem | None:
    """Convertit un post Graph API en CollectedItem.

    Retourne None si pas de contenu textuel extractible (post photo sans
    légende dont les attachments sont tous bloqués par Meta, par exemple).
    """
    post_id = post.get("id", "")
    if not post_id:
        return None

    msg = (post.get("message") or "").strip()
    story = (post.get("story") or "").strip()
    created_time = post.get("created_time", "")
    permalink = post.get("permalink_url", "")

    # Flatten les attachments (en filtrant les "contenu bloqué").
    att_lines: list[str] = []
    for att in (post.get("attachments") or {}).get("data", []):
        a_type = att.get("type", "")
        a_title = (att.get("title") or "").strip()
        a_desc = (att.get("description") or "").strip()
        target_url = ((att.get("target") or {}).get("url")) or att.get("url", "") or ""

        if _is_blocked(a_title):
            # Meta cache le contenu — on garde quand même le type + URL si utile
            if target_url:
                att_lines.append(f"[attachment {a_type}: {target_url}]")
            continue

        line_parts = [f"[attachment {a_type}]"]
        if a_title:
            line_parts.append(a_title)
        if a_desc:
            line_parts.append(a_desc)
        if target_url:
            line_parts.append(f"→ {target_url}")
        att_lines.append(" ".join(line_parts))

    raw_parts: list[str] = []
    if story:
        raw_parts.append(f"[story] {story}")
    if msg:
        raw_parts.append(msg)
    raw_parts.extend(att_lines)
    raw_text = "\n\n".join(p for p in raw_parts if p).strip()

    if not raw_text:
        return None

    # Filtre du bruit : si raw_text se réduit à une story système (statut
    # actualisé, changement de photo) SANS message, attachment utile ou
    # URL annexée, on skip. Évite ~50% d'appels Claude inutiles.
    if not msg and not att_lines and story in NOISE_STORIES:
        return None

    return CollectedItem(
        source_kind="fb",
        source_ref=f"fb:{post_id}",
        fetched_at=datetime.utcnow().isoformat() + "Z",
        raw_text=raw_text,
        raw_metadata={
            "post_id": post_id,
            "created_time": created_time,
            "permalink_url": permalink,
            "page": "Le Bidul",
        },
    )


def _is_blocked(title: str) -> bool:
    """True si le title indique un contenu bloqué par Meta (cross-page, privacy)."""
    return any(title.startswith(p) for p in BLOCKED_PREFIXES)
