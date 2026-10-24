# Progression détaillée + validation du mois — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Faire remonter une progression détaillée (par page à la collecte, par item à l'extraction) dans le feed UI de tapageur-gui, et valider le format du champ Mois pour éviter un export vide silencieux sur un typo.

**Architecture:** Un callback `progress` optionnel (défaut `None`, rétrocompatible) threadé depuis `service.run` (qui le reçoit déjà de `app.py`) vers `normalize_items` (par item) et `WebConnector.collect` (par page), plus `items_from_files`/`items_from_urls`. Validation du mois côté `index.html` (guard avant lancement).

**Tech Stack:** Python 3.11+, pytest + unittest.mock, JS (pywebview).

## Global Constraints

- Python `>=3.11`.
- Tous les nouveaux paramètres `progress` sont **optionnels** (`progress: Callable[[str], None] | None = None`) → CLI et comportement existants inchangés ; `None` = no-op.
- Les messages de progression sont des **chaînes contrôlées** (compteurs + slug/ref), rendus via `.textContent` côté UI (déjà en place) — jamais d'HTML.
- Format mois attendu : `AAAA-MM` (regex `^\d{4}-\d{2}$`).
- Commits en français, terminés par exactement `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

| Fichier | Responsabilité | Neuf / Modifié |
|---------|----------------|----------------|
| `tapageur/normalize.py` | `normalize_items(..., progress=None)` — émet « Extraction i/n : ref » par item. | Modifié |
| `tapageur/connectors/web.py` | `WebConnector.collect(self, month, progress=None)` — émet le nombre de pages + « Page i/n : slug » par fetch suivi. | Modifié |
| `tapageur/gui/inputs.py` | `items_from_files(paths, progress=None)`, `items_from_urls(url_inputs, month, progress=None)` threadent `progress`. | Modifié |
| `tapageur/gui/service.py` | `run` thread son `progress` vers les builders d'items + `_pipeline`→`normalize_items`. | Modifié |
| `tapageur/gui/web/index.html` | Guard : rejeter un mois mal formé (hors `ne pas filtrer`). | Modifié |
| `tests/test_normalize.py`, `tests/test_web.py`, `tests/gui/test_inputs.py`, `tests/gui/test_service.py` | Tests. | Modifié |

---

## Task 1: `normalize_items` — callback de progression par item

**Files:**
- Modify: `tapageur/normalize.py` (`normalize_items`)
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: `normalize_items(items, month, out_path, model=None, month_filter=True, progress=None)`. Pour chaque item (indexé 1..n), appelle `progress(f"Extraction {i}/{n} : {ref_short}")` AVANT le traitement (de sorte que même un cache hit fasse avancer l'affichage). `ref_short` = la même troncature à 60 que celle déjà calculée. Défaut `None` = no-op.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_normalize.py` :

