# Notes de version — tapageur-gui

> Ces notes sont publiées avec la Release GitHub du tag correspondant.
> Ajouter la nouvelle version **en tête**, puis taguer `vX.Y.Z`.

## 1.1.1 — 2026-10-27

Correction de doublons en mode « Ajouter ».

### Corrections
- **Textes collés ne créent plus de doublons** en mode **Ajouter** : un texte
  identique déjà traité est désormais reconnu (via le contenu) et ignoré, au
  lieu d'être réajouté à chaque passe. Un texte modifié reste bien retraité.

## 1.1.0 — 2026-10-27

Modes d'écriture, fusion/dédoublonnage et fiabilité d'extraction.

### Nouveautés
- **Trois modes d'écriture (xlsx)** au lieu de la simple case « Ajouter » :
  - **Créer / écraser** : fichier neuf.
  - **Ajouter (incrémental)** : n'extrait que les sources **non encore
    traitées** et ajoute leurs lignes.
  - **Fusionner** : complète les lignes existantes (remplit les trous HEURE /
    PRIX / FESTOCHE / … sans jamais écraser une valeur), ajoute les manquants,
    et accole la source. Idéal pour compléter avec un agenda tiers.
- **Manifeste des sources traitées** (feuille cachée `_sources_traitees`) :
  le mode incrémental ignore fiablement les sources déjà traitées, **y compris
  celles qui n'avaient produit aucun événement** (PDF/affiches hors-mois…).
- **Détail de la fusion** dans le Résumé/log : lignes « ajouté » / « complété »
  avec les champs renseignés.
- **Log en direct préfixé par la source** (quel site pour « N pages à
  récupérer »).

### Corrections / fiabilité
- **Extraction tolérante aux réponses très denses** : sur une page qui génère
  beaucoup d'événements, la sortie du modèle pouvait être tronquée et faire
  perdre **toute** la page ; désormais les événements valides sont conservés.
- **Pages d'événements en erreur (soft-404)** ignorées, avec repli sur la page
  d'agenda.
- Nouveaux **alias de lieux** (Twin's Beer, La Citadelle des Anges, L'Éolienne,
  Musée de la Musique Mécanique).

### Notes
- Ferme le fichier xlsx dans Excel avant une passe **Ajouter** / **Fusionner**
  (sinon l'écriture échoue).
- Exécutable à reconstruire/retaguer pour embarquer ces nouveautés.

## 1.0.1 — 2026-10-26

Fiabilisation de l'extraction (corrections suite aux tests).

### Corrections
- **Anti-confabulation (prompt v11)** : le modèle n'invente plus d'événements
  absents du contenu. Cas observé : une page de festival d'où sortait un
  festival de cinéma d'une autre ville, totalement absent du texte. Une page
  sans programme concret ne produit plus rien, et un contenu vide n'est plus
  envoyé au modèle.
- **Exclusion cinéma** renforcée (projections, festivals de film, « nuit du
  cinéma ») et **cafés philo / débats** désormais exclus.
- **Pages suivies en erreur (soft-404)** ignorées : quand un site renvoie une
  page « introuvable » en HTTP 200 pour ses liens d'événements, on se **replie
  sur la page d'agenda** (qui contient souvent tout le programme) au lieu de
  tout perdre.
- **Colonne FESTOCHE élargie** : capte le festival/cycle, sinon l'événement-
  cadre (ex. « Soirée Beaujolais »), sinon l'association/collectif organisateur.

### Notes
- Exécutable à reconstruire/retaguer pour embarquer ces correctifs.

## 1.0.0 — 2026-10-25

Première version distribuée (exécutable Windows one-file).

### Fonctionnalités
- Extraction d'événements culturels depuis **PDF / images** (affiches),
  **texte collé** et **URLs** (via le navigateur embarqué WebView2), vers le
  format du tableur biduleur (**xlsx / CSV / JSON**).
- **Overrides par élément** : lieu, asso/festival, mode « festival (une ligne) ».
- **Sélection du mois** : un mois précis (multi-mois possible), ou **tous les
  mois des sources** (un fichier par mois) avec année de référence éditable.
- **Colonnes de provenance** (`TYPE SOURCE` / `SOURCE`) et date au format
  « Jour N » (ex. `Mardi 2`) pour l'interop biduleur.
- Events **sans horaire** conservés (`HEURE = « ? »`) avec alerte.
- **Mode debug** : sauvegarde config + logs, import d'une config pour rejouer.
- **Thème sombre**, **glisser-déposer** de fichiers, **append** xlsx.
- **Suivi en direct** des événements extraits + **détail** dans le Résumé.
- **Message clair** si la clé API Anthropic est invalide/expirée.
- Extraction fiabilisée : l'année/le mois réels sont respectés (pas de report
  sur le mois cible), un set **DJ** est traité comme un concert.

### Notes
- Windows : nécessite le runtime **WebView2** (présent sur Windows récents).
- Les sites **anti-bot** (Cloudflare) peuvent ne rien renvoyer via le
  navigateur embarqué.
