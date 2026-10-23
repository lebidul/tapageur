# tapageur-gui — Design

**Date :** 2026-10-24
**Statut :** validé (brainstorming), prêt pour plan d'implémentation
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Un **utilitaire de bureau avec interface graphique** qui permet à un membre de
l'équipe Bidul de produire le fichier de tapage à partir de sources ponctuelles
(flyers, PDF, pages web), **sans passer par la CLI**.

L'app réutilise le paquet `tapageur` **comme bibliothèque** : aucune règle
d'extraction, canonicalisation ou dédup n'est réécrite.

### Ce que l'utilisateur fait
1. Dépose des fichiers (PDF, JPG/PNG) dans une zone de drop et/ou colle des URLs.
2. Coche le(s) mois cible(s).
3. Choisit les formats de sortie et le dossier de destination.
4. Clique **Lancer**.
5. L'app extrait, écrit les fichiers, et affiche un **résumé + alertes qualité**.
6. L'utilisateur corrige ensuite le fichier **dans Excel/LibreOffice** (pas
   d'édition dans l'app).

## 2. Décisions de cadrage (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Audience v1** | Toi + équipe Bidul. Chacun sa propre `ANTHROPIC_API_KEY`, stockée en local. Zéro serveur, zéro clé partagée. |
| **Distribution** | App de bureau téléchargeable depuis GitHub. `.exe` Windows (packaging = « deuxième temps »). |
| **Édition** | **Pas d'édition dans l'app.** Extraction → fichier direct. Correction dans Excel après coup. L'app fournit en revanche un **résumé lecture seule + alertes**. |
| **Framework GUI** | **`pywebview`** : UI HTML/JS dans une fenêtre native, cœur Python. Meilleur compromis UI/packaging/réutilisation. |
| **Multi-mois** | Cocher 1..N mois → **un fichier de sortie par mois** (une seule passe d'extraction, fetches mutualisés). Case **« ne pas filtrer par mois »** pour tout sortir d'un coup. |
| **Formats de sortie** | **xlsx cloné du template**, **CSV `;`**, **JSON** (cases à cocher, les trois possibles). |
| **Sites JS (navigateur)** | **Navigateur embarqué dès v1** via le chemin Playwright existant. Chromium installé au **premier démarrage** (`playwright install chromium`, ~150 Mo une fois). |
| **URL : suivi de liens** | Par défaut lire **seulement** la page collée. Case à cocher **« suivre les liens d'agenda »** par URL. |

## 3. Architecture

```
UI (HTML/JS, pywebview) ──bridge──▶ service Python
                                       │
   fichiers déposés ─┐                 ├─▶ connectors.docs._route_file()   → CollectedItem[]
   URLs + options ───┼──── build ─────▶├─▶ WebConnector (config synthétique) → CollectedItem[]
                     │                 │
                     ▼                 ▼
            normalize_items() ─▶ canonicalize ─▶ dedup ─▶ group_events ─▶ (convert_to_onliner)
                     │
                     ├─▶ export_xlsx   (clone du template)
                     ├─▶ export_csv    (fonction existante)
                     └─▶ export_json
                     │
              résumé + alertes qualité (lecture seule) ─▶ UI
```

### Nouveau code — sous-paquet `tapageur/gui/`

| Module | Rôle | Neuf ? |
|--------|------|--------|
| `app.py` | Lance la fenêtre pywebview, expose l'API bridge JS↔Python. | neuf |
| `service.py` | Orchestration : build items → pipeline → export → résumé. **Zéro logique métier dupliquée**, appelle les fonctions existantes. | neuf |
| `inputs.py` | Construit les `CollectedItem` : fichiers (réutilise `docs._route_file`) + URLs (config `websites:` synthétique → `WebConnector`). | neuf (fin) |
| `export_xlsx.py` | Remplit une **copie du template** (feuille `lebiduleur`), conserve les feuilles de référence + validations. | **neuf (seul vrai code métier)** |
| `settings.py` | Lit/écrit la config locale (`%APPDATA%/tapageur/settings.json`) : clé API, email tapeur. | neuf |
| `web/index.html` + JS | L'écran unique. | neuf |

Réutilisé tel quel : `connectors/docs.py`, `connectors/web.py` (WebConnector),
`normalize.py`, `dedup.py` (canonicalize/dedup/group/onliner), `validate.py`
(export_csv), `cache.py`, `schema.py`.

## 4. Flux de données détaillé

1. **Build des items** (`inputs.py`)
   - Fichiers : chaque fichier déposé → `docs._route_file()` → `CollectedItem`
     (`image` ou `pdf`). Les fichiers sont copiés dans un dossier de travail
     temporaire pour que `source_ref` soit stable (alimente le cache).
   - URLs : chaque URL + ses options (`suivre les liens`, `festival`) devient
     une entrée `websites:` synthétique passée à `WebConnector.collect(month)`.
     On récupère ainsi gratuitement : navigateur (`needs_browser`), suivi de
     liens (`follow_event_links`), mode festival (`mode: festival_onliner`).
2. **Pipeline par mois coché** : `normalize_items` → `canonicalize` → `dedup`
   → `group_events` → `convert_to_onliner` (si des entrées sont marquées
   festival). Si « ne pas filtrer par mois » est coché, le filtre
   `date_iso.startswith(month)` est désactivé (voir §7, point ouvert).
3. **Export** : un fichier par format demandé **par mois**, dans le dossier
   de sortie (ex. `tapage_2026-10.xlsx`, `tapage_2026-10.csv`, `.json`).
4. **Résumé** renvoyé à l'UI : par mois, nombre d'events + liste d'alertes.

## 5. Paramètres de l'UI

### Essentiels — à chaque run
- Entrées : fichiers déposés + URLs (avec, par URL, les cases « suivre les
  liens » et « c'est un festival »).
- Mois cible(s) (multi-coche) + case **« ne pas filtrer par mois »**.
- Formats de sortie (xlsx / csv / json) + dossier de destination.

### Réglages persistants — une fois
- `ANTHROPIC_API_KEY` : stockée en local, affichée masquée. **Sans elle, rien
  ne tourne** (message clair, pas de crash).
- `tapeur_email` (colonne A « INFO TAPEUR ») : défaut `lebidul@live.fr`.

### Avancé — replié par défaut
- Override de modèle Sonnet/Opus : défaut = auto par type de source.

### Figés — hors UI
Mappings lieux/villes (`mappings.yaml`), system prompts / règles d'extraction,
enchaînement dedup/group/onliner.

## 6. Suggestions intégrées

- **Cache item-level** (`cache.py`) réutilisé → ne pas re-payer Claude pour un
  fichier/URL déjà traité.
- **Estimation de coût avant lancement** : « N items, ~X appels Sonnet/Opus ».
- **Alertes qualité** après extraction (le vrai gain du mode « fichier direct »,
  sans coder l'édition) :
  - prix manquant (`price == "?"`),
  - performer inconnu (`performer == "?"`),
  - **lieu/ville hors des feuilles de référence** du template
    (`communes` / `salles_lieux`) → candidats à canonicaliser.
- **Packaging** `.exe` via PyInstaller + GitHub Releases (deuxième temps).

## 7. Template de sortie xlsx

Le fichier template (`202610_tapage_biduleur_*.xlsx`) contient 4 feuilles :
- **`lebiduleur`** — données. En-têtes = 10 colonnes fixes (A–J) + 4 blocs ACT
  (GENRE / NOM SPECTACLE / COMPAGNIE‑ARTISTE / STYLE). Correspond à la sortie de
  `validate.export_csv` (libellés plus riches côté template).
- **`communes`** — liste de référence des villes (validation de données).
- **`salles_lieux`** — liste de référence des lieux (validation de données).
- **`date`** — correspondance date → libellé FR (« Jeudi 1 ») → format col DATE.

`export_xlsx.py` part d'une **copie** du template embarqué, écrit les lignes
d'events dans `lebiduleur` sous l'en-tête, et **préserve** les trois feuilles de
référence et leurs validations. Décision ouverte (§9) : blocs ACT fixes à 4
(comme le template) vs dynamiques (comme `export_csv`).

## 8. Erreurs & robustesse

- Clé API absente/invalide → message explicite, pas de crash.
- Item en échec (PDF illisible, URL 404, JSON Claude invalide) → loggé dans le
  résumé, les autres items continuent (comportement déjà présent dans
  `normalize_items`).
- URL JS-only → gérée par le navigateur embarqué (plus de limite v1).
- Premier démarrage sans Chromium installé → l'app propose/lance
  `playwright install chromium` et explique le téléchargement unique.

## 9. Décisions par défaut (révisables au plan d'implémentation)

1. **Filtre mois désactivé** : quand « ne pas filtrer par mois » est coché,
   l'app produit **un seul fichier sans mois** (ex. `tapage_tous.xlsx`)
   contenant tous les events extraits, quelle que soit leur date.
2. **Blocs ACT** : **dynamiques** (`max(acts)` sur l'export, comme
   `export_csv`), pour rester cohérent avec le pipeline existant — biduleur
   supporte un nombre dynamique de colonnes.
3. **Emplacement du paquet** : sous-paquet **`tapageur/gui/`** + entry-point
   `tapageur-gui = "tapageur.gui.app:main"` dans `pyproject.toml`.
4. **Dépendances** : ajouter `pywebview` et `openpyxl` au `pyproject.toml`
   dans un groupe optionnel `gui` (`pip install -e ".[gui]"`). `openpyxl` est
   requis pour lire/écrire le template xlsx.

## 10. Tests

- Unitaires sur le code neuf :
  - `inputs.py` : routage fichier, synthèse config URL (fetch mocké).
  - `export_xlsx.py` : template rempli, feuilles de référence préservées,
    lignes correctes.
  - `settings.py` : lecture/écriture, clé absente.
- Cœur `tapageur` : déjà couvert (dedup, validate, festival_mode, web…).
- Pas de test GUI automatisé en v1 (coût/bénéfice faible) → validation manuelle.

## 11. Hors périmètre v1

- Édition des events dans l'app (correction en Excel).
- Push direct vers Google Sheets (reste côté CLI pour l'instant).
- Backend hébergé / clé API partagée.
- Packaging `.exe` (étape suivante, après une v1 lançable en local).
