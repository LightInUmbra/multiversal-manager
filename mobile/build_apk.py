"""
Builds the Android app: mobile/build/Multiversal-Manager-<version>.apk

Only what the phone needs is copied into a staging folder (never collection.db, backups or
settings), then `flet build apk` packages it. The first build downloads Flutter and the
Android SDK (a few GB) and takes a while; later builds reuse them.

    multiversal-manager\\Scripts\\python.exe mobile\\build_apk.py

APP_VERSION (e.g. from a release tag) overrides the version in pyproject.toml.
"""

# Imports
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Constants
MOBILE = Path(__file__).resolve().parent
REPO = MOBILE.parent
STAGE = MOBILE / "build" / "src"
# The desktop modules the phone app imports, and what they import in turn
SHARED = ["database.py", "sync.py", "scryfall.py", "copy_details.py", "formats.py", "brackets.py", "importer.py",
          "rules.py", "judge.py", "ask.py", "set_notes.py", "rules_library.json"]
MAGIC_PROJECTS = REPO / "external" / "Magic-Projects"


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


def draw_icon(path, size=1024):
    # The desktop's spellbook, drawn big: Android wants icons up to 432px, more than the .ico's 256
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no window needed, also on a CI runner
    sys.path.insert(0, str(REPO / "assets"))
    from PySide6.QtGui import QGuiApplication
    import make_icon
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 (painting needs one)
    make_icon.draw(size).save(str(path))


def build():
    version = os.environ.get("APP_VERSION")
    flet = Path(sys.executable).with_name("flet.exe" if os.name == "nt" else "flet")
    # 64-bit ARM only: every mainstream phone of recent years, at about a third of the size.
    # Leaves out old 32-bit phones and x86 (emulators, a few Chromebooks).
    command = [str(flet), "build", "apk", str(STAGE), "--output", str(MOBILE / "build" / "apk"),
               "--arch", "arm64-v8a", "--yes"]
    if version:
        command += ["--build-version", version]
    subprocess.run(command, check=True)
    apk = next((MOBILE / "build" / "apk").glob("*.apk"))
    target = MOBILE / "build" / f"Multiversal-Manager-{version or 'dev'}.apk"
    shutil.copy(apk, target)
    print(f"Built {target}")


if __name__ == "__main__":
    stage()
    build()
