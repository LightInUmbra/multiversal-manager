"""
Builds the Windows app, in two versions from one PyInstaller build:

- dist/Multiversal-Manager-<version>-portable.zip: unzip anywhere (a USB stick, say) and
  run. "Portable Mode.txt" beside the .exe keeps the collection and settings in that folder.
- dist/Multiversal-Manager-<version>-setup.exe: installs for the current Windows user (no
  admin needed), with a Start menu entry and an uninstaller; the collection lives in
  %LOCALAPPDATA%\\Multiversal Manager. Needs Inno Setup 6 (winget install JRSoftware.InnoSetup).

Run it with the project's virtual environment:
    multiversal-manager\\Scripts\\python.exe build.py
"""

# Imports
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import PyInstaller.__main__

import database

APP = "Multiversal Manager"
DOWNLOAD = "Multiversal-Manager"  # download file names: GitHub turns spaces into dots
VERSION = os.environ.get("APP_VERSION") or "1.0.0"  # releases set it from the tag (v1.2.0 -> 1.2.0)
ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILT = DIST / APP  # the app folder PyInstaller makes

PORTABLE_NOTE = """This copy of Multiversal Manager is portable.

Your collection, settings, backups, rules and card images are kept in this folder,
next to Multiversal Manager.exe, so you can carry the whole folder on a USB stick
and use it on any Windows computer.

Delete this file to keep your data in your Windows user folder instead
(%LOCALAPPDATA%\\Multiversal Manager), like the installed version does.
"""


def build_app():
    # One folder (not one file): starts much faster, since nothing is unpacked on every launch
    PyInstaller.__main__.run([
        str(ROOT / "main.py"),
        "--name", APP,
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        # Magic-Projects is put on sys.path at run time, which PyInstaller can't see
        "--paths", str(ROOT / "external" / "Magic-Projects"),
        "--hidden-import", "Functions.ScryFunctions",
        "--hidden-import", "classes.card",
        "--add-data", f"{ROOT / 'rules_library.json'}{os.pathsep}.",
        "--add-data", f"{ROOT / 'interactions.json.gz'}{os.pathsep}.",   # which cards work together
        "--icon", str(ROOT / "assets" / "icon.ico"),                             # the .exe's icon
        "--add-data", f"{ROOT / 'assets' / 'icon.ico'}{os.pathsep}assets",      # the windows' icon
    ])


def make_portable():
    # The app folder zipped with the portable marker beside the .exe
    target = DIST / f"{DOWNLOAD}-{VERSION}-portable.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in BUILT.rglob("*"):
            zipped.write(path, Path(APP) / path.relative_to(BUILT))
        zipped.writestr(f"{APP}/{database.PORTABLE_MARKER}", PORTABLE_NOTE)
    return target


def find_inno_setup():
    candidates = [Path(os.environ.get(var, "")) / "Inno Setup 6" / "ISCC.exe"
                  for var in ("ProgramFiles(x86)", "ProgramFiles")]
    candidates.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    found = shutil.which("ISCC")
    return Path(found) if found else next((c for c in candidates if c.exists()), None)


def make_installer():
    compiler = find_inno_setup()
    if compiler is None:
        print("Inno Setup 6 isn't installed, so no installer was made. "
              "Install it with: winget install JRSoftware.InnoSetup")
        return None
    subprocess.run([str(compiler), f"/DAppVersion={VERSION}", f"/DSourceDir={BUILT}", f"/DOutputDir={DIST}",
                    f"/DOutputName={DOWNLOAD}-{VERSION}-setup", str(ROOT / "installer.iss")], check=True)
    return DIST / f"{DOWNLOAD}-{VERSION}-setup.exe"


def main():
    build_app()
    if (BUILT / database.PORTABLE_MARKER).exists():
        sys.exit("The app folder shouldn't contain the portable marker")
    print("Portable:", make_portable())
    installer = make_installer()
    if installer:
        print("Installer:", installer)


if __name__ == "__main__":
    main()
