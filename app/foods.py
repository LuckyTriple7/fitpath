"""Lebensmittel: BLS-Import, Suche, Portionen, Open-Food-Facts-Barcodes.

Quellen:
- BLS 4.0 (Max Rubner-Institut, CC BY 4.0) als Seed-Datei seed/bls40.csv.gz,
  wird beim ersten Start importiert.
- Open Food Facts (ODbL) nur per Barcode-Abfrage, Ergebnis lokal gespeichert.
  Die Such-API darf laut Open Food Facts nicht für Suche beim Tippen genutzt
  werden, deshalb sucht FitPath nur in der eigenen Datenbank.
"""

import csv
import gzip
import json
import os
import re
import threading
import time

import httpx

from . import __version__, db, points

SEED = os.environ.get("BLS_SEED", os.path.join(os.path.dirname(os.path.dirname(__file__)), "seed", "bls40.csv.gz"))
OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
OFF_FIELDS = "code,product_name,product_name_de,generic_name_de,brands,nutriments,serving_quantity,quantity"
OFF_CONTACT = os.environ.get("OFF_CONTACT", "").strip()

FOOD_COLS = ("id, source, code, name, brand, kcal, protein, fat, satfat, carbs, sugar, fiber, alcohol, salt, "
             "zero_auto, zero_user, portions, serving_g, fav, hidden, pts_100")


def as_dict(row) -> dict:
    d = dict(row)
    d["zero"] = bool(d["zero_user"] if d.get("zero_user") is not None else d.get("zero_auto"))
    d["portions"] = portions_for(d)
    d["ampel"] = points.ampel(d.get("kcal"))
    if d["zero"]:
        d["points_100"] = 0
    elif d.get("pts_100") is not None:      # Gericht: 0-Punkte-Zutaten schon herausgerechnet
        d["points_100"] = points.round_points(d["pts_100"])
    else:
        d["points_100"] = points.round_points(points.raw_points(points.scale(d, 100)))
    return d


# ---------- BLS-Import ----------

def _num(v):
    v = (v or "").strip()
    return float(v) if v else None


def import_bls(conn, path: str = SEED) -> int:
    """BLS-Seed importieren oder aktualisieren. Eigene Markierungen (Favorit, 0-Punkte,
    Portionen, ausgeblendet) bleiben erhalten."""
    now = db.iso(db.now_utc())
    n = 0
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            vals = {k: _num(r.get(k)) for k in db.NUTRIENTS}
            zero = 1 if points.zero_auto(r["code"], r["name"], vals["kcal"]) else 0
            conn.execute(
                "INSERT INTO foods (source, code, name, kcal, protein, fat, satfat, carbs, sugar, fiber, alcohol, salt, "
                "zero_auto, created, updated) VALUES ('bls', :code, :name, :kcal, :protein, :fat, :satfat, :carbs, "
                ":sugar, :fiber, :alcohol, :salt, :zero, :now, :now) "
                "ON CONFLICT(source, code) WHERE code IS NOT NULL DO UPDATE SET name = excluded.name, "
                "kcal = excluded.kcal, protein = excluded.protein, fat = excluded.fat, satfat = excluded.satfat, "
                "carbs = excluded.carbs, sugar = excluded.sugar, fiber = excluded.fiber, alcohol = excluded.alcohol, "
                "salt = excluded.salt, zero_auto = excluded.zero_auto, updated = excluded.updated",
                {**vals, "code": r["code"], "name": r["name"], "zero": zero, "now": now})
            n += 1
    return n


def ensure_seed(conn) -> int:
    if conn.execute("SELECT 1 FROM foods WHERE source = 'bls' LIMIT 1").fetchone():
        return 0
    if not os.path.exists(SEED):
        print(f"BLS-Seed fehlt: {SEED}", flush=True)
        return 0
    n = import_bls(conn)
    print(f"BLS importiert: {n} Lebensmittel", flush=True)
    return n


# ---------- Suche ----------

# Suche: Die Datenbank ist klein (BLS ≈ 7.000 plus eigene), deshalb vergleicht FitPath
# im Speicher. Deutsche Komposita tragen das Hauptwort hinten: "Roggenbrot" ist Brot,
# "Brotaufstrich" ist Aufstrich. Darum zählt ein Treffer am Wortende des ersten Begriffs
# fast so viel wie ein exaktes Wort, ein Treffer am Wortanfang deutlich weniger.

