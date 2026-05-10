# Sources : structure, config et types

## Structure des dossiers

Tout le contenu user-supplied vit sous `sources/` (gitignored sauf `.gitkeep`) :

```
sources/
├── pdfs_saison/                  # PDFs de saison (locaux uniquement)
│   ├── .gitkeep                  # tracké pour conserver le dossier vide
│   └── Programme Acthalia 25-26.pdf   # exemple (gitignored)
│
├── docs/                         # flyers + PDFs du mois
│   ├── .gitkeep
│   └── <YYYY-MM>/                # 1 sous-dossier par mois
│       ├── concert_22mai.jpg
│       └── festival_truc.pdf
│
└── mailbox_export/               # mails exportés depuis Outlook
    ├── .gitkeep
    └── <YYYY-MM>/                # idem, 1 sous-dossier par mois
        ├── annonce.eml
        └── programme.msg
```

## Types de sources et connecteurs

### `web` — sites web (HTML et PDFs URL)

Section `websites:` dans la config YAML.

```yaml
websites:
  # Page HTML standard
  - name: superforma
    url: https://superforma.fr/agenda
    needs_browser: true               # si nécessaire (anti-bot, JS lourd)
    follow_event_links: true          # par défaut : true (suit les liens de pages event)

  # Page HTML sans follow (raw dump direct)
  - name: petit_site
    url: https://petitsite.fr/agenda
    follow_event_links: false

  # PDF distribué via URL — détection auto par extension .pdf ou Content-Type
  - name: prog_mensuel_lieu_x
    url: https://lieuX.fr/programmes/juin-2026.pdf
    # Aucun champ supplémentaire : le web connector route automatiquement
```

**Détection PDF** : extension `.pdf` dans l'URL en priorité, sinon HEAD request → `Content-Type: application/pdf`. Si HEAD échoue (timeout, 405), traité comme HTML par défaut.

**Routage modèle** : `source_kind="web"` → Sonnet. `source_kind="pdf"` (cas URL PDF) → Opus.

### `pdf` — PDFs saison locaux

Section `season_pdfs:` dans la config YAML.

```yaml
season_pdfs:
  - path: "./sources/pdfs_saison/Programme Acthalia 25-26.pdf"
    parsed_cache: ./cache/pdf_acthalia.json
    label: "Programme saison 25-26 — Acthalia"
```

**Local uniquement** : depuis le refactor de `1cefadd`, ce connecteur **refuse** les URLs (`ValueError` claire si tu en mets une). Les PDFs distribués via URL doivent passer par la section `websites:` (voir ci-dessus).

**`parsed_cache`** : le texte extrait par pdfplumber est sauvé dans ce fichier JSON la première fois, puis réutilisé. Acthalia couvre toute une saison (sept→juin), donc 1 seule extraction pour tout le cycle annuel.

**Routage modèle** : `source_kind="pdf"` → Opus.

### `mailbox` — mails locaux (.eml / .msg)

Section `mailbox:` dans la config YAML.

```yaml
mailbox:
  base_dir: sources/mailbox_export
```

Le connecteur lit `<base_dir>/<month>/*.{eml,msg}`. Le `<month>` est passé en CLI (`--month 2026-06`).

