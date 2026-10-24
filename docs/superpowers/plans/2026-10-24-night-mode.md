# Night mode — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thème sombre gris par défaut avec bascule ☀/☾ persistée dans `tapageur-gui`.

**Architecture:** `save_settings` devient fusionnant (pré-requis pour persister le thème sans écraser les autres réglages) + clé `theme` par défaut `"dark"`. Côté UI : variables CSS complètes + bloc `[data-theme="dark"]`, bouton de bascule qui applique le thème et le sauvegarde.

**Tech Stack:** Python 3.11+, pytest, pywebview (HTML/CSS/JS).

## Global Constraints

- **Sombre par défaut** : `<html data-theme="dark">` + `_DEFAULTS["theme"]="dark"`.
- `save_settings` **fusionne** avec l'existant (n'écrase que les clés fournies).
- Contenu dynamique côté JS via DOM/`textContent` uniquement (jamais `innerHTML` dynamique — sécurité webview).
- Palette exacte : voir la table de la spec §5.
- Message de commit terminé par : `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1 : `settings.py` — fusion + défaut thème

**Files:**
- Modify: `tapageur/gui/settings.py`
- Test: `tests/gui/test_settings.py`

**Interfaces:**
- `_DEFAULTS` gagne `"theme": "dark"`.
- `save_settings(data)` charge l'existant (`load_settings()`), applique `update(data)`, puis écrit → n'écrase que les clés fournies.

- [ ] **Step 1 : Écrire les tests de fusion (échec attendu)**

Ajouter dans `tests/gui/test_settings.py` :

```python
def test_save_merges_preserves_other_keys(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "settings_path", lambda: p)
    settings.save_settings({"anthropic_api_key": "sk-x", "tapeur_email": "a@b.fr"})
    settings.save_settings({"theme": "light"})          # ne doit PAS effacer la clé
    data = settings.load_settings()
    assert data["anthropic_api_key"] == "sk-x"
    assert data["tapeur_email"] == "a@b.fr"
    assert data["theme"] == "light"


def test_save_key_preserves_existing_theme(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "settings_path", lambda: p)
    settings.save_settings({"theme": "light"})
    settings.save_settings({"anthropic_api_key": "sk-y"})
    data = settings.load_settings()
    assert data["theme"] == "light"
    assert data["anthropic_api_key"] == "sk-y"


