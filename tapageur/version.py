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
- v4 : SYSTEM_PROMPT dit désormais à Claude d'ignorer date_label (recalculé
       Python en « Jour N » depuis date_iso). Bump nécessaire : le changement
       de prompt n'avait pas été versionné et les items ré-extraits depuis
       renvoyaient date_label=null, rejetés par l'ancien schéma strict. Avec
       le schéma tolérant (_EventDraft.date_label optionnel), re-extraire
       proprement et purger les caches empoisonnés.
- v5 : règle ANNÉE ajoutée aux deux prompts. Sans elle, Claude devinait une
       année passée qui fait coïncider le jour de semaine (ex. "mardi 17
       novembre" → 2020) en ignorant le « Mois cible », et le filtre
       startswith(mois) jetait tout. Désormais : année = celle du mois cible
       quand le contenu ne l'indique pas.
- v6 : règle 2 assouplie — un event sans horaire n'est plus supprimé, il est
       gardé avec times=["?"] (le tapeur complète). Fréquent sur les
       programmes de festivals saisis en events normaux.
- v7 : règle ANNÉE élargie pour couvrir le mode « tous les mois » (année de
       référence passée dans le user message au lieu d'un mois cible).
- v8 : règle DATE — ne JAMAIS forcer le mois d'un event sur le mois cible
       (ex. « 16 octobre » restait, à tort, 2026-11-16 au lieu de 2026-10-16) ;
       + distinction genre (enum sv/c/expo/dj/autre) vs style (texte libre) —
       un style (« dj », « techno »…) ne doit plus atterrir dans genre.
- v9 : un acte DJ est un concert (genre="c", « DJ » en style) — "dj" retiré des
       genres proposés + coercition déterministe dans _normalize_one (genre
       "dj" → "c").
- v10 : exclure les EXPOSITIONS (genre expo), même datées — règle 7 + drop
       déterministe dans _normalize_one (le fanzine ne liste pas les expos).
- v11 : règle d'ANCRAGE anti-confabulation (règle A) — n'extraire que des
       events littéralement présents dans le texte, events=[] sur une page
       sans programme concret, interdiction d'inventer festival/lieu/artiste
       depuis les connaissances du modèle. Corrige un cas observé sur
       cpfi-lemans.com/festival/ (page du Festival CARAVANES / Musiques du
       Monde) d'où Sonnet avait sorti un « Festival International du Film de
       La Ferté-Bernard » totalement absent du contenu. + règle 7 durcie
       (cinéma/festival de film exclus explicitement). Garde Python
       complémentaire : item sans image au texte quasi vide → pas d'appel
       modèle (cf. _MIN_TEXT_CHARS dans normalize.py).
"""

PROMPT_VERSION = "v11"
