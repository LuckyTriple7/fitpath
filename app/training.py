"""Training: Sportarten, Belastung (MET) und Aktivitätspunkte dafür.

Rechnung je Einheit: (MET − 1) × kg × Stunden = kcal über dem Ruheverbrauch. Den Ruheverbrauch
deckt das Budget schon ab, deshalb zählt nur, was darüber hinausgeht. Wie bei den Schritten wird
die Hälfte gutgeschrieben (points.ACTIVITY_CREDIT), höchstens MAX_POINTS_DAY Punkte am Tag.

Keine Doppelzählung mit den Schritten: Gehen, Laufen und Wandern erzeugen Schritte, die schon über
den Schrittbonus zählen. Je Einheit werden die Schritte geschätzt (Schritte je Minute × Dauer) und
der Teil abgezogen, den der Schrittbonus an dem Tag tatsächlich gutgeschrieben hat. Spazieren bringt
deshalb praktisch nichts extra, Joggen nur den Anteil über dem Gehen.

Doppelte Einheiten: Schreiben zwei Apps dieselbe Einheit nach Health Connect (z. B. Samsung Health und
Google Fit), überlappen sie sich zeitlich. Eine Einheit aus Health Connect, die zu mindestens der Hälfte
in einer früher beginnenden steckt, zählt nicht.

MET-Werte gerundet nach dem Compendium of Physical Activities (Herrmann u. a., 2024).
"""

import uuid
from datetime import timedelta

from . import db, points

INTENSITIES = ("leicht", "mittel", "hart")
INTENSITY_HINT = {"leicht": "Reden geht locker", "mittel": "etwas außer Atem", "hart": "Reden fällt schwer"}
MAX_POINTS_DAY = 15            # Obergrenze Trainingspunkte je Tag
MIN_MINUTES, MAX_MINUTES = 3, 720
TRAIN_DAY_MINUTES = 20         # ab so vielen Minuten Training (ohne Spazieren) ist es ein Trainingstag

# Schlüssel: (Name, Symbol, MET leicht/mittel/hart, Schritte je Minute)
SPORTS = {
    "schwimmen": ("Schwimmen", "🏊", (4.8, 5.8, 9.8), 0),
    "rad": ("Radfahren", "🚴", (4.0, 6.8, 10.0), 0),
    "laufen": ("Joggen, Laufen", "🏃", (7.0, 9.0, 11.0), 160),
    "gehen": ("Spazieren, Walking", "🚶", (2.8, 3.5, 4.8), 100),
    "wandern": ("Wandern, Nordic Walking", "🥾", (4.5, 6.0, 7.8), 100),
    "kraft": ("Krafttraining", "🏋️", (3.5, 5.0, 6.0), 0),
    "ergometer": ("Heimtrainer, Spinning", "🚲", (3.5, 6.8, 8.8), 0),
    "crosstrainer": ("Crosstrainer", "🔁", (4.0, 5.0, 7.0), 0),
    "rudern": ("Rudern, Rudergerät", "🚣", (4.8, 7.0, 8.5), 0),
    "hiit": ("HIIT, Zirkeltraining", "🔥", (5.0, 8.0, 10.0), 0),
    "yoga": ("Yoga, Pilates, Dehnen", "🧘", (2.3, 3.0, 4.0), 0),
    "aqua": ("Aquafitness", "💦", (4.0, 5.3, 6.5), 0),
    "tanzen": ("Tanzen", "💃", (4.5, 5.5, 7.3), 0),
    "ballsport": ("Ballsport, Tennis", "⚽", (5.0, 7.0, 9.0), 0),
    "sonstiges": ("Sonstiges", "💪", (3.0, 4.5, 6.5), 0),
}

# Health Connect: Name (ab Life Dashboard 1.27) → Sportart. Fehlt der Name, hilft die Typnummer.
HC_NAMES = {
    "swimming_pool": "schwimmen", "swimming_open_water": "schwimmen",
    "biking": "rad", "biking_stationary": "ergometer",
    "running": "laufen", "running_treadmill": "laufen",
    "walking": "gehen", "wheelchair": "gehen",
    "hiking": "wandern", "snowshoeing": "wandern",
    "strength_training": "kraft", "weightlifting": "kraft", "calisthenics": "kraft",
    "elliptical": "crosstrainer", "stair_climbing_machine": "crosstrainer", "stair_climbing": "crosstrainer",
    "rowing": "rudern", "rowing_machine": "rudern", "paddling": "rudern",
    "high_intensity_interval_training": "hiit", "boot_camp": "hiit", "boxing": "hiit", "martial_arts": "hiit",
    "yoga": "yoga", "pilates": "yoga", "stretching": "yoga", "guided_breathing": "yoga",
    "dancing": "tanzen", "exercise_class": "hiit",
    "water_polo": "ballsport", "soccer": "ballsport", "basketball": "ballsport", "tennis": "ballsport",
    "badminton": "ballsport", "volleyball": "ballsport", "table_tennis": "ballsport", "squash": "ballsport",
    "handball": "ballsport", "racquetball": "ballsport", "rugby": "ballsport", "baseball": "ballsport",
    "softball": "ballsport", "cricket": "ballsport", "football_american": "ballsport",
    "football_australian": "ballsport", "ice_hockey": "ballsport", "roller_hockey": "ballsport",
}
HC_TYPES = {
    "0": "sonstiges", "2": "ballsport", "5": "ballsport", "8": "rad", "9": "ergometer", "10": "hiit",
    "11": "hiit", "13": "kraft", "16": "tanzen", "25": "crosstrainer", "36": "hiit", "37": "wandern",
    "48": "yoga", "53": "rudern", "54": "rudern", "56": "laufen", "57": "laufen", "64": "ballsport",
    "70": "kraft", "71": "yoga", "73": "schwimmen", "74": "schwimmen", "76": "ballsport", "79": "gehen",
    "81": "kraft", "83": "yoga",
}


