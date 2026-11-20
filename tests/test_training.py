"""Training: Punkte nach MET, keine Doppelzählung mit Schritten, Health Connect, API."""

from app import db, ingest, points, training
from tests.test_recipes_ai import H, client


def w(kind, minutes, intensity="mittel", start="2026-11-18T08:00:00+00:00", source="manual", wid=None):
    return {"id": wid or f"{kind}-{start}", "start": start, "minutes": minutes, "kind": kind,
            "intensity": intensity, "source": source}


def test_swimming_points():
    r = training.day_credit([w("schwimmen", 30)], 80, 0)
    # (5,8 − 1) × 80 kg × 0,5 h = 192 kcal, davon die Hälfte
    assert round(r["kcal"]) == 96 and r["workouts"][0]["points"] == 3
    assert r["train_minutes"] == 30 and r["swim"]


def test_walking_counts_via_steps():
    # Schritte über der Grundlinie decken das Spazieren schon ab
    r = training.day_credit([w("gehen", 30)], 80, 5000)
    assert r["kcal"] == 0 and r["workouts"][0]["covered_steps"] == 3000 and r["train_minutes"] == 0
    # unter der Grundlinie hat der Schrittbonus nichts gutgeschrieben, dann zählt das Gehen selbst
    assert round(training.day_credit([w("gehen", 30)], 80, 0)["kcal"]) == 50


def test_running_only_counts_above_steps():
    r = training.day_credit([w("laufen", 30)], 80, 10000)
    # (9 − 1) × 80 × 0,5 = 320 kcal, minus 4.800 Schritte × 80 × 0,0005 = 192 → 128, davon die Hälfte
    assert round(r["kcal"]) == 64 and r["workouts"][0]["covered_steps"] == 4800
    # Schritte werden nur einmal abgezogen
    r = training.day_credit([w("laufen", 30), w("laufen", 30, start="2026-11-18T17:00:00+00:00")], 80, 6000)
    assert [x["covered_steps"] for x in r["workouts"]] == [4800, 1200]


def test_cap_and_intensity():
    r = training.day_credit([w("hiit", 300, "hart")], 80, 0)
    assert r["kcal"] == training.MAX_POINTS_DAY * points.KCAL_PER_POINT and r["capped"]
    easy = training.day_credit([w("rad", 60, "leicht")], 80, 0)["kcal"]
    hard = training.day_credit([w("rad", 60, "hart")], 80, 0)["kcal"]
    assert easy < hard


def test_duplicate_sessions_from_two_apps():
    a = w("schwimmen", 40, source="hc", wid="a", start="2026-11-18T08:00:00+00:00")
    b = w("schwimmen", 38, source="hc", wid="b", start="2026-11-18T08:01:00+00:00")
    r = training.day_credit([a, b], 80, 0)
    assert [x["duplicate"] for x in r["workouts"]] == [False, True]
    assert r["train_minutes"] == 40


def test_hc_mapping():
    assert training.kind_for_hc("swimming_pool", "74") == "schwimmen"
    assert training.kind_for_hc(None, "56") == "laufen"
    assert training.kind_for_hc("", "79") == "gehen"
    assert training.kind_for_hc("kitesurfing", "999") == "sonstiges"


EX = {"source": "health_connect", "sequence": 500, "exercise": [
    {"type": "74", "name": "swimming_pool", "title": "Schwimmen", "start_time": "2026-11-17T17:00:00Z",
     "end_time": "2026-11-17T17:45:00Z", "duration_seconds": 2700, "uuid": "ex1", "source": "com.sec.android.app.shealth"},
    {"type": "79", "start_time": "2026-11-17T09:00:00Z", "end_time": "2026-11-17T09:20:00Z", "uuid": "ex2"},
    {"type": "56", "start_time": "2026-11-17T10:00:00Z", "end_time": "2026-11-17T10:01:00Z", "uuid": "ex3"},
]}


def test_ingest_exercise():
    db.init()
    with db.connect() as conn:
        conn.execute("DELETE FROM workouts")
        r = ingest.apply(conn, EX)
        assert r["exercise"] == 2                              # 1 Minute ist zu kurz
        rows = {x["id"]: dict(x) for x in conn.execute("SELECT * FROM workouts")}
        assert rows["hc:ex1"]["kind"] == "schwimmen" and rows["hc:ex1"]["minutes"] == 45
        assert rows["hc:ex1"]["day"] == "2026-11-17" and rows["hc:ex2"]["minutes"] == 20
        # Sportart von Hand geändert: nächste Lieferung überschreibt sie nicht, Dauer bleibt von der Uhr
        training.update(conn, "hc:ex1", {"kind": "aqua", "minutes": 99})
        ingest.apply(conn, {**EX, "sequence": 501})
        row = conn.execute("SELECT * FROM workouts WHERE id = 'hc:ex1'").fetchone()
        assert row["kind"] == "aqua" and row["minutes"] == 45
        # in FitPath gelöscht: nur ausgeblendet, kommt nicht wieder
        training.delete(conn, "hc:ex1")
        ingest.apply(conn, {**EX, "sequence": 502})
        assert conn.execute("SELECT hidden FROM workouts WHERE id = 'hc:ex1'").fetchone()[0] == 1
        assert all(x["id"] != "hc:ex1" for x in training.by_day(conn, "2026-11-17", "2026-11-17").get("2026-11-17", []))
        # in Health Connect gelöscht
        ingest.apply(conn, {"source": "health_connect", "sequence": 503,
                            "deleted_records": [{"type": "exercise", "uuid": "ex2"}]})
        assert not conn.execute("SELECT 1 FROM workouts WHERE id = 'hc:ex2'").fetchone()


def test_api_manual_workout():
    c = client()
    st = c.get("/api/state").json()
    assert "schwimmen" in st["training"]["sports"]
    day = st["today"]
    before = (st["overview"]["activity"] or {}).get("act_points", 0)
    assert c.post("/api/workouts", headers=H, json={"kind": "tauchen", "minutes": 30}).status_code == 400
    assert c.post("/api/workouts", headers=H, json={"kind": "schwimmen", "minutes": 1}).status_code == 400
    st = c.post("/api/workouts", headers=H, json={"id": "m1", "kind": "schwimmen", "minutes": "45", "day": day}).json()
    a = st["overview"]["activity"]
    assert a["act_points"] > before and a["workouts"][0]["name"] == "Schwimmen" and a["train_minutes"] == 45
    assert c.post("/api/workouts", headers=H, json={"id": "m1", "kind": "rad", "minutes": 20}).status_code == 409
    parts = st["motivation"]["xp"]["parts"]
    assert next(x for x in parts if x["label"] == "Trainingstage")["count"] >= 1
    harder = c.put("/api/workouts/m1", headers=H, json={"intensity": "hart"}).json()["overview"]["activity"]
    assert harder["train_kcal"] > a["train_kcal"]
    assert c.put("/api/workouts/nix", headers=H, json={"intensity": "hart"}).status_code == 404
    st = c.delete("/api/workouts/m1", headers=H).json()
    assert not any(x["id"] == "m1" for x in (st["overview"]["activity"] or {}).get("workouts", []))
    c.__exit__(None, None, None)
