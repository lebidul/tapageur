# Mode debug — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Case « mode debug » qui sauve config + logs à chaque run, et bouton « Importer une config » qui repeuple l'UI.

**Architecture:** Côté Python (`app.py`), `run_extraction` capture stdout via un tee quand `debug` est vrai et écrit `config_<ts>.json` + `run_<ts>.log` dans `<out_dir>/debug/` ; `import_config` lit un JSON. Côté UI, une case + un bouton + `applyConfig` qui repeuple les champs.

**Tech Stack:** Python 3.11+, pytest, pywebview (HTML/JS).

## Global Constraints

- La **clé API** n'est jamais écrite dans la config exportée, ni touchée à l'import.
- Logs = **stdout complet** du run (tee), écrits même en cas d'erreur.
- Emplacement : `<out_dir>/debug/`. Timestamp `YYYYMMDD_HHMMSS` partagé config+log.
- Contenu JS dynamique via DOM/`.value`/`.checked` (jamais `innerHTML` avec données).
- Message de commit terminé par : `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1 : `app.py` — helpers + capture + import

**Files:**
- Modify: `tapageur/gui/app.py`
- Test: `tests/gui/test_app.py`

**Interfaces:**
- `_debug_config(payload: dict) -> dict` : payload sans `api_key` ni `debug`.
- `_read_config(path) -> dict` : JSON → dict ; erreur → `{}`.
- `_tee_stdout()` : context manager, remplace `sys.stdout` par un tee, yield le buffer.
- `_write_debug(out_dir, ts, config, log)` : écrit les 2 fichiers dans `debug/`.
- `Api.import_config() -> dict` : dialogue fichier → `_read_config`.
- `run_extraction` : si `payload["debug"]`, wrap l'exécution dans `_tee_stdout` et écrit config+log.

- [ ] **Step 1 : Tests des helpers (échec attendu)**

Ajouter dans `tests/gui/test_app.py` :

```python
def test_debug_config_excludes_api_key():
    payload = {"api_key": "sk-x", "debug": True, "files": [], "months": ["2026-11"],
               "month_mode": "specific", "formats": ["xlsx"], "out_dir": "."}
    cfg = app._debug_config(payload)
    assert "api_key" not in cfg
    assert "debug" not in cfg
    assert cfg["months"] == ["2026-11"]
    assert cfg["month_mode"] == "specific"


def test_read_config_valid_and_invalid(tmp_path):
    good = tmp_path / "c.json"
    good.write_text('{"months": ["2026-11"], "formats": ["xlsx"]}', encoding="utf-8")
    assert app._read_config(good)["months"] == ["2026-11"]
    bad = tmp_path / "bad.json"
    bad.write_text("pas du json", encoding="utf-8")
    assert app._read_config(bad) == {}
    assert app._read_config(tmp_path / "absent.json") == {}
```

- [ ] **Step 2 : Lancer → échec**

Run: `python -m pytest tests/gui/test_app.py -k "debug_config or read_config" -q`
Expected: FAIL (helpers absents).

- [ ] **Step 3 : Implémenter les helpers dans `app.py`**

Ajouter aux imports (en tête) :

```python
import io
import sys
from contextlib import contextmanager
from datetime import datetime
```

Ajouter (niveau module, après `_WEB = ...`) :

```python
def _debug_config(payload: dict) -> dict:
    """Config rejouable : le payload sans secret ni flag debug."""
    return {k: v for k, v in payload.items() if k not in ("api_key", "debug")}


def _read_config(path) -> dict:
    """Lit un fichier config JSON → dict ; {} si absent / illisible."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@contextmanager
def _tee_stdout():
    """Remplace sys.stdout par un tee (terminal réel + buffer). isatty()=False
    pour que Rich n'émette pas de codes couleur dans le log."""
    buf = io.StringIO()
    orig = sys.stdout

    class _Tee:
        def write(self, s):
            orig.write(s)
            buf.write(s)
            return len(s)
        def flush(self):
            orig.flush()
        def isatty(self):
            return False
        def __getattr__(self, name):
            return getattr(orig, name)

    sys.stdout = _Tee()
    try:
        yield buf
    finally:
        sys.stdout = orig


def _write_debug(out_dir, ts: str, config: dict, log: str) -> None:
    d = Path(out_dir) / "debug"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"config_{ts}.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    (d / f"run_{ts}.log").write_text(log, encoding="utf-8")
```

- [ ] **Step 4 : Lancer → succès**

Run: `python -m pytest tests/gui/test_app.py -k "debug_config or read_config" -q`
Expected: PASS.

- [ ] **Step 5 : `import_config` + capture dans `run_extraction`**

Ajouter la méthode à `Api` (près de `choose_files`) :

```python
    def import_config(self) -> dict:
        res = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=("Config (*.json)", "Tous (*.*)"),
        )
        if not res:
            return {}
        return _read_config(res[0])
```

Dans `run_extraction`, repérer la fin (le bloc `try: results = run(...)` jusqu'au
`return {...}`) et le remplacer par une exécution factorisée + le wrap debug :

```python
        def _do_run() -> dict:
            try:
                results = run(req, progress=progress)
            except Exception as e:  # remonte l'erreur à l'UI au lieu de crasher
                return {"error": str(e)}
            return {"results": [
                {"month": r.month, "n_events": r.n_events,
                 "files": [str(p) for p in r.files], "alerts": r.alerts}
                for r in results
            ]}

        if payload.get("debug"):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            with _tee_stdout() as buf:
                out = _do_run()
            try:
                _write_debug(payload.get("out_dir") or ".", ts,
                             _debug_config(payload), buf.getvalue())
            except OSError:
                pass  # l'échec d'écriture debug ne doit pas masquer le résultat
            return out
        return _do_run()
