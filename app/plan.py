"""Tagesplan: Budget je Tag mit Refeed-Tagen und Pausen.

Refeed-Tage (nur im Modus „Abnehmen“): An festen Wochentagen gilt der Bedarf statt des Ziels, also kein
Defizit. Die übrigen Tage der Woche tragen das Defizit dieser Tage mit, damit die Woche gleich bleibt:
    übrige Tage = Ziel − Refeed-Tage × (Bedarf − Ziel) ÷ übrige Tage
Fallen die übrigen Tage dabei unter die Untergrenze (points.KCAL_FLOOR), bleiben sie auf der Untergrenze
und die Refeed-Tage bekommen nur, was dadurch frei wird. Bringt das weniger als MIN_REFEED_UPLIFT kcal,
gibt es in der Woche keinen Refeed. Studien dazu: Campbell u. a. 2020 (2 Refeed-Tage je Woche, gleiches
Wochendefizit, etwas mehr fettfreie Masse und Grundumsatz erhalten).

Welche Wochentage gelten, steht in `refeed_plan` ([{from: Montag, days: [5, 6]}], jeweils ab dieser Woche),
damit eine Änderung frühere Wochen nicht umschreibt. `refeed_weeks` ({Montag: [Tage]}) tauscht für eine
einzelne Woche.

Pausen (`pauses`: [{start, end, kind}]):
- „urlaub“: nichts erfassen. Keine Erinnerungen; Urlaubstage zählen nicht für Wochenreserve, Serie,
  Tage im Budget und den Echten Bedarf (dort auch die RECOVERY_DAYS danach nicht: Das Wasser vom
  salzigen Urlaubsessen geht erst wieder herunter).
- „erhaltung“ (Diätpause): weiter erfassen, Budget = Bedarf.
In einer Woche mit Pausentagen gibt es keinen Refeed: Die wenigen übrigen Tage müssten sonst das ganze
Defizit tragen, und die Pause ist ohnehin schon eine Erholung.
"""

from datetime import date, timedelta

from . import points

KINDS = ("urlaub", "erhaltung")
MAX_DAYS = {"urlaub": 60, "erhaltung": 28}
MAX_REFEED_DAYS = 2
MIN_REFEED_UPLIFT = 100        # kcal: weniger mehr am Refeed-Tag lohnt nicht
RECOVERY_DAYS = 3              # nach dem Urlaub, für den Echten Bedarf
KEEP_DAYS = 400                # so lange bleiben vergangene Pausen und Refeed-Pläne gespeichert


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


# ---------- Pausen ----------

def pause_on(s: dict, day) -> dict | None:
    k = _d(day).isoformat()
    return next((p for p in s.get("pauses") or [] if p["start"] <= k <= p["end"]), None)


def is_vacation(s: dict, day) -> bool:
    p = pause_on(s, day)
    return bool(p and p["kind"] == "urlaub")


def clean_pauses(value, today: date | None = None) -> list:
    """Prüft die Liste aus der Oberfläche. ValueError bei Unsinn, alte Pausen fallen weg."""
    today = today or date.today()
    out = []
    for p in list(value)[:40]:
        p = dict(p)
        kind = p.get("kind")
        start, end = _d(p["start"]), _d(p["end"])
        if kind not in KINDS or end < start or (end - start).days + 1 > MAX_DAYS[kind]:
            raise ValueError
        if end < today - timedelta(days=KEEP_DAYS):
            continue
        out.append({"start": start.isoformat(), "end": end.isoformat(), "kind": kind})
    out.sort(key=lambda p: p["start"])
    for a, b in zip(out, out[1:]):
        if b["start"] <= a["end"]:
            raise ValueError
    return out


# ---------- Refeed ----------

def refeed_days(s: dict, week: date) -> list:
    """Refeed-Wochentage (0 = Montag) der Woche, die mit `week` (Montag) beginnt."""
    k = week.isoformat()
    override = (s.get("refeed_weeks") or {}).get(k)
    if override is not None:
        return list(override)
    current = []
    for entry in s.get("refeed_plan") or []:
        if entry["from"] <= k:
            current = entry["days"]
    return list(current)


def clean_days(value) -> list:
    days = sorted({int(x) for x in list(value)})
    if len(days) > MAX_REFEED_DAYS or any(not 0 <= x <= 6 for x in days):
        raise ValueError
    return days


def set_refeed(s: dict, days: list, today: date) -> list:
    """Neuer `refeed_plan`: gilt ab dieser Woche, frühere Wochen bleiben, wie sie waren."""
    week = monday(today).isoformat()
    keep_from = (today - timedelta(days=KEEP_DAYS)).isoformat()
    plan = [e for e in s.get("refeed_plan") or [] if e["from"] < week]
    # das älteste noch nötige Stück behalten (es gilt bis zur nächsten Änderung)
    while len(plan) > 1 and plan[1]["from"] <= keep_from:
        plan.pop(0)
    if (plan[-1]["days"] if plan else []) != days:
        plan.append({"from": week, "days": days})
    return plan


