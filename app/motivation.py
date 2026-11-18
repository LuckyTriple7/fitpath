"""Motivation: Level und Erfahrungspunkte, Abzeichen, Wochen-Challenge, Heißhunger-Auswertung.

Alles wird aus den vorhandenen Daten berechnet. Gespeichert werden nur der Zeitpunkt,
an dem ein Abzeichen zum ersten Mal erreicht wurde (`unlocked`), geschaffte Challenges
(`challenges_done`) und gewechselte Challenges (`challenge_skips`). Ein einmal erreichtes
Abzeichen bleibt, auch wenn z. B. das Gewicht später wieder steigt.

Erfahrungspunkte (XP):
  erfasster Tag 10 · Tag im Budget 10 · Schrittziel erreicht 10 · gewogen 5 ·
  Heißhunger überstanden 15 · Abzeichen 50 · Wochen-Challenge 50
"""

from datetime import date, timedelta

from . import body, db, diary, points

XP = {"logged": 10, "budget": 10, "steps": 10, "weigh": 5, "resisted": 15, "badge": 50, "challenge": 50}

LEVELS = [
    (0, "Erster Schritt"), (100, "Losgelaufen"), (250, "Spaziergänger"), (500, "Wanderer"),
    (900, "Pfadfinder"), (1400, "Bergsteiger"), (2000, "Gipfelstürmer"), (2800, "Ausdauernd"),
    (3800, "Langstreckler"), (5000, "Routinier"), (6500, "Vorbild"), (8500, "Legende"),
]

# (id, Symbol, Titel, Kennzahl, Ziel)
BADGES = [
    ("first", "🌱", "Erster Eintrag", "logged_days", 1),
    ("streak3", "🔥", "3 Tage in Folge erfasst", "best_streak", 3),
    ("streak7", "🔥", "7 Tage in Folge erfasst", "best_streak", 7),
    ("streak30", "🏅", "30 Tage in Folge erfasst", "best_streak", 30),
    ("budget7", "🎯", "7 Tage im Budget", "budget_days", 7),
    ("budget30", "🎯", "30 Tage im Budget", "budget_days", 30),
    ("steps1", "👟", "Schrittziel erreicht", "steps_goal_days", 1),
    ("steps10", "👟", "10× Schrittziel", "steps_goal_days", 10),
    ("steps20k", "🚀", "20.000 Schritte an einem Tag", "max_steps", 20000),
    ("weigh10", "⚖️", "10× gewogen", "weigh_days", 10),
    ("loss2", "📉", "−2 % Gewicht", "loss_pct", 2),
    ("loss5", "❤️", "−5 % Gewicht", "loss_pct", 5),
    ("loss10", "💪", "−10 % Gewicht", "loss_pct", 10),
    ("goal", "🏆", "Zielgewicht erreicht", "goal_reached", 1),
    ("recipe", "🍲", "Erstes eigenes Gericht", "recipes", 1),
    ("sos5", "🧘", "5× Heißhunger überstanden", "resisted", 5),
]

# (id, Symbol, Titel, Kennzahl der laufenden Woche, Ziel)
CHALLENGES = [
    ("log5", "📝", "An 5 Tagen alle Mahlzeiten erfassen", "full_days", 5),
    ("budget4", "🎯", "4 Tage im Budget", "budget_days", 4),
    ("steps3", "👟", "3 Tage über dem Schrittziel", "steps_goal_days", 3),
    ("zero10", "🥦", "10× Obst oder Gemüse (0 Punkte)", "zero_entries", 10),
    ("weigh3", "⚖️", "3× wiegen", "weigh_days", 3),
    ("protein3", "🍗", "An 3 Tagen genug Eiweiß (1 g je kg)", "protein_days", 3),
    ("fiber3", "🌾", "An 3 Tagen 25 g Ballaststoffe", "fiber_days", 3),
    ("recipe1", "🍲", "Ein neues Gericht anlegen", "recipes", 1),
    ("sos2", "🧘", "2× Heißhunger aussitzen", "resisted", 2),
]

DEFAULT_TRIGGERS = ["Stress", "Langeweile", "Abends vor dem Fernseher", "Nach dem Essen", "Müdigkeit",
                    "Frust", "Gesellschaft", "Süßes gesehen"]