```python
def test_normalize_items_calls_progress_per_item(monkeypatch, tmp_path):
    from tapageur import normalize as _norm
    from tapageur.schema import CollectedItem
    # normalize_items construit Anthropic() en tête → clé factice (aucun appel réel :
    # _normalize_one est monkeypatché juste après).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    items = [
        CollectedItem(source_kind="web", source_ref="https://x.fr/a",
                      fetched_at="2026-01-01T00:00:00Z", raw_text="x", raw_metadata={}),
        CollectedItem(source_kind="web", source_ref="https://x.fr/b",
                      fetched_at="2026-01-01T00:00:00Z", raw_text="y", raw_metadata={}),
    ]
    # Court-circuite l'appel Claude : chaque item → 0 event (peu importe ici)
    monkeypatch.setattr(_norm, "_normalize_one", lambda *a, **k: [])
    seen = []
    _norm.normalize_items(items, "2026-11", tmp_path / "out.json",
                          progress=lambda msg: seen.append(msg))
    assert any("1/2" in m for m in seen)
    assert any("2/2" in m for m in seen)
    assert all(m.startswith("Extraction ") for m in seen)
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/test_normalize.py::test_normalize_items_calls_progress_per_item -v`
Expected: FAIL (`TypeError: normalize_items() got an unexpected keyword argument 'progress'`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/normalize.py`, signature de `normalize_items` :

```python
def normalize_items(
    items: list[CollectedItem],
    month: str,
    out_path: Path,
    model: str | None = None,
    month_filter: bool = True,
    progress: "Callable[[str], None] | None" = None,
) -> list[Event]:
```

Ajouter en tête de fichier l'import de typing si absent :

```python
from collections.abc import Callable
```

Dans la boucle `for i, item in enumerate(items, 1):`, juste après le calcul de `ref_short` (qui existe déjà), insérer :

```python
        if progress:
            progress(f"Extraction {i}/{len(items)} : {ref_short}")
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_normalize.py -v` puis `pytest -q`
Expected: le nouveau PASS ; suite entière verte (défaut `None` préserve tout).

- [ ] **Step 5: Commit**

```bash
git add tapageur/normalize.py tests/test_normalize.py
git commit -m "feat(normalize): callback progress par item dans normalize_items

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `WebConnector.collect` — progression par page suivie

**Files:**
- Modify: `tapageur/connectors/web.py` (`WebConnector.collect`)
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `WebConnector.collect(self, month, progress=None)` (override compatible de `Connector.collect(self, month)` — param optionnel ajouté). Dans la branche follow, après sélection finale des `event_urls`, appelle `progress(f"{len(event_urls)} pages à récupérer")`, puis dans la boucle de fetch `progress(f"Page {i}/{len(event_urls)} : {slug}")` (où `slug` = dernier segment non vide du chemin de `ev_url`). Défaut `None` = no-op. Les autres branches (not-follow, fallback) n'émettent rien d'obligatoire.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_web.py` :

```python
def test_collect_follow_domain_reports_page_progress(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    index_html = _html_with_links(["/diphonie/", "/polyphonies/", "/contact/"])
    monkeypatch.setattr(web, "_fetch",
                        lambda url, needs_browser=False: index_html if url.endswith("/festival/")
                        else "<p>event</p>")
    monkeypatch.setattr(web, "_filter_event_urls",
                        lambda a, u, m: ["https://site.fr/diphonie/", "https://site.fr/polyphonies/"])
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/festival/", "name": "fest",
        "follow_event_links": True, "follow_scope": "domain", "prefilter_by_month": False,
    }]})
    seen = []
    items = list(conn.collect("2026-11", progress=lambda msg: seen.append(msg)))
    assert len(items) == 2
    assert any("2 pages" in m for m in seen)
    assert any("Page 1/2" in m and "diphonie" in m for m in seen)
    assert any("Page 2/2" in m and "polyphonies" in m for m in seen)
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/test_web.py::test_collect_follow_domain_reports_page_progress -v`
Expected: FAIL (`TypeError: collect() got an unexpected keyword argument 'progress'`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/connectors/web.py`, changer la signature de la méthode :

```python
    def collect(self, month: str, progress=None) -> Iterator[CollectedItem]:
```

Juste avant la boucle `for ev_url in event_urls:` (après que `event_urls` soit finalisé par le pré-filtre), ajouter :

```python
            if progress:
                progress(f"{len(event_urls)} pages à récupérer")
```

Et transformer la boucle de fetch en `enumerate` avec émission par page :

```python
            for i, ev_url in enumerate(event_urls, 1):
                if progress:
                    slug = [s for s in ev_url.rstrip("/").split("/") if s][-1]
                    progress(f"Page {i}/{len(event_urls)} : {slug}")
                try:
                    ev_html = _fetch(ev_url, needs_browser=needs_browser)
                except Exception as e:
                    print(f"[web]   {ev_url}: {e}")
                    continue
                ev_text = BeautifulSoup(ev_html, "html.parser").get_text("\n", strip=True)
                yield _web_item(ev_url, ev_text, site_name, mode, model_override,
                                extra_meta={"agenda_url": url})
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_web.py -v -k "collect_follow_domain"` puis `pytest -q`
Expected: nouveaux + existants PASS ; suite verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/connectors/web.py tests/test_web.py
git commit -m "feat(web): progression par page dans collect (mode follow)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `inputs.py` — threader `progress`

**Files:**
- Modify: `tapageur/gui/inputs.py`
- Test: `tests/gui/test_inputs.py`

