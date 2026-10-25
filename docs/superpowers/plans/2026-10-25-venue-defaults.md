# Défauts heure/prix par lieu — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compléter l'heure/le prix manquants d'un event selon des défauts par lieu (`config/venue_defaults.yaml`), ex. Bistro Broc Café → 20h00 / au chapeau.

**Architecture:** Un YAML lieu→{time,price} chargé comme `mappings.yaml` ; `apply_venue_defaults` tourne dans `service._pipeline` après `canonicalize` (lieu canonique) et ne remplit que les champs absents.

**Tech Stack:** Python 3.11+, pyyaml, pytest, PyInstaller.

## Global Constraints

- N'écrase JAMAIS une heure/un prix réellement extraits — n'agit que si absent
  (heure `[]`/`["?"]` ; prix vide/`"?"`).
- Clé = nom **canonique** du lieu (après `canonicalize`).
- YAML embarqué dans l'exe (résolu via `_MEIPASS`, comme `mappings.yaml`).
- Message de commit terminé par : `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1 : config + `dedup.load_venue_defaults` / `apply_venue_defaults`

**Files:**
- Create: `config/venue_defaults.yaml`
- Modify: `tapageur/dedup.py`
- Test: `tests/test_dedup.py`

**Interfaces:**
- `load_venue_defaults(path: Path = Path("config/venue_defaults.yaml")) -> dict`
- `apply_venue_defaults(events: list[Event], defaults: dict) -> list[Event]`

- [ ] **Step 1 : Créer `config/venue_defaults.yaml`**

```yaml
# Heure / prix par défaut par lieu (nom canonique), appliqués UNIQUEMENT si
# absents de la source. Ajouter d'autres lieux ici (puis rebuild pour l'exe).
"Bistro Broc Café":
  time: "20h00"
  price: "au chapeau"
```

- [ ] **Step 2 : Tests (échec attendu)**

Ajouter dans `tests/test_dedup.py` (adapter l'import d'`Event`/`Act` au style du fichier) :

```python
def _ev(venue, times, price):
    from tapageur.schema import Event, Act
    return Event(tapeur_email="t@b.fr", date_label="Mardi 2", date_iso="2026-11-02",
                 times=times, venue=venue, city="Le Mans", price=price,
                 acts=[Act(genre="c", title=None, performer="A", style=None)],
                 source_kind="web", source_ref="x")


def test_load_venue_defaults_reads_yaml(tmp_path):
    from tapageur import dedup
    p = tmp_path / "vd.yaml"
    p.write_text('"Bistro Broc Café":\n  time: "20h00"\n  price: "au chapeau"\n', encoding="utf-8")
    d = dedup.load_venue_defaults(p)
    assert d["Bistro Broc Café"]["time"] == "20h00"
    assert dedup.load_venue_defaults(tmp_path / "absent.yaml") == {}


def test_apply_venue_defaults_fills_missing():
    from tapageur import dedup
    defaults = {"Bistro Broc Café": {"time": "20h00", "price": "au chapeau"}}
    evs = [_ev("Bistro Broc Café", ["?"], "?")]
    out = dedup.apply_venue_defaults(evs, defaults)
    assert out[0].times == ["20h00"]
    assert out[0].price == "au chapeau"


def test_apply_venue_defaults_keeps_extracted():
    from tapageur import dedup
    defaults = {"Bistro Broc Café": {"time": "20h00", "price": "au chapeau"}}
    evs = [_ev("Bistro Broc Café", ["18h30"], "7€")]
    out = dedup.apply_venue_defaults(evs, defaults)
    assert out[0].times == ["18h30"] and out[0].price == "7€"


def test_apply_venue_defaults_ignores_other_venues():
    from tapageur import dedup
    defaults = {"Bistro Broc Café": {"time": "20h00", "price": "au chapeau"}}
    evs = [_ev("Autre Lieu", ["?"], "?")]
    out = dedup.apply_venue_defaults(evs, defaults)
    assert out[0].times == ["?"] and out[0].price == "?"
