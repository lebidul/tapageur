"""
Connecteur Outlook : récupère les emails de dossiers spécifiques via Microsoft Graph API.

Comptes supportés : Outlook.com, Hotmail, Live, Microsoft 365.
Diff avec Gmail : Outlook utilise des DOSSIERS (mailFolders) et non des labels.

Setup une fois :
1. Créer une App Registration sur https://entra.microsoft.com (Azure AD)
   - Type : "Accounts in any organizational directory and personal Microsoft accounts"
   - Redirect URI : Public client (mobile/desktop) → http://localhost
   - API permissions : Mail.Read (déléguées)
2. Récupérer Application (client) ID → MSAL_CLIENT_ID dans .env
3. Premier run : flux device code (lien + code à coller dans le navigateur)
4. Token caché dans token_cache.bin pour les runs suivants (refresh auto)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import requests

from tapageur.connectors.base import Connector, register
from tapageur.schema import CollectedItem


GRAPH_API = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]
TOKEN_CACHE_PATH = Path("token_cache.bin")


@register
class OutlookConnector(Connector):
    name = "outlook"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        if not self.config.get("enabled", False):
            return

        token = self._get_access_token()
        if not token:
            print("[outlook] pas de token, skip")
            return

        folders = self.config.get("folders", [])
        since_days = self.config.get("since_days", 60)
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()

        for folder_path in folders:
            folder_id = self._resolve_folder_id(token, folder_path)
            if not folder_id:
                print(f"[outlook] dossier introuvable : {folder_path}")
                continue
            yield from self._fetch_folder_messages(token, folder_id, since, folder_path)

    # ---------- Auth (MSAL device code flow) ----------

    def _get_access_token(self) -> str | None:
        """
        Auth via MSAL : silencieux si token caché valide, sinon device code flow.
        """
        try:
            import msal  # lazy import pour ne charger que si Outlook est activé
        except ImportError:
            print("[outlook] msal non installé : pip install msal")
            return None

        client_id = os.environ.get("MSAL_CLIENT_ID")
        if not client_id:
            print("[outlook] MSAL_CLIENT_ID absent dans .env")
            return None

        # Cache persistant du token (refresh sans re-auth pendant ~90 jours)
        cache = msal.SerializableTokenCache()
        if TOKEN_CACHE_PATH.exists():
            cache.deserialize(TOKEN_CACHE_PATH.read_text())

        app = msal.PublicClientApplication(
            client_id,
            authority="https://login.microsoftonline.com/consumers",  # comptes perso (live.fr, outlook.com)
            token_cache=cache,
        )

        # 1) Tenter en silencieux depuis le cache
        accounts = app.get_accounts()
        result = None
        if accounts:
            result = app.acquire_token_silent(SCOPES, account=accounts[0])

        # 2) Sinon device code flow (premier run ou refresh expiré)
        if not result:
            flow = app.initiate_device_flow(scopes=SCOPES)
            if "user_code" not in flow:
                print(f"[outlook] échec device flow : {flow}")
                return None
            print(f"\n[outlook] {flow['message']}\n")  # ex. "To sign in, use a web browser to open..."
            result = app.acquire_token_by_device_flow(flow)

        # Persistance cache
        if cache.has_state_changed:
            TOKEN_CACHE_PATH.write_text(cache.serialize())

        return result.get("access_token")

    # ---------- Graph API calls ----------

    def _resolve_folder_id(self, token: str, folder_path: str) -> str | None:
        """
        Résout 'Bidul/Agendas' en ID de dossier.
        Outlook a des dossiers imbriqués : on descend la hiérarchie.
        """
        headers = {"Authorization": f"Bearer {token}"}
        parts = [p for p in folder_path.split("/") if p]

        # Premier niveau : /me/mailFolders
        url = f"{GRAPH_API}/me/mailFolders"
        params = {"$filter": f"displayName eq '{parts[0]}'", "$select": "id,displayName"}
        resp = requests.get(url, headers=headers, params=params, timeout=15).json()
        if not resp.get("value"):
            return None
        current_id = resp["value"][0]["id"]

        # Niveaux suivants : /me/mailFolders/{id}/childFolders
        for sub in parts[1:]:
            url = f"{GRAPH_API}/me/mailFolders/{current_id}/childFolders"
            params = {"$filter": f"displayName eq '{sub}'", "$select": "id,displayName"}
            resp = requests.get(url, headers=headers, params=params, timeout=15).json()
            if not resp.get("value"):
                return None
            current_id = resp["value"][0]["id"]

        return current_id

    def _fetch_folder_messages(
        self, token: str, folder_id: str, since_iso: str, folder_label: str
    ) -> Iterator[CollectedItem]:
        """Itère les messages d'un dossier depuis since_iso, en paginant via @odata.nextLink."""
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{GRAPH_API}/me/mailFolders/{folder_id}/messages"
        params = {
            "$filter": f"receivedDateTime ge {since_iso}",
            "$select": "id,subject,from,receivedDateTime,bodyPreview,body,webLink",
            "$top": 50,
            "$orderby": "receivedDateTime desc",
        }

        while url:
            resp = requests.get(url, headers=headers, params=params, timeout=20).json()
            for msg in resp.get("value", []):
                body = msg.get("body", {})
                # body.contentType peut être "html" ou "text"
                raw_text = _strip_html(body.get("content", "")) if body.get("contentType") == "html" else body.get("content", "")
                yield CollectedItem(
                    source_kind="outlook",
                    source_ref=msg["id"],
                    fetched_at=datetime.utcnow().isoformat() + "Z",
                    raw_text=raw_text,
                    raw_metadata={
                        "subject": msg.get("subject"),
                        "from": (msg.get("from") or {}).get("emailAddress", {}).get("address"),
                        "received": msg.get("receivedDateTime"),
                        "folder": folder_label,
                        "web_link": msg.get("webLink"),
                    },
                )
            url = resp.get("@odata.nextLink")
            params = None  # nextLink contient déjà tous les params


def _strip_html(html: str) -> str:
    """Strip basique HTML → texte. Pour qqch de robuste, utiliser BeautifulSoup."""
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
