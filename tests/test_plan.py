"""Tagesplan: Refeed-Tage, Diätpause, Urlaub (app/plan.py) und wo das Budget je Tag wirkt."""

from datetime import date, timedelta

import pytest

from app import adaptive, db, motivation, plan, points
from tests.test_motivation import H, client, log

MON = date(2026, 11, 23)                     # Montag
KT = {"tdee": 2700, "target": 2150, "floor": 1500}
LOSE = {"mode": "lose", "refeed_plan": [{"from": "2026-01-05", "days": [5, 6]}]}


def kinds(w):
    return [v["kind"] for v in w.values()]


def test_refeed_week_keeps_weekly_deficit():
    w = plan.week(LOSE, KT, MON)
    assert kinds(w) == ["normal"] * 5 + ["refeed"] * 2
    assert w["2026-11-28"]["target"] == 2700 and w["2026-11-23"]["target"] == 1930
    assert sum(v["target"] for v in w.values()) == 7 * 2150
    assert w["2026-11-29"]["points"] == points.points_budget(2700)


def test_refeed_respects_floor():
    # übrige Tage kämen auf 1440: bleiben bei 1500, Refeed bekommt nur das Freiwerdende
    w = plan.week(LOSE, {"tdee": 2000, "target": 1600, "floor": 1500}, MON)
    assert w["2026-11-23"]["target"] == 1500 and w["2026-11-28"]["target"] == 1850
    assert sum(v["target"] for v in w.values()) == 7 * 1600
    # lohnt sich nicht mehr (weniger als 100 kcal mehr): kein Refeed
    kt = {"tdee": 2000, "target": 1520, "floor": 1500}
    assert set(kinds(plan.week(LOSE, kt, MON))) == {"normal"}
    assert plan.info(LOSE, kt, MON)["blocked"] == "floor"


def test_no_refeed_when_keeping_weight():
    s = {**LOSE, "mode": "keep"}
    kt = {"tdee": 2700, "target": 2700, "floor": 1500}
    assert set(kinds(plan.week(s, kt, MON))) == {"normal"}
    assert plan.info(s, kt, MON)["blocked"] == "keep"


def test_pauses_in_week():
    s = {**LOSE, "pauses": [{"start": "2026-11-19", "end": "2026-11-24", "kind": "urlaub"},
                            {"start": "2026-11-27", "end": "2026-11-27", "kind": "erhaltung"}]}
    w = plan.week(s, KT, MON)
    # Woche mit Pause: kein Refeed, Pausentage auf Bedarf, übrige auf Ziel
    assert kinds(w) == ["urlaub", "urlaub", "normal", "normal", "erhaltung", "normal", "normal"]
    assert w["2026-11-23"]["target"] == 2700 and w["2026-11-27"]["target"] == 2700
    assert w["2026-11-25"]["target"] == 2150
    assert w["2026-11-23"]["pause"]["end"] == "2026-11-24"
    assert plan.is_vacation(s, "2026-11-24") and not plan.is_vacation(s, "2026-11-27")
    assert plan.info(s, KT, MON)["blocked"] == "pause"
    # Woche danach: wieder Refeed
    assert "refeed" in kinds(plan.week(s, KT, MON + timedelta(days=7)))


