# Horaires / tarifs par défaut, par lieu — Design

**Date :** 2026-10-25
**Statut :** validé (brainstorming), prêt pour plan
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Pour certains lieux, l'heure et/ou le prix ne figurent jamais sur la source
mais sont toujours les mêmes (ex. **Bistro Broc Café** : 20h00, « au chapeau »).
Permettre de définir, **par lieu**, une heure et un prix **par défaut**,
appliqués automatiquement quand l'extraction ne les trouve pas.

## 2. Décisions (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Par quoi** | Par **lieu** (pas par source saisie) — automatique, extensible à d'autres lieux. |
| **Config** | Fichier `config/venue_defaults.yaml`, **embarqué dans l'exe** (rebuild pour éditer, comme `mappings.yaml`). |
| **Clé** | Nom **canonique** du lieu (tel qu'après `canonicalize` / dans `salles_lieux`). |
| **Application** | Seulement si le champ **manque** (heure `["?"]`/vide ; prix `"?"`/vide) — jamais sur une valeur extraite. |
| **Seed** | `Bistro Broc Café` → `{time: "20h00", price: "au chapeau"}`. |

## 3. État actuel

- `dedup.load_mappings(path="config/mappings.yaml")` + `canonicalize(events,
  mappings)` : la canonicalisation remet le lieu sous sa forme canonique.
- `service._pipeline` : `normalize_items` → `canonicalize` → `dedup` →
  `group_events` → `convert_to_onliner`.
- `mappings.yaml` est embarqué dans l'exe + résolu via `_MEIPASS`
  (`service._mappings_path`), bundle `tapageur.spec`.

## 4. Changements

### `config/venue_defaults.yaml` (nouveau)
```yaml
# Heure / prix par défaut par lieu (forme canonique), appliqués SI absents.
"Bistro Broc Café":
  time: "20h00"
  price: "au chapeau"
```

### `tapageur/dedup.py`
- `load_venue_defaults(path: Path = Path("config/venue_defaults.yaml")) -> dict` :
  lit le YAML → `{venue: {"time": ..., "price": ...}}` ; `{}` si absent/illisible.
- `apply_venue_defaults(events, defaults) -> list[Event]` : pour chaque event
  dont `event.venue` est une clé de `defaults` :
  - si `event.times` est vide ou `["?"]` **et** `defaults[venue].get("time")`
    → `event.times = [time]` ;
  - si `event.price` est vide ou `"?"` **et** `defaults[venue].get("price")`
    → `event.price = price`.
  Retourne la liste (events mutés en place).

### `tapageur/gui/service.py`
- `_venue_defaults_path()` : miroir de `_mappings_path()` (`_MEIPASS` si figé,
  sinon `config/venue_defaults.yaml`).
- `_pipeline` : après `canonicalize`, insérer
  `events = apply_venue_defaults(events, load_venue_defaults(_venue_defaults_path()))`.

### `tapageur.spec`
- Ajouter aux `datas` : `("config/venue_defaults.yaml", "config")`.

## 5. Tests

- `load_venue_defaults` : lit un YAML valide → dict ; absent → `{}`.
- `apply_venue_defaults` :
  - event au « Bistro Broc Café » avec `times=["?"]`, `price="?"` → `20h00`,
    `au chapeau` ;
  - event au même lieu avec `times=["18h30"]`, `price="7€"` → **inchangés** ;
  - event dans un lieu non listé → inchangé ;
  - lieu listé mais seul `time` défini → seul l'horaire est complété.

## 6. Hors périmètre

- Pipeline CLI (`cli.py`) — cette feature cible le GUI/exe ; à étendre plus tard
  si besoin.
- Édition du YAML sans rebuild pour l'exe (choix : embarqué).
- Autres champs par défaut (ville, genre…).
- Défauts globaux (tout est par lieu).