SYNONYMS = {
    # Schlüssel und Werte in Suchschreibweise: klein, ä→a, ö→o, ü→u, ß→ss
    "ei": ["huhnerei"], "eier": ["huhnerei"], "nutella": ["nuss-nougat-creme"],
    # meist gekocht gegessen: gekochte Variante zuerst
    "nudeln": ["teigwaren eifrei gekocht"], "nudel": ["teigwaren eifrei gekocht"],
    "pasta": ["teigwaren eifrei gekocht"], "spaghetti": ["teigwaren eifrei gekocht"],
    "reis": ["reis poliert gekocht", "reis gekocht"], "kartoffel": ["kartoffel geschalt gekocht"],
    "kartoffeln": ["kartoffel geschalt gekocht"], "haferbrei": ["porridge", "hafer grutze gekocht"],
    "cola": ["colagetrank"], "fanta": ["orangenlimonade"], "limo": ["orangenlimonade", "zitronenlimonade"],
    "sprite": ["zitronenlimonade"], "quark": ["speisequark"], "magerquark": ["speisequark magerstufe"],
    "huttenkase": ["korniger frischkase"], "frischkase": ["frischkasezubereitung natur"],
    "hack": ["rind hackfleisch", "schwein hackfleisch"], "hackfleisch": ["rind hackfleisch", "schwein hackfleisch"],
    "rinderhack": ["rind hackfleisch"], "rinderhackfleisch": ["rind hackfleisch"], "schweinehack": ["schwein hackfleisch"],
    "schinken": ["schwein kochschinken kochpokelware"], "kochschinken": ["schwein kochschinken kochpokelware"],
    "hahnchenschenkel": ["hahnchen unterschenkel"], "hahnchenkeule": ["hahnchen unterschenkel"],
    "hahnchenbrust": ["hahnchen brustfilet"], "putenbrust": ["pute brust ohne haut"],
    "zwiebel": ["speisezwiebel"], "zwiebeln": ["speisezwiebel"], "kidneybohne": ["kidneybohne reif gekocht"],
    "kidneybohnen": ["kidneybohne reif gekocht"], "erbsen": ["erbse grun"], "bohnen": ["bohne grun"],
    "brokkoli": ["broccoli roh", "broccoli gekocht"], "pilze": ["champignon roh"], "champignons": ["champignon roh"],
    "salat": ["kopfsalat roh", "eisbergsalat roh"], "mohre": ["karotte"], "mohren": ["karotte"],
    "karotten": ["karotte"], "paprika": ["gemusepaprika"], "tomaten": ["tomate"],
    "semmel": ["brotchen"], "schrippe": ["brotchen"], "weckle": ["brotchen"],
    "brezel": ["laugengeback mit hagelsalz"], "breze": ["laugengeback mit hagelsalz"],
    "brezn": ["laugengeback mit hagelsalz"], "brezen": ["laugengeback mit hagelsalz"],
    "laugenbrezel": ["laugengeback mit hagelsalz"], "laugenstange": ["laugengeback mit hagelsalz"],
    "laugenbrotchen": ["laugengeback mit hagelsalz"], "laugensemmel": ["laugengeback mit hagelsalz"],
    "laugenweckle": ["laugengeback mit hagelsalz"],
    "toast": ["weizentoastbrot buttertoastbrot"], "toastbrot": ["weizentoastbrot buttertoastbrot"], "weissbrot": ["weizenbrot weissbrot"],
    "baguette": ["weizenbrot weissbrot"], "knackebrot": ["roggenvollkornknackebrot"],
    "brotchen": ["weizenbrotchen", "roggenbrotchen"], "brot": ["roggenmischbrot", "weizenmischbrot", "vollkornbrot"],
    "berliner": ["berliner krapfen"], "krapfen": ["berliner krapfen"], "keks": ["butterkekse"], "kekse": ["butterkekse"],
    "waffel": ["waffeln einfache"], "waffeln": ["waffeln einfache"], "eis": ["vanilleeis", "speiseeis"],
    "gummibarchen": ["fruchtgummi gummibonbon"], "gummibaren": ["fruchtgummi gummibonbon"], "chips": ["kartoffelchips stapelchips"],
    "walnusse": ["walnuss"], "mandeln": ["mandel suss"], "nusse": ["haselnuss", "walnuss", "mandel suss"],
    "o-saft": ["orangensaft"], "pommes": ["pommes frites"], "milch": ["vollmilch", "milch fettarm"],
    "kakao": ["milchmischgetrank kakao"], "cappuccino": ["cappuccino getrank milch"],
    "haferflocken": ["hafer flocken"], "spatzle": ["eierteigwaren gekocht", "eier-frischteigwaren spatzle"],
    "nudelsalat": ["salat aus eierteigwaren"], "sushi": ["sushi mit lachs", "sushi vegan"],
    "burger": ["hamburger", "cheeseburger"],
    "apfelschorle": ["fruchtsaftschorle apfel"], "wasser": ["mineralwasser", "trinkwasser"],
    "kase": ["schnittkase", "gouda", "emmentaler", "hartkase"],
    "bier": ["pils", "export hell", "weizenbier"], "weizen": ["hefeweizen weizenbier"],
    "weizenbier": ["hefeweizen weizenbier"], "wein": ["rotwein trocken", "weisswein trocken"],
    "rotwein": ["rotwein trocken"], "weisswein": ["weisswein trocken"], "schnaps": ["obstbrand", "wodka"],
    "joghurt": ["joghurt mild"],
    # häufige Rezept-Zutaten
    "mehl": ["weizen mehl type 405"], "weizenmehl": ["weizen mehl type 405"], "zucker": ["zucker weiss"],
    "salz": ["speisesalz"], "butter": ["butter mild gesauert"], "sahne": ["schlagsahne"],
    "rapskernol": ["rapsol"], "rapsol": ["rapsol"], "pflanzenol": ["rapsol"], "sonnenblumenol": ["sonnenblumenol"],
    "obstsaft": ["apfelsaft"], "saft": ["apfelsaft", "orangensaft"], "bruhe": ["gemusebruhe"],
    "creme fraiche": ["creme fraiche"], "gemuse": ["gemusemischung"], "fleisch": ["rind fleisch", "schwein fleisch"], "knoblauchzehe": ["knoblauch roh"], "knoblauchzehen": ["knoblauch roh"],
}
SYNONYM_BONUS = 25
EXACT_BONUS = 15
GROUP_PENALTY = {"V5": 12, "V6": 12, "U2": 12, "U4": 12, "U6": 12, "U8": 12, "R4": 8, "R5": 8}
_UML = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e", "è": "e"})
_cache = {"sig": None, "rows": []}


