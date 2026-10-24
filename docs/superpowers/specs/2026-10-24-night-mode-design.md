# Night mode (thème sombre) — Design

**Date :** 2026-10-24
**Statut :** validé (brainstorming), prêt pour plan
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Ajouter un thème sombre (gris) à l'app `tapageur-gui`, avec un bouton de
bascule clair/sombre dans l'UI. **Sombre par défaut**, préférence **persistée**
entre deux lancements.

## 2. État actuel

- `tapageur/gui/web/index.html` : thème clair, déjà piloté en partie par des
  variables CSS `:root` (`--accent`, `--bg`, `--card`, `--panel-bg`,
  `--border`, …). Quelques couleurs restent **en dur** : texte du body
  (`#1a202c`), zone de drop (`#888` / `#666`), `#progress` (`#4a5568`), fond
  des boutons (`#fff`).
- `tapageur/gui/settings.py` : réglages persistés (JSON par OS). **`save_settings`
  fait `{**_DEFAULTS, **data}` puis réécrit tout** → il ne fusionne pas avec le
  fichier existant : sauver un sous-ensemble de clés écrase les autres.
- `index.html` charge les réglages au `pywebviewready` via `api().get_settings()`.

## 3. Décisions (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Bascule** | Bouton ☀/☾ dans l'en-tête ; clic = clair↔sombre. |
| **Défaut** | **Sombre.** `<html data-theme="dark">` au départ (1er rendu déjà sombre). |
| **Persistance** | **Oui**, via les réglages existants (clé `theme`). |
| **Teinte** | Gris (pas noir pur). |

## 4. Fix préalable : `save_settings` doit fusionner

`save_settings(data)` doit charger l'existant puis le mettre à jour avec `data`,
au lieu de repartir des seuls défauts. Sinon `save_settings({"theme": …})`
effacerait `anthropic_api_key` / `tapeur_email` (et inversement, le save des
réglages effacerait le thème).

```python
def save_settings(data: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    merged = load_settings()      # défauts + fichier existant
    merged.update(data)           # n'écrase que les clés fournies
    p.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
```

Ajouter `"theme": "dark"` à `_DEFAULTS`.

## 5. CSS : variabilisation + thème sombre

**Variabiliser** les couleurs en dur en nouvelles variables `:root` (valeurs
claires actuelles conservées) :
- `--text: #1a202c` (body)
- `--muted: #4a5568` (#progress)
- `--drop-border: #888`, `--drop-text: #666` (#drop)
- `--button-bg: #ffffff` (boutons)

Puis les utiliser dans `body` (color), `#drop`, `#progress`, `button`.

**Thème sombre** via sélecteur d'attribut `[data-theme="dark"]` (overrides) :

| Variable | Clair (`:root`) | Sombre (`[data-theme="dark"]`) |
|----------|-----------------|-------------------------------|
| `--bg` | `#eef2f7` | `#1e2227` |
| `--card` | `#ffffff` | `#272c33` |
| `--panel-bg` | `#f6f6f6` | `#22262c` |
| `--border` | `#cbd5e0` | `#3a4049` |
| `--text` | `#1a202c` | `#e4e7eb` |
| `--muted` | `#4a5568` | `#a0aec0` |
| `--drop-border` | `#888` | `#5a616b` |
| `--drop-text` | `#666` | `#a0aec0` |
| `--button-bg` | `#ffffff` | `#2f353d` |
| `--accent` | `#2b6cb0` | `#63b3ed` |
| `--accent-dark` | `#22508a` | `#4a90d9` |
| `--accent-contrast` | `#ffffff` | `#1a202c` |
| `--warning` | `#a4400f` | `#fc8181` |

`<html lang="fr" data-theme="dark">` pour démarrer en sombre.

## 6. Bascule (UI + JS)

- Bouton `#theme-toggle` dans l'en-tête (près du `<h1>`), libellé ☀ (en sombre,
  propose de passer en clair) / ☾ (en clair). Rendu via DOM/`textContent`
  (jamais d'`innerHTML` dynamique, cohérent avec la sécurité du webview).
- `applyTheme(theme)` : `document.documentElement.dataset.theme = theme` et met
  à jour l'icône du bouton.
- Au `pywebviewready` / dans `loadSettings()` : `applyTheme(cfg.theme || "dark")`.
- Clic sur le bouton : bascule la valeur, `applyTheme(...)`, puis
  `api().save_settings({theme})` (fusion → ne touche pas les autres réglages).

## 7. Tests

- `settings.save_settings` fusionne :
  - sauver `{"theme": "light"}` sur un fichier ayant `anthropic_api_key="sk-x"`
    conserve la clé API ;
  - sauver `{"anthropic_api_key": "sk-y"}` conserve un `theme` déjà présent.
- `settings.load_settings` : défaut `theme == "dark"` quand le fichier est absent.

(Le rendu CSS et le bouton ne sont pas testés en unitaire — vérif manuelle dans
l'app, comme pour le reste de l'UI.)

## 8. Hors périmètre

- Suivre le thème de l'OS (`prefers-color-scheme`).
- Transitions animées lors de la bascule.
- Thèmes multiples / personnalisables.
