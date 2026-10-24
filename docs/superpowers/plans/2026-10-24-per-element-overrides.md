# Overrides par élément — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Chaque élément de source (fichier / URL / texte) peut forcer le lieu, l'asso/festival, et être marqué « festival (une ligne) ».

**Architecture:** Le cœur applique déjà `raw_metadata["default_venue"]/["default_festival"]` (si absent) et `mode="festival_onliner"`. On enrichit les builders d'items et l'UI pour poser ces métadonnées par élément, + une propagation `default_venue`/`default_festival` dans `WebConnector` (via `_web_item`/extra_meta).

**Tech Stack:** Python 3.11+, pytest, JS (pywebview).

## Global Constraints

- Python `>=3.11`.
- Tous les nouveaux champs de dataclass sont **optionnels** (défauts) → rétrocompatible.
- Clés de métadonnées exactes : `default_venue`, `default_festival`, `mode` (valeur `"festival_onliner"`). Appliquées par item ; `mode` déclenche `FESTIVAL_SYSTEM_PROMPT`.
- Commits en français, terminés par exactement `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

| Fichier | Changement | Tâche |
|---------|-----------|-------|
| `tapageur/connectors/web.py` | Propager `default_venue`/`default_festival` site → item. | T1 |
| `tapageur/gui/inputs.py` | `UrlInput` += venue/info_orga ; `TextInput` += is_festival ; `FileInput` + `items_from_files(list[FileInput])`. | T1/T2/T3 |
| `tapageur/gui/service.py` | `RunRequest.file_paths` → `file_inputs`. | T3 |
| `tapageur/gui/app.py` | `run_extraction` : `FileInput(**f)` depuis `payload["files"]`. | T3 |
| `tapageur/gui/web/index.html` | Contrôles par élément (fichiers en lignes ; url lieu/asso ; texte festival) + payload. | T4 |
| Tests | web/inputs/service/app. | T1-T3 |

---

## Task 1 : URLs — lieu/asso + propagation WebConnector

**Files:**
- Modify: `tapageur/connectors/web.py`, `tapageur/gui/inputs.py`
- Test: `tests/test_web.py`, `tests/gui/test_inputs.py`

**Interfaces:**
- `UrlInput(url, follow_links=False, is_festival=False, venue="", info_orga="")`.
- `_url_to_site` ajoute `default_venue`/`default_festival` au dict site si non vides.
- `WebConnector` : chaque item y:eldé porte `default_venue`/`default_festival` dans `raw_metadata` quand la config du site les contient.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/gui/test_inputs.py` :

```python
def test_url_to_site_carries_overrides():
    site = inputs._url_to_site(inputs.UrlInput(url="https://ex.fr/a", venue="Le Scarron", info_orga="Asso X"))
    assert site["default_venue"] == "Le Scarron"
    assert site["default_festival"] == "Asso X"
```

Ajouter à `tests/test_web.py` :

```python
def test_collect_propagates_overrides_to_items(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    monkeypatch.setattr(web, "_fetch", lambda url, needs_browser=False: "<p>concert</p>")
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/p", "name": "p",
        "follow_event_links": False,
        "default_venue": "Le Scarron", "default_festival": "Asso X",
    }]})
    items = list(conn.collect("2026-11"))
    assert items[0].raw_metadata["default_venue"] == "Le Scarron"
    assert items[0].raw_metadata["default_festival"] == "Asso X"
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/gui/test_inputs.py::test_url_to_site_carries_overrides tests/test_web.py::test_collect_propagates_overrides_to_items -v`
Expected: FAIL (clés `default_venue`/`default_festival` absentes).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/inputs.py` :

```python
@dataclass
class UrlInput:
    """Une URL collée dans l'UI + ses options par-entrée."""
    url: str
    follow_links: bool = False
    is_festival: bool = False
    venue: str = ""
    info_orga: str = ""
```

et dans `_url_to_site`, avant le `return site` :

```python
    if u.venue:
        site["default_venue"] = u.venue
    if u.info_orga:
        site["default_festival"] = u.info_orga
