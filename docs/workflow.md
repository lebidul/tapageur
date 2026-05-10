# Workflow mensuel

Guide pas à pas pour produire un mois de tapage biduleur, de la collecte au push Google Sheets.

## Vue d'ensemble du pipeline

```
collect   → cache/<month>/raw.json
normalize → cache/<month>/normalized.json   (via Claude API + cache item-level)
preview   → cache/<month>/preview.csv       (à valider à la main dans LibreOffice)
push      → Google Sheets
```

## Étape 0 — Préparer les sources

Avant `collect`, dépose les fichiers du mois dans la structure dédiée :

```bash
# Flyers, affiches, programmes — images ET PDFs acceptés
sources/docs/2026-06/concert_22.jpg
sources/docs/2026-06/festival_truc.pdf

# Mails utiles — exportés depuis Outlook (Classic ou Web)
sources/mailbox_export/2026-06/annonce_concert_X.msg
sources/mailbox_export/2026-06/programme_lieu_Y.eml
```

### Pour exporter les mails depuis Outlook

**Outlook Web (`outlook.live.com`)** : sélectionne les mails dans la liste, drag-and-drop vers le dossier Windows → fichiers `.eml`.

**Outlook Classic Desktop** : multi-sélection (Ctrl+clic), drag-and-drop **depuis un mail déjà sélectionné** → fichiers `.msg`. ⚠️ Si tu drag depuis un mail non-sélectionné, Outlook désélectionne tout et ne copie que celui-là. C'est un bug Outlook bien connu.

**Outlook "New" (la version 2024+)** : multi-drag cassé. Utilise Classic ou Web à la place.

### Pour les pièces jointes

Pas besoin de les extraire à la main : le connecteur `mailbox` **extrait automatiquement** les images et PDFs en pièce jointe et les traite comme des `CollectedItem` séparés (vision Opus). Inutile aussi de les remettre dans `sources/docs/` — risque de doublon.

## Étape 1 — `collect`

Lit la config, instancie chaque connecteur actif, parse les sources, écrit `cache/<month>/raw.json`.

### Avec la config par défaut

```bash
tapageur collect --month 2026-06
# → lit config/sources.yaml
```

### Avec une config mensuelle dédiée (recommandé)

```bash
tapageur collect --month 2026-06 -c config/sources_2026_06.yaml
```

Voir [sources.md](sources.md) pour la structure des configs et comment en créer une.

### Ce qui se passe sous le capot

Pour chaque connecteur actif :
1. Lit sa section de la config (`websites:`, `mailbox:`, `season_pdfs:`, `docs:`)
2. Fetche / lit / parse les sources de cette section
3. Yield des `CollectedItem` avec `source_kind` correct
4. Errors par connecteur isolées : si un site web foire, les autres connecteurs tournent quand même

**Sortie** : `cache/<month>/raw.json` contenant la liste de tous les `CollectedItem` collectés.

## Étape 2 — `normalize`

Appelle Claude pour chaque item, parse la sortie JSON, valide event-par-event, applique canonicalize + dedup.

### Mode synchrone (défaut)

```bash
tapageur normalize --month 2026-06
```

Le programme tourne jusqu'à ce que tous les items soient traités. Durée typique : ~30 sec à 2 min selon le nombre de sources.

### Mode batch (50% off, 24h SLA)

```bash
tapageur normalize --month 2026-06 --batch
# … jusqu'à 24h plus tard …
tapageur retrieve  --month 2026-06
```

Voir [batch.md](batch.md) pour les détails.

### Le cache item-level

À chaque appel Claude réussi, le résultat est caché dans `cache/normalize/<hash>.json` où `<hash> = sha256(source_ref + content_hash + month)`. Conséquences :

- **Re-runs gratuits** : tu peux relancer `normalize` autant que tu veux, seuls les items modifiés ou nouveaux re-passent par Claude.
- **Invalidation automatique** : si un site web change son contenu, le `content_hash` change → cache miss → re-call Claude → résultat à jour.
- **Invalidation manuelle** : `rm -rf cache/normalize/` purge tout, prochain run = paye plein tarif.

### Canonicalize + dedup

Après l'appel Claude, le code applique :
1. **Canonicalize** : remplace les variantes par les formes canoniques selon `config/mappings.yaml` (611 venues, ~684 alias). Ex: `"Le Scarron"` → `"Théâtre Paul Scarron"`.
2. **Dedup** : fingerprint `(date_iso, premier_horaire, venue, premier_performer)` ; en cas de collision, garde le premier.

**Sortie** : `cache/<month>/normalized.json` contenant la liste finale d'`Event`.

## Étape 3 — `preview`

Génère un CSV à partir de `normalized.json` pour validation manuelle dans un tableur.

```bash
tapageur preview --month 2026-06
# → cache/2026-06/preview.csv
```

### Que valider à la main

1. **Dates correctes** : Claude se trompe parfois sur l'année quand un PDF de saison mentionne plusieurs années.
2. **Lieux canoniques** : si un nouveau lieu n'est pas dans `mappings.yaml`, il sort tel quel. Ajoute-le à `mappings.yaml` pour les prochains mois, OU corrige à la main dans le CSV.
3. **Prix** : `"?"` signifie « Claude n'a pas trouvé ». À compléter si tu sais.
4. **Performer = "?"** : artiste/compagnie non identifiable dans la source. Idem, compléter si possible.
5. **Doublons résiduels** : 2 sources différentes peuvent annoncer le même event avec des libellés légèrement différents (genre différent, prix différent...). Le dedup ne les fusionne que si fingerprint identique.

### Ré-itérer après corrections

Si tu corriges un `mappings.yaml`, tu peux relancer :
```bash
tapageur normalize --month 2026-06   # cache hit, re-applique canonicalize sur la nouvelle table
tapageur preview   --month 2026-06   # nouveau CSV
```
Gratuit (cache).

## Étape 4 — `push`

Push le `preview.csv` validé vers Google Sheets.

```bash
tapageur push --month 2026-06
# Auth via sheets-sa.json (service account)
```

Variables d'environnement requises :
- `TAPAGE_SHEET_ID` : ID du Google Sheet cible
- `sheets-sa.json` : credentials service account au root du repo

## Troubleshooting

### `cache/<month>/raw.json n'existe pas`
Tu as lancé `normalize` avant `collect`. Lance `collect` d'abord.

### Un site web renvoie 403
Ajoute `needs_browser: true` à son entrée dans la config. Playwright (browser headless) sera utilisé au lieu de `requests`.

### Un PDF saison n'est pas re-parsé après modification
Le `parsed_cache` (JSON intermédiaire de pdfplumber) est sticky. Supprime-le manuellement : `rm cache/pdf_acthalia_25_26.json`.

### Coût Claude trop élevé sur un test
Vérifie que `MODEL_BY_KIND` route bien Sonnet sur les sources simples (web/outlook/fb) et Opus uniquement sur pdf/image. Voir `tapageur/normalize.py`.

### Le pipeline crashe sur `validation error` pendant normalize
Le fix bug 1 (commit `5fcd6ff`) skip les events invalides individuellement et log la cause. Regarde la sortie console : `[warn] event N invalide (acts.0.performer: ...): skip`. Si c'est un cas que tu veux récupérer, corrige le prompt Claude dans `tapageur/normalize.py::SYSTEM_PROMPT`.
