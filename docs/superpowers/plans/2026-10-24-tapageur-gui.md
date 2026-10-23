# tapageur-gui Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une app de bureau (pywebview) qui extrait les événements de fichiers déposés et d'URLs, et écrit le fichier de tapage (xlsx/csv/json), en réutilisant le cœur `tapageur`.

**Architecture:** Sous-paquet `tapageur/gui/` : une coquille pywebview (fenêtre native + UI HTML/JS) appelle un service Python qui construit des `CollectedItem` (fichiers via `connectors.docs`, URLs via `WebConnector`), lance le pipeline existant (`normalize_items` → `canonicalize` → `dedup` → `group_events` → `convert_to_onliner`), puis exporte. Aucune règle métier dupliquée.

**Tech Stack:** Python 3.11+, pywebview, openpyxl, le paquet `tapageur` existant (anthropic, pydantic, click, requests, bs4, playwright, pdfplumber), pytest.

## Global Constraints

- Python `>=3.11` (déjà imposé par `pyproject.toml`).
- Réutiliser le cœur `tapageur` **comme bibliothèque** — ne jamais réimplémenter extraction / canonicalisation / dédup / export CSV.
- Aucune clé API en dur. `ANTHROPIC_API_KEY` vient des réglages locaux de l'utilisateur, injectée dans `os.environ` au lancement d'un run.
- Nouveau code sous `tapageur/gui/`. Dépendances GUI dans un extra optionnel `[gui]`.
- Colonne A « INFO TAPEUR » = `tapeur_email`, défaut `lebidul@live.fr`.
- Délimiteur CSV = `;` (via `validate.export_csv` existant).
- Commits fréquents, un par tâche au minimum. Messages en français, terminés par `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

| Fichier | Responsabilité | Neuf / Modifié |
|---------|----------------|----------------|
| `pyproject.toml` | Extra `[gui]` (pywebview, openpyxl) + entry-point `tapageur-gui`. | Modifié |
| `tapageur/gui/__init__.py` | Marqueur de paquet. | Créé |
| `tapageur/gui/settings.py` | Réglages locaux (clé API, email tapeur) dans `%APPDATA%/tapageur/settings.json`. | Créé |
| `tapageur/gui/inputs.py` | `CollectedItem` depuis fichiers (via `docs._route_file`) et URLs (via `WebConnector`). | Créé |
| `tapageur/gui/export_xlsx.py` | Remplit une copie du template xlsx (feuille `lebiduleur`), conserve les feuilles de référence. | Créé |
| `tapageur/gui/service.py` | Orchestration : build items → pipeline → alertes → export. | Créé |
| `tapageur/gui/app.py` | Fenêtre pywebview + API bridge JS↔Python. | Créé |
| `tapageur/gui/web/index.html` | Écran unique (drop, URLs, mois, formats, Lancer, résumé). | Créé |
| `tapageur/gui/assets/template.xlsx` | Template de sortie épuré (données vidées, feuilles de référence conservées). | Créé |
| `tapageur/normalize.py` | Ajout du paramètre `month_filter: bool = True`. | Modifié |
| `tests/gui/test_settings.py` | Tests settings. | Créé |
| `tests/gui/test_inputs.py` | Tests inputs (fichiers + URLs mockées). | Créé |
| `tests/gui/test_export_xlsx.py` | Tests export xlsx. | Créé |
| `tests/gui/test_service.py` | Tests orchestration (normalize mocké). | Créé |
| `tests/test_normalize.py` | Test additionnel `month_filter=False`. | Modifié |

---

## Task 1: Squelette du paquet + dépendances

**Files:**
- Modify: `pyproject.toml`
- Create: `tapageur/gui/__init__.py`
- Create: `tests/gui/__init__.py`

**Interfaces:**
- Consumes: rien.
- Produces: le paquet importable `tapageur.gui` ; l'extra `pip install -e ".[gui]"` ; l'entry-point console `tapageur-gui`.

- [ ] **Step 1: Ajouter l'extra `[gui]` et l'entry-point dans `pyproject.toml`**

Dans `[project.optional-dependencies]`, ajouter sous le bloc `dev` existant :

```toml
gui = [
    "pywebview>=5.0",
    "openpyxl>=3.1",
]
```

Dans `[project.scripts]`, à côté de `tapageur = "tapageur.cli:main"`, ajouter :

```toml
tapageur-gui = "tapageur.gui.app:main"
```

- [ ] **Step 2: Créer les marqueurs de paquet**

Créer `tapageur/gui/__init__.py` :

```python
"""Utilitaire de bureau tapageur (pywebview)."""
```

Créer `tests/gui/__init__.py` (fichier vide).

- [ ] **Step 3: Installer l'extra et vérifier l'import**

Run: `pip install -e ".[gui]" && python -c "import tapageur.gui, webview, openpyxl; print('ok')"`
Expected: affiche `ok` sans erreur d'import.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml tapageur/gui/__init__.py tests/gui/__init__.py
git commit -m "feat(gui): squelette paquet tapageur.gui + extra [gui]

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Réglages locaux (`settings.py`)

**Files:**
- Create: `tapageur/gui/settings.py`
- Test: `tests/gui/test_settings.py`

**Interfaces:**
- Consumes: rien.
- Produces :
  - `DEFAULT_TAPEUR_EMAIL: str = "lebidul@live.fr"`
  - `settings_path() -> pathlib.Path`
  - `load_settings() -> dict` (clés : `anthropic_api_key: str`, `tapeur_email: str` ; valeurs par défaut si fichier absent)
  - `save_settings(data: dict) -> None`

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/gui/test_settings.py` :

