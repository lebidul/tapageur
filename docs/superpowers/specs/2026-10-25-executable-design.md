# Exécutable téléchargeable (URLs via WebView2 + packaging) — Design

**Date :** 2026-10-25
**Statut :** validé (brainstorming), prêt pour plan
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Distribuer `tapageur-gui` comme **exécutable Windows one-file** téléchargeable,
publié en **GitHub Release à chaque tag `vX.Y.Z`**. Pour rester léger et
autonome, les URLs sont récupérées via le **navigateur embarqué (WebView2)** au
lieu de Playwright+Chromium.

## 2. État actuel

- `web._do_fetch(url, needs_browser=True)` utilise **Playwright/Chromium**
  (`web.py:330-357`). Le GUI passe toujours `needs_browser=True`
  (`inputs._url_to_site`). Fichiers (PDF/image) et texte collé n'utilisent PAS
  de navigateur.
- Libs lourdes du `pyproject` **non importées** par le chemin GUI :
  `paddleocr`, `pandas`, `gspread`, `msal`, `extract_msg` (vérifié).
- `app._WEB = Path(__file__).parent/"web"/"index.html"` ;
  `export_xlsx.TEMPLATE_PATH = Path(__file__).parent/"assets"/"template.xlsx"`.
- Pas de `.github/` (aucune CI).

## 3. Décisions (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Distribution** | Desktop (pas de web app) ; exe **one-file** Windows. |
| **URLs** | Récupérées via **WebView2 embarqué** (retire Playwright du chemin GUI). |
| **Trigger publication** | Tag `vX.Y.Z` → build `windows-latest` → asset de Release. |
| **Anti-bot (Cloudflare)** | Hors portée dans l'exe (WebView2 simple, sans stealth). |

## 4. Partie A — URLs via le navigateur embarqué

### `tapageur/connectors/web.py`
- Hook module : `_BROWSER_FETCH: Callable[[str], str] | None = None`.
- `_do_fetch(url, needs_browser=False)` : si `needs_browser` **et**
  `_BROWSER_FETCH` défini → `return _BROWSER_FETCH(url)`. Sinon, comportement
  actuel (Playwright si `needs_browser`, requests sinon). → **CLI inchangé**
  (hook non défini → Playwright).

### `tapageur/gui/app.py`
- `_webview_fetch(url: str, settle_ms: int = 5000, timeout: float = 60) -> str` :
  ouvre une fenêtre pywebview **cachée** sur `url`
  (`webview.create_window(..., hidden=True)`), attend l'événement `loaded`
  (via `window.events.loaded` + `threading.Event`), laisse `settle_ms` au JS,
  récupère `window.evaluate_js("document.documentElement.outerHTML")`, ferme la
  fenêtre (`window.destroy()`), renvoie le HTML (ou `""` si timeout/erreur).
- Dans `main()` (avant `webview.start()` ou juste après création) : installer le
  hook `web._BROWSER_FETCH = _webview_fetch` pour que tout le pipeline GUI passe
  par WebView2.
- Concurrence : `_webview_fetch` est appelé depuis le thread d'extraction
  (hors UI) ; `create_window` / `evaluate_js` / `destroy` sont appelables après
  `start()`. Le `loaded` + `threading.Event(timeout)` sécurise l'attente.

### Vérif (manuelle)
- Dans l'app, une URL JS (ex. un agenda rendu côté client) ressort ses events,
  **sans** Playwright (désinstallé ou non appelé).

## 5. Partie B — Packaging one-file + CI

### `tapageur.spec` (PyInstaller, racine du repo)
- Entrée : `tapageur/gui/app.py`, `name="tapageur-gui"`, `console=False`,
  `onefile`.
- `datas` : `tapageur/gui/web/index.html` → `tapageur/gui/web` ;
  `tapageur/gui/assets/template.xlsx` → `tapageur/gui/assets`.
- `excludes` : `paddleocr`, `pandas`, `gspread`, `msal`, `extract_msg`,
  `playwright`, `playwright_stealth` (+ transitifs lourds : `paddle`,
  `paddlepaddle` si présents).
- Hidden imports éventuels (pywebview backend edgechromium : `webview.platforms.edgechromium`,
  `clr` / pythonnet) — à ajuster selon l'erreur de build.

### Chemin figé
- Vérifier que `Path(__file__).parent/…` résout dans le bundle (PyInstaller
  place les `datas` sous le même arbre de package). Si KO : fallback
  `getattr(sys, "_MEIPASS", ...)` dans `app._WEB` et `export_xlsx.TEMPLATE_PATH`
  (helper `_resource(relpath)`).

### `.github/workflows/release.yml`
- `on: push: tags: ['v*']`.
- Job `windows-latest` : `actions/setup-python` (3.11) → `pip install .[gui]
  pyinstaller` → `pyinstaller tapageur.spec` → upload
  `dist/tapageur-gui.exe` en asset via `softprops/action-gh-release` (ou
  `gh release create/upload`).
- Nom de l'asset : `tapageur-gui-<tag>.exe`.

### Vérif (locale + CI)
- Build local : `pyinstaller tapageur.spec` → `dist/tapageur-gui.exe` se lance,
  fichiers + texte + URL OK.
- Push d'un tag de test `vX.Y.Z-rc` → la Release reçoit l'exe → téléchargement +
  double-clic sur une machine propre.

## 6. Tests

- `web._do_fetch` : avec `_BROWSER_FETCH` défini (mock renvoyant un HTML) et
  `needs_browser=True` → retourne le HTML du hook sans toucher Playwright ;
  avec hook `None` et `needs_browser=False` → chemin requests inchangé.
- (Le `_webview_fetch` réel, le build PyInstaller et le workflow : vérif
  manuelle / CI — non unitaires.)

## 7. Hors périmètre

- macOS / Linux ; bundler Chromium ; sites anti-bot dans l'exe ; auto-update ;
  icône personnalisée ; signature du binaire.