DEFAULT_PLANS = {
    "Stress": "Erst 10 tiefe Atemzüge, dann ein Glas Wasser",
    "Langeweile": "10 Minuten raus an die Luft oder jemanden anrufen",
    "Abends vor dem Fernseher": "Tee kochen, Gemüsesticks oder Gurke statt Chips",
    "Nach dem Essen": "Zähne putzen – danach schmeckt Süßes nicht",
    "Müdigkeit": "Kurz hinlegen oder früher ins Bett, statt Zucker als Wachmacher",
    "Frust": "Einmal um den Block gehen und dann neu entscheiden",
    "Süßes gesehen": "Aus dem Blick räumen und 10 Minuten warten",
}


def _days(first: date, last: date):
    d = first
    while d <= last:
        yield d
        d += timedelta(days=1)


def day_data(conn, s: dict, first: date, last: date) -> dict:
    """Je Tag: Einträge, Mahlzeiten, Punkte, 0-Punkte-Einträge, Eiweiß, Ballaststoffe, Schritte,
    Aktivitätspunkte, gewogen, Heißhunger überstanden."""
    f, l = first.isoformat(), last.isoformat()
    b = diary.budget(conn, s)
    tot = diary.totals(conn, f, l)
    act = diary.activity(conn, f, l, b["weight"], int(s.get("steps_baseline") or 5000))
    zero = dict(conn.execute("SELECT day, COUNT(*) FROM food_log WHERE zero = 1 AND day BETWEEN ? AND ? GROUP BY day",
                             (f, l)).fetchall())
    weighed = {r[0] for r in conn.execute("SELECT DISTINCT day FROM body WHERE kind = 'weight' AND day BETWEEN ? AND ?", (f, l))}
    resisted = {}
    for r in conn.execute("SELECT ts FROM events WHERE kind = 'craving' AND resisted = 1"):
        k = db.local_day(db.parse(r[0]))
        if f <= k <= l:
            resisted[k] = resisted.get(k, 0) + 1
    out = {}
    for d in _days(first, last):
        k = d.isoformat()
        t, a = tot.get(k) or {}, act.get(k) or {}
        out[k] = {"entries": t.get("entries", 0), "meals": t.get("meals", 0), "points": t.get("points", 0),
                  "protein": t.get("protein", 0.0), "fiber": t.get("fiber", 0.0), "zero": zero.get(k, 0),
                  "steps": a.get("steps") or 0, "act_points": a.get("act_points", 0),
                  "weighed": k in weighed, "resisted": resisted.get(k, 0)}
    return {"days": out, "budget": b}


def _start(conn, s: dict, today: date) -> date:
    cands = [today]
    if s.get("start_date"):
        cands.append(db.parse_day(s["start_date"]))
    for q in ("SELECT MIN(day) FROM food_log", "SELECT MIN(day) FROM body", "SELECT MIN(day) FROM activity"):
        v = conn.execute(q).fetchone()[0]
        if v:
            cands.append(db.parse_day(v))
    return max(min(cands), today - timedelta(days=730))


def _in_budget(x: dict, budget_points: int) -> bool:
    return x["entries"] > 0 and x["points"] <= budget_points + x["act_points"]


