# tapageur

Pipeline mensuel pour remplir le Google Sheet du **tapage biduleur** (Le Bidul / Radio Alpa) à partir de sources hétérogènes.

## Workflow

```
Sources → Connecteurs → JSON brut → Normalisation Claude → Validation → Google Sheets
```

| Source            | Connecteur     | Cadence                                    |
|-------------------|----------------|--------------------------------------------|
| Mailbox Outlook   | `outlook.py`   | Chaque mois (dossier `Bidul/Agendas`)       |
| Sites web         | `web.py`       | Chaque mois (URLs récurrentes)              |
| PDFs saison       | `pdf.py`       | 1× par saison (caché ensuite)               |
| Page Facebook     | `fb.py`        | Chaque mois (events de notre page)          |
| Flyers / images   | `images.py`    | Au cas par cas (dossier mensuel)            |

## Usage

```bash
# Setup une fois
cp .env.example .env  # remplir clés
pip install -e ".[dev]"
playwright install chromium

# Pour chaque mois
make month=2026-06         # collecte + normalisation → CSV preview
# ... validation manuelle dans LibreOffice ...
make push month=2026-06    # push validé vers Google Sheets
```

## Structure

```
tapageur/
├── config/
│   ├── sources.yaml       # URLs, labels Gmail, page FB, dossiers flyers
│   └── mappings.yaml      # canonicalisation lieux + artistes
├── tapageur/              # package Python
│   ├── cli.py             # entry point (collect / normalize / preview / push)
│   ├── schema.py          # Pydantic models alignés sur les colonnes du sheet
│   ├── connectors/        # 1 module par source
│   ├── normalize.py       # appel Claude API + filtre mois courant
│   ├── dedup.py           # fingerprint + mappings canoniques
│   ├── validate.py        # export CSV pour relecture
│   └── push.py            # gspread → Google Sheet
├── cache/                 # raw + normalized par mois (gitignored)
├── flyers/                # images à OCRiser, organisées par mois (gitignored)
└── scripts/
    └── parse_season_pdf.py  # outil ponctuel saison
```

## Schéma cible

Aligné sur le Google Sheet `tapage_biduleur` existant — voir `tapageur/schema.py`. Une ligne = un événement à un lieu et une date donnés, avec jusqu'à 4 artistes/spectacles regroupés (cols M/Q/U/Y).

## Commandes CLI

```bash
tapageur collect --month 2026-06    # collecte → cache/2026-06/raw.json
tapageur normalize --month 2026-06  # Claude API → cache/2026-06/normalized.json
tapageur preview --month 2026-06    # CSV pour validation manuelle
tapageur push --month 2026-06       # gspread → Google Sheet
```