def test_refeed_plan_history_and_week_swap():
    today = date(2026, 11, 25)
    s = {"mode": "lose"}
    s["refeed_plan"] = plan.set_refeed(s, [5, 6], today)
    assert s["refeed_plan"] == [{"from": "2026-11-23", "days": [5, 6]}]
    assert plan.refeed_days(s, MON - timedelta(days=7)) == []        # frühere Woche bleibt
    # zwei Wochen später aus: diese Woche bleibt Sa/So
    later = today + timedelta(days=14)
    s["refeed_plan"] = plan.set_refeed(s, [], later)
    assert plan.refeed_days(s, MON) == [5, 6] and plan.refeed_days(s, MON + timedelta(days=14)) == []
    # mehrfach in derselben Woche ändern ersetzt nur den Eintrag dieser Woche
    s["refeed_plan"] = plan.set_refeed(s, [4, 5], later)
    s["refeed_plan"] = plan.set_refeed(s, [], later)
    assert s["refeed_plan"] == [{"from": "2026-11-23", "days": [5, 6]}, {"from": "2026-12-07", "days": []}]

    s = {"mode": "lose", "refeed_plan": [{"from": "2026-11-23", "days": [5, 6]}]}
    s["refeed_weeks"] = plan.set_week(s, MON, [4, 6], today)
    assert plan.refeed_days(s, MON) == [4, 6] and plan.refeed_days(s, MON + timedelta(days=7)) == [5, 6]
    assert plan.set_week(s, MON, [5, 6], today) == {}                 # gleich wie immer: kein Tausch
    assert plan.set_week(s, MON, None, today) == {}
    s["refeed_weeks"] = plan.set_week(s, MON, [], today)               # diese Woche ohne Refeed
    assert set(kinds(plan.week(s, KT, MON))) == {"normal"}
    for bad in (MON + timedelta(days=1), MON - timedelta(days=7), MON + timedelta(days=14)):
        with pytest.raises(ValueError):
            plan.set_week(s, bad, [5], today)
    with pytest.raises(ValueError):
        plan.clean_days([1, 2, 3])
    with pytest.raises(ValueError):
        plan.clean_days([7])


def test_clean_pauses():
    today = date(2026, 11, 25)
    ok = plan.clean_pauses([{"start": "2026-12-20", "end": "2027-01-02", "kind": "urlaub"},
                            {"start": "2026-11-01", "end": "2026-11-07", "kind": "erhaltung"},
                            {"start": "2024-01-01", "end": "2024-01-10", "kind": "urlaub"}], today)
    assert [p["start"] for p in ok] == ["2026-11-01", "2026-12-20"]   # sortiert, sehr alte fallen weg
    bad = [
        [{"start": "2026-12-01", "end": "2026-12-10", "kind": "urlaub"}, {"start": "2026-12-10", "end": "2026-12-12", "kind": "urlaub"}],
        [{"start": "2026-12-10", "end": "2026-12-01", "kind": "urlaub"}],
        [{"start": "2026-12-01", "end": "2026-12-29", "kind": "erhaltung"}],          # 29 Tage Diätpause
        [{"start": "2026-12-01", "end": "2026-12-03", "kind": "fasten"}],
        [{"start": "2026-12-01", "kind": "urlaub"}],
    ]
    for b in bad:
        with pytest.raises((ValueError, KeyError)):
            plan.clean_pauses(b, today)


def test_week_summary_with_plan():
    # Mo normal (40 von 43 → +3), Di Urlaub mit Eintrag (zählt nicht), heute Mittwoch Refeed-Budget 62
    p = {"2026-11-23": {"points": 43, "target": 1930, "kind": "normal"},
         "2026-11-24": {"points": 62, "target": 2700, "kind": "urlaub"},
         "2026-11-25": {"points": 62, "target": 2700, "kind": "refeed"}}
    days = {"2026-11-23": {"points": 40, "kcal": 1800, "entries": 3},
            "2026-11-24": {"points": 90, "kcal": 3500, "entries": 2},
            "2026-11-25": {"points": 50, "kcal": 2200, "entries": 2}}
    w = points.week_summary(days, date(2026, 11, 25), 49, 2150, p)
    assert w["reserve_points"] == 3
    assert w["today_left_points"] == 12
    assert w["days"][1]["left_points"] == 62 - 90


def test_adaptive_start_after_vacation():
    s = {"pauses": [{"start": "2026-11-01", "end": "2026-11-10", "kind": "urlaub"},
                    {"start": "2026-11-15", "end": "2026-11-16", "kind": "erhaltung"}]}
    start, after = plan.adaptive_start(s, date(2026, 10, 28), date(2026, 11, 24))
    assert start == after == date(2026, 11, 14)                 # 10. + 3 Tage Erholung + 1
    start, after = plan.adaptive_start(s, date(2026, 11, 20), date(2026, 12, 17))
    assert start == date(2026, 11, 20) and after is None         # Urlaub liegt vor dem Zeitraum


