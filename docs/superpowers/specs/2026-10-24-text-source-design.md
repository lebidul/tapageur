# Source « texte collé » — Design

**Date :** 2026-10-24
**Statut :** validé (brainstorming), prêt pour plan d'implémentation
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Permettre d'ajouter aux sources un **texte copié-collé** (en plus des fichiers et
des URLs), et de **fournir à la main** deux infos qui n'apparaissent pas toujours
dans le texte :
- le **lieu** (colonne H « LIEU », depuis la liste `salles_lieux`) ;
- l'**asso/orga** (colonne D « FESTOCHE / ÉVÉNEMENT », champ `festival`).

## 2. Décisions de cadrage (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Saisie** | Section « Textes » avec bouton **« + Ajouter un texte »** ; plusieurs entrées possibles, chacune = une source (une zone de texte + ses deux champs). |
| **Lieu** → colonne H `venue`. Champ avec **autocomplétion** (`<datalist>` depuis `salles_lieux`) ; saisie libre autorisée. |
| **Asso/orga** → colonne D `festival` (« FESTOCHE / ÉVÉNEMENT »). |
| **Application** | **Override seulement si absent** : on applique le lieu si l'event extrait n'a pas de lieu (vide/`?`), et l'asso/orga si `festival` est vide. On n'écrase jamais une valeur que Claude a extraite. |
| **Champs** | Ces deux-là uniquement pour l'instant (ville, date, heure, prix, genre restent extraits du texte). |

## 3. Flux (réutilise le pipeline existant)

- Chaque texte collé devient un `CollectedItem` de **nouveau `source_kind="text"`** :
  - `raw_text` = le texte collé ;
  - `raw_metadata = {"default_venue": <lieu ou "">, "default_festival": <asso/orga ou "">}`.
- Extraction Claude classique (prompt standard ; modèle Sonnet pour `text`).
- **Application des overrides** par item, dans `normalize._normalize_one`, après
  validation du `_EventDraft` et **avant** la création de l'`Event` :
  - si `default_venue` présent ET `draft.venue` vide ou `"?"` → `draft.venue = default_venue` ;
  - si `default_festival` présent ET `draft.festival` vide/None → `draft.festival = default_festival`.
  (Générique, piloté par `raw_metadata` ; aucun effet si ces clés sont absentes,
  donc inoffensif pour les autres sources.)
- Ensuite : filtre mois, canonicalisation du lieu (`canonicalize` mappe le lieu
  fourni vers sa forme canonique comme n'importe quel lieu), dédup, groupement,
  export, append — inchangés.

## 4. Pièces touchées

| Fichier | Changement |
|---------|------------|
| `tapageur/schema.py` | Ajouter `"text"` au `Literal` `source_kind` (de `CollectedItem` et `Event`). |
| `tapageur/normalize.py` | `MODEL_BY_KIND["text"] = "claude-sonnet-4-5"` ; dans `_normalize_one`, appliquer les overrides `default_venue`/`default_festival` depuis `item.raw_metadata`. |
| `tapageur/gui/inputs.py` | `@dataclass TextInput(text, venue="", info_orga="")` ; `items_from_texts(text_inputs, progress=None) -> list[CollectedItem]`. |
| `tapageur/gui/service.py` | `RunRequest.text_inputs: list[TextInput]` (défaut `[]`) ; `run` construit aussi les items texte (`items += items_from_texts(...)`), avec progress. |
| `tapageur/gui/app.py` | `Api.get_venues() -> list[str]` (liste `salles_lieux` depuis le template) ; `run_extraction` lit `payload["texts"]` → `TextInput(...)`. |
| `tapageur/gui/web/index.html` | Section « Textes » + « + Ajouter un texte » (zone de texte + champ lieu lié à un `<datalist>` + champ asso/orga) ; `texts` ajouté au payload ; `<datalist>` peuplé via `get_venues()` au chargement. |

## 5. Détails

- **`items_from_texts`** : pour chaque `TextInput` à texte non vide, crée un
  `CollectedItem(source_kind="text", source_ref="texte #<n>", raw_text=<texte>,
  raw_metadata={"default_venue": venue, "default_festival": info_orga})`.
  `source_ref` unique et lisible (ex. « texte #1 ») pour le cache et les logs.
  Progress : « Texte i/n… » (optionnel, cohérent avec le reste).
- **`get_venues`** : réutilise la lecture de `salles_lieux` du template (comme
  `service._reference_lists`, qui lit déjà `communes`/`salles_lieux`) ; renvoyer
  la liste triée.
- **Filtre mois** : les events d'un texte sont filtrés par mois comme les autres
  (le texte contient les dates). Rien de spécial.
- **Mode festival** : non concerné (extraction classique).

## 6. Tests

- `schema` : un `CollectedItem`/`Event` avec `source_kind="text"` est valide.
- `normalize._normalize_one` : item `text` avec `raw_metadata` → le venue
  fallback s'applique quand Claude renvoie un venue vide/`?`, et PAS quand Claude
  renvoie un venue ; idem pour `festival` (Claude mocké).
- `inputs.items_from_texts` : construit les `CollectedItem` attendus
  (source_kind, raw_text, metadata), ignore les textes vides.
- `service` : `RunRequest(text_inputs=[...])` → les items texte entrent dans le
  pipeline (via un run avec `normalize_items` mocké, vérifier que les items texte
  sont passés).
- `app` : `run_extraction` avec `payload["texts"]` → `RunRequest.text_inputs`
  correctement peuplé ; `get_venues()` renvoie une liste non vide.

## 7. Hors périmètre
- Autres champs éditables (ville, date, heure, prix, genre).
- Override « toujours » (on reste sur « seulement si absent »).
- Menu déroulant strict pour le lieu (on reste sur l'autocomplétion libre).
