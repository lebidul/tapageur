"""Fenêtre pywebview + API bridge pour tapageur-gui."""
from __future__ import annotations

import json
from pathlib import Path

import webview

from tapageur.gui import settings as _settings
from tapageur.gui.inputs import TextInput, UrlInput
from tapageur.gui.service import RunRequest, run

_WEB = Path(__file__).parent / "web" / "index.html"


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

    def run_extraction(self, payload: dict) -> dict:
        """payload : {file_paths, urls:[{url,follow_links,is_festival}],
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
            file_paths=[Path(p) for p in payload.get("file_paths", [])],
            url_inputs=[UrlInput(**u) for u in payload.get("urls", [])],
            text_inputs=[TextInput(**t) for t in payload.get("texts", [])],
            months=payload.get("months", []),
            no_month_filter=payload.get("no_month_filter", False),
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

        try:
            results = run(req, progress=progress)
        except Exception as e:  # remonte l'erreur à l'UI au lieu de crasher
            return {"error": str(e)}
        return {"results": [
            {"month": r.month, "n_events": r.n_events,
             "files": [str(p) for p in r.files], "alerts": r.alerts}
            for r in results
        ]}


def main() -> None:
    webview.create_window("tapageur", str(_WEB), js_api=Api(), width=900, height=720)
    webview.start()


if __name__ == "__main__":
    main()
