"""Release vorbereiten: Version setzen, Changelog-Abschnitt datieren, Commit und Tag.

    python tools/release.py 1.2.3
    git push --follow-tags        # danach baut GitHub das Image (:1.2.3, :1.2, :latest) und das Release

Voraussetzungen: auf main, keine offenen Änderungen, im CHANGELOG.md unter
„## [Unveröffentlicht]“ steht mindestens ein Eintrag.
"""

import datetime
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main(version: str) -> int:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit("Version als X.Y.Z angeben")
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        sys.exit("nicht auf main")
    if git("status", "--porcelain"):
        sys.exit("offene Änderungen – erst committen")
    if f"v{version}" in git("tag").split():
        sys.exit(f"Tag v{version} gibt es schon")
    init = ROOT / "app" / "__init__.py"
    current = re.search(r'__version__ = "([^"]+)"', init.read_text()).group(1)
    if tuple(map(int, version.split("."))) <= tuple(map(int, current.split("."))):
        sys.exit(f"{version} ist nicht neuer als {current}")
    log = ROOT / "CHANGELOG.md"
    text = log.read_text()
    m = re.search(r"^## \[Unveröffentlicht\]\n(.*?)(?=^## \[)", text, re.S | re.M)
    if not m or not m.group(1).strip():
        sys.exit("Unter „## [Unveröffentlicht]“ steht nichts")
    today = datetime.date.today().isoformat()
    text = text.replace("## [Unveröffentlicht]\n", f"## [Unveröffentlicht]\n\n## [{version}] – {today}\n", 1)
    log.write_text(text)
    init.write_text(init.read_text().replace(f'__version__ = "{current}"', f'__version__ = "{version}"'))
    git("add", "CHANGELOG.md", "app/__init__.py")
    git("commit", "-m", f"chore(release): v{version}")
    git("tag", "-a", f"v{version}", "-m", f"v{version}")
    print(f"v{version} vorbereitet ({current} → {version}). Jetzt: git push --follow-tags")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
