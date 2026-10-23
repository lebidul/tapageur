"""
Test d'extraction Claude isolé sur les .eml/.msg du dossier mailbox.

Lit cache/mailbox_export/<month>/, lance normalize via Claude (Sonnet 4.5 car
source_kind="outlook"), et affiche les Events extraits groupés par mail
source. Permet de comparer avec ce qui a été saisi à la main dans le sheet
sans polluer cache/<month>/normalized.json.

Bénéficie du cache item-level : re-runs gratuits tant que les fichiers
sources sont inchangés.

Usage :
    python scripts/test_mailbox_extract.py [YYYY-MM]
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

from tapageur.connectors.mailbox import MailboxConnector  # noqa: E402
from tapageur.normalize import normalize_items  # noqa: E402


def main() -> int:
    month = sys.argv[1] if len(sys.argv) > 1 else datetime.utcnow().strftime("%Y-%m")

    print(f"=== Mailbox → Claude extraction — month {month} ===\n")

    conn = MailboxConnector({})
    items = list(conn.collect(month))

    if not items:
        print(f"Aucun mail dans cache/mailbox_export/{month}/. Stop.")
        return 1

    print(f"{len(items)} mails à normaliser via Claude (Sonnet 4.5)\n")

    # Output dédié au test, pas de pollution du pipeline mensuel.
    out_dir = Path("cache") / "test_mailbox_extract"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{month}.json"

    events = normalize_items(items, month, out_path)

    # Index source_ref → item pour retrouver subject/from à l'affichage.
    by_ref = {it.source_ref: it for it in items}

    # Group events par source.
    by_src: dict[str, list] = {}
    for e in events:
        by_src.setdefault(e.source_ref, []).append(e)

    print(f"\n{'=' * 70}")
    print(f"  Résultats : {len(events)} events extraits de {len(by_src)}/{len(items)} mails")
    print(f"{'=' * 70}\n")

    # Affiche chaque mail avec ses events (ou "rien extrait").
    for item in items:
        meta = item.raw_metadata
        subject = (meta.get("subject") or "").strip()
        sender = meta.get("from") or "?"
        filename = meta.get("filename") or "?"
        evs = by_src.get(item.source_ref, [])

        print(f"📧 {filename}")
        print(f"   De     : {sender}")
        print(f"   Sujet  : {subject}")

        if not evs:
            print(f"   → AUCUN event extrait")
        else:
            for e in evs:
                acts = " / ".join(
                    f"{a.performer}" + (f" ({a.style})" if a.style else "")
                    for a in e.acts
                )
                times = " & ".join(e.times)
                fest = f"  [{e.festival}]" if e.festival else ""
                print(f"   → {e.date_iso} {times} | {e.venue}, {e.city} | {e.price} | {acts}{fest}")
        print()

    print(f"Output JSON : {out_path}")
    print(f"Cache item-level : cache/normalize/<hash>.json (re-run gratuit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
