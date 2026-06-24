"""
Connecteur PDF saison — paths LOCAUX uniquement.

Stratégie raw-text-dump : on extrait le texte page par page avec pdfplumber,
on yield UN CollectedItem par PDF avec le texte concaténé. La structuration
est laissée à Claude au moment de la normalisation (cf. memory
feedback_extraction_strategy).

Le résultat est mis en cache JSON (`parsed_cache` dans config) — réutilisable
chaque mois sans relancer pdfplumber.

Les PDFs distribués via une URL HTTP(S) ne passent PAS par ce connecteur :
ils sont déclarés dans la section `websites:` du YAML, et le connecteur web
détecte le Content-Type pdf pour les router en CollectedItem source_kind=pdf
(cf. connectors/web.py::_is_pdf_url, _fetch_pdf_url).
"""
from __future__ import annotations

import json
from datetime import datetime
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
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            # mode propagé dynamiquement depuis la config (sans re-parser
            # le PDF si l'utilisateur ajoute/change le flag).
            mode = entry.get("mode")
            for item_dict in data.get("items", []):
                item = CollectedItem(**item_dict)
                if mode:
                    item.raw_metadata["mode"] = mode
                yield item

    def _parse_and_cache(self, entry: dict, cache_path: Path) -> None:
        """
        Extrait le texte du PDF local via pdfplumber et écrit un JSON
        `{"items": [CollectedItem]}` à `cache_path`.

        Lève FileNotFoundError si le path n'existe pas, ou ValueError si
        l'entrée pointe vers une URL (route à corriger : déménager vers
        la section websites).
        """
        import pdfplumber  # lazy import (lourd)

        path_str: str = entry["path"]
        if path_str.startswith(("http://", "https://")):
            raise ValueError(
                f"season_pdfs n'accepte plus d'URL : {path_str!r}. "
                "Déplace cette source dans la section `websites:` — "
                "le connecteur web détecte le Content-Type pdf automatiquement."
            )

        local_path = Path(path_str)
        if not local_path.exists():
            raise FileNotFoundError(f"PDF introuvable : {path_str}")

        with pdfplumber.open(local_path) as pdf:
            n_pages = len(pdf.pages)
            text = "\n\n".join((p.extract_text() or "") for p in pdf.pages)

        item = CollectedItem(
            source_kind="pdf",
            source_ref=path_str,
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
