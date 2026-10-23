"""
Test d'extraction ad-hoc sur sources variées (web, PDF, image).

But : valider la qualité d'extraction Claude sur un échantillon hétérogène
sans toucher la config production ni écraser le cache mensuel courant.

Usage :
    python scripts/test_extraction.py

Sources hardcodées dans WEB_SOURCES / PDF_SOURCES / IMAGE_SOURCE plus bas —
adapter au besoin.

Notes :
- Bénéficie du cache item-level (cache/normalize/<hash>.json) : re-run gratuit
  tant que les pages web ne changent pas.
- Mode sync (pas de batch) : feedback immédiat dans la console.
- Sortie : cache/test_extraction/<month>.json + résumé console.
- Coût estimé au 1er run : ~$3-5 (Sonnet sur web, Opus sur PDF/image).
"""
from __future__ import annotations

import base64
import sys
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Charge .env AVANT d'importer les modules qui lisent ANTHROPIC_API_KEY.
load_dotenv(override=True)

from tapageur.connectors.web import _fetch  # noqa: E402
from tapageur.normalize import normalize_items  # noqa: E402
from tapageur.schema import CollectedItem  # noqa: E402


WEB_SOURCES: list[tuple[str, str, bool]] = [
    # (label, url, needs_browser)
    ("bistrobroccafe", "https://bistrobroccafe.e-monsite.com/", False),
    ("musiquesmagiques", "https://www.musiquesmagiques.fr/Agenda/index.php", False),
    ("lafonderie", "https://www.lafonderie.fr/les-ouvertures-publiques/", False),
]

PDF_SOURCES: list[tuple[str, Path]] = [
    ("acthalia_25_26", Path("season_pdfs/Programme Acthalia saison 2025-2026.pdf")),
    ("projet_24_27", Path("season_pdfs/projet_24-27opt.pdf")),
]

IMAGE_SOURCES: list[tuple[str, Path]] = [
    ("flyer_687038320", Path("season_pdfs/687038320_1377985241030382_3802993201109553842_n.jpg")),
    ("flyer_681511786", Path("season_pdfs/681511786_1589379639854676_2415967332257482436_n.jpg")),
]

MONTHS = ["2026-05", "2026-06"]


def fetch_web(label: str, url: str, needs_browser: bool = False) -> CollectedItem:
    """Fetch + parse HTML → CollectedItem (raw text dump, pas de follow links)."""
    print(f"  [web] {label} ← {url}")
    try:
        html = _fetch(url, needs_browser=needs_browser)
    except Exception as e:
        if not needs_browser:
            # Retry avec navigateur headless (anti-bot, JS, etc.)
            print(f"    requests failed ({e}), retry avec Playwright")
            html = _fetch(url, needs_browser=True)
        else:
            raise

    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    return CollectedItem(
        source_kind="web",
        source_ref=url,
        fetched_at=datetime.utcnow().isoformat() + "Z",
        raw_text=text,
        raw_metadata={"label": label, "site": label},
    )


def fetch_pdf(label: str, path: Path) -> CollectedItem:
    """pdfplumber → text dump → CollectedItem."""
    import pdfplumber  # lazy

    print(f"  [pdf] {label} ← {path}")
    with pdfplumber.open(path) as pdf:
        n_pages = len(pdf.pages)
        text = "\n\n".join((p.extract_text() or "") for p in pdf.pages)
    return CollectedItem(
        source_kind="pdf",
        source_ref=str(path),
        fetched_at=datetime.utcnow().isoformat() + "Z",
        raw_text=text,
        raw_metadata={"label": label, "n_pages": n_pages},
    )


def fetch_image(label: str, path: Path) -> CollectedItem:
    """Image → base64 → CollectedItem (vision Claude uniquement, pas d'OCR)."""
    print(f"  [img] {label} ← {path}")
    img_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/jpeg")
    return CollectedItem(
        source_kind="image",
        source_ref=str(path),
        fetched_at=datetime.utcnow().isoformat() + "Z",
        raw_text="",  # OCR non câblé dans le connecteur actuel
        raw_image_b64=img_b64,
        raw_metadata={"label": label, "mime": mime},
    )


def collect_all() -> list[CollectedItem]:
    items: list[CollectedItem] = []

    print("=== Web ===")
    for label, url, needs_browser in WEB_SOURCES:
        try:
            items.append(fetch_web(label, url, needs_browser))
        except Exception as e:
            print(f"  [err] {label}: {e}")

    print("\n=== PDF ===")
    for label, path in PDF_SOURCES:
        if not path.exists():
            print(f"  [skip] {path} not found")
            continue
        try:
            items.append(fetch_pdf(label, path))
        except Exception as e:
            print(f"  [err] {label}: {e}")

    print("\n=== Image ===")
    for label, path in IMAGE_SOURCES:
        if not path.exists():
            print(f"  [skip] {path} not found")
            continue
        try:
            items.append(fetch_image(label, path))
        except Exception as e:
            print(f"  [err] {label}: {e}")

    return items


def short_label(item: CollectedItem) -> str:
    lbl = item.raw_metadata.get("label", "?")
    return f"{item.source_kind}:{lbl}"


def print_event(e) -> None:
    """Pretty-print compact d'un Event."""
    acts = " / ".join(
        f"{a.performer}" + (f" ({a.style})" if a.style else "")
        for a in e.acts
    )
    times = " & ".join(e.times)
    fest = f"  [{e.festival}]" if e.festival else ""
    print(f"    {e.date_iso} {times} | {e.venue}, {e.city} | {e.price} | {acts}{fest}")


def main() -> int:
    items = collect_all()
    if not items:
        print("Aucun item collecté. Stop.", file=sys.stderr)
        return 1

    print(f"\n=== {len(items)} items collectés, normalisation sur {MONTHS} ===\n")

    out_dir = Path("cache") / "test_extraction"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict[str, int]] = {}

    for month in MONTHS:
        print(f"\n{'=' * 60}\n  MONTH = {month}\n{'=' * 60}")
        out_path = out_dir / f"{month}.json"
        events = normalize_items(items, month, out_path)

        # Group par source pour affichage
        per_source: dict[str, list] = {}
        for e in events:
            per_source.setdefault(e.source_ref, []).append(e)

        print(f"\n  → {len(events)} events extraits pour {month}\n")
        for src, evs in per_source.items():
            src_short = src if len(src) < 70 else src[:67] + "..."
            print(f"  {src_short} ({len(evs)})")
            for e in evs:
                print_event(e)
            print()

        summary[month] = {short_label(it): 0 for it in items}
        for e in events:
            # retrouve l'item correspondant via source_ref
            for it in items:
                if it.source_ref == e.source_ref:
                    summary[month][short_label(it)] += 1
                    break

    # Récap final
    print(f"\n{'=' * 60}\n  SUMMARY\n{'=' * 60}")
    src_labels = sorted({lbl for m in summary.values() for lbl in m})
    header = f"{'source':<35}" + "".join(f"{m:>10}" for m in MONTHS)
    print(header)
    print("-" * len(header))
    for lbl in src_labels:
        row = f"{lbl:<35}" + "".join(f"{summary[m].get(lbl, 0):>10}" for m in MONTHS)
        print(row)

    print(f"\nOutputs : cache/test_extraction/{{{','.join(MONTHS)}}}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
