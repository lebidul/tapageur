# Design : découverte d'URL — events en paramètre de requête (connecteur web)

Date : 2026-10-27
Statut : validé (feature dispatchée, spec complète)

## Problème

Deux sites dont les events ne sont pas découverts par `WebConnector`.

### Cas 1 — events identifiés par un PARAMÈTRE DE REQUÊTE (la-ferte-bernard)

`https://www.la-ferte-bernard.fr/culture-animations/centre-culturel/` liste **25 events**
de la forme `https://www.la-ferte-bernard.fr/?saison_culturelle=<slug>` : **même chemin**
(la racine `/`), distingués UNIQUEMENT par la query `?saison_culturelle=…` (custom post
type WordPress sans permaliens jolis). Rendu côté serveur (vérifié au curl le 2026-10-27).

**Cause** : `_extract_subpages` canonise sur `scheme://host/path` et **strippe la query**,
puis déduplique sur le chemin. Les 25 liens s'effondrent tous sur
`https://www.la-ferte-bernard.fr/` → 24 events perdus. Vérifié : `scope="domain"` renvoie
75 candidats, **0** contenant `saison_culturelle`. (NB : chemin `/` ≠ chemin agenda → ces
events ne sortent qu'en `follow_scope: "domain"`, jamais en `subpath`.)

### Cas 2 — La Perche Comedy Club : billetterie EXTERNE (pas de la découverte d'URL)

`https://www.laperchecomedyclub.fr/billetterie/` (site Jimdo, rendu côté serveur). La page
d'agenda **porte elle-même** les 6 events en clair dans son texte (nom, date, lieu : « TOM
BALDETTI – TOME 1 / 06 NOVEMBRE 2026 / LES SAULNIERES - LE MANS », etc.). Les seuls liens
« détail » pointent vers une **billetterie tierce** (`my.weezevent.com/…`,
`fnacspectacles.com/…`) : **cross-domaine**, donc légitimement non suivis par
`_extract_subpages` (sécurité same-host). Il n'y a **aucune page détail same-host** à
découvrir. Ce n'est donc **pas** un problème de découverte d'URL (query-param ou autre) :
c'est le motif « billetterie externe » que la consigne demande de **documenter**.

Comportement correct déjà en place : sans page détail same-host exploitable, `collect`
retombe sur l'index (`repli sur l'index` en scope subpath, `fallback index` en scope
domaine quand le pré-filtre ne retient rien) → le texte de `/billetterie/`, auto-suffisant,
est normalisé et les 6 events en sont extraits. Un test de régression verrouille ce
diagnostic (0 lien détail same-host ; les events sont dans le texte de l'index).

## Décision de design (le vrai choix) : blocklist, pas allowlist

Pour distinguer les events query-param SANS exploser le nombre de candidats, deux approches :

- **Allowlist** de clés « signifiantes » (`saison_culturelle`, `event`, `p`, `id`…) :
  rejetée. Fragile, site-spécifique, à maintenir à la main — contraire au principe du
  projet (déléguer l'extraction à Claude, éviter les sélecteurs par site).
- **Blocklist** : on canonise en **préservant la query**, après avoir retiré (1) les
  paramètres de **tracking** et (2) les paramètres de **pagination**. Tout le reste est
  « signifiant » par défaut. Générique ; le bruit résiduel est trié en aval par le
  pré-filtre mois (`_filter_event_urls`). **Retenu.**

Le blow-up est borné : les paramètres de tracking (source n°1 de variantes : `?utm_*`,
`?fbclid`…) sont strippés → les liens qui ne différaient que par le tracking continuent de
fusionner (comportement actuel préservé). Un lien n'est de toute façon compté qu'une fois
(set de sortie).

### Paramètres strippés

| Famille | Clés | Raison |
|---|---|---|
| Tracking | `utm_*` (préfixe), `fbclid`, `gclid`, `gclsrc`, `dclid`, `gbraid`, `wbraid`, `gad*` (préfixe), `msclkid`, `mc_*` (préfixe), `_gl`, `igshid`, `yclid`, `ref`, `ref_src`, `spm` | bruit, jamais distinctif d'un event |
| Pagination | clé `page`, `paged`, ou préfixe `e-page` | déjà gérés par la pagination (`_page_param` / `_extract_pagination_urls`) ; ne pas re-découvrir comme events |

Tout autre paramètre est **préservé**. La query canonique est **triée** (clés+valeurs) pour
une déduplication stable (`?a=1&b=2` == `?b=2&a=1`).

## Architecture

Un helper pur dans `tapageur/connectors/web.py`, réutilisé partout où une URL est canonisée.

### `_clean_query(query: str) -> str`
Filtre une query string : retire tracking + pagination, garde le reste, trie, ré-encode.
Retourne `""` si plus rien (→ canonical = chemin nu, comme aujourd'hui).

### `_canonical_url(base_url, href) -> str` (helper existant, mis à jour)
Devient `scheme://host/path[?clean_query]`. Source unique de canonisation : utilisé par
`_extract_card_snippets` (match ancre↔URL) ET par `_extract_subpages` (sorties), pour
qu'ils produisent EXACTEMENT la même forme (sinon les cartes des events query-param
seraient vides).

### `_extract_subpages(…)` (mis à jour)
Les deux modes (heuristique défaut et `pattern`) construisent désormais le canonical via
`_canonical_url` (donc avec `_clean_query`) au lieu de `f"{scheme}://{host}{path}"`. Les
filtres de scope (`path == base_path`, `startswith(base_path + "/")`, `_TAXONOMY`) restent
sur le **chemin** (inchangés). Un lien distingué uniquement par un param de pagination
retombe sur son chemin nu → s'il s'agit du chemin agenda, il reste exclu par
`path == base_path` ; sinon il devient le candidat « chemin nu », pas N events fantômes.

**Non touché** : `_extract_pagination_urls` et `_page_key` gardent leur propre canonisation
(query brute préservée) — c'est leur rôle. Aucune régression pagination.

## Non-régression (vérifiée par tests existants)
- `test_extract_subpages_domain_scope_dedups_fragment_and_query` : `/a/`, `/a/#frag`,
  `/a/?utm=1` fusionnent toujours en un seul `…/a/` (utm strippé, fragment ignoré).
- Tests `pattern` (msj.world) : URLs sans query → canonical = chemin, inchangé.
- Pagination (#15), cartes/pré-filtre (#12), scope subpath/domaine : inchangés.

## Tests (TDD)
Unitaires `_clean_query` : strippe `utm_*`/`fbclid`/`ref` ; strippe `page`/`paged`/`e-page*` ;
garde `saison_culturelle` ; trie ; vide → `""`.

Unitaires `_extract_subpages` (scope domaine) :
- 25 `?saison_culturelle=` ressortent **distincts** (fixture ferte réelle).
- `?utm_source=x` sur un même chemin → fusionne (pas de nouveau candidat).
- `?page=2` / `?e-page-x=2` ne sont pas pris pour des events.
- Cartes : l'ancre d'un event query-param retrouve bien sa carte (même canonical).

Cas 2 (fixture perche réelle) : `_extract_subpages` → **0** lien détail same-host (tout en
weezevent/fnac, cross-domaine) ; le texte de l'index contient les 6 events datés
(→ le repli-index les récupère). Documente que c'est de la billetterie externe.

## YAGNI (écarté)
- Pas d'allowlist de params signifiants (voir décision).
- Pas de suivi des billetteries externes (Weezevent/Fnac) : hors scope découverte d'URL.
- Pas de cap de candidats dédié : le set de sortie + le pré-filtre mois suffisent.
