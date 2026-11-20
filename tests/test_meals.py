"""Gespeicherte Mahlzeiten und Prognose fürs Zielgewicht."""

from datetime import date, timedelta

from app import body, db
from tests.test_recipes_ai import H, client, food


def test_forecast():
    today = date(2026, 11, 20)
    lose = {"mode": "lose", "pace": 0.5}
    f = body.forecast(95, 85, None, lose, today)                  # noch kein Trend: geplantes Tempo
    assert f["basis"] == "plan" and f["weeks"] == 20 and f["date"] == (today + timedelta(days=140)).isoformat()
    f = body.forecast(95, 85, -0.625, lose, today)                # echtes Tempo
    assert f["basis"] == "trend" and f["weeks"] == 16 and not f["capped"]
    f = body.forecast(95, 85, -2.0, lose, today)                  # Anfangs-Wasser: höchstens 1 % pro Woche
    assert f["capped"] and f["per_week"] == 0.95 and f["weeks"] == 11
    assert body.forecast(95, 85, 0.1, lose, today) == {"basis": "trend", "stalled": True}
    assert body.forecast(95, 85, None, {"mode": "lose", "pace": 0.01}, today)["far"]
    assert body.forecast(95, 85, -1.0, {"mode": "keep"}, today) is None
    assert body.forecast(84, 85, -1.0, lose, today) is None       # Ziel schon erreicht


def test_meal_templates():
    c = client()
    with db.connect() as conn:
        conn.execute("DELETE FROM meal_templates")
    brot = food(c, "roggenvollkornbrot")
    butter = food(c, "butter")
    items = [{"food_id": brot["id"], "grams": 100, "portion": "2× 1 Scheibe"}, {"food_id": butter["id"], "grams": 10}]
    assert c.post("/api/templates", headers=H, json={"name": "", "items": items}).status_code == 400
    assert c.post("/api/templates", headers=H, json={"name": "Leer", "items": []}).status_code == 400
    st = c.post("/api/templates", headers=H, json={"name": "Mein Frühstück", "meal": "fruehstueck", "items": items}).json()
    t = st["templates"][0]
    assert t["name"] == "Mein Frühstück" and t["meal"] == "fruehstueck" and len(t["items"]) == 2 and t["points"] > 0
    assert t["points"] == sum(i["points"] for i in t["items"])

    # gleicher Name ersetzt (ergänzen), kein zweiter Eintrag
    st = c.post("/api/templates", headers=H, json={"name": "mein frühstück", "meal": "fruehstueck",
                                                   "items": items + [{"food_id": brot["id"], "grams": 50}]}).json()
    assert len(st["templates"]) == 1 and len(st["templates"][0]["items"]) == 3

    # erfassen, Butter diesmal weglassen
    day = st["today"]
    r = c.post(f"/api/templates/{t['id']}/log", headers=H, json={"meal": "abend", "day": day, "skip": [1]}).json()
    assert len(r["added"]) == 2
    got = [e for e in r["overview"]["entries"] if e["id"] in r["added"]]
    assert {e["meal"] for e in got} == {"abend"} and {e["grams"] for e in got} == {100, 50}
    assert got[0]["portion"] == "2× 1 Scheibe" or got[1]["portion"] == "2× 1 Scheibe"
    assert r["templates"][0]["uses"] == 1
    assert c.post(f"/api/templates/{t['id']}/log", headers=H, json={"skip": [0, 1, 2]}).status_code == 400

    # umbenennen, Standard-Mahlzeit entfernen, löschen
    st = c.put(f"/api/templates/{t['id']}", headers=H, json={"name": "Brotzeit", "meal": None, "items": items}).json()
    assert st["templates"][0]["name"] == "Brotzeit" and st["templates"][0]["meal"] is None
    assert c.put("/api/templates/nix", headers=H, json={"name": "x", "items": items}).status_code == 404
    assert c.delete(f"/api/templates/{t['id']}", headers=H).json()["templates"] == []
    assert c.delete(f"/api/templates/{t['id']}", headers=H).status_code == 404
    assert c.post("/api/templates/nix/log", headers=H, json={}).status_code == 404
    c.__exit__(None, None, None)
