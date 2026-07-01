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
- v3 : source_ref injectée dans le user message (ligne "Source : ...")
       + FESTIVAL_SYSTEM_PROMPT durci pour rendre l'URL obligatoire dans
       acts[0].title quand la source est une page web. Corrige un cas
       observé sur atoutboutdchamp (title=null malgré URL disponible).
"""

PROMPT_VERSION = "v3"
