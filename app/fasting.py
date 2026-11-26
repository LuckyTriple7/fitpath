"""Intervallfasten: 14:10, 16:8 oder 18:6, Standard aus.

Kein Start-Knopf nötig: Die Fastenzeit läuft von der letzten Mahlzeit bis zur ersten des nächsten Tages, beides
kommt aus den Uhrzeiten der Einträge. Getränke fast ohne Energie (schwarzer Kaffee, Tee, unter FREE_KCAL) brechen das
Fasten nicht. Einträge, die für einen anderen Tag nachgetragen wurden (Uhrzeit liegt nicht an ihrem Tag), zählen nicht,
weil ihre Uhrzeit nur den Zeitpunkt des Eintragens zeigt. Wer die letzte Mahlzeit nicht erfasst hat, startet von Hand
(Einstellung fast_since). Punkte, Budget und Wochenreserve ändern sich durch das Fasten nicht.
"""

from datetime import date, datetime, time, timedelta

from . import db

MODES = {"14:10": 14, "16:8": 16, "18:6": 18}
FREE_KCAL = 10                    # Kaffee schwarz, Tee, Wasser
TOLERANCE_H = 0.25                # 15 Minuten Spielraum für „geschafft“
MAX_GAP_H = 48                    # längere Lücken sind fehlende Einträge, kein Fasten


def hours(s: dict) -> int | None:
    return MODES.get(s.get("fast_mode") or "")


def window(s: dict, d: date) -> tuple:
    """Essensfenster, das am Tag d öffnet: (auf, zu) in Ortszeit. Darf über Mitternacht gehen."""
    h, m = (int(x) for x in (s.get("fast_window") or "12:00").split(":"))
    op = datetime.combine(d, time(h, m), tzinfo=db.TZ)
    return op, op + timedelta(hours=24 - hours(s))


def _manual(s: dict) -> datetime | None:
    try:
        return db.local(db.parse(s["fast_since"])) if s.get("fast_since") else None
    except ValueError:
        return None


def meal_times(conn, first: date, last: date) -> list:
    """Uhrzeiten (Ortszeit, sortiert) der Einträge mit Energie, die an ihrem Tag erfasst wurden."""
    rows = conn.execute("SELECT ts, day FROM food_log WHERE day BETWEEN ? AND ? AND COALESCE(kcal, 0) > ?",
                        (first.isoformat(), last.isoformat(), FREE_KCAL))
    out = []
    for r in rows:
        try:
            loc = db.local(db.parse(r["ts"]))
        except ValueError:
            continue
        if loc.date().isoformat() == r["day"]:
            out.append(loc)
    return sorted(out)


def days(conn, s: dict, first: date, last: date) -> dict:
    """{Tag: {hours, ok}} für Tage, deren Fastenzeit mit der ersten Mahlzeit endete."""
    fh = hours(s)
    if not fh:
        return {}
    times = meal_times(conn, first - timedelta(days=2), last)
    manual = _manual(s)
    out, d = {}, first
    while d <= last:
        firsts = [t for t in times if t.date() == d]
        if firsts:
            f = firsts[0]
            prev = [t for t in times if t < f]
            start = prev[-1] if prev else None
            if manual and manual < f and (not start or manual > start):
                start = manual
            if start and (f - start) <= timedelta(hours=MAX_GAP_H):
                h = (f - start).total_seconds() / 3600
                out[d.isoformat()] = {"hours": round(h, 1), "ok": h >= fh - TOLERANCE_H}
        d += timedelta(days=1)
    return out


def status(conn, s: dict, now: datetime | None = None) -> dict | None:
    """Alles für die Karte auf Heute und die Statistik. None, wenn Fasten aus ist."""
    fh = hours(s)
    if not fh:
        return None
    now = db.local(now or db.now_utc())
    today = now.date()
    past = [t for t in meal_times(conn, today - timedelta(days=2), today) if t <= now]
    manual = _manual(s)
    hist = days(conn, s, today - timedelta(days=29), today)
    streak, d = 0, today
    if today.isoformat() not in hist:      # heute noch nicht gegessen: Serie zählt ab gestern
        d -= timedelta(days=1)
    while d.isoformat() in hist and hist[d.isoformat()]["ok"]:
        streak += 1
        d -= timedelta(days=1)
    week = [hist[k] for k in hist if k > (today - timedelta(days=7)).isoformat()]
    op, cl = window(s, today)
    return {
        "mode": s["fast_mode"], "fast_hours": fh, "eat_hours": 24 - fh,
        "window_open": op.strftime("%H:%M"), "window_close": cl.strftime("%H:%M"),
        "last_meal": db.iso(past[-1]) if past else None,
        "manual_since": db.iso(manual) if manual and manual <= now else None,
        "today": hist.get(today.isoformat()),
        "streak": streak,
        "week_ok": sum(1 for x in week if x["ok"]), "week_days": len(week),
        "avg_hours": round(sum(x["hours"] for x in hist.values()) / len(hist), 1) if hist else None,
        "days": [{"day": (today - timedelta(days=i)).isoformat(), **(hist.get((today - timedelta(days=i)).isoformat()) or {})}
                 for i in range(13, -1, -1)],
    }


def phase(s: dict, now: datetime, last_meal: datetime | None) -> str:
    """Für die Erinnerungen: 'fasting' (außerhalb des Fensters), 'open' (Fenster offen, darin noch nichts gegessen)
    oder 'window' (Fenster offen, schon gegessen)."""
    for d in (now.date() - timedelta(days=1), now.date()):
        op, cl = window(s, d)
        if op <= now < cl:
            return "window" if last_meal and last_meal >= op else "open"
    return "fasting"
