# TODO — features à développer

Backlog des évolutions demandées. Chaque entrée sera cadrée (brainstorming →
spec → plan) avant implémentation. Les « Questions ouvertes » sont à trancher à
ce moment-là.

---

## 1. Mode debug (sauver / importer une config de passe) — ✅ FAIT (2026-10-25)

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

## 2. Sélection du mois : décision parente — ✅ FAIT (2026-10-25)

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

## 3. Exécutable téléchargeable (GitHub Releases) — ⚙️ implémenté (2026-10-25), build Windows à valider

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

## 5. Extraction : GENRE parfois rempli avec le STYLE — ✅ FAIT (2026-10-25, v9 : DJ→concert, coercition déterministe)

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

## 6. Message d'erreur clair sur échec d'authentification Anthropic (401) — ✅ FAIT (2026-10-25)

**But :** quand la clé API Anthropic est invalide/expirée (HTTP 401), afficher
un message explicite plutôt que l'erreur brute.

- Aujourd'hui : `run_extraction` catche l'exception → `{"error": str(e)}` →
  l'UI affiche le texte brut de l'erreur SDK (peu clair pour l'utilisateur).
- Voulu : détecter l'erreur d'authentification (ex. `anthropic.AuthenticationError`
  / HTTP 401) et renvoyer un message du type « Clé API Anthropic invalide ou
  expirée — vérifie-la dans Réglages. »

**Questions ouvertes :**
- Détection : attraper `anthropic.AuthenticationError` spécifiquement (plus
  robuste que de parser « 401 » dans le message).
- Étendre aux autres erreurs fréquentes ? (quota / rate limit 429, réseau).
- Où : dans `run_extraction` (ou `normalize_items`), mapper l'exception → message
  FR clair avant de remonter à l'UI.

---

## 7. (minor) Inclure l'option « mode debug » dans la config exportée — ✅ FAIT (2026-10-25)

**But :** que le fichier `config_<ts>.json` mémorise l'état de la case « mode
debug », et que l'import la restaure.

- Aujourd'hui : `app._debug_config` **exclut** `debug` (et `api_key`,
  `tapeur_email`) ; `applyConfig` ne touche pas `#debug-mode`.
- Voulu : conserver `debug` dans la config et, à l'import, recocher la case
  `#debug-mode` en conséquence.

**À faire :** retirer `"debug"` de la liste d'exclusion de `_debug_config` ;
dans `applyConfig`, `document.getElementById('debug-mode').checked = !!cfg.debug`.

---

## 8. Afficher le détail des événements extraits dans le Résumé — ✅ FAIT (2026-10-25)

**But :** pouvoir relire les events extraits directement dans l'app, sans
ouvrir le xlsx.

- Aujourd'hui : le Résumé montre la progression, le nombre d'events, le chemin
  de sortie et les alertes — mais pas le **contenu** des events.
- Voulu : lister chaque event extrait (date, lieu, artiste(s), heure, source…)
  dans la section Résumé.

**Questions ouvertes :**
- `run_extraction` renvoie déjà `results[].n_events` ; il faudrait remonter
  aussi les events (ex. `event_to_row` ou un sous-ensemble lisible) vers l'UI.
- Rendu : tableau compact par mois ? repli/dépli ? Tout via DOM/textContent
  (sécurité).
- Volume : tronquer / scroller si beaucoup d'events.

---

## 9. Extraction des images d'une page web (vision)

**But :** capter les events quand l'info est dans une **image** de la page (ex.
sites Wix comme `rencontresencoreheureux.org` : flyers .png, aucun texte HTML
exploitable → 0 event aujourd'hui).

- Aujourd'hui : le connecteur web ne lit que le **texte** HTML ; les images de
  page ne passent pas en vision.
- **Contournement actuel** : enregistrer l'affiche depuis la page et l'ajouter
  comme source **fichier** (qui passe déjà en vision).

**Questions ouvertes :**
- Quelles images envoyer en vision ? Une page Wix a des dizaines d'images
  (logos, déco, plusieurs flyers) → heuristique (taille mini, zone contenu) ou
  tout envoyer (coûteux/bruité) ?
- Télécharger + encoder les images (comme `_pdf_pages_to_images`) et créer un
  item image par flyer.
- Déclencher seulement si la page ne donne (presque) pas de texte / 0 event ?

---

## 10. Identifier la source dans le log live / Résumé — ⚙️ log live FAIT (2026-10-26), Résumé à faire

**État :** le log live préfixe désormais la source (`<site> : N pages à
récupérer` / `<site> — Page i/N : slug`, web.py). Reste à faire : grouper /
titrer les events **par source dans le Résumé**.

**But :** savoir à quelle source se rapportent les infos affichées pendant
l'extraction (log live) et dans le Résumé — au moins un en-tête en début de
section.