```

Dans `tapageur/connectors/web.py`, `WebConnector.collect`, là où `mode`/
`model_override` sont lus (début de la boucle site), ajouter :

```python
            overrides = {k: site[k] for k in ("default_venue", "default_festival") if site.get(k)}
```

Passer ces overrides dans chaque item :
- **Branche PDF-URL** (après `item = _fetch_pdf_url(...)`, où `mode`/`model_override` sont déjà posés) : ajouter
  ```python
                    item.raw_metadata.update(overrides)
  ```
- **Chaque appel `_web_item(...)`** : ajouter l'argument `extra_meta`. Pour les
  appels qui n'en passaient pas (not-follow + les 3 fallbacks) :
  `_web_item(url, text, site_name, mode, model_override, extra_meta=overrides)`.
  Pour l'appel page-event (qui passe déjà `extra_meta={"agenda_url": url}`) :
  `extra_meta={**overrides, "agenda_url": url}`.

(`_web_item` fusionne déjà `extra_meta` dans `meta` → les clés `default_*` arrivent dans `raw_metadata`.)

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_web.py tests/gui/test_inputs.py -v` puis `pytest -q`
Expected: nouveaux + existants PASS ; suite verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/connectors/web.py tapageur/gui/inputs.py tests/test_web.py tests/gui/test_inputs.py
git commit -m "feat(gui): overrides lieu/asso par URL + propagation WebConnector

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2 : Textes — toggle « festival (une ligne) »

**Files:**
- Modify: `tapageur/gui/inputs.py`
- Test: `tests/gui/test_inputs.py`

**Interfaces:**
- `TextInput(text, venue="", info_orga="", is_festival=False)`.
- `items_from_texts` pose `raw_metadata["mode"]="festival_onliner"` si `is_festival`.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/gui/test_inputs.py` :

```python
def test_items_from_texts_festival_mode():
    out = inputs.items_from_texts([inputs.TextInput(text="festival X", is_festival=True)])
    assert out[0].raw_metadata.get("mode") == "festival_onliner"


def test_items_from_texts_no_mode_by_default():
    out = inputs.items_from_texts([inputs.TextInput(text="concert")])
    assert "mode" not in out[0].raw_metadata
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/gui/test_inputs.py -v -k "festival_mode or no_mode_by_default"`
Expected: FAIL (`TypeError` is_festival inconnu / `mode` absent).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/inputs.py` :

```python
@dataclass
class TextInput:
    """Un texte collé dans l'UI + ses champs éditables (overrides si absents)."""
    text: str
    venue: str = ""
    info_orga: str = ""
    is_festival: bool = False
```

et dans `items_from_texts`, construire la metadata avec le mode conditionnel :

```python
        meta = {"default_venue": t.venue, "default_festival": t.info_orga}
        if t.is_festival:
            meta["mode"] = "festival_onliner"
        items.append(CollectedItem(
            source_kind="text",
            source_ref=f"texte #{i}",
            fetched_at=datetime.utcnow().isoformat() + "Z",
            raw_text=t.text,
            raw_metadata=meta,
        ))
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/gui/test_inputs.py -v` puis `pytest -q`
Expected: nouveaux + existants PASS ; suite verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/inputs.py tests/gui/test_inputs.py
git commit -m "feat(gui): toggle « festival (une ligne) » par texte collé

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3 : Fichiers — `FileInput` + overrides, service + app

**Files:**
- Modify: `tapageur/gui/inputs.py`, `tapageur/gui/service.py`, `tapageur/gui/app.py`
- Test: `tests/gui/test_inputs.py`, `tests/gui/test_service.py`, `tests/gui/test_app.py`

