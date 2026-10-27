# Web Agenda Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suivre la pagination des pages d'agenda du connecteur web pour collecter les events des pages 2..N (pas seulement la page 1).

**Architecture:** Deux helpers purs dans `tapageur/connectors/web.py` — `_extract_pagination_urls` (détection des liens de pagination) et `_collect_paginated_cards` (crawl borné + union des paires (url, carte) sur toutes les pages) — branchés dans `WebConnector.collect` à la place du `_extract_subpages` page-1-seul. Activé par défaut, no-op sur les sites non paginés.

**Tech Stack:** Python, BeautifulSoup, pytest, `urllib.parse`.

## Global Constraints

- Fichier unique modifié : `tapageur/connectors/web.py` ; tests : `tests/test_web.py`.
- Trailer de commit : `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Ne pas régresser : scope subpath/domaine existant, sites non paginés, pré-filtre #12.
- Cap dur : `_MAX_AGENDA_PAGES = 10` pages d'agenda au total.
- Détection sur le MÊME chemin que l'agenda uniquement ; une page d'event (chemin différent) n'est jamais prise pour une pagination ; N ≥ 2 (page 1 exclue).

---

### Task 1: `_extract_pagination_urls` + helpers de détection

**Files:**
- Modify: `tapageur/connectors/web.py` (ajout de `_MAX_AGENDA_PAGES`, `_PAGE_SEGMENT`, `_page_param`, `_extract_pagination_urls`)
- Test: `tests/test_web.py`

**Interfaces:**
- Produces:
  - `_MAX_AGENDA_PAGES: int = 10`
  - `_page_param(query: str) -> int | None` — N de page si la query porte un marqueur (`page`, `paged`, ou clé commençant par `e-page`), sinon None.
  - `_extract_pagination_urls(html: str, base_url: str) -> list[str]` — URLs canoniques des autres pages du même agenda (query préservée pour les formes query, chemin `/page/N/` sinon), ordonnées par N croissant puis cibles `next` sans N.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# ---------- _extract_pagination_urls ----------

_PAGINATION_BASE = "https://site.fr/programme/"

def test_pagination_elementor_e_page_hash():
    from tapageur.connectors.web import _extract_pagination_urls
    html = '''
      <a class="page-numbers" href="https://site.fr/programme/?e-page-5e7f2769=2">2</a>
      <a class="page-numbers" href="https://site.fr/programme/?e-page-5e7f2769=3">3</a>
      <a class="page-numbers next" href="https://site.fr/programme/?e-page-5e7f2769=2">»</a>
    '''
    out = _extract_pagination_urls(html, _PAGINATION_BASE)
    assert out == [
        "https://site.fr/programme/?e-page-5e7f2769=2",
        "https://site.fr/programme/?e-page-5e7f2769=3",
    ]

def test_pagination_query_page_and_paged():
    from tapageur.connectors.web import _extract_pagination_urls
    html = '''<a href="/programme/?page=2">2</a>
              <a href="/programme/?paged=3">3</a>'''
    out = _extract_pagination_urls(html, _PAGINATION_BASE)
    assert out == ["https://site.fr/programme/?page=2",
                   "https://site.fr/programme/?paged=3"]

def test_pagination_path_segment():
    from tapageur.connectors.web import _extract_pagination_urls
    html = '<a href="/programme/page/2/">2</a><a href="/programme/page/3/">3</a>'
    out = _extract_pagination_urls(html, _PAGINATION_BASE)
    assert out == ["https://site.fr/programme/page/2/",
                   "https://site.fr/programme/page/3/"]

def test_pagination_rel_next_same_path_without_number():
    """rel=next sur le même chemin mais query non numérotable → suivi quand même."""
    from tapageur.connectors.web import _extract_pagination_urls
    html = '<a rel="next" href="/programme/?after=abc123">suivant</a>'
    out = _extract_pagination_urls(html, _PAGINATION_BASE)
    assert out == ["https://site.fr/programme/?after=abc123"]

def test_pagination_excludes_page_one_and_non_page_query():
    from tapageur.connectors.web import _extract_pagination_urls
    html = '''<a href="/programme/?e-page-x=1">1</a>
              <a href="/programme/?lang=en">EN</a>
              <a href="/programme/?utm=foo">x</a>'''
    assert _extract_pagination_urls(html, _PAGINATION_BASE) == []

def test_pagination_ignores_event_pages_and_cross_domain():
    """Un lien d'event (autre chemin) ou cross-domain n'est pas une pagination."""
    from tapageur.connectors.web import _extract_pagination_urls
    html = '''<a href="/event/giedre/?page=2">event</a>
              <a href="https://evil.com/programme/?page=2">evil</a>'''
    assert _extract_pagination_urls(html, _PAGINATION_BASE) == []

def test_page_param_detects_markers():
    from tapageur.connectors.web import _page_param
    assert _page_param("e-page-5e7f2769=4") == 4
    assert _page_param("page=2") == 2
    assert _page_param("paged=3") == 3
    assert _page_param("lang=en") is None
    assert _page_param("") is None
```

