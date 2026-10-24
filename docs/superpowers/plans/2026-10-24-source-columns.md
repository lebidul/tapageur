# Colonnes source (TYPE SOURCE / SOURCE) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter deux colonnes de provenance (`TYPE SOURCE`, `SOURCE`) en tête de chaque ligne du fichier de sortie (CSV et xlsx), pour la relecture.

**Architecture:** Les champs `source_kind` / `source_ref` existent déjà sur `Event`. On les rend lisibles via deux helpers dans `validate.py`, on les préfixe dans `event_to_row` (partagé CSV + xlsx), on fait passer `_N_FIXED_COLS` de 10 à 12 dans l'export xlsx, et on régénère le `template.xlsx` avec les deux en-têtes en tête. biduleur lit par nom de colonne et ignore les colonnes inconnues → aucun changement côté biduleur.

**Tech Stack:** Python 3.11+, pydantic v2, openpyxl, pytest.

## Global Constraints

- **biduleur n'est PAS modifié.** La compatibilité repose sur le fait qu'il lit par nom de colonne et ignore les inconnues.
- En-têtes exacts des 2 nouvelles colonnes : `"TYPE SOURCE"` (col A) et `"SOURCE"` (col B). Tout le reste décalé de 2 vers la droite.
- `_N_FIXED_COLS == 12` après la feature.
- Mapping TYPE SOURCE : `web`→`URL`, `pdf`→`Document`, `image`→`Image`, `text`→`Texte`, `outlook`→`Email`, `fb`→`Facebook`, inconnu→valeur brute.
- Nettoyage SOURCE : `pdf`/`image`→basename ; `pdf` avec `#page=N`→`basename (p.N)` ; `web`/`text`/`outlook`/`fb`→inchangé.
- Les feuilles de référence du template (`communes`, `salles_lieux`, `date`) restent intactes.
- Message de commit terminé par : `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1 : `validate.py` — helpers + préfixe dans `event_to_row` (CSV)

**Files:**
- Modify: `tapageur/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consomme : `Event.source_kind`, `Event.source_ref` (schema.py, déjà présents).
- Produit :
  - `_source_type_label(source_kind: str) -> str`
  - `_source_ref_display(source_kind: str, source_ref: str) -> str`
  - `event_to_row(ev, n_acts=None) -> list[str]` renvoie désormais **12** colonnes fixes + 4·n_acts : `[TYPE SOURCE, SOURCE, INFO TAPEUR, DATE TAPAGE, DATE EMISSION RADIO, FESTOCHE, STYLE FESTOCHE, DATE, HEURE, LIEU, VILLE, PRIX, GENRE 1, …]`.
  - `HEADERS_BASE` = 12 entrées (préfixées de `"TYPE SOURCE"`, `"SOURCE"`).

- [ ] **Step 1 : Écrire les tests des helpers (échec attendu)**

Ajouter dans `tests/test_validate.py` (après les imports, importer les helpers) :

```python
from tapageur.validate import _source_type_label, _source_ref_display


def test_source_type_label_mapping():
    assert _source_type_label("web") == "URL"
    assert _source_type_label("pdf") == "Document"
    assert _source_type_label("image") == "Image"
    assert _source_type_label("text") == "Texte"
    assert _source_type_label("outlook") == "Email"
    assert _source_type_label("fb") == "Facebook"


def test_source_type_label_unknown_falls_back_to_raw():
    assert _source_type_label("inconnu") == "inconnu"


def test_source_ref_display_image_is_basename():
    assert _source_ref_display("image", r"C:\dossier\flyer.png") == "flyer.png"


def test_source_ref_display_pdf_with_page():
    assert _source_ref_display("pdf", r"C:\dossier\prog.pdf#page=2") == "prog.pdf (p.2)"


def test_source_ref_display_pdf_without_page():
    assert _source_ref_display("pdf", r"C:\dossier\prog.pdf") == "prog.pdf"


def test_source_ref_display_web_and_text_unchanged():
    assert _source_ref_display("web", "https://example.com/x") == "https://example.com/x"
    assert _source_ref_display("text", "texte #1") == "texte #1"
```

