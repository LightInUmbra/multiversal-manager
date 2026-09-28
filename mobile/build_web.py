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
import os
import subprocess
import sys

from build_apk import MOBILE, STAGE, stage


def build():
    command = [sys.executable, "-m", "flet_cli.cli", "build", "web", str(STAGE), "--output", str(MOBILE / "build" / "web"),
               "--base-url", os.environ.get("BASE_URL", "/"), "--yes"]
    if os.environ.get("APP_VERSION"):
        command += ["--build-version", os.environ["APP_VERSION"]]
    subprocess.run(command, check=True)
    print(f"Built {MOBILE / 'build' / 'web'}")


if __name__ == "__main__":
    stage()
    build()
