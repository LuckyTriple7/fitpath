"""Health-Connect-Daten von Life Dashboard Companion (Webhook).

Format laut docs/webhook.md im Repo owen282000/life-dashboard-companion-app:
- POST, JSON, `source: health_connect`, `sequence` je Installation steigend.
- Signatur `X-Signature: sha256=<hex HMAC-SHA256(secret, roher Body)>`.
  Alternativ akzeptiert FitPath `Authorization: Bearer <secret>` (eigener Header in der App).
- `daily_totals`: je lokalem Tag Schritte, aktive/gesamte kcal, Strecke, über die
  Aggregat-API von Health Connect ohne Doppelzählung von Handy und Uhr. Für ein
  Datum gilt der Wert aus der Lieferung mit der höchsten `sequence`.
- `weight` (kilograms, time, uuid), `body_fat` (percentage, time, uuid).
- `deleted_records`: [{type, uuid}] – Gewicht/Körperfett mit dieser uuid entfernen.
- `test: true` = Test-Ping ohne Daten.

Rohe Schrittdatensätze werden nicht addiert (Handy und Uhr schreiben doppelt),
dafür sind die Tagessummen da.
"""

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import timedelta
from urllib.parse import quote, urlencode

from . import db, training

KEEP_DAYS = 14
DENY_PER_MINUTE = 20        # abgelehnte Anfragen, danach 429 ohne den Body zu lesen
DENY_LOG_SECONDS = 60       # höchstens ein Protokolleintrag für Ablehnungen pro Minute
RAW_LIMIT = 32_000
BODY_KINDS = {"weight": ("weight", "kilograms", 20, 400), "body_fat": ("fat", "percentage", 1, 75)}


PAIR_PAGE = "https://owen282000.github.io/life-dashboard-companion-app/pair"


def new_secret(conn) -> str:
    secret = secrets.token_urlsafe(32)
    db.set_setting(conn, "ingest_secret", secret)
    return secret


def pairing_link(url: str, secret: str, name: str | None = "FitPath", sources=("health_connect",),
                 app: bool = False) -> str:
    """Koppel-Link nach docs/pairing.md von Life Dashboard: alles im Fragment (nach #),
    jeder Wert vollständig prozentkodiert. https-Form für den QR-Code, lifedashboard://
    für einen Knopf, wenn FitPath schon auf dem Handy offen ist."""
    fields = {"v": "1", "url": url, "secret": secret}
    if name:
        fields["name"] = name
    if sources:
        fields["sources"] = ",".join(sources)
    return ("lifedashboard://pair" if app else PAIR_PAGE) + "#" + urlencode(fields, quote_via=quote, safe="")


def pair_info(url: str, secret: str) -> dict:
    import segno
    link = pairing_link(url, secret)
    qr = segno.make(link, error="m").svg_inline(scale=5, border=4, dark="#000", light="#fff")
    return {"url": url, "secret": secret, "link": link, "app_link": pairing_link(url, secret, app=True), "qr_svg": qr}


def check(secret: str | None, body: bytes, signature: str | None, authorization: str | None) -> str | None:
    """None, wenn die Anfrage echt ist, sonst der Grund für die Ablehnung."""
    if not secret:
        return "In FitPath ist noch kein Geheimnis eingerichtet"
    if signature:
        if not signature.startswith("sha256="):
            return "Signatur in unbekanntem Format"
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        # als Bytes vergleichen: compare_digest wirft bei Nicht-ASCII-Strings TypeError
        if hmac.compare_digest(expected.encode(), signature[7:].strip().lower().encode()):
            return None
        return "Signatur passt nicht – Geheimnis in Life Dashboard stimmt nicht mit FitPath überein"
    if authorization and authorization.lower().startswith("bearer "):
        if hmac.compare_digest(authorization[7:].strip().encode(), secret.encode()):
            return None
        return "Bearer-Header passt nicht"
    return "Ohne Signatur – in Life Dashboard ist kein HMAC signing secret eingetragen"


def verify(secret: str | None, body: bytes, signature: str | None, authorization: str | None) -> bool:
    return check(secret, body, signature, authorization) is None


_deny_lock = threading.Lock()
_denied: list = []          # Zeitpunkte der Ablehnungen der letzten Minute
_deny_logged = [0.0, 0]     # letzter Protokolleintrag, seitdem nicht protokolliert


