"""Intervallfasten: Fastenzeit aus den Uhrzeiten der Einträge, Serie, Fenster, Erinnerungen, API."""

from datetime import date, datetime

from app import db, fasting
from tests.test_motivation import H, client, log

BREAD = "Roggenvollkornbrot"
S16 = {"fast_mode": "16:8", "fast_window": "12:00", "fast_since": ""}


def _food(conn) -> str:
    return conn.execute("SELECT name FROM foods WHERE name LIKE ? ORDER BY length(name) LIMIT 1", (BREAD + "%",)).fetchone()[0]


def at(day: str, hm: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{hm}:00+02:00")       # Juni: Sommerzeit


def _setup(conn):
    bread = _food(conn)
    meals = [("2025-06-01", "20:00"),
             ("2025-06-02", "12:30"), ("2025-06-02", "19:30"),       # 17 h → geschafft
             ("2025-06-03", "10:00"), ("2025-06-03", "19:00"),       # 14,5 h → nicht geschafft
             ("2025-06-04", "11:30"), ("2025-06-04", "19:00"),       # 16,5 h
             ("2025-06-05", "11:15"), ("2025-06-05", "19:00")]       # 16,25 h (Toleranz 15 min)
    for day, hm in meals:
        log(conn, day, food_name=bread, grams=80, meal="mittag", ts=at(day, hm).isoformat())
    log(conn, "2025-06-05", grams=5, ts=at("2025-06-05", "08:00").isoformat())            # Kaffee-ähnlich: < 10 kcal
    log(conn, "2025-06-05", food_name=bread, grams=80, ts=at("2025-06-07", "09:00").isoformat())   # nachgetragen


def test_fasting_days_status_phase():
    c = client()
    try:
        with db.connect() as conn:
            _setup(conn)
            assert fasting.status(conn, {"fast_mode": ""}) is None
            d = fasting.days(conn, S16, date(2025, 6, 1), date(2025, 6, 5))
            assert "2025-06-01" not in d                                   # keine Mahlzeit davor
            assert d["2025-06-02"] == {"hours": 16.5, "ok": True}
            assert d["2025-06-03"] == {"hours": 14.5, "ok": False}
            assert d["2025-06-05"]["ok"] and d["2025-06-05"]["hours"] == 16.2

            st = fasting.status(conn, S16, at("2025-06-05", "15:00"))
            assert st["fast_hours"] == 16 and st["eat_hours"] == 8
            assert (st["window_open"], st["window_close"]) == ("12:00", "20:00")
            assert st["last_meal"] == db.iso(at("2025-06-05", "11:15"))     # Kaffee und Nachtrag zählen nicht
            assert st["streak"] == 2 and st["week_ok"] == 3 and st["week_days"] == 4
            assert st["today"]["ok"] and len(st["days"]) == 14 and st["days"][-1]["day"] == "2025-06-05"

            # 18:6: dieselben Tage reichen nicht
            st18 = fasting.status(conn, {**S16, "fast_mode": "18:6"}, at("2025-06-05", "15:00"))
            assert st18["streak"] == 0 and st18["window_close"] == "18:00"

            # Phasen fürs Fenster
            last = at("2025-06-05", "11:15")
            assert fasting.phase(S16, at("2025-06-05", "13:00"), last) == "open"      # vor dem Fenster gegessen
            assert fasting.phase(S16, at("2025-06-05", "13:00"), at("2025-06-05", "12:30")) == "window"
            assert fasting.phase(S16, at("2025-06-05", "21:00"), last) == "fasting"
            # Fenster über Mitternacht
            late = {**S16, "fast_window": "20:00"}
            assert fasting.phase(late, at("2025-06-06", "02:00"), None) == "open"
            assert fasting.window(late, date(2025, 6, 5))[1] == at("2025-06-06", "04:00")

            # Von Hand gestartet: zählt, wenn später als die letzte erfasste Mahlzeit
            manual = {**S16, "fast_since": db.iso(at("2025-06-05", "21:00"))}
            log(conn, "2025-06-06", food_name=_food(conn), grams=80, ts=at("2025-06-06", "13:30").isoformat())
            assert fasting.days(conn, manual, date(2025, 6, 6), date(2025, 6, 6))["2025-06-06"]["hours"] == 16.5
            assert fasting.days(conn, S16, date(2025, 6, 6), date(2025, 6, 6))["2025-06-06"]["hours"] == 18.5

        # API: Einstellungen, Status in /api/state, Uhrzeit eines Eintrags ändern
        assert c.get("/api/state").json()["fasting"] is None
        r = c.put("/api/settings", headers=H, json={"fast_mode": "14:10", "fast_window": "10:30"})
        assert r.status_code == 200
        f = r.json()["fasting"]
        assert f["mode"] == "14:10" and f["window_open"] == "10:30" and f["window_close"] == "20:30"
        assert c.put("/api/settings", headers=H, json={"fast_window": "25:00"}).status_code == 400
        assert c.put("/api/settings", headers=H, json={"fast_since": "2099-01-01T00:00:00+00:00"}).status_code == 400
        assert c.put("/api/settings", headers=H, json={"fast_since": "kaputt"}).status_code == 400
        assert c.put("/api/settings", headers=H, json={"fast_since": db.iso(db.now_utc())}).json()["fasting"]["manual_since"]
        assert c.put("/api/settings", headers=H, json={"fast_mode": "20:4"}).json()["fasting"] is None
        today = c.get("/api/state").json()["today"]
        bread = c.get("/api/foods/search", params={"q": "roggenvollkornbrot"}).json()[0]
        c.post("/api/log", headers=H, json={"id": "f1", "food_id": bread["id"], "grams": 50, "day": today})
        ts = f"{today}T06:15:00+01:00"
        c.post("/api/log", headers=H, json={"id": "f1", "food_id": bread["id"], "grams": 50, "day": today, "ts": ts})
        with db.connect() as conn:
            assert conn.execute("SELECT ts FROM food_log WHERE id = 'f1'").fetchone()[0] == db.iso(db.parse(ts))
        c.post("/api/log", headers=H, json={"id": "f1", "food_id": bread["id"], "grams": 60, "day": today})   # ohne ts: bleibt
        with db.connect() as conn:
            assert conn.execute("SELECT ts FROM food_log WHERE id = 'f1'").fetchone()[0] == db.iso(db.parse(ts))
    finally:
        with db.connect() as conn:
            for k, v in (("fast_mode", ""), ("fast_window", "12:00"), ("fast_since", "")):
                db.set_setting(conn, k, v)
        c.__exit__(None, None, None)


def test_fasting_push(monkeypatch):
    from app import push
    sent = []
    monkeypatch.setattr(push, "send", lambda conn, title, body, url="/", tag="": sent.append((title, body)) or 1)
    s = {**S16, "fast_push": True}
    with db.connect() as conn:
        conn.execute("DELETE FROM push_log WHERE kind = 'fast'")
        try:
            last = at("2025-06-09", "19:30")
            assert not push.fasting_push(conn, s, at("2025-06-10", "09:00"), last, "fasting")       # mitten in der Fastenzeit
            assert push.fasting_push(conn, s, at("2025-06-10", "12:05"), last, "open")
            assert sent[-1][0] == "Essensfenster offen" and "16 Stunden" in sent[-1][1]
            assert not push.fasting_push(conn, s, at("2025-06-10", "12:20"), last, "open")          # nur einmal
            assert push.fasting_push(conn, s, at("2025-06-10", "19:40"), at("2025-06-10", "13:00"), "window")
            assert sent[-1][0] == "Essensfenster schließt um 20:00"
            assert len(sent) == 2
        finally:
            conn.execute("DELETE FROM push_log WHERE kind = 'fast'")
