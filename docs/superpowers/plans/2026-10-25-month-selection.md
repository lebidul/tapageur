# Sélection du mois — décision parente — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Décision parente « un mois précis » (multi-mois, 1 fichier/mois) vs « tous les mois des sources » (1 fichier par mois détecté), avec année de référence auto (déc→+1) éditable.

**Architecture:** `normalize` gagne un indice « année de référence » pour le mode sans filtre. `service.run` route selon `month_mode` : mode « all » extrait une fois sans filtre puis groupe les events par `date_iso[:7]` et exporte par mois. L'UI passe d'un champ libre + case à un radio parent + champ année éditable.

**Tech Stack:** Python 3.11+, pydantic v2, pytest, pywebview (HTML/JS).

## Global Constraints

- `month_mode` ∈ {`"specific"`, `"all"`} remplace `no_month_filter`.
- Mode « specific » : comportement actuel (multi-mois, filtre strict, 1 fichier/mois).
- Mode « all » : 1 fichier **par mois détecté** (`date_iso[:7]`), année de référence passée à Claude.
- Année de référence : `default_reference_year()` = année courante, **déc → +1** ; éditable côté UI.
- `cache_key` du mode « all » varie selon l'année de référence (passer `month="tous-<année>"`).
- Contenu JS dynamique via DOM/`textContent` (jamais `innerHTML` dynamique).
- Message de commit terminé par : `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1 : `normalize` — indice année de référence (mode sans filtre)

**Files:**
- Modify: `tapageur/normalize.py`, `tapageur/version.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- `normalize_items(items, month, out_path, model=None, month_filter=True, progress=None, reference_year=None)`
- `_normalize_one(client, item, month, model, tapeur_email, month_filter=True, reference_year=None)`
- Mode sans filtre + `reference_year` → user message : « Mois cible : tous les mois (année de référence : {reference_year} — utilise cette année pour les dates sans année) ».

- [ ] **Step 1 : Test du month_hint avec année de référence (échec attendu)**

Ajouter dans `tests/test_normalize.py` (réutilise `_fake_client_returning` / `_text_item`) :

```python
def test_normalize_one_passes_reference_year_hint(monkeypatch):
    """En mode sans filtre + reference_year, le user message cite l'année de réf."""
    from tapageur import normalize as _norm
    seen = {}
    real_build = _norm._build_user_content
    def spy(item, month_hint):
        seen["hint"] = month_hint
        return real_build(item, month_hint)
    monkeypatch.setattr(_norm, "_build_user_content", spy)
    item = _text_item({})
    ev = {"date_iso": "2026-11-17", "times": ["20h00"], "venue": "V",
          "city": "Le Mans", "price": "?",
          "acts": [{"genre": "c", "title": None, "performer": "A", "style": None}]}
    _norm._normalize_one(_fake_client_returning([ev]), item, "tous-2026", None,
                         "t@b.fr", month_filter=False, reference_year="2026")
    assert "2026" in seen["hint"]
    assert "référence" in seen["hint"].lower()
```

- [ ] **Step 2 : Lancer → échec**