```python
import json
from tapageur.gui import settings


def test_load_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings_path", lambda: tmp_path / "settings.json")
    data = settings.load_settings()
    assert data["tapeur_email"] == settings.DEFAULT_TAPEUR_EMAIL
    assert data["anthropic_api_key"] == ""


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "settings_path", lambda: p)
    settings.save_settings({"anthropic_api_key": "sk-test", "tapeur_email": "a@b.fr"})
    assert p.exists()
    data = settings.load_settings()
    assert data["anthropic_api_key"] == "sk-test"
    assert data["tapeur_email"] == "a@b.fr"


def test_load_fills_missing_keys(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"anthropic_api_key": "sk-x"}), encoding="utf-8")
    monkeypatch.setattr(settings, "settings_path", lambda: p)
    data = settings.load_settings()
    assert data["anthropic_api_key"] == "sk-x"
    assert data["tapeur_email"] == settings.DEFAULT_TAPEUR_EMAIL
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/gui/test_settings.py -v`
Expected: FAIL (`ModuleNotFoundError: tapageur.gui.settings` ou `AttributeError`).

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `tapageur/gui/settings.py` :

```python
"""Réglages locaux persistants (clé API, email tapeur)."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_TAPEUR_EMAIL = "lebidul@live.fr"
_DEFAULTS = {"anthropic_api_key": "", "tapeur_email": DEFAULT_TAPEUR_EMAIL}


def settings_path() -> Path:
    """Chemin du fichier de réglages, par OS."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / "tapageur"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tapageur"
    return base / "settings.json"


def load_settings() -> dict:
    """Charge les réglages ; complète les clés manquantes par les défauts."""
    p = settings_path()
    data = dict(_DEFAULTS)
    if p.exists():
        try:
            data.update(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return data


def save_settings(data: dict) -> None:
    """Écrit les réglages (crée le dossier au besoin)."""
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    merged = {**_DEFAULTS, **data}
    p.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
```

- [ ] **Step 4: Lancer le test pour vérifier le succès**

Run: `pytest tests/gui/test_settings.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/settings.py tests/gui/test_settings.py
git commit -m "feat(gui): settings locaux (clé API + email tapeur)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Entrées fichiers (`inputs.items_from_files`)

**Files:**
- Create: `tapageur/gui/inputs.py`
- Test: `tests/gui/test_inputs.py`

**Interfaces:**
- Consumes: `tapageur.connectors.docs._route_file(path: Path) -> CollectedItem | None`.
- Produces: `items_from_files(paths: list[Path]) -> list[CollectedItem]` (ignore silencieusement les extensions non supportées et les PDF sans texte, pour lesquels `_route_file` renvoie `None`).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/gui/test_inputs.py` :

```python
from pathlib import Path
from tapageur.gui import inputs


def test_items_from_files_routes_image(tmp_path):
    # 1x1 px PNG minimal
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f1e0000000049454e44ae426082"
    )
    f = tmp_path / "flyer.png"
    f.write_bytes(png)
    items = inputs.items_from_files([f])
    assert len(items) == 1
    assert items[0].source_kind == "image"
    assert items[0].source_ref == str(f)


def test_items_from_files_skips_unsupported(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("rien", encoding="utf-8")
    assert inputs.items_from_files([txt]) == []
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/gui/test_inputs.py -v`
Expected: FAIL (`ModuleNotFoundError: tapageur.gui.inputs`).

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `tapageur/gui/inputs.py` :

```python
"""Construit des CollectedItem depuis fichiers déposés et URLs collées."""
from __future__ import annotations

from pathlib import Path

from tapageur.connectors.docs import _route_file
from tapageur.schema import CollectedItem


def items_from_files(paths: list[Path]) -> list[CollectedItem]:
    """Route chaque fichier via le connecteur docs. Ignore les types non
    gérés et les PDF sans texte (``_route_file`` renvoie ``None``)."""
    items: list[CollectedItem] = []
    for p in paths:
        item = _route_file(Path(p))
        if item is not None:
            items.append(item)
    return items
```

- [ ] **Step 4: Lancer le test pour vérifier le succès**

Run: `pytest tests/gui/test_inputs.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/inputs.py tests/gui/test_inputs.py
git commit -m "feat(gui): items_from_files (réutilise docs._route_file)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Entrées URLs (`inputs.items_from_urls`)

**Files:**
- Modify: `tapageur/gui/inputs.py`
- Test: `tests/gui/test_inputs.py`

**Interfaces:**
- Consumes: `tapageur.connectors.web.WebConnector(config: dict).collect(month: str) -> Iterator[CollectedItem]`. Clés `websites[]` lues par WebConnector : `url`, `name`, `needs_browser`, `follow_event_links`, `mode`, `prefilter_by_month`.
- Produces :
  - `@dataclass UrlInput(url: str, follow_links: bool = False, is_festival: bool = False)`
  - `items_from_urls(url_inputs: list[UrlInput], month: str) -> list[CollectedItem]`

Chaque `UrlInput` devient une entrée `websites:` synthétique passée à `WebConnector` : `needs_browser=True` (navigateur embarqué v1, toutes URLs lisibles), `follow_event_links=follow_links`, `mode="festival_onliner"` si `is_festival`, `prefilter_by_month=False` (le filtrage mois se fait en aval dans `normalize`).

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/gui/test_inputs.py` :

