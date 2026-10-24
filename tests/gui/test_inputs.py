from pathlib import Path
from datetime import datetime
from tapageur.gui import inputs
from tapageur.schema import CollectedItem


def test_items_from_files_routes_image(tmp_path):
    # 1x1 px PNG minimal
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f1e0000000049454e44ae426082"
    )
    f = tmp_path / "flyer.png"
    f.write_bytes(png)
    items = inputs.items_from_files([f])
    assert len(items) == 1
    assert items[0].source_kind == "image"
    assert items[0].source_ref == str(f)


def test_items_from_files_skips_unsupported(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("rien", encoding="utf-8")
    assert inputs.items_from_files([txt]) == []


def test_items_from_files_extends_multi(monkeypatch, tmp_path):
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(inputs, "_route_file", lambda p: ["a", "b"])
    assert inputs.items_from_files([f]) == ["a", "b"]


def test_url_input_builds_synthetic_config(monkeypatch):
    captured = {}

    class FakeWeb:
        def __init__(self, config):
            captured["config"] = config

        def collect(self, month, progress=None):
            captured["month"] = month
            yield CollectedItem(
                source_kind="web",
                source_ref="https://ex.fr/a",
                fetched_at=datetime.utcnow().isoformat() + "Z",
                raw_text="texte",
                raw_metadata={},
            )

    monkeypatch.setattr(inputs, "WebConnector", FakeWeb)
    out = inputs.items_from_urls(
        [inputs.UrlInput(url="https://ex.fr/a", follow_links=True, is_festival=True)],
        month="2026-10",
    )
    assert len(out) == 1
    site = captured["config"]["websites"][0]
    assert site["url"] == "https://ex.fr/a"
    assert site["needs_browser"] is True
    assert site["follow_event_links"] is True
    assert site["mode"] == "festival_onliner"
    assert site["prefilter_by_month"] is False
    assert captured["month"] == "2026-10"


def test_url_input_defaults_no_festival(monkeypatch):
    captured = {}

    class FakeWeb:
        def __init__(self, config):
            captured["config"] = config

        def collect(self, month, progress=None):
            return iter(())

    monkeypatch.setattr(inputs, "WebConnector", FakeWeb)
    inputs.items_from_urls([inputs.UrlInput(url="https://ex.fr/b")], month="2026-10")
    site = captured["config"]["websites"][0]
    assert site["follow_event_links"] is False
    assert "mode" not in site


def test_url_input_sets_follow_scope_domain(monkeypatch):
    captured = {}

    class FakeWeb:
        def __init__(self, config):
            captured["config"] = config

        def collect(self, month, progress=None):
            return iter(())

    monkeypatch.setattr(inputs, "WebConnector", FakeWeb)
    inputs.items_from_urls([inputs.UrlInput(url="https://ex.fr/a", follow_links=True)], month="2026-10")
    site = captured["config"]["websites"][0]
    assert site["follow_scope"] == "domain"


def test_items_from_files_reports_progress(tmp_path):
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f1e0000000049454e44ae426082"
    )
    f = tmp_path / "flyer.png"
    f.write_bytes(png)
    seen = []
    inputs.items_from_files([f], progress=lambda m: seen.append(m))
    assert any("flyer.png" in m and "1/1" in m for m in seen)


def test_items_from_texts_builds_item_with_overrides():
    out = inputs.items_from_texts([
        inputs.TextInput(text="concert ce soir", venue="Le Scarron", info_orga="Asso X"),
    ])
    assert len(out) == 1
    it = out[0]
    assert it.source_kind == "text"
    assert it.raw_text == "concert ce soir"
    assert it.raw_metadata["default_venue"] == "Le Scarron"
    assert it.raw_metadata["default_festival"] == "Asso X"
    assert it.source_ref == "texte #1"


def test_items_from_texts_skips_blank():
    out = inputs.items_from_texts([
        inputs.TextInput(text="   "),
        inputs.TextInput(text="vrai texte"),
    ])
    assert len(out) == 1
    assert out[0].raw_text == "vrai texte"


def test_items_from_urls_threads_progress(monkeypatch):
    captured = {}

    class FakeWeb:
        def __init__(self, config):
            pass

        def collect(self, month, progress=None):
            captured["progress"] = progress
            return iter(())

    monkeypatch.setattr(inputs, "WebConnector", FakeWeb)
    cb = lambda m: None
    inputs.items_from_urls([inputs.UrlInput(url="https://ex.fr/a")], month="2026-11", progress=cb)
    assert captured["progress"] is cb


def test_url_to_site_carries_overrides():
    site = inputs._url_to_site(inputs.UrlInput(url="https://ex.fr/a", venue="Le Scarron", info_orga="Asso X"))
    assert site["default_venue"] == "Le Scarron"
    assert site["default_festival"] == "Asso X"
