"""Rezept-Import per Link (Cookidoo, Chefkoch und andere Seiten mit schema.org „Recipe“).

Ablauf: Seite einmal abrufen (nur öffentliche Adressen, höchstens 3 MB), die eingebetteten
Rezeptdaten (JSON-LD) lesen und jede Zutat einem Lebensmittel der eigenen Datenbank zuordnen
(Menge in Gramm schätzen, Suche, auf Wunsch KI). Gespeichert wird erst, wenn der Nutzer die
Zuordnung bestätigt; dann entsteht ein normales Gericht (siehe foods.save_recipe).

Die Nährwerte der Seite (oft nur kcal, Eiweiß, Fett, Kohlenhydrate) dienen zur Kontrolle und
als Rückfall, wenn sich die Zutaten nicht zuordnen lassen.
"""

import html
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from . import __version__, foods

MAX_BYTES = 3 * 1024 * 1024
UA = f"FitPath/{__version__} (Rezept-Import auf Nutzerwunsch)"

FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
# Einheit → Gramm (Flüssigkeiten ml ≈ g)
UNITS = {
    "g": 1, "gramm": 1, "kg": 1000, "ml": 1, "l": 1000, "liter": 1000, "cl": 10, "dl": 100,
    "el": 12, "esslöffel": 12, "tbsp": 12, "tl": 5, "teelöffel": 5, "tsp": 5,
    "prise": 0.5, "prisen": 0.5, "pinch": 0.5, "msp": 0.5, "msp.": 0.5, "messerspitze": 0.5,
    "dose": 400, "dosen": 400, "becher": 200, "pck": 10, "pck.": 10, "päckchen": 10, "packung": 200,
    "bund": 30, "zehe": 4, "zehen": 4, "knoblauchzehe": 4, "knoblauchzehen": 4, "clove": 4, "cloves": 4,
    "scheibe": 25, "scheiben": 25, "slice": 25, "slices": 25, "handvoll": 30, "stange": 60, "stangen": 60,
    "zweig": 2, "zweige": 2, "blatt": 1, "blätter": 1, "tasse": 150, "cup": 150,
}
# Stückgewichte, wenn keine Einheit dasteht („1 Zwiebel“)
PIECES = [
    (r"zwiebel|onion", 80), (r"knoblauch|garlic", 4), (r"karotte|möhre|carrot", 70), (r"kartoffel|potato", 80),
    (r"paprika|pepper", 160), (r"tomate|tomato", 90), (r"zucchini", 250), (r"gurke|cucumber", 400),
    (r"ei\b|eier|egg", 55), (r"apfel|apple", 150), (r"birne|pear", 160), (r"banane|banana", 120),
    (r"zitrone|lemon", 100), (r"limette|lime", 60), (r"orange", 150), (r"avocado", 150), (r"aubergine", 300),
    (r"lauch|porree|leek", 200), (r"brötchen|roll", 60), (r"hähnchenbrust|chicken breast", 150),
]
# Englische Zutaten (internationale Cookidoo-Rezepte), wenn keine KI übersetzt
EN = {
    "onion": "Speisezwiebel", "onions": "Speisezwiebel", "carrot": "Karotte", "carrots": "Karotte",
    "sweet potato": "Süßkartoffel", "potato": "Kartoffel", "potatoes": "Kartoffel", "pear": "Birne", "apple": "Apfel",
    "water": "Trinkwasser", "chicken": "Hähnchen", "chicken breast": "Hähnchen Brustfilet", "chicken thighs": "Hähnchen Unterschenkel",
    "beef": "Rind", "minced beef": "Rind Hackfleisch", "ground beef": "Rind Hackfleisch", "pork": "Schwein",
    "zucchini": "Zucchini", "courgette": "Zucchini", "garlic": "Knoblauch", "garlic clove": "Knoblauch", "garlic cloves": "Knoblauch",
    "tomato": "Tomate", "tomatoes": "Tomate", "tinned tomatoes": "Tomaten Konserve", "olive oil": "Olivenöl",
    "vegetable oil": "Rapsöl", "rapeseed oil": "Rapsöl", "butter": "Butter", "flour": "Weizen Mehl Type 405",
    "plain flour": "Weizen Mehl Type 405", "sugar": "Zucker weiß", "milk": "Vollmilch", "cream": "Schlagsahne",
    "salt": "Speisesalz", "pepper": "Pfeffer", "egg": "Hühnerei", "eggs": "Hühnerei", "rice": "Reis", "pasta": "Teigwaren",
    "spinach": "Spinat", "broccoli": "Broccoli", "lemon": "Zitrone", "honey": "Honig", "cheese": "Gouda",
    "parmesan": "Parmesan", "yoghurt": "Joghurt", "yogurt": "Joghurt", "vegetable stock paste": "Gemüsebrühe",
    "vegetable stock": "Gemüsebrühe", "stock": "Gemüsebrühe", "leek": "Lauch", "pepper bell": "Gemüsepaprika",
    "red pepper": "Gemüsepaprika rot", "mushrooms": "Champignon", "lentils": "Linsen", "oats": "Hafer Flocken",
}
SKIP = re.compile(r"^(wasser|water|eiswürfel|ice)\b|nach belieben|zum garnieren|optional", re.I)
NOISE = re.compile(r"\b(frisch|gehackt|gewürfelt|halbiert|geviertelt|in stücken|in scheiben|geschält|fein|grob|"
                   r"tiefgekühlt|tk|gerieben|zerdrückt|zimmerwarm|weich|kalt|warm|ca\.|etwa|klein|groß|mittelgroß)\b", re.I)


