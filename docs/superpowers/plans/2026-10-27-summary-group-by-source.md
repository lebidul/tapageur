# Plan — TODO #10 (reste) : grouper les events par source dans le Résumé

**État amont :** le log live préfixe déjà la source (web.py, mergé). Reste la
partie **Résumé** de l'UI : grouper / titrer les events extraits par source.

## Objectif

Dans la section Résumé, chaque bloc d'events d'un mois est sous-groupé par
**source** : un en-tête lisible par source, puis ses events indentés. L'ordre
des sources suit leur première apparition. Aucune régression sur le reste du
Résumé (compteurs, fichiers, alertes).

## Décisions (questions ouvertes TODO #10 tranchées)

- **Granularité** : un en-tête par source suffit (la demande). La source reste
  aussi sur chaque ligne de l'xlsx (col SOURCE) — inchangé.
- **Libellé de l'en-tête** : réutiliser `validate._source_ref_display(kind, ref)`
  (URL / nom de fichier / « texte #N ») plutôt que de dupliquer la logique en JS.
  → calculé côté Python dans `_events_summary`, exposé en `source_label`.
- **Clé de groupement** : le `source_label` affiché (events d'une même source
  partagent kind+ref donc le même label). Fallback `source` puis
  « (source inconnue) » si vide.
- **Sécurité** : rendu DOM/textContent uniquement (comme l'existant), jamais
  d'innerHTML.

## Étapes (TDD)

1. **Python — `tapageur/gui/app.py` `_events_summary`** : ajouter
   `source_label` (= `_source_ref_display(ev.source_kind, ev.source_ref)`),
   conserver `source`. Test pytest d'abord (`tests/gui/test_app.py`) :
   le dict porte `source_label` lisible pour web / pdf(#page) / text.
2. **JS — `index.html` `renderSummary`** : au sein de chaque résultat de mois,
   grouper `r.events` par `source_label` en préservant l'ordre de première
   apparition ; rendre un `div.source-head` par source puis ses events indentés.
3. **CSS — `index.html`** : style `#summary .source-head` (discret, léger retrait).

## Vérification

- `pytest` complet (pas de régression ; nouveau test vert).
- Relecture JS : pur DOM, pas d'innerHTML, ordre stable, fallback source vide.
- Pas de bump `PROMPT_VERSION` (aucun prompt modèle touché ; cf. mémoire
  `prompt_version_bump` — rien de mis en cache ici).
