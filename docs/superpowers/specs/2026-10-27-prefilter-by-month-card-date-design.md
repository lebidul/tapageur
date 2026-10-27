# Spec — Pré-filtre par mois avant fetch (lire la date sur la carte d'agenda)

TODO #12. Approche **A** (enrichir le signal du pré-filtre). Date : 2026-10-27.

## Problème

En GUI, chaque URL d'agenda part avec `prefilter_by_month=False`
(`tapageur/gui/inputs.py::_url_to_site`) et `follow_scope="domain"`. Le
pré-filtre Claude (`_filter_event_urls`) tourne donc en mode « page d'event vs
nav » **sans filtrage mois**, et reçoit en entrée le `get_text()` **à plat** de
l'agenda + la liste brute d'URLs. Résultat : le modèle ne relie pas un slug à sa
date, applique « en doute, inclure », et **toutes** les pages détail sont
fetchées puis normalisées. Le filtre mois n'intervient qu'en aval
(`normalize`), **après** fetch + appel modèle → fetch et calls inutiles pour les
events hors-mois.

Cas de référence : `https://leoliennearnage.fr/programme-concerts-spectacles/`,
cible **novembre 2026**. 6 events sur l'agenda, dates visibles sur chaque carte
Elementor :

| slug | date carte | dans 2026-11 ? |
|------|-----------|----------------|
| soiree-ouverture… | 25 septembre 2026 | non |
| jazz-magic | 10 octobre 2026 | non |
| jazz-magic-18h30 | 10 octobre 2026 | non |
| giedre-maxi-best-of | **16 octobre 2026** | **non** (cas cité) |
| par-monts-et-par-soi | 28 octobre 2026 | non |
| berengere-krief-sexe | 6 novembre 2026 | **oui** |

Attendu : seul `berengere-krief-sexe` est fetché ; les 5 autres (dont giedre)
sont écartés **avant** le fetch.

## Diagnostic (vérifié sur la page live)

Sur chaque carte, la date (`<span …datetime-date>16 octobre 2026</span>`) et le
lien (`<a href=".../event/giedre-maxi-best-of/">`) vivent dans des widgets
Elementor distincts mais sous un **conteneur commun** (`div.e-con…`). En
remontant depuis le `<a>`, le plus petit ancêtre contenant une date **et** un
seul lien event est exactement cette carte. Validé live : les 6 cartes se
résolvent proprement, chacune avec sa date.

## Approche retenue (A)

Donner au pré-filtre des **paires explicites** `URL candidate → texte de sa
carte (avec date)` au lieu du blob à plat, et lui demander d'exclure les
hors-mois d'après la date de carte — **en gardant « pas de date lisible →
INCLURE »** (date seulement sur la page détail) ⇒ zéro event perdu.

### Changements

1. **`_extract_card_snippets(html, base_url, urls) -> list[tuple[str, str]]`**
   (nouveau, `web.py`). Pour chaque `url` de `urls` (déjà produite par
   `_extract_subpages`), trouve le `<a>` qui pointe dessus (canonisation
   identique : `urljoin` + path sans query/fragment), remonte les ancêtres et
   renvoie le texte du **plus petit ancêtre** qui :
   - contient une **date FR** (regex `jour + mois` en toutes lettres,
     accents tolérés ; + formes numériques `jj/mm`), **et**
   - ne contient **aucun autre** lien candidat (⇒ on a isolé une carte, pas le
     conteneur de liste).
   Texte plafonné (~300 car.). Aucun ancêtre qualifiant → `""` (pas de date
   fiable). Ordre de sortie = ordre de `urls`.

2. **`_filter_event_urls(cards: list[tuple[str, str]], month) -> list[str]`**
   (signature changée : `cards` remplace `agenda_text` + `urls`). Construit un
   message utilisateur listant chaque candidat avec sa carte (ou « aucune date
   lisible »). Sanity check inchangé : ne garde que des URLs présentes dans
   `{u for u, _ in cards}`.

3. **`PREFILTER_SYSTEM`** réécrit : entrée = liens candidats chacun avec le
   texte de sa carte d'agenda (parfois vide). Deux tâches : (a) exclure
   menu/nav ; (b) si « Mois cible » fourni, exclure les events dont la **date de
   carte** est clairement hors de ce mois ; **si un lien n'a pas de date lisible
   → INCLURE** (date peut-être seulement sur la page détail). Sortie JSON
   `{"urls": [...]}` inchangée.

4. **`collect()`** (`web.py`) : après `_extract_subpages`, construit
   `cards = _extract_card_snippets(html, url, event_urls)` et appelle
   `_filter_event_urls(cards, pf_month)`.

5. **GUI `_url_to_site`** : `prefilter_by_month` passe de `False` à **`True`**
   — c'est ce qui fait réellement passer le mois cible au pré-filtre en GUI.
   Sûr grâce à « pas de date → inclure » (aucun event à date non visible n'est
   perdu ; le filtre mois aval reste le garde-fou).

## Décisions / questions tranchées

- **Zéro sur-filtrage** : la règle « pas de date → inclure » est la garde
  anti-perte. Un event dont la date n'est pas sur l'agenda est fetché comme
  avant, puis filtré en aval. On ne perd que des fetch, jamais des events.
- **Nav vs mois** : « inclure en doute » s'applique à la décision **mois** (pas
  de date), pas au routage nav : une page `/contact/` sans date reste exclue
  par son slug (tâche a).
- **PROMPT_VERSION : pas de bump.** Le pré-filtre n'est **pas** mis en cache
  disque (`cache.py` ne cache que la normalisation, clé = item + mois +
  PROMPT_VERSION). `PREFILTER_SYSTEM` n'est référencé ni par `cache.py` ni par
  `normalize.py`. Le prompt de normalisation est inchangé → aucun
  empoisonnement de cache. Bumper invaliderait inutilement tout le cache
  normalize. (cf. mémoire « bump PROMPT_VERSION à chaque modif de prompt » :
  vaut pour les prompts *cachés* de normalize, pas pour ce routeur non caché.)
- **Scope/pattern** : `_extract_card_snippets` travaille sur la liste `urls`
  déjà filtrée par `_extract_subpages`, donc indépendant du scope/pattern.
- **Extension C (déterministe)** : hors périmètre (TODO la renvoie à plus tard).

## Critères d'acceptation

1. `_extract_card_snippets` sur un HTML façon Elementor extrait, pour le lien
   giedre, une carte contenant « 16 octobre 2026 » ; pour un lien nav sans date,
   `""` ; pour un lien dont le seul ancêtre daté enveloppe aussi un autre lien
   candidat, `""` (garde anti-liste).
2. `_filter_event_urls(cards, "2026-11")` inclut « 2026-11 » et le texte des
   cartes dans le message, et applique le sanity check.
3. `collect()` passe bien des paires (URL, carte) au pré-filtre.
4. GUI : `_url_to_site(...)["prefilter_by_month"] is True`.
5. Non-régression : suite `pytest` verte (tests `_extract_subpages`, soft-404,
   fallback index, no-key, progress… inchangés en comportement).
6. (Live, opt-in, skip sans clé) sur les 6 cartes réelles + « Mois cible
   2026-11 », le pré-filtre ne retient que `berengere-krief-sexe` (giedre
   écarté). Validé manuellement sur la page live au moment du design.
