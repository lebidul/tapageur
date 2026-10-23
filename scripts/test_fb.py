"""
Test isolé du connecteur Facebook.

Lit les posts récents de la page Le Bidul via Graph API et affiche
created_time / message / attachments SANS appeler Claude. Permet de valider
le token + la structure des données avant de lancer `tapageur collect`.

Usage :
    python scripts/test_fb.py [since_days]   # défaut : 60
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv(override=True)

from tapageur.connectors.fb import FacebookConnector  # noqa: E402


def main() -> int:
    since_days = int(sys.argv[1]) if len(sys.argv) > 1 else 60

    cfg = {
        "facebook": {
            "enabled": True,
            "page_id": "me",
            "since_days": since_days,
        }
    }
    conn = FacebookConnector(cfg)

    print(f"=== Facebook test — posts de Le Bidul des {since_days} derniers jours ===\n")

    items = list(conn.collect(month="2026-05"))  # month ignoré ici, c'est Claude qui filtre

    if not items:
        print("Aucun post utile trouvé. Pistes :")
        print("- Token expiré ? (vérifier FB_PAGE_ACCESS_TOKEN)")
        print("- Aucun post récent sur la page ?")
        return 0

    for i, item in enumerate(items, 1):
        meta = item.raw_metadata
        created = (meta.get("created_time") or "")[:16].replace("T", " ")
        permalink = meta.get("permalink_url", "")
        snippet = item.raw_text.replace("\n", " | ")[:200]

        print(f"[{i}] {created} — post {meta.get('post_id', '?')[:30]}")
        print(f"    {snippet}")
        if permalink:
            print(f"    URL: {permalink}")
        print()

    print(f"=== {len(items)} posts utilisables ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
