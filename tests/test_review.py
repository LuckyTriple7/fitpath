"""Wochenrückblick: Kennzahlen einer abgeschlossenen Woche, Hinweis auf „Heute“, API."""

from datetime import date, timedelta

from app import db, review
from tests.test_motivation import H, client, log

MON = date(2025, 3, 3)                       # weit in der Vergangenheit, stört die anderen Tests nicht
BREAD = "Roggenvollkornbrot"


def _food(conn) -> str:
    return conn.execute("SELECT name FROM foods WHERE name LIKE ? ORDER BY length(name) LIMIT 1", (BREAD + "%",)).fetchone()[0]


def _setup(conn):
    name = _food(conn)
    for i in range(5):                                       # Mo–Fr erfasst, Do deutlich drüber
        log(conn, (MON + timedelta(days=i)).isoformat(), food_name=name, grams=1500 if i == 3 else 100 + i * 20,
            meal="mittag")
    for day, kg in (("2025-02-28", 95.0), ("2025-03-04", 94.6), ("2025-03-08", 94.2)):
        conn.execute("INSERT INTO body (ts, day, kind, value, source) VALUES (?, ?, 'weight', ?, 'manual')",
                     (f"{day}T06:00:00+00:00", day, kg))


def _cleanup(conn):
    first, last = (MON - timedelta(days=7)).isoformat(), (MON + timedelta(days=6)).isoformat()
    conn.execute("DELETE FROM food_log WHERE day BETWEEN ? AND ?", (first, last))
    conn.execute("DELETE FROM body WHERE day BETWEEN '2025-02-28' AND ?", (last,))


def test_week_review_and_teaser():
    c = client()
    try:
        with db.connect() as conn:
            _setup(conn)
            s = db.get_settings(conn)
            r = review.week(conn, s, MON + timedelta(days=2))          # beliebiger Tag → Montag der Woche
            assert r["start"] == MON.isoformat() and r["end"] == "2025-03-09" and len(r["days"]) == 7
            assert r["complete"] and r["prev_start"] == "2025-02-24" and r["next_start"] == "2025-03-10"
            assert r["logged"] == 5 and r["in_budget"] == 4
            thu = r["days"][3]
            assert thu["left_points"] < 0 and r["best"]["day"] != thu["day"]
            assert r["best"]["left_points"] == max(d["left_points"] for d in r["days"][:5] if d["left_points"] >= 0)
            assert r["balance_points"] == sum(d["left_points"] for d in r["days"][:5])
            assert r["avg"]["fiber"] > 0 and r["avg"]["salt"] > 0 and r["targets"]["fiber"] == 30
            assert r["trend"]["weighings"] == 2 and r["trend"]["start"] == 95.0 and r["trend"]["delta"] < 0
            assert r["prev"]["logged"] == 0 and r["prev"]["avg_points"] is None

            # Urlaub am Mittwoch zählt nicht mit
            s2 = {**s, "pauses": [{"start": "2025-03-05", "end": "2025-03-05", "kind": "urlaub"}]}
            r2 = review.week(conn, s2, MON)
            assert r2["logged"] == 4 and r2["plan_days"] == {"urlaub": 1}

            # Hinweis auf „Heute“: Mo–Mi der Folgewoche, bis gesehen
            t = review.teaser(conn, s, MON + timedelta(days=7))
            assert t == {"start": r["start"], "end": r["end"], "logged": 5, "in_budget": 4,
                         "balance_points": r["balance_points"], "balance_kcal": r["balance_kcal"],
                         "trend_delta": r["trend"]["delta"]}
            assert review.teaser(conn, s, MON + timedelta(days=9)) is not None            # Mittwoch
            assert review.teaser(conn, s, MON + timedelta(days=10)) is None               # Donnerstag
            assert review.teaser(conn, {**s, "review_seen": MON.isoformat()}, MON + timedelta(days=7)) is None
            assert review.teaser(conn, s, MON + timedelta(days=14)) is None               # Woche ohne Einträge

        # API
        got = c.get("/api/review/week", params={"start": "2025-03-06"}).json()
        assert got["start"] == MON.isoformat() and got["in_budget"] == 4
        assert c.get("/api/review/week").status_code == 200                               # letzte Woche
        future = (date.fromisoformat(c.get("/api/state").json()["today"]) + timedelta(days=8)).isoformat()
        assert c.get("/api/review/week", params={"start": future}).status_code == 400
        assert c.get("/api/review/week", params={"start": "kaputt"}).status_code == 400
        r = c.put("/api/settings", headers=H, json={"review_seen": "2025-03-03"})
        assert r.status_code == 200 and r.json()["settings"]["review_seen"] == "2025-03-03"
        assert c.put("/api/settings", headers=H, json={"review_seen": "gestern"}).status_code == 400
        assert "week_review" in r.json()
    finally:
        with db.connect() as conn:
            _cleanup(conn)
            db.set_setting(conn, "review_seen", "")
        c.__exit__(None, None, None)
