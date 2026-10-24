# Interop date « Mardi 2 » (tapageur ↔ biduleur) — Design

**Date :** 2026-10-24
**Statut :** validé (brainstorming), prêt pour plan
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Garantir que la colonne DATE du fichier de sortie (events non-festival) soit
toujours de la forme **« Jour N »** (ex. `Mardi 2`) — jour de semaine français
capitalisé + numéro du jour, sans mois ni année. But : interopérabilité fiable
avec **biduleur**, qui lit cette colonne.

## 2. État actuel

- `date_label` (schema.py, `Col F — ex. 'Vendredi 22'`) est produit en **texte
  libre par le LLM** (prompt `normalize.py:71` : « date en français lisible
  (ex. "Vendredi 22") »). Aucune garantie de format.
- `date_iso` (YYYY-MM-DD) est **fiable** : validé et utilisé pour le filtrage
  par mois (`normalize.py:326`).
- `validate.event_to_row` écrit `ev.date_label` dans la colonne DATE pour les
  events non-festival (`validate.py:100`). Les events festival écrivent le
  marqueur magique « Festivals » (inchangé).
- biduleur (`biduleur/csv_utils.py::_parse_date`) parse déjà « Jour N » :
  `"Samedi 3".split()` → `parts[1]` = numéro du jour. `Mardi 2` est donc
  directement compatible.
- Aucun utilitaire de jour français dans tapageur (biduleur a le sien, mais
  tapageur est autonome — on ne l'importe pas).

## 3. Décision

Dériver `date_label` **de manière déterministe depuis `date_iso`** pour les
events non-festival, au lieu de faire confiance au texte du LLM.

| Sujet | Décision |
|-------|----------|
| **Format** | `"{Jour} {N}"` : jour FR capitalisé + numéro **sans zéro initial**, sans mois ni année (ex. `Mardi 2`, `Lundi 22`). |
| **Source** | `date_iso` (fiable). |
| **Festival** | Inchangé : col DATE = « Festivals », `date_label` reste libre. |
| **Fallback** | Si `date_iso` n'est pas parsable en `%Y-%m-%d`, garder le `date_label` du LLM (défensif ; ne devrait pas arriver vu la validation). |
| **Locale** | Pas de `locale` système (peu fiable/portable sous Windows) : dict des jours en dur. |

## 4. Changements

### `tapageur/normalize.py`
- Nouveau helper :
  ```python
  _JOURS_FR = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi",
               4: "Vendredi", 5: "Samedi", 6: "Dimanche"}

  def _french_date_label(date_iso: str, fallback: str = "") -> str:
      """'2026-06-02' -> 'Mardi 2'. Fallback si date_iso non parsable."""
      try:
          dt = datetime.strptime(date_iso, "%Y-%m-%d")
      except (ValueError, TypeError):
          return fallback
      return f"{_JOURS_FR[dt.weekday()]} {dt.day}"
  ```
- Dans `_normalize_one`, à la construction de l'`Event` **non-festival**,
  remplacer `date_label` par `_french_date_label(draft.date_iso, draft.date_label)`.
  Pour un event festival (`draft.is_festival`), conserver `draft.date_label`.
- `datetime` est déjà importé dans `normalize.py`.

### `tapageur/normalize.py` (prompt)
- Alléger la ligne décrivant `date_label` (événements normaux) pour indiquer
  qu'il est désormais **dérivé de `date_iso`** côté Python ; insister sur le
  fait que `date_iso` doit être exact. Le bloc festival (`date_label` libre)
  est inchangé.

### `tapageur/validate.py`
- **Inchangé** : `event_to_row` continue d'écrire `ev.date_label` (qui est
  maintenant garanti « Jour N » pour les non-festival).

## 5. Tests

- `_french_date_label` :
  - `"2026-06-02"` → `"Mardi 2"` (numéro sans zéro initial) ;
  - `"2026-06-22"` → `"Lundi 22"` ;
  - `"2026-06-01"` → `"Lundi 1"` ;
  - date invalide (`"pas-une-date"`) → fallback fourni.
- `_normalize_one` (ou au niveau `Event` construit) :
  - event non-festival avec `date_iso="2026-06-02"` → `date_label == "Mardi 2"`
    même si le LLM a renvoyé autre chose ;
  - event festival → `date_label` **inchangé** (reste la valeur libre).

## 6. Hors périmètre

- Inclure le mois/l'année dans le libellé.
- Sortie en date ISO (déléguer le calcul du jour + le regroupement de jours
  consécutifs à biduleur).
- Format des lignes festival.
- Internationalisation (autres langues).