**Interfaces:**
- Produces:
  - `items_from_files(paths, progress=None)` : pour chaque fichier (indexé 1..n), `progress(f"Fichier {i}/{n} : {path.name}")` avant routage.
  - `items_from_urls(url_inputs, month, progress=None)` : passe `progress` à `WebConnector(config).collect(month, progress=progress)`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/gui/test_inputs.py` :

```python
def test_items_from_files_reports_progress(tmp_path):
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f1e0000000049454e44ae426082"
    )
    f = tmp_path / "flyer.png"
    f.write_bytes(png)
    seen = []
    inputs.items_from_files([f], progress=lambda m: seen.append(m))
    assert any("flyer.png" in m and "1/1" in m for m in seen)


def test_items_from_urls_threads_progress(monkeypatch):
    captured = {}

    class FakeWeb:
        def __init__(self, config):
            pass

        def collect(self, month, progress=None):
            captured["progress"] = progress
            return iter(())

    monkeypatch.setattr(inputs, "WebConnector", FakeWeb)
    cb = lambda m: None
    inputs.items_from_urls([inputs.UrlInput(url="https://ex.fr/a")], month="2026-11", progress=cb)
    assert captured["progress"] is cb
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/gui/test_inputs.py -v -k "progress"`
Expected: FAIL (`TypeError: ... unexpected keyword argument 'progress'`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/inputs.py` :

```python
def items_from_files(paths: list[Path], progress=None) -> list[CollectedItem]:
    items: list[CollectedItem] = []
    n = len(paths)
    for i, p in enumerate(paths, 1):
        if progress:
            progress(f"Fichier {i}/{n} : {Path(p).name}")
        item = _route_file(Path(p))
        if item is not None:
            items.append(item)
    return items
```

```python
def items_from_urls(url_inputs: list[UrlInput], month: str, progress=None) -> list[CollectedItem]:
    config = {"websites": [_url_to_site(u) for u in url_inputs]}
    conn = WebConnector(config)
    return list(conn.collect(month, progress=progress))
```

**IMPORTANT (non-régression) :** `items_from_urls` appelle désormais `collect(month, progress=progress)`. Les tests existants de `tests/gui/test_inputs.py` (`test_url_input_builds_synthetic_config`, `test_url_input_defaults_no_festival`) définissent une `class FakeWeb` avec `def collect(self, month):` — mettre à jour ces deux signatures en `def collect(self, month, progress=None):` sinon elles lèveront `TypeError: collect() got an unexpected keyword argument 'progress'`.

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/gui/test_inputs.py -v` puis `pytest -q`
Expected: nouveaux + existants PASS ; suite verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/inputs.py tests/gui/test_inputs.py
git commit -m "feat(gui): threade progress dans items_from_files/urls

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `service.run` — threader `progress` vers builders + pipeline

**Files:**
- Modify: `tapageur/gui/service.py`
- Test: `tests/gui/test_service.py`

**Interfaces:**
- Consumes: `items_from_files(..., progress=)`, `items_from_urls(..., progress=)` (Task 3), `normalize_items(..., progress=)` (Task 1).
- Produces: `run` passe son `progress` existant à : `items_from_files(req.file_paths, progress=progress)`, `items_from_urls(req.url_inputs, url_month, progress=progress)`, et `_pipeline(items, month, month_filter, cache_out, progress)` → `normalize_items(..., progress=progress)`. Les messages d'étape existants (« Collecte des sources… », etc.) restent.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/gui/test_service.py` :

