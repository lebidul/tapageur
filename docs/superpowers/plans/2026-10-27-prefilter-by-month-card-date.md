# Plan — Pré-filtre par mois avant fetch (carte d'agenda)

Spec : `docs/superpowers/specs/2026-10-27-prefilter-by-month-card-date-design.md`.
TDD, commits atomiques sur `feat/prefilter-month-card-date`. Trailer
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Tâche 1 — `_extract_card_snippets` (extraction de carte)

**Tests d'abord** (`tests/test_web.py`) :
- HTML façon Elementor (conteneur `e-con` imbriqué : widget date +
  widget bouton/lien séparés) → carte du lien contient « 16 octobre 2026 ».
- Lien nav sans date dans ses ancêtres → `""`.
- Lien dont le plus petit ancêtre daté enveloppe **aussi** un 2e lien
  candidat → `""` (garde anti-liste).
- Carte trouvée mais sans date (ancêtre daté inexistant) → `""`.
- Ordre de sortie = ordre de `urls` ; longueur = longueur de `urls`.

**Impl** (`tapageur/connectors/web.py`) :
- Regex module `_FR_DATE` : `\b\d{1,2}\s+(janvier|février|fevrier|…|décembre|
  decembre)\b` (i, accents tolérés) ; + `\b\d{1,2}/\d{1,2}(/\d{2,4})?\b`.
- `_extract_card_snippets(html, base_url, urls)` : parse une fois, construit la
  map `canonical_href -> [<a> nodes]`, `target = set(urls)`. Pour chaque url :
  prend un `<a>` qui la cible, remonte ≤ ~10 ancêtres ; premier ancêtre dont le
  texte matche `_FR_DATE` **et** dont le nombre de liens candidats (`<a>` dont
  le canonical ∈ target) == 1 → carte = `get_text(" ", strip=True)[:300]`.
  Sinon `""`. Renvoie `[(url, snippet), …]` dans l'ordre de `urls`.

## Tâche 2 — `_filter_event_urls` (nouvelle signature) + `PREFILTER_SYSTEM`

**Tests d'abord** : adapter les 2 tests existants à `(_filter_event_urls(cards,
month))` ; vérifier que le message contient le texte des cartes + « 2026-11 »,
et que le sanity check filtre les hallucinations / URLs absentes.

**Impl** :
- Réécrire `PREFILTER_SYSTEM` (cf. spec §3).
- `_filter_event_urls(cards, month)` : `valid = {u for u,_ in cards}` ; message
  = en-tête « Mois cible » optionnel + liste `[n] url` / `carte: …` (ou
  « aucune date lisible sur l'agenda »). Parse + sanity inchangés.

## Tâche 3 — câblage `collect()`

**Tests d'abord** : adapter les monkeypatch `_filter_event_urls` des tests
`collect` à la signature `(cards, month)` ; ajouter un test qui capture
l'argument reçu et vérifie que ce sont des paires (URL, texte) et non le blob.

**Impl** : dans `collect()`, remplacer l'appel par
`cards = _extract_card_snippets(html, url, event_urls)` puis
`kept = _filter_event_urls(cards, pf_month)`.

## Tâche 4 — GUI `_url_to_site`

**Test d'abord** (`tests/gui/…` ou test ciblé) : `_url_to_site(UrlInput(...))`
→ `prefilter_by_month is True`.

**Impl** : `prefilter_by_month: True` + commentaire mis à jour.

## Tâche 5 — vérification

- `pytest` complet vert.
- Test live opt-in (skip sans `ANTHROPIC_API_KEY`) : fixture 6 cartes réelles +
  mois 2026-11 → seul `berengere-krief-sexe` retenu. (Ne pas bloquer le commit
  dessus si pas de clé en CI.)

## Hors périmètre

Extension C (drop déterministe sans modèle). Pas de bump PROMPT_VERSION.