def _norm(s: str) -> str:
    return (s or "").lower().translate(_UML)


def _index(conn) -> list:
    sig = tuple(conn.execute("SELECT COUNT(*), MAX(updated) FROM foods").fetchone())
    if _cache["sig"] != sig:
        rows = []
        for r in conn.execute("SELECT id, source, code, name, brand, fav, hidden FROM foods"):
            name = _norm(r["name"])
            words = [w for w in re.split(r"[^a-z0-9-]+", name) if w]
            head = re.split(r"[,(]", name)[0]
            first = re.split(r"[^a-z0-9-]+", head.strip())[0] if head.strip() else ""
            rows.append((r["id"], name + " " + _norm(r["brand"]), words + _norm(r["brand"]).split(), first,
                         r["source"], (r["code"] or "")[:2], r["fav"], r["hidden"], name.strip()))
        _cache.update(sig=sig, rows=rows)
    return _cache["rows"]


def _token_score(t: str, words: list, first: str) -> int:
    if first == t:
        return 100
    if first.endswith(t) and len(t) >= 3:
        return 80
    if t in words:
        return 70
    if any(w.endswith(t) for w in words) and len(t) >= 3:
        return 50
    if first.startswith(t):
        return 30
    if any(w.startswith(t) for w in words):
        return 25
    return 10


def _score(tokens: list, text: str, words: list, first: str) -> float | None:
    total = 0
    for t in tokens:
        if t not in text:
            return None
        total += _token_score(t, words, first)
    return total / len(tokens)