```python
from datetime import datetime
from tapageur.schema import CollectedItem


def test_url_input_builds_synthetic_config(monkeypatch):
    captured = {}

    class FakeWeb:
        def __init__(self, config):
            captured["config"] = config

        def collect(self, month):
            captured["month"] = month
            yield CollectedItem(
                source_kind="web",
                source_ref="https://ex.fr/a",
                fetched_at=datetime.utcnow().isoformat() + "Z",
                raw_text="texte",
                raw_metadata={},
            )

    monkeypatch.setattr(inputs, "WebConnector", FakeWeb)
    out = inputs.items_from_urls(
        [inputs.UrlInput(url="https://ex.fr/a", follow_links=True, is_festival=True)],
        month="2026-10",
    )
    assert len(out) == 1
    site = captured["config"]["websites"][0]
    assert site["url"] == "https://ex.fr/a"
    assert site["needs_browser"] is True
    assert site["follow_event_links"] is True
    assert site["mode"] == "festival_onliner"
    assert site["prefilter_by_month"] is False
    assert captured["month"] == "2026-10"


def test_url_input_defaults_no_festival(monkeypatch):
    captured = {}

    class FakeWeb:
        def __init__(self, config):
            captured["config"] = config

        def collect(self, month):
            return iter(())

    monkeypatch.setattr(inputs, "WebConnector", FakeWeb)
    inputs.items_from_urls([inputs.UrlInput(url="https://ex.fr/b")], month="2026-10")
    site = captured["config"]["websites"][0]
    assert site["follow_event_links"] is False
    assert "mode" not in site
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/gui/test_inputs.py::test_url_input_builds_synthetic_config -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'UrlInput'`).

- [ ] **Step 3: Écrire l'implémentation minimale**

Modifier `tapageur/gui/inputs.py` — ajouter en tête des imports :

```python
from dataclasses import dataclass

from tapageur.connectors.web import WebConnector
```

Et ajouter à la fin du fichier :

```python
@dataclass
class UrlInput:
    """Une URL collée dans l'UI + ses options par-entrée."""
    url: str
    follow_links: bool = False
    is_festival: bool = False


def _url_to_site(u: UrlInput) -> dict:
    """Transforme un UrlInput en entrée `websites:` pour WebConnector."""
    site: dict = {
        "url": u.url,
        "name": u.url,
        "needs_browser": True,          # navigateur embarqué v1 : toute URL lisible
        "follow_event_links": u.follow_links,
        "prefilter_by_month": False,    # filtrage mois fait en aval par normalize
    }
    if u.is_festival:
        site["mode"] = "festival_onliner"
    return site


def items_from_urls(url_inputs: list[UrlInput], month: str) -> list[CollectedItem]:
    """Collecte chaque URL via WebConnector (navigateur, suivi de liens, mode
    festival selon les options de chaque UrlInput)."""
    config = {"websites": [_url_to_site(u) for u in url_inputs]}
    conn = WebConnector(config)
    return list(conn.collect(month))
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run: `pytest tests/gui/test_inputs.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/inputs.py tests/gui/test_inputs.py
git commit -m "feat(gui): items_from_urls (config synthétique → WebConnector)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Option « ne pas filtrer par mois » dans le cœur `normalize`

**Files:**
- Modify: `tapageur/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: `normalize_items(items, month, out_path, model=None, month_filter=True)` et `_normalize_one(client, item, month, model, tapeur_email, month_filter=True)`. Quand `month_filter=False` : le filtre Python `date_iso.startswith(month)` est sauté, et l'indice « Mois cible » envoyé à Claude devient « tous les mois (ne pas filtrer par date) ».

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_normalize.py` :

```python
from unittest.mock import MagicMock
from pathlib import Path
import json as _json
from tapageur import normalize as _norm
from tapageur.schema import CollectedItem


def _fake_client_returning(events_json):
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = _json.dumps({"events": events_json})
    resp = MagicMock()
    resp.content = [block]
    client.messages.create.return_value = resp
    return client


def test_month_filter_false_keeps_other_months(monkeypatch, tmp_path):
    item = CollectedItem(
        source_kind="web", source_ref="https://x.fr", fetched_at="2026-01-01T00:00:00Z",
        raw_text="x", raw_metadata={},
    )
    ev = {
        "date_label": "Mardi 3", "date_iso": "2026-11-03", "times": ["20h00"],
        "venue": "V", "city": "C", "price": "?",
        "acts": [{"genre": "c", "title": None, "performer": "A", "style": None}],
    }
    client = _fake_client_returning([ev])
    out = _norm._normalize_one(client, item, "2026-10", None, "t@b.fr", month_filter=False)
    assert len(out) == 1  # event de novembre gardé malgré month=2026-10
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/test_normalize.py::test_month_filter_false_keeps_other_months -v`
Expected: FAIL (`TypeError: _normalize_one() got an unexpected keyword argument 'month_filter'`).

- [ ] **Step 3: Écrire l'implémentation minimale**

Dans `tapageur/normalize.py`, modifier `_build_user_content` pour accepter un libellé de mois :

```python
def _build_user_content(item: CollectedItem, month_hint: str) -> list[dict]:
```