```python
def test_run_threads_progress_into_normalize(tmp_path, monkeypatch):
    captured = {}
    def fake_normalize(items, month, out_path, model=None, month_filter=True, progress=None):
        captured["progress"] = progress
        return [_event()]
    monkeypatch.setattr(service, "normalize_items", fake_normalize)
    monkeypatch.setattr(service, "load_mappings", lambda: {})
    monkeypatch.setattr(service, "canonicalize", lambda evs, m: evs)
    monkeypatch.setattr(service, "dedup", lambda evs: evs)
    monkeypatch.setattr(service, "group_events", lambda evs: evs)
    monkeypatch.setattr(service, "convert_to_onliner", lambda evs, names: evs)
    req = service.RunRequest(
        file_paths=[], url_inputs=[], months=["2026-11"], no_month_filter=False,
        formats=["json"], out_dir=tmp_path, tapeur_email="t@b.fr",
    )
    cb = lambda m: None
    service.run(req, progress=cb)
    assert captured["progress"] is cb
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/gui/test_service.py::test_run_threads_progress_into_normalize -v`
Expected: FAIL (`captured["progress"]` est `None`, pas `cb`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/service.py`, `_pipeline` prend `progress` et le passe à `normalize_items` :

```python
def _pipeline(items, month: str, month_filter: bool, cache_out: Path, progress=None) -> list[Event]:
    events = normalize_items(items, month, cache_out, model=None, month_filter=month_filter, progress=progress)
    events = canonicalize(events, load_mappings())
    events = dedup(events)
    events = group_events(events)
    onliner_names = [ev.festival for ev in events if ev.is_festival and ev.festival]
    events = convert_to_onliner(events, onliner_names)
    return events
```

Dans `run`, à la construction des items et à l'appel pipeline, passer `progress` (qui est déjà le paramètre de `run`) :

```python
    url_month = "" if req.no_month_filter else (req.months[0] if req.months else "")
    items = list(items_from_files(req.file_paths, progress=progress))
    items += list(items_from_urls(req.url_inputs, url_month, progress=progress))
```

et dans la boucle des passes :

```python
        events = _pipeline(items, month, month_filter, cache_out, progress=progress)
```

(Note : `items` reste construit une seule fois avant la boucle — comportement conservé de la version actuelle.)

**IMPORTANT (non-régression) :** `run` appelle désormais `normalize_items(..., progress=progress)`. Le test existant `test_run_exports_requested_formats` monkeypatche `service.normalize_items` avec un lambda `lambda items, month, out_path, model=None, month_filter=True: [_event()]` — ajouter `progress=None` à sa signature (`..., month_filter=True, progress=None: [_event()]`) sinon il lèvera `TypeError`. De même, tout autre double de `normalize_items` dans `test_service.py` doit accepter `progress=None`.

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/gui/test_service.py -v` puis `pytest -q`
Expected: nouveau + existants PASS ; suite verte.

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/service.py tests/gui/test_service.py
git commit -m "feat(gui): service.run threade progress vers collecte + extraction

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Validation du champ Mois (UI)

**Files:**
- Modify: `tapageur/gui/web/index.html` (guard du gestionnaire `#run`)

**Interfaces:**
- Produces: avant de lancer, si `ne pas filtrer par mois` est décoché, chaque entrée du champ Mois doit matcher `^\d{4}-\d{2}$`. Sinon, afficher dans le résumé « Mois invalide : utilise le format AAAA-MM (ex. 2026-11). » (texte, via `textContent`) et ne pas lancer.

> Pas de test automatisé (UI). Vérification : relecture + smoke.

- [ ] **Step 1: Ajouter le guard**

Dans `tapageur/gui/web/index.html`, dans le gestionnaire du bouton `#run`, APRÈS le calcul de `months` et `noFilter` et le guard « aucun mois ciblé », ajouter :

```javascript
  if (!noFilter && !months.every(m => /^\d{4}-\d{2}$/.test(m))) {
    summary.textContent = 'Mois invalide : utilise le format AAAA-MM (ex. 2026-11).';
    return;
  }
```

(Placer ce guard AVANT `startElapsed()` / l'appel à `run_extraction`, comme les autres guards.)

- [ ] **Step 2: Vérification**

- Parse HTML : `python -c "import html.parser; html.parser.HTMLParser().feed(open(r'tapageur/gui/web/index.html',encoding='utf-8').read()); print('ok')"`.
- Relire : le guard rejette `20611`, `2026-111`, `2026/11` et accepte `2026-11` ; multi-mois `2026-07, 2026-08` passe (chaque entrée validée).
- `pytest -q` reste vert (aucun Python touché).

- [ ] **Step 3: Commit**

```bash
git add tapageur/gui/web/index.html
git commit -m "feat(gui): valide le format du champ Mois (AAAA-MM) avant lancement

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Validation de bout en bout (manuelle)

Sur `cpfi-lemans.com/festival/`, « suivre les liens » coché, **Mois = `2026-11`** : le feed affiche « N pages à récupérer », « Page i/N : slug », puis « Extraction i/N : … », et l'xlsx final contient les concerts/salons de musique avec lieu. Un mois mal formé (`20611`) est désormais refusé avec un message clair au lieu d'un export vide.

## Hors périmètre
- Progression par item dans `items_from_files` au-delà du nom de fichier.
- Barre de progression graphique (on reste en lignes de texte).
