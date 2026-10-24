# Mode debug (sauver / importer config + logs) — Design

**Date :** 2026-10-25
**Statut :** validé (brainstorming), prêt pour plan
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Faciliter le diagnostic et le rejeu d'une extraction :
- **Sauver** automatiquement la **config** d'une passe + ses **logs** (quand le
  « mode debug » est activé).
- **Importer** un fichier config pour rejouer une passe (repeupler l'UI).

## 2. État actuel

- `app.Api.run_extraction(payload)` reçoit le payload de l'UI :
  `files`, `urls`, `texts`, `months`, `month_mode`, `reference_year`,
  `formats`, `out_dir`, `append`, `api_key`, `tapeur_email`.
- Les logs d'un run partent sur **stdout** (terminal) : `print()` pour les
  warnings (`[warn] event … invalide`), Rich `Console()` (créé dans
  `normalize_items`) pour le par-item (`[1/3] …`), `cache: n hit, m miss`,
  `[onliner] …`. L'UI ne reçoit qu'un sous-ensemble via `window.onProgress`.
- `choose_files` / `choose_output_dir` utilisent `webview…create_file_dialog`.

## 3. Décisions (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Déclencheur** | Case **« mode debug »** : auto-save config + logs à chaque run. |
| **Logs** | **Terminal complet** (capture de stdout : par-item, cache, warnings, onliner). |
| **Import** | **Repeupler l'UI** (revue puis Lancer), jamais la clé API. |
| **Emplacement** | Sous-dossier `debug/` du dossier de sortie. |
| **Clé API** | **Exclue** de la config exportée. |

## 4. Changements

### `tapageur/gui/app.py`
- Helper testable `_debug_config(payload: dict) -> dict` : copie du payload
  **sans** `api_key` (ni `debug`). Sert de contenu `config_<ts>.json`.
- `run_extraction` :
  - lire `debug = bool(payload.get("debug"))`.
  - si `debug` : capturer stdout pendant `run(req, …)` via un **tee**
    (écrit sur le stdout réel ET dans un buffer), puis écrire dans
    `<out_dir>/debug/` : `config_<ts>.json` (= `_debug_config(payload)`) et
    `run_<ts>.log` (= buffer). `<ts>` = `YYYYMMDD_HHMMSS`, partagé par les 2
    fichiers. Écriture dans un `finally` (logs utiles même en cas d'erreur).
  - si `debug` est faux : comportement inchangé.
- Helper `_tee_stdout()` (context manager) : remplace `sys.stdout` par un objet
  qui écrit sur l'ancien stdout + un `io.StringIO`, restaure à la sortie, et
  expose le texte capturé.
- `Api.import_config() -> dict` : ouvre un `create_file_dialog(OPEN_DIALOG)`
  filtré `*.json` ; lit le fichier ; renvoie le dict parsé (ou `{}` si annulé /
  illisible). Lecture/parsing déportée dans un helper testable
  `_read_config(path) -> dict`.

### `tapageur/gui/web/index.html`
- Case **« mode debug »** (section Réglages) ; bouton **« Importer une config »**.
- `payload.debug = document.getElementById('debug-mode').checked`.
- `importConfig()` : `const cfg = await api().import_config(); if (cfg && Object.keys(cfg).length) applyConfig(cfg);`
- `applyConfig(cfg)` : repeuple les champs depuis le dict —
  - `files` → remplace le tableau `files` + `renderFiles()` ;
  - `urls` → vider `#urls`, `addUrlRow()` par entrée + remplir ses champs ;
  - `texts` → vider `#texts`, `addTextRow()` par entrée + remplir ;
  - `months` → `#months` ; `month_mode` → radio + `syncMonthMode()` ;
    `reference_year` → `#reference-year` ;
  - `formats` → cocher les `.fmt` correspondants ;
  - `out_dir` → `outDir` + affichage ; `append` → `#append`.
  - **Ne touche jamais** `#api-key`.

## 5. Tests

- `_debug_config` : retire `api_key` (et `debug`) ; conserve
  `files`/`urls`/`texts`/`months`/`month_mode`/`reference_year`/`formats`/
  `out_dir`/`append`.
- `_read_config(path)` : lit un JSON valide → dict ; fichier absent / JSON
  invalide → `{}`.
- (Rendu UI `applyConfig`, bouton, case, capture stdout : vérif manuelle.)

## 6. Hors périmètre

- Versionner / comparer (diff) des configs.
- Rejeu headless (sans UI).
- Capturer les logs quand « mode debug » est décoché.
- Chiffrer et inclure la clé API dans la config.
