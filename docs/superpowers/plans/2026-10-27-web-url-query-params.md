# Plan : découverte d'URL events query-param + diagnostic La Perche

Spec : `docs/superpowers/specs/2026-10-27-web-url-query-params-design.md`
Branche : `feat/web-url-query-params` (depuis `main`). Commits atomiques, TDD.

## Étape 1 — `_clean_query` (helper pur)
TDD. Tests unitaires d'abord (tests/test_web.py, nouvelle section) :
- strippe tracking (`utm_source`, `utm_*`, `fbclid`, `gclid`, `gad_source`, `mc_cid`, `ref`) ;
- strippe pagination (`page`, `paged`, `e-page-abc`) ;
- garde `saison_culturelle=bel-ami` et params génériques (`event`, `p`, `id`) ;
- query mixte tracking+signifiant → ne garde que le signifiant ;
- trie les clés (stabilité dédup) ; query vide / que-du-tracking → `""`.
Impl : `_clean_query(query)` via `parse_qsl` (garde l'ordre des valeurs), filtre clés,
`urlencode` trié. Constantes module `_TRACKING_PARAMS` (set), `_TRACKING_PREFIXES`,
réutilise la notion de clé pagination (helper `_is_pagination_key`).
Commit : `feat(web): helper _clean_query (strippe tracking + pagination, garde le reste)`.

## Étape 2 — canonisation query-aware dans `_canonical_url` + `_extract_subpages`
TDD. Tests :
- `_extract_subpages` scope domaine : 3 liens même chemin, query `saison_culturelle`
  différentes → 3 candidats distincts ; 2 liens même chemin dont `?utm=` → fusion ;
  `?page=2` sur un autre chemin → pas un candidat event distinct.
- `_canonical_url` renvoie la query nettoyée (match ancre).
Impl : `_canonical_url` → `scheme://host/path[?_clean_query]` ; `_extract_subpages`
construit `canonical` via `_canonical_url` dans les 2 modes (défaut + pattern).
Vérifier les tests existants verts (dedup fragment/query, pattern msj, taxonomy).
Commit : `feat(web): préserve les query params signifiants dans _extract_subpages`.

## Étape 3 — fixture réelle la-ferte-bernard + test d'intégration découverte
Capturer `tests/fixtures/laferte_centre_culturel.html` (curl, déjà en /tmp).
Test : `_extract_subpages(scope="domain")` sur la fixture → 25 URLs contenant
`saison_culturelle`, toutes distinctes ; une (au hasard) matche le slug attendu.
Commit : `test(web): fixture réelle la-ferte-bernard, 25 events query-param distincts`.

## Étape 4 — fixture réelle La Perche + test de diagnostic (cas 2)
Capturer `tests/fixtures/laperche_billetterie.html`.
Test : `_extract_subpages(scope="domain")` → 0 lien détail same-host portant un slug
d'artiste (tous les détails sont weezevent/fnac cross-domaine) ; le texte extrait de la
page contient les 6 dates/artistes (→ repli-index les récupère). Docstring = diagnostic
« billetterie externe, pas de découverte d'URL ».
Commit : `test(web): La Perche = billetterie externe (Weezevent/Fnac), pas de découverte d'URL`.

## Étape 5 — suite complète + PR
`pytest` complet vert (aucune régression). PR avec résumé des 2 cas, trailer
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Garde-fous
- Ne PAS toucher `_extract_pagination_urls` / `_page_key`.
- Garder les filtres de scope sur le chemin.
- `python -I` depuis le worktree importe le checkout main → `sys.path.insert(0, worktree)`
  pour tout check manuel (piège env noté en #15).
