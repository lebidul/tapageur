"""Fenêtre pywebview + API bridge pour tapageur-gui."""
from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import webview

from tapageur.gui import settings as _settings
from tapageur.gui.inputs import FileInput, TextInput, UrlInput
from tapageur.gui.service import RunRequest, run

_WEB = Path(__file__).parent / "web" / "index.html"

# Extensions acceptées au drop (mêmes que le dialogue natif choose_files).
_SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _debug_config(payload: dict) -> dict:
    """Config rejouable : le payload sans secret ni flag debug."""
    return {k: v for k, v in payload.items()
            if k not in ("api_key", "debug", "tapeur_email")}


def _read_config(path) -> dict:
    """Lit un fichier config JSON → dict ; {} si absent / illisible."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@contextmanager
def _tee_stdout():
    """Remplace sys.stdout par un tee (terminal réel + buffer). isatty()=False
    pour que Rich n'émette pas de codes couleur dans le log."""
    buf = io.StringIO()
    orig = sys.stdout

    class _Tee:
        def write(self, s):
            orig.write(s)
            buf.write(s)
            return len(s)
        def flush(self):
            orig.flush()
        def isatty(self):
            return False
        def __getattr__(self, name):
            return getattr(orig, name)

    sys.stdout = _Tee()
    try:
        yield buf
    finally:
        sys.stdout = orig


def _write_debug(out_dir, ts: str, config: dict, log: str) -> None:
    d = Path(out_dir) / "debug"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"config_{ts}.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    (d / f"run_{ts}.log").write_text(log, encoding="utf-8")


def _dropped_paths(event: dict) -> list[str]:
    """Extrait les vrais chemins disque d'un event DOM 'drop' pywebview.

    pywebview enrichit chaque fichier droppé de la clé ``pywebviewFullPath``
    (le vrai chemin, absent de l'objet File JS standard). On ne garde que les
    extensions supportées, comme le dialogue natif."""
    files = (event or {}).get("dataTransfer", {}).get("files", []) or []
    paths: list[str] = []
    for f in files:
        p = f.get("pywebviewFullPath")
        if p and Path(p).suffix.lower() in _SUPPORTED_EXTS:
            paths.append(p)
    return paths