def kind_for_hc(name, typ) -> str:
    name = str(name or "").strip().lower()
    return HC_NAMES.get(name) or HC_TYPES.get(str(typ or "").strip()) or "sonstiges"


def met(kind: str, intensity: str) -> float:
    sport = SPORTS.get(kind) or SPORTS["sonstiges"]
    i = INTENSITIES.index(intensity) if intensity in INTENSITIES else 1
    return sport[2][i]


def catalog() -> dict:
    """Für die Oberfläche: Sportarten und die Rechengrößen (Vorschau beim Eintragen)."""
    return {
        "sports": {k: {"name": n, "icon": i, "met": list(m), "spm": spm} for k, (n, i, m, spm) in SPORTS.items()},
        "intensities": [[k, INTENSITY_HINT[k]] for k in INTENSITIES],
        "kcal_per_step_kg": points.KCAL_PER_STEP_PER_KG,
        "credit": points.ACTIVITY_CREDIT,
        "kcal_per_point": points.KCAL_PER_POINT,
        "max_points_day": MAX_POINTS_DAY,
        "train_day_minutes": TRAIN_DAY_MINUTES,
    }


# ---------- Rechnung ----------

def _overlap(a: dict, b: dict) -> float:
    """Anteil von a, der zeitlich in b liegt (0–1)."""
    a0, b0 = db.parse(a["start"]), db.parse(b["start"])
    a1, b1 = a0 + timedelta(minutes=a["minutes"]), b0 + timedelta(minutes=b["minutes"])
    inter = (min(a1, b1) - max(a0, b0)).total_seconds()
    return max(0.0, inter) / max(a["minutes"] * 60, 1)


def day_credit(workouts: list, weight: float, extra_steps: int) -> dict:
    """Gutschrift eines Tages. workouts: [{id, start, minutes, kind, intensity, source, …}].
    extra_steps: Schritte über der Grundlinie, die der Schrittbonus schon gutgeschrieben hat."""
    steps_left = max(0, int(extra_steps or 0))
    kept, out, total = [], [], 0.0
    for w in sorted(workouts, key=lambda x: x["start"]):
        d = {k: w.get(k) for k in ("id", "start", "minutes", "kind", "intensity", "source", "title", "hc_type")}
        sport = SPORTS.get(w["kind"]) or SPORTS["sonstiges"]
        d.update(name=sport[0], icon=sport[1], duplicate=False, covered_steps=0, kcal=0, points=0)
        if w["source"] == "hc" and any(k["source"] == "hc" and _overlap(w, k) >= 0.5 for k in kept):
            d["duplicate"] = True
            out.append(d)
            continue
        kept.append(w)
        net = max(0.0, met(w["kind"], w["intensity"]) - 1) * weight * w["minutes"] / 60
        covered = min(int(sport[3] * w["minutes"]), steps_left)
        steps_left -= covered
        credited = max(0.0, net - covered * weight * points.KCAL_PER_STEP_PER_KG) * points.ACTIVITY_CREDIT
        d.update(covered_steps=covered, kcal=round(credited), points=points.round_points(credited / points.KCAL_PER_POINT))
        total += credited
        out.append(d)
    cap = MAX_POINTS_DAY * points.KCAL_PER_POINT
    train_minutes = sum(w["minutes"] for w in kept if w["kind"] != "gehen")
    return {"kcal": min(total, cap), "capped": total > cap, "workouts": out, "train_minutes": round(train_minutes),
            "swim": any(w["kind"] == "schwimmen" for w in kept)}


def by_day(conn, first: str, last: str) -> dict:
    out = {}
    for r in conn.execute("SELECT * FROM workouts WHERE hidden = 0 AND day BETWEEN ? AND ? ORDER BY start",
                          (first, last)):
        out.setdefault(r["day"], []).append(dict(r))
    return out


