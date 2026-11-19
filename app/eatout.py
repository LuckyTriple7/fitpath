"""Auswärts essen: fertige Teller in typischen Restaurant-Größen aus BLS-Bausteinen.

Offene Datenbanken mit Restaurant-Gerichten gibt es kaum, deshalb setzt FitPath die Teller
aus BLS-Codes zusammen (wo der BLS das ganze Gericht kennt, z. B. Döner Kebab oder Pizza,
direkt dieses). Gramm gelten für die normale Größe; klein = 75 %, groß = 130 %.

Restaurants kochen meist mit mehr Fett als die BLS-Rezepte. Pfannengerichte bekommen deshalb
einen Fettzuschlag (Rapsöl in Gramm), Gerichte aus der Fritteuse oder fertige Imbiss-Rezepte
des BLS nicht.

Die Teller landen beim Start als Lebensmittel mit `source = 'eatout'` in der Datenbank
(Schlüssel in `code`). Erfasste Einträge speichern ihre Nährwerte als Schnappschuss,
spätere Änderungen hier ändern alte Tage also nicht.
"""

import json

from . import db, points

OIL = "Q180000"          # Rapsöl
SIZES = (("klein", 0.75), ("normal", 1.0), ("groß", 1.3))
GROUPS = ("Imbiss", "Pizza", "Griechisch", "Deutsch", "Italienisch", "Asiatisch", "Salat")

