# Manifeste des sources traitées — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre le skip incrémental fiable, y compris pour les sources ayant produit 0 event (PDF/avif) et les sites à suivre, via un manifeste des sources traitées stocké dans une feuille cachée de l'xlsx.

**Architecture:** Deux helpers dans `tapageur/gui/export_xlsx.py` (lecture/écriture d'une feuille cachée `_sources_traitees`), et câblage dans `tapageur/gui/service.py` (calcul des ids d'entrée depuis `RunRequest`, skip via manifeste avec repli sur l'heuristique actuelle, écriture du manifeste après chaque passe). Aucun changement de `Event`, `event_to_row`, template, `_N_FIXED_COLS`.

**Tech Stack:** Python 3.11+, openpyxl, pytest.

## Global Constraints

- Ne RIEN changer au schéma `Event`, à `event_to_row`, au template, à `_N_FIXED_COLS`, ni aux colonnes du merge.
- Le manifeste porte sur les **entrées** (`RunRequest`), pas sur les events.
- Feuille cachée nommée `_sources_traitees`, `sheet_state="hidden"`, colonnes `id | type | date_passe`.
- Union sans doublon sur `id` (la `date_passe` d'origine est conservée).
- Écriture xlsx via `_save_workbook` (sauvegarde atomique / message si verrouillé).
- Ids : URL saisie (web), **basename** (fichier/image), « texte #N » (texte).
- Textes : **toujours traités** (jamais skippés) — id positionnel non stable.
- Skip incrémental : seulement **mode spécifique mono-mois + write_mode "append"**. Si pas de feuille manifeste → **repli** sur `_filter_present_sources` (SOURCE + hôte) existant.
- Fusionner : **pas de skip** ; Créer/Ajouter/Fusionner **écrivent** tous le manifeste (union) après la passe.
- Matching fichiers insensible à la casse (Windows) ; URLs exact.
- Commits : terminer par `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Helpers manifeste (feuille cachée) dans export_xlsx.py

**Files:**
- Modify: `tapageur/gui/export_xlsx.py`
- Test: `tests/gui/test_export_xlsx_merge.py`

**Interfaces:**
- Produces :
  - `MANIFEST_SHEET = "_sources_traitees"`
  - `has_manifest(out_path: Path) -> bool`
  - `read_processed_sources(out_path: Path) -> set[str]` (ids ; `set()` si absent)
  - `record_processed_sources(out_path: Path, sources: list[tuple[str, str]]) -> None`
    (union `(id, type)` + `date_passe` du jour ; crée la feuille cachée si absente)

- [ ] **Step 1: Écrire les tests**

```python
def test_manifest_record_then_read(tmp_path: Path):
    out = tmp_path / "f.xlsx"
    X.export_xlsx([_ev()], out)                 # crée un xlsx normal
    assert X.has_manifest(out) is False
    X.record_processed_sources(out, [("https://a.fr/x", "URL"),
                                     ("flyer.avif", "Fichier")])
    assert X.has_manifest(out) is True
    got = X.read_processed_sources(out)
    assert got == {"https://a.fr/x", "flyer.avif"}


def test_manifest_union_no_dup_keeps_first_date(tmp_path: Path):
    out = tmp_path / "f.xlsx"
    X.export_xlsx([_ev()], out)
    X.record_processed_sources(out, [("s1", "URL")])
    import openpyxl
    d1 = [r for r in openpyxl.load_workbook(out)[X.MANIFEST_SHEET]
          .iter_rows(min_row=2, values_only=True)][0][2]
    X.record_processed_sources(out, [("s1", "URL"), ("s2", "URL")])  # s1 déjà là
    wb = openpyxl.load_workbook(out)
    rows = [r for r in wb[X.MANIFEST_SHEET].iter_rows(min_row=2, values_only=True)]
    ids = [r[0] for r in rows]
    assert ids == ["s1", "s2"]                  # pas de doublon de s1
    assert rows[0][2] == d1                      # date d'origine conservée
    assert wb[X.MANIFEST_SHEET].sheet_state == "hidden"


def test_manifest_read_absent_file():
    assert X.read_processed_sources(Path("nope-xyz.xlsx")) == set()
    assert X.has_manifest(Path("nope-xyz.xlsx")) is False


def test_manifest_sheet_does_not_leak_into_data(tmp_path: Path):
    """La feuille manifeste ne doit pas perturber la lecture des events."""
    out = tmp_path / "f.xlsx"
    X.export_xlsx([_ev(perf="X")], out)
    X.record_processed_sources(out, [("s1", "URL")])
    import openpyxl
    ws = openpyxl.load_workbook(out)[X.DATA_SHEET]
    perfs = [r[14] for r in ws.iter_rows(min_row=2, values_only=True)]
    assert "X" in perfs
```

- [ ] **Step 2: Lancer → échec**

Run: `python -m pytest tests/gui/test_export_xlsx_merge.py -q`
Expected: FAIL (`has_manifest` / `record_processed_sources` absents)

- [ ] **Step 3: Implémenter**

Ajouter dans `tapageur/gui/export_xlsx.py` (après les helpers existants ; `from datetime import date` en tête si absent — sinon import local) :

```python
MANIFEST_SHEET = "_sources_traitees"


def has_manifest(out_path: Path) -> bool:
    if not out_path.exists():
        return False
    try:
        wb = openpyxl.load_workbook(out_path, read_only=True)
    except Exception:
        return False
    try:
        return MANIFEST_SHEET in wb.sheetnames
    finally:
        wb.close()


def read_processed_sources(out_path: Path) -> set:
    """Ids des sources déjà traitées (feuille cachée). set() si absent."""
    if not out_path.exists():
        return set()
    try:
        wb = openpyxl.load_workbook(out_path, read_only=True, data_only=True)
    except Exception:
        return set()
    try:
        if MANIFEST_SHEET not in wb.sheetnames:
            return set()
        ws = wb[MANIFEST_SHEET]
        out: set = set()
        for i, row in enumerate(ws.iter_rows(min_col=1, max_col=1, values_only=True)):
            if i == 0:
                continue  # en-tête
            if row and row[0]:
                out.add(str(row[0]).strip())
        return out
    finally:
        wb.close()


def record_processed_sources(out_path: Path, sources: list) -> None:
    """Union des `(id, type)` dans la feuille cachée (date d'origine conservée).
    No-op si le fichier n'existe pas ou `sources` vide."""
    from datetime import date as _date
    if not out_path.exists() or not sources:
        return
    wb = openpyxl.load_workbook(out_path)
    if MANIFEST_SHEET in wb.sheetnames:
        ws = wb[MANIFEST_SHEET]
    else:
        ws = wb.create_sheet(MANIFEST_SHEET)
        ws.sheet_state = "hidden"
        ws.append(["id", "type", "date_passe"])
    existing: set = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row and row[0]:
            existing.add(str(row[0]).strip())
    today = _date.today().isoformat()
    changed = False
    for sid, stype in sources:
        key = str(sid).strip()
        if key and key not in existing:
            ws.append([key, stype, today])
            existing.add(key)
            changed = True
    if changed:
        _save_workbook(wb, out_path)
    else:
        wb.close()
```

- [ ] **Step 4: Lancer → vert**

Run: `python -m pytest tests/gui/test_export_xlsx_merge.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/export_xlsx.py tests/gui/test_export_xlsx_merge.py
git commit -m "feat(export): manifeste des sources traitées (feuille cachée)"
```

---

### Task 2: Câblage service (ids d'entrée, skip manifeste + repli, écriture)

**Files:**
- Modify: `tapageur/gui/service.py`
- Test: `tests/gui/test_service.py`

**Interfaces:**
- Consumes : `export_xlsx.has_manifest`, `read_processed_sources`, `record_processed_sources` (Task 1)
- Produces :
  - `_input_source_ids(req) -> list[tuple[str, str]]`
  - `_filter_by_manifest(req, target, emit) -> int` (skip via manifeste ; fichiers casse-insensible, urls exact ; textes gardés)
  - `run()` : skip manifeste (repli sur `_filter_present_sources` si pas de manifeste) + `record_processed_sources` après chaque fichier écrit.

- [ ] **Step 1: Écrire les tests**

```python
def test_input_source_ids(tmp_path):
    from tapageur.gui.inputs import FileInput, UrlInput, TextInput
    req = S.RunRequest(
        url_inputs=[UrlInput(url="https://a.fr/x")],
        file_inputs=[FileInput(path=r"C:\d\1.avif")],
        text_inputs=[TextInput(text="coucou")],
        months=["2026-11"], formats=["xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
    )
    ids = S._input_source_ids(req)
    assert ("1.avif", "Fichier") in ids
    assert ("https://a.fr/x", "URL") in ids
    assert any(t == "Texte" for _, t in ids)


def test_append_skips_via_manifest(monkeypatch, tmp_path):
    from tapageur.gui.inputs import UrlInput, FileInput
    monkeypatch.setattr(S._xlsx, "has_manifest", lambda p: True)
    monkeypatch.setattr(S._xlsx, "read_processed_sources",
                        lambda p: {"https://a.fr/present", "1.avif"})
    monkeypatch.setattr(S._xlsx, "record_processed_sources", lambda *a, **k: None)
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: None)
    captured = {}
    monkeypatch.setattr(S, "items_from_urls",
                        lambda ui, m, progress=None: captured.setdefault(
                            "urls", [u.url for u in ui]) or [])
    monkeypatch.setattr(S, "items_from_files",
                        lambda fi, progress=None: captured.setdefault(
                            "files", [__import__("pathlib").Path(f.path).name for f in fi]) or [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    (tmp_path / "tapage_2026-11.xlsx").write_bytes(b"x")
    req = S.RunRequest(
        url_inputs=[UrlInput(url="https://a.fr/present"), UrlInput(url="https://a.fr/new")],
        file_inputs=[FileInput(path=r"C:\d\1.avif"), FileInput(path=r"C:\d\2.avif")],
        months=["2026-11"], formats=["xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
        write_mode="append",
    )
    S.run(req)
    assert captured["urls"] == ["https://a.fr/new"]
    assert captured["files"] == ["2.avif"]       # 1.avif (au manifeste) skippé


def test_append_falls_back_without_manifest(monkeypatch, tmp_path):
    """Pas de feuille manifeste → repli sur l'heuristique SOURCE + hôte."""
    from tapageur.gui.inputs import UrlInput
    monkeypatch.setattr(S._xlsx, "has_manifest", lambda p: False)
    called = {}
    monkeypatch.setattr(S, "_filter_present_sources",
                        lambda req, target, emit: called.setdefault("fallback", True) or 0)
    monkeypatch.setattr(S._xlsx, "record_processed_sources", lambda *a, **k: None)
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: None)
    monkeypatch.setattr(S, "items_from_urls", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_files", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    (tmp_path / "tapage_2026-11.xlsx").write_bytes(b"x")
    req = S.RunRequest(url_inputs=[UrlInput(url="https://a.fr/x")],
                       months=["2026-11"], formats=["xlsx"], out_dir=tmp_path,
                       tapeur_email="t@b.fr", write_mode="append")
    S.run(req)
    assert called.get("fallback")


def test_run_records_manifest_after_pass(monkeypatch, tmp_path):
    from tapageur.gui.inputs import UrlInput
    rec = {}
    monkeypatch.setattr(S._xlsx, "record_processed_sources",
                        lambda path, sources: rec.setdefault("sources", sources))
    monkeypatch.setattr(S._xlsx, "export_xlsx", lambda *a, **k: None)
    monkeypatch.setattr(S, "items_from_urls", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_files", lambda *a, **k: [])
    monkeypatch.setattr(S, "items_from_texts", lambda *a, **k: [])
    monkeypatch.setattr(S, "_pipeline", lambda *a, **k: [])
    monkeypatch.setattr(S, "_reference_lists", lambda: (set(), set()))
    monkeypatch.setattr(S, "build_alerts", lambda *a, **k: [])
    req = S.RunRequest(url_inputs=[UrlInput(url="https://a.fr/x")],
                       months=["2026-11"], formats=["xlsx"], out_dir=tmp_path,
                       tapeur_email="t@b.fr", write_mode="create")
    S.run(req)
    assert ("https://a.fr/x", "URL") in rec["sources"]
```

- [ ] **Step 2: Lancer → échec**

Run: `python -m pytest tests/gui/test_service.py -q`
Expected: FAIL

- [ ] **Step 3: Implémenter**

Dans `service.py` :

```python
def _input_source_ids(req: "RunRequest") -> list:
    """(id, type) des sources saisies, pour le manifeste. id = URL (web),
    basename (fichier), « texte #N » (texte)."""
    ids: list = []
    for fi in req.file_inputs:
        ids.append((Path(fi.path).name, "Fichier"))
    for u in req.url_inputs:
        ids.append((u.url, "URL"))
    n = 0
    for t in req.text_inputs:
        if getattr(t, "text", "") and t.text.strip():
            n += 1
            ids.append((f"texte #{n}", "Texte"))
    return ids


def _filter_by_manifest(req: "RunRequest", target: Path, emit) -> int:
    """Skip via manifeste : retire les file/url inputs déjà traités. Textes
    gardés. Fichiers insensibles à la casse, urls exact."""
    manifest = _xlsx.read_processed_sources(target)
    if not manifest:
        return 0
    manifest_ci = {m.casefold() for m in manifest}
    skipped = 0
    kept_files = []
    for fi in req.file_inputs:
        if Path(fi.path).name.casefold() in manifest_ci:
            skipped += 1
        else:
            kept_files.append(fi)
    kept_urls = []
    for u in req.url_inputs:
        if u.url in manifest:
            skipped += 1
        else:
            kept_urls.append(u)
    req.file_inputs = kept_files
    req.url_inputs = kept_urls
    if skipped:
        emit(f"Incrémental : {skipped} source(s) déjà traitée(s) ignorée(s).")
    return skipped
```

Dans `run()`, capturer les ids AVANT tout filtrage (juste après `ref_cities, ref_venues = _reference_lists()`):

```python
    all_input_ids = _input_source_ids(req)
```

Remplacer le bloc skip (lignes « Skip incrémental … _filter_present_sources ») par :

```python
    sources_skipped = 0
    if req.month_mode != "all" and req.write_mode == "append" and len(req.months) == 1:
        target = req.out_dir / f"tapage_{req.months[0]}.xlsx"
        if _xlsx.has_manifest(target):
            sources_skipped = _filter_by_manifest(req, target, _emit)
        else:
            sources_skipped = _filter_present_sources(req, target, _emit)  # repli
```

Après CHAQUE `_export(...)` (branches `all` ET spécifique), enregistrer le manifeste du fichier écrit :

```python
            # (après files, report = _export(...))
            if "xlsx" in req.formats:
                _xlsx.record_processed_sources(req.out_dir / f"tapage_{month}.xlsx",
                                               all_input_ids)
```

- [ ] **Step 4: Lancer → vert**

Run: `python -m pytest tests/gui/test_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/service.py tests/gui/test_service.py
git commit -m "feat(service): skip incrémental via manifeste des sources traitées"
```

---

### Task 3: Suite complète + vérif manuelle

**Files:**
- Test: toute la suite

- [ ] **Step 1: Suite complète**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 2: Vérif manuelle (dev)**

Lancer `tapageur-gui` : passe **Créer** → le fichier contient une feuille cachée `_sources_traitees` (visible via « Afficher » dans Excel) listant toutes les sources (y compris un PDF/avif à 0 event). Passe **Ajouter** en ré-ajoutant les mêmes sources + une nouvelle → log « N source(s) déjà traitée(s) ignorée(s) », seule la nouvelle est collectée (le PDF à 0 event n'est plus re-collecté). Passe **Fusionner** → aucune source skippée, manifeste à jour.

- [ ] **Step 3: Commit (si ajustements)**

```bash
git add -A
git commit -m "test: suite verte — manifeste des sources traitées"
```

---

## Self-Review

- **Couverture spec :** feuille cachée id|type|date (Task 1), union sans doublon + date conservée (Task 1), ids par type + textes gardés (Task 2), skip Ajouter + repli (Task 2), écriture dans tous les modes (Task 2), pas de changement schéma/template (aucune task n'y touche). ✓
- **Placeholders :** aucun — code complet.
- **Types :** `record_processed_sources(sources: list[tuple[str,str]])` fourni par `_input_source_ids` ; `read_processed_sources`/`has_manifest` consommés dans le skip. Cohérent.
- **Limites** (textes non skippés, repli, tous-les-mois sans skip) : conformes à la spec.
