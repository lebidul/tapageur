# TODO — features à développer

Backlog des évolutions demandées. Chaque entrée sera cadrée (brainstorming →
spec → plan) avant implémentation. Les « Questions ouvertes » sont à trancher à
ce moment-là.

---

## 1. Mode debug (sauver / importer une config de passe)

**But :** pouvoir rejouer et diagnostiquer une extraction.

- **Sauver les logs** d'une passe dans un fichier (le flux console actuel :
  collecte, extraction par item, cache hit/miss, warnings, onliner…).
- **Sauver la config** de la passe (tout ce qui décrit l'entrée : fichiers +
  overrides lieu/asso/festival, URLs, textes collés, mois, formats, dossier de
  sortie, append, no-filter). Export JSON.
- **Importer une config** : recharger ce fichier pour rejouer une passe à
  l'identique (repeupler l'UI et/ou lancer directement).

**Questions ouvertes :**
- La config inclut-elle les textes collés / le contenu, ou seulement des
  références ? (les fichiers sont des chemins disque, les textes sont du
  contenu inline).
- La clé API est un secret → **exclue** de la config exportée (à confirmer).
- Où écrire logs + config ? (dossier de sortie, sous-dossier `debug/` ?).
- Déclencheur : une case « mode debug » dans l'UI, ou toujours actif ?
- Import = repeupler l'UI (revue avant lancement) ou lancer tel quel ?

---

## 2. Sélection du mois : décision parente

**But :** clarifier le choix du périmètre temporel.

- Décision **parente** à deux branches :
  1. **Extraire un mois en particulier** → l'utilisateur saisit le mois
     (`YYYY-MM`) ; comportement actuel (filtre strict, 1 fichier de sortie).
  2. **Extraire tous les mois des sources** → **un fichier de sortie par mois**
     détecté dans les events (ex. `tapage_2026-11.xlsx`, `tapage_2026-12.xlsx`).
- Remplace l'actuel couple « champ mois » + case « ne pas filtrer par mois »
  (qui, aujourd'hui, produit un seul fichier `tous`).

**Questions ouvertes :**
- « Tous les mois » : extraire sans filtre, puis **grouper les events par mois**
  (`date_iso` → `YYYY-MM`) et exporter un fichier par groupe. Gérer les events
  festival (groupés sur le mois de leur `date_iso`).
- Nommage des fichiers par mois (déjà `tapage_<label>.*`, cohérent).
- Interaction avec l'année devinée : « tous les mois » redonne le hint « tous
  les mois » au modèle → risque de mauvaise année (cf. règle ANNÉE). À vérifier.
- UI : radio parent (mois précis / tous) + champ mois conditionnel.
- Impact code : `service.run` (construction des `passes`), `RunRequest`
  (remplacer `months` + `no_month_filter`), `app.py` (payload), `index.html`.

---

## 3. Exécutable téléchargeable (GitHub Releases)

**But :** distribuer l'app à des non-développeurs, publiée à chaque version.

- Construire un **exécutable autonome** (Windows en priorité) de `tapageur-gui`.
- **Publier sur GitHub Releases** automatiquement à chaque nouvelle version
  (tag).

**Questions ouvertes :**
- Outil de packaging : **PyInstaller** (le plus courant pour pywebview).
- Bundler les assets : `template.xlsx`, binaires `pypdfium2`, runtime WebView2
  (Edge Chromium déjà présent sur Windows récents ?), icône.
- Schéma de version / tag (ex. `v0.1.0`) et lien avec `PROMPT_VERSION`.
- CI : workflow GitHub Actions déclenché sur tag → build → upload en asset de
  Release. Runner `windows-latest`.
- Gestion de la clé API côté utilisateur final (saisie dans l'app, stockée dans
  les réglages locaux — déjà le cas).
- macOS/Linux plus tard ?

---

## 4. Merger au lieu d'ajouter (dédoublonnage à l'append)

**But :** au lieu d'ajouter aveuglément les nouvelles lignes à un fichier
mensuel existant, **fusionner** en retirant les doublons (ne pas ré-insérer un
event déjà présent).

- Aujourd'hui : `append=True` (`_append_xlsx`) ajoute les lignes à la suite,
  sans vérifier les doublons (volontaire : préserver les corrections Excel).
- Voulu : fusion dédoublonnée — un event déjà présent dans le fichier n'est pas
  ré-ajouté.

**Questions ouvertes :**
- **Clé de dédoublonnage vs xlsx existant** : `Event.fingerprint` utilise
  `date_iso`, qui **n'est PAS écrit** dans le xlsx (seule la col DATE « Jour N »
  l'est). Il faut donc soit fingerprinter à partir des colonnes visibles
  (DATE + HEURE + LIEU + ARTISTE), soit stocker `date_iso` quelque part. À
  cadrer (risque de faux positifs/négatifs).
- En cas de doublon : garder la ligne **existante** (préserver les corrections
  manuelles du tapeur) et ignorer la nouvelle — à confirmer.
- Fusion contre un fichier **édité à la main** dans Excel (lignes modifiées) :
  le parsing inverse doit être robuste.
- Remplace « Ajouter au fichier existant » ou devient une 3ᵉ option
  (recréer / ajouter / fusionner) ?

---

## 5. Extraction : GENRE parfois rempli avec le STYLE

**Bug d'extraction observé** (mars 2027) : la colonne `GENRE 2` d'un event a été
peuplée avec `dj` (qui est en réalité le **STYLE**) au lieu d'un genre attendu
(`c` / `sv`). Le modèle confond le slot GENRE et le slot STYLE pour les actes
secondaires.

**À investiguer :**
- `dj` est une valeur de `Genre` valide ET un descripteur de style courant →
  ambiguïté. Clarifier dans le prompt la distinction GENRE (c/sv/expo/dj/autre)
  vs STYLE (texte libre), surtout pour les actes 2+.
- Vérifier sur `tapage_2027-03.xlsx` (exemple fourni) le cas précis.
- Possibles pistes : renforcer le schéma/prompt, ou validation post-extraction
  (un style ne doit pas atterrir en genre).

---

> Pour attaquer une feature : la cadrer (brainstorming) en répondant aux
> questions ouvertes ci-dessus, puis spec → plan → implémentation.