**Interfaces:**
- `FileInput(path: str, venue="", info_orga="", is_festival=False)`.
- `items_from_files(file_inputs: list[FileInput], progress=None)` : route `path` via `_route_file`, puis décore chaque item (`default_venue`/`default_festival` si non vides, `mode="festival_onliner"` si `is_festival`).
- `RunRequest.file_paths` → `file_inputs: list[FileInput] = field(default_factory=list)`.
- `run` : `items_from_files(req.file_inputs, …)`.
- `app.run_extraction` : `file_inputs=[FileInput(**f) for f in payload.get("files", [])]`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/gui/test_inputs.py` :

```python
def test_items_from_files_applies_overrides(tmp_path):
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f1e0000000049454e44ae426082"
    )
    f = tmp_path / "flyer.png"
    f.write_bytes(png)
    out = inputs.items_from_files([
        inputs.FileInput(path=str(f), venue="Le Scarron", info_orga="Asso X", is_festival=True)
    ])
    assert len(out) == 1
    m = out[0].raw_metadata
    assert m["default_venue"] == "Le Scarron"
    assert m["default_festival"] == "Asso X"
    assert m["mode"] == "festival_onliner"
    assert m["filename"] == "flyer.png"   # metadata d'origine préservée
```

Mettre à jour les tests existants de `test_service.py` et `test_app.py` qui
construisent `RunRequest(..., file_paths=[])` → `file_inputs=[]`. Ajouter à
`tests/gui/test_app.py` :

```python
def test_run_extraction_passes_file_inputs(monkeypatch):
    monkeypatch.setattr(app._settings, "load_settings",
                        lambda: {"anthropic_api_key": "sk-test", "tapeur_email": "t@b.fr"})
    captured = {}
    monkeypatch.setattr(app, "run", lambda req, progress=None: captured.update(req=req) or [])
    app.Api().run_extraction({
        "files": [{"path": "/x/flyer.pdf", "venue": "Le Scarron", "info_orga": "A", "is_festival": True}],
        "urls": [], "texts": [], "months": ["2026-11"], "no_month_filter": False,
        "formats": ["json"], "out_dir": ".",
    })
    fis = captured["req"].file_inputs
    assert len(fis) == 1 and fis[0].venue == "Le Scarron" and fis[0].is_festival is True
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/gui/test_inputs.py::test_items_from_files_applies_overrides tests/gui/test_app.py::test_run_extraction_passes_file_inputs -v`
Expected: FAIL (`FileInput` absent / `RunRequest` n'a pas `file_inputs`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/inputs.py`, ajouter le dataclass et réécrire `items_from_files` :

```python
@dataclass
class FileInput:
    """Un fichier déposé/choisi + ses champs éditables par élément."""
    path: str
    venue: str = ""
    info_orga: str = ""
    is_festival: bool = False


def items_from_files(file_inputs: list[FileInput], progress=None) -> list[CollectedItem]:
    """Route chaque fichier via le connecteur docs (liste d'items), puis applique
    les overrides par élément dans raw_metadata (lieu/asso si absents, mode
    festival si demandé)."""
    items: list[CollectedItem] = []
    n = len(file_inputs)
    for i, fi in enumerate(file_inputs, 1):
        if progress:
            progress(f"Fichier {i}/{n} : {Path(fi.path).name}")
        for item in _route_file(Path(fi.path)):
            if fi.venue:
                item.raw_metadata["default_venue"] = fi.venue
            if fi.info_orga:
                item.raw_metadata["default_festival"] = fi.info_orga
            if fi.is_festival:
                item.raw_metadata["mode"] = "festival_onliner"
            items.append(item)
    return items
```

Dans `tapageur/gui/service.py`, le champ du dataclass `RunRequest` :

```python
    file_inputs: list = field(default_factory=list)   # list[FileInput]
```

(remplacer `file_paths: list[Path]`). Importer `FileInput` n'est pas nécessaire
pour l'annotation (liste générique) ; `items_from_files` est déjà importé. Dans
`run`, l'appel devient :

```python
    items = list(items_from_files(req.file_inputs, progress=progress))
```

Dans `tapageur/gui/app.py`, importer `FileInput` et construire :

```python
from tapageur.gui.inputs import FileInput, TextInput, UrlInput
...
            file_inputs=[FileInput(**f) for f in payload.get("files", [])],
```