def search(conn, q: str, limit: int = 40) -> list:
    """Suche über Name und Marke. Reihenfolge: Wortlogik (siehe oben), Favoriten,
    oft gegessen, eigene Lebensmittel, Rohzustand, kürzere Namen."""
    qn = _norm(q).strip()
    tokens = [t for t in re.split(r"[^a-z0-9-]+", qn) if t][:6]
    if not tokens:
        return []
    variants = [(tokens, 0)]
    if qn in SYNONYMS:
        variants += [(syn.split(), SYNONYM_BONUS) for syn in SYNONYMS[qn]]
    uses = dict(conn.execute("SELECT food_id, COUNT(*) FROM food_log WHERE food_id IS NOT NULL GROUP BY food_id")
                .fetchall())
    scored = []
    for fid, text, words, first, source, group, fav, hidden, name in _index(conn):
        if hidden:
            continue
        best = None
        for toks, bonus in variants:
            s = _score(toks, text, words, first)
            if s is None:
                continue
            if name == " ".join(toks):      # Name ist genau das Gesuchte („Hamburger“, „Honig“, „Tofu“)
                s += EXACT_BONUS
            if best is None or s + bonus > best:
                best = s + bonus
        if best is None:
            continue
        best += 60 * fav + min(uses.get(fid, 0), 20) * 3
        best += 6 if source in ("custom", "off", "recipe") else 0
        best += 3 if " roh" in text or "frisch" in text else 0
        best -= 6 if group[:1] in ("X", "Y") else 0
        best -= GROUP_PENALTY.get(group, 0)
        best -= len(text) / 12
        scored.append((best, fid))
    scored.sort(key=lambda x: -x[0])
    ids = [fid for _, fid in scored[:limit]]
    if not ids:
        return []
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT {FOOD_COLS} FROM foods WHERE id IN ({','.join('?' * len(ids))})", ids)}
    out = []
    for fid in ids:
        d = as_dict(rows[fid])
        d["uses"] = uses.get(fid, 0)
        out.append(d)
    return out


def get(conn, food_id: int) -> dict | None:
    row = conn.execute(f"SELECT {FOOD_COLS} FROM foods WHERE id = ?", (food_id,)).fetchone()
    return as_dict(row) if row else None


