# Overrides par élément (tous types de source) — Design

**Date :** 2026-10-24
**Statut :** validé (brainstorming), prêt pour plan
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Pour **chaque élément** de **chaque type de source** (fichier, URL, texte collé),
pouvoir fournir à la main, indépendamment :
- le **lieu** (col H, override si absent de l'extraction) ;
- l'**asso/festival** (col D « FESTOCHE/ÉVÉNEMENT », override si absent) ;
- **« festival (une ligne) »** (traiter cet élément comme un festival → résumé onliner).

Aujourd'hui : seuls les **textes** ont lieu+asso ; seules les **URLs** ont le toggle festival ; les **fichiers** n'ont rien.

## 2. Le cœur supporte déjà tout ça (par item)

- `normalize._normalize_one` applique `raw_metadata["default_venue"]` / `["default_festival"]` **si** le champ extrait est absent (déjà en place).
- `mode == "festival_onliner"` dans `raw_metadata` → `normalize` utilise `FESTIVAL_SYSTEM_PROMPT` (déjà en place ; propagé pour les URLs via la config).
- `cache_key` inclut déjà `default_venue`/`default_festival`/`mode`.

Donc ce design est surtout **UI + builders d'items** + une petite propagation côté `WebConnector`.

## 3. Décisions (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Fichiers** | Passent d'une liste plate à des **lignes** : chaque fichier = chemin + Lieu + Asso/festival + case « festival (une ligne) » + ×. |
| **Lieu en mode festival** | Champ **visible mais ignoré** quand « festival » est coché (un festival n'a pas de lieu unique ; vidé à l'export). Aucun code spécial. |
| **Interaction** | Overrides appliqués si absents (classique) ; en mode festival, l'asso/festival **complète** le nom de festival s'il manque ; le lieu est sans effet (vidé à l'export par `event_to_row`). Se compose sans cas particulier. |

## 4. Changements

### `tapageur/gui/inputs.py`
- Nouveau `@dataclass FileInput(path: str, venue="", info_orga="", is_festival=False)`.
- `items_from_files(file_inputs: list[FileInput], progress=None)` : pour chaque
  `FileInput`, router `path` via `_route_file` (liste), puis **décorer** chaque
  item produit : `raw_metadata["default_venue"]=venue` / `["default_festival"]=info_orga`
  (si non vides) et `raw_metadata["mode"]="festival_onliner"` (si `is_festival`).
- `UrlInput` gagne `venue=""`, `info_orga=""`. `_url_to_site` ajoute au dict
  site : `default_venue`, `default_festival` (si non vides). (`mode` déjà géré
  via `is_festival`.)
- `TextInput` gagne `is_festival=False`. `items_from_texts` ajoute
  `raw_metadata["mode"]="festival_onliner"` si `is_festival` (en plus de
  `default_venue`/`default_festival` déjà posés).

### `tapageur/connectors/web.py`
- `WebConnector` **propage** `default_venue`/`default_festival` depuis la config
  du site vers le `raw_metadata` de chaque item (comme il le fait déjà pour
  `mode`/`model_override`), via `_web_item` + la branche PDF-URL.

### `tapageur/gui/service.py`
- `RunRequest.file_paths` → **`file_inputs: list[FileInput]`** (défaut `[]`).
- `run` : `items_from_files(req.file_inputs, progress=progress)`.

### `tapageur/gui/app.py`
- `run_extraction` : construit `FileInput(**f) for f in payload["files"]` ;
  `UrlInput(**u)` (avec venue/info_orga) ; `TextInput(**t)` (avec is_festival).

### `tapageur/gui/web/index.html`
- **Fichiers** : la sélection crée une **ligne par fichier** (chemin + Lieu
  [datalist] + Asso/festival + case « festival (une ligne) » + ×). `files`
  devient une liste d'objets `{path, venue, info_orga, is_festival}`.
- **URLs** : ajouter Lieu [datalist] + Asso/festival à chaque ligne.
- **Textes** : ajouter la case « festival (une ligne) » à chaque ligne.
- **Payload** : `files: [{path, venue, info_orga, is_festival}]` ; chaque url
  `{url, follow_links, is_festival, venue, info_orga}` ; chaque texte
  `{text, venue, info_orga, is_festival}`.

## 5. Tests
- `items_from_files` : un `FileInput(venue, info_orga, is_festival=True)` sur une
  image → l'item porte `default_venue`/`default_festival`/`mode=festival_onliner`
  dans `raw_metadata` (fusionnés avec la metadata existante de l'item).
- `items_from_urls` : `UrlInput(venue=…, info_orga=…)` → la config site porte
  `default_venue`/`default_festival` ; `WebConnector` les propage dans l'item
  (test avec `_fetch`/`_filter_event_urls` mockés).
- `items_from_texts` : `TextInput(is_festival=True)` → item `mode=festival_onliner`.
- `web._web_item` / collect : item porte les overrides propagés.
- `app.run_extraction` : payload `files`/`urls`/`texts` → `RunRequest.file_inputs`
  et les UrlInput/TextInput peuplés (venue/info_orga/is_festival).
- `service.run` : `file_inputs` entrent dans le pipeline.

## 6. Hors périmètre
- Griser le champ Lieu en mode festival (laissé visible/ignoré).
- Autres champs éditables (ville, date, heure, prix, genre).
- Validation sémantique du contenu des overrides.
