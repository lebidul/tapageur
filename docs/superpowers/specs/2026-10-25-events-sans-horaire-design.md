# Garder les events sans horaire — Design

**Date :** 2026-10-25
**Statut :** validé (brainstorming), prêt pour plan
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Permettre d'entrer des événements **sans horaire** (ex. programmes de
festivals saisis en events normaux, comme Changé d'Air), au lieu de les
supprimer. L'horaire manquant devient `"?"` (comme prix/artiste inconnus),
et le tapeur complète à la main. Le nom du festival va en col D via le champ
**Asso/festival** existant (aucun changement de ce côté).

## 2. État actuel

- `SYSTEM_PROMPT` règle 2 : « NE JAMAIS inventer une heure. Si absent, ne pas
  créer l'event. » → tout event sans horaire est supprimé par le modèle.
- `_EventDraft.times: list[str]` (requis) ; `Event` a le validateur
  `at_least_one_time` (≥ 1 horaire).
- `build_alerts` (gui/service.py) signale prix « ? » et performer « ? », mais
  pas l'horaire.

## 3. Décisions (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Portée** | **Global** : tout event sans horaire est gardé avec `times=["?"]`. |
| **Règle 7** | **Inchangée** : conférences / ateliers / films restent exclus. |
| **Alerte** | Oui : « Horaire manquant » (comme l'alerte prix). |
| **Festival en col D** | Déjà couvert par le champ Asso/festival (override `default_festival`). |

## 4. Changements

### `tapageur/normalize.py` (prompt)
Règle 2 du `SYSTEM_PROMPT` reformulée :
> 2. NE JAMAIS inventer une heure. Si l'heure est absente, mets `times=["?"]`
>    (même convention que le prix) — ne PAS supprimer l'event.

Règle 7 inchangée. `FESTIVAL_SYSTEM_PROMPT` inchangé (utilise déjà `["?"]`).
Bump `PROMPT_VERSION` v5 → v6.

### `tapageur/normalize.py` (robustesse — défense en profondeur)
Le modèle peut renvoyer `times=[]` ou l'omettre malgré le prompt :
- `_EventDraft.times: list[str] = Field(default_factory=list)` (ne pas rejeter
  le draft si `times` est omis).
- Dans `_normalize_one`, avant la création de l'`Event` : si `draft.times` est
  vide, `draft.times = ["?"]` (sinon `at_least_one_time` rejetterait l'event).

### `tapageur/gui/service.py`
`build_alerts` : ajouter, pour chaque event dont `times` contient `"?"` :
`f"Horaire manquant : {ev.date_label} — {ev.acts[0].performer}"`.

## 5. Tests

- `_normalize_one` : un draft avec `times=[]` (ou omis) → event **gardé** avec
  `times == ["?"]` (non rejeté).
- `_normalize_one` : un draft avec `times=["20h00"]` → inchangé.
- `build_alerts` : event avec `times=["?"]` → alerte « Horaire manquant » ;
  event avec horaire réel → pas d'alerte horaire.

## 6. Hors périmètre

- Case « garder sans horaire » par source (choix : global).
- Inclure conférences / ateliers / films (règle 7 conservée).
- Routage vision des PDF majoritairement en images (évolution séparée).
