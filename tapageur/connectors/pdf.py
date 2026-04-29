"""Connecteur PDF saison : pdfplumber, parsé une fois et caché."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

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
            data = json.loads(cache_path.read_text())
            for item_dict in data.get("items", []):
                yield CollectedItem(**item_dict)

    def _parse_and_cache(self, entry: dict, cache_path: Path) -> None:
        """
        Parsing une-fois : extrait tous les events du PDF saison vers un JSON
        cache. Ensuite chaque mois on relit juste le JSON.
        """
        # TODO : implémenter avec pdfplumber
        # 1. Extraire texte page par page
        # 2. Stocker en CollectedItem (un par event détecté ou un seul "raw" gros bloc)
        # 3. Écrire le JSON
        raise NotImplementedError("TODO: parsing PDF saison")
