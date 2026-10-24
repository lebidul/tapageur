"""
Connecteur docs : remplace l'ancien connecteur images. Accepte fichiers et
dossiers, mixte PDF + images, supporte la substitution `{month}` dans les paths.

Config attendue (section `docs:` dans sources.yaml) :

    docs:
      paths:
        - sources/docs/{month}/           # dossier — tous les fichiers à l'intérieur
        - sources/special/festival.pdf    # fichier individuel
        - sources/affiches/concert.jpg    # autre fichier individuel

Substitution `{month}` : remplacée par le mois cible (passé en CLI). Permet
de garder une config permanente qui marche pour n'importe quel mois. Si tu
préfères hardcoder, écris directement `sources/docs/2026-05/`.

Routage par extension :
- .jpg/.jpeg/.png/.webp/.gif → source_kind="image" (base64 + Claude vision Opus)
- .pdf                       → source_kind="pdf"   (pdfplumber + Claude Opus)
- autre                      → skip silencieux (.DS_Store, .gitkeep, etc.)

Convention : 1 CollectedItem par fichier. source_ref = chemin local
(stable cross-run, alimente le cache item-level).
"""
from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Iterator

from tapageur.connectors.base import Connector, register
from tapageur.schema import CollectedItem


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
PDF_EXTS = {".pdf"}
MIME_BY_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
}


@register
class DocsConnector(Connector):
    name = "docs"

    def collect(self, month: str) -> Iterator[CollectedItem]:
        paths = self.config.get("docs", {}).get("paths", [])
        if not paths:
            return

        n_yielded = 0
        n_skipped = 0
        for raw in paths:
            # Forme 1 : str (path simple, pas de metadata)
            # Forme 2 : dict { path: ..., mode: ..., model: ... } (avec metadata
            # appliquée à tous les items produits par ce path).
            if isinstance(raw, dict):
                path_str = raw.get("path", "")
                entry_mode = raw.get("mode")
                entry_model = raw.get("model")
            else:
                path_str = str(raw)
                entry_mode = None
                entry_model = None

            resolved = path_str.replace("{month}", month)
            p = Path(resolved)

            if not p.exists():
                print(f"[docs] {resolved}: introuvable, skip")
                continue

            def _decorate(item: CollectedItem) -> CollectedItem:
                """Appose mode/model_override si déclarés au niveau du path."""
                if entry_mode:
                    item.raw_metadata["mode"] = entry_mode
                if entry_model:
                    item.raw_metadata["model_override"] = entry_model
                return item

            if p.is_file():
                item = _route_file(p)
                if item is not None:
                    n_yielded += 1
                    yield _decorate(item)
                else:
                    n_skipped += 1
                continue

            if p.is_dir():
                for f in sorted(p.iterdir()):
                    if not f.is_file():
                        continue
                    item = _route_file(f)
                    if item is not None:
                        n_yielded += 1
                        yield _decorate(item)
                    else:
                        n_skipped += 1
                continue

            print(f"[docs] {resolved}: ni fichier ni dossier, skip")

        if n_yielded or n_skipped:
            print(f"[docs] {n_yielded} items collectés, {n_skipped} skipped (ext non supportée)")


def _route_file(path: Path) -> CollectedItem | None:
    """Crée un CollectedItem selon l'extension. None si type non géré."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return _image_to_item(path)
    if ext in PDF_EXTS:
        return _pdf_to_item(path)
    return None


def _image_to_item(path: Path) -> CollectedItem:
    img_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    mime = MIME_BY_EXT.get(path.suffix.lower(), "image/jpeg")
    return CollectedItem(
        source_kind="image",
        source_ref=str(path),
        fetched_at=datetime.utcnow().isoformat() + "Z",
        raw_text="",
        raw_image_b64=img_b64,
        raw_metadata={"filename": path.name, "mime": mime, "label": path.stem},
    )


def _pdf_pages_to_images(path: Path) -> list[CollectedItem]:
    """Rend chaque page d'un PDF en image PNG (base64) → CollectedItem image.

    Utilisé pour les PDF sans couche texte (affiches scannées) : on les envoie
    à Claude vision au lieu de les sauter. pypdfium2 n'a aucune dépendance
    système (PDFium embarqué)."""
    import base64
    import io

    import pypdfium2 as pdfium

    items: list[CollectedItem] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=2.0)
            pil = bitmap.to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            items.append(CollectedItem(
                source_kind="image",
                source_ref=f"{path}#page={i + 1}",
                fetched_at=datetime.utcnow().isoformat() + "Z",
                raw_text="",
                raw_image_b64=b64,
                raw_metadata={
                    "filename": path.name,
                    "mime": "image/png",
                    "label": f"{path.stem} p{i + 1}",
                    "from_pdf": True,
                },
            ))
    finally:
        pdf.close()
    return items


def _pdf_to_item(path: Path) -> CollectedItem | None:
    """Extrait le texte d'un PDF local. None si PDF sans texte (image-only)."""
    import pdfplumber  # lazy
    try:
        with pdfplumber.open(path) as pdf:
            n_pages = len(pdf.pages)
            text = "\n\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as e:
        print(f"[docs] {path.name}: erreur pdfplumber {e}")
        return None
    if not text.strip():
        print(f"[docs] {path.name}: PDF sans texte extractible, skip")
        return None
    return CollectedItem(
        source_kind="pdf",
        source_ref=str(path),
        fetched_at=datetime.utcnow().isoformat() + "Z",
        raw_text=text,
        raw_metadata={"label": path.stem, "n_pages": n_pages, "local_path": str(path)},
    )