et remplacer la ligne `f"Mois cible : {month}",` par `f"Mois cible : {month_hint}",`.

Modifier la signature de `_normalize_one` :

```python
def _normalize_one(
    client: Anthropic,
    item: CollectedItem,
    month: str,
    model: str | None,
    tapeur_email: str,
    month_filter: bool = True,
) -> list[Event]:
```

Dans `_normalize_one`, calculer le libellé et le passer :

```python
    month_hint = month if month_filter else "tous les mois (ne pas filtrer par date)"
    kwargs: dict = {
        "model": model,
        "max_tokens": 16000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": _build_user_content(item, month_hint)}],
    }
```

Remplacer le filtre :

```python
        if month_filter and not draft.date_iso.startswith(month):
            continue
```

Modifier `normalize_items` pour propager le flag :

```python
def normalize_items(
    items: list[CollectedItem],
    month: str,
    out_path: Path,
    model: str | None = None,
    month_filter: bool = True,
) -> list[Event]:
```

et dans sa boucle, l'appel devient :

```python
            events = _normalize_one(client, item, month, model, tapeur_email, month_filter)
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run: `pytest tests/test_normalize.py -v`
Expected: PASS (tous, y compris le nouveau et les anciens — `month_filter` défaut `True` conserve le comportement).

- [ ] **Step 5: Commit**

```bash
git add tapageur/normalize.py tests/test_normalize.py
git commit -m "feat(normalize): option month_filter pour désactiver le filtre mois

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Export xlsx depuis le template (`export_xlsx.py`)

**Files:**
- Create: `tapageur/gui/assets/template.xlsx`
- Create: `tapageur/gui/export_xlsx.py`
- Test: `tests/gui/test_export_xlsx.py`

**Interfaces:**
- Consumes: `tapageur.validate.event_to_row(ev: Event, n_acts: int | None) -> list[str]` ; `tapageur.schema.Event`.
- Produces :
  - `TEMPLATE_PATH: pathlib.Path` (vers `assets/template.xlsx`)
  - `DATA_SHEET = "lebiduleur"`
  - `export_xlsx(events: list[Event], out_path: Path, template_path: Path = TEMPLATE_PATH) -> None`

Comportement : copie le template, écrit les events dans la feuille `lebiduleur` à partir de la ligne 2 (la ligne 1 d'en-têtes du template est conservée), nombre de blocs ACT dynamique = `max(len(ev.acts))`. Si > 4 blocs, ajoute les en-têtes « GENRE N / NOM SPECTACLE N / ARTISTE N / STYLE N » pour les blocs au-delà de 4. Les feuilles `communes` / `salles_lieux` / `date` sont laissées intactes.

- [ ] **Step 1: Générer le template épuré committé**

Le fichier source est la spreadsheet fournie par l'utilisateur. Produire une version vidée de ses données (en garder l'en-tête + les feuilles de référence), puis l'enregistrer dans le paquet. Lancer une fois :

```bash
mkdir -p tapageur/gui/assets
python -I - <<'PY'
import openpyxl
from pathlib import Path
src = Path.home() / "tibo/bidul/miseEnPage/2610/202610_tapage_biduleur_Octobre_2026.v0.xlsx"
wb = openpyxl.load_workbook(src)
ws = wb["lebiduleur"]
# Supprimer toutes les lignes de données (garder la ligne 1 d'en-têtes)
if ws.max_row > 1:
    ws.delete_rows(2, ws.max_row - 1)
wb.save("tapageur/gui/assets/template.xlsx")
print("template épuré écrit")
PY
```

Expected: affiche `template épuré écrit` et crée `tapageur/gui/assets/template.xlsx`.
Vérifier : `python -I -c "import openpyxl; wb=openpyxl.load_workbook('tapageur/gui/assets/template.xlsx'); print(wb.sheetnames, wb['lebiduleur'].max_row)"` → doit lister les 4 feuilles et `max_row` = 1.

- [ ] **Step 2: Écrire le test qui échoue**

Créer `tests/gui/test_export_xlsx.py` :

```python
import openpyxl
from tapageur.gui import export_xlsx
from tapageur.schema import Event, Act


def _event(perf="Groupe A", n_acts=1, festival=False):
    acts = [Act(genre="c", title=None, performer=f"{perf}{i}", style=None) for i in range(n_acts)]
    return Event(
        tapeur_email="t@b.fr", festival=("Fest" if festival else None),
        date_label="Vendredi 2", date_iso="2026-10-02", times=["20h00"],
        venue="Le Lieu", city="Le Mans", price="10€",
        is_festival=festival, acts=acts, source_kind="web", source_ref="https://x.fr",
    )


def test_export_writes_data_and_keeps_reference_sheets(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event()], out)
    wb = openpyxl.load_workbook(out)
    assert set(["lebiduleur", "communes", "salles_lieux", "date"]).issubset(set(wb.sheetnames))
    ws = wb["lebiduleur"]
    # ligne 1 = en-têtes conservés ; ligne 2 = 1er event
    assert ws.cell(row=2, column=1).value == "t@b.fr"        # col A INFO TAPEUR
    assert ws.cell(row=2, column=8).value == "Le Lieu"        # col H LIEU
    assert ws.cell(row=2, column=9).value == "Le Mans"        # col I VILLE


def test_export_dynamic_act_blocks(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event(n_acts=5)], out)
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    # 10 colonnes fixes + 5 blocs * 4 = 30 colonnes ; en-tête bloc 5 ajouté
    assert ws.cell(row=1, column=11 + 4 * 4).value == "GENRE 5"
    assert ws.cell(row=2, column=11 + 4 * 4).value == "c"     # genre du 5e act
```