```

- [ ] **Step 6 : Suite app**

Run: `python -m pytest tests/gui/test_app.py -q`
Expected: PASS.

- [ ] **Step 7 : Commit**

```bash
git add tapageur/gui/app.py tests/gui/test_app.py
git commit -m "feat(gui): mode debug côté Python (capture logs + export/import config)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2 : `index.html` — case debug, bouton import, applyConfig

**Files:**
- Modify: `tapageur/gui/web/index.html`

**Interfaces:**
- Consomme `api().import_config()` (Task 1) ; `payload.debug`.
- Pas de test unitaire (UI) : vérif manuelle en fin de tâche.

- [ ] **Step 1 : Case « mode debug » + bouton import (section Réglages)**

Dans le `<fieldset>` Réglages (près du bouton « Enregistrer les réglages »),
ajouter :

```html
    <div style="margin-top:8px;">
      <label><input id="debug-mode" type="checkbox"> mode debug (sauver config + logs dans debug/)</label>
      <button id="import-config" type="button" style="margin-left:12px;">Importer une config</button>
    </div>
```

- [ ] **Step 2 : `debug` dans le payload**

Dans l'objet `payload` du handler `#run`, ajouter :

```javascript
    debug: document.getElementById('debug-mode').checked,
```

- [ ] **Step 3 : import + applyConfig (JS)**

Ajouter (après `loadSettings` / les helpers de mois) :

```javascript
async function importConfig() {
  const cfg = await api().import_config();
  if (cfg && Object.keys(cfg).length) applyConfig(cfg);
}
document.getElementById('import-config').addEventListener('click', importConfig);

function applyConfig(cfg) {
  // fichiers
  files = (cfg.files || []).map(f => ({
    path: f.path || "", venue: f.venue || "", info_orga: f.info_orga || "",
    is_festival: !!f.is_festival,
  }));
  renderFiles();
  // urls
  const urlsBox = document.getElementById('urls'); urlsBox.innerHTML = '';
  (cfg.urls || []).forEach(u => {
    addUrlRow();
    const row = urlsBox.lastElementChild;
    row.querySelector('input[type=text]').value = u.url || "";
    row.querySelector('.follow').checked = !!u.follow_links;
    row.querySelector('.fest').checked = !!u.is_festival;
    row.querySelector('.u-venue').value = u.venue || "";
    row.querySelector('.u-orga').value = u.info_orga || "";
  });
  // textes
  const textsBox = document.getElementById('texts'); textsBox.innerHTML = '';
  (cfg.texts || []).forEach(t => {
    addTextRow();
    const row = textsBox.lastElementChild;
    row.querySelector('.tx-text').value = t.text || "";
    row.querySelector('.tx-venue').value = t.venue || "";
    row.querySelector('.tx-orga').value = t.info_orga || "";
    row.querySelector('.tx-fest').checked = !!t.is_festival;
  });
  // mois
  document.getElementById('months').value = (cfg.months || []).join(', ');
  const mode = cfg.month_mode || 'specific';
  const radio = document.querySelector('input[name="month-mode"][value="' + mode + '"]');
  if (radio) radio.checked = true;
  if (cfg.reference_year) document.getElementById('reference-year').value = cfg.reference_year;
  syncMonthMode();
  // formats
  document.querySelectorAll('.fmt').forEach(c => { c.checked = (cfg.formats || []).includes(c.value); });
  // dossier + append
  if (cfg.out_dir) { outDir = cfg.out_dir; document.getElementById('out-dir').textContent = outDir; }
  document.getElementById('append').checked = !!cfg.append;
}
```

(Note sécurité : `urlsBox.innerHTML = ''` / `textsBox.innerHTML = ''` vident avec
une chaîne statique ; toutes les valeurs de `cfg` sont posées via `.value` /
`.checked`, jamais injectées en HTML.)

- [ ] **Step 4 : Non-régression (suite complète)**

Run: `python -m pytest -q`
Expected: PASS (le Python n'a pas changé ici).

- [ ] **Step 5 : Vérification manuelle (app)**

Lancer `tapageur-gui` :
- Cocher « mode debug », lancer une passe → un dossier `debug/` apparaît dans le
  dossier de sortie, avec `config_<ts>.json` (sans clé API) + `run_<ts>.log`
  (contenant le par-item, cache, warnings — comme le terminal).
- « Importer une config » → choisir un `config_*.json` → les champs se
  repeuplent (fichiers, URLs, textes, mois/mode/année, formats, dossier,
  append) ; la clé API reste inchangée.
- Lancer après import → même passe.

- [ ] **Step 6 : Commit**

```bash
git add tapageur/gui/web/index.html
git commit -m "feat(gui): UI mode debug (case + import config qui repeuple l'UI)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes de revue (hors tâches)

- Le log peut perdre la couleur Rich (isatty=False volontaire → log propre) ;
  le terminal réel perd aussi la couleur pendant un run en mode debug. Acceptable.
- La config référence les fichiers par chemin disque : un import sur une autre
  machine (ou fichiers déplacés) laisse des chemins invalides — connu, hors périmètre.
