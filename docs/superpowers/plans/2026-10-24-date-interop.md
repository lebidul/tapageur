# Interop date « Mardi 2 » — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Garantir que la colonne DATE des events non-festival soit toujours « Jour N » (ex. `Mardi 2`), dérivée de `date_iso`.

**Architecture:** Un helper pur `_french_date_label(date_iso)` dans `normalize.py`, appelé dans `_normalize_one` pour écraser `date_label` des drafts non-festival juste avant la création de l'`Event`. `event_to_row` est inchangé (il lit `ev.date_label`).

**Tech Stack:** Python 3.11+, pydantic v2, pytest.

## Global Constraints

- Format exact : `"{Jour} {N}"` — jour FR capitalisé + numéro **sans zéro initial**, **sans mois ni année** (ex. `Mardi 2`, `Lundi 22`, `Lundi 1`).
- Jours dérivés **sans `locale`** système : dict en dur `{0:"Lundi",…,6:"Dimanche"}`.
- Events **festival** (`is_festival=True`) : `date_label` **inchangé**.
- Si `date_iso` non parsable en `%Y-%m-%d` : fallback sur le `date_label` fourni.
- `event_to_row` (validate.py) n'est PAS modifié.
- Message de commit terminé par : `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1 : helper `_french_date_label` + injection dans `_normalize_one`

**Files:**
- Modify: `tapageur/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produit : `_french_date_label(date_iso: str, fallback: str = "") -> str`.
- Modifie le comportement de `_normalize_one(...)` : pour chaque draft **non-festival**, `date_label` est remplacé par `_french_date_label(draft.date_iso, draft.date_label)` avant la construction de l'`Event`. Draft festival inchangé.
- Contexte existant (déjà en place, à consommer tel quel) : `_EventDraft` a les champs `date_label: str`, `date_iso: str`, `is_festival: bool = False` (tous mutables) ; `_normalize_one` construit l'`Event` via `Event(**draft.model_dump(), tapeur_email=…, source_kind=…, source_ref=…)` (normalize.py:339-345), après avoir appliqué les overrides `default_venue`/`default_festival`.
- ⚠️ **`datetime` n'est PAS importé** dans `normalize.py` (imports actuels : `json`, `os`, `Callable`, `Path`, `Anthropic`, `BaseModel`, `Console`, puis `tapageur.cache` / `tapageur.schema`). Ajouter `from datetime import datetime` dans le bloc d'imports.
- Helpers de test existants dans `tests/test_normalize.py` : `_fake_client_returning(events_json)`, `_text_item(meta)`, `_ev(venue, festival=None)` (date_iso `"2026-11-03"`).

- [ ] **Step 1 : Écrire les tests du helper (échec attendu)**

Ajouter dans `tests/test_normalize.py` :

```python
from tapageur.normalize import _french_date_label


def test_french_date_label_basic():
    assert _french_date_label("2026-06-02") == "Mardi 2"   # pas de zéro initial
    assert _french_date_label("2026-06-22") == "Lundi 22"
    assert _french_date_label("2026-06-01") == "Lundi 1"


def test_french_date_label_invalid_returns_fallback():
    assert _french_date_label("pas-une-date", "SECOURS") == "SECOURS"
    assert _french_date_label("", "SECOURS") == "SECOURS"
```

- [ ] **Step 2 : Lancer → échec**