# ---------- Speichern ----------

def clean(data: dict, partial: bool = False) -> dict:
    """Eingaben prüfen. partial: nur übergebene Felder (Bearbeiten)."""
    out = {}
    if "kind" in data or not partial:
        if data.get("kind") not in SPORTS:
            raise ValueError("Sportart unbekannt")
        out["kind"] = data["kind"]
    if "intensity" in data or not partial:
        out["intensity"] = data.get("intensity") if data.get("intensity") in INTENSITIES else "mittel"
    if "minutes" in data or not partial:
        try:
            minutes = float(str(data.get("minutes")).replace(",", "."))
        except ValueError:
            raise ValueError("Dauer fehlt") from None
        if not MIN_MINUTES <= minutes <= MAX_MINUTES:
            raise ValueError(f"Dauer {MIN_MINUTES}–{MAX_MINUTES} Minuten")
        out["minutes"] = round(minutes, 1)
    return out


def add_manual(conn, data: dict, day: str) -> str:
    v = clean(data)
    wid = str(data.get("id") or uuid.uuid4())[:64]
    now = db.now_utc()
    # Uhrzeit ist bei Hand-Einträgen nur ungefähr; heute = jetzt, sonst Mittag des Tages
    start = now if day == db.today() else db.parse(f"{day}T12:00:00")
    conn.execute(
        "INSERT INTO workouts (id, start, day, minutes, kind, intensity, source, updated) VALUES (?, ?, ?, ?, ?, ?, 'manual', ?)",
        (wid, db.iso(start - timedelta(minutes=v["minutes"])), day, v["minutes"], v["kind"], v["intensity"], db.iso(now)))
    return wid


def update(conn, wid: str, data: dict) -> str | None:
    row = conn.execute("SELECT * FROM workouts WHERE id = ?", (wid,)).fetchone()
    if not row:
        return None
    v = clean(data, partial=True)
    if row["source"] == "hc":
        v.pop("minutes", None)        # Dauer kommt von der Uhr
    if not v:
        return row["day"]
    sets = ", ".join(f"{k} = ?" for k in v)
    conn.execute(f"UPDATE workouts SET {sets}, edited = 1, updated = ? WHERE id = ?",
                 (*v.values(), db.iso(db.now_utc()), wid))
    return row["day"]


def delete(conn, wid: str) -> str | None:
    """Hand-Einträge werden gelöscht, Einheiten aus Health Connect nur ausgeblendet
    (sonst kämen sie mit der nächsten Lieferung zurück)."""
    row = conn.execute("SELECT day, source FROM workouts WHERE id = ?", (wid,)).fetchone()
    if not row:
        return None
    if row["source"] == "hc":
        conn.execute("UPDATE workouts SET hidden = 1, updated = ? WHERE id = ?", (db.iso(db.now_utc()), wid))
    else:
        conn.execute("DELETE FROM workouts WHERE id = ?", (wid,))
    return row["day"]


def ingest(conn, records: list) -> int:
    """`exercise` aus Life Dashboard Companion übernehmen. Liefert die Zahl der übernommenen Einheiten."""
    n = 0
    now = db.iso(db.now_utc())
    for rec in records or []:
        if not isinstance(rec, dict) or not rec.get("start_time"):
            continue
        try:
            start = db.parse(str(rec["start_time"]))
            end = db.parse(str(rec["end_time"])) if rec.get("end_time") else None
        except ValueError:
            continue
        secs = rec.get("duration_seconds")
        secs = float(secs) if isinstance(secs, (int, float)) else ((end - start).total_seconds() if end else 0)
        minutes = round(secs / 60, 1)
        if not MIN_MINUTES <= minutes <= MAX_MINUTES:
            continue
        key = str(rec.get("uuid") or f"{rec['start_time']}|{rec.get('type')}")[:80]
        hc_type = str(rec.get("name") or rec.get("type") or "")[:40] or None
        conn.execute(
            "INSERT INTO workouts (id, start, day, minutes, kind, intensity, source, hc_type, title, app, updated) "
            "VALUES (?, ?, ?, ?, ?, 'mittel', 'hc', ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET start = excluded.start, "
            "day = excluded.day, minutes = excluded.minutes, hc_type = excluded.hc_type, title = excluded.title, "
            "app = excluded.app, kind = CASE WHEN workouts.edited = 1 THEN workouts.kind ELSE excluded.kind END, "
            "updated = excluded.updated",
            ("hc:" + key, db.iso(start), db.local_day(start), minutes, kind_for_hc(rec.get("name"), rec.get("type")),
             hc_type, str(rec.get("title") or "")[:80] or None, str(rec.get("source") or "")[:80] or None, now))
        n += 1
    return n


def remove_hc(conn, uid: str) -> int:
    return conn.execute("DELETE FROM workouts WHERE id = ?", ("hc:" + str(uid)[:80],)).rowcount