- [ ] **Step 2: Lancer les tests → échec attendu**

Run: `python -m pytest tests/test_web.py -k "pagination or page_param" -q`
Expected: FAIL (`ImportError: cannot import name '_extract_pagination_urls'`).

- [ ] **Step 3: Implémenter** (après `_extract_subpages`, avant la section cache `_FETCH_CACHE`)

```python
# Nombre max de pages d'agenda visitées (page 1 incluse) : garde-fou
# anti-emballement sur les paginations longues/circulaires.
_MAX_AGENDA_PAGES = 10

# Segment de pagination « /page/N/ » (WordPress et consorts).
_PAGE_SEGMENT = re.compile(r"/page/(\d+)/?$")


def _page_param(query: str) -> int | None:
    """N de page depuis une query string si elle porte un marqueur de pagination
    (clé 'page', 'paged', ou clé commençant par 'e-page' — Elementor/WP Grid
    Builder nomme la sienne 'e-page-<hash>'). Sinon None."""
    from urllib.parse import parse_qs
    for key, vals in parse_qs(query).items():
        k = key.lower()
        if k in ("page", "paged") or k.startswith("e-page"):
            for v in vals:
                if v.isdigit():
                    return int(v)
    return None


def _extract_pagination_urls(html: str, base_url: str) -> list[str]:
    """Liens vers les AUTRES pages du même agenda paginé trouvés dans `html`.

    Un lien est une pagination s'il reste sur le MÊME chemin que l'agenda et
    porte un marqueur de page : query `?page=N`/`?paged=N`/`?e-page*=N`, segment
    `/page/N/`, ou attribut `rel="next"` / classe `…next` (même chemin). N >= 2
    (la page 1 est exclue). Retourne des URLs canoniques (query préservée pour
    les formes query ; chemin `/page/N/` sinon), ordonnées par N croissant, puis
    les cibles « next » sans N numérique. Une page d'event (chemin différent) ou
    cross-domaine n'est jamais prise pour une pagination."""
    base = urlparse(base_url)
    base_path = base.path.rstrip("/")
    soup = BeautifulSoup(html, "html.parser")

    numbered: dict[int, str] = {}
    extra: list[str] = []  # cibles « next » sans N exploitable (sites next-only)
    seen_extra: set[str] = set()

    for tag in soup.find_all(["a", "link"], href=True):
        p = urlparse(urljoin(base_url, tag["href"]))
        if p.netloc != base.netloc or p.scheme not in ("http", "https"):
            continue
        path = p.path.rstrip("/")

        # Forme segment « /page/N/ » (le préfixe doit être le chemin de l'agenda).
        m = _PAGE_SEGMENT.search(p.path)
        if m and path[: m.start()].rstrip("/") == base_path:
            n = int(m.group(1))
            if n >= 2:
                numbered.setdefault(n, f"{p.scheme}://{p.netloc}{p.path}")
            continue

        if path != base_path:
            continue  # pas le chemin de l'agenda → pas une pagination

        # Forme query numérotée.
        if p.query:
            n = _page_param(p.query)
            if n is not None and n >= 2:
                numbered.setdefault(n, f"{p.scheme}://{p.netloc}{p.path}?{p.query}")
                continue

        # rel="next" / classe …next sur le même chemin, sans N exploitable.
        rel = [r.lower() for r in (tag.get("rel") or [])]
        cls = [c.lower() for c in (tag.get("class") or [])]
        is_next = "next" in rel or any("next" in c for c in cls)
        if is_next and p.query:
            u = f"{p.scheme}://{p.netloc}{p.path}?{p.query}"
            if u not in seen_extra:
                seen_extra.add(u)
                extra.append(u)

    out = [numbered[n] for n in sorted(numbered)]
    for u in extra:
        if u not in out:
            out.append(u)
    return out
```

