# PDF affiche → vision — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Exploiter les PDF sans texte (affiches scannées) en rendant leurs pages en images envoyées à Claude vision, au lieu de les sauter.

**Architecture:** Nouveau helper `_pdf_pages_to_images` (pypdfium2 + Pillow) ; `_route_file` renvoie désormais une **liste** de `CollectedItem` (PDF texte → 1 item pdf ; PDF image → N items image ; image → 1 ; inconnu → []). Les deux appelants (`DocsConnector.collect`, GUI `items_from_files`) itèrent la liste. Le chemin `image` existant route vers Opus vision.

**Tech Stack:** Python 3.11+, pypdfium2, Pillow, pdfplumber, pytest.

## Global Constraints

- Python `>=3.11`.
- Déclencheur strict : on ne rend en images QUE si pdfplumber n'extrait **aucun** texte. PDF avec texte → chemin texte inchangé.
- `pypdfium2` et `Pillow` sont des **dépendances principales** (le connecteur `docs` sert aussi à la CLI). Import de pypdfium2 **lazy** dans le helper (comme pdfplumber).
- Rendu : `scale=2.0`, 1 image PNG base64 par page, `source_ref = f"{path}#page={i+1}"`.
- Commits en français, terminés par exactement `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

| Fichier | Responsabilité | Neuf / Modifié |
|---------|----------------|----------------|
| `pyproject.toml` | Ajout `pypdfium2`, `Pillow`. | Modifié |
| `tapageur/connectors/docs.py` | `_pdf_pages_to_images` ; `_route_file` → liste ; caller `collect`. | Modifié |
| `tapageur/gui/inputs.py` | `items_from_files` itère la liste. | Modifié |
| `tests/test_docs.py` | Tests rendu + routage. | Créé |
| `tests/gui/test_inputs.py` | Test items_from_files multi-items. | Modifié |

---

## Task 1 : rendu PDF→images (`_pdf_pages_to_images`) + dépendances

**Files:**
- Modify: `pyproject.toml`
- Modify: `tapageur/connectors/docs.py`
- Test: `tests/test_docs.py` (créer)

**Interfaces:**
- Produces: `_pdf_pages_to_images(path: Path) -> list[CollectedItem]` : un `CollectedItem(source_kind="image", raw_image_b64=<png b64>, raw_text="", source_ref=f"{path}#page={i+1}", raw_metadata={"filename": path.name, "mime": "image/png", "label": f"{path.stem} p{i+1}", "from_pdf": True})` par page.

- [ ] **Step 1: Ajouter les dépendances**

Dans `pyproject.toml`, `[project].dependencies`, ajouter :

```toml
    "pypdfium2>=4.0",            # rendu PDF→image pour les affiches sans texte
    "Pillow>=10.0",             # encodage PNG des pages rendues
```

(pypdfium2 et Pillow sont déjà installés dans l'environnement courant.)

- [ ] **Step 2: Écrire le test qui échoue**

Créer `tests/test_docs.py` :

```python
def _blank_pdf(path):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(200, 200)
    with open(path, "wb") as f:
        pdf.save(f)


def test_pdf_pages_to_images_blank(tmp_path):
    from tapageur.connectors.docs import _pdf_pages_to_images
    p = tmp_path / "blank.pdf"
    _blank_pdf(p)
    items = _pdf_pages_to_images(p)
    assert len(items) == 1
    it = items[0]
    assert it.source_kind == "image"
    assert it.raw_image_b64 and len(it.raw_image_b64) > 100
    assert it.source_ref.endswith("#page=1")
    assert it.raw_metadata["from_pdf"] is True
    assert it.raw_metadata["mime"] == "image/png"
```

- [ ] **Step 3: Lancer le test pour vérifier l'échec**

Run: `pytest tests/test_docs.py::test_pdf_pages_to_images_blank -v`
Expected: FAIL (`ImportError`/`AttributeError` : `_pdf_pages_to_images` n'existe pas).

- [ ] **Step 4: Écrire l'implémentation**

Dans `tapageur/connectors/docs.py`, ajouter le helper (près de `_pdf_to_item`) :

```python
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
```

- [ ] **Step 5: Lancer le test + la suite**

Run: `pytest tests/test_docs.py -v` puis `pytest -q`
Expected: PASS ; suite entière verte.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tapageur/connectors/docs.py tests/test_docs.py
git commit -m "feat(docs): rendu PDF→images (pypdfium2) pour les affiches sans texte

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2 : `_route_file` renvoie une liste + appelants

**Files:**
- Modify: `tapageur/connectors/docs.py` (`_route_file` + `DocsConnector.collect`)
- Modify: `tapageur/gui/inputs.py` (`items_from_files`)
- Test: `tests/test_docs.py`, `tests/gui/test_inputs.py`

**Interfaces:**
- Produces: `_route_file(path: Path) -> list[CollectedItem]` :
  - image → `[_image_to_item(path)]`
  - `.pdf` : `item = _pdf_to_item(path)` ; si `item is not None` → `[item]` ; sinon → `_pdf_pages_to_images(path)`
  - autre → `[]`
- `DocsConnector.collect` et `items_from_files` itèrent la liste.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_docs.py` :

