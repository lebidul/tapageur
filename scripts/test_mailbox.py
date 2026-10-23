"""
Test isolé du connecteur mailbox.

Lit cache/mailbox_export/<month>/ et affiche subject/from/date/snippet de chaque
mail trouvé, SANS appeler Claude. Permet de valider le drag-and-drop avant de
lancer `tapageur collect` (qui re-fetch toutes les sources).

Usage :
    python scripts/test_mailbox.py [YYYY-MM]

Défaut : mois courant.
"""
from __future__ import annotations

import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(override=True)

from tapageur.connectors.mailbox import MailboxConnector  # noqa: E402


def main() -> int:
    month = sys.argv[1] if len(sys.argv) > 1 else datetime.utcnow().strftime("%Y-%m")

    print(f"=== Mailbox test — month {month} ===")
    print(f"dossier : cache/mailbox_export/{month}/")
    print()

    conn = MailboxConnector({})  # défauts : cache/mailbox_export/
    items = list(conn.collect(month))

    if not items:
        print("Aucun mail trouvé. Pistes :")
        print(f"- Le dossier cache/mailbox_export/{month}/ existe-t-il ?")
        print("- Y a-t-il des .eml ou .msg dedans ?")
        print("- (.msg requiert : pip install extract-msg)")
        return 0

    for i, item in enumerate(items, 1):
        meta = item.raw_metadata
        subject = (meta.get("subject") or "").strip()
        sender = meta.get("from") or "?"
        received = (meta.get("received") or "?")[:30]
        filename = meta.get("filename") or "?"
        fmt = meta.get("format") or "?"
        # Strip control chars (\r, \f, etc.) qui peuvent réécrire la console
        # quand on print, et collapse les whitespaces multiples.
        import re
        raw = (item.raw_text or "")
        snippet = re.sub(r"[\x00-\x1f\x7f]+", " ", raw)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        snippet = snippet[:140] + ("..." if len(snippet) > 140 else "")

        print(f"[{i}] {filename} ({fmt})")
        print(f"    From   : {sender}")
        print(f"    Date   : {received}")
        print(f"    Subject: {subject}")
        print(f"    Aperçu : {snippet}")
        print()

    print(f"=== {len(items)} mails OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
