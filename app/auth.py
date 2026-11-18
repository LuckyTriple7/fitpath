"""Anmeldung per Einmal-Link oder per QR-Code/Code.

Einmal-Link: Der Server erzeugt den Link selbst (CLI oder aus einem schon
verbundenen Gerät), er gilt 15 Minuten und nur einmal.

QR-Code/Code (wie WhatsApp Web): Das neue Gerät fordert eine Kopplung an und
bekommt ein Geheimnis (bleibt im Browser) und einen 6-stelligen Code (wird
angezeigt, auch als QR-Code). Ein verbundenes Gerät gibt den Code frei, das
neue Gerät fragt nach und bekommt erst dann sein Session-Cookie. Der Code
allein nützt nichts: Freigeben kann nur ein angemeldetes Gerät, und das Cookie
geht nur an den Inhaber des Geheimnisses.

Danach hält ein Session-Cookie das Gerät angemeldet. In der Datenbank liegen
nur SHA-256-Hashes.
"""

import hashlib
import os
import re
import secrets
import threading
import time
from datetime import timedelta

from fastapi import HTTPException, Request

from . import db

COOKIE = "fp_session"
COOKIE_DAYS = 400
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() != "false"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8080").rstrip("/")
LINK_MINUTES = 15
PAIR_SECONDS = 300          # so lange gilt ein Code, danach holt das neue Gerät einen neuen
PAIR_MAX_PENDING = 30       # offene Anfragen insgesamt
PAIR_PER_MINUTE = 20        # neue Anfragen pro Minute (ohne Anmeldung erreichbar)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_link(conn, name: str = "") -> str:
    token = secrets.token_urlsafe(32)
    expires = db.now_utc() + timedelta(minutes=LINK_MINUTES)
    conn.execute("DELETE FROM link_tokens WHERE expires < ?", (db.iso(db.now_utc()),))
    conn.execute("INSERT INTO link_tokens (token_hash, expires, name) VALUES (?, ?, ?)",
                 (_hash(token), db.iso(expires), name[:40]))
    return f"{PUBLIC_URL}/auth/{token}"


def peek(conn, token: str):
    """Prüft einen Link, ohne ihn einzulösen (für die Bestätigungsseite).
    Liefert den Gerätenamen ("" wenn keiner) oder None, wenn ungültig/abgelaufen."""
    row = conn.execute("SELECT * FROM link_tokens WHERE token_hash = ?", (_hash(token),)).fetchone()
    if not row or db.parse(row["expires"]) < db.now_utc():
        return None
    return row["name"] or ""


def redeem(conn, token: str, user_agent: str):
    """Löst einen Link ein. Liefert das Session-Token oder None."""
    row = conn.execute("SELECT * FROM link_tokens WHERE token_hash = ?", (_hash(token),)).fetchone()
    if not row:
        return None
    conn.execute("DELETE FROM link_tokens WHERE token_hash = ?", (row["token_hash"],))
    if db.parse(row["expires"]) < db.now_utc():
        return None
    return _new_session(conn, row["name"] or _device_name(user_agent))


def _new_session(conn, name: str) -> str:
    session = secrets.token_urlsafe(32)
    now = db.iso(db.now_utc())
    conn.execute("INSERT INTO devices (token_hash, name, created, last_seen) VALUES (?, ?, ?, ?)",
                 (_hash(session), name[:40], now, now))
    return session


def _device_name(ua: str) -> str:
    ua = ua or ""
    for key, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                      ("Macintosh", "Mac"), ("CrOS", "ChromeOS"), ("Linux", "Linux")):
        if key in ua:
            return name
    return "Gerät"


def ua_label(ua: str) -> str:
    """„Windows · Chrome“ – zum Wiedererkennen bei der Freigabe."""
    ua = ua or ""
    browser = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung Internet"),
                                   ("Firefox/", "Firefox"), ("FxiOS", "Firefox"), ("CriOS", "Chrome"),
                                   ("Chrome/", "Chrome"), ("Safari/", "Safari")) if k in ua), None)
    return f"{_device_name(ua)} · {browser}" if browser else _device_name(ua)


