# Mode batch

L'API Batch d'Anthropic permet de traiter une liste de requêtes Claude **en différé** avec une réduction de **50%** sur l'input et l'output. En contrepartie, Anthropic se réserve jusqu'à **24h** pour traiter le batch (en pratique : souvent quelques minutes à quelques heures).

## Quand l'utiliser

| Cas | Mode |
|---|---|
| Run mensuel anticipé (J-3 avant publication) | ✅ **Batch** |
| Run de nuit / week-end | ✅ **Batch** |
| Tu publies dans 2h | ❌ Sync |
| Tu débogues ou itères sur le prompt | ❌ Sync |
| Tu veux feedback immédiat (visualiser ce qui sort) | ❌ Sync |

## L'analogie de l'imprimeur

L'API Batch fonctionne **en deux temps**, comme un imprimeur :

1. **Submit** = déposer une liste de fichiers à imprimer. Tu reçois un **ticket** (un `batch_id`).
2. **Retrieve** = revenir avec le ticket pour récupérer tes impressions, plus tard.

Sans la 2e étape, tes réponses restent stockées chez Anthropic, jamais récupérées.

## Le workflow concret

### Sync (sans batch)
```bash
tapageur normalize --month 2026-06
# → tout en 1 fois, le programme attend les réponses Claude (qq sec à qq min)
# → cache/2026-06/normalized.json prêt à l'issue
```

### Batch (en 2 commandes)
```bash
# T0 — Soumettre
tapageur normalize --month 2026-06 --batch
# → envoie toutes les requêtes d'un coup à l'API Batch
# → enregistre le batch_id dans cache/2026-06/batch_state.json
# → exit en 5 secondes, Anthropic continue en background

# … attendre jusqu'à 24h …

# T0 + qq h à 24h — Récupérer
tapageur retrieve --month 2026-06
# → lit batch_state.json, demande à Anthropic "tu as fini ?"
# → si oui, télécharge les résultats et finalise normalized.json
# → si non, message clair "réessayer plus tard"
```

## Pourquoi 2 commandes et pas 1 ?

Si `normalize --batch` faisait submit + attendre + retrieve dans la même commande, le programme **resterait bloqué pendant des heures**. Tu ne pourrais rien faire dans ton terminal, et un crash réseau ou un Ctrl+C t'obligerait à recommencer.

En séparant :
- **Submit** prend 5 secondes, tu peux fermer ton PC.
- **Retrieve** prend 30 secondes le lendemain.

L'état est persisté sur disque (`cache/<month>/batch_state.json`), donc redémarrer le PC entre les deux étapes n'est pas un problème.

## Cas de figure

### Tu lances `retrieve` avant que le batch soit fini
```
Error: Batch msgbatch_xyz123 pas encore terminé (statut: in_progress).
Réessayer plus tard.
```
Rien d'écrit, rien de cassé. Reviens dans 1h.

### Tu lances `retrieve` après succès, puis re-lances `retrieve`
```bash
$ tapageur retrieve --month 2026-06       # 1ère fois — finalise
✓ 47 events normalisés → cache/2026-06/normalized.json

$ tapageur retrieve --month 2026-06       # 2e fois
Error: Aucun batch en attente pour 2026-06.
```
Le 1er retrieve supprime `batch_state.json` après succès. Le 2e tombe sur "rien à faire".

### Tu lances `retrieve` sans avoir submit
```
Error: Aucun batch en attente pour 2026-06.
Lance `tapageur normalize --month 2026-06 --batch` d'abord.
```

### Tu re-lances `normalize --batch` alors qu'un batch est déjà en cours
```
Error: Un batch existe déjà pour 2026-06 : msgbatch_xyz123.
Lance `tapageur retrieve --month 2026-06` ou supprime cache/2026-06/batch_state.json
pour re-soumettre.
```
Garde-fou anti-doublon. Pour annuler le batch en cours et recommencer : supprime `batch_state.json` à la main.

### Tous les items sont déjà en cache au moment du submit
```
[dim]cache: 50 hit, 0 miss à soumettre[/dim]
✓ tous les items sont déjà cachés, rien à soumettre
```
Aucun appel à l'API Batch (qui rejette les batches vides). Le `retrieve` suivant lira directement le cache et finalisera.

## L'interaction avec le cache item-level

Le cache (cache/normalize/<hash>.json, voir [workflow.md](workflow.md)) est **prioritaire** sur le batch :

- Au moment du submit, les items déjà cachés ne sont **pas** envoyés au batch — économie de 100% sur ces items, pas juste 50%.
- Le batch contient uniquement les items réellement nouveaux (cache miss).
- Au retrieve, chaque résultat reçu est aussi inséré dans le cache item-level — re-runs futurs gratuits.
- `retrieve` est **idempotent** : si tu le relances avant que le state soit nettoyé, il relit le cache au lieu de re-toucher l'API.

## Économies estimées

| Item type             | Sync          | Batch         | Économie  |
|-----------------------|---------------|---------------|-----------|
| 1 page web (Sonnet)   | ~$0.030       | ~$0.015       | $0.015    |
| 1 mail (Sonnet)       | ~$0.012       | ~$0.006       | $0.006    |
| 1 PDF saison (Opus)   | ~$0.450       | ~$0.230       | $0.220    |
| 1 flyer image (Opus)  | ~$0.230       | ~$0.115       | $0.115    |
| **Run mensuel typique** | **~$5**     | **~$2.50**    | **~$2.50** |

Sur 12 mois : ~$30/an d'économie. À combiner avec le cache item-level (qui rend les re-runs gratuits) pour le maximum.

## État persisté : `batch_state.json`

```json
{
  "batch_id": "msgbatch_01abc...",
  "submitted_at": "2026-06-03T14:23:11Z",
  "month": "2026-06",
  "items": [
    {
      "custom_id": "abc123def456...",
      "source_ref": "https://siteX.fr/event/foo",
      "source_kind": "web"
    },
    ...
  ]
}
```

Le `custom_id` est calculé via `cache_key(item, month)` — ça permet :
- de mapper chaque résultat batch à l'item d'origine au moment du retrieve
- de cacher les résultats directement dans `cache/normalize/<custom_id>.json`

Le fichier est **écrit atomiquement** (tmp + rename) pour éviter les corruptions en cas de Ctrl+C pendant le submit.

## Récap simple

- **Sans `--batch`** : `normalize` fait tout en 1 fois. Pas de `retrieve`.
- **Avec `--batch`** : c'est en 2 temps. `normalize --batch` = "envoie le travail", `retrieve` = "récupère plus tard".

`retrieve` = **le finalize du mode batch**. Sans `--batch`, il n'est jamais nécessaire.