```python
def test_route_file_returns_list_for_image(tmp_path):
    from tapageur.connectors.docs import _route_file
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f1e0000000049454e44ae426082"
    )
    f = tmp_path / "x.png"
    f.write_bytes(png)
    out = _route_file(f)
    assert isinstance(out, list) and len(out) == 1
    assert out[0].source_kind == "image"


def test_route_file_unsupported_returns_empty(tmp_path):
    from tapageur.connectors.docs import _route_file
    f = tmp_path / "x.txt"
    f.write_text("rien", encoding="utf-8")
    assert _route_file(f) == []


def test_route_file_pdf_without_text_routes_to_images(tmp_path, monkeypatch):
    import tapageur.connectors.docs as docs
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF-1.4 fake")  # contenu bidon : on monkeypatche le routage
    monkeypatch.setattr(docs, "_pdf_to_item", lambda p: None)      # pas de texte
    sentinel = object()
    monkeypatch.setattr(docs, "_pdf_pages_to_images", lambda p: [sentinel])
    assert docs._route_file(f) == [sentinel]


def test_route_file_pdf_with_text_returns_single(tmp_path, monkeypatch):
    import tapageur.connectors.docs as docs
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    sentinel = object()
    monkeypatch.setattr(docs, "_pdf_to_item", lambda p: sentinel)
    assert docs._route_file(f) == [sentinel]
```

Ajouter à `tests/gui/test_inputs.py` :

```python
def test_items_from_files_extends_multi(monkeypatch, tmp_path):
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(inputs, "_route_file", lambda p: ["a", "b"])
    assert inputs.items_from_files([f]) == ["a", "b"]
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/test_docs.py -v -k route_file` puis `pytest tests/gui/test_inputs.py::test_items_from_files_extends_multi -v`
Expected: FAIL (`_route_file` renvoie encore `CollectedItem | None`, pas une liste).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/connectors/docs.py`, remplacer `_route_file` :

```python
def _route_file(path: Path) -> list[CollectedItem]:
    """Items pour un fichier, selon l'extension (liste : 0, 1 ou N items).

    PDF sans texte extractible → rendu de ses pages en images (vision)."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return [_image_to_item(path)]
    if ext in PDF_EXTS:
        item = _pdf_to_item(path)
        if item is not None:
            return [item]
        return _pdf_pages_to_images(path)
    return []
```

Dans `DocsConnector.collect`, remplacer les deux appels `item = _route_file(...)` :

Branche fichier :

```python
            if p.is_file():
                routed = _route_file(p)
                if routed:
                    for item in routed:
                        n_yielded += 1
                        yield _decorate(item)
                else:
                    n_skipped += 1
                continue
```

Branche dossier (boucle `for f in sorted(p.iterdir())`) :

```python
                    routed = _route_file(f)
                    if routed:
                        for item in routed:
                            n_yielded += 1
                            yield _decorate(item)
                    else:
                        n_skipped += 1
```

Dans `tapageur/gui/inputs.py`, `items_from_files` : remplacer le corps de la
boucle par :

```python
        items.extend(_route_file(Path(p)))
```

(c.-à-d. supprimer le `item = _route_file(...); if item is not None: items.append(item)` au profit de `extend`). Le `progress(...)` par fichier est conservé.

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_docs.py tests/gui/test_inputs.py -v` puis `pytest -q`
Expected: nouveaux + existants PASS (notamment `test_items_from_files_routes_image` / `_skips_unsupported` restent verts avec `extend`). Suite entière verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/connectors/docs.py tapageur/gui/inputs.py tests/test_docs.py tests/gui/test_inputs.py
git commit -m "feat(docs): _route_file renvoie une liste ; PDF sans texte → images

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Validation de bout en bout (manuelle)

Dans l'app, déposer `Affiche_24H_PIANO_2026_print.pdf` (PDF image), mois `2026-11`,
xlsx, Lancer : le PDF est maintenant rendu en image et envoyé à la vision Claude
(Opus) ; des événements doivent être extraits de l'affiche (avec lieu/heures si
lisibles). Un PDF avec texte garde le comportement actuel.

## Hors périmètre
- OCR texte (PaddleOCR).
- Downscale paramétrable / sélection de pages.
