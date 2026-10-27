# Manifeste des sources traitées (skip incrémental robuste) — design

**Date :** 2026-10-26
**Contexte :** complète le mode « Ajouter (incrémental) » de la feature
write-mode (merge/dédoublonnage). Remplace l'heuristique de skip actuelle
(colonne SOURCE + hôte) qui ne voit pas les sources ayant produit 0 ligne.

## Problème

Le skip incrémental actuel compare les sources saisies à la **colonne SOURCE**
du fichier. Or :
- La colonne SOURCE n'enregistre que les sources ayant produit **≥1 event
  survivant**. Une source filtrée à **0 ligne** (hors-mois, expos/cafés philo
  exclus, rien d'extrait) n'y figure pas → re-traitée à chaque passe (cas
  observé : `Saison Culturelle 26-27.pdf`, plusieurs `.avif`).
- Pour les sites **à suivre**, la colonne garde les **pages détail**, pas
  l'URL d'agenda saisie → match impossible (contourné en interim par l'hôte).

Une colonne « id » **par ligne** aurait le même défaut (0 ligne = 0 id écrit).

## Solution : manifeste des sources traitées

Un **manifeste** = la liste de **toutes les sources traitées** lors d'une
passe (même celles à 0 event), stocké dans une **feuille cachée** de l'xlsx
cible. Le manifeste porte sur les **entrées** (ce que l'utilisateur saisit),
pas sur les events → le service le calcule directement depuis `RunRequest`,
**sans toucher** au schéma `Event`, à `event_to_row`, au template, ni à
`_N_FIXED_COLS`.

### Identifiant de source (par type)

- **URL (web)** : l'URL saisie (`UrlInput.url`) — pour un site à suivre c'est
  l'URL d'agenda, exactement ce que l'utilisateur re-saisira.
- **Fichier / image** : le **basename** (`Path(path).name`). Robuste si le
  fichier est redéposé depuis un autre dossier.
- **Texte collé** : `texte:<hash>` — **hash SHA1 du contenu** (stable).
  Un texte identique déjà traité est reconnu dans le manifeste et **skippé**
  en mode Ajouter (évite le ré-ajout de ses events = doublons). Un texte
  modifié a un hash différent → retraité. (Révision du choix initial « texte
  #N positionnel, toujours traité » qui dupliquait les events du texte à
  chaque passe « Ajouter ».)

### Feuille cachée `_sources_traitees`

- Nom : `_sources_traitees`, `sheet_state="hidden"`.
- Colonnes : `id` | `type` | `date_passe` (ISO). Une ligne par source traitée.
- Union sans doublon sur `(id, type)` : une source déjà présente n'est pas
  réécrite (la `date_passe` d'origine est conservée).

### Comportement par mode d'écriture

- **Créer / écraser** : manifeste **neuf** = toutes les sources de la passe.
- **Ajouter (incrémental)** :
  1. Lire le manifeste du fichier cible.
  2. **Skipper** les file/url inputs dont l'id ∈ manifeste (textes toujours
     gardés). Émettre « Incrémental : N source(s) déjà traitée(s) ignorée(s). »
  3. Après la passe, **unionner** les sources traitées (y compris celles à 0
     event) dans le manifeste.
- **Fusionner** : **pas de skip** (le but est de re-traiter pour compléter,
  ex. passe clappin). Mettre à jour (union) le manifeste.

### Repli (fichiers sans manifeste)

Un fichier existant **sans** feuille `_sources_traitees` (créé avant cette
feature) → le mode Ajouter retombe sur l'heuristique actuelle
(`_filter_present_sources` : colonne SOURCE + hôte). Toute passe qui écrit le
fichier crée/complète désormais le manifeste → les passes suivantes l'utilisent.

### Portée temporelle

- Manifeste **par fichier de sortie** (`tapage_2026-11.xlsx` a le sien) →
  cohérent avec les fichiers mensuels.
- Skip incrémental appliqué en **mode spécifique mono-mois** (comme l'actuel).
  En mode « tous les mois », pas de skip ; le manifeste est écrit dans chaque
  fichier mensuel (mêmes entrées pour tous les mois).

## Impact code

- `tapageur/gui/export_xlsx.py` :
  - `read_processed_sources(out_path) -> set[str]` : lit la feuille cachée
    (col `id`) ; `set()` si feuille/fichier absents.
  - `record_processed_sources(out_path, sources: list[tuple[str,str]]) -> None`
    : ouvre le fichier, crée la feuille cachée si absente, unionne `(id, type)`
    + `date_passe`, sauvegarde (via `_save_workbook`).
  - `has_manifest(out_path) -> bool` : la feuille existe-t-elle (pour décider
    skip-manifeste vs repli).
- `tapageur/gui/service.py` :
  - `_input_source_ids(req) -> list[tuple[str,str]]` : (id, type) pour
    files (basename, "Document"/"Image"), urls (url, "URL"), texts
    ("texte:<hash>", "Texte") — hash du contenu.
  - `_filter_present_sources` (mode Ajouter) : si `has_manifest(target)` →
    skip via `read_processed_sources` (exact, textes gardés) ; sinon repli
    heuristique actuelle (SOURCE + hôte).
  - En fin de `run` (tous modes), appeler `record_processed_sources(target,
    input_ids)` pour chaque fichier écrit.
- Pas de changement : `Event`, `event_to_row`, template, `_N_FIXED_COLS`,
  colonnes du merge.

## Limites assumées

- **Textes collés** : matchés par hash de contenu ; un texte modifié est
  retraité (events potentiellement en double si l'ancien reste dans le fichier).
- Si l'utilisateur **supprime manuellement** la feuille cachée, on retombe sur
  le repli (re-traitement possible).
- Le manifeste suit le fichier (feuille cachée) → robuste au
  déplacement/copie de l'xlsx, et survit aux édits Excel.
- Mode « tous les mois » : pas de skip (seulement l'écriture du manifeste).

## Tests (principes)

- `record_processed_sources` crée une feuille cachée ; relecture via
  `read_processed_sources` ; union sans doublon (date d'origine conservée).
- La feuille est bien `hidden` et n'interfère pas avec l'export des events.
- Ajouter : une source (y compris à 0 event) présente au manifeste est
  skippée ; une nouvelle passe ; un texte est toujours gardé.
- Repli : fichier sans manifeste → heuristique SOURCE + hôte (comportement
  actuel conservé).
- Fusionner : aucune source skippée ; manifeste mis à jour.
- Fichier absent : Créer écrit un manifeste neuf.