def recent(conn, limit: int = 15) -> list:
    """Zuletzt gegessen, je Lebensmittel mit der zuletzt gewählten Menge."""
    rows = conn.execute(
        f"SELECT {', '.join('f.' + c.strip() for c in FOOD_COLS.split(','))}, l.grams AS last_grams, "
        "l.portion AS last_portion, MAX(l.ts) AS last_ts "
        "FROM food_log l JOIN foods f ON f.id = l.food_id WHERE f.hidden = 0 "
        "GROUP BY l.food_id ORDER BY last_ts DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = as_dict({k: r[k] for k in r.keys() if not k.startswith("last_")})
        d.update(last_grams=r["last_grams"], last_portion=r["last_portion"])
        out.append(d)
    return out


def favorites(conn) -> list:
    return [as_dict(r) for r in conn.execute(
        f"SELECT {FOOD_COLS} FROM foods WHERE fav = 1 AND hidden = 0 ORDER BY name LIMIT 100")]


def custom(conn) -> list:
    return [as_dict(r) for r in conn.execute(
        f"SELECT {FOOD_COLS} FROM foods WHERE source IN ('custom', 'off', 'recipe') AND hidden = 0 "
        "ORDER BY source = 'recipe' DESC, updated DESC LIMIT 200")]


# ---------- Portionen ----------

# (Muster auf Name, BLS-Untergruppen oder None, [(Bezeichnung, Gramm)])
PORTION_RULES = [
    (r"^apfel( geschält)?,? roh", None, [("1 Apfel (mittel)", 150)]),
    (r"^birne roh", None, [("1 Birne (mittel)", 160)]),
    (r"^banane roh", None, [("1 Banane (ohne Schale)", 120)]),
    (r"^(orange|apfelsine) roh", None, [("1 Orange (ohne Schale)", 150)]),
    (r"^mandarine roh", None, [("1 Mandarine", 60)]),
    (r"^kiwi", None, [("1 Kiwi", 70)]),
    (r"^(pfirsich|nektarine) roh", None, [("1 Stück", 130)]),
    (r"^tomate roh", None, [("1 Tomate (mittel)", 90)]),
    (r"^(gurke|salatgurke) roh", None, [("¼ Gurke", 100)]),
    (r"^gemüsepaprika", None, [("1 Paprika", 160)]),
    (r"^karotte|^möhre", None, [("1 Karotte", 70)]),
    (r"^hühnerei.*(roh|gekocht)", None, [("1 Ei (M)", 55), ("2 Eier", 110)]),
    (r"brötchen|semmel|croissant", ("B4", "B5", "D9", "D4"), [("1 Stück", 60)]),
    (r"brezel|laugen", None, [("1 Brezel", 80), ("1 Laugenstange/-brötchen", 70)]),
    (r"knäcke", None, [("1 Scheibe", 10)]),
    (r"toast", ("B3", "B8"), [("1 Scheibe Toast", 25)]),
    (r"brot", ("B1", "B2", "B3", "B6", "B7", "B8"), [("1 Scheibe", 50), ("½ Scheibe", 25)]),
    (r"kartoffel.*(gekocht|gegart|pellkartoffel)|^kartoffel (geschält|ungeschält), roh", None, [("1 Kartoffel (mittel)", 80)]),
    (r"(reis|nudel|teigwaren|spätzle|couscous|bulgur|quinoa).*gekocht", None, [("1 Portion (gekocht)", 200)]),
    (r"(reis|teigwaren|nudel).*roh", ("C3", "E4", "E5", "E8"), [("1 Portion (roh)", 75)]),
    (r"haferflocken|hafer flocken|müsli|cornflakes", None, [("1 Portion", 50), ("1 EL", 10)]),
    (r"öl\b|öl$", ("Q1", "Q2", "Q3", "Q5", "Q9"), [("1 EL", 10), ("1 TL", 4)]),
    (r"butter|margarine|streichfett|schmalz", ("Q4", "Q6", "Q8"), [("1 TL", 5), ("1 Scheibe bestrichen", 10)]),
    (r"honig|zucker|konfitüre|marmelade|nuss-nougat", ("S1",), [("1 TL", 8), ("1 EL", 20)]),
    (r"milch|kakao|buttermilch|kefir|drink", ("M1", "C6", "H8"), [("1 Glas (200 ml)", 200), ("Schuss in Kaffee", 15)]),
    (r"joghurt|quark|skyr", ("M2", "M7"), [("1 Becher (150 g)", 150), ("1 EL", 20)]),
    (r"käse", ("M0", "M3", "M4", "M5", "M6"), [("1 Scheibe", 25), ("1 Würfel/Ecke", 30)]),
    (r"frischkäse", ("M7",), [("1 Portion aufs Brot", 20)]),
    (r"kaffee \(getränk\)|tee \(getränk\)|espresso", None, [("1 Tasse", 150), ("1 Becher", 250)]),
    (r"bier|radler|weizen|pils|export", ("P1",), [("0,33 l", 330), ("0,5 l", 500)]),
    (r"wein|sekt|prosecco", ("P2", "P3"), [("1 Glas (0,2 l)", 200), ("0,1 l", 100)]),
    (r"likör|schnaps|wodka|rum|whisk|brand|korn|gin", ("P5", "P6", "P7"), [("1 Schnapsglas (2 cl)", 20)]),
    (r"saft|schorle|limonade|cola|eistee|getränk", ("N0", "N2", "N3", "F6"), [("1 Glas (200 ml)", 200), ("0,33 l", 330), ("0,5 l", 500)]),
    (r"nuss|nüsse|mandel|pistazie|cashew|erdnuss|kerne", ("H1", "H2", "H3", "H4"), [("1 Handvoll", 25)]),
    (r"schokolade", ("S5", "S6"), [("1 Rippe", 5), ("1 Riegel", 50), ("½ Tafel", 50)]),
    (r"chips|flips", None, [("1 Handvoll", 20), ("½ Tüte", 75)]),
    (r"wurst|salami|schinken|aufschnitt|mortadella|lyoner", ("W1", "W2", "W3", "W4", "W5"), [("1 Scheibe", 15), ("3 Scheiben", 45)]),
    (r"wiener|bockwurst|bratwurst|frankfurter", None, [("1 Würstchen", 70), ("1 Bratwurst", 120)]),
    (r"", ("U0", "U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8", "V1", "V2", "V3", "V4", "T0", "T1", "T2", "T3", "T4",
           "T5", "T6", "Y1", "Y2", "Y3", "Y4", "Y5", "Y6"), [("1 Portion", 150)]),
    (r"kuchen|torte|strudel", ("D1", "D2", "D3", "D4", "D5"), [("1 Stück", 120)]),
    (r"keks|plätzchen|cookie", ("D6", "D7"), [("1 Keks", 10)]),
    (r"eis\b|eiscreme|speiseeis", ("S2", "Y9"), [("1 Kugel", 60)]),
    (r"suppe|eintopf|brühe", ("X4",), [("1 Teller", 300)]),
    (r"salat", ("X1", "X2", "G1"), [("1 Schale", 150)]),
    (r"pizza", None, [("1 Pizza", 350), ("1 Stück (⅛)", 45)]),
    (r"ketchup|senf|mayonnaise|dressing|soße|sauce", None, [("1 EL", 15), ("1 TL", 5)]),
]
_COMPILED = [(re.compile(p, re.I), groups, units) for p, groups, units in PORTION_RULES]


def portions_for(food: dict) -> list:
    """Eigene Portionen zuerst, dann Portion der Quelle, dann Regeln. Höchstens 4."""
    out = []
    own = food.get("portions")
    if isinstance(own, str):
        try:
            own = json.loads(own)
        except ValueError:
            own = []
    for p in own or []:
        try:
            out.append({"name": str(p["name"])[:30], "g": float(p["g"])})
        except (KeyError, TypeError, ValueError):
            continue
    if food.get("serving_g"):
        out.append({"name": f"1 Portion ({food['serving_g']:g} g)", "g": float(food["serving_g"])})
    name, code = food.get("name") or "", food.get("code") or ""
    is_bls = food.get("source") == "bls"
    for rx, groups, units in _COMPILED:
        name_hit = bool(rx.pattern) and bool(rx.search(name))
        group_hit = groups is not None and is_bls and code[:2] in groups
        if groups is None:
            hit = name_hit                              # nur Name
        elif rx.pattern:
            hit = name_hit and (group_hit or not is_bls)  # BLS: Name und Gruppe, sonst nur Name
        else:
            hit = group_hit                             # nur BLS-Gruppe
        if hit:
            out += [{"name": u, "g": g} for u, g in units]
            break
    seen, result = set(), []
    for p in out:
        if p["name"] not in seen and p["g"] > 0:
            seen.add(p["name"])
            result.append(p)
    return result[:4]


# ---------- Eigene Lebensmittel ----------

def clean_food(data: dict) -> dict:
    name = str(data.get("name") or "").strip()[:120]
    if not name:
        raise ValueError("Name fehlt")
    out = {"name": name, "brand": str(data.get("brand") or "").strip()[:80] or None}
    for k in db.NUTRIENTS:
        v = data.get(k)
        if v in (None, ""):
            out[k] = None if k != "kcal" else 0.0
            continue
        v = float(str(v).replace(",", "."))
        limit = 900 if k == "kcal" else 100
        if not 0 <= v <= limit:
            raise ValueError(f"{k} außerhalb 0–{limit}")
        out[k] = v
    code = re.sub(r"\D", "", str(data.get("code") or ""))[:14]
    out["code"] = code or None
    serving = data.get("serving_g")
    out["serving_g"] = max(1.0, min(float(serving), 5000.0)) if serving not in (None, "") else None
    return out


def create_custom(conn, data: dict) -> int:
    f = clean_food(data)
    now = db.iso(db.now_utc())
    if f["code"]:
        row = conn.execute("SELECT id FROM foods WHERE source = 'custom' AND code = ?", (f["code"],)).fetchone()
        if row:
            update_food(conn, row["id"], data)
            return row["id"]
    cur = conn.execute(
        "INSERT INTO foods (source, code, name, brand, kcal, protein, fat, satfat, carbs, sugar, fiber, alcohol, salt, "
        "serving_g, zero_auto, created, updated) VALUES ('custom', :code, :name, :brand, :kcal, :protein, :fat, :satfat, "
        ":carbs, :sugar, :fiber, :alcohol, :salt, :serving_g, 0, :now, :now)", {**f, "now": now})
    return cur.lastrowid


def update_food(conn, food_id: int, data: dict) -> None:
    row = conn.execute("SELECT source FROM foods WHERE id = ?", (food_id,)).fetchone()
    if not row:
        raise LookupError("unbekannt")
    now = db.iso(db.now_utc())
    if row["source"] == "custom" and "name" in data:
        f = clean_food(data)
        conn.execute(
            "UPDATE foods SET code = :code, name = :name, brand = :brand, kcal = :kcal, protein = :protein, fat = :fat, "
            "satfat = :satfat, carbs = :carbs, sugar = :sugar, fiber = :fiber, alcohol = :alcohol, salt = :salt, "
            "serving_g = :serving_g, updated = :now WHERE id = :id", {**f, "now": now, "id": food_id})
    if "fav" in data:
        conn.execute("UPDATE foods SET fav = ?, updated = ? WHERE id = ?", (1 if data["fav"] else 0, now, food_id))
    if "zero" in data:
        z = None if data["zero"] is None else (1 if data["zero"] else 0)
        conn.execute("UPDATE foods SET zero_user = ?, updated = ? WHERE id = ?", (z, now, food_id))
    if "portions" in data:
        ps = [{"name": str(p.get("name") or "").strip()[:30], "g": round(float(p.get("g") or 0), 1)}
              for p in list(data["portions"] or [])[:4] if isinstance(p, dict)]
        ps = [p for p in ps if p["name"] and 0 < p["g"] <= 5000]
        conn.execute("UPDATE foods SET portions = ?, updated = ? WHERE id = ?",
                     (json.dumps(ps, ensure_ascii=False), now, food_id))


def delete_food(conn, food_id: int) -> str:
    """Eigene Lebensmittel ohne Einträge werden gelöscht, alle anderen ausgeblendet."""
    row = conn.execute("SELECT source FROM foods WHERE id = ?", (food_id,)).fetchone()
    if not row:
        return "unbekannt"
    used = conn.execute("SELECT 1 FROM food_log WHERE food_id = ? LIMIT 1", (food_id,)).fetchone()
    if row["source"] in ("custom", "recipe") and not used:
        conn.execute("DELETE FROM foods WHERE id = ?", (food_id,))
        return "gelöscht"
    conn.execute("UPDATE foods SET hidden = 1, fav = 0, updated = ? WHERE id = ?", (db.iso(db.now_utc()), food_id))
    return "ausgeblendet"


# ---------- Open Food Facts ----------

_off_lock = threading.Lock()
_off_calls: list = []
OFF_PER_MINUTE = 10   # erlaubt sind 15/min, etwas Luft lassen


def _off_allowed() -> bool:
    with _off_lock:
        now = time.monotonic()
        while _off_calls and now - _off_calls[0] > 60:
            _off_calls.pop(0)
        if len(_off_calls) >= OFF_PER_MINUTE:
            return False
        _off_calls.append(now)
        return True


def off_map(product: dict) -> dict | None:
    """Open-Food-Facts-Produkt auf Nährwerte je 100 g abbilden. None, wenn keine kcal da sind."""
    n = product.get("nutriments") or {}

    def g(*keys):
        for k in keys:
            v = n.get(k)
            if v not in (None, ""):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None
    kcal = g("energy-kcal_100g")
    if kcal is None and g("energy_100g") is not None:
        kcal = g("energy_100g") / 4.184     # kJ -> kcal
    if kcal is None:
        return None
    alcohol = g("alcohol_100g")             # % vol
    name = (product.get("product_name_de") or product.get("product_name") or product.get("generic_name_de") or "").strip()
    serving = product.get("serving_quantity")
    try:
        serving = float(serving) if serving not in (None, "") else None
    except (TypeError, ValueError):
        serving = None
    return {
        "name": name[:120] or "Unbenanntes Produkt",
        "brand": (product.get("brands") or "").split(",")[0].strip()[:80] or None,
        "kcal": round(kcal, 1), "protein": g("proteins_100g"), "fat": g("fat_100g"),
        "satfat": g("saturated-fat_100g"), "carbs": g("carbohydrates_100g"), "sugar": g("sugars_100g"),
        "fiber": g("fiber_100g"), "salt": g("salt_100g"),
        "alcohol": round(alcohol * 0.789, 2) if alcohol else None,   # % vol -> g je 100 ml
        "serving_g": serving if serving and 0 < serving <= 5000 else None,
    }


def barcode(conn, code: str) -> dict:
    """Lokal suchen (eigene, dann Open-Food-Facts-Cache), sonst Open Food Facts fragen."""
    code = re.sub(r"\D", "", code)[:14]
    if len(code) < 6:
        return {"status": "invalid"}
    for src in ("custom", "off"):
        row = conn.execute(f"SELECT {FOOD_COLS} FROM foods WHERE source = ? AND code = ?", (src, code)).fetchone()
        if row:
            if row["hidden"]:
                conn.execute("UPDATE foods SET hidden = 0, updated = ? WHERE id = ?", (db.iso(db.now_utc()), row["id"]))
            return {"status": "found", "food": as_dict(row)}
    if not _off_allowed():
        return {"status": "busy"}
    ua = f"FitPath/{__version__}" + (f" ({OFF_CONTACT})" if OFF_CONTACT else "")
    try:
        r = httpx.get(OFF_URL.format(code=code), params={"fields": OFF_FIELDS},
                      headers={"User-Agent": ua}, timeout=8)
    except httpx.HTTPError as exc:
        print(f"Open Food Facts nicht erreichbar: {exc}", flush=True)
        return {"status": "offline"}
    if r.status_code == 404:
        return {"status": "unknown", "code": code}
    if r.status_code != 200:
        print(f"Open Food Facts {r.status_code}", flush=True)
        return {"status": "offline"}
    data = r.json()
    product = data.get("product") if data.get("status") in (1, "success", "success_with_warnings") else None
    mapped = off_map(product) if product else None
    if not mapped:
        return {"status": "unknown", "code": code, "name": (product or {}).get("product_name")}
    now = db.iso(db.now_utc())
    cur = conn.execute(
        "INSERT INTO foods (source, code, name, brand, kcal, protein, fat, satfat, carbs, sugar, fiber, alcohol, salt, "
        "serving_g, zero_auto, created, updated) VALUES ('off', :code, :name, :brand, :kcal, :protein, :fat, :satfat, "
        ":carbs, :sugar, :fiber, :alcohol, :salt, :serving_g, 0, :now, :now)", {**mapped, "code": code, "now": now})
    return {"status": "found", "food": get(conn, cur.lastrowid), "new": True}


# ---------- Gerichte (aus Zutaten) ----------

def _recipe_values(conn, data: dict) -> dict:
    """Nährwerte je 100 g aus Zutaten. Gewichtsbezug: Gesamtgewicht nach dem Kochen, wenn
    angegeben (Wasser verdampft oder kommt dazu), sonst Summe der Zutaten. Punkte je 100 g
    ohne 0-Punkte-Zutaten (Gemüse im Eintopf kostet nichts, wie beim einzelnen Erfassen)."""
    name = str(data.get("name") or "").strip()[:120]
    if not name:
        raise ValueError("Name fehlt")
    items = []
    for it in list(data.get("items") or [])[:60]:
        try:
            fid, grams = int(it.get("food_id")), float(str(it.get("grams")).replace(",", "."))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Zutat ungültig")
        if not 0 < grams <= 20000:
            raise ValueError("Menge je Zutat 1–20000 g")
        food = get(conn, fid)
        if not food or food.get("source") == "recipe":
            raise ValueError("Zutat unbekannt (Gerichte in Gerichten gehen nicht)")
        items.append((food, grams))
    if not items:
        raise ValueError("Mindestens eine Zutat")
    raw_total = sum(g for _, g in items)
    total = data.get("total_g")
    total = float(str(total).replace(",", ".")) if total not in (None, "") else None
    if total is not None and not raw_total * 0.2 <= total <= raw_total * 3:
        raise ValueError("Gesamtgewicht passt nicht zu den Zutaten")
    weight = total or raw_total
    servings = max(1, min(int(data.get("servings") or 1), 50))
    sums = {k: 0.0 for k in db.NUTRIENTS}
    pts = 0.0
    for food, grams in items:
        n = points.scale(food, grams)
        for k in db.NUTRIENTS:
            sums[k] += n[k]
        if not food["zero"]:
            pts += points.raw_points(n)
    out = {k: round(v / weight * 100, 3) for k, v in sums.items()}
    out.update(name=name, pts_100=round(pts / weight * 100, 4), serving_g=round(weight / servings, 1),
               recipe=json.dumps({"items": [{"food_id": f["id"], "name": f["name"], "grams": g} for f, g in items],
                                  "servings": servings, "total_g": total, "source_url": _source(data.get("source_url"))},
                                 ensure_ascii=False))
    return out


def _source(url) -> str | None:
    url = str(url or "").strip()[:300]
    return url if re.match(r"^https?://", url) else None


def save_recipe(conn, data: dict, food_id: int | None = None) -> int:
    v = _recipe_values(conn, data)
    now = db.iso(db.now_utc())
    if food_id:
        row = conn.execute("SELECT source FROM foods WHERE id = ?", (food_id,)).fetchone()
        if not row or row["source"] != "recipe":
            raise LookupError("unbekannt")
        conn.execute(
            "UPDATE foods SET name = :name, kcal = :kcal, protein = :protein, fat = :fat, satfat = :satfat, carbs = :carbs, "
            "sugar = :sugar, fiber = :fiber, alcohol = :alcohol, salt = :salt, pts_100 = :pts_100, serving_g = :serving_g, "
            "recipe = :recipe, hidden = 0, updated = :now WHERE id = :id", {**v, "now": now, "id": food_id})
        return food_id
    cur = conn.execute(
        "INSERT INTO foods (source, name, kcal, protein, fat, satfat, carbs, sugar, fiber, alcohol, salt, pts_100, serving_g, "
        "recipe, zero_auto, created, updated) VALUES ('recipe', :name, :kcal, :protein, :fat, :satfat, :carbs, :sugar, "
        ":fiber, :alcohol, :salt, :pts_100, :serving_g, :recipe, 0, :now, :now)", {**v, "now": now})
    return cur.lastrowid


def get_recipe(conn, food_id: int) -> dict | None:
    row = conn.execute(f"SELECT {FOOD_COLS}, recipe FROM foods WHERE id = ? AND source = 'recipe'", (food_id,)).fetchone()
    if not row:
        return None
    d = as_dict({k: row[k] for k in row.keys() if k != "recipe"})
    d["recipe"] = json.loads(row["recipe"] or "{}")
    return d