# key, Gruppe, Name, [(BLS-Code, Gramm normal)], Fettzuschlag in g
PLATES = [
    # Imbiss
    ("doener", "Imbiss", "Döner Kebab (Kalb/Rind)", [("Y921062", 380)], 0),
    ("doener-huhn", "Imbiss", "Döner Kebab (Hähnchen)", [("Y921162", 380)], 0),
    ("doener-vegetarisch", "Imbiss", "Döner vegetarisch mit Schafskäse", [("Y9A1040", 380)], 0),
    ("doenerteller", "Imbiss", "Dönerteller mit Pommes, Salat und Tsatsiki",
     [("V422072", 200), ("X654042", 200), ("X201160", 100), ("X476512", 80)], 0),
    ("falafel-brot", "Imbiss", "Falafel im Fladenbrot", [("Y9A1060", 350)], 0),
    ("currywurst-pommes", "Imbiss", "Currywurst mit Pommes", [("Y944062", 450)], 0),
    ("currywurst-broetchen", "Imbiss", "Currywurst mit Brötchen", [("Y943062", 250)], 0),
    ("pommes-rot-weiss", "Imbiss", "Pommes rot-weiß (Ketchup und Mayo)",
     [("X654042", 200), ("R141100", 30), ("Q991000", 25)], 0),
    ("bratwurst-broetchen", "Imbiss", "Bratwurst im Brötchen mit Senf", [("Y942062", 200)], 0),
    ("burger-pommes", "Imbiss", "Burger mit Pommes", [("Y911360", 280), ("X654042", 150)], 0),
    ("fish-chips", "Imbiss", "Fish and Chips", [("Y693932", 450)], 0),
    ("backfisch-broetchen", "Imbiss", "Backfisch-Brötchen", [("Y610712", 200)], 0),
    ("leberkaese-broetchen", "Imbiss", "Leberkäse-Brötchen mit Senf",
     [("Y026022", 120), ("B511000", 60), ("R132000", 15)], 0),
    ("fruehlingsrollen", "Imbiss", "Frühlingsrollen (2 Stück)", [("X922143", 150)], 0),
    # Pizza (ganze Pizza, Ø etwa 30 cm)
    ("pizza-margherita", "Pizza", "Pizza Margherita", [("X912033", 450)], 0),
    ("pizza-salami", "Pizza", "Pizza Salami", [("X914133", 480)], 0),
    ("pizza-funghi", "Pizza", "Pizza Funghi", [("X912133", 460)], 0),
    ("pizza-prosciutto", "Pizza", "Pizza Prosciutto (Schinken)", [("X912412", 480)], 0),
    ("pizza-quattro-formaggi", "Pizza", "Pizza Quattro Formaggi", [("X912233", 420)], 0),
    # Griechisch
    ("gyros-pommes", "Griechisch", "Gyros mit Pommes, Tsatsiki und Krautsalat",
     [("Y384112", 200), ("X654042", 200), ("X476512", 80), ("X238310", 100)], 0),
    ("gyros-reis", "Griechisch", "Gyros mit Reis, Tsatsiki und Krautsalat",
     [("Y384112", 200), ("X821212", 200), ("X476512", 80), ("X238310", 100)], 0),
    ("tintenfisch", "Griechisch", "Tintenfischringe mit Tsatsiki und Pommes",
     [("Y686612", 250), ("X654042", 150)], 0),
    # Deutsch
    ("schnitzel-pommes", "Deutsch", "Schnitzel Wiener Art mit Pommes",
     [("Y332132", 200), ("X654042", 200)], 10),
    ("jaegerschnitzel", "Deutsch", "Jägerschnitzel mit Pommes", [("Y332532", 300), ("X654042", 200)], 10),
    ("schnitzel-bratkartoffeln", "Deutsch", "Schnitzel mit Bratkartoffeln",
     [("Y332132", 200), ("X651343", 250)], 10),
    ("schweinebraten", "Deutsch", "Schweinebraten mit Knödeln, Rotkohl und Soße",
     [("Y352212", 200), ("K241232", 240), ("U990100", 120), ("X537063", 150)], 0),
    ("steak-pommes", "Deutsch", "Rumpsteak mit Pommes und Kräuterbutter",
     [("Y184512", 250), ("X654042", 200), ("Q656000", 20)], 0),
    ("kaesespaetzle", "Deutsch", "Käsespätzle mit Röstzwiebeln", [("X711412", 450)], 15),
    ("bratwurst-kartoffelsalat", "Deutsch", "Bratwurst mit Kartoffelsalat", [("Y942132", 400)], 0),
    # Italienisch
    ("spaghetti-bolognese", "Italienisch", "Spaghetti Bolognese", [("X740433", 450)], 0),
    ("spaghetti-carbonara", "Italienisch", "Spaghetti Carbonara", [("X740733", 400)], 10),
    ("spaghetti-aglio", "Italienisch", "Spaghetti Aglio e Olio", [("X7A1020", 400)], 0),
    ("lasagne", "Italienisch", "Lasagne al forno", [("X730033", 400)], 0),
    # Asiatisch
    ("bami-goreng", "Asiatisch", "Gebratene Nudeln mit Hähnchen (Bami Goreng)", [("X891212", 450)], 15),
    ("nasi-goreng", "Asiatisch", "Gebratener Reis (Nasi Goreng)", [("X891133", 450)], 15),
    ("curry-reis", "Asiatisch", "Hähnchen-Curry mit Reis", [("Y569523", 300), ("C352032", 200)], 10),
    ("sushi", "Asiatisch", "Sushi mit Lachs (12 Stück)", [("Y627112", 300)], 0),
    # Salat
    ("salat-haehnchen", "Salat", "Salat mit gebratener Hähnchenbrust, Dressing und Brot",
     [("X201160", 250), ("Y562032", 150), ("X354040", 40), ("B511000", 50)], 0),
]


def plate_values(conn, items: list, oil: float) -> dict | None:
    """Nährwerte je 100 g, Gesamtgewicht und Rohpunkte je 100 g (ohne 0-Punkte-Bausteine)."""
    from . import foods            # spät importiert, damit eatout ohne Zyklus aus foods nutzbar bleibt
    parts = [(code, g) for code, g in items] + ([(OIL, oil)] if oil else [])
    sums = {k: 0.0 for k in db.NUTRIENTS}
    pts, total, used = 0.0, 0.0, []
    for code, grams in parts:
        row = conn.execute(f"SELECT {foods.FOOD_COLS} FROM foods WHERE source = 'bls' AND code = ?", (code,)).fetchone()
        if not row:
            return None
        food = foods.as_dict(row)
        n = points.scale(food, grams)
        for k in db.NUTRIENTS:
            sums[k] += n[k]
        if not food["zero"]:
            pts += points.raw_points(n)
        total += grams
        used.append({"food_id": food["id"], "code": code, "name": food["name"], "grams": grams,
                     "fat_extra": code == OIL and bool(oil)})
    out = {k: round(v / total * 100, 3) for k, v in sums.items()}
    out.update(total=total, pts_100=round(pts / total * 100, 4), items=used)
    return out


