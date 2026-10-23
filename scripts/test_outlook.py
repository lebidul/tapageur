"""
Bootstrap Outlook : test isolé de la connexion + listing brut des emails.

But : valider l'auth MSAL + la résolution des folders SANS toucher au cache
mensuel ni dépenser de tokens Claude. On affiche subject/from/date/snippet
pour que tu vérifies que les bons mails remontent avant d'activer le
connecteur dans le pipeline normal.

Premier run :
    python scripts/test_outlook.py
    # → device code flow (lien + code à coller dans un navigateur).
    # → token persisté dans token_cache.bin (refresh auto ~90 jours).

Runs suivants : silencieux, utilise le cache token.

Pour activer dans la prod (après validation) :
    flip `outlook.enabled: false → true` dans config/sources.yaml.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv(override=True)

# Imports projet APRÈS load_dotenv pour que MSAL_CLIENT_ID soit visible.
from tapageur.connectors.outlook import OutlookConnector  # noqa: E402


def main() -> int:
    # Override la config pour pointer sur le dossier de test (mails déjà tapés
    # dans le sheet pour mai — sert de ground truth pour valider l'extraction).
    # La config sur disque n'est pas modifiée.
    outlook_cfg = {
        "enabled": True,
        "folders": ["DATES TAPAGES/Mai 26/tapé"],
        # 180 jours : les annonces d'events peuvent arriver plusieurs mois
        # avant la date du show (saisons, festivals). 60 jours risque de
        # rater les mails tôt.
        "since_days": 180,
    }

    folders = outlook_cfg["folders"]
    since_days = outlook_cfg["since_days"]
    print(f"=== Outlook bootstrap test ===")
    print(f"folders configurés : {folders}")
    print(f"depuis             : {since_days} jours")
    print()

    # Mois passé à .collect() ne sert pas au filtrage Outlook (c'est since_days
    # qui filtre côté Graph API). On passe une valeur valide pour respecter la
    # signature.
    conn = OutlookConnector(outlook_cfg)

    items = []
    for item in conn.collect(month="2026-05"):
        items.append(item)
        meta = item.raw_metadata
        subject = (meta.get("subject") or "").strip()
        sender = meta.get("from") or "?"
        received = meta.get("received") or "?"
        folder = meta.get("folder") or "?"
        snippet = (item.raw_text or "").strip().replace("\n", " ")
        snippet = snippet[:120] + ("..." if len(snippet) > 120 else "")
        print(f"[{folder}] {received[:10]} | {sender}")
        print(f"  Sujet : {subject}")
        print(f"  Aperçu: {snippet}")
        print()

    print(f"=== {len(items)} mails récupérés ===")
    if not items:
        print()
        print("Aucun mail trouvé. Pistes :")
        print("- Les folders configurés existent-ils dans la boîte ?")
        print(f"  → {folders}")
        print(f"- Y a-t-il eu des mails depuis {since_days} jours ?")
        print("- L'auth a-t-elle bien réussi (token_cache.bin créé) ?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
