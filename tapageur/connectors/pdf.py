"""
Connecteur PDF saison.

Stratégie raw-text-dump : on télécharge le PDF (si URL), on extrait le texte
page par page avec pdfplumber, on yield UN CollectedItem par PDF avec le
texte concaténé. La structuration est laissée à Claude au moment de la
normalisation (cf. memory feedback_extraction_strategy).

Le résultat est mis en cache JSON (`parsed_cache` dans config) — réutilisable
chaque mois sans relancer pdfplumber.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

import requests

from tapageur.connectors.base import Connector, register
from tapageur.schema import CollectedItem


@register
class PdfConnector(Connector):
    name = "pdf"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        for entry in self.config.get("season_pdfs", []):
            cache_path = Path(entry["parsed_cache"])
            if not cache_path.exists():
                self._parse_and_cache(entry, cache_path)
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            for item_dict in data.get("items", []):
                yield CollectedItem(**item_dict)

    def _parse_and_cache(self, entry: dict, cache_path: Path) -> None:
        """
        Télécharge le PDF si `path` est une URL, extrait le texte avec
        pdfplumber, écrit un JSON `{"items": [CollectedItem]}` à `cache_path`.
        """
        import pdfplumber  # lazy import (lourd)

        path_or_url: str = entry["path"]
        local_path = _resolve_pdf_path(path_or_url)

        with pdfplumber.open(local_path) as pdf:
            n_pages = len(pdf.pages)
            text = "\n\n".join((p.extract_text() or "") for p in pdf.pages)

        item = CollectedItem(
            source_kind="pdf",
            source_ref=path_or_url,
            fetched_at=datetime.utcnow().isoformat() + "Z",
            raw_text=text,
            raw_metadata={
                "label": entry.get("label"),
                "n_pages": n_pages,
                "local_path": str(local_path),
            },
        )

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"items": [item.model_dump()]}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _resolve_pdf_path(path_or_url: str) -> Path:
    """Si URL : télécharge dans ./season_pdfs/<basename>.pdf et retourne le path
    local. Si chemin local : retourne tel quel (validé existant)."""
    if path_or_url.startswith(("http://", "https://")):
        parsed = urlparse(path_or_url)
        filename = Path(parsed.path).name or "download.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        local = Path("season_pdfs") / filename
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            resp = requests.get(path_or_url, timeout=60)
            resp.raise_for_status()
            local.write_bytes(resp.content)
        return local

    local = Path(path_or_url)
    if not local.exists():
        raise FileNotFoundError(f"PDF introuvable : {path_or_url}")
    return local