**Comment exporter depuis Outlook** : voir [workflow.md](workflow.md#pour-exporter-les-mails-depuis-outlook).

**Pièces jointes** : extraites automatiquement comme `CollectedItem` séparés.
- `.jpg/.png/.webp/.gif` → `source_kind="image"` (Opus vision)
- `.pdf` → `source_kind="pdf"` (Opus, via pdfplumber)
- Autres (`.docx`, `.zip`, etc.) → skip silencieux

**Routage modèle** : `source_kind="outlook"` (corps du mail) → Sonnet.

### `docs` — fichiers du mois (images + PDFs déposés à la main)

Section `docs:` dans la config YAML.

```yaml
docs:
  paths:
    - sources/docs/{month}/              # dossier (substitution {month} auto)
    - sources/docs/2026-06/              # ou hardcodé
    - sources/special/festival_unique.pdf # fichier individuel
```

**Liste de paths** : chaque entry peut être un fichier OU un dossier.
- **Fichier** : routé par extension.
- **Dossier** : tous les fichiers à la racine du dossier sont routés (pas de récursion).

**Substitution `{month}`** : `{month}` dans les paths est remplacé par le mois cible passé en CLI. Permet une config permanente qui marche sur n'importe quel mois.

**Routage par extension** :
- `.jpg/.jpeg/.png/.webp/.gif` → `source_kind="image"` (Opus vision)
- `.pdf` → `source_kind="pdf"` (Opus, via pdfplumber)
- Autres → skip silencieux (`.DS_Store`, `.gitkeep`, etc.)

### Connecteurs désactivés

- **`outlook`** (Microsoft Graph API) : verrou Microsoft sur les App Registrations pour comptes MSA personnels (live.fr) sans tenant Azure. Bypass via `mailbox` (export manuel).
- **`fb`** (Facebook Graph API) : Meta cache les events repostés cross-page, et le scraping des pages event publiques renvoie 400 depuis 2020. Le code est conservé mais désactivé.

## Configs : permanente vs mensuelle

### Config permanente : `config/sources.yaml`

Sources récurrentes qui ne changent pas d'un mois à l'autre :
- Sites web installés (Superforma)
- PDFs saison
- Conventions de dossiers via `{month}` substitution

```bash
tapageur collect --month 2026-06   # utilise config/sources.yaml par défaut
```

### Config mensuelle : `config/sources_<YYYY>_<MM>.yaml`

Pour les mois où tu ajoutes des sources ad-hoc (sites web ponctuels, PDFs URL d'un festival spécifique...), copie la config permanente et adapte. Les paths peuvent être hardcodés `2026-06` plutôt que `{month}` — plus explicite pour l'audit historique.

```bash
tapageur collect --month 2026-06 -c config/sources_2026_06.yaml
```

Voir `config/sources_2026_06.yaml` pour un exemple commenté.

## Canonicalisation des lieux

Fichier `config/mappings.yaml` : ~611 noms canoniques de lieux + ~684 alias.

```yaml
venues:
  "Théâtre Paul Scarron":
    - "Le Scarron"
    - "Scarron"
    - "Paul Scarron"
    - "Th. Scarron"
  "L'Austral":
    - "Café L'Austral"
    - "café l'austral"
  ...
```

**Appliqué automatiquement** dans `normalize` (étape canonicalize). Matching case-insensitive + strip whitespace.

### Pour enrichir

Édite `config/mappings.yaml` à la main, ajoute une entrée :
```yaml
venues:
  "Nouveau Lieu Canonique":
    - "variante 1"
    - "variante 2"
```

Re-lance `normalize` : grâce au cache, les events déjà extraits restent (gratuit), seul le canonicalize est ré-appliqué. Si tu vois `"L'Austral"` corrigé partout après ton ajout, c'est OK.

### Pour import en masse depuis 2 listes (canoniques + alias)

Place 2 fichiers dans `cache/_import/` :
- `lieu_ref.txt` : 1 canonique par ligne
- `lieu_alias.tsv` : `variant<TAB>canonical` par ligne

Puis :
```bash
python scripts/import_mappings.py
```

Le script gère :
- Dédup automatique
- Résolution transitive (A→B→C devient A→C)
- Détection de canoniques mentionnés en alias mais absents de la liste

Les sections `artists`, `festivals`, `genres` sont préservées (édit à la main).

## Filtre temporel

```yaml
filter:
  margin_days: 3
```

`margin_days` permet d'inclure des events à cheval mois précédent/suivant (utile pour les festivals qui débordent). Pas encore utilisé par le code — Claude filtre strictement par `month` cible côté serveur via la consigne dans le prompt. À implémenter si besoin.
