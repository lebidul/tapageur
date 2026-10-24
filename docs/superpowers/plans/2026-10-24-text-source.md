# Source « texte collé » — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ajouter une source « texte collé » dans la GUI, avec deux champs éditables (lieu → col H, asso/orga → col D FESTOCHE/ÉVÉNEMENT) appliqués seulement si l'info est absente du texte extrait.

**Architecture:** Nouveau `source_kind="text"` ; chaque texte collé devient un `CollectedItem` dont `raw_metadata` porte les overrides (`default_venue`, `default_festival`). Les overrides sont appliqués par item dans `normalize._normalize_one` (génériques, sans effet si absents). La GUI expose une section « Textes » + la liste `salles_lieux` pour l'autocomplétion.

**Tech Stack:** Python 3.11+, pydantic, openpyxl, pytest, JS (pywebview).

## Global Constraints

- Python `>=3.11`.
- Overrides appliqués **seulement si le champ extrait est absent** (venue vide/`?` ; festival vide/None) — jamais d'écrasement d'une valeur extraite.
- Pilotage par `raw_metadata` : **aucun effet** pour les sources sans ces clés (rétrocompatible, CLI inchangée).
- `source_kind="text"` ajouté au `Literal` partagé de `CollectedItem` ET `Event`.
- Commits en français, terminés par exactement `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

| Fichier | Responsabilité | Neuf / Modifié |
|---------|----------------|----------------|
| `tapageur/schema.py` | `"text"` dans le `Literal` `source_kind` (CollectedItem + Event). | Modifié |
| `tapageur/normalize.py` | `MODEL_BY_KIND["text"]` ; overrides `default_venue`/`default_festival` dans `_normalize_one`. | Modifié |
| `tapageur/gui/inputs.py` | `TextInput` + `items_from_texts`. | Modifié |
| `tapageur/gui/service.py` | `RunRequest.text_inputs` ; `run` construit les items texte. | Modifié |
| `tapageur/gui/app.py` | `Api.get_venues` ; `run_extraction` lit `payload["texts"]`. | Modifié |
| `tapageur/gui/web/index.html` | Section « Textes » + datalist lieux + payload. | Modifié |
| `tests/test_schema.py`, `tests/test_normalize.py`, `tests/gui/test_inputs.py`, `tests/gui/test_service.py`, `tests/gui/test_app.py` | Tests. | Créé / Modifié |

---

## Task 1: `schema` — `source_kind="text"`

**Files:**
- Modify: `tapageur/schema.py`
- Test: `tests/test_schema.py` (créer si absent)

**Interfaces:**
- Produces: `CollectedItem.source_kind` et `Event.source_kind` acceptent `"text"`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer (ou compléter) `tests/test_schema.py` :

```python
from tapageur.schema import CollectedItem


def test_collected_item_accepts_text_kind():
    item = CollectedItem(
        source_kind="text", source_ref="texte #1",
        fetched_at="2026-01-01T00:00:00Z", raw_text="concert demain",
        raw_metadata={},
    )
    assert item.source_kind == "text"
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/test_schema.py::test_collected_item_accepts_text_kind -v`
Expected: FAIL (`ValidationError` : `"text"` n'est pas une valeur permise du `Literal`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/schema.py`, les **deux** occurrences de
`source_kind: Literal["outlook", "web", "pdf", "fb", "image"]`
(dans `Event` et dans `CollectedItem`) deviennent :

```python
    source_kind: Literal["outlook", "web", "pdf", "fb", "image", "text"]
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_schema.py -v` puis `pytest -q`
Expected: PASS ; suite entière verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/schema.py tests/test_schema.py
git commit -m "feat(schema): source_kind 'text' pour les sources texte collé

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `normalize` — modèle + overrides par item

