# -*- mode: python ; coding: utf-8 -*-
# NB : construire sous Windows natif (l'exe .exe + le backend EdgeChromium en
# dépendent). Un build WSL/Linux produit un binaire Linux inutilisable ici.
import sys
from PyInstaller.utils.hooks import collect_all

datas = [
    ("tapageur/gui/web/index.html", "tapageur/gui/web"),
    ("tapageur/gui/assets/template.xlsx", "tapageur/gui/assets"),
    ("config/mappings.yaml", "config"),
]
binaries = []
hiddenimports = []
if sys.platform == "win32":
    # Backend pywebview Windows = EdgeChromium via pythonnet (paquets séparés
    # non ramenés par collect_all) → à déclarer, sinon ImportError au run.
    hiddenimports += ["clr", "clr_loader", "webview.platforms.edgechromium"]
# Collecter proprement les paquets à binaires / data cachés.
for pkg in ("webview", "pypdfium2", "pdfplumber", "anthropic"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

excludes = [
    "paddleocr", "paddle", "pandas", "gspread", "msal",
    "extract_msg", "playwright", "playwright_stealth",
]

a = Analysis(
    ["tapageur/gui/app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="tapageur-gui",
    console=False,
    upx=False,
)
