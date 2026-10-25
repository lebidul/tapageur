# Merge / dédoublonnage à l'écriture xlsx — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le choix binaire « append » par 3 modes d'écriture (Créer / Ajouter incrémental / Fusionner), le mode Fusionner complétant un fichier mensuel existant sans écraser les corrections manuelles.

**Architecture:** Le gros du travail est dans `tapageur/gui/export_xlsx.py` (reverse-parse par position, clé de match sur colonnes visibles, fill-gaps in-place, append des non-matchés) orchestré par `tapageur/gui/service.py` (routage selon `write_mode`, skip des sources déjà présentes en incrémental, compte-rendu). L'UI (`index.html`) passe d'une case à un radio 3 modes, et `app.py` relaie `write_mode`.

**Tech Stack:** Python 3.11+, openpyxl, pydantic (Event), pytest. Pas de dépendance nouvelle.

## Global Constraints

- Ne RIEN casser côté CLI : `export_xlsx(events, out_path, append=...)` et `_append_xlsx` gardent leur signature/comportement actuels.
- Écriture xlsx toujours via `_save_workbook` (sauvegarde atomique + message clair si fichier verrouillé).
- Mode Fusionner : écriture **in-place** (on patche les cellules du classeur chargé), jamais de reconstruction depuis le template → la mise en forme existante est préservée.
- Clé de match = (DATE col 8, LIEU col 10, ARTISTE1 col 15), normalisée (NFKD sans accents, trim, lower). HEURE/PRIX **exclus**.
- Politique de conflit = **compléter les trous** : on ne remplit qu'une cellule vide ou « ? » ; **jamais** d'écrasement d'une valeur non vide.
- Colonne SOURCE (et TYPE SOURCE) : la nouvelle source est **accolée** (« existant ; nouveau ») sur une ligne complétée, sans doublon.
- Indices de colonnes = miroir de `validate.event_to_row` (12 colonnes fixes A-L puis blocs de 4 par acte). Ne pas réécrire `event_to_row`.
- Fichier cible absent → les 3 modes se comportent comme « Créer ».
- Textes collés : toujours traités en incrémental (pas d'identifiant stable).
- Messages / labels UI en français.
- Commits : terminer par `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Primitives de clé de match + constantes de colonnes

**Files:**
- Modify: `tapageur/gui/export_xlsx.py` (ajout de constantes + helpers en bas du module)
- Test: `tests/gui/test_export_xlsx_merge.py` (créer)

**Interfaces:**
- Produces :
  - `_COL_TYPE_SOURCE=1, _COL_SOURCE=2, _COL_FESTOCHE=6, _COL_STYLE_FESTOCHE=7, _COL_DATE=8, _COL_HEURE=9, _COL_LIEU=10, _COL_VILLE=11, _COL_PRIX=12, _COL_ARTISTE1=_N_FIXED_COLS+3`
  - `_norm(v) -> str`
  - `_is_blank(v) -> bool` (None / "" / "?" après strip)
  - `_key_from_cells(cells: list) -> tuple[str,str,str]` (DATE, LIEU, ARTISTE1 normalisés)
  - `_event_cells(ev: Event, n_acts: int) -> list` (= `event_to_row(ev, n_acts=n_acts)`)

- [ ] **Step 1: Écrire le test**

```python
# tests/gui/test_export_xlsx_merge.py
from tapageur.gui import export_xlsx as X
from tapageur.schema import Event, Act


def _ev(perf="Groupe X", venue="Le Lézard", date_label="Mardi 3",
        heure="20h00", price="?", festival=None, is_festival=False):
    return Event(
        tapeur_email="t@b.fr", festival=festival, date_label=date_label,
        date_iso="2026-11-03", times=[heure], venue=venue, city="Le Mans",
        price=price, is_festival=is_festival,
        acts=[Act(genre="c", title=None, performer=perf, style=None)],
        source_kind="web", source_ref="https://a.fr/x",
    )


def test_norm_strips_accents_case_space():
    assert X._norm("  Le Lézard ") == X._norm("le lezard")


def test_is_blank():
    assert X._is_blank(None) and X._is_blank("") and X._is_blank("?") and X._is_blank(" ? ")
    assert not X._is_blank("20h00")


def test_key_from_cells_matches_event_cells():
    ev = _ev()
    cells = X._event_cells(ev, n_acts=1)
    # DATE col8, LIEU col10, ARTISTE1 col15
    assert X._key_from_cells(cells) == ("mardi 3", "le lezard", "groupe x")


def test_key_ignores_heure_price():
    a = X._key_from_cells(X._event_cells(_ev(heure="20h00", price="10€"), 1))
    b = X._key_from_cells(X._event_cells(_ev(heure="21h30", price="?"), 1))
    assert a == b
```

- [ ] **Step 2: Lancer le test → échec (symboles absents)**

Run: `python -m pytest tests/gui/test_export_xlsx_merge.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute '_norm'`)

- [ ] **Step 3: Implémenter les primitives**

Ajouter en bas de `tapageur/gui/export_xlsx.py` :

```python
import unicodedata
from tapageur.validate import event_to_row  # déjà importé en tête : ne pas redoubler

_COL_TYPE_SOURCE = 1
_COL_SOURCE = 2
_COL_FESTOCHE = 6
_COL_STYLE_FESTOCHE = 7
_COL_DATE = 8
_COL_HEURE = 9
_COL_LIEU = 10
_COL_VILLE = 11
_COL_PRIX = 12
_COL_ARTISTE1 = _N_FIXED_COLS + 3  # 1er bloc ACT : GENRE=13,NOM=14,ARTISTE=15,STYLE=16


def _norm(v) -> str:
    s = "" if v is None else str(v)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


def _is_blank(v) -> bool:
    return v is None or str(v).strip() in ("", "?")


def _cell(cells: list, col: int):
    return cells[col - 1] if 0 <= col - 1 < len(cells) else ""


def _key_from_cells(cells: list) -> tuple:
    return (_norm(_cell(cells, _COL_DATE)),
            _norm(_cell(cells, _COL_LIEU)),
            _norm(_cell(cells, _COL_ARTISTE1)))


def _event_cells(ev, n_acts: int) -> list:
    return event_to_row(ev, n_acts=n_acts)
```

NB : `event_to_row` est déjà importé en tête du module (`from tapageur.validate import event_to_row`) — ne pas ré-importer, la ligne ci-dessus est indicative.

- [ ] **Step 4: Lancer le test → vert**

Run: `python -m pytest tests/gui/test_export_xlsx_merge.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/export_xlsx.py tests/gui/test_export_xlsx_merge.py
git commit -m "feat(export): primitives clé de match merge (colonnes visibles)"
```

---

### Task 2: Fill-gaps (plan de complétion d'une ligne existante)

**Files:**
- Modify: `tapageur/gui/export_xlsx.py`
- Test: `tests/gui/test_export_xlsx_merge.py`

**Interfaces:**
- Consumes : constantes + `_is_blank`, `_norm` (Task 1)
- Produces :
  - `_COL_LABELS: dict[int,str]` (col → libellé pour le log, blocs ACT inclus jusqu'à N)
  - `_label_for(col: int) -> str`
  - `_plan_fill(existing: list, incoming: list, n_cols: int) -> tuple[dict[int, object], list[str]]`
    retourne `({col: value_à_écrire}, [libellés remplis])` pour les colonnes de contenu
    vides côté existant et renseignées côté entrant. EXCLUT les colonnes clé
    (DATE, LIEU, ARTISTE1) et les colonnes méta (TYPE SOURCE, SOURCE, INFO
    TAPEUR=3, DATE TAPAGE=4, DATE EMISSION=5).
  - `_merge_source_cell(existing_val, incoming_val) -> str | None`
    nouvelle valeur de la cellule SOURCE/TYPE SOURCE (ou None si rien à ajouter).

- [ ] **Step 1: Écrire le test**

```python
def test_plan_fill_fills_blanks_only():
    ev_existing = _ev(heure="20h00", price="?", festival=None)
    ev_incoming = _ev(heure="21h00", price="10€", festival="Soirée Beaujolais")
    existing = X._event_cells(ev_existing, 1)
    incoming = X._event_cells(ev_incoming, 1)
    fills, labels = X._plan_fill(existing, incoming, n_cols=len(existing))
    # PRIX (col12) vide → rempli ; FESTOCHE (col6) vide → rempli
    assert fills[X._COL_PRIX] == "10€"
    assert fills[X._COL_FESTOCHE] == "Soirée Beaujolais"
    # HEURE déjà remplie (20h00) → NON touchée
    assert X._COL_HEURE not in fills
    assert "PRIX" in labels and "FESTOCHE" in labels


def test_plan_fill_never_overwrites():
    existing = X._event_cells(_ev(heure="20h00", price="10€"), 1)
    incoming = X._event_cells(_ev(heure="21h00", price="15€"), 1)
    fills, labels = X._plan_fill(existing, incoming, n_cols=len(existing))
    assert fills == {} and labels == []


def test_merge_source_cell_appends_without_dup():
    assert X._merge_source_cell("prog.pdf", "https://a.fr/x") == "prog.pdf ; https://a.fr/x"
    assert X._merge_source_cell("https://a.fr/x", "https://a.fr/x") is None  # déjà présent
```

- [ ] **Step 2: Lancer → échec**

Run: `python -m pytest tests/gui/test_export_xlsx_merge.py -q`
Expected: FAIL (`_plan_fill` absent)

- [ ] **Step 3: Implémenter**

```python
_KEY_COLS = {_COL_DATE, _COL_LIEU, _COL_ARTISTE1}
_META_COLS = {_COL_TYPE_SOURCE, _COL_SOURCE, 3, 4, 5}  # TYPE SOURCE, SOURCE, INFO TAPEUR, DATE TAPAGE, DATE EMISSION


def _label_for(col: int) -> str:
    fixed = {
        _COL_FESTOCHE: "FESTOCHE", _COL_STYLE_FESTOCHE: "STYLE FESTOCHE",
        _COL_HEURE: "HEURE", _COL_VILLE: "VILLE", _COL_PRIX: "PRIX",
    }
    if col in fixed:
        return fixed[col]
    # bloc ACT : i = (col-1 - _N_FIXED_COLS)//4 + 1 ; sous-champ selon offset
    offset = (col - 1 - _N_FIXED_COLS) % 4
    i = (col - 1 - _N_FIXED_COLS) // 4 + 1
    sub = {0: "GENRE", 1: "NOM", 2: "ARTISTE", 3: "STYLE"}[offset]
    return f"{sub} {i}"


def _plan_fill(existing: list, incoming: list, n_cols: int):
    fills: dict[int, object] = {}
    labels: list[str] = []
    for col in range(1, n_cols + 1):
        if col in _KEY_COLS or col in _META_COLS:
            continue
        ex = _cell(existing, col)
        inc = _cell(incoming, col)
        if _is_blank(ex) and not _is_blank(inc):
            fills[col] = inc
            labels.append(_label_for(col))
    return fills, labels


def _merge_source_cell(existing_val, incoming_val) -> str | None:
    inc = ("" if incoming_val is None else str(incoming_val)).strip()
    if not inc:
        return None
    parts = [p.strip() for p in str(existing_val or "").split(";") if p.strip()]
    if any(_norm(p) == _norm(inc) for p in parts):
        return None
    parts.append(inc)
    return " ; ".join(parts)
```

- [ ] **Step 4: Lancer → vert**

Run: `python -m pytest tests/gui/test_export_xlsx_merge.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/export_xlsx.py tests/gui/test_export_xlsx_merge.py
git commit -m "feat(export): plan de complétion fill-gaps + append SOURCE"
```

---

### Task 3: `_merge_xlsx` — fusion in-place + MergeReport

**Files:**
- Modify: `tapageur/gui/export_xlsx.py`
- Test: `tests/gui/test_export_xlsx_merge.py`

**Interfaces:**
- Consumes : Task 1 + 2, `_save_workbook`, `_write_act_headers`, `DATA_SHEET`, `_N_FIXED_COLS`, `event_to_row`
- Produces :
  - `@dataclass MergeReport: added: int; filled: int; unchanged: int; added_keys: list[tuple]; filled_detail: list[tuple[tuple, list[str]]]`
  - `_merge_xlsx(events: list[Event], out_path: Path) -> MergeReport`

- [ ] **Step 1: Écrire le test (intégration sur vrai template)**

```python
from pathlib import Path


def test_merge_fills_match_and_appends_new(tmp_path: Path):
    out = tmp_path / "tapage_2026-11.xlsx"
    # Fichier initial : 1 event, HEURE connue, PRIX "?"
    base = _ev(perf="Groupe X", heure="20h00", price="?")
    X.export_xlsx([base], out)  # création
    # Fusion : même event (complète PRIX) + 1 nouvel event
    same = _ev(perf="Groupe X", heure="21h00", price="12€", festival="Soirée Beaujolais")
    new = _ev(perf="Autre Groupe", date_label="Vendredi 6", heure="20h30", price="gratuit")
    report = X._merge_xlsx([same, new], out)

    assert report.added == 1 and report.filled == 1 and report.unchanged == 0

    import openpyxl
    wb = openpyxl.load_workbook(out)
    ws = wb[X.DATA_SHEET]
    rows = {(r[7], r[9], r[14]): r for r in ws.iter_rows(min_row=2, values_only=True)}
    # ligne complétée : PRIX (col12→idx11) rempli, HEURE (idx8) préservée à 20h00
    g = rows[("Mardi 3", "Le Lézard", "Groupe X")]
    assert g[8] == "20h00"      # HEURE préservée
    assert g[11] == "12€"       # PRIX complété
    assert g[5] == "Soirée Beaujolais"  # FESTOCHE complété
    # nouvelle ligne ajoutée
    assert ("Vendredi 6", "Le Lézard", "Autre Groupe") in rows


def test_merge_absent_file_behaves_like_create(tmp_path: Path):
    out = tmp_path / "tapage_2026-11.xlsx"
    report = X._merge_xlsx([_ev()], out)
    assert out.exists() and report.added == 1 and report.filled == 0


def test_merge_appends_source(tmp_path: Path):
    out = tmp_path / "f.xlsx"
    base = _ev(perf="Groupe X", price="?")
    base.source_ref = "https://natif.fr/x"
    X.export_xlsx([base], out)
    same = _ev(perf="Groupe X", price="10€")
    same.source_ref = "https://clappin.fr/agenda-musique/"
    X._merge_xlsx([same], out)
    import openpyxl
    ws = openpyxl.load_workbook(out)[X.DATA_SHEET]
    src = [r[1] for r in ws.iter_rows(min_row=2, values_only=True)][0]
    assert "natif.fr" in src and "clappin.fr" in src
```

- [ ] **Step 2: Lancer → échec**

Run: `python -m pytest tests/gui/test_export_xlsx_merge.py -q`
Expected: FAIL (`_merge_xlsx` absent)

- [ ] **Step 3: Implémenter**

```python
from dataclasses import dataclass, field


@dataclass
class MergeReport:
    added: int = 0
    filled: int = 0
    unchanged: int = 0
    added_keys: list = field(default_factory=list)       # list[tuple]
    filled_detail: list = field(default_factory=list)     # list[(key, [labels])]


def _merge_xlsx(events: list, out_path: Path) -> MergeReport:
    """Fusionne `events` dans un xlsx existant : complète les trous des lignes
    qui matchent (DATE+LIEU+ARTISTE1), ajoute les non-matchés. In-place."""
    if not out_path.exists():
        export_xlsx(events, out_path)  # création
        return MergeReport(added=len(events),
                           added_keys=[_key_from_cells(_event_cells(e, max(1, len(e.acts))))
                                       for e in events])

    wb = openpyxl.load_workbook(out_path)
    if DATA_SHEET not in wb.sheetnames:
        raise ValueError(f"{out_path} n'a pas de feuille '{DATA_SHEET}' : fusion impossible.")
    ws = wb[DATA_SHEET]

    existing_blocks = max(1, (ws.max_column - _N_FIXED_COLS) // 4)
    target_blocks = max(existing_blocks, max((len(e.acts) for e in events), default=1))
    if target_blocks > existing_blocks:
        _write_act_headers(ws, existing_blocks + 1, target_blocks)
    n_cols = _N_FIXED_COLS + target_blocks * 4

    # Index des lignes existantes par clé (1re occurrence).
    row_cells: dict[int, list] = {}
    key_to_row: dict[tuple, int] = {}
    for r in range(2, ws.max_row + 1):
        cells = [ws.cell(row=r, column=c).value for c in range(1, n_cols + 1)]
        k = _key_from_cells(cells)
        if k == ("", "", ""):
            continue  # ligne vide
        row_cells[r] = cells
        key_to_row.setdefault(k, r)

    report = MergeReport()
    to_append: list = []
    for ev in events:
        inc = _event_cells(ev, target_blocks)
        k = _key_from_cells(inc)
        r = key_to_row.get(k)
        if r is None:
            to_append.append(inc)
            report.added += 1
            report.added_keys.append(k)
            continue
        existing = row_cells[r]
        fills, labels = _plan_fill(existing, inc, n_cols)
        new_src = _merge_source_cell(existing[_COL_SOURCE - 1], inc[_COL_SOURCE - 1])
        new_type = _merge_source_cell(existing[_COL_TYPE_SOURCE - 1], inc[_COL_TYPE_SOURCE - 1])
        if not fills and new_src is None and new_type is None:
            report.unchanged += 1
            continue
        for col, val in fills.items():
            ws.cell(row=r, column=col, value=val)
        if new_src is not None:
            ws.cell(row=r, column=_COL_SOURCE, value=new_src)
        if new_type is not None:
            ws.cell(row=r, column=_COL_TYPE_SOURCE, value=new_type)
        report.filled += 1
        report.filled_detail.append((k, labels))

    # Append des non-matchés à la suite.
    start = ws.max_row + 1
    for i, inc in enumerate(to_append):
        for c, value in enumerate(inc, start=1):
            ws.cell(row=start + i, column=c, value=value)

    _save_workbook(wb, out_path)
    return report
```

- [ ] **Step 4: Lancer → vert**

Run: `python -m pytest tests/gui/test_export_xlsx_merge.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/export_xlsx.py tests/gui/test_export_xlsx_merge.py
git commit -m "feat(export): _merge_xlsx fusion in-place + MergeReport"
```

---

### Task 4: Lecture des sources présentes (skip incrémental)

**Files:**
- Modify: `tapageur/gui/export_xlsx.py`
- Test: `tests/gui/test_export_xlsx_merge.py`

**Interfaces:**
- Produces :
  - `existing_sources(out_path: Path) -> set[str]` : valeurs normalisées de la
    colonne SOURCE (col 2), suffixe « (p.N) » retiré. `set()` si fichier/feuille
    absents.

- [ ] **Step 1: Écrire le test**

```python
def test_existing_sources_reads_source_column(tmp_path: Path):
    out = tmp_path / "f.xlsx"
    e1 = _ev(); e1.source_ref = "https://clappin.fr/agenda-musique/"
    e2 = _ev(perf="Y", date_label="Jeudi 5")
    e2.source_kind = "image"; e2.source_ref = r"C:\x\flyer.png"
    X.export_xlsx([e1, e2], out)
    srcs = X.existing_sources(out)
    assert "https://clappin.fr/agenda-musique/" in srcs
    assert "flyer.png" in srcs  # image → basename


def test_existing_sources_absent_file():
    assert X.existing_sources(Path("nope-xyz.xlsx")) == set()
```

- [ ] **Step 2: Lancer → échec**

Run: `python -m pytest tests/gui/test_export_xlsx_merge.py -q`
Expected: FAIL

- [ ] **Step 3: Implémenter**

```python
def existing_sources(out_path: Path) -> set:
    """Ensemble des sources déjà présentes (colonne SOURCE), pour le skip
    incrémental. Suffixe ' (p.N)' des PDF retiré. Vide si fichier absent."""
    if not out_path.exists():
        return set()
    try:
        wb = openpyxl.load_workbook(out_path, read_only=True, data_only=True)
    except Exception:
        return set()
    try:
        if DATA_SHEET not in wb.sheetnames:
            return set()
        ws = wb[DATA_SHEET]
        out: set = set()
        for r in ws.iter_rows(min_row=2, min_col=_COL_SOURCE, max_col=_COL_SOURCE,
                              values_only=True):
            val = r[0]
            if not val:
                continue
            for part in str(val).split(";"):
                s = part.strip()
                if s.endswith(")") and " (p." in s:
                    s = s[:s.rindex(" (p.")]
                if s:
                    out.add(s)
        return out
    finally:
        wb.close()
```

- [ ] **Step 4: Lancer → vert**

Run: `python -m pytest tests/gui/test_export_xlsx_merge.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/export_xlsx.py tests/gui/test_export_xlsx_merge.py
git commit -m "feat(export): existing_sources() pour le skip incrémental"
```

---

### Task 5: `RunRequest.write_mode` + routage service + skip incrémental + compte-rendu

**Files:**
- Modify: `tapageur/gui/service.py`
- Test: `tests/gui/test_service.py`

**Interfaces:**
- Consumes : `export_xlsx.existing_sources`, `export_xlsx._merge_xlsx`, `export_xlsx.export_xlsx`, `MergeReport`
- Produces :
  - `RunRequest.write_mode: str = "create"` (remplace `append: bool`)
  - `MonthResult` gagne : `added:int=0, filled:int=0, unchanged:int=0, sources_skipped:int=0`
  - helper interne `_source_display(kind, ref) -> str` (miroir `validate._source_ref_display`, réutilisé)
  - `_export(events, out_dir, label, formats, write_mode)` route selon le mode et renvoie `(paths, MergeReport | None)`

- [ ] **Step 1: Écrire les tests**

```python
# tests/gui/test_service.py (ajouts)
from pathlib import Path
from tapageur.gui import service as S
from tapageur.gui.inputs import UrlInput, FileInput


def test_write_mode_append_skips_present_sources(monkeypatch, tmp_path):
    # fichier existant contenant déjà la source "https://a.fr/present"
    monkeypatch.setattr(S._xlsx, "existing_sources",
                        lambda p: {"https://a.fr/present"})
    captured = {}
    def fake_items_urls(url_inputs, month, progress=None):
        captured["urls"] = [u.url for u in url_inputs]
        return []
    monkeypatch.setattr(S, "items_from_urls", fake_items_urls)
    monkeypatch.setattr(S, "items_from_files", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    (tmp_path / "tapage_2026-11.xlsx").write_bytes(b"x")  # existe
    req = S.RunRequest(
        url_inputs=[UrlInput(url="https://a.fr/present"), UrlInput(url="https://a.fr/new")],
        months=["2026-11"], formats=["xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
        write_mode="append",
    )
    S.run(req)
    assert captured["urls"] == ["https://a.fr/new"]  # source présente filtrée


def test_write_mode_merge_routes_to_merge(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(S._xlsx, "_merge_xlsx",
                        lambda evs, p: calls.setdefault("merge", True) or S._xlsx.MergeReport(added=1))
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: calls.setdefault("create", True))
    monkeypatch.setattr(S, "items_from_urls", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_files", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [object()])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    monkeypatch.setattr(S, "build_alerts", lambda *a, **k: [])
    req = S.RunRequest(url_inputs=[], months=["2026-11"], formats=["xlsx"],
                       out_dir=tmp_path, tapeur_email="t@b.fr", write_mode="merge")
    res = S.run(req)
    assert calls.get("merge") and res[0].added == 1
```

Vérifier aussi que les mocks existants de `tests/gui/test_service.py` (qui construisent `RunRequest(..., append=...)`) sont migrés vers `write_mode=...` (remplacer `append=True`→`write_mode="append"`, `append=False`/absent→défaut `"create"`).

- [ ] **Step 2: Lancer → échec**

Run: `python -m pytest tests/gui/test_service.py -q`
Expected: FAIL (`write_mode` inconnu / routage absent)

- [ ] **Step 3: Implémenter**

Dans `service.py` :

1. `RunRequest` : remplacer `append: bool = False` par `write_mode: str = "create"`.
2. `MonthResult` : ajouter `added: int = 0`, `filled: int = 0`, `unchanged: int = 0`, `sources_skipped: int = 0`.
3. Helper source display + skip :

```python
from tapageur.validate import _source_ref_display


def _input_source_display(kind: str, ref: str) -> str:
    return _source_ref_display(kind, ref)


def _filter_present_sources(req: "RunRequest", target: Path, emit) -> int:
    """En mode incrémental : retire les file/url inputs dont la SOURCE est déjà
    dans le fichier cible. Retourne le ncombre de sources ignorées. Textes gardés."""
    present = _xlsx.existing_sources(target)
    if not present:
        return 0
    present_norm = {p.strip() for p in present}
    skipped = 0
    kept_files = []
    for fi in req.file_inputs:
        disp = _input_source_display("image", fi.path)  # basename, suffisant pour fichiers/pdf
        from pathlib import Path as _P
        base = _P(fi.path).name
        if base in present_norm or disp in present_norm:
            skipped += 1
        else:
            kept_files.append(fi)
    kept_urls = []
    for u in req.url_inputs:
        if u.url in present_norm:
            skipped += 1
        else:
            kept_urls.append(u)
    req.file_inputs = kept_files
    req.url_inputs = kept_urls
    if skipped:
        emit(f"Incrémental : {skipped} source(s) déjà présente(s) ignorée(s).")
    return skipped
```

4. `_export` : router selon `write_mode` et renvoyer le report :

```python
def _export(events, out_dir: Path, label: str, formats: list, write_mode: str = "create"):
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list = []
    report = None
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
        if write_mode == "merge":
            report = _xlsx._merge_xlsx(events, p)
        elif write_mode == "append":
            _xlsx.export_xlsx(events, p, append=True)
        else:
            _xlsx.export_xlsx(events, p)
        written.append(p)
    return written, report
```

5. `run` — mode spécifique : skip incrémental AVANT collecte + export routé + report → MonthResult + log détail :

```python
    # (dans run(), avant la collecte, uniquement en mode spécifique mono-mois)
    sources_skipped = 0
    if req.month_mode != "all" and req.write_mode == "append" and len(req.months) == 1:
        target = req.out_dir / f"tapage_{req.months[0]}.xlsx"
        sources_skipped = _filter_present_sources(req, target, _emit)
```

Puis dans la boucle mois (branche `else`) remplacer l'appel `_export(... append=req.append)` par :

```python
            files, report = _export(events, req.out_dir, month, req.formats,
                                    write_mode=req.write_mode)
            alerts = build_alerts(events, ref_cities, ref_venues)
            if req.write_mode in ("append", "merge") and "xlsx" not in req.formats:
                alerts.append(f"Mode '{req.write_mode}' ignoré : xlsx non sélectionné.")
            mr = MonthResult(month=month, n_events=len(events), files=files,
                             alerts=alerts, events=events,
                             sources_skipped=sources_skipped)
            if report is not None:
                mr.added, mr.filled, mr.unchanged = report.added, report.filled, report.unchanged
                _emit(f"Fusion : {report.added} ajoutés · {report.filled} complétés · "
                      f"{report.unchanged} inchangés.")
                for k in report.added_keys:
                    _emit(f"  + AJOUTÉ  {k[0]} · {k[1]} · {k[2]}")
                for k, labels in report.filled_detail:
                    _emit(f"  ~ COMPLÉTÉ {k[0]} · {k[1]} · {k[2]} → {', '.join(labels)}")
            results.append(mr)
```

Dans la branche `all`, remplacer `append=req.append` par `write_mode=req.write_mode` et récupérer `files, report = _export(...)` (report appliqué au MonthResult du mois comme ci-dessus ; pas de skip incrémental en mode « all »).

- [ ] **Step 4: Lancer → vert**

Run: `python -m pytest tests/gui/test_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/service.py tests/gui/test_service.py
git commit -m "feat(service): write_mode (create/append/merge) + skip incrémental + report"
```

---

### Task 6: `app.py` — payload write_mode (+ compat legacy append)

**Files:**
- Modify: `tapageur/gui/app.py`
- Test: `tests/gui/test_app.py` (ajout si le fichier existe ; sinon étape de test manuel documentée)

**Interfaces:**
- Consumes : `RunRequest.write_mode`
- Produces : construction `RunRequest(..., write_mode=...)` depuis le payload, avec repli legacy `append`.

- [ ] **Step 1: Écrire le test (si tests/gui/test_app.py existe)**

```python
def test_payload_write_mode_from_legacy_append():
    # helper pur à extraire : _resolve_write_mode(payload)
    from tapageur.gui.app import _resolve_write_mode
    assert _resolve_write_mode({"write_mode": "merge"}) == "merge"
    assert _resolve_write_mode({"append": True}) == "append"
    assert _resolve_write_mode({}) == "create"
```

- [ ] **Step 2: Lancer → échec**

Run: `python -m pytest tests/gui/test_app.py -q`
Expected: FAIL (`_resolve_write_mode` absent)

- [ ] **Step 3: Implémenter**

Dans `app.py`, ajouter le helper et l'utiliser :

```python
def _resolve_write_mode(payload: dict) -> str:
    wm = payload.get("write_mode")
    if wm in ("create", "append", "merge"):
        return wm
    return "append" if payload.get("append") else "create"
```

Et dans `run_extraction`, remplacer `append=payload.get("append", False)` par
`write_mode=_resolve_write_mode(payload)`.

- [ ] **Step 4: Lancer → vert**

Run: `python -m pytest tests/gui/test_app.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/app.py tests/gui/test_app.py
git commit -m "feat(gui): payload write_mode (+ compat legacy append)"
```

---

### Task 7: UI — radio 3 modes (index.html)

**Files:**
- Modify: `tapageur/gui/web/index.html`

**Interfaces:**
- Consumes : payload `write_mode`, `applyConfig`

- [ ] **Step 1: Remplacer la case append par un radio**

Remplacer (≈ ligne 105-107) :

```html
    <div style="margin-top:8px">
      <label><input id="append" type="checkbox"> Ajouter au fichier existant (xlsx)</label>
    </div>
```

par :

```html
    <div style="margin-top:8px">
      <div>Écriture (xlsx) :</div>
      <label><input type="radio" name="write-mode" value="create" checked> Créer / écraser</label>
      <label><input type="radio" name="write-mode" value="append"> Ajouter (incrémental — ignore les sources déjà présentes)</label>
      <label><input type="radio" name="write-mode" value="merge"> Fusionner (compléter / ajouter sans écraser)</label>
    </div>
```

- [ ] **Step 2: Payload**

Remplacer `append: document.getElementById('append').checked,` (≈ ligne 488) par :

```js
    write_mode: (document.querySelector('input[name="write-mode"]:checked') || {}).value || 'create',
```

- [ ] **Step 3: applyConfig**

Remplacer `document.getElementById('append').checked = !!cfg.append;` (≈ ligne 367) par :

```js
  // write_mode (repli legacy append)
  const wm = (['create','append','merge'].includes(cfg.write_mode)) ? cfg.write_mode
             : (cfg.append ? 'append' : 'create');
  const wmRadio = document.querySelector('input[name="write-mode"][value="' + wm + '"]');
  if (wmRadio) wmRadio.checked = true;
```

- [ ] **Step 4: Vérif manuelle**

Lancer `tapageur-gui` en dev : les 3 modes s'affichent, « Créer » par défaut ; un import de config legacy (`append:true`) coche « Ajouter » ; une passe merge affiche les lignes AJOUTÉ/COMPLÉTÉ dans le Résumé/log.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/web/index.html
git commit -m "feat(gui): radio 3 modes d'écriture (créer/ajouter/fusionner)"
```

---

### Task 8: Suite complète + vérif non-régression

**Files:**
- Test: toute la suite

- [ ] **Step 1: Lancer toute la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (les anciens tests `append` migrés en `write_mode`)

- [ ] **Step 2: Vérifier l'absence de `req.append` / `append=` résiduels côté service**

Run: `python -c "import tapageur.gui.service"` et `grep -rn "\.append\b" tapageur/gui/service.py` (ne doit rester que des `list.append`, pas de `req.append`).

- [ ] **Step 3: Commit (si ajustements)**

```bash
git add -A
git commit -m "test: suite verte après migration write_mode"
```

---

## Self-Review

- **Couverture spec :** 3 modes (Task 5/7), clé de match visible (Task 1), fill-gaps + jamais d'écrasement (Task 2), SOURCE accolée (Task 2/3), reverse-parse par position (Task 3), skip incrémental par colonne SOURCE (Task 4/5), compte-rendu chiffré + détail AJOUTÉ/COMPLÉTÉ (Task 5), fichier absent = create (Task 3), textes toujours traités (Task 5 : non filtrés). ✓
- **Placeholders :** aucun — code complet à chaque étape.
- **Cohérence des types :** `MergeReport` (Task 3) consommé en Task 5 ; `existing_sources` (Task 4) consommé en Task 5 ; constantes de colonnes définies Task 1 et réutilisées. `write_mode` string unique partout.
- **Limites assumées** (édition colonne-clé, lignes groupées, cross-source naming) : documentées dans la spec, hors scope v1.