- [ ] **Step 3: Lancer le test pour vérifier l'échec**

Run: `pytest tests/gui/test_export_xlsx.py -v`
Expected: FAIL (`ModuleNotFoundError: tapageur.gui.export_xlsx`).

- [ ] **Step 4: Écrire l'implémentation minimale**

Créer `tapageur/gui/export_xlsx.py` :

```python
"""Export xlsx : remplit une copie du template (feuille `lebiduleur`)."""
from __future__ import annotations

from pathlib import Path

import openpyxl

from tapageur.schema import Event
from tapageur.validate import event_to_row

TEMPLATE_PATH = Path(__file__).parent / "assets" / "template.xlsx"
DATA_SHEET = "lebiduleur"
_N_FIXED_COLS = 10  # colonnes A-J


def export_xlsx(events: list[Event], out_path: Path, template_path: Path = TEMPLATE_PATH) -> None:
    """Copie le template et écrit les events dans la feuille `lebiduleur`.

    Blocs ACT dynamiques = max(len(acts)). Les en-têtes des blocs au-delà de 4
    (ceux présents dans le template) sont ajoutés. Les feuilles de référence
    sont laissées intactes."""
    wb = openpyxl.load_workbook(template_path)
    ws = wb[DATA_SHEET]

    # Purge d'éventuelles lignes de données résiduelles (garde la ligne 1).
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)

    n_acts = max((len(ev.acts) for ev in events), default=1)

    # En-têtes des blocs ACT supplémentaires (au-delà des 4 du template).
    for i in range(5, n_acts + 1):
        base = _N_FIXED_COLS + (i - 1) * 4
        ws.cell(row=1, column=base + 1, value=f"GENRE {i}")
        ws.cell(row=1, column=base + 2, value=f"NOM SPECTACLE {i}")
        ws.cell(row=1, column=base + 3, value=f"ARTISTE {i}")
        ws.cell(row=1, column=base + 4, value=f"STYLE {i}")

    for r, ev in enumerate(events, start=2):
        for c, value in enumerate(event_to_row(ev, n_acts=n_acts), start=1):
            ws.cell(row=r, column=c, value=value)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
```

- [ ] **Step 5: Lancer les tests pour vérifier le succès**

Run: `pytest tests/gui/test_export_xlsx.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add tapageur/gui/assets/template.xlsx tapageur/gui/export_xlsx.py tests/gui/test_export_xlsx.py
git commit -m "feat(gui): export xlsx depuis le template (feuilles de référence conservées)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Orchestration + alertes (`service.py`)

**Files:**
- Create: `tapageur/gui/service.py`
- Test: `tests/gui/test_service.py`

**Interfaces:**
- Consumes :
  - `inputs.items_from_files`, `inputs.items_from_urls`, `inputs.UrlInput`
  - `tapageur.normalize.normalize_items(items, month, out_path, model=None, month_filter=True)`
  - `tapageur.dedup.load_mappings()`, `canonicalize(events, mappings)`, `dedup(events)`, `group_events(events)`, `convert_to_onliner(events, target_festival_names)`
  - `export_xlsx.export_xlsx`, `tapageur.validate.export_csv`
- Produces :
  - `@dataclass RunRequest(file_paths, url_inputs, months, no_month_filter, formats, out_dir, tapeur_email)`
  - `@dataclass MonthResult(month: str | None, n_events: int, files: list[Path], alerts: list[str])`
  - `build_alerts(events, ref_cities: set[str], ref_venues: set[str]) -> list[str]`
  - `run(req: RunRequest) -> list[MonthResult]`

Déroulé de `run` :
1. Injecte `req.tapeur_email` dans `os.environ["TAPEUR_EMAIL"]` (lu par `normalize_items`).
2. Construit les items une fois : `items_from_files(req.file_paths)` + `items_from_urls(req.url_inputs, month)` (pour les URLs, utiliser le 1er mois ciblé, ou `""` si `no_month_filter`).
3. Détermine les passes : si `no_month_filter` → une passe `month=""`, `month_filter=False`, sortie étiquetée `"tous"` ; sinon une passe par mois de `req.months`, `month_filter=True`.
4. Par passe : `normalize_items` (vers un `out_path` temporaire sous `cache/`) → `canonicalize` → `dedup` → `group_events` → `convert_to_onliner(events, onliner_names)` où `onliner_names` = noms de festivals présents (events `is_festival`).
5. `build_alerts` + export de chaque format demandé → fichiers nommés `tapage_<label>.<ext>`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/gui/test_service.py` :

