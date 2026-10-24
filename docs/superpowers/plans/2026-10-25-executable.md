# Exécutable — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exe Windows one-file de `tapageur-gui`, URLs via WebView2 (sans Playwright), publié en Release GitHub sur tag `vX.Y.Z`.

**Architecture:** A) un hook `_BROWSER_FETCH` dans `web.py` permet au GUI d'injecter une récupération d'URL via le navigateur pywebview embarqué (CLI inchangé). B) un `.spec` PyInstaller (excludes libs lourdes + data embarquée) et un workflow GitHub Actions construisent et publient l'exe.

**Tech Stack:** Python 3.11, pywebview (WebView2), PyInstaller, GitHub Actions.

## Global Constraints

- CLI inchangé : sans hook, `_do_fetch(needs_browser=True)` garde Playwright.
- Exe one-file, `console=False`, Windows (`windows-latest`).
- Exclure du bundle : `paddleocr`, `pandas`, `gspread`, `msal`, `extract_msg`, `playwright`, `playwright_stealth`.
- Embarquer `tapageur/gui/web/index.html` et `tapageur/gui/assets/template.xlsx` à un chemin qui préserve `Path(__file__).parent/…`.
- Message de commit terminé par : `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1 : `web.py` — hook `_BROWSER_FETCH`

**Files:**
- Modify: `tapageur/connectors/web.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Module : `_BROWSER_FETCH: "Callable[[str], str] | None" = None`.
- `_do_fetch(url, needs_browser=False)` : si `needs_browser` et `_BROWSER_FETCH`
  défini → `return _BROWSER_FETCH(url)` ; sinon inchangé.

- [ ] **Step 1 : Test du hook (échec attendu)**

Ajouter dans `tests/test_web.py` :

```python
def test_do_fetch_uses_browser_hook(monkeypatch):
    from tapageur.connectors import web
    monkeypatch.setattr(web, "_BROWSER_FETCH", lambda url: f"<html>{url}</html>")
    out = web._do_fetch("https://exemple.fr/agenda", needs_browser=True)
    assert out == "<html>https://exemple.fr/agenda</html>"


def test_do_fetch_requests_path_without_hook(monkeypatch):
    from tapageur.connectors import web
    monkeypatch.setattr(web, "_BROWSER_FETCH", None)
    class _Resp:
        text = "<html>requests</html>"
        def raise_for_status(self): pass
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _Resp())
    out = web._do_fetch("https://exemple.fr/", needs_browser=False)
    assert out == "<html>requests</html>"
```

- [ ] **Step 2 : Lancer → échec**