```

- [ ] **Step 3 : Lancer → échec**

Run: `python -m pytest tests/test_dedup.py -k "venue_defaults" -q`
Expected: FAIL (fonctions absentes).

- [ ] **Step 4 : Implémenter dans `dedup.py`**

Ajouter (après `load_mappings`) :

```python
def load_venue_defaults(path: Path = Path("config/venue_defaults.yaml")) -> dict:
    """Charge les défauts heure/prix par lieu ; {} si absent/illisible."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_venue_defaults(events: list[Event], defaults: dict) -> list[Event]:
    """Complète heure/prix manquants selon le lieu (déjà canonicalisé).
    N'écrase jamais une valeur extraite."""
    for ev in events:
        d = defaults.get(ev.venue)
        if not d:
            continue
        if d.get("time") and (not ev.times or ev.times == ["?"]):
            ev.times = [d["time"]]
        if d.get("price") and (not ev.price or ev.price.strip() in ("", "?")):
            ev.price = d["price"]
    return events
```

- [ ] **Step 5 : Lancer → succès**

Run: `python -m pytest tests/test_dedup.py -k "venue_defaults" -q`
Expected: PASS.

- [ ] **Step 6 : Commit**

```bash
git add config/venue_defaults.yaml tapageur/dedup.py tests/test_dedup.py
git commit -m "feat(dedup): défauts heure/prix par lieu (load/apply_venue_defaults)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2 : câblage `service._pipeline` + bundle exe

**Files:**
- Modify: `tapageur/gui/service.py`, `tapageur.spec`
- Test: `tests/gui/test_service.py`

**Interfaces:**
- `_venue_defaults_path()` (miroir de `_mappings_path`).
- `_pipeline` applique `apply_venue_defaults` après `canonicalize`.

- [ ] **Step 1 : Test service (échec attendu)**

Ajouter dans `tests/gui/test_service.py` :

```python
def test_pipeline_applies_venue_defaults(tmp_path, monkeypatch):
    """_pipeline complète heure/prix via les défauts par lieu, après canonicalize."""
    ev = _event(times=["?"], price="?", venue="Bistro Broc Café")
    monkeypatch.setattr(service, "normalize_items",
                        lambda *a, **k: [ev])
    monkeypatch.setattr(service, "load_mappings", lambda *a, **k: {})
    monkeypatch.setattr(service, "canonicalize", lambda e, m: e)
    monkeypatch.setattr(service, "dedup", lambda e: e)
    monkeypatch.setattr(service, "group_events", lambda e: e)
    monkeypatch.setattr(service, "convert_to_onliner", lambda e, names: e)
    monkeypatch.setattr(service, "load_venue_defaults",
                        lambda *a, **k: {"Bistro Broc Café": {"time": "20h00", "price": "au chapeau"}})
    out = service._pipeline([], "2026-11", True, tmp_path / "c.json")
    assert out[0].times == ["20h00"]
    assert out[0].price == "au chapeau"
```

(`_event` accepte déjà `times` et `venue`.)

- [ ] **Step 2 : Lancer → échec**

Run: `python -m pytest tests/gui/test_service.py -k venue_defaults -q`
Expected: FAIL (`load_venue_defaults`/`apply_venue_defaults` non importés, pas appliqués).

- [ ] **Step 3 : Implémenter dans `service.py`**

Dans l'import depuis `tapageur.dedup`, ajouter `apply_venue_defaults` et
`load_venue_defaults` :

```python
from tapageur.dedup import (apply_venue_defaults, canonicalize, convert_to_onliner,
                            dedup, group_events, load_mappings, load_venue_defaults)
```

Ajouter le helper de chemin (près de `_mappings_path`) :

```python
def _venue_defaults_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "config" / "venue_defaults.yaml"
    return Path("config/venue_defaults.yaml")
```

Dans `_pipeline`, après la ligne `events = canonicalize(...)`, insérer :

```python
    events = apply_venue_defaults(events, load_venue_defaults(_venue_defaults_path()))
```

- [ ] **Step 4 : Lancer → succès**

Run: `python -m pytest tests/gui/test_service.py -k venue_defaults -q`
Expected: PASS.

- [ ] **Step 5 : Bundle dans `tapageur.spec`**

Ajouter aux `datas` :

```python
    ("config/venue_defaults.yaml", "config"),
```

- [ ] **Step 6 : Suite complète**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 7 : Commit**

```bash
git add tapageur/gui/service.py tapageur.spec tests/gui/test_service.py
git commit -m "feat(gui): appliquer les défauts heure/prix par lieu dans le pipeline

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes de revue (hors tâches)

- Pipeline CLI non couvert (hors périmètre spec) — à étendre si besoin.
- `apply_venue_defaults` tourne **après** `canonicalize` → `ev.venue` est la
  forme canonique, qui doit matcher la clé du YAML.
