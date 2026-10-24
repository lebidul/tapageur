# Mode append xlsx — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ajouter, en option, les events d'une passe au fichier `tapage_<label>.xlsx` existant (append simple, préservant les lignes déjà présentes), au lieu de le recréer.

**Architecture:** `export_xlsx` gagne un paramètre `append` ; quand il est vrai et que le fichier existe, une branche `_append_xlsx` ouvre le fichier existant et écrit les nouvelles lignes après les anciennes (feuilles de référence et lignes existantes intactes). `service` et la GUI propagent un flag `append`. csv/json inchangés.

**Tech Stack:** Python 3.11+, openpyxl, pytest, JS (pywebview).

## Global Constraints

- Python `>=3.11`.
- **Append = xlsx uniquement.** csv/json toujours recréés.
- **Append simple** : les lignes existantes ne sont jamais modifiées ni supprimées ; on ajoute après la dernière ligne de données de `lebiduleur`.
- Blocs ACT cibles en append = `max(blocs existants, max(len(acts)) de la passe)` ; élargissement des en-têtes si besoin ; jamais de rétrécissement.
- Le **chemin création actuel reste inchangé** (aucune régression de `export_xlsx` en mode normal).
- `append=True` sur un fichier **absent** → création normale. Sur un fichier **sans feuille `lebiduleur`** → `ValueError`.
- Commits en français, terminés par exactement `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

| Fichier | Responsabilité | Neuf / Modifié |
|---------|----------------|----------------|
| `tapageur/gui/export_xlsx.py` | `export_xlsx(..., append=False)` + helper `_append_xlsx`. | Modifié |
| `tapageur/gui/service.py` | `RunRequest.append` ; `_export(..., append)` → xlsx ; alerte si append sans xlsx. | Modifié |
| `tapageur/gui/app.py` | `run_extraction` lit `payload["append"]` → `RunRequest(append=...)`. | Modifié |
| `tapageur/gui/web/index.html` | Case « Ajouter au fichier existant » + `append` dans le payload. | Modifié |
| `tests/gui/test_export_xlsx.py`, `tests/gui/test_service.py`, `tests/gui/test_app.py` | Tests. | Modifié / Créé |

---

## Task 1: `export_xlsx` — mode append

**Files:**
- Modify: `tapageur/gui/export_xlsx.py`
- Test: `tests/gui/test_export_xlsx.py`

**Interfaces:**
- Produces: `export_xlsx(events, out_path, template_path=TEMPLATE_PATH, append=False) -> None`. `append=False` OU fichier absent → comportement actuel inchangé. `append=True` + fichier existant → ouvre le fichier, exige la feuille `lebiduleur` (sinon `ValueError`), calcule `existing_blocks = max(1, (ws.max_column - 10)//4)`, `n_acts = max(existing_blocks, max(len(acts)))`, élargit les en-têtes des blocs `existing_blocks+1..n_acts`, écrit les events à partir de `ws.max_row + 1`, sauve sur place.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/gui/test_export_xlsx.py` (le helper `_event` existe déjà dans ce fichier) :

```python
def test_append_preserves_and_adds(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event(perf="Alpha")], out)                 # création
    export_xlsx.export_xlsx([_event(perf="Beta")], out, append=True)     # append
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    # 1 en-tête + 2 lignes de données
    assert ws.cell(row=2, column=13).value == "Alpha0"   # ARTISTE 1, 1re ligne inchangée
    assert ws.cell(row=3, column=13).value == "Beta0"    # ARTISTE 1, ligne ajoutée
    assert ws.max_row == 3


def test_append_widens_act_blocks(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event(n_acts=1)], out)                     # 4 blocs (template)
    export_xlsx.export_xlsx([_event(n_acts=5, perf="X")], out, append=True)
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    assert ws.cell(row=1, column=11 + 4 * 4).value == "GENRE 5"         # en-tête bloc 5 ajouté
    assert ws.cell(row=3, column=11 + 4 * 4).value == "c"               # genre 5e act, ligne ajoutée


def test_append_without_lebiduleur_raises(tmp_path):
    import openpyxl as _ox
    foreign = tmp_path / "foreign.xlsx"
    wb = _ox.Workbook()
    wb.active.title = "autre"
    wb.save(foreign)
    import pytest
    with pytest.raises(ValueError):
        export_xlsx.export_xlsx([_event()], foreign, append=True)


def test_append_on_missing_file_creates(tmp_path):
    out = tmp_path / "nouveau.xlsx"
    export_xlsx.export_xlsx([_event(perf="Solo")], out, append=True)     # fichier absent
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    assert ws.cell(row=2, column=13).value == "Solo0"
    assert ws.max_row == 2
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/gui/test_export_xlsx.py -v -k append`
Expected: FAIL (`TypeError: export_xlsx() got an unexpected keyword argument 'append'`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/export_xlsx.py`, changer la signature et router vers l'append :

```python
def export_xlsx(events: list[Event], out_path: Path, template_path: Path = TEMPLATE_PATH,
                append: bool = False) -> None:
    """Écrit les events dans la feuille `lebiduleur`.

    append=False (ou fichier absent) : part d'une copie du template (création).
    append=True + fichier existant : ajoute les lignes à la suite, en préservant
    les lignes et feuilles existantes."""
    if append and out_path.exists():
        _append_xlsx(events, out_path)
        return

    wb = openpyxl.load_workbook(template_path)
    ws = wb[DATA_SHEET]
    # ... (corps de création ACTUEL, inchangé) ...
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
```

(Garder le corps de création existant tel quel — seule la signature et le `if append…` en tête changent.)

Ajouter le helper :

```python
def _write_act_headers(ws, first: int, last: int) -> None:
    """Écrit les en-têtes des blocs ACT `first..last` (inclus) sur la ligne 1."""
    for i in range(first, last + 1):
        base = _N_FIXED_COLS + (i - 1) * 4
        ws.cell(row=1, column=base + 1, value=f"GENRE {i}")
        ws.cell(row=1, column=base + 2, value=f"NOM SPECTACLE {i}")
        ws.cell(row=1, column=base + 3, value=f"ARTISTE {i}")
        ws.cell(row=1, column=base + 4, value=f"STYLE {i}")


def _append_xlsx(events: list[Event], out_path: Path) -> None:
    wb = openpyxl.load_workbook(out_path)
    if DATA_SHEET not in wb.sheetnames:
        raise ValueError(
            f"{out_path} n'a pas de feuille '{DATA_SHEET}' : append impossible."
        )
    ws = wb[DATA_SHEET]
    existing_blocks = max(1, (ws.max_column - _N_FIXED_COLS) // 4)
    n_acts = max(existing_blocks, max((len(ev.acts) for ev in events), default=1))
    if n_acts > existing_blocks:
        _write_act_headers(ws, existing_blocks + 1, n_acts)
    start = ws.max_row + 1
    for r, ev in enumerate(events, start=start):
        for c, value in enumerate(event_to_row(ev, n_acts=n_acts), start=1):
            ws.cell(row=r, column=c, value=value)
    wb.save(out_path)
```

(Optionnel mais propre : refactoriser le corps de création pour utiliser `_write_act_headers(ws, 5, n_acts)` à la place de sa boucle d'en-têtes — comportement identique. Ne pas le faire si ça complique.)

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/gui/test_export_xlsx.py -v` puis `pytest -q`
Expected: les 4 nouveaux + les 2 existants PASS ; suite entière verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/export_xlsx.py tests/gui/test_export_xlsx.py
git commit -m "feat(gui): export_xlsx mode append (ajoute au fichier existant)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `service` — propager `append`

**Files:**
- Modify: `tapageur/gui/service.py`
- Test: `tests/gui/test_service.py`

**Interfaces:**
- Produces:
  - `RunRequest` gagne `append: bool = False` (champ final avec défaut).
  - `_export(events, out_dir, label, formats, append=False)` : passe `append` à `_xlsx.export_xlsx(events, p, append=append)` (xlsx seul ; json/csv inchangés).
  - `run` : passe `req.append` à `_export`. Si `req.append and "xlsx" not in req.formats`, ajoute à chaque `MonthResult.alerts` : « Append ignoré : xlsx non sélectionné. »

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/gui/test_service.py` :

```python
def test_export_append_adds_to_existing_xlsx(tmp_path):
    import openpyxl
    service._export([_event(perf="Un")], tmp_path, "2026-11", ["xlsx"], append=False)
    service._export([_event(perf="Deux")], tmp_path, "2026-11", ["xlsx"], append=True)
    ws = openpyxl.load_workbook(tmp_path / "tapage_2026-11.xlsx")["lebiduleur"]
    assert ws.max_row == 3   # en-tête + 2 events


def test_run_append_without_xlsx_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "normalize_items",
                        lambda *a, **k: [_event()])
    monkeypatch.setattr(service, "load_mappings", lambda: {})
    monkeypatch.setattr(service, "canonicalize", lambda evs, m: evs)
    monkeypatch.setattr(service, "dedup", lambda evs: evs)
    monkeypatch.setattr(service, "group_events", lambda evs: evs)
    monkeypatch.setattr(service, "convert_to_onliner", lambda evs, names: evs)
    req = service.RunRequest(
        file_paths=[], url_inputs=[], months=["2026-11"], no_month_filter=False,
        formats=["json"], out_dir=tmp_path, tapeur_email="t@b.fr", append=True,
    )
    results = service.run(req)
    assert any("xlsx" in a.lower() for a in results[0].alerts)
```

Note : `_event` existe déjà dans `test_service.py` ; `normalize_items` est monkeypatché avec `*a, **k` pour absorber le paramètre `progress`.

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/gui/test_service.py -v -k append`
Expected: FAIL (`TypeError: _export() got an unexpected keyword argument 'append'` / `RunRequest.__init__() got an unexpected keyword argument 'append'`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/service.py` :

Ajouter le champ au dataclass (en dernier) :

```python
@dataclass
class RunRequest:
    file_paths: list[Path]
    url_inputs: list[UrlInput]
    months: list[str]
    no_month_filter: bool
    formats: list[str]
    out_dir: Path
    tapeur_email: str
    append: bool = False
```

`_export` :

```python
def _export(events: list[Event], out_dir: Path, label: str, formats: list[str],
            append: bool = False) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if "json" in formats:
        p = out_dir / f"tapage_{label}.json"
        p.write_text(json.dumps([e.model_dump() for e in events], indent=2, ensure_ascii=False),
                     encoding="utf-8")
        written.append(p)
    if "csv" in formats:
        p = out_dir / f"tapage_{label}.csv"
        export_csv(events, p)
        written.append(p)
    if "xlsx" in formats:
        p = out_dir / f"tapage_{label}.xlsx"
        _xlsx.export_xlsx(events, p, append=append)
        written.append(p)
    return written
```

Dans `run`, l'appel export devient (et l'alerte append) :

```python
        files = _export(events, req.out_dir, label, req.formats, append=req.append)
        alerts = build_alerts(events, ref_cities, ref_venues)
        if req.append and "xlsx" not in req.formats:
            alerts.append("Append ignoré : xlsx non sélectionné.")
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/gui/test_service.py -v` puis `pytest -q`
Expected: nouveaux + existants PASS ; suite verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/service.py tests/gui/test_service.py
git commit -m "feat(gui): service propage le flag append vers l'export xlsx

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: GUI — case « Ajouter au fichier existant »

**Files:**
- Modify: `tapageur/gui/app.py`
- Modify: `tapageur/gui/web/index.html`
- Test: `tests/gui/test_app.py` (créé)

**Interfaces:**
- Produces: `app.Api.run_extraction` construit `RunRequest(..., append=payload.get("append", False))`. `index.html` ajoute une case `#append` (section Sortie) et `append: document.getElementById('append').checked` au payload (toutes les clés existantes conservées).

- [ ] **Step 1: Écrire le test qui échoue (app.py)**

Créer `tests/gui/test_app.py` :

```python
from pathlib import Path
import tapageur.gui.app as app


def test_run_extraction_passes_append(monkeypatch):
    # Clé présente → pas de court-circuit "clé absente".
    monkeypatch.setattr(app._settings, "load_settings",
                        lambda: {"anthropic_api_key": "sk-test", "tapeur_email": "t@b.fr"})
    captured = {}
    # dict.update renvoie None → `None or []` → [] (liste de résultats vide),
    # tout en capturant la RunRequest passée à run.
    monkeypatch.setattr(app, "run", lambda req, progress=None: captured.update(req=req) or [])
    res = app.Api().run_extraction({
        "file_paths": [], "urls": [], "months": ["2026-11"],
        "no_month_filter": False, "formats": ["xlsx"], "out_dir": ".",
        "append": True,
    })
    assert "results" in res
    assert captured["req"].append is True
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/gui/test_app.py -v`
Expected: FAIL (`AttributeError` : `RunRequest` n'a pas encore `append` au moment où app le passe — ou `captured["req"].append` absent car app ne le passe pas).

> Prérequis : Task 2 (RunRequest.append) doit être faite avant ce test. Elle l'est (ordre du plan).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/app.py`, `run_extraction`, ajouter le champ à la construction de `RunRequest` :

```python
        req = RunRequest(
            file_paths=[Path(p) for p in payload.get("file_paths", [])],
            url_inputs=[UrlInput(**u) for u in payload.get("urls", [])],
            months=payload.get("months", []),
            no_month_filter=payload.get("no_month_filter", False),
            formats=payload.get("formats", []),
            out_dir=Path(payload.get("out_dir") or "."),
            tapeur_email=cfg.get("tapeur_email", _settings.DEFAULT_TAPEUR_EMAIL),
            append=payload.get("append", False),
        )
```

Dans `tapageur/gui/web/index.html`, section **Sortie** (sous les cases de format), ajouter la case :

```html
    <div style="margin-top:8px">
      <label><input id="append" type="checkbox"> Ajouter au fichier existant (xlsx)</label>
    </div>
```

Et dans le `payload` du gestionnaire `#run`, ajouter la clé (sans toucher aux autres) :

```javascript
    append: document.getElementById('append').checked,
```

- [ ] **Step 4: Lancer les tests + smoke**

Run: `pytest tests/gui/test_app.py -v` puis `pytest -q`
Expected: nouveau PASS ; suite verte (166+ selon l'état).
Smoke HTML : `python -c "import html.parser; html.parser.HTMLParser().feed(open(r'tapageur/gui/web/index.html',encoding='utf-8').read()); print('ok')"`.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/app.py tapageur/gui/web/index.html tests/gui/test_app.py
git commit -m "feat(gui): case « Ajouter au fichier existant » (append xlsx)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Validation de bout en bout (manuelle)

Faire une 1re passe (append décoché) → `tapage_2026-11.xlsx` créé. Corriger une
ligne dans Excel, enregistrer. Faire une 2e passe avec **« Ajouter au fichier
existant » coché** → les nouvelles lignes s'ajoutent à la fin, la ligne corrigée
reste intacte, les feuilles de référence aussi.

## Hors périmètre
- Append csv/json.
- Dédup inter-passes.
