"""Adaptiver Bedarf: Verbrauch aus Einträgen und Gewichtsverlauf."""

import os
import random
from datetime import date, timedelta

import pytest

from app import adaptive, db, points
from tests.test_api import H, client

TODAY = date(2026, 11, 19)
S = {"sex": "m", "birth_year": 1975, "height_cm": 178, "activity": 1.375, "mode": "lose", "pace": 0.5,
     "steps_baseline": 5000}


@pytest.fixture
def fresh_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", os.path.join(tmp_path, "adaptive.db"))
    db.init()


def _fill(days=28, kcal=2000, kg0=95.0, kg_per_week=-0.5, logged_every=1, weigh_every=2, noise=0.0):
    rnd = random.Random(1)
    with db.connect() as conn:
        for i in range(days):
            d = TODAY - timedelta(days=days - i)
            if i % logged_every == 0:
                for meal in ("mittag", "abend"):
                    conn.execute("INSERT INTO food_log (id, ts, day, meal, name, grams, kcal, created) "
                                 "VALUES (?, ?, ?, ?, 'Test', 300, ?, ?)",
                                 (f"{d}-{meal}", f"{d}T12:00:00+00:00", d.isoformat(), meal, kcal / 2, f"{d}T12:00:00+00:00"))
            if i % weigh_every == 0:
                kg = kg0 + kg_per_week / 7 * i + rnd.uniform(-noise, noise)
                conn.execute("INSERT INTO body (ts, day, kind, value, source) VALUES (?, ?, 'weight', ?, 'manual')",
                             (f"{d}T06:00:00+00:00", d.isoformat(), round(kg, 2)))


def test_estimate_real_need(fresh_db):
    _fill()                                                 # 2.000 kcal, −0,5 kg/Woche
    with db.connect() as conn:
        r = adaptive.estimate(conn, S, TODAY)
    assert r["status"] == "ok"
    assert r["kg_per_week"] == pytest.approx(-0.5, abs=0.01)
    assert r["real"] == pytest.approx(2000 + 0.5 / 7 * 7700, abs=5)     # ≈ 2.550 kcal
    assert r["confidence"] == "hoch" and r["error"] <= 5               # Wiegewerte auf 0,01 kg gerundet
    assert r["suggested"] == adaptive._round50(r["real"] - r["model"])
    assert r["suggest"] is (abs(r["suggested"]) >= adaptive.MIN_CHANGE)
    assert r["points_new"] != r["points_now"] or not r["suggest"]


def test_noisy_weights_lower_confidence(fresh_db):
    _fill(days=16, weigh_every=2, noise=1.5)                # wenige, stark schwankende Wiegewerte
    with db.connect() as conn:
        r = adaptive.estimate(conn, S, TODAY)
    assert r["status"] == "ok" and r["confidence"] in ("mittel", "niedrig") and r["error"] > 150


def test_too_early_and_gaps(fresh_db):
    _fill(days=10)
    with db.connect() as conn:
        assert adaptive.estimate(conn, S, TODAY)["status"] == "early"
        conn.execute("DELETE FROM food_log")
        conn.execute("DELETE FROM body")
    _fill(days=28, logged_every=2)                          # nur jeder zweite Tag erfasst
    with db.connect() as conn:
        r = adaptive.estimate(conn, S, TODAY)
    assert r["status"] == "gaps" and r["logged"] == 14


def test_adjust_changes_budget():
    base = points.kcal_target(S, 90)
    plus = points.kcal_target({**S, "tdee_adjust": 200}, 90)
    assert plus["tdee"] == base["tdee"] + 200 and plus["adjust"] == 200
    assert plus["target"] == base["target"] + 200


def test_adjust_setting_is_rounded_and_capped():
    c = client()
    assert c.put("/api/settings", headers=H, json={"tdee_adjust": 137}).json()["settings"]["tdee_adjust"] == 150
    assert c.put("/api/settings", headers=H, json={"tdee_adjust": -900}).json()["settings"]["tdee_adjust"] == -500
    assert c.put("/api/settings", headers=H, json={"tdee_adjust": "x"}).status_code == 400
    assert "adaptive" in c.get("/api/stats?days=7").json()
    c.put("/api/settings", headers=H, json={"tdee_adjust": 0})
    c.__exit__(None, None, None)