- [ ] **Step 4: Lancer les tests → vert**

Run: `python -m pytest tests/test_web.py -k "pagination or page_param" -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add tapageur/connectors/web.py tests/test_web.py
git commit -m "feat(web): détection des liens de pagination d'agenda

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `_collect_paginated_cards` (crawl borné + union)

**Files:**
- Modify: `tapageur/connectors/web.py` (ajout de `_page_key`, `_collect_paginated_cards`)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `_extract_subpages`, `_extract_card_snippets`, `_extract_pagination_urls`, `_MAX_AGENDA_PAGES` (Task 1).
- Produces:
  - `_page_key(url: str) -> tuple[str, str, str]` — clé de dédup (host, path sans slash final, query).
  - `_collect_paginated_cards(first_html: str, base_url: str, fetch: Callable[[str], str], pattern: str | None = None, scope: str = "subpath", max_pages: int = _MAX_AGENDA_PAGES) -> list[tuple[str, str]]` — paires (url event, carte) sur toutes les pages, dédupliquées par URL (1re vue), ordre de découverte.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# ---------- _collect_paginated_cards ----------

def test_collect_paginated_cards_unions_pages():
    """Page 1 → events A,B + liens vers pages 2 et 3 ; pages 2,3 → autres events."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    p1 = f'''
      <div><span>5 novembre 2026</span><a href="/event/a/">A</a></div>
      <a class="page-numbers" href="{base}?e-page-h=2">2</a>
      <a class="page-numbers" href="{base}?e-page-h=3">3</a>'''
    p2 = '<div><span>6 novembre 2026</span><a href="/event/b/">B</a></div>'
    p3 = '<div><span>7 novembre 2026</span><a href="/event/c/">C</a></div>'
    pages = {f"{base}?e-page-h=2": p2, f"{base}?e-page-h=3": p3}
    pairs = _collect_paginated_cards(p1, base, lambda u: pages[u], scope="domain")
    cards = dict(pairs)
    assert set(cards) == {"https://site.fr/event/a/", "https://site.fr/event/b/",
                          "https://site.fr/event/c/"}
    assert "5 novembre 2026" in cards["https://site.fr/event/a/"]
    assert "6 novembre 2026" in cards["https://site.fr/event/b/"]
    assert "7 novembre 2026" in cards["https://site.fr/event/c/"]

def test_collect_paginated_cards_dedups_repeated_events():
    """Un event présent sur 2 pages n'apparaît qu'une fois (1re occurrence)."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    p1 = f'''<div><span>5 novembre 2026</span><a href="/event/a/">A</a></div>
             <a class="page-numbers" href="{base}?page=2">2</a>'''
    p2 = '<div><span>5 novembre 2026</span><a href="/event/a/">A again</a></div>'
    pairs = _collect_paginated_cards(p1, base, lambda u: p2, scope="domain")
    assert [u for u, _ in pairs] == ["https://site.fr/event/a/"]

def test_collect_paginated_cards_next_only_crawl():
    """Site « next-only » : chaque page ne lie que la suivante → crawl en chaîne."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    p1 = f'<a href="/event/a/">A</a><a class="next" href="{base}?paged=2">›</a>'
    p2 = f'<a href="/event/b/">B</a><a class="next" href="{base}?paged=3">›</a>'
    p3 = '<a href="/event/c/">C</a>'
    pages = {f"{base}?paged=2": p2, f"{base}?paged=3": p3}
    pairs = _collect_paginated_cards(p1, base, lambda u: pages[u], scope="domain")
    assert {u for u, _ in pairs} == {"https://site.fr/event/a/",
                                     "https://site.fr/event/b/",
                                     "https://site.fr/event/c/"}

def test_collect_paginated_cards_respects_cap():
    """Au plus max_pages pages visitées (page 1 incluse) → fetchs bornés."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    # chaque page i lie i+1 à l'infini
    def fetch(u):
        from urllib.parse import urlparse, parse_qs
        n = int(parse_qs(urlparse(u).query)["paged"][0])
        return f'<a href="/event/e{n}/">E{n}</a><a class="next" href="{base}?paged={n+1}">›</a>'
    p1 = f'<a href="/event/e1/">E1</a><a class="next" href="{base}?paged=2">›</a>'
    calls = {"n": 0}
    def counting_fetch(u):
        calls["n"] += 1
        return fetch(u)
    pairs = _collect_paginated_cards(p1, base, counting_fetch, scope="domain", max_pages=3)
    assert calls["n"] == 2            # page 1 (non fetchée ici) + 2 fetchs = 3 pages
    assert len(pairs) == 3            # e1, e2, e3

def test_collect_paginated_cards_tolerates_fetch_error():
    """Un fetch de page paginée en erreur est ignoré ; les autres restent."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    p1 = f'''<a href="/event/a/">A</a>
             <a class="page-numbers" href="{base}?page=2">2</a>
             <a class="page-numbers" href="{base}?page=3">3</a>'''
    def fetch(u):
        if u.endswith("page=2"):
            raise RuntimeError("boom")
        return '<a href="/event/c/">C</a>'
    pairs = _collect_paginated_cards(p1, base, fetch, scope="domain")
    urls = {u for u, _ in pairs}
    assert "https://site.fr/event/a/" in urls   # page 1
    assert "https://site.fr/event/c/" in urls   # page 3 (page 2 en erreur, ignorée)

def test_collect_paginated_cards_no_pagination_single_page():
    """Site non paginé : aucune page supplémentaire fetchée."""
    from tapageur.connectors.web import _collect_paginated_cards
    base = "https://site.fr/programme/"
    p1 = '<div><span>5 novembre 2026</span><a href="/event/a/">A</a></div>'
    calls = []
    pairs = _collect_paginated_cards(p1, base, lambda u: calls.append(u) or "", scope="domain")
    assert calls == []                                   # aucun fetch
    assert [u for u, _ in pairs] == ["https://site.fr/event/a/"]
```

