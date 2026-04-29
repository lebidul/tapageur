"""
Connecteur images : flyers déposés dans flyers/<YYYY-MM>/.
PaddleOCR pour le texte, puis Claude vision en parallèle pour structurer.
"""
from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Iterator

from tapageur.connectors.base import Connector, register
from tapageur.schema import CollectedItem


@register
class ImagesConnector(Connector):
    name = "images"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        base = Path(self.config.get("flyers", {}).get("base_dir", "./flyers"))
        month_dir = base / month
        if not month_dir.exists():
            return

        for img_path in sorted(month_dir.glob("*")):
            if img_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue

            # OCR (rapide, donne un premier filet)
            ocr_text = self._ocr(img_path)

            # Image en base64 pour Claude vision (au moment de la normalisation)
            img_b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")

            yield CollectedItem(
                source_kind="image",
                source_ref=str(img_path),
                fetched_at=datetime.utcnow().isoformat() + "Z",
                raw_text=ocr_text,
                raw_image_b64=img_b64,
                raw_metadata={
                    "filename": img_path.name,
                    "size_bytes": img_path.stat().st_size,
                    "mime": _guess_mime(img_path),
                },
            )

    def _ocr(self, path: Path) -> str:
        """PaddleOCR (déjà utilisé dans Bidul Indexer)."""
        # TODO : importer paddleocr ici (lazy car lourd à charger)
        # from paddleocr import PaddleOCR
        # ocr = PaddleOCR(use_angle_cls=True, lang='fr')
        # result = ocr.ocr(str(path), cls=True)
        # return "\n".join(line[1][0] for block in result for line in block)
        return ""


def _guess_mime(path: Path) -> str:
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