(remplacer la ligne `file_paths=[Path(p) for p in payload.get("file_paths", [])]`).

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/gui -v` puis `pytest -q`
Expected: nouveaux + existants PASS (les tests service/app mis à jour) ; suite verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/inputs.py tapageur/gui/service.py tapageur/gui/app.py tests/gui/
git commit -m "feat(gui): FileInput + overrides par fichier (lieu/asso/festival)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4 : UI — contrôles par élément

**Files:**
- Modify: `tapageur/gui/web/index.html`

**Interfaces:**
- Fichiers : une **ligne par fichier** (chemin + Lieu [datalist] + Asso/festival + case « festival (une ligne) » + ×). `files` = `[{path, venue, info_orga, is_festival}]`.
- URLs : chaque ligne gagne Lieu [datalist] + Asso/festival ; `collectUrls` ajoute `venue`, `info_orga`.
- Textes : chaque ligne gagne « festival (une ligne) » ; `collectTexts` ajoute `is_festival`.
- Payload : `files: collectFiles()`, urls `{url, follow_links, is_festival, venue, info_orga}`, texts `{text, venue, info_orga, is_festival}`.

> Pas de test auto (UI). Vérif : parse HTML + relance manuelle.

- [ ] **Step 1: Fichiers en lignes**

Remplacer la gestion `files` (tableau de chemins + `renderFiles`) par un tableau
d'objets et un rendu en lignes. `files` devient `[]` d'objets ; le handler
`choose_files` et le drop poussent `{path, venue:"", info_orga:"", is_festival:false}`.
`renderFiles` construit, par fichier, une ligne (tous les champs via DOM/
`.textContent`/`.value`, jamais innerHTML dynamique) :
- un `<span>` avec le chemin ;
- un `<input class="f-venue" list="venues">` (Lieu) ;
- un `<input class="f-orga">` (Asso/festival) ;
- un `<label><input type="checkbox" class="f-fest"> festival (une ligne)</label>` ;
- un bouton « × » qui `files.splice(i,1); renderFiles()`.
Lier les `input`/checkbox à l'objet `files[i]` (sur `change`/`input`, mettre à
jour `files[i].venue` / `.info_orga` / `.is_festival`) pour que l'état survive au
re-render. Ajouter `collectFiles()` qui renvoie `files` tel quel (déjà au bon
format), en filtrant les chemins vides.

- [ ] **Step 2: URLs — Lieu + Asso**

Dans `addUrlRow`, ajouter après les cases existantes deux champs :
`<input type="text" class="u-venue" list="venues" placeholder="Lieu (si absent)">`
et `<input type="text" class="u-orga" placeholder="Asso/festival (si absent)">`
(créés via DOM, comme le bouton ×). Dans `collectUrls`, ajouter :
`venue: r.querySelector('.u-venue').value.trim(), info_orga: r.querySelector('.u-orga').value.trim()`.

- [ ] **Step 3: Textes — case festival**

Dans `addTextRow`, ajouter une case `<label><input type="checkbox" class="tx-fest"> festival (une ligne)</label>` (dans `row2`). Dans `collectTexts`, ajouter :
`is_festival: r.querySelector('.tx-fest').checked`.

- [ ] **Step 4: Payload**

Dans le gestionnaire `#run`, remplacer `file_paths: files` (ou l'ancien) par
`files: collectFiles()`. Les urls/texts passent déjà par `collectUrls()`/
`collectTexts()` enrichis. Adapter le garde « aucune source » pour utiliser
`collectFiles().length` au lieu de `files.length` si nécessaire.

- [ ] **Step 5: Vérif + commit**

Run: `python -c "import html.parser; html.parser.HTMLParser().feed(open(r'tapageur/gui/web/index.html',encoding='utf-8').read()); print('ok')"` ; `pytest -q` (inchangé).
Relire : aucun innerHTML dynamique introduit ; les 3 sections exposent les contrôles ; payload cohérent avec `app.run_extraction` (files objets, urls venue/info_orga, texts is_festival).

```bash
git add tapageur/gui/web/index.html
git commit -m "feat(gui): contrôles par élément (fichiers en lignes, url/texte lieu-asso-festival)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Validation de bout en bout (manuelle)
Déposer une affiche + saisir son lieu + asso, cocher festival sur une URL de
festival, coller un texte avec son lieu : vérifier dans l'xlsx que chaque source
porte bien le lieu (col H) / l'asso (col D) forcés, et que les éléments
« festival » sortent en ligne onliner.

## Hors périmètre
- Griser le Lieu en mode festival.
- Autres champs éditables.
