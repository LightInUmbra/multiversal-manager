"""
Builds the web version: mobile/build/web, a static site for GitHub Pages

It's the phone app, staged the same way as for the APK (see build_apk.py) and built with
`flet build web`, so the Python runs in the browser (Pyodide) and needs no server. The web
app keeps no collection of its own between visits; signing in pulls it from sync.

    multiversal-manager\\Scripts\\python.exe mobile\\build_web.py

BASE_URL is the folder the site is served from: "multiversal-manager" for
https://lightinumbra.github.io/multiversal-manager/, "/" (the default) to try it locally with
`python -m http.server -d mobile/build/web`.
"""

# Imports
import json
import os
import shutil
import subprocess
import sys

import requests

from build_apk import MOBILE, REPO, STAGE, stage


def bundle_rules():
    """The rules for the website to read (rules.BUNDLED), since browsers can't download them
    from Wizards of the Coast: the desktop's downloaded copy (every document, set notes and
    MTG Wiki pages), plus Scryfall's list of card names, which Ask a Rules Question uses."""
    source, target = REPO / "rules", STAGE / "rules_bundle"
    if not (source / "cr.txt").exists():
        raise SystemExit("No rules to bundle: open the desktop app's Rules window once to download them.")
    shutil.copytree(source, target, dirs_exist_ok=True)
    if not (target / "card_names.json").exists():
        names = requests.get("https://api.scryfall.com/catalog/card-names", timeout=60,
                             headers={"User-Agent": "MultiversalManager/1.0", "Accept": "application/json"})
        names.raise_for_status()
        (target / "card_names.json").write_text(json.dumps(names.json()["data"]), encoding="utf-8")
    print(f"Bundled the rules: {sum(1 for p in target.rglob('*') if p.is_file())} files")


def build():
    command = [sys.executable, "-m", "flet_cli.cli", "build", "web", str(STAGE), "--output", str(MOBILE / "build" / "web"),
               "--base-url", os.environ.get("BASE_URL", "/"), "--yes"]
    if os.environ.get("APP_VERSION"):
        command += ["--build-version", os.environ["APP_VERSION"]]
    subprocess.run(command, check=True)
    print(f"Built {MOBILE / 'build' / 'web'}")


if __name__ == "__main__":
    stage()
    bundle_rules()
    build()