def too_many_denied() -> bool:
    with _deny_lock:
        now = time.monotonic()
        while _denied and now - _denied[0] > 60:
            _denied.pop(0)
        return len(_denied) >= DENY_PER_MINUTE


def log_denied(conn, reason: str, size: int) -> None:
    """Ablehnung zählen; ins Protokoll nur einmal pro Minute (sonst ließe sich die DB fluten)."""
    with _deny_lock:
        now = time.monotonic()
        _denied.append(now)
        if _deny_logged[0] and now - _deny_logged[0] < DENY_LOG_SECONDS:
            _deny_logged[1] += 1
            return
        skipped, _deny_logged[0], _deny_logged[1] = _deny_logged[1], now, 0
    summary = {"reason": reason, "bytes": size}
    if skipped:
        summary["more"] = skipped
    _log(conn, "denied", None, summary)


def _log(conn, kind: str, seq, summary: dict, raw: bytes | None = None) -> None:
    conn.execute("INSERT INTO ingest_log (ts, seq, kind, summary, raw) VALUES (?, ?, ?, ?, ?)",
                 (db.iso(db.now_utc()), seq, kind, json.dumps(summary, ensure_ascii=False),
                  raw[:RAW_LIMIT].decode("utf-8", "replace") if raw else None))
    conn.execute("DELETE FROM ingest_log WHERE ts < ?", (db.iso(db.now_utc() - timedelta(days=KEEP_DAYS)),))


