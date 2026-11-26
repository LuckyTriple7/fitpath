"""Linien-Icons für den Stil „Sachlich“ bauen: app/static/icons.svg aus Lucide (ISC-Lizenz).

    python tools/icons.py

Liest die Icon-Namen aus EMOJI_ICON in app/static/app.js, lädt jedes Icon von lucide-static
(feste Version unten) und schreibt alle als <symbol id="name"> in eine Datei. Neues Emoji in der
Oberfläche: in EMOJI_ICON eintragen (Lucide-Name von https://lucide.dev/icons oder null = bleibt
Emoji, nur grau), dann dieses Skript laufen lassen. tests/test_style.py prüft beides.
"""

import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
LUCIDE = "0.460.0"
URL = "https://cdn.jsdelivr.net/npm/lucide-static@{v}/icons/{name}.svg"


def icon_names() -> list[str]:
    js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    block = re.search(r"const EMOJI_ICON = \{(.*?)\n\};", js, re.S)
    if not block:
        sys.exit("EMOJI_ICON nicht gefunden")
    return sorted(set(re.findall(r':\s*"([a-z0-9-]+)"', block.group(1))))


def fetch(name: str) -> str:
    with urllib.request.urlopen(URL.format(v=LUCIDE, name=name), timeout=20) as r:
        svg = r.read().decode("utf-8")
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S)
    if not inner:
        sys.exit(f"{name}: kein SVG")
    return " ".join(line.strip() for line in inner.group(1).strip().splitlines())


def main() -> int:
    names = icon_names()
    symbols = []
    for n in names:
        try:
            symbols.append(f'<symbol id="{n}" viewBox="0 0 24 24">{fetch(n)}</symbol>')
        except Exception as e:                     # z. B. Tippfehler im Namen → 404
            sys.exit(f"{n}: {e}")
    out = ROOT / "app" / "static" / "icons.svg"
    out.write_text(
        f"<!-- Lucide {LUCIDE} (https://lucide.dev), ISC-Lizenz, siehe static/vendor/LICENSE.txt. "
        "Erzeugt von tools/icons.py, nicht von Hand ändern. -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg">\n' + "\n".join(symbols) + "\n</svg>\n", encoding="utf-8")
    print(f"{len(names)} Icons → {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
