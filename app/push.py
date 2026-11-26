"""Web-Push: VAPID-Schlüssel und Erinnerungen.

Erinnerungen (alle abschaltbar, Ruhezeiten und Höchstzahl pro Tag gelten):
- Wiegen: an den gewählten Wochentagen zur gewählten Uhrzeit, wenn noch kein Gewicht da ist.
- Mittag: zur gewählten Uhrzeit, wenn heute noch nichts erfasst ist.
- Abend: zur gewählten Uhrzeit, wenn heute weniger als zwei Mahlzeiten erfasst sind.
Im Urlaub (plan.py) kommt keine Erinnerung.
"""

import asyncio
import base64
import json
import os
import random
from datetime import datetime

from datetime import timedelta

from . import db, fasting, motivation, plan

VAPID_FILE = os.path.join(db.DATA_DIR, "vapid_private.pem")
VAPID_SUB = os.environ.get("VAPID_SUB") or os.environ.get("PUBLIC_URL") or "https://localhost"
TICK_SECONDS = 300

_public_key = None


def ensure_vapid() -> str:
    """Erzeugt beim ersten Start ein Schlüsselpaar und liefert den öffentlichen Schlüssel."""
    global _public_key
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    if os.path.exists(VAPID_FILE):
        vapid = Vapid.from_file(VAPID_FILE)
    else:
        vapid = Vapid()
        vapid.generate_keys()
        vapid.save_key(VAPID_FILE)
        os.chmod(VAPID_FILE, 0o600)
    raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    _public_key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return _public_key


def public_key() -> str:
    return _public_key or ensure_vapid()


def send(conn, title: str, body: str, url: str = "/", tag: str = "fitpath") -> int:
    from pywebpush import WebPushException, webpush

    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag}, ensure_ascii=False)
    sent = 0
    for sub in conn.execute("SELECT * FROM push_subs").fetchall():
        info = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
        try:
            webpush(info, payload, vapid_private_key=VAPID_FILE,
                    vapid_claims={"sub": VAPID_SUB}, ttl=3600, timeout=15)
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                conn.execute("DELETE FROM push_subs WHERE endpoint = ?", (sub["endpoint"],))
            print(f"Push-Fehler {status}: {exc}", flush=True)
        except Exception as exc:
            print(f"Push-Fehler: {exc}", flush=True)
    return sent


def _hm(value: str, default: str) -> tuple:
    try:
        h, m = (value or default).split(":")
        return int(h), int(m)
    except ValueError:
        h, m = default.split(":")
        return int(h), int(m)


def in_quiet(settings: dict, loc: datetime) -> bool:
    qs = _hm(settings.get("quiet_start"), "22:00")
    qe = _hm(settings.get("quiet_end"), "07:00")
    cur = (loc.hour, loc.minute)
    if qs <= qe:
        return qs <= cur < qe
    return cur >= qs or cur < qe


def _log(conn, kind: str, slot: str) -> bool:
    """True, wenn der Slot neu ist (noch nicht gesendet)."""
    try:
        conn.execute("INSERT INTO push_log (ts, kind, slot) VALUES (?, ?, ?)",
                     (db.iso(db.now_utc()), kind, slot))
        return True
    except Exception:
        return False


def _sent_today(conn, loc: datetime) -> int:
    start = loc.replace(hour=0, minute=0, second=0, microsecond=0)
    return conn.execute("SELECT COUNT(*) FROM push_log WHERE ts >= ?", (db.iso(start),)).fetchone()[0]


WEIGH_TEXTS = ["Guten Morgen! Kurz auf die Waage – nüchtern ist der Wert am ehrlichsten.",
               "Wiege-Tag. Der Trend zählt, nicht der einzelne Wert."]
LUNCH_TEXTS = ["Heute noch nichts erfasst. Ein Tipp auf „Zuletzt“ reicht oft schon.",
               "Was gab's bisher? Frühstück und Mittag nachtragen dauert 30 Sekunden."]
SNACK_TEXTS = ["Um diese Zeit kommt oft der Snack-Hunger. Erst ein Glas Wasser – und wenn doch, Obst oder Gemüse kosten 0 Punkte.",
               "Gleich ist Snack-Zeit. Hast du einen Plan? Im Notfall hilft der 🍫-Knopf oben.",
               "Kleiner Hinweis vor der üblichen Nasch-Zeit: Tee, Wasser oder ein Apfel halten bis zur nächsten Mahlzeit."]
EVENING_TEXTS = ["Tag fast geschafft. Fehlt noch eine Mahlzeit im Tagebuch?",
                 "Kurzer Abend-Check: Ist alles erfasst? Dann siehst du morgen die Reserve."]