def _num(v, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def apply(conn, payload: dict, raw: bytes | None = None) -> dict:
    """Lieferung einspielen. Liefert eine kurze Zusammenfassung."""
    if payload.get("test"):
        _log(conn, "test", None, {"message": str(payload.get("message") or "")[:120]})
        return {"ok": True, "test": True}
    if payload.get("source") not in ("health_connect", "healthkit_ios"):
        _log(conn, "ignored", payload.get("sequence"), {"source": str(payload.get("source"))[:40]})
        return {"ok": True, "ignored": True}
    seq = payload.get("sequence")
    seq = int(seq) if isinstance(seq, int) else None
    if seq is not None and conn.execute(
            "SELECT 1 FROM ingest_log WHERE seq = ? AND kind = 'sync' LIMIT 1", (seq,)).fetchone():
        return {"ok": True, "duplicate": True}

    now = db.iso(db.now_utc())
    summary = {"days": 0, "weight": 0, "body_fat": 0, "exercise": 0, "deleted": 0}

    # Tagessummen: nur übernehmen, wenn die Lieferung neuer ist als die gespeicherte
    for t in payload.get("daily_totals") or []:
        if not isinstance(t, dict):
            continue
        day = str(t.get("date") or "")[:10]
        try:
            db.parse_day(day)
        except ValueError:
            continue
        row = conn.execute("SELECT seq FROM activity WHERE day = ? AND source = 'hc'", (day,)).fetchone()
        if row and seq is not None and row["seq"] is not None and row["seq"] > seq:
            continue
        steps = _num(t.get("steps"), 0, 200_000)
        conn.execute(
            "INSERT INTO activity (day, source, steps, active_kcal, total_kcal, distance_m, seq, updated) "
            "VALUES (?, 'hc', ?, ?, ?, ?, ?, ?) ON CONFLICT(day, source) DO UPDATE SET "
            "steps = coalesce(excluded.steps, activity.steps), active_kcal = coalesce(excluded.active_kcal, activity.active_kcal), "
            "total_kcal = coalesce(excluded.total_kcal, activity.total_kcal), "
            "distance_m = coalesce(excluded.distance_m, activity.distance_m), seq = excluded.seq, updated = excluded.updated",
            (day, int(steps) if steps is not None else None, _num(t.get("active_calories"), 0, 20_000),
             _num(t.get("total_calories"), 0, 30_000), _num(t.get("distance_meters"), 0, 500_000), seq, now))
        summary["days"] += 1

    # Gewicht und Körperfett, Schlüssel ist die uuid aus Health Connect
    for key, (kind, field, lo, hi) in BODY_KINDS.items():
        for rec in payload.get(key) or []:
            if not isinstance(rec, dict) or not rec.get("uuid") or not rec.get("time"):
                continue
            value = _num(rec.get(field), lo, hi)
            if value is None:
                continue
            try:
                ts = db.parse(str(rec["time"]))
            except ValueError:
                continue
            conn.execute(
                "INSERT INTO body (ts, day, kind, value, source, ext_id) VALUES (?, ?, ?, ?, 'hc', ?) "
                "ON CONFLICT(kind, ext_id) WHERE ext_id IS NOT NULL DO UPDATE SET ts = excluded.ts, "
                "day = excluded.day, value = excluded.value",
                (db.iso(ts), db.local_day(ts), kind, round(value, 2), str(rec["uuid"])[:80]))
            summary[key] += 1

    # Trainingseinheiten (Schlüssel ist die uuid aus Health Connect)
    summary["exercise"] = training.ingest(conn, payload.get("exercise"))

    for d in payload.get("deleted_records") or []:
        if isinstance(d, dict) and d.get("type") == "exercise" and d.get("uuid"):
            summary["deleted"] += training.remove_hc(conn, d["uuid"])
        if isinstance(d, dict) and d.get("type") in BODY_KINDS and d.get("uuid"):
            n = conn.execute("DELETE FROM body WHERE kind = ? AND ext_id = ?",
                             (BODY_KINDS[d["type"]][0], str(d["uuid"])[:80])).rowcount
            summary["deleted"] += n

    types = sorted(k for k, v in payload.items() if isinstance(v, list) and k not in ("daily_totals",))
    summary["types"] = types[:20]
    totals = [t for t in payload.get("daily_totals") or [] if isinstance(t, dict) and t.get("date")]
    if totals:
        last = max(totals, key=lambda t: str(t["date"]))
        summary["steps_last"] = {"date": str(last["date"])[:10], "steps": last.get("steps")}
    # Diagnose der App je Datentyp (steht am Ende der Lieferung, die Rohdaten sind gekürzt)
    diag = payload.get("_diagnostics")
    if isinstance(diag, dict):
        summary["diag"] = {
            str(k)[:40]: {"granted": v.get("permission_granted"), "raw": v.get("raw_record_count"),
                          "sent": v.get("filtered_record_count"),
                          "error": str(v["error"])[:120] if v.get("error") else None,
                          "read_from": str(v.get("read_from") or "")[:25] or None}
            for k, v in list(diag.items())[:40] if isinstance(v, dict)}
    if payload.get("backfill"):
        summary["backfill"] = True
    _log(conn, "sync", seq, summary, raw)
    if seq is not None:
        s = db.get_settings(conn)
        if seq > int(s.get("ingest_seq") or 0):
            db.set_setting(conn, "ingest_seq", seq)
    return {"ok": True, **summary}


WATCH = {"steps": "Schritte", "weight": "Gewicht", "body_fat": "Körperfett", "active_calories": "Aktive Kalorien"}


def status(conn) -> dict:
    rows = conn.execute("SELECT ts, seq, kind, summary FROM ingest_log ORDER BY id DESC LIMIT 10").fetchall()
    last = conn.execute("SELECT MAX(updated) FROM activity WHERE source = 'hc'").fetchone()[0]
    # Neueste Diagnose je Datentyp aus den letzten Lieferungen zusammenführen
    diag, have_diag = {}, False
    for r in conn.execute("SELECT summary FROM ingest_log WHERE kind = 'sync' ORDER BY id DESC LIMIT 60"):
        d = json.loads(r["summary"] or "{}").get("diag")
        if d:
            have_diag = True
            for k, v in d.items():
                diag.setdefault(k, v)
    last_weight = conn.execute("SELECT day, value FROM body WHERE kind = 'weight' AND source = 'hc' "
                               "ORDER BY ts DESC LIMIT 1").fetchone()
    types = []
    for key, label in WATCH.items():
        d = diag.get(key)
        if not have_diag:
            state = None
        elif d is None:
            state = "In Life Dashboard nicht ausgewählt (Health → What to send)"
        elif d.get("granted") is False:
            state = "Keine Health-Connect-Berechtigung für Life Dashboard"
        elif d.get("error"):
            state = f"Fehler: {d['error']}"
        elif not d.get("raw"):
            state = "Keine Datensätze im Lesezeitraum – in Life Dashboard „Send history“ nutzen"
        else:
            state = f"ok ({d['raw']} Datensätze gelesen)"
        types.append({"key": key, "label": label, "state": state, "ok": bool(d and d.get("raw") and d.get("granted") is not False)})
    return {
        "last": [{"ts": r["ts"], "seq": r["seq"], "kind": r["kind"], "summary": json.loads(r["summary"] or "{}")}
                 for r in rows],
        "last_activity": last,
        "types": types,
        "has_diag": have_diag,
        "last_weight": dict(last_weight) if last_weight else None,
    }
