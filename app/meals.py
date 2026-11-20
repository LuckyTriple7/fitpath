"""Gespeicherte Mahlzeiten: feste Kombinationen („Mein Frühstück“: Brot, Butter, Käse, Kaffee) mit einem Tipp erfassen.

Gespeichert werden nur Lebensmittel, Menge und Portion. Die Nährwerte kommen beim Erfassen frisch aus der
Datenbank, wie bei jedem anderen Eintrag. Gleicher Name (ohne Groß/klein) ersetzt eine vorhandene Mahlzeit,
so lässt sich eine Mahlzeit ergänzen: auf Heute anpassen und unter demselben Namen neu merken.
"""

import json
import uuid

from . import db, diary, foods, points

MAX_ITEMS = 30
MAX_TEMPLATES = 50


def clean(conn, data: dict) -> dict:
    name = " ".join(str(data.get("name") or "").split())[:60]
    if not name:
        raise ValueError("Name fehlt")
    meal = data.get("meal") if data.get("meal") in diary.MEALS else None
    items = []
    for it in list(data.get("items") or [])[:MAX_ITEMS]:
        try:
            fid, grams = int(it.get("food_id")), float(str(it.get("grams")).replace(",", "."))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Eintrag ungültig") from None
        if not 0 < grams <= 5000:
            raise ValueError("Menge 1–5000 g")
        if not foods.get(conn, fid):
            raise ValueError("Lebensmittel unbekannt")
        portion = " ".join(str(it.get("portion") or "").split())[:40] or None
        items.append({"food_id": fid, "grams": round(grams, 1), "portion": portion})
    if not items:
        raise ValueError("Mindestens ein Lebensmittel")
    return {"name": name, "meal": meal, "items": items}


def _out(conn, row) -> dict:
    items, pts, kcal, protein, grams = [], 0, 0.0, 0.0, 0.0
    for it in json.loads(row["items"]):
        f = foods.get(conn, it["food_id"])
        if not f:                      # Lebensmittel inzwischen gelöscht
            continue
        n = points.scale(f, it["grams"])
        e = {**n, "zero": f["zero"], "grams": it["grams"],
             "points_raw": f["pts_100"] * it["grams"] / 100 if f.get("pts_100") is not None else None}
        p = points.entry_points(e)
        items.append({**it, "name": f["name"] + (f" ({f['brand']})" if f.get("brand") else ""), "points": p,
                      "kcal": round(n["kcal"]), "ampel": f["ampel"]})
        pts += p
        kcal += n["kcal"]
        protein += n["protein"] or 0
        grams += it["grams"]
    return {"id": row["id"], "name": row["name"], "meal": row["meal"], "uses": row["uses"],
            "items": items, "points": pts, "kcal": round(kcal), "protein": round(protein, 1),
            "ampel": points.ampel(kcal / grams * 100 if grams else 0)}


def list_all(conn) -> list:
    return [_out(conn, r) for r in conn.execute(
        "SELECT * FROM meal_templates ORDER BY uses DESC, last_used DESC, name LIMIT ?", (MAX_TEMPLATES,))]


def get(conn, tid: str) -> dict | None:
    row = conn.execute("SELECT * FROM meal_templates WHERE id = ?", (tid,)).fetchone()
    return _out(conn, row) if row else None


def save(conn, data: dict, tid: str | None = None) -> str:
    v = clean(conn, data)
    now = db.iso(db.now_utc())
    if tid is None:
        same = conn.execute("SELECT id FROM meal_templates WHERE lower(name) = lower(?)", (v["name"],)).fetchone()
        tid = same["id"] if same else None
    if tid is None:
        if conn.execute("SELECT COUNT(*) FROM meal_templates").fetchone()[0] >= MAX_TEMPLATES:
            raise ValueError(f"Höchstens {MAX_TEMPLATES} Mahlzeiten")
        tid = str(uuid.uuid4())
        conn.execute("INSERT INTO meal_templates (id, name, meal, items, created, updated) VALUES (?, ?, ?, ?, ?, ?)",
                     (tid, v["name"], v["meal"], json.dumps(v["items"]), now, now))
    else:
        n = conn.execute("UPDATE meal_templates SET name = ?, meal = ?, items = ?, updated = ? WHERE id = ?",
                         (v["name"], v["meal"], json.dumps(v["items"]), now, tid)).rowcount
        if not n:
            raise LookupError("Mahlzeit nicht gefunden")
    return tid


def delete(conn, tid: str) -> bool:
    return conn.execute("DELETE FROM meal_templates WHERE id = ?", (tid,)).rowcount > 0


def fit_candidates(conn, templates: list | None = None) -> list:
    """Kandidaten für „Was passt noch?“: nur eigene Sachen (Favoriten, zuletzt Gegessenes, gespeicherte
    Mahlzeiten), jeweils in der üblichen Menge. Was davon in die übrigen Punkte passt und wie es sortiert
    wird, entscheidet die Oberfläche (sie kennt die Anzeige Punkte/kcal). Fehlt ein 0-Punkte-Lebensmittel,
    kommt ein Apfel dazu."""
    recent = foods.recent(conn, 30)
    last = {f["id"]: f for f in recent}
    out, seen = [], set()
    for f in foods.favorites(conn) + recent:
        if f["id"] in seen:
            continue
        seen.add(f["id"])
        r = last.get(f["id"])
        if r:
            grams, portion = r["last_grams"], r["last_portion"]
        elif f["portions"]:
            grams, portion = f["portions"][0]["g"], f["portions"][0]["name"]
        else:
            continue                   # Favorit ohne Portion und nie gegessen: keine sinnvolle Menge
        out.append(_candidate(f, grams, portion))
    if not any(c["zero"] for c in out):
        apple = next((f for f in foods.search(conn, "apfel", 5) if f["zero"] and f["portions"]), None)
        if apple:
            out.append(_candidate(apple, apple["portions"][0]["g"], apple["portions"][0]["name"]))
    for t in templates if templates is not None else list_all(conn):
        if t["items"]:
            out.append({"kind": "tpl", "id": t["id"], "name": t["name"], "points": t["points"], "kcal": t["kcal"],
                        "protein": t["protein"], "ampel": t["ampel"], "zero": False, "fav": True})
    return out


def _candidate(f: dict, grams: float, portion: str | None) -> dict:
    n = points.scale(f, grams)
    e = {**n, "zero": f["zero"], "points_raw": f["pts_100"] * grams / 100 if f.get("pts_100") is not None else None}
    return {"kind": "food", "id": f["id"], "name": f["name"], "grams": grams, "portion": portion,
            "points": points.entry_points(e), "kcal": round(n["kcal"]), "protein": round(n["protein"] or 0, 1),
            "ampel": f["ampel"], "zero": f["zero"], "fav": bool(f.get("fav"))}


def items_for_log(conn, tid: str, skip=()) -> list:
    """Einträge der Mahlzeit (ohne die übersprungenen Positionen) und Nutzung zählen."""
    row = conn.execute("SELECT items FROM meal_templates WHERE id = ?", (tid,)).fetchone()
    if not row:
        raise LookupError("Mahlzeit nicht gefunden")
    skip = {int(i) for i in skip if str(i).lstrip("-").isdigit()}
    items = [it for i, it in enumerate(json.loads(row["items"])) if i not in skip and foods.get(conn, it["food_id"])]
    if items:
        conn.execute("UPDATE meal_templates SET uses = uses + 1, last_used = ? WHERE id = ?", (db.iso(db.now_utc()), tid))
    return items
