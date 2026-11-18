"""Lieber-Tausch: Alternativen bei Heißhunger auf etwas Bestimmtes.

Feste Liste je Gelüst, alle Lebensmittel aus dem BLS 4.0 (Code), Punkte und kcal
werden aus der Datenbank berechnet. Dazu je Gelüst eine kleine „bewusst genießen“-
Menge des Originals: Ein geplanter Genuss im Budget ist besser als ein Verbot, das
später in einen Fressanfall kippt.

Reihenfolge: Tausche, die schon oft gewählt wurden, rutschen nach oben (gezählt aus
den Heißhunger-Ereignissen mit `food` und `swap`).
"""

from . import foods, points

# parts: (BLS-Code, Gramm, Portionstext)
CRAVINGS = [
    {"key": "schokolade", "emoji": "🍫", "label": "Schokolade", "search": "Schokolade",
     "treat": {"name": "4 Stück Vollmilchschokolade", "parts": [("S539900", 25, "4 Stück")]},
     "swaps": [
         {"key": "bitter", "name": "2 Stück Bitterschokolade", "tip": "Langsam im Mund schmelzen lassen – kräftiger Geschmack, kleine Menge reicht.",
          "parts": [("S570000", 10, "2 Stück")]},
         {"key": "schokoquark", "name": "Schoko-Quark", "tip": "Magerquark mit 1 TL Kakao und Süßstoff verrühren – macht lange satt.",
          "parts": [("M713100", 150, None), ("S713000", 5, "1 TL")]},
         {"key": "kakao", "name": "Heißer Kakao", "tip": "Milch 1,5 % mit 1 TL Kakao und Süßstoff – warm, süß und braucht Zeit.",
          "parts": [("M111200", 200, "1 Becher"), ("S713000", 5, "1 TL")]},
         {"key": "banane-kakao", "name": "Banane mit Kakao", "tip": "Banane in Scheiben, mit etwas Kakao bestäubt.",
          "parts": [("F503100", 120, "1 Banane"), ("S713000", 3, None)]},
     ]},
    {"key": "chips", "emoji": "🥔", "label": "Chips", "search": "Chips",
     "treat": {"name": "Kleine Schale Chips", "parts": [("K280100", 25, "1 Handvoll")]},
     "swaps": [
         {"key": "gemuese-dip", "name": "Gemüsesticks mit Kräuterquark", "tip": "Gurke und Kohlrabi in Stifte, dazu Kräuterquark – knackig und salzig.",
          "parts": [("G520100", 150, None), ("G331100", 100, None), ("Y771510", 50, None)]},
         {"key": "popcorn", "name": "Popcorn ungesüßt", "tip": "Große Schüssel für wenig Punkte – selbst gemacht, leicht gesalzen.",
          "parts": [("C533000", 20, "1 Schüssel")]},
         {"key": "edamame", "name": "Edamame", "tip": "Mit grobem Salz – herzhaft, viel Eiweiß.",
          "parts": [("X574512", 100, "1 Schale")]},
         {"key": "gewuerzgurke", "name": "Gewürzgurken", "tip": "Sauer und salzig – stillt die Lust auf Herzhaftes.",
          "parts": [("G520802", 100, "2 Gurken")]},
     ]},
    {"key": "eis", "emoji": "🍦", "label": "Eis", "search": "Speiseeis",
     "treat": {"name": "1 Kugel Eis", "parts": [("S243000", 60, "1 Kugel")]},
     "swaps": [
         {"key": "nicecream", "name": "Bananen-Eis", "tip": "Gefrorene Banane pürieren – cremig wie Softeis.",
          "parts": [("F503100", 120, "1 Banane")]},
         {"key": "joghurt-beeren", "name": "Joghurt mit TK-Beeren", "tip": "Gefrorene Heidelbeeren in Joghurt rühren, kurz warten – wird fest wie Frozen Yogurt.",
          "parts": [("M141200", 150, None), ("F304100", 100, None)]},
         {"key": "skyr-erdbeer", "name": "Skyr mit Erdbeeren", "tip": "Aus dem Kühlschrank, mit Süßstoff – kalt und süß.",
          "parts": [("M710100", 150, None), ("F301100", 100, None)]},
         {"key": "sorbet", "name": "1 Kugel Sorbet", "tip": "Wenn's Eisdiele sein muss: Fruchtsorbet statt Sahneeis.",
          "parts": [("S201000", 60, "1 Kugel")]},
     ]},
    {"key": "gummi", "emoji": "🍬", "label": "Gummibärchen", "search": "Fruchtgummi",
     "treat": {"name": "Kleine Handvoll Gummibärchen", "parts": [("S361000", 20, "1 Handvoll")]},
     "swaps": [
         {"key": "trauben-tk", "name": "Gefrorene Weintrauben", "tip": "Im Tiefkühler – kalt, süß, zum Lutschen.",
          "parts": [("F310100", 150, None)]},
         {"key": "erdbeeren", "name": "Erdbeeren", "tip": "Eine Schale – süß und 0 Punkte.",
          "parts": [("F301100", 200, "1 Schale")]},
         {"key": "zuckerfrei", "name": "Fruchtgummi zuckerfrei", "tip": "Kleine Menge – größere Mengen können auf den Bauch schlagen.",
          "parts": [("S342000", 20, "1 Handvoll")]},
     ]},
    {"key": "kekse", "emoji": "🍪", "label": "Kekse", "search": "Kekse",
     "treat": {"name": "4 Butterkekse", "parts": [("D630400", 20, "4 Kekse")]},
     "swaps": [
         {"key": "apfel-quark", "name": "Quark mit Apfelmus", "tip": "Magerquark mit 2 EL ungesüßtem Apfelmus und Zimt – wie Kuchenfüllung.",
          "parts": [("M713100", 100, None), ("Y864112", 40, "2 EL")]},
         {"key": "reiswaffel", "name": "1 Schoko-Reiswaffel", "tip": "Knusprig und süß, aber leicht.",
          "parts": [("C532900", 13, "1 Waffel")]},
         {"key": "apfel", "name": "Apfel mit Zimt", "tip": "In Spalten, mit Zimt – 0 Punkte.",
          "parts": [("F110100", 150, "1 Apfel")]},
     ]},
    {"key": "limo", "emoji": "🥤", "label": "Cola/Limo", "search": "Cola",
     "treat": {"name": "1 kleines Glas Cola", "parts": [("N330000", 200, "1 Glas")]},
     "swaps": [
         {"key": "cola-zero", "name": "Cola mit Süßungsmitteln", "tip": "Gleicher Geschmack, 0 Punkte.",
          "parts": [("N331000", 330, "1 Dose")]},
         {"key": "tee", "name": "Tee", "tip": "Grüner oder Früchtetee, warm oder als Eistee ohne Zucker.",
          "parts": [("N610100", 300, "1 Becher")]},
         {"key": "sprudel", "name": "Sprudel mit Zitrone und Minze", "tip": "Eiskalt, mit Zitronenscheibe und Minze – spritzig wie Limo.",
          "parts": [("N110000", 400, "1 großes Glas")]},
     ]},
]