def fasting_push(conn, s: dict, loc: datetime, last, phase: str) -> bool:
    """Essensfenster geht auf (in der ersten Stunde, wenn noch nichts gegessen) oder schließt in 30 Minuten."""
    for d in (loc.date() - timedelta(days=1), loc.date()):
        op, cl = fasting.window(s, d)
        if phase == "open" and op <= loc < op + timedelta(hours=1) and _log(conn, "fast", f"fast_open:{d}"):
            h = (loc - last).total_seconds() / 3600 if last else None
            body = (f"{int(h)} Stunden gefastet, geschafft! Guten Appetit." if h is not None and h >= fasting.hours(s) - fasting.TOLERANCE_H
                    else f"Ab jetzt bis {cl.strftime('%H:%M')} darfst du essen.")
            send(conn, "Essensfenster offen", body, "/#heute", "fast")
            return True
        if cl - timedelta(minutes=30) <= loc < cl and _log(conn, "fast", f"fast_close:{d}"):
            send(conn, f"Essensfenster schließt um {cl.strftime('%H:%M')}",
                 "Noch 30 Minuten. Danach beginnt die Fastenzeit, Wasser, Tee und schwarzer Kaffee gehen immer.", "/#heute", "fast")
            return True
    return False


def tick() -> None:
    with db.connect() as conn:
        s = db.get_settings(conn)
        if not s.get("onboarded") or not s.get("push_enabled"):
            return
        if not conn.execute("SELECT 1 FROM push_subs LIMIT 1").fetchone():
            return
        loc = db.local(db.now_utc())
        today = loc.date().isoformat()
        if plan.is_vacation(s, loc.date()):
            return
        if in_quiet(s, loc) or _sent_today(conn, loc) >= int(s.get("push_max_per_day") or 3):
            return
        cur = (loc.hour, loc.minute)

        # 1. Wiegen
        if loc.weekday() in (s.get("weigh_days") or []) and cur >= _hm(s.get("weigh_time"), "07:30") and cur < (12, 0):
            weighed = conn.execute("SELECT 1 FROM body WHERE kind = 'weight' AND day = ?", (today,)).fetchone()
            if not weighed and _log(conn, "weigh", f"weigh:{today}"):
                send(conn, "Wiegen", random.choice(WEIGH_TEXTS), "/#gewicht", "weigh")
                return

        entries = conn.execute("SELECT COUNT(*), COUNT(DISTINCT meal) FROM food_log WHERE day = ?", (today,)).fetchone()

        # Fasten: Fenster öffnet / schließt bald; in der Fastenzeit keine Snack-Erinnerung
        phase, opens_late = None, False
        if fasting.hours(s):
            past = [t for t in fasting.meal_times(conn, loc.date() - timedelta(days=1), loc.date()) if t <= loc]
            last = past[-1] if past else None
            phase = fasting.phase(s, loc, last)
            op_today = fasting.window(s, loc.date())[0]
            opens_late = loc < op_today + timedelta(hours=2)     # „Nichts erfasst“ erst, wenn das Fenster eine Weile offen ist
            if s.get("fast_push") and fasting_push(conn, s, loc, last, phase):
                return

        # 2. Mittag: noch nichts erfasst
        if s.get("lunch_reminder") and cur >= _hm(s["lunch_reminder"], "14:00") and cur < (17, 0) and not opens_late:
            if not entries[0] and _log(conn, "lunch", f"lunch:{today}"):
                send(conn, "Noch nichts erfasst", random.choice(LUNCH_TEXTS), "/#heute", "lunch")
                return

        # 3. Snack-Uhrzeiten: etwa 15 Minuten vor einer Stunde, in der oft genascht wird
        if s.get("snack_push") and phase != "fasting":
            nxt = (loc + timedelta(minutes=20)).replace(minute=0, second=0, microsecond=0)
            if 0 < (nxt - loc).total_seconds() / 60 <= 20:
                for h in motivation.critical_hours(conn):
                    if h["hour"] == nxt.hour and _log(conn, "snack", f"snack:{today}:{h['hour']}"):
                        send(conn, "Snack-Zeit", random.choice(SNACK_TEXTS), "/#sos", "snack")
                        return

        # 4. Abend: weniger als zwei Mahlzeiten
        if s.get("evening_time") and cur >= _hm(s["evening_time"], "20:30"):
            if entries[1] < 2 and _log(conn, "evening", f"evening:{today}"):
                send(conn, "Tag abschließen", random.choice(EVENING_TEXTS), "/#heute", "evening")


async def loop() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception as exc:
            print(f"Push-Planer: {exc}", flush=True)
        await asyncio.sleep(TICK_SECONDS)