Run: `python -m pytest tests/test_normalize.py -k reference_year_hint -q`
Expected: FAIL (`_normalize_one` n'accepte pas `reference_year`).

- [ ] **Step 3 : Implémenter le paramètre + le hint**

Dans `tapageur/normalize.py`, signature de `_normalize_one` (ajouter le param) :

```python
def _normalize_one(
    client: Anthropic,
    item: CollectedItem,
    month: str,
    model: str | None,
    tapeur_email: str,
    month_filter: bool = True,
    reference_year: str | None = None,
) -> list[Event]:
```

Repérer la ligne qui construit `month_hint` (recherche `month_hint =`) et la remplacer par :

```python
    if month_filter:
        month_hint = month
    elif reference_year:
        month_hint = (f"tous les mois (année de référence : {reference_year} — "
                      f"utilise cette année pour les dates sans année)")
    else:
        month_hint = "tous les mois (ne pas filtrer par date)"
```

Dans `normalize_items`, ajouter `reference_year: str | None = None` à la signature
et le passer à l'appel `_normalize_one(...)` :

```python
            events = _normalize_one(client, item, month, model, tapeur_email,
                                    month_filter, reference_year)
```

- [ ] **Step 4 : Lancer → succès**

Run: `python -m pytest tests/test_normalize.py -k reference_year_hint -q`
Expected: PASS.

- [ ] **Step 5 : Élargir la règle ANNÉE + bump PROMPT_VERSION**

Dans `SYSTEM_PROMPT`, règle 0, remplacer la phrase sur l'année par (ajout « ou
de l'année de référence ») :

```
0. ANNÉE (CRITIQUE) : le « Mois cible » du user message (ex. 2026-11), OU
   l'« année de référence » qu'il indique, fixe l'année de référence. Pour
   toute date du contenu SANS année explicite, date_iso DOIT utiliser cette
   année. Ne déduis JAMAIS l'année à partir du seul jour de semaine (plusieurs
   années partagent le même jour — n'invente pas une année passée). N'utilise
   une autre année que si elle est ÉCRITE explicitement dans le contenu.
```

Dans `tapageur/version.py` : ajouter au changelog et passer `PROMPT_VERSION = "v7"`.

```python
- v7 : règle ANNÉE élargie pour couvrir le mode « tous les mois » (année de
       référence passée dans le user message au lieu d'un mois cible).
```

- [ ] **Step 6 : Suite normalize**

Run: `python -m pytest tests/test_normalize.py -q`
Expected: PASS.

- [ ] **Step 7 : Commit**

```bash
git add tapageur/normalize.py tapageur/version.py tests/test_normalize.py
git commit -m "feat(normalize): indice année de référence pour le mode tous les mois

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2 : `service` — default_reference_year + RunRequest + run (2 modes)

**Files:**
- Modify: `tapageur/gui/service.py`
- Test: `tests/gui/test_service.py`

**Interfaces:**
- `default_reference_year(today: date | None = None) -> str`
- `RunRequest` : `no_month_filter` retiré ; `month_mode: str = "specific"` et
  `reference_year: str = ""` ajoutés ; `months`, `append`, etc. conservés.
- `run` : mode « specific » = une passe filtrée par mois (inchangé) ; mode « all »
  = extraire sans filtre (année de réf) puis grouper par `date_iso[:7]`, un export
  par mois.
- Consomme `normalize_items(..., reference_year=...)` (Task 1).

- [ ] **Step 1 : Tests (échec attendu)**

Dans `tests/gui/test_service.py`, ajouter :

```python
from datetime import date


def test_default_reference_year_normal_and_december():
    assert service.default_reference_year(date(2026, 11, 1)) == "2026"
    assert service.default_reference_year(date(2026, 1, 5)) == "2026"
    assert service.default_reference_year(date(2026, 12, 10)) == "2027"


def test_run_all_months_one_file_per_month(tmp_path, monkeypatch):
    """Mode all : events sur 2 mois → 2 fichiers groupés par mois."""
    evs = [_event(perf="Nov", times=["20h00"]), _event(perf="Dec", times=["21h00"])]
    evs[0].date_iso = "2026-11-10"
    evs[1].date_iso = "2026-12-05"
    monkeypatch.setattr(service, "normalize_items",
                        lambda items, month, out_path, model=None, month_filter=True,
                               progress=None, reference_year=None: list(evs))
    monkeypatch.setattr(service, "load_mappings", lambda: {})
    monkeypatch.setattr(service, "canonicalize", lambda e, m: e)
    monkeypatch.setattr(service, "dedup", lambda e: e)
    monkeypatch.setattr(service, "group_events", lambda e: e)
    monkeypatch.setattr(service, "convert_to_onliner", lambda e, names: e)

    req = service.RunRequest(
        file_inputs=[], url_inputs=[], months=[], month_mode="all",
        reference_year="2026", formats=["xlsx"], out_dir=tmp_path, tapeur_email="t@b.fr",
    )
    results = service.run(req)
    months = sorted(r.month for r in results)
    assert months == ["2026-11", "2026-12"]
    names = sorted(p.name for r in results for p in r.files)
    assert names == ["tapage_2026-11.xlsx", "tapage_2026-12.xlsx"]
```

Mettre à jour les tests existants qui utilisent `no_month_filter` :
- `test_run_exports_requested_formats` : `no_month_filter=False` → `month_mode="specific"` ; signature du mock `normalize_items` → ajouter `reference_year=None`.
- `test_run_threads_progress_into_normalize` : idem (`no_month_filter=False` → `month_mode="specific"` ; mock `fake_normalize(..., reference_year=None)`).

- [ ] **Step 2 : Lancer → échec**

Run: `python -m pytest tests/gui/test_service.py -q`
Expected: FAIL (`default_reference_year` absent ; `RunRequest` ne connaît pas `month_mode`).

- [ ] **Step 3 : Implémenter**

Dans `tapageur/gui/service.py`, en tête (imports) :

```python
from datetime import date
```

Ajouter le helper :

```python
def default_reference_year(today: date | None = None) -> str:
    """Année de référence pour le mode « tous les mois » : année courante,
    sauf en décembre (on prépare janvier de l'année suivante)."""
    today = today or date.today()
    return str(today.year + 1 if today.month == 12 else today.year)
```

`RunRequest` : retirer `no_month_filter`, ajouter `month_mode` / `reference_year` :

```python
@dataclass
class RunRequest:
    url_inputs: list[UrlInput]
    months: list[str]
    formats: list[str]
    out_dir: Path
    tapeur_email: str
    month_mode: str = "specific"          # "specific" | "all"
    reference_year: str = ""              # mode "all" ; vide → default_reference_year()
    append: bool = False
    text_inputs: list[TextInput] = field(default_factory=list)
    file_inputs: list = field(default_factory=list)
```

`_pipeline` : ajouter `reference_year` :

```python
def _pipeline(items, month: str, month_filter: bool, cache_out: Path,
              progress=None, reference_year: str | None = None) -> list[Event]:
    events = normalize_items(items, month, cache_out, model=None,
                             month_filter=month_filter, progress=progress,
                             reference_year=reference_year)
    events = canonicalize(events, load_mappings())
    events = dedup(events)
    events = group_events(events)
    onliner_names = [ev.festival for ev in events if ev.is_festival and ev.festival]
    events = convert_to_onliner(events, onliner_names)
    return events
```

Remplacer le corps de `run` (après `ref_cities, ref_venues = _reference_lists()`
et la collecte des items) par la logique à deux modes :

```python
    os.environ["TAPEUR_EMAIL"] = req.tapeur_email
    ref_cities, ref_venues = _reference_lists()

    _emit("Collecte des sources…")
    url_month = "" if req.month_mode == "all" else (req.months[0] if req.months else "")
    items = list(items_from_files(req.file_inputs, progress=progress))
    items += list(items_from_urls(req.url_inputs, url_month, progress=progress))
    items += list(items_from_texts(req.text_inputs, progress=progress))

    results: list[MonthResult] = []

    if req.month_mode == "all":
        ref_year = req.reference_year or default_reference_year()
        key = f"tous-{ref_year}"
        cache_out = Path("cache") / key / "gui_normalized.json"
        _emit("tous les mois : extraction…")
        events = _pipeline(items, key, False, cache_out, progress=progress,
                           reference_year=ref_year)
        from collections import defaultdict
        by_month: dict[str, list[Event]] = defaultdict(list)
        for ev in events:
            by_month[ev.date_iso[:7]].append(ev)
        for month in sorted(by_month):
            evs = by_month[month]
            _emit(f"{month} : {len(evs)} events, export…")
            files = _export(evs, req.out_dir, month, req.formats, append=req.append)
            alerts = build_alerts(evs, ref_cities, ref_venues)
            results.append(MonthResult(month=month, n_events=len(evs),
                                       files=files, alerts=alerts))
        if not by_month:
            results.append(MonthResult(month=None, n_events=0, files=[],
                                       alerts=["Aucun event extrait."]))
    else:
        for month in req.months:
            cache_out = Path("cache") / month / "gui_normalized.json"
            _emit(f"{month} : extraction…")
            events = _pipeline(items, month, True, cache_out, progress=progress)
            _emit(f"{month} : {len(events)} events, export…")
            files = _export(events, req.out_dir, month, req.formats, append=req.append)
            alerts = build_alerts(events, ref_cities, ref_venues)
            if req.append and "xlsx" not in req.formats:
                alerts.append("Append ignoré : xlsx non sélectionné.")
            results.append(MonthResult(month=month, n_events=len(events),
                                       files=files, alerts=alerts))

    _emit("Terminé.")
    return results
```

(Retirer l'ancien bloc `passes = ...` devenu inutile.)

- [ ] **Step 4 : Lancer → succès**

Run: `python -m pytest tests/gui/test_service.py -q`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add tapageur/gui/service.py tests/gui/test_service.py
git commit -m "feat(gui): service en 2 modes (un mois / tous les mois -> 1 fichier par mois)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3 : `app.py` + `index.html` — Api année de réf, payload, UI radio

**Files:**
- Modify: `tapageur/gui/app.py`, `tapageur/gui/web/index.html`
- Test: `tests/gui/test_app.py`

**Interfaces:**
- `Api.default_reference_year() -> str` (délègue à `service.default_reference_year`).
- `run_extraction` : lit `payload["month_mode"]` (défaut `"specific"`),
  `payload["reference_year"]` (défaut `""`), `payload["months"]` ; construit
  `RunRequest(month_mode=..., reference_year=..., months=...)`.

- [ ] **Step 1 : Test app (échec attendu)**

Dans `tests/gui/test_app.py`, ajouter :

```python
def test_run_extraction_passes_month_mode(monkeypatch):
    monkeypatch.setattr(app._settings, "load_settings",
                        lambda: {"anthropic_api_key": "sk-test", "tapeur_email": "t@b.fr"})
    captured = {}
    monkeypatch.setattr(app, "run", lambda req, progress=None: captured.update(req=req) or [])
    app.Api().run_extraction({
        "files": [], "urls": [], "texts": [],
        "month_mode": "all", "reference_year": "2027",
        "formats": ["xlsx"], "out_dir": ".",
    })
    assert captured["req"].month_mode == "all"
    assert captured["req"].reference_year == "2027"


def test_default_reference_year_exposed():
    val = app.Api().default_reference_year()
    assert val.isdigit() and len(val) == 4
```

Mettre à jour les tests existants de `run_extraction` qui envoient
`no_month_filter`/`file_paths` : utiliser `"files": []` et ne plus envoyer
`no_month_filter` (le défaut `month_mode="specific"` s'applique). Vérifier que
leurs assertions ne portent plus sur `req.no_month_filter`.

- [ ] **Step 2 : Lancer → échec**

Run: `python -m pytest tests/gui/test_app.py -q`
Expected: FAIL (`default_reference_year` / `month_mode` absents).

- [ ] **Step 3 : Implémenter `app.py`**

Ajouter la méthode à `Api` :

```python
    def default_reference_year(self) -> str:
        from tapageur.gui.service import default_reference_year
        return default_reference_year()
```

Dans `run_extraction`, remplacer la construction de `RunRequest` (champs mois) :

```python
        req = RunRequest(
            file_inputs=[FileInput(**f) for f in payload.get("files", [])],
            url_inputs=[UrlInput(**u) for u in payload.get("urls", [])],
            text_inputs=[TextInput(**t) for t in payload.get("texts", [])],
            months=payload.get("months", []),
            month_mode=payload.get("month_mode", "specific"),
            reference_year=payload.get("reference_year", ""),
            formats=payload.get("formats", []),
            out_dir=Path(payload.get("out_dir") or "."),
            tapeur_email=cfg.get("tapeur_email", _settings.DEFAULT_TAPEUR_EMAIL),
            append=payload.get("append", False),
        )
```

- [ ] **Step 4 : Lancer app tests → succès**

Run: `python -m pytest tests/gui/test_app.py -q`
Expected: PASS.

- [ ] **Step 5 : UI — radio parent + champ année éditable (`index.html`)**

Remplacer la section « Mois » (le `<fieldset>` contenant `#months` et
`#no-filter`) par :

