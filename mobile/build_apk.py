"""
Builds the Android app: mobile/build/Multiversal-Manager-<version>.apk

Only what the phone needs is copied into a staging folder (never collection.db, backups or
settings), then `flet build apk` packages it. The first build downloads Flutter and the
Android SDK (a few GB) and takes a while; later builds reuse them.

    multiversal-manager\\Scripts\\python.exe mobile\\build_apk.py

APP_VERSION (e.g. from a release tag) overrides the version in pyproject.toml.

Signing: every APK has to be signed with the same key for a phone to take it as an update.
The key is mobile/signing/release.jks with its password in mobile/signing/signing.json (both
git-ignored; back them up, since a lost key means no more updates to installed apps). The
release workflow passes them instead as ANDROID_SIGNING_KEY_STORE and
ANDROID_SIGNING_KEY_STORE_PASSWORD. Without either, the APK gets this computer's debug key.
"""

# Imports
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# Constants
MOBILE = Path(__file__).resolve().parent
REPO = MOBILE.parent
STAGE = MOBILE / "build" / "src"
# The desktop modules the phone app imports, and what they import in turn
SHARED = ["database.py", "sync.py", "scryfall.py", "copy_details.py", "formats.py", "brackets.py", "importer.py",
          "rules.py", "judge.py", "ask.py", "set_notes.py", "rules_library.json", "card_scan.py", "price_changes.py", "deck_stats.py",
          "synergy.py", "interactions.py", "interactions.json.gz", "market.py", "mtgjson.py", "card_sorting.py"]
MAGIC_PROJECTS = REPO / "external" / "Magic-Projects"
SIGNING = MOBILE / "signing"
KEY_ALIAS = "multiversal-manager"
# theme.FONTS, from Google Fonts' repository
FONTS = {"Cinzel.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf",
         "Roboto.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/Roboto%5Bwdth,wght%5D.ttf"}


def stage():
    # Flet keeps its compile cache in STAGE/build; it's reused, and its background Gradle
    # process may still hold files there open, so only the app's own files are replaced
    STAGE.mkdir(parents=True, exist_ok=True)
    for item in STAGE.iterdir():
        if item.name != "build":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    (STAGE / "assets").mkdir()
    for path in [*MOBILE.glob("*.py"), MOBILE / "pyproject.toml"]:
        if path.name != "build_apk.py":
            shutil.copy(path, STAGE / path.name)
    for name in SHARED:
        shutil.copy(REPO / name, STAGE / name)
    # scryfall.py looks for Magic-Projects at external/Magic-Projects, as in the repo
    for package in ["Functions", "classes"]:
        shutil.copytree(MAGIC_PROJECTS / package, STAGE / "external" / "Magic-Projects" / package,
                        ignore=shutil.ignore_patterns("__pycache__"))
    draw_icon(STAGE / "assets" / "icon.png")
    (STAGE / "assets" / "fonts").mkdir()
    for name, url in FONTS.items():
        urllib.request.urlretrieve(url, STAGE / "assets" / "fonts" / name)


def draw_icon(path, size=1024):
    # The desktop's spellbook, drawn big: Android wants icons up to 432px, more than the .ico's 256
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no window needed, also on a CI runner
    sys.path.insert(0, str(REPO / "assets"))
    from PySide6.QtGui import QGuiApplication
    import make_icon
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 (painting needs one)
    make_icon.draw(size).save(str(path))


def build_number(version):
    # Android's version code, which has to grow with every release: 1.2.3 -> 10203
    major, minor, patch = (int(part) for part in (version.split(".") + ["0", "0"])[:3])
    return major * 10000 + minor * 100 + patch


def signing():
    """(key store path, password) from the release workflow or mobile/signing, or None"""
    if os.environ.get("ANDROID_SIGNING_KEY_STORE"):
        return os.environ["ANDROID_SIGNING_KEY_STORE"], os.environ["ANDROID_SIGNING_KEY_STORE_PASSWORD"]
    settings = SIGNING / "signing.json"
    if settings.exists():
        saved = json.loads(settings.read_text(encoding="utf-8"))
        return str(SIGNING / saved["key_store"]), saved["password"]
    return None


def build():
    version = os.environ.get("APP_VERSION")
    # 64-bit ARM only: every mainstream phone of recent years, at about a third of the size.
    # Leaves out old 32-bit phones and x86 (emulators, a few Chromebooks).
    # Flet's command line through this Python, since where its `flet` command lands differs
    # (next to python.exe in a venv, in a Scripts folder beside it on GitHub's machines)
    command = [sys.executable, "-m", "flet_cli.cli", "build", "apk", str(STAGE), "--output", str(MOBILE / "build" / "apk"),
               "--arch", "arm64-v8a", "--yes"]
    if version:
        command += ["--build-version", version, "--build-number", str(build_number(version))]
    key = signing()
    if key:
        store, password = key
        command += ["--android-signing-key-store", store, "--android-signing-key-alias", KEY_ALIAS,
                    "--android-signing-key-store-password", password, "--android-signing-key-password", password]
    elif version:
        sys.exit("A release APK has to be signed with the release key (see the top of this file).")
    else:
        print("No release key found, so this APK gets this computer's debug key.")
    subprocess.run(command, check=True)
    apk = next((MOBILE / "build" / "apk").glob("*.apk"))
    target = MOBILE / "build" / f"Multiversal-Manager-{version or 'dev'}.apk"
    shutil.copy(apk, target)
    print(f"Built {target}")


if __name__ == "__main__":
    stage()
    build()
