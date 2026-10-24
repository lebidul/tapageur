# Smart Follow-Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** En mode « suivre les liens », découvrir les pages d'événement qui sont des liens frères du même hôte (pas seulement des sous-chemins), trier les vraies pages d'événement via un pré-filtre Claude, et retomber sur la page d'index si le pré-filtre ne peut pas trancher.

**Architecture:** Ajouts ciblés dans `tapageur/connectors/web.py` (option `follow_scope`, pré-filtre généralisé `_filter_event_urls`, orchestration de la branche follow avec fallback), plus un one-liner GUI dans `tapageur/gui/inputs.py`. Rétrocompatible : le défaut `follow_scope="subpath"` préserve le comportement actuel.

**Tech Stack:** Python 3.11+, BeautifulSoup, anthropic (pré-filtre Sonnet), pytest + unittest.mock.

## Global Constraints

- Python `>=3.11`.
- **Rétrocompatibilité** : `follow_scope` défaut `"subpath"` = comportement actuel inchangé ; les tests existants de `_extract_subpages` doivent rester verts.
- Même-hôte = même `netloc` que l'URL d'agenda (pas de cross-domaine, pas de sous-domaines différents).
- Le pré-filtre Claude n'a qu'un seul appelant (`web.collect`) ; `_filter_urls_by_month` est renommé `_filter_event_urls` (pas d'alias).
- Fallback index = émettre la page d'agenda elle-même comme `CollectedItem` web (même contenu que la branche `not follow`), avec `mode`/`model_override` propagés.
- Commits en français, terminés par exactement `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

| Fichier | Responsabilité | Neuf / Modifié |
|---------|----------------|----------------|
| `tapageur/connectors/web.py` | `follow_scope` dans `_extract_subpages` ; `_filter_event_urls` ; rework branche follow de `collect` + helper fallback. | Modifié |
| `tapageur/gui/inputs.py` | `_url_to_site` ajoute `follow_scope="domain"`. | Modifié |
| `tests/test_web.py` | Tests scope domaine, pré-filtre généralisé, collect follow+domaine, fallback. | Modifié |
| `tests/gui/test_inputs.py` | Test `follow_scope="domain"` dans l'entrée synthétique. | Modifié |

---

## Task 1: `_extract_subpages` — paramètre `scope` + découverte domaine

**Files:**
- Modify: `tapageur/connectors/web.py` (fonction `_extract_subpages`)
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `_extract_subpages(html: str, base_url: str, pattern: str | None = None, scope: str = "subpath") -> list[str]`. `scope="domain"` : retourne tous les liens même-`netloc` (http/https), hors l'URL d'agenda elle-même, dédupliqués/canonisés (sans fragment ni query). `pattern` continue de primer. `scope="subpath"` : comportement actuel (sous-chemin strict).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_web.py` (section `_extract_subpages`) :

```python
def test_extract_subpages_domain_scope_keeps_siblings():
    from tapageur.connectors.web import _extract_subpages
    html = '''
      <a href="/festival/">agenda</a>
      <a href="/diphonie-des-steppes/">event A</a>
      <a href="/contact/">menu</a>
      <a href="#top">ancre</a>
      <a href="mailto:x@y.fr">mail</a>
      <a href="https://autre.fr/x/">externe</a>
    '''
    subs = _extract_subpages(html, base_url="https://site.fr/festival/", scope="domain")
    assert "https://site.fr/diphonie-des-steppes/" in subs
    assert "https://site.fr/contact/" in subs          # menu gardé (le pré-filtre triera)
    assert "https://site.fr/festival/" not in subs      # pas l'agenda lui-même
    assert not any("autre.fr" in u for u in subs)        # pas cross-domaine
    assert not any(u.startswith("mailto") or "#" in u for u in subs)


def test_extract_subpages_domain_scope_dedups_fragment_and_query():
    from tapageur.connectors.web import _extract_subpages
    html = '''
      <a href="/a/">x</a>
      <a href="/a/#section">x frag</a>
      <a href="/a/?utm=1">x query</a>
    '''
    subs = _extract_subpages(html, base_url="https://site.fr/festival/", scope="domain")
    assert subs.count("https://site.fr/a/") == 1
    assert len([u for u in subs if u.endswith("/a/")]) == 1
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/test_web.py::test_extract_subpages_domain_scope_keeps_siblings tests/test_web.py::test_extract_subpages_domain_scope_dedups_fragment_and_query -v`
Expected: FAIL (`TypeError: _extract_subpages() got an unexpected keyword argument 'scope'`).

- [ ] **Step 3: Écrire l'implémentation minimale**

Dans `tapageur/connectors/web.py`, changer la signature :

```python
def _extract_subpages(html: str, base_url: str, pattern: str | None = None, scope: str = "subpath") -> list[str]:
```

Dans la boucle, APRÈS le bloc `if compiled_pattern is not None:` (inchangé) et le `if p.netloc != base.netloc: continue`, remplacer le bloc sous-chemin par une bifurcation selon `scope`. La fin de boucle devient :

```python
        # Heuristique par défaut : sous-chemin strict de base_path.
        if p.netloc != base.netloc:
            continue
        if p.scheme not in ("http", "https"):
            continue
        if path == base_path:
            continue  # la page agenda elle-même
        if scope == "subpath" and not path.startswith(base_path + "/"):
            continue
        clean = f"{p.scheme}://{p.netloc}{p.path}"
        out.add(clean)
    return sorted(out)
```

(Note : en `scope="domain"` on saute la contrainte `base_path + "/"` ; tout lien même-hôte, http/https, non-agenda est gardé. Le `clean` sans fragment/query assure la déduplication.)

- [ ] **Step 4: Lancer les tests (nouveaux + anciens)**

Run: `pytest tests/test_web.py -v -k extract_subpages`
Expected: PASS — les 2 nouveaux ET les 3 existants (`heuristic_default`, `with_pattern_overrides_heuristic`, `pattern_skips_cross_domain`).

- [ ] **Step 5: Commit**

```bash
git add tapageur/connectors/web.py tests/test_web.py
git commit -m "feat(web): _extract_subpages scope=domain (liens frères même-hôte)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Pré-filtre généralisé `_filter_event_urls`

**Files:**
- Modify: `tapageur/connectors/web.py` (renommer+généraliser `_filter_urls_by_month`, mettre à jour `PREFILTER_SYSTEM`, mettre à jour l'unique appelant dans `collect`)
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `_filter_event_urls(agenda_text: str, urls: list[str], month: str | None) -> list[str]`. `month=None` → « quelles URLs sont des pages d'événement » ; `month="YYYY-MM"` → en plus, dans ce mois. Retourne un sous-ensemble strict de `urls` (sanity check conservé). Lève en cas d'erreur API/parse (le caller gère le fallback).

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_web.py` :

```python
def test_filter_event_urls_month_none_sanity_filters_hallucinations():
    from unittest.mock import Mock, patch
    import tapageur.connectors.web as web
    urls = ["https://site.fr/a/", "https://site.fr/b/"]
    fake = Mock()
    block = Mock(); block.type = "text"
    block.text = '{"urls": ["https://site.fr/a/", "https://site.fr/HALLUCINE/"]}'
    fake.messages.create.return_value = Mock(content=[block])
    with patch("anthropic.Anthropic", return_value=fake):
        kept = web._filter_event_urls("agenda overview", urls, month=None)
    assert kept == ["https://site.fr/a/"]  # b non choisie, HALLUCINE filtrée


def test_filter_event_urls_month_set_passes_month_in_prompt():
    from unittest.mock import Mock, patch
    import tapageur.connectors.web as web
    urls = ["https://site.fr/a/"]
    fake = Mock()
    block = Mock(); block.type = "text"
    block.text = '{"urls": ["https://site.fr/a/"]}'
    fake.messages.create.return_value = Mock(content=[block])
    with patch("anthropic.Anthropic", return_value=fake):
        kept = web._filter_event_urls("agenda", urls, month="2026-11")
    sent = fake.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "2026-11" in sent
    assert kept == ["https://site.fr/a/"]
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/test_web.py::test_filter_event_urls_month_none_sanity_filters_hallucinations -v`
Expected: FAIL (`AttributeError: module 'tapageur.connectors.web' has no attribute '_filter_event_urls'`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/connectors/web.py`, remplacer le `PREFILTER_SYSTEM` par une version qui gère la présence ou non d'un mois :

```python
PREFILTER_SYSTEM = """\
Tu es un router d'URLs. À partir d'un texte d'agenda et d'une liste d'URLs candidates \
(du même site), retourne UNIQUEMENT les URLs qui pointent vers une PAGE D'ÉVÉNEMENT \
(concert, spectacle, date programmée), et PAS vers une page de menu/navigation \
(accueil, à-propos, contact, mentions légales, presse, cours, stages génériques…).

Si une ligne "Mois cible" est fournie, ne garde en plus que les événements de ce mois.

Heuristiques :
- Le slug d'URL contient souvent le nom de l'artiste/spectacle listé dans l'agenda.
- Le texte d'agenda donne les événements (et parfois leurs dates).
- En cas d'INCERTITUDE : INCLURE l'URL. Mieux vaut un fetch inutile qu'un event raté.

Réponds UNIQUEMENT par un JSON valide :
{"urls": ["...", "..."]}

- AUCUN texte avant ou après.
- PAS de markdown.
- Liste vide si aucune URL ne correspond."""
```

Renommer la fonction et rendre `month` optionnel :

```python
def _filter_event_urls(
    agenda_text: str,
    urls: list[str],
    month: str | None,
) -> list[str]:
    """Pré-filtrage Claude : quelles URLs candidates sont des pages d'événement
    (optionnellement dans `month` = 'YYYY-MM'), d'après le texte d'agenda.

    Retourne un sous-ensemble strict de `urls` (sanity check côté Python).
    En cas d'erreur API/parse, lève l'exception : le caller décide du fallback."""
    from anthropic import Anthropic

    from tapageur.normalize import _extract_json

    client = Anthropic()
    header = f"Mois cible : {month}\n\n" if month else ""
    user = (
        header
        + f"=== Agenda overview ===\n{agenda_text}\n\n"
        + f"=== URLs candidates ({len(urls)}) ===\n" + "\n".join(urls)
    )
    response = client.messages.create(
        model=PREFILTER_MODEL,
        max_tokens=4000,
        system=PREFILTER_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise ValueError("réponse Claude sans bloc text")

    raw = _extract_json(text)
    data = json.loads(raw)
    candidates = data.get("urls", [])
    if not isinstance(candidates, list):
        raise ValueError(f"format inattendu : urls={candidates!r}")

    valid = set(urls)
    return [u for u in candidates if u in valid]
```

Mettre à jour l'unique appelant dans `collect` (la ligne actuelle
`kept = _filter_urls_by_month(agenda_text, event_urls, month)`) en :

```python
                        kept = _filter_event_urls(agenda_text, event_urls, month)
```

(Le rework complet du gating est en Task 3 ; ici on garde le comportement
actuel, juste avec le nouveau nom et `month` toujours passé.)

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_web.py -v -k "filter_event_urls"` puis `pytest -q`
Expected: les 2 nouveaux PASS ; suite entière verte (aucune référence restante à `_filter_urls_by_month`).

- [ ] **Step 5: Commit**

```bash
git add tapageur/connectors/web.py tests/test_web.py
git commit -m "feat(web): pré-filtre généralisé _filter_event_urls (mois optionnel)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `collect()` branche follow — `follow_scope`, gating pré-filtre, fallback index

**Files:**
- Modify: `tapageur/connectors/web.py` (méthode `WebConnector.collect`, + petit helper `_web_item`)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `_extract_subpages(..., scope=...)` (Task 1), `_filter_event_urls(...)` (Task 2).
- Produces: comportement de `collect` en mode follow :
  - lit `follow_scope = site.get("follow_scope", "subpath")`.
  - `candidates = _extract_subpages(html, url, pattern=event_link_pattern, scope=follow_scope)`.
  - `run_prefilter = bool(candidates) and os.environ.get("ANTHROPIC_API_KEY") and (prefilter_by_month or follow_scope == "domain")`.
  - si `run_prefilter` : `pf_month = month if prefilter_by_month else None` ; `kept = _filter_event_urls(agenda_text, candidates, pf_month)` ; si `follow_scope=="domain"` et `kept` vide → **fallback index** (yield la page d'agenda) + `continue` ; sinon `candidates = kept`.
  - sinon, si `follow_scope == "domain"` (pré-filtre impossible) → **fallback index** + `continue`.
  - sinon (`subpath` sans pré-filtre) → comportement actuel (fetch tous les `candidates`).
  - Helper `_web_item(url, text, site_name, mode, model_override) -> CollectedItem` factorise la construction d'un item web (utilisé par la branche `not follow` ET le fallback).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_web.py` :

```python
def _html_with_links(hrefs):
    return "".join(f'<a href="{h}">x</a>' for h in hrefs)


def test_collect_follow_domain_prefilters_events(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # index + 1 event + 1 menu, tous même-hôte racine
    index_html = _html_with_links(["/diphonie/", "/contact/"])
    monkeypatch.setattr(web, "_fetch",
                        lambda url, needs_browser=False: index_html if url.endswith("/festival/")
                        else "<p>page event diphonie 20 NOV 20h</p>")
    monkeypatch.setattr(web, "_filter_event_urls",
                        lambda agenda, urls, month: ["https://site.fr/diphonie/"])
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)  # pas de HEAD réseau
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/festival/", "name": "fest",
        "follow_event_links": True, "follow_scope": "domain",
        "prefilter_by_month": False,
    }]})
    items = list(conn.collect("2026-11"))
    refs = [it.source_ref for it in items]
    assert refs == ["https://site.fr/diphonie/"]  # event gardé, menu + index écartés


def test_collect_follow_domain_fallback_index_when_prefilter_empty(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    index_html = _html_with_links(["/contact/", "/a-propos/"])
    monkeypatch.setattr(web, "_fetch", lambda url, needs_browser=False: index_html)
    monkeypatch.setattr(web, "_filter_event_urls", lambda agenda, urls, month: [])
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)  # pas de HEAD réseau
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/festival/", "name": "fest",
        "follow_event_links": True, "follow_scope": "domain",
        "prefilter_by_month": False,
    }]})
    items = list(conn.collect("2026-11"))
    assert len(items) == 1
    assert items[0].source_ref == "https://site.fr/festival/"  # fallback = page d'index
    assert items[0].source_kind == "web"


def test_collect_follow_domain_fallback_index_when_no_key(monkeypatch):
    import tapageur.connectors.web as web
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    index_html = _html_with_links(["/diphonie/"])
    monkeypatch.setattr(web, "_fetch", lambda url, needs_browser=False: index_html)
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)  # pas de HEAD réseau
    conn = web.WebConnector({"websites": [{
        "url": "https://site.fr/festival/", "name": "fest",
        "follow_event_links": True, "follow_scope": "domain",
        "prefilter_by_month": False,
    }]})
    items = list(conn.collect("2026-11"))
    assert len(items) == 1
    assert items[0].source_ref == "https://site.fr/festival/"  # pas de fetch massif du domaine
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/test_web.py -v -k "collect_follow_domain"`
Expected: FAIL (fallback non implémenté : en scope domaine sans retenue, le code actuel ne yield pas la page d'index).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/connectors/web.py`, ajouter le helper (près des autres helpers du module) :

```python
def _web_item(url: str, text: str, site_name: str,
              mode: str | None, model_override: str | None,
              extra_meta: dict | None = None) -> CollectedItem:
    """Construit un CollectedItem web (texte d'une page), métadonnées propagées."""
    meta = {"site": site_name}
    if extra_meta:
        meta.update(extra_meta)
    if mode:
        meta["mode"] = mode
    if model_override:
        meta["model_override"] = model_override
    return CollectedItem(
        source_kind="web",
        source_ref=url,
        fetched_at=datetime.utcnow().isoformat() + "Z",
        raw_text=text,
        raw_metadata=meta,
    )
```

Dans `WebConnector.collect`, après `needs_browser`/`follow`/`mode`/`model_override`, lire le scope :

```python
            follow_scope = site.get("follow_scope", "subpath")
```

Remplacer la branche `if not follow:` (dump index) pour réutiliser le helper :

```python
            if not follow:
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
                yield _web_item(url, text, site_name, mode, model_override)
                continue
```

Remplacer la branche follow (découverte + pré-filtre + fetch) par :

```python
            event_pattern = site.get("event_link_pattern")
            event_urls = _extract_subpages(html, base_url=url, pattern=event_pattern, scope=follow_scope)
            agenda_text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            print(f"[web] {site_name}: {len(event_urls)} URLs candidates (scope={follow_scope})")

            prefilter_by_month = site.get("prefilter_by_month", True)
            has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
            run_prefilter = bool(event_urls) and has_key and (prefilter_by_month or follow_scope == "domain")

            if run_prefilter:
                pf_month = month if prefilter_by_month else None
                try:
                    kept = _filter_event_urls(agenda_text, event_urls, pf_month)
                    print(f"[web]   {len(kept)}/{len(event_urls)} retenues")
                    event_urls = kept
                except Exception as e:
                    print(f"[web]   prefilter échoué ({e})")
                    if follow_scope == "domain":
                        yield _web_item(url, agenda_text, site_name, mode, model_override)
                        continue
                    # scope subpath : comportement historique = fetch all
                if follow_scope == "domain" and not event_urls:
                    print(f"[web]   0 event retenu → fallback page d'index")
                    yield _web_item(url, agenda_text, site_name, mode, model_override)
                    continue
            elif follow_scope == "domain":
                # pré-filtre impossible (pas de clé / 0 candidat) : ne pas fetcher
                # tout le domaine → fallback page d'index.
                print(f"[web]   pré-filtre indisponible en scope domaine → fallback index")
                yield _web_item(url, agenda_text, site_name, mode, model_override)
                continue

            for ev_url in event_urls:
                try:
                    ev_html = _fetch(ev_url, needs_browser=needs_browser)
                except Exception as e:
                    print(f"[web]   {ev_url}: {e}")
                    continue
                ev_text = BeautifulSoup(ev_html, "html.parser").get_text("\n", strip=True)
                yield _web_item(ev_url, ev_text, site_name, mode, model_override,
                                extra_meta={"agenda_url": url})
```

(Comportement `subpath` : `run_prefilter` ne dépend que de `prefilter_by_month` comme avant ; pas de fallback index ; on fetch les sous-pages. Inchangé.)

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_web.py -v -k "collect_follow_domain"` puis `pytest -q`
Expected: les 3 nouveaux PASS ; suite entière verte (les tests `_extract_subpages`/PDF/cache existants inchangés).

- [ ] **Step 5: Commit**

```bash
git add tapageur/connectors/web.py tests/test_web.py
git commit -m "feat(web): mode follow domaine + gating pré-filtre + fallback index

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: GUI — activer le scope domaine sur « suivre les liens »

**Files:**
- Modify: `tapageur/gui/inputs.py` (`_url_to_site`)
- Test: `tests/gui/test_inputs.py`

**Interfaces:**
- Produces: l'entrée synthétique `websites:` construite par `_url_to_site` porte `follow_scope="domain"` (en plus des champs existants `url`, `name`, `needs_browser=True`, `follow_event_links`, `prefilter_by_month=False`, et `mode` si festival).

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/gui/test_inputs.py` (dans les tests URL) :

```python
def test_url_input_sets_follow_scope_domain(monkeypatch):
    captured = {}

    class FakeWeb:
        def __init__(self, config):
            captured["config"] = config

        def collect(self, month):
            return iter(())

    monkeypatch.setattr(inputs, "WebConnector", FakeWeb)
    inputs.items_from_urls([inputs.UrlInput(url="https://ex.fr/a", follow_links=True)], month="2026-10")
    site = captured["config"]["websites"][0]
    assert site["follow_scope"] == "domain"
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `pytest tests/gui/test_inputs.py::test_url_input_sets_follow_scope_domain -v`
Expected: FAIL (`KeyError: 'follow_scope'`).

- [ ] **Step 3: Écrire l'implémentation**

Dans `tapageur/gui/inputs.py`, fonction `_url_to_site`, ajouter la clé au dict `site` :

```python
    site: dict = {
        "url": u.url,
        "name": u.url,
        "needs_browser": True,
        "follow_event_links": u.follow_links,
        "follow_scope": "domain",       # GUI : « suivre les liens » = découverte domaine + pré-filtre
        "prefilter_by_month": False,
    }
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/gui/test_inputs.py -v` puis `pytest -q`
Expected: tous PASS (le nouveau + les 4 existants ; suite entière verte).

- [ ] **Step 5: Commit**

```bash
git add tapageur/gui/inputs.py tests/gui/test_inputs.py
git commit -m "feat(gui): « suivre les liens » active le scope domaine du connecteur

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Validation de bout en bout (manuelle, après Task 4)

Avec une clé API renseignée dans l'app, sur `https://www.cpfi-lemans.com/festival/`,
case « suivre les liens » cochée, « ne pas filtrer par mois » cochée : l'app doit
découvrir les slugs racine, pré-filtrer les pages d'événement (diphonie,
polyphonies, arabesques…), les fetcher et en extraire des événements individuels
**avec lieu** (ex. « Au CPFI – Musiques du Monde »). Si le pré-filtre ne tourne
pas, l'app retombe sur la page d'index (events sans lieu) plutôt que 0.

## Hors périmètre
- Exposer `follow_scope`/`event_link_pattern` dans l'UI.
- Liens cross-domaine (billetterie externe).
- Récursion multi-niveaux.