- [ ] **Step 2 : Lancer → échec**

Run: `python -m pytest tests/test_validate.py -k "source_type_label or source_ref_display" -q`
Expected: FAIL (ImportError : les helpers n'existent pas).

- [ ] **Step 3 : Implémenter les helpers + la constante dans `validate.py`**

`Path` est déjà importé (`from pathlib import Path`). Ajouter après `FESTIVAL_DATE_MARKER` :

```python
# Libellés lisibles pour la colonne TYPE SOURCE (col A).
_SOURCE_TYPE_LABELS = {
    "web": "URL",
    "pdf": "Document",
    "image": "Image",
    "text": "Texte",
    "outlook": "Email",
    "fb": "Facebook",
}


def _source_type_label(source_kind: str) -> str:
    """Libellé français du type de source ; valeur brute si inconnue."""
    return _SOURCE_TYPE_LABELS.get(source_kind, source_kind)


def _source_ref_display(source_kind: str, source_ref: str) -> str:
    """Référence lisible pour la colonne SOURCE.

    pdf/image → nom de fichier seul ; pdf avec '#page=N' → 'fichier (p.N)'.
    Les autres types (web/text/outlook/fb) sont rendus inchangés.
    """
    ref = source_ref or ""
    if source_kind in ("pdf", "image"):
        path_part, _, frag = ref.partition("#")
        name = Path(path_part).name or ref
        if source_kind == "pdf" and frag.startswith("page="):
            page = frag[len("page="):]
            if page:
                return f"{name} (p.{page})"
        return name
    return ref
```

- [ ] **Step 4 : Lancer → succès**

Run: `python -m pytest tests/test_validate.py -k "source_type_label or source_ref_display" -q`
Expected: PASS.

- [ ] **Step 5 : Mettre à jour `HEADERS_BASE` et préfixer `event_to_row`**

Dans `validate.py`, remplacer la définition de `HEADERS_BASE` :

```python
# En-têtes fixes (cols A-L)
HEADERS_BASE = [
    "TYPE SOURCE", "SOURCE",
    "INFO TAPEUR", "DATE TAPAGE", "DATE EMISSION RADIO", "FESTOCHE", "STYLE FESTOCHE",
    "DATE", "HEURE", "LIEU", "VILLE", "PRIX",
]
```

Dans `event_to_row`, préfixer la liste `row` par les 2 cellules de provenance (les commentaires de colonnes passent de A-J à C-L) :

```python
    row = [
        _source_type_label(ev.source_kind),                       # A — TYPE SOURCE
        _source_ref_display(ev.source_kind, ev.source_ref),       # B — SOURCE
        ev.tapeur_email,                  # C — INFO TAPEUR
        ev.tapage_iso,                    # D — DATE TAPAGE
        "",                               # E — DATE EMISSION RADIO (vide, manuel)
        ev.festival or "",                # F — FESTOCHE
        ev.festival_style or "",          # G — STYLE FESTOCHE
        date_cell,                        # H — DATE
        time_cell,                        # I — HEURE
        venue_cell,                       # J — LIEU
        ev.city,                          # K — VILLE
        ev.price,                         # L — PRIX
    ]
```

Mettre à jour la docstring de `event_to_row` : « 12 colonnes fixes (A-L) puis 4 colonnes par ACT ».

- [ ] **Step 6 : Mettre à jour les tests de position existants (décalage +2)**

Dans `tests/test_validate.py` :

`test_classic_event_unchanged` :

```python
def test_classic_event_unchanged():
    """Event classique : provenance en A/B, DATE/HEURE/LIEU remplis normalement."""
    row = event_to_row(_make_classic_event())
    assert row[0] == "URL"                       # TYPE SOURCE
    assert row[1] == "https://example.com/x"     # SOURCE
    assert row[2] == "lebidul@live.fr"           # INFO TAPEUR
    assert row[7] == "Vendredi 22"               # DATE
    assert row[8] == "20h30"                     # HEURE
    assert row[9] == "Le Chapiteau"              # LIEU
    assert row[10] == "Le Mans"                  # VILLE
```

`test_festival_event_uses_marker` : remplacer le bloc d'assertions par (décalage +2) :

```python
    row = event_to_row(ev)

    # FESTOCHE + STYLE FESTOCHE remplis
    assert row[5] == "Festival Kikloche"  # FESTOCHE
    assert "petites formes" in row[6]     # STYLE FESTOCHE

    # DATE = marqueur magique
    assert row[7] == FESTIVAL_DATE_MARKER  # DATE
    assert row[7] == "Festivals"

    # HEURE + LIEU vides
    assert row[8] == ""                   # HEURE
    assert row[9] == ""                   # LIEU

    # VILLE + PRIX + ACT 1 toujours rendus
    assert row[10] == "Saint-Aubin-de-Locquenay"
    assert row[11] == "voir site"
    assert row[12] == "sv"                # GENRE 1
    assert row[13] == "https://www.facebook.com/kikloche"  # NOM SPECTACLE 1
    assert row[14] == "15 spectacles"     # ARTISTE 1
```

`test_row_length_matches_n_acts_param` :

```python
def test_row_length_matches_n_acts_param():
    """event_to_row(ev, n_acts=N) → 12 cols base + 4*N cols acts."""
    ev = _make_classic_event()
    assert len(event_to_row(ev, n_acts=4)) == 12 + 4 * 4
    assert len(event_to_row(ev, n_acts=3)) == 12 + 4 * 3
    assert len(event_to_row(ev, n_acts=1)) == 12 + 4 * 1
```

`test_row_pads_empty_when_n_acts_exceeds_event_acts` :

```python
def test_row_pads_empty_when_n_acts_exceeds_event_acts():
    """Si on demande 4 blocs mais l'event n'a qu'1 act, les 3 blocs suivants
    sont remplis de cellules vides."""
    ev = _make_classic_event()  # 1 act
    row = event_to_row(ev, n_acts=4)
    assert row[12] == "c"                 # GENRE 1 (act 1)
    assert row[16:20] == ["", "", "", ""]  # act 2 vide
    assert row[20:24] == ["", "", "", ""]  # act 3 vide
    assert row[24:28] == ["", "", "", ""]  # act 4 vide
```

`test_make_headers_dynamic_count` :

```python
def test_make_headers_dynamic_count():
    """_make_headers(n) renvoie 12 cols base + 4*n cols acts."""
    h1 = _make_headers(1)
    assert len(h1) == 12 + 4
    assert h1[12:16] == ["GENRE 1", "NOM SPECTACLE 1", "ARTISTE 1", "STYLE 1"]

    h7 = _make_headers(7)
    assert len(h7) == 12 + 4 * 7
    assert h7[-4:] == ["GENRE 7", "NOM SPECTACLE 7", "ARTISTE 7", "STYLE 7"]
```

`test_export_csv_uses_max_acts_across_events` : remplacer `10 + 4 * 7` par `12 + 4 * 7`.

`test_export_csv_empty_events_uses_min_one_act_block` : remplacer `10 + 4 * 1` par `12 + 4 * 1`.

- [ ] **Step 7 : Lancer tout le fichier → succès**

Run: `python -m pytest tests/test_validate.py -q`
Expected: PASS (tous).

- [ ] **Step 8 : Commit**

```bash
git add tapageur/validate.py tests/test_validate.py
git commit -m "feat(export): colonnes TYPE SOURCE / SOURCE dans event_to_row (CSV)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2 : `export_xlsx` + régénération du template (xlsx)

**Files:**
- Modify: `tapageur/gui/export_xlsx.py`
- Modify (binaire, régénéré par script) : `tapageur/gui/assets/template.xlsx`
- Test: `tests/gui/test_export_xlsx.py`

**Interfaces:**
- Consomme : `event_to_row` (Task 1, renvoie 12 cols fixes + 4·n_acts).
- Produit : xlsx dont la feuille `lebiduleur` a `A1="TYPE SOURCE"`, `B1="SOURCE"`, `C1="INFO TAPEUR"`, … et les valeurs d'event écrites positionnellement depuis la col 1.

- [ ] **Step 1 : Régénérer le template (2 colonnes en tête)**

Exécuter ce script (depuis la racine du repo) :

```bash
python -I - <<'PY'
import openpyxl
from pathlib import Path
p = Path("tapageur/gui/assets/template.xlsx")
wb = openpyxl.load_workbook(p)
ws = wb["lebiduleur"]
old = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
assert old[0] == "INFO TAPEUR", f"en-tête inattendu: {old[0]!r}"
new = ["TYPE SOURCE", "SOURCE"] + old
for c, val in enumerate(new, start=1):
    ws.cell(row=1, column=c, value=val)
wb.save(p)
print("template régénéré :", len(new), "colonnes ; A1,B1 =", new[0], "/", new[1])
PY
```

Expected (stdout) : `template régénéré : 28 colonnes ; A1,B1 = TYPE SOURCE / SOURCE`

- [ ] **Step 2 : Vérifier l'en-tête du template**

```bash
python -I - <<'PY'
import openpyxl
from pathlib import Path
ws = openpyxl.load_workbook(Path("tapageur/gui/assets/template.xlsx"))["lebiduleur"]
h = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
assert h[0] == "TYPE SOURCE" and h[1] == "SOURCE" and h[2] == "INFO TAPEUR"
assert h[11] == "PRIX" and h[12] == "GENRE 1"
print("OK", ws.max_column, "colonnes")
PY
```

Expected : `OK 28 colonnes`

- [ ] **Step 3 : Écrire/mettre à jour les tests export (échec attendu)**

Dans `tests/gui/test_export_xlsx.py`, remplacer `test_export_writes_data_and_keeps_reference_sheets` par (décalage +2 + vérif des 2 nouvelles colonnes) :

```python
def test_export_writes_data_and_keeps_reference_sheets(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event()], out)
    wb = openpyxl.load_workbook(out)
    assert set(["lebiduleur", "communes", "salles_lieux", "date"]).issubset(set(wb.sheetnames))
    ws = wb["lebiduleur"]
    # En-têtes : provenance en A/B, INFO TAPEUR décalé en C
    assert ws.cell(row=1, column=1).value == "TYPE SOURCE"
    assert ws.cell(row=1, column=2).value == "SOURCE"
    assert ws.cell(row=1, column=3).value == "INFO TAPEUR"
    # Ligne 2 = 1er event
    assert ws.cell(row=2, column=1).value == "URL"            # TYPE SOURCE (source_kind=web)
    assert ws.cell(row=2, column=2).value == "https://x.fr"   # SOURCE
    assert ws.cell(row=2, column=3).value == "t@b.fr"         # INFO TAPEUR
    assert ws.cell(row=2, column=10).value == "Le Lieu"       # LIEU (col J, +2)
    assert ws.cell(row=2, column=11).value == "Le Mans"       # VILLE (col K, +2)