Run: `python -m pytest tests/test_normalize.py -k french_date_label -q`
Expected: FAIL (ImportError : `_french_date_label` n'existe pas).

- [ ] **Step 3 : Implémenter le helper dans `normalize.py`**

D'abord ajouter l'import manquant dans le bloc d'imports (après `from pathlib import Path`) :

```python
from datetime import datetime
```

Puis ajouter, après les imports (avant `_EventDraft`) :

```python
_JOURS_FR = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi",
             4: "Vendredi", 5: "Samedi", 6: "Dimanche"}


def _french_date_label(date_iso: str, fallback: str = "") -> str:
    """'2026-06-02' -> 'Mardi 2'. Fallback si date_iso non parsable.

    Jour FR capitalisé + numéro sans zéro initial, sans mois ni année.
    Pas de dépendance à la locale système.
    """
    try:
        dt = datetime.strptime(date_iso, "%Y-%m-%d")
    except (ValueError, TypeError):
        return fallback
    return f"{_JOURS_FR[dt.weekday()]} {dt.day}"
```

- [ ] **Step 4 : Lancer → succès**

Run: `python -m pytest tests/test_normalize.py -k french_date_label -q`
Expected: PASS.

- [ ] **Step 5 : Écrire les tests d'injection (échec attendu)**

Ajouter dans `tests/test_normalize.py` (réutilise `_fake_client_returning` / `_text_item`) :

```python
def test_normalize_one_derives_date_label_non_festival():
    """Le date_label du LLM est écrasé par la forme 'Jour N' dérivée de date_iso."""
    from tapageur import normalize as _norm
    item = _text_item({})
    ev = {
        "date_label": "LABEL FAUX DU LLM", "date_iso": "2026-11-10",
        "times": ["20h00"], "venue": "V", "city": "Le Mans", "price": "?",
        "acts": [{"genre": "c", "title": None, "performer": "A", "style": None}],
    }
    out = _norm._normalize_one(_fake_client_returning([ev]), item, "2026-11", None, "t@b.fr")
    assert out[0].date_label == "Mardi 10"


def test_normalize_one_keeps_festival_date_label():
    """Event festival : date_label libre conservé (non dérivé)."""
    from tapageur import normalize as _norm
    item = _text_item({})
    ev = {
        "date_label": "27-28 juin", "date_iso": "2026-06-27", "is_festival": True,
        "festival": "Festival X", "times": ["?"], "venue": "", "city": "Le Mans",
        "price": "?",
        "acts": [{"genre": "sv", "title": None, "performer": "15 spectacles", "style": None}],
    }
    out = _norm._normalize_one(_fake_client_returning([ev]), item, "2026-06", None, "t@b.fr")
    assert out[0].date_label == "27-28 juin"
```

- [ ] **Step 6 : Lancer → échec**

Run: `python -m pytest tests/test_normalize.py -k "derives_date_label or keeps_festival_date" -q`
Expected: FAIL (le test non-festival échoue : `date_label` vaut encore « LABEL FAUX DU LLM »).

- [ ] **Step 7 : Implémenter l'injection dans `_normalize_one`**

Dans `tapageur/normalize.py`, juste **avant** le bloc `try: events.append(Event(...))` (après les overrides `default_venue`/`default_festival`, ~ligne 334), insérer :

```python
        # Interop biduleur : la colonne DATE des events non-festival doit être
        # de la forme « Jour N » (ex. « Mardi 2 »), dérivée de date_iso et non
        # du texte libre du LLM. Les festivals gardent leur date_label libre
        # (la colonne DATE porte « Festivals » côté export).
        if not draft.is_festival:
            draft.date_label = _french_date_label(draft.date_iso, draft.date_label)
```

Puis alléger la description de `date_label` dans le prompt système (normalize.py:71), par ex. :

```
- date_label : ignoré pour les events normaux (recalculé côté Python depuis
  date_iso en « Jour N »). date_iso DOIT être exact.
```

(Le bloc festival du prompt, normalize.py:137, reste inchangé : `date_label` libre.)

- [ ] **Step 8 : Lancer → succès**

Run: `python -m pytest tests/test_normalize.py -k "derives_date_label or keeps_festival_date" -q`
Expected: PASS.

- [ ] **Step 9 : Suite complète (non-régression)**

Run: `python -m pytest -q`
Expected: PASS (toute la suite).

- [ ] **Step 10 : Commit**

```bash
git add tapageur/normalize.py tests/test_normalize.py
git commit -m "feat(normalize): dérive date_label en « Jour N » depuis date_iso (interop biduleur)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes de revue (hors tâche)

- Le champ `date_label` du schéma reste typé `str` (description à rafraîchir éventuellement, non bloquant).
- Les events festival conservent un `date_label` libre : c'est voulu (col DATE = « Festivals » à l'export).
- `dedup`/`service` consomment `date_label` sans le parser → bénéficient du libellé dérivé sans changement.
