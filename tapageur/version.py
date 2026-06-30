"""
Constantes versionnées qui invalident certains caches au changement.

Importée par cache.py et par normalize.py — module tampon pour éviter les
imports circulaires entre les 2.

PROMPT_VERSION : bump manuellement à chaque modification *de fond* de
SYSTEM_PROMPT ou FESTIVAL_SYSTEM_PROMPT dans normalize.py. La version est
incluse dans la cache_key item-level → un bump invalide automatiquement
toutes les entrées cache au prochain `tapageur normalize`, qui re-call
Claude avec le nouveau prompt.

Bumps notables :
- v1 (initial) : prompt avec règles 1-8.
- v2 : ajout règle 9 — ignorer les dates dans les légendes de photos
       (anti-faux-positif observé sur LeMans_Guide-ete-2026.pdf).
"""

PROMPT_VERSION = "v2"