```

`test_export_dynamic_act_blocks` (les ACT démarrent en col 13 = 12+1) :

```python
def test_export_dynamic_act_blocks(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event(n_acts=5)], out)
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    # 12 colonnes fixes + 5 blocs * 4 = 32 colonnes ; en-tête bloc 5 ajouté
    assert ws.cell(row=1, column=13 + 4 * 4).value == "GENRE 5"
    assert ws.cell(row=2, column=13 + 4 * 4).value == "c"     # genre du 5e act
```

`test_append_preserves_and_adds` (ARTISTE 1 = col 15 = 13+2) :

```python
def test_append_preserves_and_adds(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event(perf="Alpha")], out)                 # création
    export_xlsx.export_xlsx([_event(perf="Beta")], out, append=True)     # append
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    assert ws.cell(row=2, column=15).value == "Alpha0"   # ARTISTE 1, 1re ligne inchangée
    assert ws.cell(row=3, column=15).value == "Beta0"    # ARTISTE 1, ligne ajoutée
    assert ws.max_row == 3
```

`test_append_widens_act_blocks` :

```python
def test_append_widens_act_blocks(tmp_path):
    out = tmp_path / "tapage.xlsx"
    export_xlsx.export_xlsx([_event(n_acts=1)], out)                     # 4 blocs (template)
    export_xlsx.export_xlsx([_event(n_acts=5, perf="X")], out, append=True)
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    assert ws.cell(row=1, column=13 + 4 * 4).value == "GENRE 5"         # en-tête bloc 5 ajouté
    assert ws.cell(row=3, column=13 + 4 * 4).value == "c"               # genre 5e act, ligne ajoutée