KEYS = {c["key"] for c in CRAVINGS}
TREAT = "genuss"    # swap-Wert, wenn das Original bewusst genossen wurde


def _resolve(conn, parts) -> dict | None:
    """Teile auflösen: Lebensmittel aus der Datenbank, Punkte je Teil gerundet (wie im Tagebuch)."""
    out, pts, kcal = [], 0, 0.0
    for code, grams, portion in parts:
        row = conn.execute(f"SELECT {foods.FOOD_COLS} FROM foods WHERE source = 'bls' AND code = ?", (code,)).fetchone()
        if not row:
            return None
        f = foods.as_dict(row)
        n = points.scale(f, grams)
        p = 0 if f["zero"] else points.round_points(points.raw_points(n))
        out.append({"food_id": f["id"], "name": f["name"], "grams": grams, "portion": portion, "points": p,
                    "kcal": round(n["kcal"])})
        pts += p
        kcal += n["kcal"]
    return {"parts": out, "points": pts, "kcal": round(kcal)}


def _uses(conn) -> dict:
    rows = conn.execute("SELECT food, swap, COUNT(*) FROM events WHERE kind = 'craving' AND food IS NOT NULL "
                        "AND swap IS NOT NULL GROUP BY food, swap").fetchall()
    return {(f, s): n for f, s, n in rows}


def catalog(conn) -> list:
    uses = _uses(conn)
    result = []
    for c in CRAVINGS:
        treat = _resolve(conn, c["treat"]["parts"])
        swaps = []
        for i, s in enumerate(c["swaps"]):
            r = _resolve(conn, s["parts"])
            if r:
                swaps.append({"key": s["key"], "name": s["name"], "tip": s["tip"], "uses": uses.get((c["key"], s["key"]), 0),
                              "_i": i, **r})
        swaps.sort(key=lambda x: (-x["uses"], x["_i"]))
        for s in swaps:
            del s["_i"]
        result.append({"key": c["key"], "emoji": c["emoji"], "label": c["label"], "search": c["search"],
                       "treat": {"name": c["treat"]["name"], **treat} if treat else None, "swaps": swaps})
    return result