```python
from pathlib import Path
from tapageur.gui import service
from tapageur.schema import Event, Act


def _event(price="10€", perf="A", city="Le Mans", venue="Le Lieu"):
    return Event(
        tapeur_email="t@b.fr", date_label="Vendredi 2", date_iso="2026-10-02",
        times=["20h00"], venue=venue, city=city, price=price,
        acts=[Act(genre="c", title=None, performer=perf, style=None)],
        source_kind="web", source_ref="https://x.fr",
    )


def test_build_alerts_flags_missing_and_unknown():
    evs = [_event(price="?", perf="?", city="Ailleurs", venue="Inconnu")]
    alerts = service.build_alerts(evs, ref_cities={"Le Mans"}, ref_venues={"Le Lieu"})
    joined = " ".join(alerts)
    assert "prix" in joined.lower()
    assert "performer" in joined.lower() or "artiste" in joined.lower()
    assert "Ailleurs" in joined
    assert "Inconnu" in joined


def test_run_exports_requested_formats(tmp_path, monkeypatch):
    # normalize_items mocké : renvoie 1 event, ignore l'appel Claude
    monkeypatch.setattr(service, "normalize_items",
                        lambda items, month, out_path, model=None, month_filter=True: [_event()])
    monkeypatch.setattr(service, "load_mappings", lambda: {})
    monkeypatch.setattr(service, "canonicalize", lambda evs, m: evs)
    monkeypatch.setattr(service, "dedup", lambda evs: evs)
    monkeypatch.setattr(service, "group_events", lambda evs: evs)
    monkeypatch.setattr(service, "convert_to_onliner", lambda evs, names: evs)

    req = service.RunRequest(
        file_paths=[], url_inputs=[], months=["2026-10"], no_month_filter=False,
        formats=["json", "csv", "xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
    )
    results = service.run(req)
    assert len(results) == 1
    r = results[0]
    assert r.month == "2026-10"
    assert r.n_events == 1
    exts = {p.suffix for p in r.files}
    assert exts == {".json", ".csv", ".xlsx"}
    for p in r.files:
        assert p.exists()
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/gui/test_service.py -v`
Expected: FAIL (`ModuleNotFoundError: tapageur.gui.service`).

- [ ] **Step 3: Écrire l'implémentation minimale**

Créer `tapageur/gui/service.py` :

```python
"""Orchestration GUI : build items → pipeline → alertes → export."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from tapageur.dedup import (canonicalize, convert_to_onliner, dedup,
                            group_events, load_mappings)
from tapageur.gui import export_xlsx as _xlsx
from tapageur.gui.inputs import UrlInput, items_from_files, items_from_urls
from tapageur.normalize import normalize_items
from tapageur.schema import Event
from tapageur.validate import export_csv


@dataclass
class RunRequest:
    file_paths: list[Path]
    url_inputs: list[UrlInput]
    months: list[str]
    no_month_filter: bool
    formats: list[str]            # sous-ensemble de {"xlsx", "csv", "json"}
    out_dir: Path
    tapeur_email: str


@dataclass
class MonthResult:
    month: str | None
    n_events: int
    files: list[Path] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)


def build_alerts(events: list[Event], ref_cities: set[str], ref_venues: set[str]) -> list[str]:
    """Signale prix/performer manquants et lieux/villes hors listes de référence."""
    alerts: list[str] = []
    for ev in events:
        if ev.price == "?":
            alerts.append(f"Prix manquant : {ev.date_label} — {ev.acts[0].performer}")
        for act in ev.acts:
            if act.performer == "?":
                alerts.append(f"Artiste/performer inconnu : {ev.date_label} @ {ev.venue}")
        if ref_cities and ev.city and ev.city not in ref_cities:
            alerts.append(f"Ville hors liste de référence : {ev.city}")
        if ref_venues and ev.venue and ev.venue not in ref_venues:
            alerts.append(f"Lieu hors liste de référence : {ev.venue}")
    return alerts


def _reference_lists() -> tuple[set[str], set[str]]:
    """Lit communes / salles_lieux depuis le template embarqué."""
    import openpyxl
    wb = openpyxl.load_workbook(_xlsx.TEMPLATE_PATH, read_only=True)
    cities = {r[0] for r in wb["communes"].iter_rows(values_only=True) if r and r[0]}
    venues = {r[0] for r in wb["salles_lieux"].iter_rows(values_only=True) if r and r[0]}
    return cities, venues


def _pipeline(items, month: str, month_filter: bool, cache_out: Path) -> list[Event]:
    events = normalize_items(items, month, cache_out, model=None, month_filter=month_filter)
    events = canonicalize(events, load_mappings())
    events = dedup(events)
    events = group_events(events)
    onliner_names = [ev.festival for ev in events if ev.is_festival and ev.festival]
    events = convert_to_onliner(events, onliner_names)
    return events


def _export(events: list[Event], out_dir: Path, label: str, formats: list[str]) -> list[Path]:
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
        _xlsx.export_xlsx(events, p)
        written.append(p)
    return written


def run(req: RunRequest) -> list[MonthResult]:
    os.environ["TAPEUR_EMAIL"] = req.tapeur_email
    ref_cities, ref_venues = _reference_lists()

    if req.no_month_filter:
        passes = [("", "tous", False)]
    else:
        passes = [(m, m, True) for m in req.months]

    results: list[MonthResult] = []
    for month, label, month_filter in passes:
        items = list(items_from_files(req.file_paths))
        items += list(items_from_urls(req.url_inputs, month))
        cache_out = Path("cache") / (label or "tous") / "gui_normalized.json"
        events = _pipeline(items, month, month_filter, cache_out)
        files = _export(events, req.out_dir, label, req.formats)
        alerts = build_alerts(events, ref_cities, ref_venues)
        results.append(MonthResult(
            month=(month or None), n_events=len(events), files=files, alerts=alerts,
        ))
    return results
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run: `pytest tests/gui/test_service.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Lancer toute la suite**

