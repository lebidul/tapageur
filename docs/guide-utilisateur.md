# Guide utilisateur — tapageur-gui

`tapageur-gui` est l'application de bureau qui extrait les événements culturels
de tes sources (affiches, programmes PDF, agendas en ligne, texte collé) et
produit un fichier au format du tableur biduleur.

## 1. Lancer l'application

- **Exécutable Windows** : télécharge le `.exe` depuis les
  [Releases GitHub](https://github.com/lebidul/tapageur/releases) et double-clique.
- **Depuis le code** (développeurs) : dans l'environnement Python du projet,
  lance la commande `tapageur-gui`.

## 2. Réglages (à faire une fois)

Dans la section **Réglages** :

- **Clé API Anthropic** : ta clé (nécessaire — c'est Claude qui lit les sources).
- **Email tapeur** : ton identifiant, repris dans la colonne INFO TAPEUR.
- Clique **Enregistrer les réglages** (la clé est stockée localement, jamais
  dans les fichiers de config exportés).

Le bouton **Importer une config** recharge une passe précédente (voir le mode
debug plus bas).

## 3. Ajouter des sources

Trois types de sources, cumulables dans une même passe.

### Fichiers (affiches, programmes)
- Formats acceptés : **PDF, JPG, PNG, WebP, GIF, AVIF**.
- **Glisser-déposer** les fichiers sur la zone prévue, ou **Choisir des fichiers**.
- Options par fichier :
  - **Lieu** : force le lieu si l'affiche ne le dit pas clairement.
  - **Info orga** : nom de l'organisateur / asso / festival (va en colonne
    FESTOCHE si l'extraction n'en trouve pas).
  - **Festival (une ligne)** : coche pour résumer tout le fichier en **une
    seule ligne** « festival » (utile pour une affiche de festival).

### URLs (agendas en ligne)
- Colle l'URL d'une page d'agenda.
- Options par URL :
  - **Suivre les liens** : explore les pages d'événements liées à l'agenda
    (pagination incluse) et ne télécharge que les events **du mois ciblé**.
    Laisse décoché pour un agenda qui tient sur une seule page.
  - **Lieu**, **Info orga**, **Festival** : comme pour les fichiers.

### Texte collé
- Colle du texte brut (ex. un programme reçu par message).
- Options : **Lieu**, **Info orga**, **Festival**.

## 4. Choisir le mois

- **Un mois précis** : saisis le mois au format `AAAA-MM` (ex. `2026-11`) ; seuls
  les events de ce mois sont gardés, dans un seul fichier.
- **Tous les mois des sources** : extrait tout et produit **un fichier par mois**
  détecté. Une **année de référence** sert à dater les events qui n'indiquent pas
  l'année.

## 5. Sortie

- **Formats** : `xlsx` (le principal), `csv`, `json` (cases à cocher).
- **Écriture (xlsx)** — trois modes :
  - **Créer / écraser** : fichier neuf (écrase un fichier existant).
  - **Ajouter (incrémental)** : n'extrait que les **sources non encore traitées**
    (lues dans le fichier) et ajoute leurs lignes. Rapide pour « j'ai juste
    ajouté une source ».
  - **Fusionner** : complète les lignes existantes (remplit les trous HEURE /
    PRIX / … **sans jamais écraser** une valeur) et ajoute les events manquants.
    Idéal pour compléter avec un agenda tiers.
- **Dossier de sortie** : où écrire les fichiers (`tapage_<mois>.xlsx`, …).

## 6. Mode debug

La case **mode debug** sauvegarde, dans un sous-dossier `debug/`, la **config**
de la passe (sans la clé API) et le **log** complet. Pratique pour rejouer une
extraction (via **Importer une config**) ou diagnostiquer un souci.

## 7. Lancer et lire le résultat

Clique **Lancer l'extraction**. Pendant la passe :

- Le **log en direct** affiche la progression, horodatée `[HH:MM:SS] [mm:ss]`
  (heure système + temps écoulé), préfixée par la source (ex.
  `leoliennearnage.fr : 6 pages à récupérer`).
- Le **Résumé** liste, **groupés par source**, les events extraits (date, lieu,
  artistes, heure), les compteurs, les **alertes** (prix / horaire / artiste
  manquant, lieu ou ville hors liste de référence — avec la source entre
  crochets), et, en mode Fusionner, le détail `+ AJOUTÉ` / `~ COMPLÉTÉ`.
- À la fin : « **Terminé en Xm Ys** ».

Le fichier `tapage_<mois>.xlsx` est écrit dans le dossier de sortie, au format
biduleur (colonnes TYPE SOURCE, SOURCE, FESTOCHE, DATE, HEURE, LIEU, VILLE,
PRIX, puis les blocs GENRE / NOM / ARTISTE / STYLE par acte). Il contient aussi
une **feuille cachée `_sources_traitees`** (le « manifeste » qui permet au mode
Ajouter d'ignorer les sources déjà faites).

## 8. Conseils & pièges

- **Ferme le fichier xlsx dans Excel** avant une passe **Ajouter** ou
  **Fusionner** (sinon l'écriture échoue — le fichier est verrouillé).
- **« Info orga »** est le levier le plus simple pour imposer un festival /
  organisateur à toutes les lignes d'une source.
- Les events **hors du mois ciblé** sont écartés (et, pour les agendas suivis,
  souvent **avant** le téléchargement, grâce au pré-filtre par mois).
- Certains sites **anti-bot** (Cloudflare) peuvent ne rien renvoyer.
- Après avoir **reconstruit** l'app, relance-la pour charger les nouveautés.

## 9. Personnalisation (config)

Ces fichiers sont embarqués dans l'exe (modifier puis reconstruire) :

- `config/mappings.yaml` — **formes canoniques** des lieux / artistes /
  festivals et leurs **alias** (ex. « TWINS BEER » → « Twin's Beer »). Évite les
  doublons dus aux variantes d'orthographe.
- `config/venue_defaults.yaml` — **défauts par lieu** appliqués uniquement si
  l'info manque : `time` (horaire), `price` (tarif), `city` (ville). Ex. un lieu
  dont l'heure est toujours la même, ou dont la ville se déduit du nom.

Voir aussi [architecture.md](architecture.md) pour le fonctionnement interne.