```html
  <fieldset>
    <legend>Mois</legend>
    <label><input type="radio" name="month-mode" value="specific" checked> Un mois précis</label>
    <label><input type="radio" name="month-mode" value="all"> Tous les mois des sources</label>
    <div id="month-specific" style="margin-top:8px;">
      <input id="months" type="text" placeholder="2026-10, 2026-11" size="30">
    </div>
    <div id="month-all" style="margin-top:8px; display:none;">
      <label>Année de référence <input id="reference-year" type="text" size="6"></label>
    </div>
  </fieldset>
```

Ajouter le JS (section settings ou près du run) : bascule d'affichage +
pré-remplissage de l'année.

```javascript
function monthMode() {
  const r = document.querySelector('input[name="month-mode"]:checked');
  return r ? r.value : 'specific';
}
function syncMonthMode() {
  const all = monthMode() === 'all';
  document.getElementById('month-specific').style.display = all ? 'none' : '';
  document.getElementById('month-all').style.display = all ? '' : 'none';
}
document.querySelectorAll('input[name="month-mode"]').forEach(
  r => r.addEventListener('change', syncMonthMode));
```

Dans `loadSettings()` (ou au `pywebviewready`), pré-remplir l'année et
synchroniser l'affichage :

```javascript
  document.getElementById('reference-year').value = await api().default_reference_year();
  syncMonthMode();
```

