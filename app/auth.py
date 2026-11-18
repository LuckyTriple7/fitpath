"""Anmeldung per Einmal-Link.

Der Server erzeugt den Link selbst (CLI oder aus einem schon verbundenen
Gerät), er gilt 15 Minuten und nur einmal. Danach hält ein Session-Cookie
das Gerät angemeldet. In der Datenbank liegen nur SHA-256-Hashes.
"""

import hashlib
import os
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request

from . import db

COOKIE = "fp_session"
COOKIE_DAYS = 400
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() != "false"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8080").rstrip("/")
LINK_MINUTES = 15


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
    session = secrets.token_urlsafe(32)
    name = row["name"] or _device_name(user_agent)
    now = db.iso(db.now_utc())
    conn.execute("INSERT INTO devices (token_hash, name, created, last_seen) VALUES (?, ?, ?, ?)",
                 (_hash(session), name, now, now))
    return session


def _device_name(ua: str) -> str:
    ua = ua or ""
    if "Android" in ua:
        return "Android"
    if "Windows" in ua:
        return "Windows"
    if "Linux" in ua:
        return "Linux"
    return "Gerät"


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