```

`test_append_on_missing_file_creates` (ARTISTE 1 = col 15) :

```python
def test_append_on_missing_file_creates(tmp_path):
    out = tmp_path / "nouveau.xlsx"
    export_xlsx.export_xlsx([_event(perf="Solo")], out, append=True)     # fichier absent
    ws = openpyxl.load_workbook(out)["lebiduleur"]
    assert ws.cell(row=2, column=15).value == "Solo0"
    assert ws.max_row == 2
```

(`test_append_without_lebiduleur_raises`, `test_save_locked_file_raises_clear_error`, `test_save_atomic_no_tmp_left` restent inchangés.)

- [ ] **Step 4 : Lancer → échec**

Run: `python -m pytest tests/gui/test_export_xlsx.py -q`
Expected: FAIL (positions encore à 10 fixes, en-têtes A/B absents côté code — le template est déjà régénéré mais `_N_FIXED_COLS` vaut encore 10, donc l'écriture des blocs ACT et de l'append est décalée).

- [ ] **Step 5 : Passer `_N_FIXED_COLS` à 12**

Dans `tapageur/gui/export_xlsx.py` :

```python
_N_FIXED_COLS = 12  # colonnes A-L (TYPE SOURCE, SOURCE, puis INFO TAPEUR … PRIX)
```

(Aucune autre ligne à changer : `_write_act_headers` et `_append_xlsx` dérivent leurs positions de `_N_FIXED_COLS` ; `export_xlsx` écrit `event_to_row` positionnellement depuis la colonne 1.)

- [ ] **Step 6 : Lancer → succès**

Run: `python -m pytest tests/gui/test_export_xlsx.py -q`
Expected: PASS (tous).

- [ ] **Step 7 : Suite complète (non-régression)**

Run: `python -m pytest -q`
Expected: PASS (toute la suite).

- [ ] **Step 8 : Commit**

```bash
git add tapageur/gui/export_xlsx.py tapageur/gui/assets/template.xlsx tests/gui/test_export_xlsx.py
git commit -m "feat(gui): template + export xlsx avec colonnes TYPE SOURCE / SOURCE

_N_FIXED_COLS 10 -> 12 ; template régénéré avec les 2 en-têtes en tête.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes de revue (hors tâches)

- **Pré-existant, hors périmètre** : pour les blocs ACT ≥ 5, `_write_act_headers` écrit `"ARTISTE N"` alors que biduleur attend `COMPAGNIE N` (`_ARTISTE_PATTERN`). Non introduit par cette feature, ne pas corriger ici.
- **Pré-existant, hors périmètre** : `HEADERS_BASE` (CSV) utilise des noms « amicaux » (`FESTOCHE`, `DATE EMISSION RADIO`) et non les noms exacts de biduleur (`FESTOCHE\nEVENEMENT `, …). La compat biduleur vraie passe par le xlsx (template). Inchangé ici.
- **Append ancien ↔ nouveau fichier** : append sur un fichier créé avant cette feature (10 cols fixes) n'est pas supporté (cf. spec §8).