class ImportError_(Exception):
    pass


# ---------- Abruf ----------

def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def fetch(url: str) -> tuple[str, str]:
    """Seite abrufen. Nur http/https, nur öffentliche Server (kein Zugriff aufs Heimnetz), höchstens 3 Weiterleitungen."""
    for _ in range(4):
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname or u.port not in (None, 80, 443):
            raise ImportError_("Bitte einen normalen https-Link einfügen")
        if not _public_host(u.hostname):
            raise ImportError_("Die Adresse ist nicht öffentlich erreichbar")
        with httpx.Client(timeout=12, follow_redirects=False) as client:
            with client.stream("GET", url, headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
                                                     "Accept": "text/html,application/xhtml+xml"}) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code != 200:
                    raise ImportError_(f"Seite antwortet mit {r.status_code}")
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise ImportError_("Seite zu groß")
                return url, body.decode(r.encoding or "utf-8", "replace")
    raise ImportError_("Zu viele Weiterleitungen")


# ---------- Rezeptdaten ----------

def _recipes(node):
    if isinstance(node, list):
        for x in node:
            yield from _recipes(x)
    elif isinstance(node, dict):
        t = node.get("@type")
        if t == "Recipe" or (isinstance(t, list) and "Recipe" in t):
            yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _recipes(node[key])


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None


def parse_recipe(page: str) -> dict:
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for r in _recipes(data):
            ingredients = [html.unescape(re.sub(r"<[^>]+>", "", str(x))).strip() for x in r.get("recipeIngredient") or []]
            if not ingredients:
                continue
            y = r.get("recipeYield")
            y = y[0] if isinstance(y, list) and y else y
            ytext = html.unescape(str(y or "")).strip()
            n = r.get("nutrition") or {}
            nutrition = {k: _num(n.get(src)) for k, src in (
                ("kcal", "calories"), ("protein", "proteinContent"), ("fat", "fatContent"), ("satfat", "saturatedFatContent"),
                ("carbs", "carbohydrateContent"), ("sugar", "sugarContent"), ("fiber", "fiberContent"))}
            yield_g = _num(ytext) if re.search(r"\d\s*(g|gramm|ml)\b", ytext, re.I) else None
            servings = None if yield_g else _num(ytext)
            return {"name": html.unescape(str(r.get("name") or "Rezept")).strip()[:120], "ingredients": ingredients[:60],
                    "yield_text": ytext, "yield_g": yield_g, "servings": int(servings) if servings else None,
                    "nutrition": {k: v for k, v in nutrition.items() if v is not None}}
    raise ImportError_("Auf der Seite stehen keine lesbaren Rezeptdaten (schema.org „Recipe“)")


# ---------- Zutaten ----------

