# tapageur

Pipeline mensuel pour remplir le Google Sheet du **tapage biduleur** (Le Bidul / Radio Alpa) à partir de sources hétérogènes — sites web, PDFs, mails Outlook, flyers.

## Vue d'ensemble

```
Sources hétérogènes → Connecteurs → JSON brut → Claude (extraction) → Canonicalize + dedup → CSV preview → Google Sheets
```

| Source              | Connecteur  | Modèle    | Cadence                                          |
|---------------------|-------------|-----------|--------------------------------------------------|
| Sites web           | `web`       | Sonnet    | Mensuel — URLs récurrentes ; détecte PDFs URL    |
| PDFs saison locaux  | `pdf`       | Opus      | 1× par saison (cache disque ensuite)             |
| Mails (.eml/.msg)   | `mailbox`   | Sonnet    | Mensuel — drag-and-drop manuel depuis Outlook    |
| Docs du mois        | `docs`      | Opus      | Au cas par cas — images + PDFs déposés à la main |
| Page Facebook       | `fb`        | Sonnet    | **Désactivé** — Meta cache les reposts cross-page |
| Outlook (Graph API) | `outlook`   | Sonnet    | **Désactivé** — pas de tenant Azure sur compte MSA |

## Documentation

- [Guide utilisateur — tapageur-gui](docs/guide-utilisateur.md) : prise en main
  de l'application (sources, mois, modes d'écriture, Résumé, conseils).
- [Architecture](docs/architecture.md) : composants, flux de données et zoom sur
  le connecteur web (diagrammes Mermaid).

## Setup

```bash
cp .env.example .env       # remplir ANTHROPIC_API_KEY + autres clés
pip install -e ".[dev]"
playwright install chromium    # pour les sites web qui nécessitent un browser headless
```

## Workflow d'un mois

```bash
# 1. Préparer (drag-and-drop des fichiers dans les dossiers)
#    sources/docs/2026-06/         — flyers, affiches (images + PDFs)
#    sources/mailbox_export/2026-06/ — mails exportés depuis Outlook

# 2. Lancer le pipeline
tapageur collect    --month 2026-06 -c config/sources_2026_06.yaml
tapageur normalize  --month 2026-06
tapageur preview    --month 2026-06   # ouvrir le CSV dans LibreOffice, corriger
tapageur push       --month 2026-06   # vers Google Sheets
```

Détails complets : [docs/workflow.md](docs/workflow.md).

## Mode batch (50% off Claude)

Pour économiser ~50% sur le coût Claude quand tu peux attendre 24h :

```bash
tapageur normalize --month 2026-06 --batch   # submit + exit
# … jusqu'à 24h plus tard …
tapageur retrieve  --month 2026-06           # récupère + finalise
```

Détails : [docs/batch.md](docs/batch.md).

## Documentation

- **[docs/workflow.md](docs/workflow.md)** — Pipeline mensuel pas à pas, commandes, troubleshooting.
- **[docs/batch.md](docs/batch.md)** — Mode batch synchrone vs asynchrone, comment `retrieve` fonctionne.
- **[docs/sources.md](docs/sources.md)** — Types de sources, structure des dossiers, config par mois, canonicalisation des lieux.

## Structure du repo

```
tapageur/
├── config/
│   ├── sources.yaml          # config par défaut (sources permanentes)
│   ├── sources_<YYYY>_<MM>.yaml  # configs mensuelles dédiées (optionnel)
│   └── mappings.yaml         # 611 venues canoniques + alias
├── tapageur/                 # package Python
│   ├── cli.py                # entry point (collect / normalize / retrieve / preview / push)
│   ├── schema.py             # Pydantic models alignés sur le sheet
│   ├── connectors/           # 1 module par source
│   ├── normalize.py          # appel Claude (Sonnet/Opus selon source_kind)
│   ├── batch.py              # Message Batches API (50% off, 24h SLA)
│   ├── cache.py              # cache item-level (source_ref + content_hash + month)
│   ├── dedup.py              # canonicalize + dedup
│   ├── validate.py           # export CSV pour relecture
│   └── push.py               # gspread → Google Sheet
├── sources/                  # données user (gitignored sauf .gitkeep)
│   ├── pdfs_saison/          # PDFs de saison (locaux uniquement)
│   ├── docs/<YYYY-MM>/       # flyers + PDFs du mois
│   └── mailbox_export/<YYYY-MM>/   # .eml / .msg exportés
├── cache/                    # raw + normalized par mois (gitignored)
├── scripts/                  # outils ponctuels (import_mappings, tests ad-hoc)
└── tests/                    # 79 tests pytest
```

## Schéma cible

Aligné sur le Google Sheet `tapage_biduleur`. Une ligne = un événement à un lieu et une date donnée, avec **N actes regroupés** (N est dynamique : pas de limite, le CSV génère autant de blocs ACT que nécessaire — biduleur supporte ce format depuis [PR #106](https://github.com/lebidul/biduleur/pull/106)). Voir `tapageur/schema.py`.

## Commandes CLI

```bash
# Toutes les commandes acceptent --month répétable pour le multi-mois (bidul d'été)
tapageur collect    --month 2026-06 [-c CONFIG] [--site X] [--connector Y]
tapageur normalize  --month 2026-06 [--batch]
tapageur retrieve   --month 2026-06               # finalise un batch (si --batch utilisé)
tapageur preview    --month 2026-06               # CSV pour validation manuelle
tapageur push       --month 2026-06               # → Google Sheets

# Bidul d'été : juillet + août en 1 commande chaque étape
tapageur collect    --month 2026-07 --month 2026-08 -c config/sources_summer_2026.yaml
tapageur normalize  --month 2026-07 --month 2026-08
tapageur preview    --month 2026-07 --month 2026-08
tapageur push       --month 2026-07 --month 2026-08
```

Détails : [docs/workflow.md](docs/workflow.md) (avec sous-sections sur le mode festival onliner, le mode sélectif `--site`/`--connector`, et les 3 passes canonicalize/dedup/group).
