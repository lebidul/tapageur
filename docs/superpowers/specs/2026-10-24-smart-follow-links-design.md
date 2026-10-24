# « Suivre les liens » intelligent (découverte domaine + pré-filtre) — Design

**Date :** 2026-10-24
**Statut :** validé (brainstorming), prêt pour plan d'implémentation
**Branche :** feat/tapageur-gui
**Auteur :** Thibault Uzu + Claude

## 1. Problème

En mode « suivre les liens » (`follow_event_links: true`), le connecteur web
(`tapageur/connectors/web.py`) ne découvre que les liens **sous le chemin** de
l'URL d'agenda (heuristique sous-chemin stricte dans `_extract_subpages`), sauf
si un `event_link_pattern` (regex) est fourni.

Cas réel qui casse (debuggé le 2026-10-24) : `https://www.cpfi-lemans.com/festival/`.
Les pages d'événement sont des **slugs à la racine du site**
(`/diphonie-des-steppes/`, `/polyphonies-georgiennes/`, …), **mêlées aux pages
de menu** (`/contact/`, `/actualites/`, `/les-instruments/`…). Aucune n'est un
sous-chemin de `/festival/` → `0 URLs candidates` → **0 événement**, alors que
les pages de détail sont riches (lieu, heure, prix, artistes).

## 2. Objectif

En mode « suivre les liens », pouvoir découvrir les pages d'événement qui sont
des **liens frères du même hôte** (pas seulement des sous-chemins), puis laisser
**Claude** trier les vraies pages d'événement d'après le texte de l'agenda
(les slugs correspondent aux titres listés ; les pages de menu sont écartées).

## 3. Décisions de cadrage (brainstorming)

| Sujet | Décision |
|-------|----------|
| **UX GUI** | Réutiliser la case existante **« suivre les liens »** : elle active le mode intelligent (découverte domaine + pré-filtre). Aucun nouveau contrôle. |
| **Fallback** | Si le pré-filtre ne peut pas tourner (pas de clé API, ou échec) OU ne retient aucune URL en mode domaine → **retomber sur la page d'index** (émise comme item). Jamais de 0 silencieux, jamais de fetch massif des pages de menu. |
| **Rétrocompat CLI** | Nouvelle option `follow_scope` défaut `"subpath"` → les configs CLI existantes ne changent pas de comportement. |

## 4. Changements

### 4.1 `web.py` — option `follow_scope` (nouvelle, rétrocompatible)
Chaque entrée `websites:` peut porter `follow_scope`:
- `"subpath"` (**défaut**) — comportement actuel : liens sous le chemin de l'URL d'agenda.
- `"domain"` — tous les liens du **même hôte** que l'URL d'agenda, après exclusion
  de : l'URL d'agenda elle-même, les ancres (`#...`), `mailto:`/`tel:`/`javascript:`,
  les schémas non-http(s), et les variantes qui ne diffèrent que par un fragment.
  Déduplique. `event_link_pattern`, s'il est fourni, continue de primer sur le scope.

`_extract_subpages(html, base_url, pattern=None, scope="subpath")` gagne le
paramètre `scope`. La logique pattern reste prioritaire ; sinon le filtrage
dépend du scope.

### 4.2 `web.py` — pré-filtre Claude généralisé
Le pré-filtre actuel `_filter_urls_by_month(agenda_text, urls, month)` choisit
les URLs d'un **mois**. On le généralise :

`_filter_event_urls(agenda_text, urls, month: str | None) -> list[str]`
- `month` = `None` → « quelles URLs candidates sont des **pages d'événement**
  (vs menu, à-propos, contact, mentions légales…) d'après le texte d'agenda ».
- `month` = `"YYYY-MM"` → en plus, uniquement celles dont l'événement est dans ce mois.
- En cas d'incertitude : **inclure** (mieux vaut un fetch inutile qu'un event raté),
  comportement conservé de l'actuel.