Run: `pytest -q`
Expected: tous les tests passent (nouveaux + existants).

- [ ] **Step 6: Commit**

```bash
git add tapageur/gui/service.py tests/gui/test_service.py
git commit -m "feat(gui): orchestration run() + alertes qualité

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Fenêtre pywebview + UI (`app.py`, `web/index.html`)

**Files:**
- Create: `tapageur/gui/app.py`
- Create: `tapageur/gui/web/index.html`

**Interfaces:**
- Consumes: `settings.load_settings/save_settings`, `service.run`, `service.RunRequest`, `inputs.UrlInput`.
- Produces: `main()` — point d'entrée console `tapageur-gui`. Classe `Api` exposée au JS via pywebview (`get_settings`, `save_settings`, `run_extraction`, `choose_output_dir`, `choose_files`).

> **Note chemins de fichiers :** dans pywebview (comme dans un navigateur) un objet JS `File` issu d'un drop n'expose pas son chemin disque de façon fiable. La sélection passe donc par le dialogue natif `create_file_dialog` (vrais chemins). Le drag-drop est conservé en best-effort (si le backend expose `.path`).

> Pas de test automatisé (UI) en v1 — validation manuelle (Step 3).

- [ ] **Step 1: Écrire l'API bridge + le lanceur**

Créer `tapageur/gui/app.py` :

```python
"""Fenêtre pywebview + API bridge pour tapageur-gui."""
from __future__ import annotations

from pathlib import Path

import webview

from tapageur.gui import settings as _settings
from tapageur.gui.inputs import UrlInput
from tapageur.gui.service import RunRequest, run

_WEB = Path(__file__).parent / "web" / "index.html"


class Api:
    """Méthodes appelées depuis le JS (window.pywebview.api.*)."""

    def get_settings(self) -> dict:
        return _settings.load_settings()

    def save_settings(self, data: dict) -> dict:
        _settings.save_settings(data)
        return {"ok": True}

    def choose_output_dir(self) -> str:
        res = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return res[0] if res else ""

    def choose_files(self) -> list[str]:
        res = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True,
            file_types=("Sources (*.pdf;*.jpg;*.jpeg;*.png;*.webp;*.gif)", "Tous (*.*)"),
        )
        return list(res) if res else []

    def run_extraction(self, payload: dict) -> dict:
        """payload : {file_paths, urls:[{url,follow_links,is_festival}],
        months:[...], no_month_filter, formats:[...], out_dir}."""
        cfg = _settings.load_settings()
        if not cfg.get("anthropic_api_key"):
            return {"error": "Clé API Anthropic absente. Renseigne-la dans les réglages."}
        import os
        os.environ["ANTHROPIC_API_KEY"] = cfg["anthropic_api_key"]

        req = RunRequest(
            file_paths=[Path(p) for p in payload.get("file_paths", [])],
            url_inputs=[UrlInput(**u) for u in payload.get("urls", [])],
            months=payload.get("months", []),
            no_month_filter=payload.get("no_month_filter", False),
            formats=payload.get("formats", []),
            out_dir=Path(payload.get("out_dir") or "."),
            tapeur_email=cfg.get("tapeur_email", _settings.DEFAULT_TAPEUR_EMAIL),
        )
        try:
            results = run(req)
        except Exception as e:  # remonte l'erreur à l'UI au lieu de crasher
            return {"error": str(e)}
        return {"results": [
            {"month": r.month, "n_events": r.n_events,
             "files": [str(p) for p in r.files], "alerts": r.alerts}
            for r in results
        ]}


def main() -> None:
    webview.create_window("tapageur", str(_WEB), js_api=Api(), width=900, height=720)
    webview.start()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Écrire l'écran unique**