def summary(conn, s: dict, today: date | None = None) -> dict:
    """Kennzahlen über die ganze Zeit."""
    today = today or db.parse_day(db.today())
    dd = day_data(conn, s, _start(conn, s, today), today)
    days, b = dd["days"], dd["budget"]
    goal = int(s.get("steps_goal") or 8000)
    keys = sorted(days)
    past = [k for k in keys if k < today.isoformat()]
    logged = [k for k in keys if days[k]["entries"]]
    # Serie: aufeinanderfolgende Tage mit Eintrag, endend heute oder gestern
    best = cur = 0
    for k in keys:
        cur = cur + 1 if days[k]["entries"] else 0
        best = max(best, cur)
    streak = 0
    for k in reversed(keys):
        if days[k]["entries"]:
            streak += 1
        elif k == today.isoformat():
            continue          # heute noch nichts erfasst: Serie zählt bis gestern
        else:
            break
    bs = body.summary(conn, s)
    start_w, trend = bs.get("start") or 0, bs.get("trend") or 0
    return {
        "logged_days": len(logged),
        "streak": streak,
        "best_streak": best,
        "budget_days": sum(1 for k in past if _in_budget(days[k], b["points"])),
        "steps_goal_days": sum(1 for k in keys if days[k]["steps"] >= goal),
        "max_steps": max((days[k]["steps"] for k in keys), default=0),
        "weigh_days": sum(1 for k in keys if days[k]["weighed"]),
        "loss_pct": round((start_w - trend) / start_w * 100, 1) if start_w and trend else 0,
        "goal_reached": 1 if trend and bs.get("goal") and trend <= bs["goal"] else 0,
        "recipes": conn.execute("SELECT COUNT(*) FROM foods WHERE source = 'recipe'").fetchone()[0],
        "resisted": sum(days[k]["resisted"] for k in keys),
    }


def week_counts(conn, s: dict, today: date) -> dict:
    monday = points.week_start(today)
    dd = day_data(conn, s, monday, today)
    days, b = dd["days"], dd["budget"]
    goal = int(s.get("steps_goal") or 8000)
    kg = b["weight"]
    t = today.isoformat()
    return {
        "full_days": sum(1 for x in days.values() if x["meals"] >= 3),
        "budget_days": sum(1 for k, x in days.items() if k < t and _in_budget(x, b["points"])),
        "steps_goal_days": sum(1 for x in days.values() if x["steps"] >= goal),
        "zero_entries": sum(x["zero"] for x in days.values()),
        "weigh_days": sum(1 for x in days.values() if x["weighed"]),
        "protein_days": sum(1 for x in days.values() if x["entries"] and x["protein"] >= kg),
        "fiber_days": sum(1 for x in days.values() if x["fiber"] >= 25),
        "recipes": conn.execute("SELECT COUNT(*) FROM foods WHERE source = 'recipe' AND created >= ?",
                                (db.iso(db.parse(f"{monday.isoformat()}T00:00:00")),)).fetchone()[0],
        "resisted": sum(x["resisted"] for x in days.values()),
    }


def challenge(conn, s: dict, today: date | None = None) -> dict:
    """Challenge der laufenden Woche; wird bei Erreichen einmalig als geschafft gespeichert."""
    today = today or db.parse_day(db.today())
    monday = points.week_start(today).isoformat()
    skips = int((s.get("challenge_skips") or {}).get(monday, 0))
    idx = (today.isocalendar()[1] + skips) % len(CHALLENGES)
    cid, icon, title, metric, target = CHALLENGES[idx]
    done_list = list(s.get("challenges_done") or [])
    done = next((x for x in done_list if x.get("week") == monday), None)
    if done:   # geschaffte Challenge der Woche bleibt angezeigt
        c = next((c for c in CHALLENGES if c[0] == done["id"]), CHALLENGES[idx])
        cid, icon, title, metric, target = c
    progress = min(week_counts(conn, s, today)[metric], target)
    if progress >= target and not done:
        done = {"week": monday, "id": cid, "ts": db.iso(db.now_utc())}
        db.set_setting(conn, "challenges_done", (done_list + [done])[-200:])
    ends = (points.week_start(today) + timedelta(days=6)).isoformat()
    return {"id": cid, "icon": icon, "title": title, "progress": progress, "target": target, "week": monday,
            "ends": ends, "done": bool(done), "xp": XP["challenge"]}


def skip_challenge(conn, s: dict, today: date | None = None) -> None:
    today = today or db.parse_day(db.today())
    monday = points.week_start(today).isoformat()
    if any(x.get("week") == monday for x in s.get("challenges_done") or []):
        return
    skips = dict(s.get("challenge_skips") or {})
    skips = {k: v for k, v in skips.items() if k >= (today - timedelta(days=60)).isoformat()}
    skips[monday] = int(skips.get(monday, 0)) + 1
    db.set_setting(conn, "challenge_skips", skips)