(Implémentation : un seul prompt système qui prend en compte la présence ou non
d'un mois cible. L'ancien nom peut être conservé en alias si d'autres appelants
l'utilisent — vérifier ; aujourd'hui seul `web.collect` l'appelle.)

### 4.3 `web.py` — orchestration dans `collect()` (branche follow)
Pour une entrée en mode follow :
1. `candidates = _extract_subpages(html, url, pattern=event_link_pattern, scope=follow_scope)`.
2. Décider si on pré-filtre :
   `run_prefilter = bool(candidates) and ANTHROPIC_API_KEY présente and (prefilter_by_month OR follow_scope == "domain")`.
3. Si `run_prefilter` :
   - `pf_month = month if prefilter_by_month else None` (le connecteur ne
     contraint au mois que si `prefilter_by_month` est actif ; en scope domaine
     sans filtrage mois, on choisit « pages d'événement » tout court).
   - `kept = _filter_event_urls(agenda_text, candidates, pf_month)`.
   - Si `follow_scope == "domain"` et `kept` est **vide** → **fallback index**
     (émettre la page d'index comme item web) et `continue`.
   - Sinon `candidates = kept`.
4. Si `follow_scope == "domain"` et pré-filtre impossible (pas de clé) →
   **fallback index** et `continue` (éviter de fetcher tout le menu).
5. Fetch chaque URL retenue + yield (comportement actuel).

Le **fallback index** = exactement la branche `not follow` existante (dump du
texte de l'agenda en un `CollectedItem` web, avec `mode`/`model_override`
propagés) → à factoriser en un petit helper pour éviter la duplication.

Comportement `subpath` (CLI) inchangé : le pré-filtre ne tourne que si
`prefilter_by_month` (défaut `True`), avec contrainte mois, et pas de fallback
index (on garde le comportement historique : 0 sous-page = 0 item).

### 4.4 GUI — `inputs.py`
`_url_to_site` ajoute `"follow_scope": "domain"` à l'entrée synthétique. Combiné
à `follow_event_links = u.follow_links` et `prefilter_by_month = False` déjà en
place : quand l'utilisateur coche « suivre les liens », le connecteur découvre
les liens du domaine et pré-filtre (mois `None` → pages d'événement), avec
fallback index. Quand la case est décochée, `follow_event_links=False` → la page
d'index est émise (comportement actuel, inchangé).

## 5. Flux sur cpfi-lemans.com (exemple)
1. `/festival/` fetchée (navigateur). `follow_scope="domain"` → ~25 liens du domaine.
2. Pré-filtre (1 appel Sonnet) : garde `/diphonie-des-steppes/`,
   `/polyphonies-georgiennes/`, `/arabesques-persanes/`,
   `/musiques-et-chants-du-bassin-mediterraneen/`, etc. ; écarte `/contact/`,
   `/actualites/`, `/mentions-legales/`…
3. Fetch des ~8 pages d'événement → ~8 `CollectedItem` web riches (lieu/heure/prix/artistes).
4. Extraction classique downstream → événements individuels avec lieu.

## 6. Erreurs & robustesse
- Pas de clé API + scope domaine → fallback index (pas de fetch massif).
- Pré-filtre échoue (exception) → fallback index (ne pas fetcher tout le domaine).
- Pré-filtre renvoie 0 en scope domaine → fallback index (la page liste souvent
  les events en ligne).
- Une page d'événement en échec (404, timeout) → loggée, les autres continuent
  (comportement actuel).

## 7. Tests (`tests/test_web.py`)
- `_extract_subpages` scope `"domain"` : sur un HTML avec liens racine + menu +
  ancres + mailto + externe, retourne les liens même-hôte dédupliqués, hors
  index/ancres/mailto/externe.
- `_extract_subpages` scope `"subpath"` : comportement actuel inchangé
  (test de non-régression).
- `_filter_event_urls` avec `month=None` : Claude mocké renvoie un sous-ensemble ;
  on vérifie que seules les URLs retournées sont gardées.
- `collect` branche follow + scope domaine : Claude (prefilter + fetch) mocké —
  pages d'événement retenues → items ; menu écarté.
- Fallback index : prefilter mocké renvoie `[]` (ou pas de clé) → un seul item =
  la page d'index.

## 8. Décisions par défaut (révisables au plan)
1. **Exclusions scope domaine** : on exclut ancres, mailto/tel/javascript,
   schémas non-http, l'URL d'agenda elle-même, et on normalise en enlevant le
   fragment. On ne tente PAS de filtre heuristique « menu » (nom de slug) — c'est
   le rôle du pré-filtre Claude.
2. **`_filter_event_urls`** remplace `_filter_urls_by_month` (un seul point
   d'appel : `web.collect`). Pas d'alias conservé sauf si un autre appelant
   apparaît.
3. **Même-hôte** = même `netloc` que l'URL d'agenda (pas de sous-domaines
   différents).

## 9. Hors périmètre
- Exposer `follow_scope` ou `event_link_pattern` dans l'UI (la case unique suffit).
- Suivre des liens cross-domaine (billetterie externe, HelloAsso…).
- Récursion multi-niveaux (on ne suit qu'un niveau depuis l'agenda, comme aujourd'hui).
