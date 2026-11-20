"""Tagebuch: Einträge, Tagessummen, Budget mit Aktivität und Reserve, Verlauf."""

from datetime import date, timedelta

from . import body, db, points, training

MEALS = ("fruehstueck", "mittag", "abend", "snack")


def entry_out(row) -> dict:
    e = dict(row)
    e["zero"] = bool(e.get("zero"))
    e["points"] = points.entry_points(e)
    grams = float(e.get("grams") or 0)
    e["ampel"] = points.ampel(float(e.get("kcal") or 0) / grams * 100) if grams else "green"
    return e


def entries(conn, day: str) -> list:
    return [entry_out(r) for r in conn.execute(
        "SELECT * FROM food_log WHERE day = ? ORDER BY ts, created", (day,))]


def totals(conn, first: str, last: str) -> dict:
    """{Tag: {points, kcal, protein, fat, satfat, carbs, sugar, fiber, alcohol, entries, kcal_green/yellow/red}}"""
    out = {}
    for r in conn.execute("SELECT * FROM food_log WHERE day BETWEEN ? AND ?", (first, last)):
        e = entry_out(r)
        t = out.setdefault(e["day"], {"points": 0, "entries": 0, "kcal": 0.0, "protein": 0.0, "fat": 0.0, "satfat": 0.0,
                                      "carbs": 0.0, "sugar": 0.0, "fiber": 0.0, "alcohol": 0.0,
                                      "kcal_green": 0.0, "kcal_yellow": 0.0, "kcal_red": 0.0, "meals": set()})
        t["points"] += e["points"]
        t["entries"] += 1
        t["meals"].add(e["meal"])
        for k in ("kcal", "protein", "fat", "satfat", "carbs", "sugar", "fiber", "alcohol"):
            t[k] += float(e.get(k) or 0)
        t["kcal_" + e["ampel"]] += float(e.get("kcal") or 0)
    for t in out.values():
        t["meals"] = len(t["meals"])
    return out


def activity(conn, first: str, last: str, weight: float, baseline: int) -> dict:
    """{Tag: {steps, active_kcal, source, act_points, act_kcal, step_kcal, train_kcal, workouts, …}}.
    Schritte: je Tag der höchste Wert aller Quellen. Aktivitätspunkte = Schritte + Training (training.py)."""
    rows = {}
    for r in conn.execute("SELECT * FROM activity WHERE day BETWEEN ? AND ? ORDER BY day", (first, last)):
        cur = rows.get(r["day"])
        if not cur or (cur["steps"] or 0) < (r["steps"] or 0):
            rows[r["day"]] = r
    workouts = training.by_day(conn, first, last)
    out = {}
    for day in sorted(set(rows) | set(workouts)):
        r = rows.get(day)
        steps = r["steps"] if r else None
        bonus = points.activity_bonus(steps, weight, baseline)
        tr = training.day_credit(workouts.get(day, []), weight, bonus["extra_steps"])
        credited = bonus["kcal_raw"] + tr["kcal"]
        out[day] = {"steps": steps, "active_kcal": r["active_kcal"] if r else None, "source": r["source"] if r else None,
                    "updated": r["updated"] if r else None, "extra_steps": bonus["extra_steps"],
                    "act_points": points.round_points(credited / points.KCAL_PER_POINT), "act_kcal": round(credited),
                    "step_kcal": bonus["kcal"], "train_kcal": round(tr["kcal"]), "train_capped": tr["capped"],
                    "train_minutes": tr["train_minutes"], "swim": tr["swim"], "workouts": tr["workouts"]}
    return out


def budget(conn, s: dict) -> dict:
    weight = body.budget_weight(conn, s)
    kt = points.kcal_target(s, weight)
    return {**kt, "points": points.points_budget(kt["target"]), "weight": round(weight, 1)}


