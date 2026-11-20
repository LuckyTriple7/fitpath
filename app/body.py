"""Gewicht: Trend, Wochentempo, Meilensteine.

Das Trendgewicht glättet die täglichen Schwankungen (Wasser, Salz, Verdauung)
exponentiell mit α = 0,1: trend = trend_vorher + 0,1 × (Waage − trend_vorher).
Tage ohne Wiegen übernehmen den Trend unverändert.
"""

from datetime import date, timedelta

from . import db, points

ALPHA = 0.1


def daily_weights(conn, since: str | None = None) -> list:
    """Ein Wert pro Tag: das erste Wiegen des Tages (morgens nüchtern ist am vergleichbarsten)."""
    sql = ("SELECT day, value FROM body b WHERE kind = 'weight' AND ts = "
           "(SELECT MIN(ts) FROM body b2 WHERE b2.kind = 'weight' AND b2.day = b.day)")
    args = []
    if since:
        sql += " AND day >= ?"
        args.append(since)
    rows = conn.execute(sql + " GROUP BY day ORDER BY day", args).fetchall()
    return [(r["day"], float(r["value"])) for r in rows]


def trend_series(weights: list) -> list:
    """weights: [(Tag, kg)] aufsteigend. Ergebnis: [{day, weight, trend}]."""
    out, trend = [], None
    for day, kg in weights:
        trend = kg if trend is None else trend + ALPHA * (kg - trend)
        out.append({"day": day, "weight": round(kg, 2), "trend": round(trend, 2)})
    return out


def rate_per_week(series: list, today: date, days: int = 21) -> float | None:
    """Steigung des Trends über die letzten Tage (lineare Regression) in kg pro Woche."""
    since = (today - timedelta(days=days)).isoformat()
    pts = [((date.fromisoformat(x["day"]) - today).days, x["trend"]) for x in series if x["day"] >= since]
    if len(pts) < 4 or pts[-1][0] - pts[0][0] < 7:
        return None
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    var = sum((p[0] - mx) ** 2 for p in pts)
    if not var:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / var
    return round(slope * 7, 2)


def forecast(current: float, goal: float, rate: float | None, s: dict, today: date) -> dict | None:
    """Wann das Zielgewicht bei gleichem Tempo erreicht wäre.

    Grundlage ist das echte Tempo (Trend der letzten 3 Wochen), solange es das noch nicht gibt das geplante.
    Schneller als 1 % des Gewichts pro Woche wird nicht gerechnet: Am Anfang ist viel davon Wasser, das
    würde die Prognose zu früh machen. Angezeigt wird sie ungefähr (Anfang/Mitte/Ende eines Monats)."""
    if s.get("mode") != "lose" or not goal or not current or current <= goal:
        return None
    if rate is not None:
        if rate > -0.05:
            return {"basis": "trend", "stalled": True}
        per_week, basis = -rate, "trend"
    else:
        per_week, basis = float(s.get("pace") or 0), "plan"
        if per_week <= 0:
            return None
    cap = current * points.MAX_LOSS_SHARE_WEEK
    capped = per_week > cap
    per_week = min(per_week, cap)
    weeks = (current - goal) / per_week
    out = {"basis": basis, "per_week": round(per_week, 2), "capped": capped, "weeks": round(weeks)}
    if weeks > 260:
        out["far"] = True
    else:
        out["date"] = (today + timedelta(days=round(weeks * 7))).isoformat()
    return out


def summary(conn, s: dict) -> dict:
    """Aktueller Stand für Start und Gewichts-Seite."""
    series = trend_series(daily_weights(conn))
    today = db.parse_day(db.today())
    start = float(s.get("start_weight") or 0) or (series[0]["weight"] if series else 0)
    goal = float(s.get("goal_weight") or 0)
    last = series[-1] if series else None
    current = last["trend"] if last else start
    lost = round(start - current, 1) if start else 0
    total = start - goal if start and goal and start > goal else 0
    milestones = []
    if start:
        for pct in (5, 10, 15):
            target = round(start * (1 - pct / 100), 1)
            if goal and target < goal - 0.05 and pct > 5:
                break
            milestones.append({"pct": pct, "kg": target, "done": current <= target})
    if total:
        milestones.append({"pct": None, "kg": goal, "done": current <= goal, "goal": True})
    height = float(s.get("height_cm") or 0) / 100
    return {
        "weight": last["weight"] if last else None,
        "trend": round(current, 1) if current else None,
        "day": last["day"] if last else None,
        "weighed_today": bool(last and last["day"] == today.isoformat()),
        "start": start, "goal": goal, "lost": lost,
        "progress": round(max(0.0, min(lost / total, 1.0)), 3) if total else None,
        "rate": rate_per_week(series, today),
        "forecast": forecast(current, goal, rate_per_week(series, today), s, today) if total else None,
        "bmi": round(current / (height * height), 1) if current and height else None,
        "milestones": milestones,
        "count": len(series),
    }


def budget_weight(conn, s: dict) -> float:
    """Gewicht für die Budget-Berechnung: Trend, sonst Startgewicht."""
    series = trend_series(daily_weights(conn))
    if series:
        return series[-1]["trend"]
    return float(s.get("start_weight") or 80)