def _amount(text: str) -> tuple[float | None, str]:
    """Führende Menge lesen: 2, 0,5, 1/2, ½, 1 ½, Spannen wie 40 - 60 (Mittelwert)."""
    t = text.strip()
    for f, v in FRACTIONS.items():
        t = re.sub(rf"(\d)\s*{f}", lambda m: f"{m.group(1)}+{v}", t)
        t = t.replace(f, str(v))
    m = re.match(r"^(\d+(?:[.,]\d+)?(?:\+\d+(?:\.\d+)?)?(?:/\d+)?)(?:\s*[-–]\s*(\d+(?:[.,]\d+)?(?:\+\d+(?:\.\d+)?)?))?\s*", t)
    if not m:
        return None, t

    def val(s):
        s = s.replace(",", ".")
        if "/" in s:
            a, b = s.split("/")
            return float(a) / float(b)
        return sum(float(x) for x in s.split("+"))
    a = val(m.group(1))
    if m.group(2):
        a = (a + val(m.group(2))) / 2
    return a, t[m.end():]


def parse_line(line: str) -> dict:
    """„250 g Süßkartoffel“ → {grams: 250, name: "Süßkartoffel"}; ohne Gramm-Angabe grams None."""
    amount, rest = _amount(line)
    words = rest.split()
    unit = words[0].lower().rstrip(".") if words else ""
    grams = None
    if amount is not None and (unit in UNITS or unit + "." in UNITS):
        grams = amount * UNITS.get(unit, UNITS.get(unit + ".", 1))
        rest = " ".join(words[1:])
    if not rest.strip() and words:          # „3 Knoblauchzehen“: Einheit ist zugleich die Zutat
        rest = words[0]
    rest = re.sub(r"^(nach belieben|optional|etwas|evtl\.?)\s+", "", rest, flags=re.I)
    name = re.split(r"[,(]", rest)[0]
    name = NOISE.sub(" ", name)
    name = re.sub(r"\b(skinless|boneless|fresh|chopped|diced|sliced|peeled|large|small|medium)\b", " ", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" -–")
    if grams is None and amount is not None:
        for pat, g in PIECES:
            if re.search(pat, name, re.I):
                grams = amount * g
                break
    return {"line": line, "name": name or line, "amount": amount, "grams": round(grams, 1) if grams else None}


def match(conn, line: str, search: str | None = None, grams: float | None = None) -> dict:
    p = parse_line(line)
    term = (search or p["name"]).strip()
    if not search:
        low = term.lower()
        term = EN.get(low) or next((v for k, v in sorted(EN.items(), key=lambda kv: -len(kv[0])) if re.search(rf"\b{k}\b", low)), term)
    hits = foods.search(conn, term, 5) if term else []
    if not hits and " " in term:
        hits = foods.search(conn, term.split()[-1], 5)      # „rote Linsen“ → „Linsen“
    g = grams or p["grams"]
    if not g and p["amount"] and hits and hits[0]["portions"]:
        g = hits[0]["portions"][0]["g"] * p["amount"]
    if not g and p["amount"] is None:
        g = 5                         # ohne Menge: Würz- oder Garnierzutat
    skip = bool(SKIP.search(p["name"]) or SKIP.search(line))
    return {"line": line, "search": term, "grams": round(g or 100, 1), "guessed": not (grams or p["grams"]),
            "candidates": hits, "use": bool(hits) and not skip}


def build(conn, url: str, ai_terms: list | None = None) -> dict:
    final_url, page = fetch(url)
    return from_parsed(conn, final_url, parse_recipe(page), ai_terms)


def from_parsed(conn, final_url: str, r: dict, ai_terms: list | None = None) -> dict:
    """Vorschlag zum Bestätigen. ai_terms: optional je Zutat {search, grams} von der KI."""
    items = []
    for i, line in enumerate(r["ingredients"]):
        t = ai_terms[i] if ai_terms and i < len(ai_terms) and isinstance(ai_terms[i], dict) else {}
        items.append(match(conn, line, t.get("search"), t.get("grams")))
    # Cookidoo & Co.: Nährwerte gelten für eine Portion, bei Ausbeute in Gramm für die ganze Menge
    return {"name": r["name"], "url": final_url, "servings": r["servings"] or 4, "servings_known": bool(r["servings"]),
            "total_g": r["yield_g"], "yield_text": r["yield_text"], "nutrition": r["nutrition"] or None,
            "nutrition_scope": "total" if r["yield_g"] else "portion", "items": items}