def sync(conn) -> int:
    """Teller anlegen oder aktualisieren. Nicht mehr definierte Teller werden ausgeblendet
    (erfasste Einträge bleiben gültig). Liefert die Anzahl der Teller."""
    now = db.iso(db.now_utc())
    keys = []
    for key, group, name, items, oil in PLATES:
        v = plate_values(conn, items, oil)
        if not v:
            print(f"Auswärts: BLS-Baustein für „{name}“ fehlt, übersprungen", flush=True)
            continue
        portions = [{"name": f"{label} ({round(v['total'] * f)} g)", "g": round(v["total"] * f)} for label, f in SIZES]
        recipe = {"group": group, "items": v["items"], "fat_extra_g": oil, "total_g": v["total"]}
        conn.execute(
            "INSERT INTO foods (source, code, name, brand, kcal, protein, fat, satfat, carbs, sugar, fiber, alcohol, salt, "
            "pts_100, portions, recipe, zero_auto, created, updated) VALUES ('eatout', :code, :name, :brand, :kcal, "
            ":protein, :fat, :satfat, :carbs, :sugar, :fiber, :alcohol, :salt, :pts_100, :portions, :recipe, 0, :now, :now) "
            "ON CONFLICT(source, code) WHERE code IS NOT NULL DO UPDATE SET name = excluded.name, brand = excluded.brand, "
            "kcal = excluded.kcal, protein = excluded.protein, fat = excluded.fat, satfat = excluded.satfat, "
            "carbs = excluded.carbs, sugar = excluded.sugar, fiber = excluded.fiber, alcohol = excluded.alcohol, "
            "salt = excluded.salt, pts_100 = excluded.pts_100, portions = excluded.portions, recipe = excluded.recipe, "
            "hidden = 0, updated = excluded.updated",   # Teller lassen sich in der App nicht ausblenden
            {**{k: v[k] for k in db.NUTRIENTS}, "code": key, "name": name, "brand": f"Auswärts · {group}",
             "pts_100": v["pts_100"], "portions": json.dumps(portions, ensure_ascii=False),
             "recipe": json.dumps(recipe, ensure_ascii=False), "now": now})
        keys.append(key)
    marks = ",".join("?" * len(keys)) or "''"
    conn.execute(f"UPDATE foods SET hidden = 1 WHERE source = 'eatout' AND code NOT IN ({marks})", keys)
    return len(keys)


def plates(conn) -> list:
    """Alle Teller für die Auswahl, nach Gruppe sortiert, mit kcal und Punkten der normalen Größe."""
    from . import foods
    rows = conn.execute(f"SELECT {foods.FOOD_COLS}, recipe FROM foods WHERE source = 'eatout' AND hidden = 0").fetchall()
    out = []
    for r in rows:
        d = foods.as_dict({k: r[k] for k in r.keys() if k != "recipe"})
        rec = json.loads(r["recipe"] or "{}")
        g = float(rec.get("total_g") or 0)
        d.update(group=rec.get("group", ""), normal_g=g, normal_kcal=round((d["kcal"] or 0) * g / 100),
                 normal_points=points.round_points((d.get("pts_100") or 0) * g / 100))
        out.append(d)
    order = {grp: i for i, grp in enumerate(GROUPS)}
    return sorted(out, key=lambda x: (order.get(x["group"], 99), x["name"]))


def recipe_of(conn, food_id: int) -> dict | None:
    row = conn.execute("SELECT recipe FROM foods WHERE id = ? AND source = 'eatout'", (food_id,)).fetchone()
    return json.loads(row["recipe"] or "{}") if row else None