Créer `tapageur/gui/web/index.html` (zone de drop, liste d'URLs avec cases, mois, formats, dossier, bouton Lancer, zone de résumé, panneau réglages). Contenu complet :

```html
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<style>
  body { font-family: system-ui, sans-serif; margin: 0; padding: 16px; }
  h1 { font-size: 18px; }
  fieldset { margin-bottom: 12px; }
  #drop { border: 2px dashed #888; border-radius: 8px; padding: 24px; text-align: center; color: #666; }
  #drop.over { border-color: #2b7; color: #2b7; }
  .url-row { display: flex; gap: 8px; align-items: center; margin: 4px 0; }
  .url-row input[type=text] { flex: 1; }
  #summary { white-space: pre-wrap; background: #f6f6f6; padding: 12px; border-radius: 6px; }
  .alert { color: #a40; }
  button { padding: 6px 14px; }
</style>
</head>
<body>
  <h1>tapageur</h1>

  <fieldset>
    <legend>Fichiers (PDF, JPG, PNG)</legend>
    <div id="drop">Dépose des fichiers ici (ou clique pour choisir)</div>
    <ul id="file-list"></ul>
  </fieldset>

  <fieldset>
    <legend>URLs</legend>
    <div id="urls"></div>
    <button id="add-url">+ Ajouter une URL</button>
  </fieldset>

  <fieldset>
    <legend>Mois</legend>
    <input id="months" type="text" placeholder="2026-10, 2026-11" size="30">
    <label><input id="no-filter" type="checkbox"> ne pas filtrer par mois</label>
  </fieldset>

  <fieldset>
    <legend>Sortie</legend>
    <label><input type="checkbox" class="fmt" value="xlsx" checked> xlsx</label>
    <label><input type="checkbox" class="fmt" value="csv"> csv</label>
    <label><input type="checkbox" class="fmt" value="json"> json</label>
    <div style="margin-top:8px">
      <button id="choose-dir">Dossier de sortie…</button>
      <span id="out-dir">(aucun)</span>
    </div>
  </fieldset>

  <fieldset>
    <legend>Réglages</legend>
    <div><label>Clé API Anthropic <input id="api-key" type="password" size="40"></label></div>
    <div><label>Email tapeur <input id="email" type="text" size="30"></label></div>
    <button id="save-settings">Enregistrer les réglages</button>
  </fieldset>

  <button id="run">Lancer</button>
  <h2>Résumé</h2>
  <div id="summary">—</div>

<script>
const api = () => window.pywebview.api;
let files = [];
let outDir = "";

function renderFiles() {
  document.getElementById('file-list').innerHTML =
    files.map(f => `<li>${f}</li>`).join('');
}

// --- drop zone ---
const drop = document.getElementById('drop');
// Sélection fiable : dialogue natif pywebview (renvoie de vrais chemins).
drop.addEventListener('click', async () => {
  const picked = await api().choose_files();
  for (const p of picked) files.push(p);
  renderFiles();
});
// Drag-drop best-effort (si le backend expose .path).
drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', e => {
  e.preventDefault(); drop.classList.remove('over');
  for (const f of e.dataTransfer.files) if (f.path) files.push(f.path);
  renderFiles();
});

// --- urls ---
function addUrlRow() {
  const div = document.createElement('div');
  div.className = 'url-row';
  div.innerHTML = `<input type="text" placeholder="https://…">
    <label><input type="checkbox" class="follow"> suivre les liens</label>
    <label><input type="checkbox" class="fest"> festival</label>`;
  document.getElementById('urls').appendChild(div);
}
document.getElementById('add-url').addEventListener('click', addUrlRow);

function collectUrls() {
  return [...document.querySelectorAll('.url-row')].map(r => ({
    url: r.querySelector('input[type=text]').value.trim(),
    follow_links: r.querySelector('.follow').checked,
    is_festival: r.querySelector('.fest').checked,
  })).filter(u => u.url);
}

// --- settings ---
async function loadSettings() {
  const s = await api().get_settings();
  document.getElementById('api-key').value = s.anthropic_api_key || '';
  document.getElementById('email').value = s.tapeur_email || '';
}
document.getElementById('save-settings').addEventListener('click', async () => {
  await api().save_settings({
    anthropic_api_key: document.getElementById('api-key').value,
    tapeur_email: document.getElementById('email').value,
  });
  alert('Réglages enregistrés.');
});

// --- output dir ---
document.getElementById('choose-dir').addEventListener('click', async () => {
  outDir = await api().choose_output_dir();
  document.getElementById('out-dir').textContent = outDir || '(aucun)';
});

// --- run ---
document.getElementById('run').addEventListener('click', async () => {
  const summary = document.getElementById('summary');
  summary.textContent = 'Extraction en cours…';
  const payload = {
    file_paths: files,
    urls: collectUrls(),
    months: document.getElementById('months').value.split(',').map(s => s.trim()).filter(Boolean),
    no_month_filter: document.getElementById('no-filter').checked,
    formats: [...document.querySelectorAll('.fmt:checked')].map(c => c.value),
    out_dir: outDir,
  };
  const res = await api().run_extraction(payload);
  if (res.error) { summary.innerHTML = `<span class="alert">Erreur : ${res.error}</span>`; return; }
  summary.innerHTML = res.results.map(r => {
    const files = r.files.map(f => `  ${f}`).join('\n');
    const alerts = r.alerts.length
      ? '\n  <span class="alert">⚠ ' + r.alerts.join('</span>\n  <span class="alert">⚠ ') + '</span>'
      : '';
    return `[${r.month || 'tous'}] ${r.n_events} events\n${files}${alerts}`;
  }).join('\n\n');
});

window.addEventListener('pywebviewready', loadSettings);
</script>
</body>
</html>
```

- [ ] **Step 3: Vérification manuelle**

Run: `tapageur-gui` (ou `python -m tapageur.gui.app`).
Vérifier : la fenêtre s'ouvre ; renseigner la clé API dans Réglages + Enregistrer ; déposer un flyer PDF/JPG, saisir le mois ; cocher xlsx ; choisir un dossier ; Lancer ; le résumé affiche le nombre d'events, les fichiers écrits et d'éventuelles alertes ; le fichier xlsx s'ouvre dans Excel avec les feuilles de référence.
Note : au tout premier run avec une URL, Playwright peut devoir installer Chromium (`playwright install chromium`).

- [ ] **Step 4: Commit**

```bash
git add tapageur/gui/app.py tapageur/gui/web/index.html
git commit -m "feat(gui): fenêtre pywebview + écran unique (drop, URLs, mois, formats)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Hors périmètre v1 (rappel)

- Édition des events dans l'app (correction en Excel).
- Push Google Sheets (reste CLI).
- Packaging `.exe` (PyInstaller + GitHub Releases) — étape suivante.
- Backend hébergé / clé partagée.
- **Override de modèle Sonnet/Opus dans l'UI** (spec §5 « avancé ») — différé ; le pipeline garde la sélection auto par type de source.
- **Estimation de coût avant lancement** (spec §6, suggestion) — différée.