- [ ] **Step 2: Lancer les tests → échec attendu**

Run: `python -m pytest tests/test_web.py -k "collect_paginated_cards" -q`
Expected: FAIL (`ImportError: cannot import name '_collect_paginated_cards'`).

- [ ] **Step 3: Implémenter** (après `_extract_pagination_urls`)

```python
def _page_key(url: str) -> tuple[str, str, str]:
    """Clé de dédup d'une page d'agenda (host, path sans slash final, query)."""
    p = urlparse(url)
    return (p.netloc, p.path.rstrip("/"), p.query)


def _collect_paginated_cards(
    first_html: str,
    base_url: str,
    fetch,
    pattern: str | None = None,
    scope: str = "subpath",
    max_pages: int = _MAX_AGENDA_PAGES,
) -> list[tuple[str, str]]:
    """Union des paires (URL d'event, texte de carte) sur toutes les pages d'un
    agenda paginé (page 1 + pages 2..N découvertes via `_extract_pagination_urls`).

    `fetch(url) -> html` est injecté (testable ; en prod `lambda u: _fetch(u,
    needs_browser=...)`). Crawl borné : chaque page visitée au plus une fois, au
    plus `max_pages` pages au total. Chaque page est passée à `_extract_subpages`
    puis `_extract_card_snippets` (les cartes des pages 2..N portent LEUR date, ce
    que le pré-filtre mois exploite). Dédoublonne par URL (1re occurrence gagne,
    ordre de découverte préservé). Un fetch de page en erreur est loggé et ignoré."""
    pairs: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    def _ingest(html: str) -> None:
        urls = _extract_subpages(html, base_url, pattern=pattern, scope=scope)
        for u, snip in _extract_card_snippets(html, base_url, urls):
            if u not in seen_urls:
                seen_urls.add(u)
                pairs.append((u, snip))

    visited: set[tuple[str, str, str]] = {_page_key(base_url)}
    pending: list[str] = []

    def _enqueue(html: str) -> None:
        for pu in _extract_pagination_urls(html, base_url):
            k = _page_key(pu)
            if k not in visited:
                visited.add(k)
                pending.append(pu)

    _ingest(first_html)
    _enqueue(first_html)

    n_fetched = 0
    while pending and n_fetched < max_pages - 1:
        pu = pending.pop(0)
        try:
            phtml = fetch(pu)
        except Exception as e:
            print(f"[web]   pagination {pu}: {e}")
            continue
        n_fetched += 1
        _ingest(phtml)
        _enqueue(phtml)

    return pairs
```

