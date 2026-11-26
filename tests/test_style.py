"""Beide Stile (Lebendig, Sachlich) bleiben vollständig: jedes Emoji hat ein Linien-Icon oder ist bewusst
ausgenommen, jedes Icon steckt in icons.svg, Radien laufen über die Variablen in styles.css."""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
EMOJI = re.compile("[ℹ←-⇿⌀-⏿☀-➿⬀-⯿\U0001F000-\U0001FAFF]")


def emoji_icon() -> dict:
    block = re.search(r"const EMOJI_ICON = \{(.*?)\n\};", APP_JS, re.S).group(1)
    return {k: v for k, v in re.findall(r'"([^"]+)":\s*(?:"([a-z0-9-]+)"|null)', block)}


def emoji_keep() -> set:
    return set(json.loads(re.search(r"const EMOJI_KEEP = new Set\((\[.*?\])\)", APP_JS).group(1)))


def test_every_emoji_has_icon_or_is_kept():
    known = set(emoji_icon()) | emoji_keep()
    files = [STATIC / "app.js", STATIC / "index.html", *sorted((ROOT / "app").glob("*.py"))]
    missing = {}
    for f in files:
        for ch in EMOJI.findall(f.read_text(encoding="utf-8")):
            if ch not in known:
                missing.setdefault(ch, f.name)
    assert not missing, f"Emoji ohne Eintrag in EMOJI_ICON (app.js), Stil „Sachlich“ bedenken: {missing}"


def test_icons_exist_in_sprite():
    sprite = set(re.findall(r'<symbol id="([a-z0-9-]+)"', (STATIC / "icons.svg").read_text(encoding="utf-8")))
    names = {v for v in emoji_icon().values() if v}
    assert names <= sprite, f"fehlen in icons.svg, python tools/icons.py ausführen: {sorted(names - sprite)}"


def test_both_styles_define_same_light_tokens():
    blocks = re.findall(r':root\[data-style="sachlich"\][^{]*\{([^}]*)\}', CSS)
    tokens = [set(re.findall(r"(--[a-z0-9-]+):", b)) for b in blocks]
    dark, light_sys, light = tokens
    assert light_sys == light
    assert light <= dark


def test_radii_use_variables():
    # Feste Radien nur für kleine Details (Legenden, Punkte); alles andere über --radius/--r-md/--r-sm/--r-pill,
    # damit der Stil „Sachlich“ sie zentral umstellen kann
    allowed = {"0", "50%", "2px", "3px", "4px", "8px", "12px"}
    bad = []
    for val in re.findall(r"border-radius:\s*([^;]+);", CSS):
        while re.search(r"\w+\([^()]*\)", val):          # var(...) und calc(...) von innen nach außen entfernen
            val = re.sub(r"\w+\([^()]*\)", "", val)
        parts = val.split()
        bad += [p for p in parts if p not in allowed]
    assert not bad, f"feste Radien, bitte Variablen nehmen: {bad}"


def test_style_assets_are_served():
    from tests.test_api import client
    c = client()
    r = c.get("/icons.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml") and "<symbol" in r.text
    r = c.get("/vendor/inter-latin-wght-5.1.0.woff2")
    assert r.status_code == 200 and r.headers["content-type"] == "font/woff2"
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert '"/icons.svg"' in sw and '"/vendor/inter-latin-wght-5.1.0.woff2"' in sw     # offline verfügbar
    c.__exit__(None, None, None)