**Files:**
- Modify: `tapageur/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: `MODEL_BY_KIND["text"] = "claude-sonnet-4-5"`. Dans `_normalize_one`, après validation du `_EventDraft` et le filtre mois, avant la création de l'`Event` : si `meta.get("default_venue")` et `draft.venue` vide/`"?"` → `draft.venue = meta["default_venue"]` ; si `meta.get("default_festival")` et `draft.festival` vide/None → `draft.festival = meta["default_festival"]`. (`meta = item.raw_metadata or {}` existe déjà en tête de `_normalize_one`.)

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_normalize.py` (le helper `_fake_client_returning` existe déjà dans ce fichier, ajouté par la feature month_filter) :

```python
def _text_item(meta):
    from tapageur.schema import CollectedItem
    return CollectedItem(
        source_kind="text", source_ref="texte #1", fetched_at="2026-01-01T00:00:00Z",
        raw_text="x", raw_metadata=meta,
    )


def _ev(venue, festival=None):
    ev = {
        "date_label": "Mardi 3", "date_iso": "2026-11-03", "times": ["20h00"],
        "venue": venue, "city": "Le Mans", "price": "?",
        "acts": [{"genre": "c", "title": None, "performer": "A", "style": None}],
    }
    if festival is not None:
        ev["festival"] = festival
    return ev


def test_default_venue_applied_when_extracted_empty():
    from tapageur import normalize as _norm
    item = _text_item({"default_venue": "Le Scarron"})
    client = _fake_client_returning([_ev(venue="?")])
    out = _norm._normalize_one(client, item, "2026-11", None, "t@b.fr")
    assert out[0].venue == "Le Scarron"


def test_default_venue_not_applied_when_extracted_present():
    from tapageur import normalize as _norm
    item = _text_item({"default_venue": "Le Scarron"})
    client = _fake_client_returning([_ev(venue="La Fonderie")])
    out = _norm._normalize_one(client, item, "2026-11", None, "t@b.fr")
    assert out[0].venue == "La Fonderie"


def test_default_festival_applied_when_extracted_empty():
    from tapageur import normalize as _norm
    item = _text_item({"default_festival": "Asso Bidul"})
    client = _fake_client_returning([_ev(venue="La Fonderie", festival=None)])
    out = _norm._normalize_one(client, item, "2026-11", None, "t@b.fr")
    assert out[0].festival == "Asso Bidul"
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/test_normalize.py -v -k "default_venue or default_festival"`
Expected: FAIL (venue reste `"?"`, festival reste `None` — overrides pas encore implémentés).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/normalize.py` :

Ajouter l'entrée au dict `MODEL_BY_KIND` :

```python
    "text": "claude-sonnet-4-5",
```

Dans `_normalize_one`, dans la boucle `for i, draft_data in enumerate(raw_events):`,
juste après le bloc du filtre mois (`if month_filter and not draft.date_iso.startswith(month): continue`)
et **avant** le `try: events.append(Event(...))`, insérer :

```python
        # Overrides fournis à la main (sources texte collé) : seulement si
        # l'info est absente de l'extraction. `meta` est défini en tête de la
        # fonction (item.raw_metadata or {}).
        if meta.get("default_venue") and (not draft.venue or draft.venue.strip() in ("", "?")):
            draft.venue = meta["default_venue"]
        if meta.get("default_festival") and not (draft.festival and draft.festival.strip()):
            draft.festival = meta["default_festival"]
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_normalize.py -v` puis `pytest -q`
Expected: les 3 nouveaux PASS ; suite entière verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/normalize.py tests/test_normalize.py
git commit -m "feat(normalize): overrides lieu/festival par item + modèle source text

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `inputs` — `TextInput` + `items_from_texts`

**Files:**
- Modify: `tapageur/gui/inputs.py`
- Test: `tests/gui/test_inputs.py`

**Interfaces:**
- Produces:
  - `@dataclass TextInput(text: str, venue: str = "", info_orga: str = "")`
  - `items_from_texts(text_inputs: list[TextInput], progress=None) -> list[CollectedItem]` : pour chaque entrée à `text.strip()` non vide (indexée 1..n), crée `CollectedItem(source_kind="text", source_ref=f"texte #{i}", fetched_at=<iso now>, raw_text=text, raw_metadata={"default_venue": venue, "default_festival": info_orga})`. Émet `progress(f"Texte {i}/{n}…")` si fourni. Ignore les textes vides.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/gui/test_inputs.py` :