class Api:
    """Méthodes appelées depuis le JS (window.pywebview.api.*)."""

    def get_settings(self) -> dict:
        return _settings.load_settings()

    def save_settings(self, data: dict) -> dict:
        _settings.save_settings(data)
        return {"ok": True}

    def get_venues(self) -> list[str]:
        import openpyxl
        from tapageur.gui import export_xlsx as _xlsx
        wb = openpyxl.load_workbook(_xlsx.TEMPLATE_PATH, read_only=True)
        try:
            venues = {r[0] for r in wb["salles_lieux"].iter_rows(values_only=True)
                      if r and r[0] and not str(r[0]).startswith("=")}
        finally:
            wb.close()
        return sorted(venues)

    def choose_output_dir(self) -> str:
        res = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return res[0] if res else ""

    def choose_files(self) -> list[str]:
        res = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True,
            file_types=("Sources (*.pdf;*.jpg;*.jpeg;*.png;*.webp;*.gif)", "Tous (*.*)"),
        )
        return list(res) if res else []

    def import_config(self) -> dict:
        res = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=("Config (*.json)", "Tous (*.*)"),
        )
        if not res:
            return {}
        return _read_config(res[0])

    def default_reference_year(self) -> str:
        from tapageur.gui.service import default_reference_year
        return default_reference_year()

    def run_extraction(self, payload: dict) -> dict:
        """payload : {files:[{path,venue,info_orga,is_festival}], urls:[{url,follow_links,is_festival}],
        months:[...], no_month_filter, formats:[...], out_dir}."""
        # Clé tapée dans l'UI mais pas encore enregistrée : on la persiste d'abord.
        if payload.get("api_key"):
            _settings.save_settings({
                "anthropic_api_key": payload["api_key"],
                "tapeur_email": payload.get("tapeur_email") or _settings.DEFAULT_TAPEUR_EMAIL,
            })

        cfg = _settings.load_settings()
        if not cfg.get("anthropic_api_key"):
            return {"error": "Clé API Anthropic absente — renseigne-la dans Réglages."}
        import os
        os.environ["ANTHROPIC_API_KEY"] = cfg["anthropic_api_key"]

        req = RunRequest(
            file_inputs=[FileInput(**f) for f in payload.get("files", [])],
            url_inputs=[UrlInput(**u) for u in payload.get("urls", [])],
            text_inputs=[TextInput(**t) for t in payload.get("texts", [])],
            months=payload.get("months", []),
            month_mode=payload.get("month_mode", "specific"),
            reference_year=payload.get("reference_year", ""),
            formats=payload.get("formats", []),
            out_dir=Path(payload.get("out_dir") or "."),
            tapeur_email=cfg.get("tapeur_email", _settings.DEFAULT_TAPEUR_EMAIL),
            append=payload.get("append", False),
        )
        def progress(msg: str) -> None:
            # run_extraction tourne hors du thread UI : evaluate_js marshale sans danger.
            try:
                webview.windows[0].evaluate_js("window.onProgress(" + json.dumps(msg) + ")")
            except Exception:  # une erreur de push UI ne doit jamais interrompre le run
                pass

        def _do_run() -> dict:
            try:
                results = run(req, progress=progress)
            except Exception as e:  # remonte l'erreur à l'UI au lieu de crasher
                return {"error": str(e)}
            return {"results": [
                {"month": r.month, "n_events": r.n_events,
                 "files": [str(p) for p in r.files], "alerts": r.alerts}
                for r in results
            ]}

        if payload.get("debug"):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            with _tee_stdout() as buf:
                out = _do_run()
            try:
                _write_debug(payload.get("out_dir") or ".", ts,
                             _debug_config(payload), buf.getvalue())
            except Exception:
                pass  # l'échec d'écriture debug ne doit jamais masquer le résultat
            return out
        return _do_run()


def _webview_fetch(url: str, settle_ms: int = 5000, timeout: float = 60.0) -> str:
    """Récupère le HTML d'une URL via une fenêtre pywebview cachée (WebView2).
    Remplace Playwright dans le GUI. Renvoie '' en cas d'échec/timeout."""
    import time
    import threading
    result: dict[str, str] = {}
    done = threading.Event()
    win = webview.create_window("fetch", url, hidden=True)

    def _on_loaded():
        try:
            time.sleep(settle_ms / 1000)  # laisse le JS se stabiliser
            result["html"] = win.evaluate_js(
                "document.documentElement.outerHTML") or ""
        except Exception:
            result["html"] = ""
        finally:
            done.set()

    win.events.loaded += _on_loaded
    done.wait(timeout)
    try:
        win.destroy()
    except Exception:
        pass
    return result.get("html", "")


def main() -> None:
    window = webview.create_window("tapageur", str(_WEB), js_api=Api(), width=900, height=720)

    def _wire_drop(*_) -> None:
        # Le vrai drag-drop (avec chemins disque) passe par l'API DOM pywebview
        # côté Python : un addEventListener('drop') JS ne verrait que des File
        # sans .path. On s'abonne au drop sur #drop ; pywebview nous livre
        # pywebviewFullPath, qu'on pousse dans l'UI via window.onFilesDropped.
        from webview.dom import DOMEventHandler
        el = window.dom.get_element("#drop")
        if not el:
            return

        def _on_drop(event: dict) -> None:
            paths = _dropped_paths(event)
            if paths:
                window.evaluate_js("window.onFilesDropped(" + json.dumps(paths) + ")")

        el.on("drop", DOMEventHandler(_on_drop, prevent_default=True))

    window.events.loaded += _wire_drop

    from tapageur.connectors import web as _web
    _web._BROWSER_FETCH = _webview_fetch

    webview.start()


if __name__ == "__main__":
    main()
