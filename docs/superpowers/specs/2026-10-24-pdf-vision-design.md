# PDF affiche → vision — Design

**Date :** 2026-10-24
**Statut :** validé (brainstorming), prêt pour plan
**Auteur :** Thibault Uzu + Claude

## 1. Problème

Un PDF **sans couche texte** (affiche scannée/vectorielle, ex.
`Affiche_24H_PIANO_2026_print.pdf`) est **sauté** par le connecteur `docs` :
`_pdf_to_item` renvoie `None` quand pdfplumber n'extrait aucun texte → 0 event.

## 2. Objectif

Exploiter ces PDF en les **rendant en images** et en les envoyant à **Claude
vision** (le chemin `source_kind="image"` existe déjà → modèle Opus vision).

## 3. Décisions (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Déclencheur** | Seulement si le PDF n'a **aucun** texte extractible (pdfplumber vide). Un PDF avec texte garde le chemin texte actuel, inchangé. |
| **Rendu** | **Toutes les pages** → **1 `CollectedItem` image par page**. |
| **Dépendance** | **`pypdfium2`** (wheel pip, PDFium embarqué, aucune dépendance système → compatible futur `.exe`) + **`Pillow`** pour encoder en PNG. |
| **Modèle** | `image` → Opus vision (déjà `MODEL_BY_KIND["image"]`). |

## 4. Changements

### `pyproject.toml`
Ajouter aux dépendances principales : `pypdfium2>=4.0`, `Pillow>=10.0`.
(Déps principales car `docs` est utilisé aussi par la CLI.)

### `tapageur/connectors/docs.py`
- Nouveau `_pdf_pages_to_images(path) -> list[CollectedItem]` : ouvre le PDF
  avec pypdfium2, rend chaque page (scale ≈ 2 → ~144 dpi), encode en PNG base64
  via Pillow, retourne un `CollectedItem(source_kind="image", raw_image_b64=…,
  source_ref=f"{path}#page={i+1}", raw_metadata={"filename", "mime":"image/png",
  "label": f"{stem} p{i}", "from_pdf": True})` par page.
- **`_route_file(path)` renvoie désormais `list[CollectedItem]`** (0, 1 ou N) :
  - image → `[_image_to_item(path)]`
  - `.pdf` avec texte → `[item_texte]`
  - `.pdf` sans texte → `_pdf_pages_to_images(path)`
  - extension non gérée → `[]`
- `DocsConnector.collect` : adapte l'appelant (`for item in _route_file(f): yield _decorate(item)` ; `n_yielded`/`n_skipped` ajustés : skipped si la liste est vide).

### `tapageur/gui/inputs.py`
- `items_from_files` : `items.extend(_route_file(Path(p)))` au lieu de l'ancien
  `item = _route_file(...); if item is not None: append`.

## 5. Détails rendu
- `scale=2.0` (≈ 144 dpi) : lisible pour la vision, taille raisonnable
  (une page A4 ≈ 1240×1754 px, bien sous la limite de redimensionnement de
  Claude vision ~1568 px côté long — Claude redimensionne au besoin).
- 1 page = 1 item → 1 appel vision. Une affiche = 1 page.
- `source_ref` inclut `#page=N` → clés de cache distinctes par page.

## 6. Tests (`tests/test_docs.py` — créer ; `tests/gui/test_inputs.py`)
- `_pdf_pages_to_images` sur un PDF 1 page vierge (créé via
  `pypdfium2.PdfDocument.new()` dans le test) → 1 item `source_kind="image"`,
  `raw_image_b64` non vide, `source_ref` finissant par `#page=1`,
  `raw_metadata["from_pdf"] is True`.
- `_route_file` routage : image → liste de 1 image ; PDF texte → liste de 1
  (`source_kind="pdf"`) ; PDF sans texte → bascule vers images (monkeypatch
  `_pdf_to_item` → None et `_pdf_pages_to_images` → `[sentinel]` pour tester le
  routage sans dépendre du rendu) ; extension inconnue → `[]`.
- `items_from_files` : un PDF sans texte (monkeypatch `_route_file` → 2 items
  image) produit bien 2 items.

## 7. Hors périmètre
- OCR texte (PaddleOCR) : on envoie directement l'image à la vision, plus simple
  et meilleur sur les affiches à typo créative.
- Fusion multi-pages en une image.
- Sélection de pages / downscale paramétrable.