- [ ] **Step 4: Lancer les tests → vert**

Run: `python -m pytest tests/test_web.py -k "collect_paginated_cards" -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add tapageur/connectors/web.py tests/test_web.py
git commit -m "feat(web): union multi-pages des events (crawl pagination borné)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Branchement dans `WebConnector.collect`

**Files:**
- Modify: `tapageur/connectors/web.py` (corps de `collect`, section « Mode follow »)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `_collect_paginated_cards` (Task 2), `_extract_subpages`, `_extract_card_snippets`.
- Produces: comportement de `collect` suivant la pagination quand `site.get("paginate", True)`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
def test_collect_follows_pagination_unions_events(monkeypatch):
    """collect() en scope domaine suit la pagination et collecte les events des
    pages 2..N (fetch mocké)."""
    import tapageur.connectors.web as web
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # pas de pré-filtre
    base = "https://site.fr/programme/"
    p1 = (f'<div><span>5 nov 2026</span><a href="/event/a/">A</a></div>'
          f'<a class="page-numbers" href="{base}?e-page-h=2">2</a>')
    p2 = '<div><span>6 nov 2026</span><a href="/event/b/">B</a></div>'
    def fake_fetch(url, needs_browser=False):
        if url == base:
            return p1
        if url == f"{base}?e-page-h=2":
            return p2
        return "<p>Concert détail</p>"
    monkeypatch.setattr(web, "_fetch", fake_fetch)
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    conn = web.WebConnector({"websites": [{
        "url": base, "name": "s", "follow_event_links": True,
        "follow_scope": "domain", "prefilter_by_month": False,
    }]})
    refs = {it.source_ref for it in conn.collect("2026-11")}
    assert "https://site.fr/event/a/" in refs
    assert "https://site.fr/event/b/" in refs   # page 2 suivie

def test_collect_paginate_false_single_page(monkeypatch):
    """paginate:false → page 1 seule (pas de suivi des liens de pagination)."""
    import tapageur.connectors.web as web
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    base = "https://site.fr/programme/"
    p1 = (f'<a href="/event/a/">A</a>'
          f'<a class="page-numbers" href="{base}?e-page-h=2">2</a>')
    fetched = []
    def fake_fetch(url, needs_browser=False):
        fetched.append(url)
        return p1 if url == base else "<p>détail</p>"
    monkeypatch.setattr(web, "_fetch", fake_fetch)
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    conn = web.WebConnector({"websites": [{
        "url": base, "name": "s", "follow_event_links": True,
        "follow_scope": "domain", "prefilter_by_month": False, "paginate": False,
    }]})
    refs = {it.source_ref for it in conn.collect("2026-11")}
    assert refs == {"https://site.fr/event/a/"}
    assert f"{base}?e-page-h=2" not in fetched   # page 2 jamais fetchée

def test_collect_prefilter_receives_cards_from_all_pages(monkeypatch):
    """Le pré-filtre reçoit les cartes (datées) des events de TOUTES les pages."""
    import tapageur.connectors.web as web
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    base = "https://site.fr/programme/"
    p1 = (f'<div><span>16 octobre 2026</span><a href="/event/a/">A</a></div>'
          f'<a class="page-numbers" href="{base}?e-page-h=2">2</a>')
    p2 = '<div><span>6 novembre 2026</span><a href="/event/b/">B</a></div>'
    def fake_fetch(url, needs_browser=False):
        if url == base: return p1
        if url == f"{base}?e-page-h=2": return p2
        return "<p>détail</p>"
    monkeypatch.setattr(web, "_fetch", fake_fetch)
    monkeypatch.setattr(web, "_is_pdf_url", lambda url: False)
    captured = {}
    def fake_prefilter(cards, month):
        captured["cards"] = dict(cards)
        return [u for u, _ in cards]
    monkeypatch.setattr(web, "_filter_event_urls", fake_prefilter)
    conn = web.WebConnector({"websites": [{
        "url": base, "name": "s", "follow_event_links": True,
        "follow_scope": "domain", "prefilter_by_month": True,
    }]})
    list(conn.collect("2026-11"))
    assert "16 octobre 2026" in captured["cards"]["https://site.fr/event/a/"]
    assert "6 novembre 2026" in captured["cards"]["https://site.fr/event/b/"]  # page 2
```

