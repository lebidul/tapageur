"""
Import des venues canoniques + alias dans config/mappings.yaml.

Lit deux fichiers :
- cache/_import/lieu_ref.txt   : 1 nom canonique par ligne
- cache/_import/lieu_alias.tsv : `variant<TAB>canonical` par ligne (1 header)

Produit le YAML structuré dans config/mappings.yaml en remplaçant la section
`venues`. Les autres sections (`artists`, `festivals`, `genres`) sont
préservées telles quelles.

Le script peut être relancé à tout moment pour ré-importer une liste mise à
jour (les alias absents disparaissent, les nouveaux apparaissent).

Usage :
    python scripts/import_mappings.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml


REF_PATH = Path("cache/_import/lieu_ref.txt")
ALIAS_PATH = Path("cache/_import/lieu_alias.tsv")
MAPPINGS_PATH = Path("config/mappings.yaml")


def load_ref(path: Path) -> set[str]:
    """Lit la liste des canoniques. Dédup."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return {ln.strip() for ln in lines if ln.strip()}


def load_alias(path: Path) -> list[tuple[str, str]]:
    """Lit le TSV alias→canonical. Skip header et lignes mal formées."""
    pairs: list[tuple[str, str]] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        if "\t" not in raw:
            print(f"  [warn] ligne {i} sans tab, skip: {raw[:60]!r}")
            continue
        parts = raw.split("\t")
        if len(parts) != 2:
            print(f"  [warn] ligne {i} a {len(parts)} colonnes, skip")
            continue
        variant, canonical = parts[0].strip(), parts[1].strip()
        if variant == "variante" and canonical == "lieu_nom":
            continue  # header
        if not variant or not canonical:
            continue
        pairs.append((variant, canonical))
    return pairs


def _resolve_chain(target: str, alias_map: dict[str, str], max_hops: int = 10) -> str:
    """Suit la chaîne A→B→C jusqu'à un point fixe ou un cycle.

    Exemple : si on a {26 rue Gambetta...: Le Français, Le Français: Cinéma le Français},
    alors _resolve_chain('Le Français') retourne 'Cinéma le Français'.
    """
    seen = {target}
    current = target
    for _ in range(max_hops):
        if current not in alias_map:
            return current
        next_ = alias_map[current]
        if next_ == current or next_ in seen:
            return current  # point fixe ou cycle détecté
        seen.add(next_)
        current = next_
    return current


def build_venues(
    canonicals: set[str],
    alias_pairs: list[tuple[str, str]],
) -> tuple[dict[str, list[str]], list[str], list[tuple[str, str, str]]]:
    """Construit {canonical: [aliases]} trié, avec résolution des chaînes.

    Si A→B et B→C : tous les alias de B (et A lui-même) deviennent alias de C.
    Permet de garder une cohérence sans demander à l'humain de tout aplatir.

    Retourne :
    - venues : dict trié canonical → list[aliases]
    - extras : canoniques référencés mais absents de lieu_ref
    - resolved_chains : liste des chaînes résolues (pour log)
    """
    # alias_map direct : variant → canonical (le dernier gagne en cas de doublon)
    alias_map: dict[str, str] = {}
    for variant, canonical in alias_pairs:
        if variant != canonical:
            alias_map[variant] = canonical

    # Résolution transitive : chaque alias pointe vers la cible finale.
    resolved_chains: list[tuple[str, str, str]] = []
    final_alias_map: dict[str, str] = {}
    for variant, direct in alias_map.items():
        final = _resolve_chain(direct, alias_map)
        if final != direct:
            resolved_chains.append((variant, direct, final))
        final_alias_map[variant] = final

    # Construction des venues.
    venues: dict[str, list[str]] = {c: [] for c in canonicals}
    extras: set[str] = set()

    for variant, canonical in final_alias_map.items():
        if canonical not in venues:
            extras.add(canonical)
            venues[canonical] = []
        if variant not in venues[canonical]:
            venues[canonical].append(variant)

    # Tri alphabétique des canoniques + de leurs alias.
    sorted_venues = {}
    for c in sorted(venues, key=lambda s: s.lower()):
        sorted_venues[c] = sorted(venues[c], key=lambda s: s.lower())

    return sorted_venues, sorted(extras, key=str.lower), resolved_chains


def write_mappings(venues: dict[str, list[str]]) -> None:
    """Charge mappings.yaml, remplace venues, préserve le reste, ré-écrit."""
    if MAPPINGS_PATH.exists():
        existing = yaml.safe_load(MAPPINGS_PATH.read_text(encoding="utf-8")) or {}
    else:
        existing = {}

    new_data = {
        "venues": venues,
        "artists": existing.get("artists", {}),
        "festivals": existing.get("festivals", {}),
        "genres": existing.get("genres", {}),
    }

    header = (
        "# Mappings canoniques pour le dédoublonnage.\n"
        "# - venues : généré par scripts/import_mappings.py depuis cache/_import/.\n"
        "# - artists / festivals / genres : édités manuellement.\n"
        "# Format : \"forme_canonique\": [variantes...]\n\n"
    )

    body = yaml.dump(
        new_data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=120,
    )

    MAPPINGS_PATH.write_text(header + body, encoding="utf-8")


def main() -> int:
    if not REF_PATH.exists():
        print(f"[error] {REF_PATH} introuvable", file=sys.stderr)
        return 1
    if not ALIAS_PATH.exists():
        print(f"[error] {ALIAS_PATH} introuvable", file=sys.stderr)
        return 1

    print(f"=== Import venues from {REF_PATH} + {ALIAS_PATH} ===\n")

    canonicals = load_ref(REF_PATH)
    print(f"lieu_ref     : {len(canonicals)} canoniques uniques")

    alias_pairs = load_alias(ALIAS_PATH)
    print(f"lieu_alias   : {len(alias_pairs)} paires variant→canonical")

    venues, extras, chains = build_venues(canonicals, alias_pairs)
    n_with_aliases = sum(1 for v in venues.values() if v)
    n_aliases_total = sum(len(v) for v in venues.values())

    print(f"\nrésultat :")
    print(f"  - {len(venues)} canoniques au total")
    print(f"  - {n_with_aliases} ont au moins 1 alias")
    print(f"  - {n_aliases_total} alias mappés")

    if chains:
        print(f"\n[info] {len(chains)} chaînes résolues transitivement (A→B→C devient A→C) :")
        for variant, intermediate, final in chains[:10]:
            print(f"    {variant!r:<40} → {intermediate!r:<28} → {final!r}")
        if len(chains) > 10:
            print(f"    ... et {len(chains) - 10} autres")

    if extras:
        print(f"\n[info] {len(extras)} canoniques référencés par alias mais absents de lieu_ref :")
        for c in extras[:20]:
            print(f"    - {c}")
        if len(extras) > 20:
            print(f"    ... et {len(extras) - 20} autres")
        print("  (intégrés quand même ; à vérifier manuellement si typos)")

    write_mappings(venues)
    print(f"\n[green] écrit dans {MAPPINGS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
