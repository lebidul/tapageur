# Design : pagination des pages d'agenda (connecteur web)

Date : 2026-10-27
Statut : validé (feature dispatchée, spec complète)

## Problème

Quand une page d'agenda est paginée, `WebConnector.collect` ne lit que la **page 1** :
les events des pages suivantes sont perdus.

Cas réel : `https://leoliennearnage.fr/programme-concerts-spectacles/` a **4 pages**
(pagination Elementor / WP Grid Builder), soit **24 events uniques** ; seuls les 6 de
la page 1 sont actuellement collectés.

**Cause** : `_extract_subpages` canonise les liens sur `scheme://host/path` et **ignore
les query strings**, donc les liens de pagination `?e-page-<hash>=N` (même chemin,
paramètre de requête) ne sont jamais suivis.

## Investigation (point de vigilance : AJAX ?)

Vérifié au curl le 2026-10-27 : les URLs paginées sont **rendues côté serveur**, pas
en AJAX. `?e-page-5e7f2769=2/3/4` renvoient chacune 6 events distincts en HTTP direct.
Les liens de pagination sont de vrais ancrages `<a class="page-numbers"
href="…?e-page-5e7f2769=N">` (+ `<a class="page-numbers next" …>`). Chaque page liste
les pages suivantes. → Feature viable par URL directe (curl comme WebView2). Aucune
stratégie AJAX nécessaire.

## Formes de pagination à gérer

Un lien est une **pagination** s'il reste sur le **même chemin que l'agenda** et porte
un marqueur de page :

| Forme | Exemple | Détection |
|---|---|---|
| Query Elementor | `?e-page-5e7f2769=2` | clé query commençant par `e-page`, valeur ≥ 2 |
| Query WP | `?page=2`, `?paged=2` | clé query `page`/`paged`, valeur ≥ 2 |
| Segment | `/programme/page/2/` | `{agenda_path}/page/<N>/`, N ≥ 2 |
| rel/class next | `rel="next"`, `class="… next"` | ancrage même chemin marqué « suivant » |

Une page d'**event** (chemin différent de l'agenda) n'est jamais prise pour une
pagination. La page 1 elle-même (N=1 ou pas de marqueur) est exclue de la liste.

## Architecture

Deux helpers purs dans `tapageur/connectors/web.py`, plus un branchement dans `collect`.

### `_extract_pagination_urls(html, base_url) -> list[str]`
Retourne les URLs **canoniques** des autres pages du même agenda trouvées dans `html`
(query préservée pour les formes query ; chemin `/page/N/` sinon). Contraintes :
même host, même chemin que l'agenda, marqueur de page présent, N ≥ 2. Ordonnées par N
croissant ; une cible `next` sans N numérique est ajoutée en fin. Dédoublonnées.

### `_collect_paginated_cards(first_html, base_url, fetch, pattern, scope, max_pages) -> list[tuple[str,str]]`
Union, sur **toutes** les pages de l'agenda, des paires **(URL d'event, texte de carte)**.
- Ingère la page 1 : `_extract_subpages` + `_extract_card_snippets`.
- Découvre les pages 2..N via `_extract_pagination_urls` (crawl **borné** : visite
  chaque page au plus une fois, cap `max_pages` pages au total, ≤ `max_pages-1` fetch
  supplémentaires), ré-scanne chaque page récupérée pour d'éventuelles pages de plus
  (gère les sites « next-only »).
- `fetch(url) -> html` est **injecté** (testable ; en prod `lambda u: _fetch(u,
  needs_browser=needs_browser)`).
- **Dédoublonne par URL** (première occurrence gagne, ordre de découverte préservé).

Pourquoi retourner les **cartes** et pas seulement les URLs : le pré-filtre mois
(`_filter_event_urls`) lit la date sur la carte de chaque lien. Les events des pages
2..N ont leur date dans le HTML de LEUR page, absent du HTML page 1 ; les extraire
par page garde le pré-filtre efficace (sinon « pas de date → inclure » → fetch inutiles).

### Branchement dans `collect`
Remplace l'actuel `event_urls = _extract_subpages(html, …)` (page 1 seule) par :
```
if site.get("paginate", True):
    cards_pairs = _collect_paginated_cards(html, url, lambda u: _fetch(u, needs_browser=needs_browser),
                                           event_pattern, follow_scope, _MAX_AGENDA_PAGES)
else:
    urls = _extract_subpages(html, url, event_pattern, follow_scope)
    cards_pairs = _extract_card_snippets(html, url, urls)
event_urls = [u for u, _ in cards_pairs]
```
Le pré-filtre réutilise directement `cards_pairs` au lieu de recalculer
`_extract_card_snippets`. `agenda_text` (fallback index) reste le texte de la page 1.
Le reste de `collect` (prefilter, soft-404, fallbacks, progress) est inchangé.

Activé **par défaut** : sur un site non paginé, `_extract_pagination_urls` renvoie `[]`
→ aucun fetch supplémentaire, aucun changement de comportement. Opt-out `paginate: false`.

### Cap
`_MAX_AGENDA_PAGES = 10` (constante module) — total de pages d'agenda visitées, garde-fou
anti-emballement. léolienne (4 pages) passe largement.

## Gestion d'erreur
- Un fetch de page paginée qui échoue est loggé (`[web]   pagination <url>: <e>`) et
  **ignoré** : on garde les events des pages déjà lues (dégradation douce, comme les
  fetchs d'event individuels).
- Crawl borné par `visited` (clé = host+path+query normalisés) : jamais de boucle, cap dur.

## Tests (TDD)
Unitaires `_extract_pagination_urls` :
- Elementor `?e-page-<hash>=N`, `?page=N`, `?paged=N`, `/page/N/`, `rel="next"`.
- N'inclut pas la page 1 ni N=1 ; ignore query non-page (`?lang`, `?utm`) ; ignore
  cross-domain ; ne prend pas un lien d'event (autre chemin) pour une pagination.

Unitaires `_collect_paginated_cards` (fetch mocké) :
- Union multi-pages + dédup ; cartes des pages 2..N datées ; respect du cap ;
  site « next-only » crawlé de proche en proche ; fetch d'une page en erreur → ignoré.

Intégration `collect` (fetch mocké, scope domaine) : pagination suivie → events des
pages 2..N présents ; `paginate:false` → page 1 seule ; site non paginé → inchangé.

Fixture léolienne (HTML réel capturé) si possible : page 1 avec liens `page-numbers`
+ fixtures des pages 2..N, vérifier l'union des 24 events.

Non-régression : scope subpath/domaine existant, sites non paginés, pré-filtre #12.

## YAGNI (écarté)
- Pas de support AJAX/scroll infini (non nécessaire ici ; à documenter si un site le fait).
- Pas de pagination des pages d'event détail (hors scope).
- Un seul knob (`paginate`), cap en constante — pas de surface de config superflue.
