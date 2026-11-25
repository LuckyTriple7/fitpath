"""Adaptiver Bedarf: tatsächlicher Verbrauch aus Einträgen und Gewichtsverlauf.

Verbrauch pro Tag = Ø Zufuhr − Gewichtsänderung pro Tag × 7.700 kcal/kg

- Zeitraum: die letzten 28 abgeschlossenen Tage (heute zählt nicht), frühestens ab dem ersten Eintrag.
- Zufuhr: Durchschnitt der vollständig erfassten Tage (mindestens zwei Mahlzeiten und 800 kcal).
  Halb erfasste Tage würden die Zufuhr und damit den Verbrauch zu niedrig schätzen.
- Gewichtsänderung: Steigung einer Regressionsgeraden über die Wiegewerte (nicht über den Trend,
  der läuft hinterher). Ihr Standardfehler ergibt die Unsicherheit in kcal.
- Urlaub (plan.py): Der Zeitraum beginnt frühestens RECOVERY_DAYS nach dem letzten Urlaub. Dort wird
  nicht erfasst, und die Zunahme danach ist zum großen Teil Wasser.
- Vergleich mit dem Modell: Formel (Grundumsatz × Aktivitätsfaktor) plus die im Zeitraum
  gutgeschriebene Aktivität. Die Differenz wird als Korrektur `tdee_adjust` vorgeschlagen.
"""

import math
from datetime import date, timedelta

from . import body, db, diary, plan, points

WINDOW_DAYS = 28
MIN_DAYS = 14                  # so viele Tage seit dem ersten Eintrag
MIN_WEIGHINS = 6
MIN_SPAN_DAYS = 10             # zwischen erstem und letztem Wiegewert im Zeitraum
MIN_LOGGED_SHARE = 0.7         # Anteil vollständig erfasster Tage
MIN_CHANGE = 100               # kleinere Abweichungen sind Rauschen, kein Vorschlag
MAX_ADJUST = 500               # Korrektur höchstens ± so viele kcal pro Tag
FULL_DAY_KCAL = 800
FULL_DAY_MEALS = 2


def _regression(points_xy: list) -> tuple[float, float]:
    """Steigung und deren Standardfehler."""
    n = len(points_xy)
    mx = sum(x for x, _ in points_xy) / n
    my = sum(y for _, y in points_xy) / n
    sxx = sum((x - mx) ** 2 for x, _ in points_xy)
    slope = sum((x - mx) * (y - my) for x, y in points_xy) / sxx
    resid = sum((y - (my + slope * (x - mx))) ** 2 for x, y in points_xy)
    se = math.sqrt(resid / (n - 2) / sxx) if n > 2 else float("inf")
    return slope, se


def _round50(v: float) -> int:
    return int(round(v / 50.0)) * 50


def estimate(conn, s: dict, today: date | None = None) -> dict:
    today = today or db.parse_day(db.today())
    last = today - timedelta(days=1)
    first_row = conn.execute("SELECT MIN(day) FROM food_log").fetchone()[0]
    current = int(s.get("tdee_adjust") or 0)
    base = {"adjust": current, "window_days": WINDOW_DAYS, "min_days": MIN_DAYS, "min_weighins": MIN_WEIGHINS}
    if not first_row:
        return {**base, "status": "early", "days": 0, "weighins": 0}
    start = max(last - timedelta(days=WINDOW_DAYS - 1), date.fromisoformat(first_row))
    start, after = plan.adaptive_start(s, start, last)
    if after:
        base["after_pause"] = after.isoformat()
        base["ready"] = (after + timedelta(days=MIN_DAYS)).isoformat()
    days = (last - start).days + 1
    weights = [(d, kg) for d, kg in body.daily_weights(conn, start.isoformat()) if d <= last.isoformat()]
    info = {**base, "days": max(days, 0), "weighins": len(weights), "first": start.isoformat(), "last": last.isoformat()}
    if days < MIN_DAYS or len(weights) < MIN_WEIGHINS:
        return {**info, "status": "early"}

    tot = diary.totals(conn, start.isoformat(), last.isoformat())
    full = [t for t in tot.values() if t["meals"] >= FULL_DAY_MEALS and t["kcal"] >= FULL_DAY_KCAL]
    info["logged"] = len(full)
    if len(full) < days * MIN_LOGGED_SHARE:
        return {**info, "status": "gaps", "need_logged": math.ceil(days * MIN_LOGGED_SHARE)}

    xy = [((date.fromisoformat(d) - start).days, kg) for d, kg in weights]
    span = xy[-1][0] - xy[0][0]
    if span < MIN_SPAN_DAYS:
        return {**info, "status": "early"}
    slope, se = _regression(xy)                       # kg pro Tag
    intake = sum(t["kcal"] for t in full) / len(full)
    real = intake - slope * points.KCAL_PER_KG
    err = se * points.KCAL_PER_KG

    # Modell ohne Korrektur, mit dem mittleren Gewicht und der gutgeschriebenen Aktivität im Zeitraum
    mean_kg = sum(kg for _, kg in weights) / len(weights)
    model = points.kcal_target({**s, "tdee_adjust": 0}, mean_kg, today)["tdee"]
    act = diary.activity(conn, start.isoformat(), last.isoformat(), mean_kg, int(s.get("steps_baseline") or 5000))
    act_kcal = sum(a["act_kcal"] for a in act.values()) / days

    share = len(full) / days
    if err <= 150 and share >= 0.85 and days >= 21:
        confidence = "hoch"
    elif err <= 300:
        confidence = "mittel"
    else:
        confidence = "niedrig"
    suggested = max(-MAX_ADJUST, min(MAX_ADJUST, _round50(real - model - act_kcal)))
    suggest = confidence != "niedrig" and abs(suggested - current) >= MIN_CHANGE
    # Wirkung aufs Budget mit dem aktuellen Gewicht (wie diary.budget), Untergrenze inklusive
    weight = body.budget_weight(conn, s)
    target_now = points.kcal_target(s, weight, today)["target"]
    target_new = points.kcal_target({**s, "tdee_adjust": suggested}, weight, today)["target"]
    suggest = suggest and target_new != target_now     # z. B. Untergrenze erreicht: Korrektur bewirkt nichts
    return {
        **info, "status": "ok",
        "intake": round(intake), "kg_per_week": round(slope * 7, 2),
        "real": round(real), "error": round(err), "confidence": confidence,
        "model": round(model), "activity": round(act_kcal),
        "suggested": suggested, "suggest": suggest,
        "target_now": target_now, "target_new": target_new,
        "points_now": points.points_budget(target_now), "points_new": points.points_budget(target_new),
    }
