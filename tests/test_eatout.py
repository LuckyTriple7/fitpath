"""Auswärts essen: Teller aus BLS-Bausteinen."""

from app import db, eatout, foods
from tests.test_api import H, client


def test_all_plates_built_with_sizes():
    c = client()
    plates = c.get("/api/foods/lists").json()["eatout"]
    assert len(plates) == len(eatout.PLATES)                  # jeder BLS-Code existiert
    groups = [p["group"] for p in plates]
    assert groups == sorted(groups, key=eatout.GROUPS.index)  # nach Gruppe sortiert
    for p in plates:
        names = [x["name"].split(" ")[0] for x in p["portions"]]
        assert names[:3] == ["klein", "normal", "groß"], p["name"]
        assert p["portions"][1]["g"] == round(p["normal_g"])
        assert 300 <= p["normal_kcal"] <= 1600, (p["name"], p["normal_kcal"])
    c.__exit__(None, None, None)


def test_plate_details_and_fat_extra():
    c = client()
    plates = {p["name"]: p for p in c.get("/api/foods/lists").json()["eatout"]}
    schnitzel = c.get(f"/api/foods/{plates['Schnitzel Wiener Art mit Pommes']['id']}").json()
    parts = schnitzel["eatout"]["items"]
    assert any(it["fat_extra"] and it["grams"] == 10 for it in parts)          # Pfannengericht mit Fettzuschlag
    doener = c.get(f"/api/foods/{plates['Döner Kebab (Kalb/Rind)']['id']}").json()
    assert not any(it["fat_extra"] for it in doener["eatout"]["items"])         # fertiges BLS-Gericht ohne
    c.__exit__(None, None, None)


def test_zero_point_parts_do_not_count():
    with db.connect() as conn:
        v = eatout.plate_values(conn, [("X201160", 250)], 0)            # nur gemischter Salat
        salad_zero = foods.as_dict(conn.execute(f"SELECT {foods.FOOD_COLS} FROM foods WHERE source = 'bls' AND code = 'X201160'").fetchone())["zero"]
    assert v["kcal"] > 0
    assert (v["pts_100"] == 0) is salad_zero


def test_search_finds_plate_and_log_entry():
    c = client()
    hits = c.get("/api/foods/search?q=Döner").json()
    assert hits[0]["source"] == "eatout"
    plate = hits[0]
    normal = plate["portions"][1]
    r = c.post("/api/log", headers=H, json={"food_id": plate["id"], "grams": normal["g"], "portion": normal["name"], "meal": "abend"})
    assert r.status_code == 200
    e = next(x for x in r.json()["overview"]["entries"] if x["food_id"] == plate["id"])
    assert e["points"] == round(plate["pts_100"] * normal["g"] / 100 + 1e-9)
    c.__exit__(None, None, None)


def test_plates_not_usable_as_ingredient():
    c = client()
    plate = c.get("/api/foods/lists").json()["eatout"][0]
    r = c.post("/api/recipes", headers=H, json={"name": "Test", "items": [{"food_id": plate["id"], "grams": 100}]})
    assert r.status_code == 400
    c.__exit__(None, None, None)


def test_removed_plate_is_hidden(monkeypatch):
    key = eatout.PLATES[0][0]
    hidden = lambda conn: conn.execute("SELECT hidden FROM foods WHERE source = 'eatout' AND code = ?", (key,)).fetchone()[0]
    with db.connect() as conn:
        monkeypatch.setattr(eatout, "PLATES", eatout.PLATES[1:])
        eatout.sync(conn)
        assert hidden(conn) == 1                      # nicht mehr definiert: ausgeblendet
        monkeypatch.undo()
        eatout.sync(conn)
        assert hidden(conn) == 0                      # wieder definiert: wieder sichtbar