def level_for(xp: int) -> dict:
    lvl = 1
    for i, (low, _) in enumerate(LEVELS):
        if xp >= low:
            lvl = i + 1
    low, name = LEVELS[lvl - 1]
    high = LEVELS[lvl][0] if lvl < len(LEVELS) else low + 2500
    return {"level": lvl, "name": name, "low": low, "high": high,
            "progress": round(min(1.0, (xp - low) / (high - low)), 3) if high > low else 1.0}


def state(conn, s: dict) -> dict:
    """Abzeichen (mit Freischaltung), Challenge, Level und XP für die Oberfläche."""
    sm = summary(conn, s)
    unlocked = dict(s.get("unlocked") or {})
    now = db.iso(db.now_utc())
    badges, changed = [], False
    for bid, icon, title, metric, target in BADGES:
        value = sm.get(metric, 0)
        if value >= target and bid not in unlocked:
            unlocked[bid] = now
            changed = True
        badges.append({"id": bid, "icon": icon, "title": title, "value": value, "target": target,
                       "progress": round(min(1.0, value / target), 3) if target else 1.0,
                       "unlocked": unlocked.get(bid)})
    if changed:
        db.set_setting(conn, "unlocked", unlocked)
    ch = challenge(conn, s)
    s = db.get_settings(conn)
    parts = [
        ("Erfasste Tage", sm["logged_days"], XP["logged"]),
        ("Tage im Budget", sm["budget_days"], XP["budget"]),
        ("Schrittziel erreicht", sm["steps_goal_days"], XP["steps"]),
        ("Gewogen", sm["weigh_days"], XP["weigh"]),
        ("Heißhunger überstanden", sm["resisted"], XP["resisted"]),
        ("Abzeichen", len(unlocked), XP["badge"]),
        ("Wochen-Challenges", len(s.get("challenges_done") or []), XP["challenge"]),
    ]
    total = sum(n * p for _, n, p in parts)
    return {
        "xp": {"points": total, **level_for(total),
               "parts": [{"label": l, "count": n, "each": p, "xp": n * p} for l, n, p in parts]},
        "badges": badges,
        "challenge": ch,
        "challenges_done": len(s.get("challenges_done") or []),
        "streak": sm["streak"],
        "best_streak": sm["best_streak"],
    }


# ---------- Heißhunger ----------

def critical_hours(conn, today: date | None = None, lookback: int = 21) -> list:
    """Uhrzeiten, zu denen oft genascht wird: Snack-Einträge und Heißhunger der letzten Wochen,
    gezählt als Tage je Stunde. Höchstens zwei Stunden, mindestens an 3 Tagen."""
    today = today or db.parse_day(db.today())
    since = today - timedelta(days=lookback)
    per_hour: dict = {}
    rows = conn.execute("SELECT ts FROM food_log WHERE meal = 'snack' AND day >= ?", (since.isoformat(),)).fetchall()
    rows += conn.execute("SELECT ts FROM events WHERE kind = 'craving' AND ts >= ?",
                         (db.iso(db.parse(f"{since.isoformat()}T00:00:00")),)).fetchall()
    for (ts,) in rows:
        loc = db.local(db.parse(ts))
        per_hour.setdefault(loc.hour, set()).add(loc.date())
    hours = sorted(((h, len(d)) for h, d in per_hour.items() if len(d) >= 3), key=lambda x: -x[1])[:2]
    return [{"hour": h, "days": n} for h, n in sorted(hours)]


def craving_stats(conn, first: str) -> dict:
    rows = conn.execute("SELECT * FROM events WHERE kind = 'craving' AND ts >= ? ORDER BY ts",
                        (db.iso(db.parse(f"{first}T00:00:00")),)).fetchall()
    total = len(rows)
    resisted = sum(1 for r in rows if r["resisted"])
    trig: dict = {}
    for r in rows:
        if r["trigger"]:
            t = trig.setdefault(r["trigger"], [0, 0])
            t[0] += 1
            t[1] += 1 if r["resisted"] else 0
    top = sorted(({"trigger": k, "count": v[0], "resisted": v[1]} for k, v in trig.items()), key=lambda x: -x["count"])[:6]
    return {"total": total, "resisted": resisted, "triggers": top, "hours": critical_hours(conn)}
