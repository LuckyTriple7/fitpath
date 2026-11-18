"""SQLite-Zugriff und Einstellungen für FitPath."""

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "fitpath.db")
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))

NUTRIENTS = ("kcal", "protein", "fat", "satfat", "carbs", "sugar", "fiber", "alcohol", "salt")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS foods (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,              -- bls | off | custom
    code TEXT,                         -- BLS-Code oder Barcode
    name TEXT NOT NULL,
    brand TEXT,
    kcal REAL, protein REAL, fat REAL, satfat REAL, carbs REAL,
    sugar REAL, fiber REAL, alcohol REAL, salt REAL,   -- je 100 g
    zero_auto INTEGER NOT NULL DEFAULT 0,
    zero_user INTEGER,                 -- NULL = Regel gilt, sonst 0/1
    portions TEXT,                     -- JSON [{name, g}] eigene Portionen
    serving_g REAL,                    -- Portionsangabe der Quelle (Open Food Facts)
    fav INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS foods_src_code ON foods (source, code) WHERE code IS NOT NULL;

CREATE TABLE IF NOT EXISTS food_log (
    id TEXT PRIMARY KEY,               -- UUID vom Gerät (Offline-Warteschlange)
    ts TEXT NOT NULL,
    day TEXT NOT NULL,                 -- lokaler Tag JJJJ-MM-TT
    meal TEXT NOT NULL,                -- fruehstueck | mittag | abend | snack
    food_id INTEGER,
    name TEXT NOT NULL,
    grams REAL NOT NULL,
    portion TEXT,
    kcal REAL, protein REAL, fat REAL, satfat REAL, carbs REAL,
    sugar REAL, fiber REAL, alcohol REAL, salt REAL,   -- Schnappschuss für die Menge
    zero INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS food_log_day ON food_log (day);
CREATE INDEX IF NOT EXISTS food_log_food ON food_log (food_id);

CREATE TABLE IF NOT EXISTS body (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    kind TEXT NOT NULL,                -- weight | fat | waist
    value REAL NOT NULL,
    source TEXT NOT NULL,              -- manual | hc
    ext_id TEXT                        -- uuid aus Health Connect
);
CREATE INDEX IF NOT EXISTS body_kind_day ON body (kind, day);
CREATE UNIQUE INDEX IF NOT EXISTS body_ext ON body (kind, ext_id) WHERE ext_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS activity (
    day TEXT NOT NULL,
    source TEXT NOT NULL,              -- hc | manual
    steps INTEGER,
    active_kcal REAL,
    total_kcal REAL,
    distance_m REAL,
    seq INTEGER,                       -- sequence der Health-Connect-Lieferung
    updated TEXT NOT NULL,
    PRIMARY KEY (day, source)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, seq INTEGER, kind TEXT NOT NULL,
    summary TEXT, raw TEXT);
CREATE INDEX IF NOT EXISTS ingest_log_seq ON ingest_log (seq);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, name TEXT,
    created TEXT NOT NULL, last_seen TEXT);
CREATE TABLE IF NOT EXISTS link_tokens (
    token_hash TEXT PRIMARY KEY, expires TEXT NOT NULL, name TEXT);
CREATE TABLE IF NOT EXISTS push_subs (
    endpoint TEXT PRIMARY KEY, p256dh TEXT NOT NULL, auth TEXT NOT NULL,
    device_id INTEGER, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS push_log (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, slot TEXT UNIQUE);
"""

DEFAULTS = {
    "onboarded": False,
    # Profil
    "sex": "m",
    "birth_year": 1975,
    "height_cm": 178,
    "start_weight": 90.0,
    "start_date": None,
    "goal_weight": 80.0,
    "activity": 1.375,          # Aktivitätsfaktor ohne Sport (1,2 sitzend … 1,725 sehr aktiv)
    "mode": "lose",             # lose | keep
    "pace": 0.5,                # kg pro Woche im Modus "lose"
    # Anzeige
    "display": "points",        # points | kcal
    "steps_baseline": 5000,     # Schritte, die der Aktivitätsfaktor schon abdeckt
    "steps_goal": 8000,
    # Health Connect (Life Dashboard Companion)
    "ingest_secret": None,
    "ingest_seq": 0,
    # Push
    "push_enabled": True,
    "quiet_start": "22:00",
    "quiet_end": "07:00",
    "push_max_per_day": 3,
    "weigh_time": "07:30",
    "weigh_days": [0, 3],       # Mo und Do; leer = keine Erinnerung
    "lunch_reminder": "14:00",
    "evening_time": "20:30",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse(ts: str) -> datetime:
    ts = ts.strip().replace("Z", "+00:00")
    # Health Connect liefert bis zu 9 Nachkommastellen, fromisoformat kann höchstens 6
    m = re.match(r"^(.*?\.)(\d+)(.*)$", ts)
    if m:
        ts = f"{m.group(1)}{m.group(2)[:6].ljust(6, '0')}{m.group(3)}"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc)


def local(dt: datetime) -> datetime:
    return dt.astimezone(TZ)


def local_day(dt: datetime) -> str:
    return local(dt).date().isoformat()


def today() -> str:
    return local_day(now_utc())


def parse_day(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


MIGRATIONS = {
    # Tabelle: [(Spalte, Typ)] – fehlende Spalten werden beim Start ergänzt
    "foods": [("recipe", "TEXT"),        # JSON {items: [{food_id, name, grams}], servings, total_g}
              ("pts_100", "REAL")],      # Rohpunkte je 100 g, nur für Gerichte (0-Punkte-Zutaten zählen nicht)
    "food_log": [("points_raw", "REAL")],  # Rohpunkte der Menge, wenn nicht aus den Nährwerten berechenbar
}


def check_writable() -> None:
    """Klare Meldung statt „unable to open database file“, wenn der Datenordner nicht beschreibbar ist
    (typisch: Docker hat ./data beim ersten Start als root angelegt)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    probe = os.path.join(DATA_DIR, ".schreibtest")
    try:
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
    except OSError as exc:
        uid = os.getuid() if hasattr(os, "getuid") else "?"
        raise SystemExit(
            f"FEHLER: Datenordner {DATA_DIR} ist nicht beschreibbar ({exc.strerror}). Die App läuft als UID {uid}.\n"
            f"Lösung: auf dem Host im Stack-Ordner 'chown {uid} data' ausführen, oder in compose.yml statt "
            f"'./data:/data' ein benanntes Volume nehmen (siehe README, Einrichten mit Dockge).") from None


def init() -> None:
    check_writable()
    with connect() as conn:
        conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, typ in cols:
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_settings(conn) -> dict:
    result = json.loads(json.dumps(DEFAULTS))
    for row in conn.execute("SELECT key, value FROM settings"):
        result[row["key"]] = json.loads(row["value"])
    return result


def set_setting(conn, key: str, value) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )


def public_settings(s: dict) -> dict:
    """Einstellungen für die Oberfläche: ohne Geheimnisse."""
    out = {k: v for k, v in s.items() if k != "ingest_secret"}
    out["ingest_configured"] = bool(s.get("ingest_secret"))
    return out