def test_default_theme_is_dark(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings_path", lambda: tmp_path / "settings.json")
    assert settings.load_settings()["theme"] == "dark"
```

- [ ] **Step 2 : Lancer → échec**

Run: `python -m pytest tests/gui/test_settings.py -q`
Expected: FAIL (`test_save_merges_preserves_other_keys` : la clé API est effacée par le 2ᵉ save ; `test_default_theme_is_dark` : pas de clé `theme`).

- [ ] **Step 3 : Implémenter fusion + défaut**

Dans `tapageur/gui/settings.py` :

```python
_DEFAULTS = {"anthropic_api_key": "", "tapeur_email": DEFAULT_TAPEUR_EMAIL, "theme": "dark"}
```

```python
def save_settings(data: dict) -> None:
    """Écrit les réglages (crée le dossier au besoin).

    Fusionne avec l'existant : seules les clés fournies dans `data` sont
    modifiées (sauver {theme} ne touche pas la clé API, et inversement)."""
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    merged = load_settings()
    merged.update(data)
    p.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
```

- [ ] **Step 4 : Lancer → succès**

Run: `python -m pytest tests/gui/test_settings.py -q`
Expected: PASS (anciens + nouveaux tests).

- [ ] **Step 5 : Commit**

```bash
git add tapageur/gui/settings.py tests/gui/test_settings.py
git commit -m "feat(gui): save_settings fusionnant + clé theme (défaut dark)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2 : `index.html` — thème sombre + bascule

**Files:**
- Modify: `tapageur/gui/web/index.html`

**Interfaces:**
- Consomme : `api().get_settings()` renvoie `theme` (Task 1) ; `api().save_settings({theme})` (fusion, Task 1).
- Pas de test unitaire (UI) : vérif manuelle dans l'app en fin de tâche.

- [ ] **Step 1 : Ajouter les variables claires manquantes dans `:root`**

Dans le bloc `:root { … }`, ajouter :

```css
    --text: #1a202c;
    --muted: #4a5568;
    --drop-border: #888;
    --drop-text: #666;
    --button-bg: #ffffff;
```

- [ ] **Step 2 : Ajouter le bloc thème sombre après `:root`**

Juste après la fermeture de `:root { … }` :

```css
  [data-theme="dark"] {
    --accent: #63b3ed;
    --accent-dark: #4a90d9;
    --accent-contrast: #1a202c;
    --warning: #fc8181;
    --bg: #1e2227;
    --card: #272c33;
    --panel-bg: #22262c;
    --border: #3a4049;
    --text: #e4e7eb;
    --muted: #a0aec0;
    --drop-border: #5a616b;
    --drop-text: #a0aec0;
    --button-bg: #2f353d;
  }
```

- [ ] **Step 3 : Utiliser les variables (couleurs en dur → variables)**

Modifier ces règles existantes :
- `body { … background: var(--bg); color: var(--text); }` (remplacer `color: #1a202c`)
- `#drop { border: 2px dashed var(--drop-border); … color: var(--drop-text); … }` (remplacer `#888` et `#666`)
- `#progress { color: var(--muted); … }` (remplacer `#4a5568`)
- `button { … background: var(--button-bg); … }` (remplacer `background: #fff`)

- [ ] **Step 4 : En-tête avec bouton de bascule**

Ajouter dans le `<style>` :

```css
  #header { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 3px solid var(--accent); padding-bottom: 6px; margin-bottom: 12px; }
  #header h1 { border-bottom: none; padding-bottom: 0; margin: 0; }
  #theme-toggle { font-size: 16px; line-height: 1; padding: 4px 10px; }
```

Remplacer `<h1>tapageur</h1>` (ligne ~40) par :

```html
  <div id="header">
    <h1>tapageur</h1>
    <button id="theme-toggle" title="Basculer clair / sombre" aria-label="Basculer le thème">☀</button>
  </div>
```

(`h1` garde sa règle `color/font-size` ; seule sa bordure est neutralisée par `#header h1`.)

- [ ] **Step 5 : Démarrer en sombre**

Remplacer `<html lang="fr">` par `<html lang="fr" data-theme="dark">`.

- [ ] **Step 6 : JS — appliquer / basculer / persister**

Dans la section `// --- settings ---`, ajouter `applyTheme` + le listener du bouton, et appeler `applyTheme` dans `loadSettings` :

```javascript
function applyTheme(theme) {
  const t = (theme === 'light') ? 'light' : 'dark';
  document.documentElement.dataset.theme = t;
  document.getElementById('theme-toggle').textContent = (t === 'dark') ? '☀' : '☾';
}
document.getElementById('theme-toggle').addEventListener('click', () => {
  const next = (document.documentElement.dataset.theme === 'dark') ? 'light' : 'dark';
  applyTheme(next);
  api().save_settings({ theme: next });
});
```

Dans `loadSettings()`, après avoir rempli api-key / email, ajouter :

```javascript
  applyTheme(s.theme || 'dark');
```

- [ ] **Step 7 : Non-régression (suite complète)**

Run: `python -m pytest -q`
Expected: PASS (le code Python n'a pas changé ici ; confirme que rien n'est cassé).

- [ ] **Step 8 : Vérification manuelle dans l'app**

Lancer `tapageur-gui` :
- l'app démarre en **sombre** (gris, texte clair lisible) ;
- le bouton ☀ bascule en clair (icône ☾), re-clic re-sombre ;
- fermer puis relancer : le dernier thème choisi est **conservé** ;
- vérifier qu'enregistrer la clé API ne réinitialise pas le thème (et inversement).

- [ ] **Step 9 : Commit**

```bash
git add tapageur/gui/web/index.html
git commit -m "feat(gui): thème sombre + bouton de bascule persisté

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes de revue (hors tâches)

- Léger flash possible au démarrage si la préférence sauvée est « clair » (1er rendu sombre → bascule au `loadSettings`). Acceptable (défaut = sombre).
- Contraste : accent clair `#63b3ed` sur fonds gris, texte foncé sur bouton primaire. Vérifier la lisibilité à l'œil lors du test manuel.