def test_api_vacation_streak_reminder_and_adaptive():
    c = client()
    today = date.fromisoformat(c.get("/api/state").json()["today"])
    with db.connect() as conn:
        db.set_setting(conn, "start_date", (today - timedelta(days=20)).isoformat())
        for i in range(1, 15):
            d = today - timedelta(days=i)
            if 4 <= i <= 8:                                   # Urlaub, nichts erfasst
                continue
            for meal in ("fruehstueck", "mittag", "abend"):
                log(conn, d.isoformat(), meal=meal)
    pauses = [{"start": (today - timedelta(days=8)).isoformat(), "end": (today - timedelta(days=4)).isoformat(),
               "kind": "urlaub"}]
    assert c.get("/api/state").json()["motivation"]["streak"] == 3
    r = c.put("/api/settings", headers=H, json={"pauses": pauses})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["settings"]["pauses"] == pauses
    assert st["motivation"]["streak"] == 9 and st["motivation"]["best_streak"] == 9
    with db.connect() as conn:
        est = adaptive.estimate(conn, db.get_settings(conn), today)
    assert est["status"] == "early" and est["after_pause"] == (today - timedelta(days=0)).isoformat()

    # Überschneidung und Unsinn werden abgelehnt
    clash = pauses + [{"start": (today - timedelta(days=4)).isoformat(), "end": today.isoformat(), "kind": "erhaltung"}]
    assert c.put("/api/settings", headers=H, json={"pauses": clash}).status_code == 400
    assert c.put("/api/settings", headers=H, json={"pauses": "x"}).status_code == 400

    # laufender Urlaub: keine Erinnerungen
    now = [{"start": today.isoformat(), "end": (today + timedelta(days=3)).isoformat(), "kind": "urlaub"}]
    st = c.put("/api/settings", headers=H, json={"pauses": now}).json()
    assert st["overview"]["plan"]["kind"] == "urlaub" and st["plan"]["pause_now"]["kind"] == "urlaub"
    with db.connect() as conn:
        assert plan.is_vacation(db.get_settings(conn), today)
    c.put("/api/settings", headers=H, json={"pauses": []})


def test_api_refeed_settings():
    c = client()
    r = c.put("/api/settings", headers=H, json={"refeed_days": [6, 5]})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["plan"]["refeed_days"] == [5, 6] and st["plan"]["week_days"] == [5, 6]
    assert st["plan"]["refeed"]["target"] == st["overview"]["budget"]["tdee"]
    wp = st["overview"]["week_plan"]
    assert [v["kind"] for v in wp.values()] == ["normal"] * 5 + ["refeed"] * 2
    assert sum(v["target"] for v in wp.values()) == 7 * st["overview"]["budget"]["target"]
    assert c.put("/api/settings", headers=H, json={"refeed_days": [1, 2, 3]}).status_code == 400

    week = st["plan"]["week_start"]
    st = c.put("/api/settings", headers=H, json={"refeed_week": {"week": week, "days": [4]}}).json()
    assert st["plan"]["week_days"] == [4] and st["plan"]["week_override"] and st["plan"]["refeed_days"] == [5, 6]
    assert st["plan"]["refeed_next"] == [5, 6]
    st = c.put("/api/settings", headers=H, json={"refeed_week": {"week": week, "days": None}}).json()
    assert st["plan"]["week_days"] == [5, 6] and not st["plan"]["week_override"]
    assert c.put("/api/settings", headers=H, json={"refeed_week": {"week": "2020-01-06", "days": [5]}}).status_code == 400

    # Statistik: Budget je Tag
    days = c.get("/api/stats?days=7").json()["days"]
    assert all("budget_points" in d and "plan" in d for d in days)
    with db.connect() as conn:
        for k in ("refeed_plan", "refeed_weeks"):
            conn.execute("DELETE FROM settings WHERE key = ?", (k,))


def test_budget_days_use_day_budget():
    """Ein Refeed-Samstag mit 60 P ist im Budget, auch wenn das normale Budget kleiner ist."""
    c = client()
    today = date.fromisoformat(c.get("/api/state").json()["today"])
    with db.connect() as conn:
        s = db.get_settings(conn)
        s["refeed_plan"] = [{"from": "2020-01-06", "days": [5, 6]}]
        dd = motivation.day_data(conn, s, today - timedelta(days=13), today)
        sat = next(k for k in dd["days"] if date.fromisoformat(k).weekday() == 5)
        mon = next(k for k in dd["days"] if date.fromisoformat(k).weekday() == 0)
        assert dd["days"][sat]["budget"] > dd["budget"]["points"] > dd["days"][mon]["budget"]