- [ ] **Step 6 : UI — garde + payload (`index.html`)**

Dans le handler `#run`, remplacer la lecture mois/validation et le payload :

```javascript
  const mode = monthMode();
  const months = document.getElementById('months').value.split(',').map(s => s.trim()).filter(Boolean);
  const refYear = document.getElementById('reference-year').value.trim();
  if (mode === 'specific') {
    if (months.length === 0) { summary.textContent = 'Aucun mois ciblé — saisis au moins un mois.'; return; }
    if (!months.every(m => /^\d{4}-\d{2}$/.test(m))) { summary.textContent = 'Mois invalide : format AAAA-MM (ex. 2026-11).'; return; }
  } else {
    if (!/^\d{4}$/.test(refYear)) { summary.textContent = 'Année de référence invalide : format AAAA (ex. 2026).'; return; }
  }
```

Dans l'objet `payload`, remplacer `months`/`no_month_filter` par :

```javascript
    months: months,
    month_mode: mode,
    reference_year: refYear,
```

- [ ] **Step 7 : Suite complète**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 8 : Vérification manuelle (app)**

Lancer `tapageur-gui` :
- « Un mois précis » : champ mois visible, « tous » caché ; extraction d'un mois
  → 1 fichier (comme avant).
- « Tous les mois des sources » : champ mois caché, année de référence visible et
  pré-remplie (année courante, ou +1 en décembre), éditable ; une extraction sur
  des sources multi-mois → **un fichier par mois** ; une date sans année tombe
  dans l'année de référence.

- [ ] **Step 9 : Commit**

```bash
git add tapageur/gui/app.py tapageur/gui/web/index.html tests/gui/test_app.py
git commit -m "feat(gui): UI sélection du mois (radio parent + année de référence éditable)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes de revue (hors tâches)

- Le rendu CSS/JS de l'UI (Task 3) n'a pas de test unitaire → vérif manuelle (Step 8).
- Mode « all » : tous les mois trouvés produisent un fichier (y compris des mois
  lointains d'une brochure de saison) — voulu (cf. spec §6).
- `append` en mode « all » s'applique par fichier mensuel (même sémantique).