Run: `python -m pytest tests/test_web.py -k "browser_hook or requests_path_without_hook" -q`
Expected: FAIL (`_BROWSER_FETCH` n'existe pas).

- [ ] **Step 3 : Implémenter le hook**

Dans `tapageur/connectors/web.py`, ajouter au niveau module (près des autres
constantes, ex. après `_FETCH_CACHE`) :

```python
# Hook optionnel : le GUI l'installe pour récupérer les pages via le navigateur
# embarqué (WebView2) au lieu de Playwright. None = comportement CLI (Playwright).
_BROWSER_FETCH = None  # type: "Callable[[str], str] | None"
```

Dans `_do_fetch`, en tête de la branche `if needs_browser:` :

```python
    if needs_browser:
        if _BROWSER_FETCH is not None:
            return _BROWSER_FETCH(url)
        from playwright.sync_api import sync_playwright
        ...  # (inchangé)
```

- [ ] **Step 4 : Lancer → succès**

Run: `python -m pytest tests/test_web.py -k "browser_hook or requests_path_without_hook" -q`
Expected: PASS.

- [ ] **Step 5 : Suite web**

Run: `python -m pytest tests/test_web.py -q`
Expected: PASS.

- [ ] **Step 6 : Commit**

```bash
git add tapageur/connectors/web.py tests/test_web.py
git commit -m "feat(web): hook _BROWSER_FETCH (récup URL injectable, CLI inchangé)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2 : `app.py` — `_webview_fetch` + installation du hook

**Files:**
- Modify: `tapageur/gui/app.py`
- (Pas de test unitaire — vérif manuelle.)

**Interfaces:**
- `_webview_fetch(url, settle_ms=5000, timeout=60.0) -> str` (via pywebview).
- `main()` installe `web._BROWSER_FETCH = _webview_fetch`.

- [ ] **Step 1 : Implémenter `_webview_fetch`**

Ajouter les imports nécessaires (`threading`, `time`) et, au niveau module :

```python
def _webview_fetch(url: str, settle_ms: int = 5000, timeout: float = 60.0) -> str:
    """Récupère le HTML d'une URL via une fenêtre pywebview cachée (WebView2).
    Remplace Playwright dans le GUI. Renvoie '' en cas d'échec/timeout."""
    import time
    import threading
    result: dict[str, str] = {}
    done = threading.Event()
    win = webview.create_window("fetch", url, hidden=True)

    def _on_loaded():
        try:
            time.sleep(settle_ms / 1000)  # laisse le JS se stabiliser
            result["html"] = win.evaluate_js(
                "document.documentElement.outerHTML") or ""
        except Exception:
            result["html"] = ""
        finally:
            done.set()

    win.events.loaded += _on_loaded
    done.wait(timeout)
    try:
        win.destroy()
    except Exception:
        pass
    return result.get("html", "")
```

- [ ] **Step 2 : Installer le hook dans `main()`**

Dans `main()`, avant `webview.start()` :

```python
    from tapageur.connectors import web as _web
    _web._BROWSER_FETCH = _webview_fetch
```

- [ ] **Step 3 : Non-régression (suite complète)**

Run: `python -m pytest -q`
Expected: PASS (le pipeline n'est pas modifié ; seul un hook est ajouté).

- [ ] **Step 4 : Vérification manuelle (app)**

Lancer `tapageur-gui`, ajouter une URL d'agenda rendue en JS (sans case festival),
mois adéquat → l'extraction ressort des events, **sans** Playwright. (Les sites
anti-bot Cloudflare peuvent ne rien ressortir — attendu.)

- [ ] **Step 5 : Commit**

```bash
git add tapageur/gui/app.py
git commit -m "feat(gui): récup URL via WebView2 embarqué (installe _BROWSER_FETCH)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3 : Packaging — `tapageur.spec` + workflow Release

**Files:**
- Create: `tapageur.spec`
- Create: `.github/workflows/release.yml`

**Interfaces:**
- `pyinstaller tapageur.spec` → `dist/tapageur-gui.exe` (one-file).
- Tag `v*` → build windows → asset de Release.

- [ ] **Step 1 : Écrire `tapageur.spec`**

Créer `tapageur.spec` à la racine :

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ("tapageur/gui/web/index.html", "tapageur/gui/web"),
    ("tapageur/gui/assets/template.xlsx", "tapageur/gui/assets"),
]
binaries = []
hiddenimports = []
# Collecter proprement les paquets à binaires / data cachés.
for pkg in ("webview", "pypdfium2", "pdfplumber", "anthropic"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

excludes = [
    "paddleocr", "paddle", "pandas", "gspread", "msal",
    "extract_msg", "playwright", "playwright_stealth",
]

a = Analysis(
    ["tapageur/gui/app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="tapageur-gui",
    console=False,
    onefile=True,
    upx=False,
)
```

- [ ] **Step 2 : Build local (vérif manuelle)**

```bash
pip install pyinstaller
pyinstaller tapageur.spec
```

`dist/tapageur-gui.exe` doit se lancer : fichiers PDF/image + texte collé OK ;
une URL simple OK ; `index.html` et `template.xlsx` bien trouvés (sinon, ajuster
le chemin figé — voir Note de revue). En cas d'erreur d'import au lancement,
ajouter le module manquant à `hiddenimports`.

- [ ] **Step 3 : Écrire le workflow Release**

Créer `.github/workflows/release.yml` :

```yaml
name: release
on:
  push:
    tags: ["v*"]
permissions:
  contents: write
jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install
        run: pip install .[gui] pyinstaller
      - name: Build
        run: pyinstaller tapageur.spec
      - name: Rename asset
        run: Copy-Item dist/tapageur-gui.exe "dist/tapageur-gui-${{ github.ref_name }}.exe"
        shell: pwsh
      - name: Release
        uses: softprops/action-gh-release@v2
        with:
          files: dist/tapageur-gui-${{ github.ref_name }}.exe
```

- [ ] **Step 4 : Commit**

```bash
git add tapageur.spec .github/workflows/release.yml
git commit -m "build: PyInstaller one-file + workflow Release sur tag

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 5 : Vérification (CI, après merge)**

Pousser un tag de test (ex. `v0.1.0-rc1`) → l'action build sur windows-latest →
la Release reçoit `tapageur-gui-v0.1.0-rc1.exe`. Télécharger + double-clic sur une
machine Windows propre : l'app démarre, fichiers/texte/URL OK.

---

## Notes de revue (hors tâches)

- **Chemin figé** : si l'exe ne trouve pas `index.html`/`template.xlsx`,
  remplacer `Path(__file__).parent` dans `app._WEB` et
  `export_xlsx.TEMPLATE_PATH` par un helper :
  `Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "tapageur/gui/…"`.
- Le `.spec` est un point de départ : les `hiddenimports` / `collect_all`
  peuvent devoir être ajustés selon les erreurs réelles de build (backend
  pywebview edgechromium / pythonnet `clr`).
- Risque WebView2 (Task 2) : si `evaluate_js` renvoie du HTML incomplet pour
  certains sites, augmenter `settle_ms`. Anti-bot : hors périmètre.