def overview(conn, s: dict, day: str) -> dict:
    """Alles für die Seite „Heute“ (oder einen anderen Tag)."""
    d = db.parse_day(day)
    b = budget(conn, s)
    first = points.week_start(d).isoformat()
    tot = totals(conn, first, day)
    act = activity(conn, first, day, b["weight"], int(s.get("steps_baseline") or 5000))
    merged = {k: {**tot.get(k, {}), **act.get(k, {})} for k in set(tot) | set(act)}
    week = points.week_summary(merged, d, b["points"], b["target"])
    t = tot.get(day) or {}
    # Für „Wie gestern“: Mahlzeiten des Vortags
    prev_day = (d - timedelta(days=1)).isoformat()
    prev = {}
    for e in entries(conn, prev_day):
        m = prev.setdefault(e["meal"], {"count": 0, "points": 0, "kcal": 0.0, "names": [], "items": []})
        m["count"] += 1
        m["items"].append({k: e.get(k) for k in ("id", "name", "grams", "portion", "points", "kcal", "ampel")})
        m["points"] += e["points"]
        m["kcal"] += float(e.get("kcal") or 0)
        if len(m["names"]) < 3:
            m["names"].append(e["name"].split(",")[0][:30])
    return {
        "day": day,
        "prev_day": prev_day,
        "prev": prev,
        "budget": b,
        "week": week,
        "entries": entries(conn, day),
        "totals": {k: round(v, 1) if isinstance(v, float) else v for k, v in t.items()},
        "activity": act.get(day),
    }


def history(conn, s: dict, days: int) -> dict:
    """Verlauf für die Statistik."""
    today = db.parse_day(db.today())
    first = (today - timedelta(days=days - 1)).isoformat()
    b = budget(conn, s)
    tot = totals(conn, first, today.isoformat())
    act = activity(conn, first, today.isoformat(), b["weight"], int(s.get("steps_baseline") or 5000))
    series = []
    d = date.fromisoformat(first)
    while d <= today:
        k = d.isoformat()
        t, a = tot.get(k) or {}, act.get(k) or {}
        series.append({
            "day": k, "points": t.get("points", 0), "kcal": round(t.get("kcal", 0)), "entries": t.get("entries", 0),
            "protein": round(t.get("protein", 0)), "fat": round(t.get("fat", 0)), "carbs": round(t.get("carbs", 0)),
            "fiber": round(t.get("fiber", 0), 1), "sugar": round(t.get("sugar", 0)),
            "steps": a.get("steps"), "act_points": a.get("act_points", 0), "act_kcal": a.get("act_kcal", 0),
            "train_kcal": a.get("train_kcal", 0), "train_minutes": a.get("train_minutes", 0),
        })
        d += timedelta(days=1)
    logged = [x for x in series if x["entries"] and x["day"] != today.isoformat()]
    n = len(logged) or 1
    green = sum(t.get("kcal_green", 0) for t in tot.values())
    yellow = sum(t.get("kcal_yellow", 0) for t in tot.values())
    red = sum(t.get("kcal_red", 0) for t in tot.values())
    all_kcal = green + yellow + red or 1
    in_budget = sum(1 for x in logged if x["points"] <= b["points"] + x["act_points"])
    with_steps = [x["steps"] for x in series if x["steps"]]
    weights = body.trend_series(body.daily_weights(conn))
    return {
        "days": series,
        "budget": b,
        "avg": {
            "points": round(sum(x["points"] for x in logged) / n, 1),
            "kcal": round(sum(x["kcal"] for x in logged) / n),
            "protein": round(sum(x["protein"] for x in logged) / n),
            "fat": round(sum(x["fat"] for x in logged) / n),
            "carbs": round(sum(x["carbs"] for x in logged) / n),
            "fiber": round(sum(x["fiber"] for x in logged) / n, 1),
            "steps": round(sum(with_steps) / len(with_steps)) if with_steps else None,
        },
        "logged_days": len(logged),
        "in_budget": in_budget,
        "ampel": {"green": round(green / all_kcal, 3), "yellow": round(yellow / all_kcal, 3), "red": round(red / all_kcal, 3)},
        "weights": [w for w in weights if w["day"] >= first],
        "top": top_foods(conn, first),
    }


def top_foods(conn, first: str, limit: int = 8) -> list:
    """Größte Punkte-Lieferanten im Zeitraum."""
    agg = {}
    for r in conn.execute("SELECT * FROM food_log WHERE day >= ?", (first,)):
        e = entry_out(r)
        a = agg.setdefault(e["name"], {"name": e["name"], "points": 0, "kcal": 0.0, "count": 0})
        a["points"] += e["points"]
        a["kcal"] += float(e.get("kcal") or 0)
        a["count"] += 1
    out = sorted(agg.values(), key=lambda x: (-x["points"], -x["kcal"]))[:limit]
    for x in out:
        x["kcal"] = round(x["kcal"])
    return out