```python
def test_items_from_texts_builds_item_with_overrides():
    out = inputs.items_from_texts([
        inputs.TextInput(text="concert ce soir", venue="Le Scarron", info_orga="Asso X"),
    ])
    assert len(out) == 1
    it = out[0]
    assert it.source_kind == "text"
    assert it.raw_text == "concert ce soir"
    assert it.raw_metadata["default_venue"] == "Le Scarron"
    assert it.raw_metadata["default_festival"] == "Asso X"
    assert it.source_ref == "texte #1"


def test_items_from_texts_skips_blank():
    out = inputs.items_from_texts([
        inputs.TextInput(text="   "),
        inputs.TextInput(text="vrai texte"),
    ])
    assert len(out) == 1
    assert out[0].raw_text == "vrai texte"
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/gui/test_inputs.py -v -k texts`
Expected: FAIL (`AttributeError` : `TextInput` / `items_from_texts` absents).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/inputs.py`, ajouter (près des autres définitions, après `items_from_urls`) :

```python
@dataclass
class TextInput:
    """Un texte collé dans l'UI + ses champs éditables (overrides si absents)."""
    text: str
    venue: str = ""
    info_orga: str = ""


def items_from_texts(text_inputs: list[TextInput], progress=None) -> list[CollectedItem]:
    """Construit un CollectedItem (source_kind='text') par texte non vide.
    venue / info_orga sont portés dans raw_metadata et appliqués en aval par
    normalize uniquement si l'event extrait n'a pas déjà l'info."""
    from datetime import datetime
    kept = [t for t in text_inputs if t.text and t.text.strip()]
    items: list[CollectedItem] = []
    n = len(kept)
    for i, t in enumerate(kept, 1):
        if progress:
            progress(f"Texte {i}/{n}…")
        items.append(CollectedItem(
            source_kind="text",
            source_ref=f"texte #{i}",
            fetched_at=datetime.utcnow().isoformat() + "Z",
            raw_text=t.text,
            raw_metadata={"default_venue": t.venue, "default_festival": t.info_orga},
        ))
    return items
```

(Vérifier que `dataclass` et `CollectedItem` sont déjà importés en tête du fichier — ils le sont pour `UrlInput`/`items_from_files`.)

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/gui/test_inputs.py -v` puis `pytest -q`
Expected: nouveaux + existants PASS ; suite verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/inputs.py tests/gui/test_inputs.py
git commit -m "feat(gui): TextInput + items_from_texts (sources texte collé)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `service` — intégrer les textes au run

**Files:**
- Modify: `tapageur/gui/service.py`
- Test: `tests/gui/test_service.py`

**Interfaces:**
- Produces:
  - `RunRequest` gagne `text_inputs: list[TextInput] = field(default_factory=list)` (après `append`).
  - `run` : construit aussi les items texte, `items += list(items_from_texts(req.text_inputs, progress=progress))`, après les fichiers et URLs.
- Consumes: `items_from_texts` (Task 3).

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/gui/test_service.py` :

```python
def test_run_includes_text_inputs(tmp_path, monkeypatch):
    captured = {}
    def fake_normalize(items, month, out_path, model=None, month_filter=True, progress=None):
        captured["items"] = list(items)
        return [_event()]
    monkeypatch.setattr(service, "normalize_items", fake_normalize)
    monkeypatch.setattr(service, "load_mappings", lambda: {})
    monkeypatch.setattr(service, "canonicalize", lambda evs, m: evs)
    monkeypatch.setattr(service, "dedup", lambda evs: evs)
    monkeypatch.setattr(service, "group_events", lambda evs: evs)
    monkeypatch.setattr(service, "convert_to_onliner", lambda evs, names: evs)
    from tapageur.gui.inputs import TextInput
    req = service.RunRequest(
        file_paths=[], url_inputs=[], months=["2026-11"], no_month_filter=False,
        formats=["json"], out_dir=tmp_path, tapeur_email="t@b.fr",
        text_inputs=[TextInput(text="concert", venue="Le Scarron")],
    )
    service.run(req)
    kinds = [it.source_kind for it in captured["items"]]
    assert "text" in kinds
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/gui/test_service.py::test_run_includes_text_inputs -v`
Expected: FAIL (`RunRequest.__init__() got an unexpected keyword argument 'text_inputs'`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/service.py` :

