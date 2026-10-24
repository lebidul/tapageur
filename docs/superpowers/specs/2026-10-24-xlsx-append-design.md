# Mode « append » pour la sortie xlsx — Design

**Date :** 2026-10-24
**Statut :** validé (brainstorming), prêt pour plan d'implémentation
**Auteur :** Thibault Uzu + Claude

## 1. Objectif

Permettre, en option, d'**ajouter les résultats d'une passe d'extraction au fichier
de sortie xlsx existant** au lieu de le recréer — pour accumuler les événements
d'un mois au fil de plusieurs passes, **sans perdre les corrections faites à la
main dans Excel**.

## 2. Décisions de cadrage (brainstorming)

| Sujet | Décision |
|-------|----------|
| **Modèle** | **Append simple** : on ajoute les nouvelles lignes à la fin de la feuille `lebiduleur`, sans toucher aux lignes déjà présentes → les corrections manuelles sont préservées. Pas de dédup inter-passes (relancer la même source peut dupliquer). |
| **Formats** | **xlsx uniquement.** csv/json continuent de se recréer à chaque passe (l'option append ne les concerne pas). |
| **Alignement ACT** | Blocs ACT cibles = `max(blocs existants, blocs de la nouvelle passe)`. Si la nouvelle passe en a plus → on élargit les en-têtes (anciennes lignes paddées de cellules vides). Lignes plus courtes paddées. **Aucune perte de données.** |
| **UI** | Une case **« Ajouter au fichier existant »** dans la section Sortie. |

## 3. Comportement

`export_xlsx(events, out_path, template_path=TEMPLATE_PATH, append=False)` :

- **`append=False`** (défaut) OU **`append=True` mais `out_path` n'existe pas** :
  comportement actuel — on part d'une **copie du template**, on écrit les events
  à partir de la ligne 2. (Ainsi, la toute première passe avec append coché
  fonctionne comme une création.)
- **`append=True` et `out_path` existe** :
  1. Ouvrir le **fichier existant** (`out_path`), pas le template.
  2. Exiger une feuille `lebiduleur` ; sinon → `ValueError` explicite (on n'écrase
     pas un fichier étranger).
  3. Calculer les **blocs ACT existants** depuis la ligne d'en-têtes
     (`(max_column - 10) // 4`, au moins 1).
  4. `n_acts = max(blocs_existants, max(len(ev.acts) for ev in events))`.
  5. Si `n_acts > blocs_existants` : écrire les en-têtes des blocs supplémentaires
     sur la ligne 1 (« GENRE k / NOM SPECTACLE k / ARTISTE k / STYLE k »).
  6. Écrire chaque nouvel event à partir de `ws.max_row + 1`, via
     `validate.event_to_row(ev, n_acts=n_acts)` (padding automatique).
  7. Les feuilles de référence (`communes`, `salles_lieux`, `date`) et les lignes
     existantes ne sont pas touchées.
  8. Sauver dans `out_path` (sur place).

## 4. Intégration

- `service.RunRequest` gagne un champ `append: bool`.
- `service._export` : passe `append` à l'export xlsx uniquement. csv/json inchangés.
  Si `append` est vrai mais `"xlsx"` n'est pas dans `formats` → l'export xlsx n'a
  pas lieu, donc l'option est sans effet (une alerte « append ignoré : xlsx non
  sélectionné » peut être ajoutée au résumé).
- `app.Api.run_extraction` : lit `payload["append"]` → `RunRequest(append=...)`.
- `index.html` : case **« Ajouter au fichier existant »** dans la section Sortie ;
  `append` ajouté au payload envoyé à `run_extraction` (toutes les clés
  existantes conservées).

## 5. Cas limites
- Fichier existant sans feuille `lebiduleur` → `ValueError` remontée à l'UI comme
  erreur claire (le run n'écrase rien).
- Multi-mois / « ne pas filtrer » : chaque fichier `tapage_<label>.xlsx` est
  appendé indépendamment (label = mois, ou « tous »).
- Append coché, fichier absent → création normale (pas d'erreur).
- `n_acts` plus petit que l'existant → on garde la largeur existante, nouvelles
  lignes paddées (jamais de rétrécissement/troncature des blocs existants).

## 6. Tests (`tests/gui/test_export_xlsx.py`)
- **Append préserve + ajoute** : créer un xlsx avec 1 event (mode normal), puis
  `export_xlsx([autre_event], path, append=True)` → le fichier a 2 lignes de
  données, la 1re inchangée.
- **Élargissement** : fichier existant à 1 bloc ACT, append d'un event à 3 actes
  → en-têtes « GENRE 3 » présents, 1re ligne paddée (cellules vides), nouvelle
  ligne remplie.
- **Erreur si pas de `lebiduleur`** : un xlsx sans cette feuille + `append=True`
  → `ValueError`.
- **Append sur fichier absent** = création : `append=True` vers un chemin
  inexistant → fichier créé avec l'event (comme le mode normal).
- `service` : `RunRequest(append=True)` propage l'append à l'export xlsx (via un
  test qui vérifie que le 2e run ajoute une ligne).

## 7. Hors périmètre
- Append pour csv / json (toujours recréés).
- Dédup inter-passes (incompatible avec la préservation des corrections manuelles).
- Détection de doublons / avertissement sur réexécution de la même source
  (éventuel suivi ultérieur).
