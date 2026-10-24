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

> Pour attaquer une feature : la cadrer (brainstorming) en répondant aux
> questions ouvertes ci-dessus, puis spec → plan → implémentation.
