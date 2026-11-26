"""Wochenrückblick: eine abgeschlossene Woche (Mo–So) auf einen Blick.

Tage im Budget, Bilanz, bester Tag, Trendgewicht, Ø-Nährwerte mit Richtwerten, Schritte, Training und der
Vergleich zur Vorwoche. Urlaubstage zählen wie in der Statistik nicht mit. Auf „Heute“ erscheint montags bis
mittwochs ein Hinweis auf die letzte Woche, bis man ihn öffnet oder wegklickt (Einstellung review_seen).
"""

from datetime import date, timedelta

from . import body, db, diary, plan, points

TEASER_DAYS = 3                   # Mo, Di, Mi
NUTRIENTS = ("kcal", "protein", "fat", "satfat", "carbs", "sugar", "fiber", "alcohol", "salt")


def last_monday(today: date) -> date:
    """Montag der letzten abgeschlossenen Woche."""
    return plan.monday(today) - timedelta(days=7)


def _days(conn, s: dict, b: dict, start: date) -> list:
    end = start + timedelta(days=6)
    first, last = start.isoformat(), end.isoformat()
    tot = diary.totals(conn, first, last)
    act = diary.activity(conn, first, last, b["weight"], int(s.get("steps_baseline") or 5000))
    budgets = plan.days(s, b, start, end)
    out = []
    for i in range(7):
        k = (start + timedelta(days=i)).isoformat()
        t, a, p = tot.get(k) or {}, act.get(k) or {}, budgets[k]
        used_p, used_k = int(t.get("points") or 0), float(t.get("kcal") or 0)
        act_p, act_k = int(a.get("act_points") or 0), float(a.get("act_kcal") or 0)
        out.append({
            "day": k, "plan": p["kind"], "entries": int(t.get("entries") or 0),
            "points": used_p, "kcal": round(used_k),
            "budget_points": p["points"], "budget_kcal": p["target"], "act_points": act_p, "act_kcal": round(act_k),
            "left_points": p["points"] + act_p - used_p, "left_kcal": round(p["target"] + act_k - used_k),
            "steps": a.get("steps"), "train_minutes": round(a.get("train_minutes") or 0),
            **{n: float(t.get(n) or 0) for n in NUTRIENTS if n != "kcal"},
            "_act": a,
        })
    return out


def _summary(days: list) -> dict:
    """Kennzahlen über die gezählten Tage (mit Einträgen, ohne Urlaub)."""
    logged = [d for d in days if d["entries"] and d["plan"] != "urlaub"]
    n = len(logged)
    return {
        "logged": n,
        "in_budget": sum(1 for d in logged if d["left_points"] >= 0),
        "balance_points": sum(d["left_points"] for d in logged),
        "balance_kcal": sum(d["left_kcal"] for d in logged),
        "avg_points": round(sum(d["points"] for d in logged) / n, 1) if n else None,
        "avg_kcal": round(sum(d["kcal"] for d in logged) / n) if n else None,
        "_logged": logged,
    }


def _trend(conn, start: date) -> dict | None:
    """Trendgewicht am Ende der Vorwoche und am Ende dieser Woche (letzter Wert davor)."""
    first, last = start.isoformat(), (start + timedelta(days=6)).isoformat()
    series = body.trend_series(body.daily_weights(conn))
    before = [x for x in series if x["day"] < first]
    upto = [x for x in series if x["day"] <= last]
    inside = [x for x in series if first <= x["day"] <= last]
    if not upto or not inside:
        return None
    ref = before[-1] if before else inside[0]
    end = upto[-1]
    return {"start": ref["trend"], "end": end["trend"], "delta": round(end["trend"] - ref["trend"], 2),
            "weighings": len(inside), "last_weight": inside[-1]["weight"]}


def week(conn, s: dict, start: date) -> dict:
    """Rückblick für die Woche ab `start` (Montag)."""
    start = plan.monday(start)
    today = db.parse_day(db.today())
    b = diary.budget(conn, s)
    days = _days(conn, s, b, start)
    cur = _summary(days)
    prev = _summary(_days(conn, s, b, start - timedelta(days=7)))
    logged = cur.pop("_logged")
    prev.pop("_logged")
    n = len(logged) or 1
    avg = {k: round(sum(d[k] for d in logged) / n, 1) for k in NUTRIENTS if k != "kcal"}
    avg["kcal"] = cur["avg_kcal"] or 0
    avg_target = sum(d["budget_kcal"] for d in logged) / n if logged else b["target"]
    best = max((d for d in logged if d["left_points"] >= 0), key=lambda d: (d["left_points"], d["left_kcal"]), default=None)
    steps = [d["steps"] for d in days if d["steps"]]
    train = diary.training_summary({d["day"]: d["_act"] for d in days if d["_act"]})
    kinds = [d["plan"] for d in days]
    nxt = start + timedelta(days=7)
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(days=6)).isoformat(),
        "prev_start": (start - timedelta(days=7)).isoformat(),
        "next_start": nxt.isoformat() if nxt <= last_monday(today) else None,
        "complete": start + timedelta(days=6) < today,
        "days": [{k: v for k, v in d.items() if not k.startswith("_") and k not in NUTRIENTS} for d in days],
        **cur,
        "best": {"day": best["day"], "left_points": best["left_points"], "left_kcal": best["left_kcal"]} if best else None,
        "avg": avg,
        "targets": {"protein": round(b["weight"] * 1.0), "fiber": 30, "sugar": 50,
                    "satfat": round(avg_target * .1 / 9), "salt": 6},
        "steps_avg": round(sum(steps) / len(steps)) if steps else None,
        "steps_days": len(steps),
        "training": train,
        "trend": _trend(conn, start),
        "plan_days": {k: kinds.count(k) for k in ("refeed", "urlaub", "erhaltung") if k in kinds},
        "prev": prev,
    }


def teaser(conn, s: dict, today: date | None = None) -> dict | None:
    """Kurzfassung der letzten Woche für „Heute“ (Mo–Mi, bis gesehen). None, wenn nichts zu zeigen ist."""
    today = today or db.parse_day(db.today())
    start = last_monday(today)
    if today.weekday() >= TEASER_DAYS or s.get("review_seen") == start.isoformat():
        return None
    r = week(conn, s, start)
    if not r["logged"]:
        return None
    return {"start": r["start"], "end": r["end"], "logged": r["logged"], "in_budget": r["in_budget"],
            "balance_points": r["balance_points"], "balance_kcal": r["balance_kcal"],
            "trend_delta": r["trend"]["delta"] if r["trend"] else None}
