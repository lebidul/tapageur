# Colonnes source dans la sortie (TYPE SOURCE / SOURCE) — Design

**Date :** 2026-10-24
**Statut :** validé (brainstorming), prêt pour plan
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Faire apparaître, pour **chaque ligne** du fichier de sortie (xlsx et CSV),
d'où provient l'événement :
- **TYPE SOURCE** : le type d'entrée (URL / Document / Image / Texte…) ;
- **SOURCE** : la référence lisible (URL, nom de fichier, « texte #1 »).

But : aider la relecture manuelle du fichier avant publication, en sachant
immédiatement d'où vient chaque ligne.

## 2. Contrainte biduleur — levée

Le fichier de sortie est repris tel quel par **biduleur** (repo de publication
`lebidul/biduleur`). Vérifié dans `biduleur/csv_utils.py` +
`biduleur/constants.py` :

- biduleur lit le fichier avec **pandas, par nom de colonne**, pas par
  position. Colonnes requises : `DATE`, `HEURE`, `FESTOCHE\nEVENEMENT `,
  `STYLE \nFESTOCHE / EVENEMENT `, `VILLE`, `LIEU`, `PRIX` ; blocs spectacle
  détectés par motif (`GENRE N`, `NOM SPECTACLE N`, `COMPAGNIE N`,
  `STYLE … SPECTACLE N`).
- **Toute colonne inconnue est ignorée.** Précédents existants de colonnes
  optionnelles ignorées si non lues : `INACTIF`, `DEVISE`, `DATE FIN`, `BIDUL`.
- Les noms `TYPE SOURCE` / `SOURCE` ne collisionnent avec aucun nom requis ni
  aucun motif spectacle.

**Conséquence : zéro changement côté biduleur.** Le travail tient entièrement
dans `tapageur`.

## 3. Les champs existent déjà

`Event` (schema.py) porte déjà :
- `source_kind: Literal["outlook","web","pdf","fb","image","text"]`
- `source_ref: str` (URL / message-id / chemin fichier)

Aucun changement de schéma. On se contente de les **rendre** dans la ligne.

## 4. Décisions (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Emplacement** | Les 2 colonnes **tout à gauche** (A = TYPE SOURCE, B = SOURCE). Tout le reste décalé de 2. Provenance = 1ère chose visible en relecture. |
| **TYPE SOURCE** | **Libellé français** (mapping lisible), pas le code brut. |
| **SOURCE** | **Référence nettoyée** (basename, page PDF, URL), pas le ref technique verbeux. |
| **CSV + xlsx** | Les deux (fonction `event_to_row` partagée). |

## 5. Mapping et nettoyage

### TYPE SOURCE — `source_kind` → libellé

| source_kind | libellé |
|-------------|---------|
| `web`       | URL |
| `pdf`       | Document |
| `image`     | Image |
| `text`      | Texte |
| `outlook`   | Email |
| `fb`        | Facebook |
| (autre)     | la valeur brute (fallback) |

### SOURCE — nettoyage de `source_ref`

- `web` → l'URL telle quelle.
- `text` → tel quel (ex. `texte #1`).
- `image` → **basename** du chemin (pas le chemin disque complet).
- `pdf` → `basename (p.N)` si le ref contient `#page=N`, sinon `basename`.
- `outlook` / `fb` → tel quel (message-id / URL).

Règle d'implémentation : isoler un éventuel suffixe `#page=N`, puis pour
`pdf`/`image` ne garder que le nom de fichier (`Path(part).name`) ; pour
`pdf` avec page, suffixer ` (p.N)`. Les autres types sont rendus inchangés.

## 6. Changements (tous dans `tapageur`)

### `tapageur/validate.py`
- `HEADERS_BASE` : préfixer `"TYPE SOURCE"`, `"SOURCE"` → 12 en-têtes de base.
  (`HEADERS`, constante historique de compat, suit automatiquement puisque
  `HEADERS = HEADERS_BASE + blocs ACT` ; vérifier les tests qui l'importent.)
- Nouveaux helpers :
  - `_source_type_label(source_kind: str) -> str` (mapping §5, fallback = brut).
  - `_source_ref_display(source_kind: str, source_ref: str) -> str` (nettoyage §5).
- `event_to_row(ev, n_acts=None)` : **préfixe** la ligne par
  `[_source_type_label(ev.source_kind), _source_ref_display(ev.source_kind, ev.source_ref)]`
  avant les colonnes A-J actuelles. Le reste (blocs ACT, mode festival)
  inchangé.

### `tapageur/gui/export_xlsx.py`
- `_N_FIXED_COLS` : 10 → **12**.
- `_write_act_headers` : inchangé (calcule `base = _N_FIXED_COLS + (i-1)*4`,
  donc suit la constante).
- `_append_xlsx` : `existing_blocks = (max_column - _N_FIXED_COLS) // 4`
  reste correct pour les fichiers créés par cette version (12 cols fixes).
- `export_xlsx` : inchangé (écrit `event_to_row` positionnellement depuis la
  colonne 1 ; les 2 nouvelles valeurs tombent en A-B).

### `tapageur/gui/assets/template.xlsx`
- Insérer **2 colonnes en tête** de la feuille `lebiduleur`
  (`ws.insert_cols(1, 2)`), puis poser `A1 = "TYPE SOURCE"`, `B1 = "SOURCE"`.
  Les en-têtes existants (INFO TAPEUR … PRIX, GENRE 1 …) glissent de 2 vers la
  droite et gardent leurs noms exacts attendus par biduleur. Feuilles de
  référence (`communes`, `salles_lieux`) **intactes**.

## 7. Tests

- `validate._source_type_label` : chaque `source_kind` → bon libellé ;
  valeur inconnue → brut.
- `validate._source_ref_display` :
  - `image` chemin → basename seul ;
  - `pdf` `…/flyer.pdf#page=2` → `flyer.pdf (p.2)` ;
  - `pdf` sans page → `flyer.pdf` ;
  - `web` URL → inchangé ; `text` `texte #1` → inchangé.
- `validate.event_to_row` : la ligne commence par `[libellé, ref nettoyée]`,
  puis INFO TAPEUR en 3ᵉ position ; longueur = 12 + 4·n_acts.
- `gui.export_xlsx` : `A1 == "TYPE SOURCE"`, `B1 == "SOURCE"` ;
  `C1 == "INFO TAPEUR"` (décalage) ; une valeur d'event tombe bien dans la
  bonne colonne (ex. LIEU en col J) ; en-têtes ACT au bon endroit ; append
  (2ᵉ fichier) conserve l'alignement.

## 8. Hors périmètre

- Compatibilité **append** entre un ancien fichier (10 cols, sans colonnes
  source) et la nouvelle version : non supporté ; on suppose un template
  homogène.
- Rendre `TYPE SOURCE` / `SOURCE` éditables dans l'UI.
- Exploitation de ces colonnes côté biduleur.
- Hyperlien cliquable dans `SOURCE` (texte simple uniquement).