Import : ajouter `items_from_texts` et `TextInput` à l'import depuis `tapageur.gui.inputs` :

```python
from tapageur.gui.inputs import (TextInput, UrlInput, items_from_files,
                                 items_from_texts, items_from_urls)
```

Champ du dataclass (après `append`) :

```python
    append: bool = False
    text_inputs: list[TextInput] = field(default_factory=list)
```

Dans `run`, après la construction des items fichiers + URLs :

```python
    items += list(items_from_texts(req.text_inputs, progress=progress))
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/gui/test_service.py -v` puis `pytest -q`
Expected: nouveau + existants PASS ; suite verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/service.py tests/gui/test_service.py
git commit -m "feat(gui): service intègre les sources texte collé au run

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: GUI — section « Textes » + liste des lieux

**Files:**
- Modify: `tapageur/gui/app.py`
- Modify: `tapageur/gui/web/index.html`
- Test: `tests/gui/test_app.py`

**Interfaces:**
- Produces:
  - `Api.get_venues() -> list[str]` : liste triée de `salles_lieux` (lue depuis le template, comme `service._reference_lists`).
  - `run_extraction` : `text_inputs=[TextInput(**t) for t in payload.get("texts", [])]` dans la construction de `RunRequest`.
  - `index.html` : section « Textes » avec bouton « + Ajouter un texte » (chaque entrée = `<textarea>` + champ lieu lié à `<datalist id="venues">` + champ asso/orga) ; `texts: [{text, venue, info_orga}]` ajouté au payload (clés existantes conservées) ; `<datalist>` peuplé via `get_venues()` au `pywebviewready`.

- [ ] **Step 1: Écrire le test qui échoue (app.py)**

Ajouter à `tests/gui/test_app.py` :

```python
def test_run_extraction_passes_texts(monkeypatch):
    monkeypatch.setattr(app._settings, "load_settings",
                        lambda: {"anthropic_api_key": "sk-test", "tapeur_email": "t@b.fr"})
    captured = {}
    monkeypatch.setattr(app, "run", lambda req, progress=None: captured.update(req=req) or [])
    app.Api().run_extraction({
        "file_paths": [], "urls": [], "texts": [{"text": "concert", "venue": "Le Scarron", "info_orga": "Asso X"}],
        "months": ["2026-11"], "no_month_filter": False, "formats": ["json"], "out_dir": ".",
    })
    tis = captured["req"].text_inputs
    assert len(tis) == 1
    assert tis[0].text == "concert" and tis[0].venue == "Le Scarron" and tis[0].info_orga == "Asso X"


def test_get_venues_returns_list(monkeypatch):
    venues = app.Api().get_venues()
    assert isinstance(venues, list)
    assert len(venues) > 0
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/gui/test_app.py -v -k "texts or venues"`
Expected: FAIL (`text_inputs` absent / `get_venues` absent).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/app.py` :

Import : ajouter `TextInput` à l'import inputs :

```python
from tapageur.gui.inputs import TextInput, UrlInput
```

Méthode `get_venues` dans `Api` (réutilise la lecture du template) :

```python
    def get_venues(self) -> list[str]:
        import openpyxl
        from tapageur.gui import export_xlsx as _xlsx
        wb = openpyxl.load_workbook(_xlsx.TEMPLATE_PATH, read_only=True)
        try:
            venues = {r[0] for r in wb["salles_lieux"].iter_rows(values_only=True) if r and r[0]}
        finally:
            wb.close()
        return sorted(venues)