def set_week(s: dict, week: date, days: list | None, today: date) -> dict:
    """Tausch für eine Woche (diese oder nächste); None nimmt ihn zurück."""
    if week != monday(week) or not monday(today) <= week <= monday(today) + timedelta(days=7):
        raise ValueError
    weeks = {k: v for k, v in (s.get("refeed_weeks") or {}).items()
             if k >= (today - timedelta(days=KEEP_DAYS)).isoformat()}
    weeks.pop(week.isoformat(), None)
    if days is not None:
        plain = refeed_days({**s, "refeed_weeks": {}}, week)
        if days != plain:
            weeks[week.isoformat()] = days
    return weeks


# ---------- Budget je Tag ----------

def week(s: dict, kt: dict, week_start: date) -> dict:
    """{JJJJ-MM-TT: {kind, target, points, pause}} für die 7 Tage ab `week_start` (Montag).
    kt: points.kcal_target (mit tdee, target, floor). kind: normal | refeed | urlaub | erhaltung."""
    days = [week_start + timedelta(days=i) for i in range(7)]
    pauses = {d: pause_on(s, d) for d in days}
    tdee, target, floor = kt["tdee"], kt["target"], kt["floor"]
    refeed = []
    if s.get("mode", "lose") == "lose" and tdee > target and not any(pauses.values()):
        wd = refeed_days(s, week_start)
        refeed = [d for d in days if d.weekday() in wd]
    hi = lo = float(target)
    n = 7 - len(refeed)
    if refeed and n:
        hi, lo = float(tdee), target - len(refeed) * (tdee - target) / n
        if lo < floor:
            lo = float(floor)
            hi = target + (target - floor) * n / len(refeed)
        if hi - target < MIN_REFEED_UPLIFT:
            refeed, hi, lo = [], float(target), float(target)
    out = {}
    for d in days:
        p = pauses[d]
        if p:
            kind, t = p["kind"], float(tdee)
        elif d in refeed:
            kind, t = "refeed", hi
        else:
            kind, t = "normal", lo
        out[d.isoformat()] = {"kind": kind, "target": round(t), "points": points.points_budget(t), "pause": p}
    return out


def days(s: dict, kt: dict, first, last) -> dict:
    """Budget je Tag für einen beliebigen Zeitraum."""
    first, last = _d(first), _d(last)
    out, w = {}, monday(first)
    while w <= last:
        out.update(week(s, kt, w))
        w += timedelta(days=7)
    return {k: v for k, v in out.items() if first.isoformat() <= k <= last.isoformat()}


def adaptive_start(s: dict, start: date, last: date) -> tuple[date, date | None]:
    """Erster Tag, ab dem der Echte Bedarf rechnen darf: nach dem letzten Urlaub im Zeitraum plus
    RECOVERY_DAYS. Liefert (Start, Tag nach dem Urlaub oder None)."""
    after = None
    for p in s.get("pauses") or []:
        if p["kind"] != "urlaub" or _d(p["start"]) > last:
            continue
        cut = _d(p["end"]) + timedelta(days=RECOVERY_DAYS + 1)
        if cut > start:
            start, after = cut, cut
    return start, after


def info(s: dict, kt: dict, today: date) -> dict:
    """Für die Oberfläche (Mehr): Refeed dieser Woche, laufende und kommende Pausen."""
    this = monday(today)
    wk = week(s, kt, this)
    ref = [v for v in wk.values() if v["kind"] == "refeed"]
    norm = [v for v in wk.values() if v["kind"] == "normal"]
    wanted = refeed_days(s, this)
    blocked = None
    if wanted and not ref:
        if s.get("mode", "lose") != "lose" or kt["tdee"] <= kt["target"]:
            blocked = "keep"
        elif any(v["pause"] for v in wk.values()):
            blocked = "pause"
        else:
            blocked = "floor"
    k = today.isoformat()
    return {
        "refeed_days": refeed_days({**s, "refeed_weeks": {}}, this),
        "refeed_next": refeed_days(s, this + timedelta(days=7)),
        "week_days": wanted,
        "week_override": this.isoformat() in (s.get("refeed_weeks") or {}),
        "week_start": this.isoformat(),
        "refeed": {"points": ref[0]["points"], "target": ref[0]["target"]} if ref else None,
        "normal": {"points": norm[0]["points"], "target": norm[0]["target"]} if ref and norm else None,
        "blocked": blocked,
        "pauses": [p for p in s.get("pauses") or [] if p["end"] >= (today - timedelta(days=30)).isoformat()],
        "pause_now": pause_on(s, today),
        "pause_next": next((p for p in s.get("pauses") or [] if p["start"] > k), None),
        "max_days": MAX_DAYS,
    }