- [ ] **Step 2: Lancer les tests → échec attendu**

Run: `python -m pytest tests/test_web.py -k "follows_pagination or paginate_false or cards_from_all_pages" -q`
Expected: FAIL (page 2 non suivie / `site.fr/event/b/` absent).

- [ ] **Step 3: Implémenter** — dans `collect`, remplacer le bloc actuel

Remplacer (lignes ~146-148) :
```python
            event_pattern = site.get("event_link_pattern")
            event_urls = _extract_subpages(html, base_url=url, pattern=event_pattern, scope=follow_scope)
            agenda_text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            print(f"[web] {site_name}: {len(event_urls)} URLs candidates (scope={follow_scope})")
```
par :
```python
            event_pattern = site.get("event_link_pattern")
            # paginate (défaut True) : suit les pages 2..N de l'agenda et unit la
            # découverte des events. No-op sur un site non paginé (0 lien trouvé).
            if site.get("paginate", True):
                cards_pairs = _collect_paginated_cards(
                    html, url, lambda u: _fetch(u, needs_browser=needs_browser),
                    pattern=event_pattern, scope=follow_scope)
            else:
                urls0 = _extract_subpages(html, base_url=url, pattern=event_pattern, scope=follow_scope)
                cards_pairs = _extract_card_snippets(html, url, urls0)
            event_urls = [u for u, _ in cards_pairs]
            agenda_text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            print(f"[web] {site_name}: {len(event_urls)} URLs candidates (scope={follow_scope})")
```
Puis, dans la branche `if run_prefilter:`, remplacer :
```python
                cards = _extract_card_snippets(html, url, event_urls)
```
par :
```python
                # Cartes déjà extraites page par page (toutes les pages d'agenda),
                # y compris les dates des events des pages 2..N.
                cards = cards_pairs
```

