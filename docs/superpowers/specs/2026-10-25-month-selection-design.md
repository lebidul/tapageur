# Sélection du mois — décision parente — Design

**Date :** 2026-10-25
**Statut :** validé (brainstorming), prêt pour plan
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Clarifier le choix du périmètre temporel via une **décision parente** :
1. **Un mois précis** — l'utilisateur saisit le(s) mois (`AAAA-MM`), filtre strict,
   un fichier de sortie par mois (comportement actuel).
2. **Tous les mois des sources** — extraire sans filtre puis produire **un
   fichier de sortie par mois détecté** dans les events.

## 2. État actuel

- UI (`index.html`, section « Mois ») : champ libre multi-mois
  (`2026-10, 2026-11`) + case « ne pas filtrer par mois ».
- `RunRequest` : `months: list[str]` + `no_month_filter: bool`.
- `service.run` :
  - `no_month_filter=True` → une passe `("", "tous", False)` → **un seul**
    fichier `tous` avec tout.
  - sinon → une passe par mois (`(m, m, True)`), filtre strict, un fichier chacun.
- `normalize._normalize_one` : `month_hint = month` si filtre, sinon
  « tous les mois (ne pas filtrer par date) ». Règle ANNÉE (v5) : utiliser
  l'année du « Mois cible » pour les dates sans année.
- `cache_key` indexe par `month` (donc varie par mois ciblé).

## 3. Décisions (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Choix parent** | Radio : « un mois précis » / « tous les mois des sources ». |
| **Mode précis** | **Garder le multi-mois** (`2026-10, 2026-11`), 1 fichier/mois. |
| **Mode tous** | 1 fichier **par mois détecté** (groupé sur `date_iso` → `AAAA-MM`). |
| **Année de référence (mode tous)** | Auto = année courante ; **si décembre → année+1** (on prépare janvier). **Champ éditable** pré-rempli avec cette valeur. |
| **Override année** | Oui (champ éditable). |

## 4. Changements

### `tapageur/gui/service.py`
- Helper `default_reference_year(today: date | None = None) -> str` :
  `today.year` ; si `today.month == 12` → `today.year + 1`. Renvoie `str`.
- `RunRequest` : remplacer `no_month_filter: bool` par
  `month_mode: str` (`"specific"` | `"all"`) et ajouter
  `reference_year: str = ""` (mode « all » ; vide → `default_reference_year()`).
  `months: list[str]` conservé (mode « specific »).
- `run` :
  - **specific** : une passe par mois de `req.months` (filtre), export par mois
    (inchangé).
  - **all** : extraire **une fois** sans filtre avec l'année de référence →
    **grouper les events par `date_iso[:7]`** → un `_export` par groupe (label =
    `AAAA-MM`). 0 event → aucun fichier, `MonthResult` informatif éventuel.
  - L'année de référence effective = `req.reference_year or default_reference_year()`.

### `tapageur/normalize.py`
- `normalize_items` / `_normalize_one` : nouveau paramètre
  `reference_year: str | None = None`. Quand `month_filter=False` et
  `reference_year` fourni, le user message devient :
  « Mois cible : tous les mois (année de référence : {reference_year} — utilise
  cette année pour les dates sans année) ».
- `cache_key` : en mode « all », la clé doit varier selon l'année de référence.
  Implémentation : passer `month = f"tous-{reference_year}"` à `normalize_items`
  (sert de clé de cache + label de sortie interne) avec `month_filter=False`.
- Règle ANNÉE du `SYSTEM_PROMPT` élargie : « année du « Mois cible » **ou** de
  l'« année de référence » indiquée ». Bump `PROMPT_VERSION` v6 → v7.

### `tapageur/gui/app.py`
- `run_extraction` : lire `payload["month_mode"]`, `payload["reference_year"]`,
  `payload["months"]` ; construire `RunRequest` en conséquence.
- Nouvelle méthode `Api.default_reference_year() -> str` (pour pré-remplir l'UI).

### `tapageur/gui/web/index.html`
- Section « Mois » : radio parent
  `(•) Un mois précis` / `( ) Tous les mois des sources`.
  - « précis » → affiche `#months` (multi, validation `AAAA-MM`).
  - « tous » → cache `#months`, affiche `#reference-year` (champ éditable,
    pré-rempli via `api().default_reference_year()`).
- Payload : `month_mode` (`"specific"`/`"all"`), `months`, `reference_year`.
  Supprimer `no_month_filter`.
- Validation : « précis » → au moins un mois valide ; « tous » → année
  `AAAA` (4 chiffres).

## 5. Tests

- `default_reference_year` : `date(2026,11,1)` → `"2026"` ; `date(2026,12,10)`
  → `"2027"` ; `date(2026,1,5)` → `"2026"`.
- `service.run` mode **all** : `normalize_items` moqué renvoyant des events sur
  2 mois (`2026-11`, `2026-12`) → **2 fichiers** (`tapage_2026-11.*`,
  `tapage_2026-12.*`), chacun avec les bons events.
- `service.run` mode **specific** : inchangé (un fichier par mois listé).
- `app.run_extraction` : payload `month_mode`/`reference_year` → `RunRequest`
  correct (moquer `run`).
- `normalize` : en mode all, le user message contient l'année de référence
  (test léger de `_build_user_content` ou du `month_hint`).

## 6. Hors périmètre

- Borner les mois produits en mode « tous » (on sort tous les mois trouvés).
- Détection de périmètre temporel autre que via `date_iso`.
- Fusion automatique avec un fichier mensuel existant (append reste manuel,
  par case, inchangé).