# ---------- Kopplung per QR-Code/Code ----------

_pair_lock = threading.Lock()
_pair_calls: list = []


def _pair_allowed() -> bool:
    with _pair_lock:
        now = time.monotonic()
        while _pair_calls and now - _pair_calls[0] > 60:
            _pair_calls.pop(0)
        if len(_pair_calls) >= PAIR_PER_MINUTE:
            return False
        _pair_calls.append(now)
        return True


def _pair_cleanup(conn) -> None:
    conn.execute("DELETE FROM pair_requests WHERE expires < ?", (db.iso(db.now_utc()),))


def pair_start(conn, user_agent: str) -> dict | None:
    """Neue Anfrage. None, wenn gerade zu viele offen sind."""
    _pair_cleanup(conn)
    if not _pair_allowed() or conn.execute(
            "SELECT COUNT(*) FROM pair_requests WHERE status = 'pending'").fetchone()[0] >= PAIR_MAX_PENDING:
        return None
    active = {r[0] for r in conn.execute("SELECT code FROM pair_requests")}
    code = f"{secrets.randbelow(1_000_000):06d}"
    while code in active:
        code = f"{secrets.randbelow(1_000_000):06d}"
    rid = secrets.token_urlsafe(32)
    now = db.now_utc()
    conn.execute("INSERT INTO pair_requests (rid_hash, code, expires, ua, created) VALUES (?, ?, ?, ?, ?)",
                 (_hash(rid), code, db.iso(now + timedelta(seconds=PAIR_SECONDS)), (user_agent or "")[:300], db.iso(now)))
    return {"rid": rid, "code": code, "seconds": PAIR_SECONDS}


def _pending(conn, code: str):
    if not re.fullmatch(r"\d{6}", code or ""):
        return None
    _pair_cleanup(conn)
    return conn.execute("SELECT * FROM pair_requests WHERE code = ? AND status = 'pending'", (code,)).fetchone()


def pair_info(conn, code: str) -> dict | None:
    row = _pending(conn, code)
    if not row:
        return None
    age = (db.now_utc() - db.parse(row["created"])).total_seconds()
    return {"code": code, "label": ua_label(row["ua"]), "name": _device_name(row["ua"]), "age_s": int(age)}


def pair_decide(conn, code: str, approve: bool, name: str = "") -> bool:
    row = _pending(conn, code)
    if not row:
        return False
    conn.execute("UPDATE pair_requests SET status = ?, name = ? WHERE rid_hash = ?",
                 ("approved" if approve else "denied", (name or _device_name(row["ua"]))[:40], row["rid_hash"]))
    return True


def pair_poll(conn, rid: str) -> tuple[str, str | None]:
    """(Status, Session-Token). Bei „approved“ wird die Anfrage verbraucht."""
    if not rid or len(rid) > 100:
        return "expired", None
    row = conn.execute("SELECT * FROM pair_requests WHERE rid_hash = ?", (_hash(rid),)).fetchone()
    if not row or db.parse(row["expires"]) < db.now_utc():
        return "expired", None
    if row["status"] == "pending":
        return "pending", None
    conn.execute("DELETE FROM pair_requests WHERE rid_hash = ?", (row["rid_hash"],))
    if row["status"] == "denied":
        return "denied", None
    return "approved", _new_session(conn, row["name"])


def device_for(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM devices WHERE token_hash = ?", (_hash(token),)).fetchone()
        if not row:
            return None
        now = db.now_utc()
        if not row["last_seen"] or (now - db.parse(row["last_seen"])).total_seconds() > 600:
            conn.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (db.iso(now), row["id"]))
        return dict(row)


def require(request: Request) -> dict:
    device = device_for(request)
    if not device:
        raise HTTPException(401, "nicht angemeldet")
    # Einfacher CSRF-Schutz: ändernde Anfragen brauchen den Header der App
    if request.method not in ("GET", "HEAD") and request.headers.get("x-fitpath") != "1":
        raise HTTPException(403, "Header fehlt")
    return device
