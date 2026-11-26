"""Gerichte aus Zutaten, „Wie gestern“ und Erfassen per Text (KI-Antwort simuliert)."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import ai, auth, db, main, points

H = {"x-fitpath": "1"}


def client():
    c = TestClient(main.app)
    c.__enter__()
    with db.connect() as conn:
        url = auth.create_link(conn, "Test")
    path = url.replace("http://testserver", "")
    assert c.post(path, follow_redirects=False).status_code == 303
    if not c.get("/api/state").json()["settings"]["onboarded"]:
        c.post("/api/onboarding", headers=H, json={"settings": {"start_weight": 95, "goal_weight": 85}})
    return c


def food(c, q, name=None):
    hits = c.get("/api/foods/search", params={"q": q}).json()
    return next(h for h in hits if h["name"] == name) if name else hits[0]


def test_recipe_zero_ingredients_and_logging():
    c = client()
    hack = food(c, "hackfleisch", "Schwein Hackfleisch, roh")
    tomate = food(c, "tomate", "Tomate roh")
    assert tomate["zero"] and not hack["zero"]
    body = {"name": "Testgericht", "servings": 4, "items": [
        {"food_id": hack["id"], "grams": 400}, {"food_id": tomate["id"], "grams": 600}]}
    r = c.post("/api/recipes", headers=H, json=body)
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["source"] == "recipe" and rec["recipe"]["servings"] == 4
    assert rec["portions"][0]["g"] == 250                       # 1000 g / 4 Portionen
    # Punkte nur aus dem Hackfleisch, kcal aus beidem
    pts_hack = points.raw_points(points.scale(hack, 400))
    assert abs(rec["pts_100"] - pts_hack / 1000 * 100) < 0.01
    kcal_all = (hack["kcal"] * 4 + tomate["kcal"] * 6) / 10
    assert abs(rec["kcal"] - kcal_all) < 0.1

    st = c.post("/api/log", headers=H, json={"id": "r1", "food_id": rec["id"], "grams": 250, "meal": "abend"}).json()
    e = next(x for x in st["overview"]["entries"] if x["id"] == "r1")
    assert e["points"] == points.round_points(pts_hack / 4)
    assert abs(e["kcal"] - kcal_all * 2.5) < 0.5

    # Gericht mit Gesamtgewicht nach dem Kochen (Wasser verdampft)
    r = c.put(f"/api/recipes/{rec['id']}", headers=H, json={**body, "total_g": 800})
    assert r.json()["portions"][0]["g"] == 200
    assert c.post("/api/recipes", headers=H, json={**body, "total_g": 50}).status_code == 400
    assert c.post("/api/recipes", headers=H, json={"name": "Leer", "items": []}).status_code == 400
    # Gericht taucht in Suche und unter „Eigene“ auf
    assert any(h["id"] == rec["id"] for h in c.get("/api/foods/search", params={"q": "testgericht"}).json())
    assert c.get("/api/foods/lists").json()["custom"][0]["source"] == "recipe"
    c.__exit__(None, None, None)


def test_copy_yesterday():
    c = client()
    today = c.get("/api/state").json()["today"]
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    brot = food(c, "roggenvollkornbrot")
    c.post("/api/log", headers=H, json={"id": "y1", "food_id": brot["id"], "grams": 100, "meal": "fruehstueck", "day": yesterday})
    st = c.get("/api/state").json()
    assert st["overview"]["prev"]["fruehstueck"]["count"] >= 1
    before = len([e for e in st["overview"]["entries"] if e["meal"] == "fruehstueck"])
    st = c.post("/api/log/copy", headers=H, json={"from": yesterday, "to": today, "meal": "fruehstueck"}).json()
    after = len([e for e in st["overview"]["entries"] if e["meal"] == "fruehstueck"])
    assert after == before + st["overview"]["prev"]["fruehstueck"]["count"]
    # Nur ausgewählte Einträge übernehmen (im Fenster mit ✕ rausgenommen)
    c.post("/api/log", headers=H, json={"id": "y2", "food_id": brot["id"], "grams": 50, "meal": "mittag", "day": yesterday})
    c.post("/api/log", headers=H, json={"id": "y3", "food_id": brot["id"], "grams": 70, "meal": "mittag", "day": yesterday})
    items = c.get("/api/state").json()["overview"]["prev"]["mittag"]["items"]
    assert {i["id"] for i in items} >= {"y2", "y3"} and items[0]["grams"] and "points" in items[0]
    st = c.post("/api/log/copy", headers=H, json={"from": yesterday, "to": today, "meal": "mittag", "ids": ["y3"]}).json()
    lunch = [e for e in st["overview"]["entries"] if e["meal"] == "mittag"]
    assert [e["grams"] for e in lunch] == [70]
    c.__exit__(None, None, None)


def test_copy_any_day_and_move():
    c = client()
    today = c.get("/api/state").json()["today"]
    d = date.fromisoformat(today)
    old, other = (d - timedelta(days=5)).isoformat(), (d - timedelta(days=3)).isoformat()
    brot = food(c, "roggenvollkornbrot")
    try:
        c.post("/api/log", headers=H, json={"id": "m1", "food_id": brot["id"], "grams": 80, "meal": "abend", "day": old})
        c.post("/api/log", headers=H, json={"id": "m2", "food_id": brot["id"], "grams": 40, "meal": "snack", "day": old})
        # Tagesliste fürs Übernehmen-Fenster
        got = c.get("/api/log", params={"day": old}).json()
        assert got["day"] == old and {e["id"] for e in got["entries"]} >= {"m1", "m2"}
        assert all("points" in e and "ampel" in e for e in got["entries"])
        assert c.get("/api/log", params={"day": "kaputt"}).status_code == 400
        # Reste vom Abend in ein anderes Mittag
        st = c.post("/api/log/copy", headers=H, json={"from": old, "to": other, "meal": "abend", "to_meal": "mittag"}).json()
        assert st["overview"]["day"] == other
        assert [(e["meal"], e["grams"]) for e in st["overview"]["entries"]] == [("mittag", 80)]
        # Ganzer Tag: Mahlzeiten bleiben, to_meal ohne meal wird ignoriert
        c.post("/api/log/copy", headers=H, json={"from": old, "to": other, "to_meal": "mittag"})
        meals = sorted(e["meal"] for e in c.get("/api/log", params={"day": other}).json()["entries"])
        assert meals == ["abend", "mittag", "snack"]
        # Nicht in die Zukunft
        future = (d + timedelta(days=1)).isoformat()
        assert c.post("/api/log/copy", headers=H, json={"from": old, "to": future}).status_code == 400
        # Verschieben: gleiche id mit anderem Tag und anderer Mahlzeit
        st = c.post("/api/log", headers=H, json={"id": "m2", "food_id": brot["id"], "grams": 40, "meal": "fruehstueck", "day": other}).json()
        assert st["overview"]["day"] == other
        assert "m2" not in {e["id"] for e in c.get("/api/log", params={"day": old}).json()["entries"]}
        assert any(e["id"] == "m2" and e["meal"] == "fruehstueck" for e in st["overview"]["entries"])
    finally:
        with db.connect() as conn:
            conn.execute("DELETE FROM food_log WHERE day IN (?, ?)", (old, other))
        c.__exit__(None, None, None)


def test_recipe_half_servings():
    c = client()
    hack = food(c, "hackfleisch", "Schwein Hackfleisch, roh")
    body = {"name": "Halbgericht", "servings": 2.5, "items": [{"food_id": hack["id"], "grams": 500}]}
    rec = c.post("/api/recipes", headers=H, json=body).json()
    assert rec["recipe"]["servings"] == 2.5 and rec["portions"][0]["g"] == 200
    rec = c.post("/api/recipes", headers=H, json={**body, "servings": 0.2}).json()
    assert rec["recipe"]["servings"] == 0.5                      # Untergrenze halbe Portion
    assert c.post("/api/recipes", headers=H, json={**body, "servings": "x"}).status_code == 400
    c.__exit__(None, None, None)


def test_ai_parse(monkeypatch):
    c = client()
    assert c.post("/api/ai/parse", headers=H, json={"text": "2 Brötchen"}).status_code == 503

    async def fake(system, user, max_tokens=700):
        assert "Brötchen" in user
        return ('```json\n{"meal": "fruehstueck", "items": [{"label": "2 Brötchen", "search": "Weizenbrötchen", "grams": 120},'
                ' {"label": "Kaffee mit Milch", "search": "Kaffee (Getränk)", "grams": 150}]}\n```')
    monkeypatch.setattr(ai, "AI_KEY", "test")
    monkeypatch.setattr(ai, "_complete", fake)
    assert c.get("/api/state").json()["ai"]
    r = c.post("/api/ai/parse", headers=H, json={"text": "2 Brötchen und Kaffee mit Milch"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["meal"] == "fruehstueck" and len(d["items"]) == 2
    assert d["items"][0]["candidates"][0]["name"].startswith("Weizenbrötchen") and d["items"][0]["grams"] == 120
    assert d["items"][1]["candidates"][0]["name"].startswith("Kaffee")

    async def broken(system, user, max_tokens=700):
        return "Tut mir leid"
    monkeypatch.setattr(ai, "_complete", broken)
    assert c.post("/api/ai/parse", headers=H, json={"text": "irgendwas"}).status_code == 502
    c.__exit__(None, None, None)


def test_ai_label_photo(monkeypatch):
    c = client()
    img = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
    assert c.post("/api/ai/label", headers=H, json={"images": [img]}).status_code == 503
    seen = {}

    async def fake(system, user, max_tokens=700):
        seen["user"] = user
        return ('{"name": "Proteinriegel Schoko", "brand": "Testmarke", "kcal": null, "kj": "1590", "protein": "30", '
                '"fat": "12,5", "satfat": "6", "carbs": "35", "sugar": "< 3", "fiber": 8, "salt": "0,4", '
                '"alcohol_vol": null, "serving_g": 45, "note": null}')
    monkeypatch.setattr(ai, "AI_KEY", "test")
    monkeypatch.setattr(ai, "_complete", fake)
    r = c.post("/api/ai/label", headers=H, json={"images": [img]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert seen["user"][1] == {"type": "image_url", "image_url": {"url": img}}
    assert d["kcal"] == 380.0 and d["fat"] == 12.5 and d["sugar"] == 3 and d["salt"] == 0.4 and d["serving_g"] == 45
    assert d["name"] == "Proteinriegel Schoko" and d["brand"] == "Testmarke" and d["found"] == 8 and d["warnings"] == []
    # ungültige Fotos
    assert c.post("/api/ai/label", headers=H, json={"images": []}).status_code == 400
    assert c.post("/api/ai/label", headers=H, json={"images": ["data:text/html;base64,PGh0bWw+"]}).status_code == 400
    assert c.post("/api/ai/label", headers=H, json={"images": ["https://example.com/a.jpg"]}).status_code == 400

    async def broken(system, user, max_tokens=700):
        return "Ich sehe nur ein unscharfes Bild."
    monkeypatch.setattr(ai, "_complete", broken)
    assert c.post("/api/ai/label", headers=H, json={"images": [img]}).status_code == 502
    c.__exit__(None, None, None)


def test_clean_label_plausibility():
    d = ai.clean_label({"kcal": 100, "protein": 20, "fat": 20, "carbs": 30, "satfat": 25, "sugar": 10})
    assert d["satfat"] is None                                   # „davon“ größer als Fett: verlesen
    assert any("bitte prüfen" in w for w in d["warnings"])       # 20·4 + 20·9 + 30·4 = 380 ≠ 100
    d = ai.clean_label({"kcal": 2000, "protein": -1, "alcohol_vol": "5,0 % vol", "note": "Werte nur je Portion"})
    assert d["kcal"] is None and d["protein"] is None and d["alcohol"] == 3.95 and d["warnings"] == ["Werte nur je Portion"]