- [ ] **Step 4: Lancer la suite web complète → vert**

Run: `python -m pytest tests/test_web.py -q`
Expected: PASS (anciens + nouveaux tests).

- [ ] **Step 5: Commit**

```bash
git add tapageur/connectors/web.py tests/test_web.py
git commit -m "feat(web): collect() suit la pagination des pages d'agenda

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Régression sur la vraie page léolienne (fixture HTML réel)

**Files:**
- Create: `tests/fixtures/leolienne_programme_page1.html` (page 1 réelle capturée le 2026-10-27)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `_extract_pagination_urls` (Task 1).

- [ ] **Step 1: Créer la fixture** (page 1 réelle déjà capturée au curl)

```bash
cp /tmp/leo1.html tests/fixtures/leolienne_programme_page1.html
```

- [ ] **Step 2: Écrire le test qui échoue si la détection casse**

```python
# ---------- Régression : vraie page léolienne (pagination Elementor) ----------

_LEO_PROG_FIXTURE = Path(__file__).parent / "fixtures" / "leolienne_programme_page1.html"
_LEO_PROG_URL = "https://leoliennearnage.fr/programme-concerts-spectacles/"

def test_leolienne_real_page1_pagination_detected():
    """Sur la vraie page 1 léolienne (markup Elementor `page-numbers`), les 3
    pages suivantes (?e-page-5e7f2769=2/3/4) sont détectées — ni plus, ni moins."""
    from tapageur.connectors.web import _extract_pagination_urls
    html = _LEO_PROG_FIXTURE.read_text(encoding="utf-8")
    out = _extract_pagination_urls(html, _LEO_PROG_URL)
    assert out == [
        f"{_LEO_PROG_URL}?e-page-5e7f2769=2",
        f"{_LEO_PROG_URL}?e-page-5e7f2769=3",
        f"{_LEO_PROG_URL}?e-page-5e7f2769=4",
    ]
```

- [ ] **Step 3: Lancer → vert** (la fixture et le code existent déjà)

Run: `python -m pytest tests/test_web.py -k leolienne -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/leolienne_programme_page1.html tests/test_web.py
git commit -m "test(web): régression pagination sur la vraie page léolienne

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage :**
- Détection `?e-page-<hash>=N`, `?page=N`, `?paged=N`, `/page/N/`, `rel=next` → Task 1 (tests dédiés chacun).
- Ne pas confondre event/pagination → Task 1 `test_pagination_ignores_event_pages_and_cross_domain`.
- Fetch pages 2..N + union + cap + dédup → Task 2.
- Intégration `collect` + `_fetch(needs_browser)` → Task 3.
- Cartes datées des pages 2..N pour le pré-filtre → Task 2 + Task 3 `test_collect_prefilter_receives_cards_from_all_pages`.
- Point AJAX → résolu en amont (spec) : rendu serveur, pas d'action plan nécessaire.
- Fixture léolienne → Task 4.
- Non-régression sites non paginés / scope → Task 2 `no_pagination_single_page`, Task 3 `paginate_false`, suite existante (Task 3 step 4).

**2. Placeholder scan :** aucun TBD/TODO ; tout le code est écrit.

**3. Type consistency :** `_collect_paginated_cards(... ) -> list[tuple[str,str]]` consommé en `cards_pairs` (list de paires) et passé à `_filter_event_urls(cards, month)` qui attend `list[tuple[str,str]]` ✓. `_extract_pagination_urls -> list[str]` ✓. `_page_param -> int | None` ✓.

## Execution Handoff

Exécution **inline** dans cette session (session dispatchée autonome) via superpowers:executing-plans, commits atomiques par tâche.