```

Dans `run_extraction`, ajouter à la construction de `RunRequest` :

```python
            text_inputs=[TextInput(**t) for t in payload.get("texts", [])],
```

Dans `tapageur/gui/web/index.html` :

Ajouter un `<datalist>` (une fois, près du `<body>` ou dans la section Textes) :

```html
  <datalist id="venues"></datalist>
```

Ajouter la section Textes (après la section URLs) :

```html
  <fieldset>
    <legend>Textes</legend>
    <div id="texts"></div>
    <button id="add-text">+ Ajouter un texte</button>
  </fieldset>
```

Dans le `<script>`, la fabrique de ligne + la collecte :

```javascript
function addTextRow() {
  const div = document.createElement('div');
  div.className = 'text-row';
  div.style.margin = '8px 0';
  const ta = document.createElement('textarea');
  ta.rows = 4; ta.style.width = '100%'; ta.placeholder = 'Colle le texte ici…';
  const venue = document.createElement('input');
  venue.type = 'text'; venue.setAttribute('list', 'venues'); venue.placeholder = 'Lieu (si absent du texte)';
  const orga = document.createElement('input');
  orga.type = 'text'; orga.placeholder = 'Asso / organisateur (si absent)';
  venue.className = 'tx-venue'; orga.className = 'tx-orga'; ta.className = 'tx-text';
  div.appendChild(ta);
  const row2 = document.createElement('div'); row2.style.marginTop = '4px';
  row2.appendChild(venue); row2.appendChild(document.createTextNode(' ')); row2.appendChild(orga);
  div.appendChild(row2);
  document.getElementById('texts').appendChild(div);
}
document.getElementById('add-text').addEventListener('click', addTextRow);

function collectTexts() {
  return [...document.querySelectorAll('.text-row')].map(r => ({
    text: r.querySelector('.tx-text').value,
    venue: r.querySelector('.tx-venue').value.trim(),
    info_orga: r.querySelector('.tx-orga').value.trim(),
  })).filter(t => t.text.trim());
}

async function loadVenues() {
  const venues = await api().get_venues();
  const dl = document.getElementById('venues');
  dl.textContent = '';
  for (const v of venues) { const o = document.createElement('option'); o.value = v; dl.appendChild(o); }
}
```

Dans le payload du gestionnaire `#run`, ajouter (clés existantes conservées) :

```javascript
    texts: collectTexts(),
```

Dans le handler `pywebviewready` (qui appelle déjà `loadSettings`), appeler aussi `loadVenues()` :

```javascript
window.addEventListener('pywebviewready', () => { loadSettings(); loadVenues(); });
```

(Si `pywebviewready` appelle actuellement `loadSettings` directement, le remplacer par la version ci-dessus.)

- [ ] **Step 4: Lancer les tests + smoke**

Run: `pytest tests/gui/test_app.py -v` puis `pytest -q`
Expected: nouveaux + existants PASS ; suite verte.
Smoke HTML : `python -c "import html.parser; html.parser.HTMLParser().feed(open(r'tapageur/gui/web/index.html',encoding='utf-8').read()); print('ok')"`.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/app.py tapageur/gui/web/index.html tests/gui/test_app.py
git commit -m "feat(gui): section « Textes » + autocomplétion lieux (source texte collé)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Validation de bout en bout (manuelle)

« + Ajouter un texte », coller une annonce **sans lieu** (ex. « Vendredi 7 novembre
20h30, concert de X »), choisir un lieu dans l'autocomplétion + saisir une asso.
Mois `2026-11`, xlsx. Lancer : l'event extrait doit avoir le **lieu choisi** (col H)
et l'**asso en col D FESTOCHE/ÉVÉNEMENT**. Un texte qui contient déjà un lieu ne
doit PAS se faire écraser par le lieu saisi.

## Hors périmètre
- Autres champs éditables (ville, date, heure, prix, genre).
- Override « toujours ».