- Aujourd'hui : le log enchaîne des blocs anonymes (« 6 pages à récupérer »,
  « 5 pages à récupérer », « 9 pages à récupérer »…) et la liste `Page i/N :
  <slug>` sans indiquer de quel site/fichier il s'agit. Impossible de savoir
  que « 9 pages à récupérer » = le Festival CARAVANES (cpfi) ou que les
  `Agenda-NNNN` = musiquesmagiques.
- Voulu : préfixer chaque section par la source (nom du site / URL / fichier),
  ex. « === musiquesmagiques.fr === » avant son bloc « N pages à récupérer »,
  et idem côté Résumé (grouper / titrer les events par source).

**Questions ouvertes :**
- Le `progress(...)` actuel (web.py) émet « N pages à récupérer » / « Page i/N :
  slug » sans le `site_name` → ajouter le nom de la source dans ces messages.
- Côté Résumé : les events portent déjà `source_ref` (colonne SOURCE) ; on peut
  titrer/grouper par `source_ref` ou `site`.
- Granularité : un en-tête par source suffit (demande), vs. source sur chaque
  ligne (déjà le cas dans l'xlsx via la colonne SOURCE).
- Harmoniser avec les connecteurs docs/mailbox (mêmes préfixes de section).

---

## 11. Écriture fallback si le fichier cible est déjà ouvert

**But :** ne pas perdre toute l'extraction (collecte + appels modèle) quand le
fichier xlsx cible est verrouillé parce qu'ouvert dans Excel.

- Aujourd'hui (Windows) : si `tapage_2026-11.xlsx` est ouvert dans Excel, la
  sauvegarde openpyxl échoue (`PermissionError`) → le run entier est perdu, il
  faut tout refaire (re-fetch + re-normalisation, même si le cache aide).
- Voulu : en cas d'échec d'écriture sur le fichier cible, **écrire dans un
  fichier de repli** (ex. `tapage_2026-11 (1).xlsx` ou suffixe horodaté
  `tapage_2026-11__20261026_1742.xlsx`) au lieu de tout jeter, et **signaler
  clairement** le chemin de repli dans le Résumé / une alerte.

**Questions ouvertes :**
- Détection : attraper `PermissionError` (et `OSError` « file in use ») autour
  du `save()` dans `export_xlsx` / le chemin append (`_append_xlsx`).
- Nommage du repli : suffixe `(n)` incrémental vs horodaté. Horodaté = jamais
  de collision, plus lisible pour « c'est la version de secours ».
- Re-tenter d'abord (demander à l'utilisateur de fermer le fichier puis retry),
  ou basculer directement sur le repli sans interaction ? (le but étant de ne
  pas reperdre le process → repli direct, mais proposer un bouton « réessayer »
  serait un plus).
- S'applique aussi au mode « tous les mois » (plusieurs fichiers) : repli par
  fichier concerné.
- Idem pour les autres formats de sortie (csv, etc.) si verrouillés.

---

## 12. Pré-filtre par mois avant fetch (lire la date sur la carte d'agenda)

**But :** ne pas fetcher ni normaliser les pages détail d'events hors du mois
cible quand leur date est déjà visible sur la page d'agenda.

- Observé sur `https://leoliennearnage.fr/programme-concerts-spectacles/` : la
  page `giedre-maxi-best-of` (16 octobre) est fetchée alors que la cible est
  novembre → fetch + appel modèle inutiles (puis 0 event au filtre mois).
- Diagnostic : la date EST sur la carte d'agenda (conteneur Elementor qui
  contient le lien `/event/…` ET « 16 octobre 2026 »), mais `_filter_event_urls`
  reçoit un `get_text` À PLAT + la liste d'URLs → le modèle ne relie pas le slug
  à sa date et, par prudence (« en doute, inclure »), garde l'event.

**Approche retenue (A) — enrichir le signal du pré-filtre :**
- Extraire, pour chaque lien candidat, le texte de sa **carte** (plus petit
  ancêtre contenant le lien + une date) et passer au modèle des **paires
  explicites** `slug → texte de carte (avec date)` au lieu du blob à plat.
- Ajuster `PREFILTER_SYSTEM` pour exploiter la date de chaque carte et exclure
  les hors-mois ; garder la règle « en doute, inclure » quand aucune date n'est
  lisible sur la carte (date seulement sur la page détail) → zéro event perdu.
- Fichiers : `tapageur/connectors/web.py` (`_extract_subpages` / nouveau
  `_extract_card_snippets`, `_filter_event_urls`, `PREFILTER_SYSTEM`).

**Extension possible (C, plus tard) :** fast-path déterministe — parser la date
FR sur la carte et droper les hors-mois sans appeler le modèle, uniquement sur
une date lue avec certitude (sinon fallback A). Nécessite un parseur de dates FR
et une garde anti-sur-filtrage.

**À écarter :** le déterministe SEUL (risque de sur-filtrage = events perdus).

---

> Pour attaquer une feature : la cadrer (brainstorming) en répondant aux
> questions ouvertes ci-dessus, puis spec → plan → implémentation.
