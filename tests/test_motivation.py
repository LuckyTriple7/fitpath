"""Motivation: XP, Level, Abzeichen, Wochen-Challenge, Heißhunger, Snack-Uhrzeiten."""

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import auth, db, main, motivation, points

H = {"x-fitpath": "1"}


def client():
    c = TestClient(main.app)
    c.__enter__()
    with db.connect() as conn:
        for t in ("food_log", "body", "activity", "events"):
            conn.execute(f"DELETE FROM {t}")
        for k in ("unlocked", "challenges_done", "challenge_skips", "start_date", "motivation_rev"):
            conn.execute("DELETE FROM settings WHERE key = ?", (k,))
        url = auth.create_link(conn, "Test")
    assert c.post(url.replace("http://testserver", ""), follow_redirects=False).status_code == 303
    c.post("/api/onboarding", headers=H, json={"settings": {"start_weight": 95, "goal_weight": 85, "height_cm": 178}})
    return c


def log(conn, day, food_name="Apfel roh", grams=150, meal="snack", ts=None):
    f = conn.execute("SELECT * FROM foods WHERE name = ?", (food_name,)).fetchone()
    from app import foods
    food = foods.get(conn, f["id"])
    e = {"id": str(uuid.uuid4()), "ts": ts or f"{day}T10:00:00+00:00", "day": day, "meal": meal, "food_id": food["id"],
         "name": food["name"], "grams": grams, "portion": None, "zero": 1 if food["zero"] else 0,
         **points.scale(food, grams), "points_raw": None}
    main._upsert_entry(conn, e)


def test_level_thresholds():
    assert motivation.level_for(0)["level"] == 1
    assert motivation.level_for(99)["level"] == 1
    assert motivation.level_for(100)["level"] == 2
    assert motivation.level_for(260)["name"] == "Spaziergänger"
    assert motivation.level_for(100000)["level"] == len(motivation.LEVELS)


def test_streak_badges_xp_and_challenge():
    c = client()
    today = date.fromisoformat(c.get("/api/state").json()["today"])
    with db.connect() as conn:
        db.set_setting(conn, "start_date", (today - timedelta(days=10)).isoformat())
        for i in range(1, 8):          # 7 Tage mit Einträgen bis gestern, je 3 Mahlzeiten (0-Punkte-Obst)
            d = (today - timedelta(days=i)).isoformat()
            for meal in ("fruehstueck", "mittag", "abend"):
                log(conn, d, meal=meal)
    st = c.get("/api/state").json()
    m = st["motivation"]
    assert m["streak"] == 7 and m["best_streak"] == 7
    got = {b["id"] for b in m["badges"] if b["unlocked"]}
    assert {"first", "streak3", "streak7", "budget7"} <= got
    assert m["xp"]["points"] >= 7 * 10 + 7 * 10 + 4 * 50
    # Abzeichen bleiben, auch wenn die Daten verschwinden
    with db.connect() as conn:
        conn.execute("DELETE FROM food_log")
    again = {b["id"] for b in c.get("/api/state").json()["motivation"]["badges"] if b["unlocked"]}
    assert got <= again
    # Challenge wechseln
    ch1 = c.get("/api/state").json()["motivation"]["challenge"]
    ch2 = c.post("/api/challenge/skip", headers=H).json()["motivation"]["challenge"]
    assert ch1["id"] != ch2["id"] or ch1["done"]
    c.__exit__(None, None, None)


def test_challenge_done_once():
    c = client()
    today = date.fromisoformat(c.get("/api/state").json()["today"])
    with db.connect() as conn:
        s = db.get_settings(conn)
        idx = [x[0] for x in motivation.CHALLENGES].index("zero10")
        # Woche so drehen, dass „zero10“ dran ist
        skips = (idx - today.isocalendar()[1]) % len(motivation.CHALLENGES)
        db.set_setting(conn, "challenge_skips", {points.week_start(today).isoformat(): skips})
        for _ in range(10):
            log(conn, today.isoformat())
        ch = motivation.challenge(conn, db.get_settings(conn), today)
        assert ch["id"] == "zero10" and ch["done"] and ch["progress"] == 10
        motivation.challenge(conn, db.get_settings(conn), today)
        assert len(db.get_settings(conn)["challenges_done"]) == 1
    c.__exit__(None, None, None)


def test_craving_events_and_stats():
    c = client()
    for res in (True, True, False):
        r = c.post("/api/events", headers=H, json={"kind": "craving", "trigger": "Stress", "intensity": 7, "resisted": res})
        assert r.status_code == 200
    assert c.post("/api/events", headers=H, json={"kind": "quatsch"}).status_code == 400
    st = c.get("/api/stats?days=7").json()["cravings"]
    assert st["total"] == 3 and st["resisted"] == 2 and st["triggers"][0]["trigger"] == "Stress"
    assert c.get("/api/state").json()["motivation"]["xp"]["parts"][4]["count"] == 2
    ev = c.get("/api/events").json()
    c.delete(f"/api/events/{ev[0]['id']}", headers=H)
    assert len(c.get("/api/events").json()) == 2
    c.__exit__(None, None, None)


def test_critical_hours_and_plans():
    c = client()
    today = date.fromisoformat(c.get("/api/state").json()["today"])
    with db.connect() as conn:
        for i in range(1, 5):          # 4 Tage Snack um 15 Uhr (Berlin, Winter = 14 Uhr UTC)
            d = (today - timedelta(days=i)).isoformat()
            log(conn, d, ts=f"{d}T14:10:00+00:00")
        hours = motivation.critical_hours(conn, today)
    assert hours == [{"hour": 15, "days": 4}]
    r = c.put("/api/settings", headers=H, json={"craving_triggers": ["Stress", "Feierabend", "Stress"],
                                                "plans": {"Feierabend": "Erst duschen"}})
    s = r.json()["settings"]
    assert s["craving_triggers"] == ["Stress", "Feierabend"] and s["plans"] == {"Feierabend": "Erst duschen"}
    c.__exit__(None, None, None)


def test_only_from_setup_day():
    """Nachgeladene Daten vor dem Einrichtungstag zählen nicht für Erfolge."""
    c = client()
    today = date.fromisoformat(c.get("/api/state").json()["today"])
    with db.connect() as conn:
        db.set_setting(conn, "start_date", today.isoformat())
        for i in range(1, 60):     # zwei Monate Schritte und Gewicht aus der Vergangenheit
            d = (today - timedelta(days=i)).isoformat()
            conn.execute("INSERT OR REPLACE INTO activity (day, source, steps, updated) VALUES (?, 'hc', 25000, ?)", (d, db.iso(db.now_utc())))
            conn.execute("INSERT INTO body (ts, day, kind, value, source) VALUES (?, ?, 'weight', 99, 'hc')", (f"{d}T06:00:00+00:00", d))
        # alter Stand: früher freigeschaltete Abzeichen aus der Vergangenheit
        db.set_setting(conn, "unlocked", {"steps10": "2026-01-01T00:00:00+00:00", "weigh10": "2026-01-01T00:00:00+00:00"})
        db.set_setting(conn, "motivation_rev", 1)
    m = c.get("/api/state").json()["motivation"]
    got = {b["id"] for b in m["badges"] if b["unlocked"]}
    assert not {"steps1", "steps10", "steps20k", "weigh10"} & got
    parts = {p["label"]: p["count"] for p in m["xp"]["parts"]}
    assert parts["Schrittziel erreicht"] == 0 and parts["Gewogen"] <= 1
    c.__exit__(None, None, None)
