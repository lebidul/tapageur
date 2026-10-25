# Merge / dédoublonnage à l'écriture xlsx — design

**Date :** 2026-10-26
**TODO :** #4 (Merger au lieu d'ajouter)

## Objectif

Remplacer le choix binaire actuel (« Ajouter au fichier existant » = append
aveugle) par **trois modes d'écriture** explicites, dont un mode qui fusionne
intelligemment avec un fichier mensuel existant sans ré-insérer les doublons ni
écraser les corrections manuelles du tapeur.

## Les 3 modes d'écriture

L'UI remplace la case « Ajouter au fichier existant » par un **choix à 3
options** (radio) :

### 1. Créer / écraser
Fichier neuf à partir du template (= comportement non-append actuel). Si le
fichier existe, il est écrasé.

### 2. Ajouter (incrémental)
- On lit la **colonne SOURCE** du fichier existant → ensemble des sources déjà
  présentes.
- On **ne collecte/extrait que les sources absentes** de cet ensemble.
- Leurs lignes sont **ajoutées à la suite** (append brut, pas de dédoublonnage
  ligne-à-ligne — inutile puisque ces sources n'étaient pas là).
- Pas de ré-extraction des sources déjà présentes (économie d'appels modèle).
- **Limite assumée** : si une source déjà présente a gagné de nouveaux events
  depuis la dernière passe, ils ne sont PAS récupérés (c'est le rôle du mode
  Fusionner). Si le fichier n'existe pas → se comporte comme « Créer ».

### 3. Fusionner
- On (re)traite les sources demandées (le **cache de normalisation** rend le
  re-traitement d'une source inchangée quasi gratuit).
- On **reverse-parse** le fichier existant en lignes comparables.
- Pour chaque event entrant (après dedup/group internes) :
  - **match** avec une ligne existante → politique **« compléter les trous »**
    (voir ci-dessous) ;
  - **pas de match** → nouvelle ligne ajoutée à la suite.
- Écriture **in-place** (patch des cellules + ajout de lignes) pour préserver
  la mise en forme du fichier. Si le fichier n'existe pas → « Créer ».

## Clé de match (mode Fusionner)

Un event entrant correspond à une ligne existante si **tous** ces champs
(normalisés minuscule/trim) sont égaux :

- **DATE** (colonne H, libellé « Jour N », ex. « Mardi 2 »)
- **LIEU** (colonne J ; canonique des deux côtés car `canonicalize()` tourne
  en amont et les lignes du fichier ont été écrites canoniques)
- **ARTISTE du 1ᵉ acte** (1ʳᵉ colonne ARTISTE, ex. col O)

**HEURE et PRIX sont EXCLUS de la clé** : ce sont des champs à compléter, pas à
discriminer (le tapeur peut avoir corrigé une heure).

Rationale : c'est le `Event.fingerprint()` existant (`date_iso|heure|venue|
artiste`) adapté aux colonnes visibles — `date_iso` n'étant pas stocké dans
l'xlsx, on utilise le libellé DATE, stable à l'intérieur d'un fichier mensuel.

## Politique de conflit : « compléter les trous »

Quand un event entrant matche une ligne existante :
- La ligne existante **gagne** (présomption de correction manuelle).
- Pour chaque champ de contenu **vide ou « ? »** sur la ligne existante, si
  l'entrant a une valeur, on **remplit** la cellule. Champs concernés :
  HEURE, PRIX, FESTOCHE, STYLE FESTOCHE, et les blocs ACT au-delà de ceux déjà
  présents (GENRE/NOM/ARTISTE/STYLE des actes supplémentaires), ainsi que les
  sous-champs vides d'un acte existant (ex. STYLE vide).
- **Jamais** d'écrasement d'une valeur non vide/non-« ? ».
- **Colonne SOURCE** : la nouvelle source est **accolée** à la cellule SOURCE
  existante (ex. « `prog.pdf` ; `https://…` ») pour tracer la double
  provenance. TYPE SOURCE suit la même logique (concat des libellés distincts).

## Matching des sources (mode Ajouter incrémental)

On compare l'identifiant d'une source d'entrée à l'ensemble des valeurs de la
colonne SOURCE du fichier, en reproduisant `validate._source_ref_display` :

- **Fichier / image** : nom de fichier (basename). Un PDF multi-pages s'affiche
  « `fichier.pdf (p.N)` » → match sur le **préfixe basename**.
- **URL (web)** : URL brute, match exact.
- **Texte collé** : rendu « texte #N » (positionnel, non stable entre passes)
  → **non matchable de façon fiable** : les textes collés sont **toujours
  traités** en mode incrémental (documenté ; l'utilisateur gère).

## Reverse-parse (lecture du fichier existant)

- **Hypothèse : template structurellement intact** (colonnes à leur position
  d'origine). Lecture **par position de colonne** (12 colonnes fixes A-L puis
  blocs de 4 par acte), cohérente avec `validate.HEADERS` / `_N_FIXED_COLS`.
- On lit la feuille de données (`DATA_SHEET`), on saute l'en-tête, on extrait
  par ligne : DATE, HEURE, LIEU, PRIX, FESTOCHE, STYLE FESTOCHE, SOURCE, TYPE
  SOURCE, et les blocs ACT (GENRE/NOM/ARTISTE/STYLE).
- Conventions « vide » : chaîne vide ou « ? » = trou à compléter.

## Cas d'usage : passe de complément cross-agenda (ex. clappin.fr)

Workflow visé : après les extractions natives, relancer une passe en mode
**Fusionner** avec **uniquement** des URLs d'un agenda tiers équivalent
(ex. `https://clappin.fr/agenda-musique/`, `https://clappin.fr/agenda-theatre/`)
pour **compléter** et **ajouter** des events manquants au fichier mensuel.

- **Ajouter les manquants** → ✅ couvert (event tiers sans match = nouvelle ligne).
- **Compléter les trous** → ✅ couvert (remplit HEURE/PRIX/FESTOCHE/… vides ou « ? »).
- **Corriger** (remplacer une valeur déjà remplie) → ❌ **non supporté** : la
  politique « compléter les trous » n'écrase jamais une cellule non vide (choix
  explicite ; aucune provenance par cellule pour distinguer une correction
  manuelle d'une valeur d'extraction). Pour corriger, le tapeur édite à la main.

Ce use case ne demande **aucune mécanique spécifique** : c'est le mode
Fusionner appliqué à une liste d'URLs tierces. La seule réserve est le matching
cross-source (cf. Limites).

## Compte-rendu (Résumé / progress)

À la fin d'une fusion, émettre un récap chiffré **et** le **détail par event**
dans le log live / Résumé, pour que le tapeur voie exactement ce qui a bougé :

- Récap : « **N** events ajoutés · **M** lignes complétées · **K** inchangées »
  (+ pour l'incrémental : « **S** sources déjà présentes ignorées »).
- Détail, une ligne par event touché :
  - **AJOUTÉ** : `+ <DATE> · <LIEU> · <ARTISTE>` (nouvelle ligne).
  - **COMPLÉTÉ** : `~ <DATE> · <LIEU> · <ARTISTE> → champs remplis : HEURE, PRIX`
    (lister les champs effectivement remplis, et la source d'origine du
    complément).
  Les events inchangés ne sont pas listés individuellement (juste comptés).

## Impact code

- `tapageur/gui/service.py` :
  - `RunRequest` : remplacer `append: bool` par `write_mode:
    Literal["create","append","merge"]`.
  - Mode « append » (incrémental) : avant collecte, lire l'ensemble SOURCE du
    fichier existant et filtrer `file_inputs` / `url_inputs` (textes toujours
    gardés).
  - Mode « merge » : après pipeline, appeler la fusion.
  - `MonthResult` : ajouter les compteurs de fusion (added / filled /
    unchanged / sources_skipped) pour le Résumé.
- `tapageur/gui/export_xlsx.py` :
  - Router selon `write_mode` (create → `export_xlsx`, append →
    `_append_xlsx` existant, merge → nouveau `_merge_xlsx`).
  - `_merge_xlsx(events, out_path)` : reverse-parse → match → fill-gaps
    in-place → append des non-matchés → save.
  - Helpers : `_parse_existing_rows(ws)`, `_row_key(...)`, `_fill_gaps(...)`.
- `tapageur/validate.py` : exposer/clé commune de normalisation
  (`_source_ref_display` déjà présent ; factoriser une `source_display()` si
  besoin pour le matching incrémental).
- `tapageur/gui/app.py` : payload `write_mode` (remplace `append`), +
  `_debug_config` inchangé (write_mode conservé).
- `tapageur/gui/web/index.html` : radio 3 modes (Créer / Ajouter / Fusionner)
  à la place de la case append ; `applyConfig` restaure la sélection.

## Limites assumées (v1)

- Édition manuelle d'une **colonne-clé** (DATE/LIEU/ARTISTE) d'une ligne →
  match raté → doublon possible (inévitable sans ancre cachée type `date_iso`).
- **Lignes groupées** (festival multi-artistes) : clé ancrée sur le 1ᵉ artiste
  (comme `fingerprint()`). Un event isolé correspondant à un artiste
  non-premier d'une ligne groupée pourrait être ré-ajouté (cas rare).
- Mode incrémental : textes collés toujours re-traités ; nouveaux events d'une
  source déjà présente non récupérés (→ utiliser Fusionner).
- **Matching cross-source** (passe clappin & co) : un même event annoncé par
  deux agendas différents ne se complète QUE si DATE + LIEU + ARTISTE
  coïncident après canonicalisation. Un nom d'artiste orthographié différemment
  (ou un lieu absent de la liste d'alias) → pas de match → l'event tiers est
  **ajouté en doublon** au lieu de compléter. Les alias de lieux atténuent le
  risque côté LIEU ; côté ARTISTE il n'y a pas de normalisation (hors scope v1).
- **Corriger non supporté** : Fusionner complète les trous et ajoute, mais
  n'écrase jamais une valeur déjà présente (pas de mode « source prioritaire »
  en v1).

## Tests (principes)

- `_row_key` / normalisation : égalité malgré casse/accents/espaces.
- Fusion : match → complète un HEURE « ? » et un PRIX vide, préserve une heure
  déjà remplie, accole la SOURCE.
- Fusion : non-match → nouvelle ligne.
- Incrémental : une source déjà dans SOURCE est filtrée ; une nouvelle passe ;
  un texte collé passe toujours.
- Reverse-parse : lecture correcte par position (12 cols + blocs ACT).
- Fichier absent : les 3 modes se comportent comme « Créer ».
- Préservation de la mise en forme (écriture in-place, pas de reconstruction
  depuis le template en mode merge).
- Compte-rendu : une fusion qui ajoute 1 event et complète 1 ligne émet bien
  les lignes de détail « AJOUTÉ » / « COMPLÉTÉ (champs : …) » attendues.
- Use case clappin : passe Fusionner avec 2 URLs tierces → events manquants
  ajoutés, trous complétés, valeurs déjà remplies inchangées.
