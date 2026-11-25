import hashlib
import hmac
import json
from datetime import date

from app import body, db, ingest


def setup_module():
    db.init()


def test_trend_smooths():
    s = body.trend_series([("2026-11-01", 90.0), ("2026-11-02", 91.0), ("2026-11-03", 89.0)])
    assert s[0]["trend"] == 90.0
    assert s[1]["trend"] == 90.1
    assert s[2]["trend"] == 89.99


def test_rate_per_week():
    days = [(f"2026-11-{d:02d}", 90 - 0.1 * d) for d in range(1, 22)]
    series = [{"day": d, "trend": w} for d, w in days]
    r = body.rate_per_week(series, date(2026, 11, 21))
    assert r == -0.7
    assert body.rate_per_week(series[:3], date(2026, 11, 3)) is None


def test_verify_signature_and_bearer():
    raw = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"geheim", raw, hashlib.sha256).hexdigest()
    assert ingest.verify("geheim", raw, sig, None)
    assert not ingest.verify("geheim", raw, "sha256=00", None)
    assert ingest.verify("geheim", raw, None, "Bearer geheim")
    assert not ingest.verify("geheim", raw, None, "Bearer falsch")
    assert not ingest.verify(None, raw, sig, None)


PAYLOAD = {
    "timestamp": "2026-11-18T07:15:02.481Z", "app_version": "1.30.1", "source": "health_connect",
    "timezone": "Europe/Berlin", "sequence": 100,
    "daily_totals": [
        {"date": "2026-11-17", "steps": 9874, "distance_meters": 7120.0, "active_calories": 498.4, "total_calories": 2390.1},
        {"date": "2026-11-18", "steps": 1204, "active_calories": 58.2},
    ],
    "steps": [{"count": 412, "start_time": "2026-11-18T06:00:00Z", "end_time": "2026-11-18T07:00:00Z",
               "uuid": "s1", "source": "com.google.android.apps.fitness"}],
    "weight": [{"kilograms": 92.4, "time": "2026-11-17T23:30:00.123456789Z", "uuid": "w1", "source": "com.withings"}],
    "body_fat": [{"percentage": 24.5, "time": "2026-11-18T06:30:00Z", "uuid": "f1"}],
}


def test_apply_payload_and_dedupe():
    with db.connect() as conn:
        for table in ("body", "activity", "ingest_log"):
            conn.execute(f"DELETE FROM {table}")
        r = ingest.apply(conn, PAYLOAD, json.dumps(PAYLOAD).encode())
        assert r["days"] == 2 and r["weight"] == 1 and r["body_fat"] == 1
        # gleiche sequence nochmal: wird übersprungen
        assert ingest.apply(conn, PAYLOAD)["duplicate"]
        a = {x["day"]: dict(x) for x in conn.execute("SELECT * FROM activity")}
        assert a["2026-11-17"]["steps"] == 9874
        w = conn.execute("SELECT * FROM body WHERE kind = 'weight'").fetchone()
        # 23:30 UTC ist in Berlin schon der 18.
        assert w["day"] == "2026-11-18" and w["value"] == 92.4

        # neuere Lieferung aktualisiert den laufenden Tag, ältere nicht
        newer = {**PAYLOAD, "sequence": 102, "daily_totals": [{"date": "2026-11-18", "steps": 5000}],
                 "weight": [], "body_fat": []}
        ingest.apply(conn, newer)
        older = {**PAYLOAD, "sequence": 101, "daily_totals": [{"date": "2026-11-18", "steps": 3000}],
                 "weight": [], "body_fat": []}
        ingest.apply(conn, older)
        steps = conn.execute("SELECT steps FROM activity WHERE day = '2026-11-18'").fetchone()[0]
        assert steps == 5000

        # Gewicht erneut mit gleicher uuid: kein Duplikat, Wert aktualisiert
        again = {"source": "health_connect", "sequence": 103,
                 "weight": [{"kilograms": 92.0, "time": "2026-11-17T23:30:00Z", "uuid": "w1"}]}
        ingest.apply(conn, again)
        rows = conn.execute("SELECT value FROM body WHERE kind = 'weight'").fetchall()
        assert [r[0] for r in rows] == [92.0]

        # Löschung
        ingest.apply(conn, {"source": "health_connect", "sequence": 104,
                            "deleted_records": [{"type": "weight", "uuid": "w1"}]})
        assert conn.execute("SELECT COUNT(*) FROM body WHERE kind = 'weight'").fetchone()[0] == 0
        assert ingest.apply(conn, {"test": True, "source": "health_connect"})["test"]


def test_pairing_link_known_vector():
    # Test-Vektor aus docs/pairing.md von Life Dashboard Companion
    link = ingest.pairing_link("http://192.168.10.138:8123/api/webhook/" + "a" * 64, "b" * 64,
                               name="Home Assistant", sources=("health_connect", "screen_time"))
    assert link == (
        "https://owen282000.github.io/life-dashboard-companion-app/pair#v=1&url=http%3A%2F%2F192.168.10.138%3A8123"
        "%2Fapi%2Fwebhook%2F" + "a" * 64 + "&secret=" + "b" * 64 + "&name=Home%20Assistant&sources=health_connect%2Cscreen_time")
    assert ingest.pairing_link("https://x/y", "s", app=True).startswith("lifedashboard://pair#v=1&url=https%3A%2F%2Fx%2Fy")
    info = ingest.pair_info("https://fp.example/api/ingest/health", "geheim")
    assert info["qr_svg"].startswith("<svg") and "secret=geheim" in info["link"]


def test_check_reasons():
    raw = b"{}"
    assert "kein Geheimnis" in ingest.check(None, raw, None, None)
    assert "Ohne Signatur" in ingest.check("g", raw, None, None)
    assert "passt nicht" in ingest.check("g", raw, "sha256=00", None)
    good = "sha256=" + hmac.new(b"g", raw, hashlib.sha256).hexdigest()
    assert ingest.check("g", raw, good, None) is None


def test_status_diagnostics():
    with db.connect() as conn:
        conn.execute("DELETE FROM ingest_log")
        diag = {"steps": {"permission_granted": True, "raw_record_count": 96, "filtered_record_count": 3, "error": None},
                "body_fat": {"permission_granted": False, "raw_record_count": 0, "filtered_record_count": 0, "error": None},
                "active_calories": {"permission_granted": True, "raw_record_count": 0, "filtered_record_count": 0, "error": None}}
        ingest.apply(conn, {"source": "health_connect", "sequence": 900, "_diagnostics": diag,
                            "daily_totals": [{"date": "2026-11-18", "steps": 626}]})
        # spätere Pakete desselben Syncs: nur der noch laufende Typ
        ingest.apply(conn, {"source": "health_connect", "sequence": 901,
                            "_diagnostics": {"heart_rate": {"permission_granted": True, "raw_record_count": 2000}}})
        st = {t["key"]: t for t in ingest.status(conn)["types"]}
        assert st["steps"]["ok"] and "96" in st["steps"]["state"]
        assert "nicht ausgewählt" in st["weight"]["state"]
        assert "Berechtigung" in st["body_fat"]["state"]
        assert "Send history" in st["active_calories"]["state"]
        last = ingest.status(conn)["last"]
        assert any(x["summary"].get("steps_last", {}).get("steps") == 626 for x in last)


def test_weight_twins_from_several_apps():
    """Samsung Health und Health Sync schreiben dieselbe Messung mit eigener uuid nach Health Connect."""
    with db.connect() as conn:
        for table in ("body", "ingest_log"):
            conn.execute(f"DELETE FROM {table}")
        r = ingest.apply(conn, {"source": "health_connect", "sequence": 300, "weight": [
            {"kilograms": 97.0, "time": "2026-11-18T06:10:00Z", "uuid": "sh1", "source": "com.sec.android.app.shealth"},
            {"kilograms": 97.0, "time": "2026-11-18T06:10:00Z", "uuid": "hs1", "source": "nl.appyhapps.healthsync"},
            {"kilograms": 96.999, "time": "2026-11-18T06:12:30Z", "uuid": "gf1", "source": "com.google.android.apps.fitness"},
            # anderer Wert oder deutlich später: eigene Messung
            {"kilograms": 96.4, "time": "2026-11-18T06:11:00Z", "uuid": "sh2"},
            {"kilograms": 97.0, "time": "2026-11-18T18:00:00Z", "uuid": "sh3"},
        ]})
        assert r["weight"] == 3 and r["twins"] == 2
        ids = sorted(x[0] for x in conn.execute("SELECT ext_id FROM body WHERE kind = 'weight'"))
        assert ids == ["sh1", "sh2", "sh3"]
        # spätere Lieferung derselben Datensätze: Zwilling bleibt draußen, der bekannte wird aktualisiert
        r = ingest.apply(conn, {"source": "health_connect", "sequence": 301, "weight": [
            {"kilograms": 97.0, "time": "2026-11-18T06:10:00Z", "uuid": "hs1"},
            {"kilograms": 97.0, "time": "2026-11-18T06:10:00Z", "uuid": "sh1"}]})
        assert r["weight"] == 1 and r["twins"] == 1
        assert conn.execute("SELECT COUNT(*) FROM body WHERE kind = 'weight'").fetchone()[0] == 3


def test_dedupe_existing_twins():
    with db.connect() as conn:
        conn.execute("DELETE FROM body")
        rows = [("2026-11-22T06:00:00+00:00", 96.0, "hc", "a"), ("2026-11-22T06:00:00+00:00", 96.0, "hc", "b"),
                ("2026-11-22T06:05:00+00:00", 96.0, "hc", "c"), ("2026-11-22T06:00:00+00:00", 96.0, "manual", None),
                ("2026-11-22T06:00:00+00:00", 96.0, "hc", None)]
        for ts, v, src, ext in rows:
            conn.execute("INSERT INTO body (ts, day, kind, value, source, ext_id) VALUES (?, '2026-11-22', 'weight', ?, ?, ?)",
                         (ts, v, src, ext))
        conn.execute("INSERT INTO body (ts, day, kind, value, source, ext_id) VALUES "
                     "('2026-11-22T06:00:00+00:00', '2026-11-22', 'fat', 24.0, 'hc', 'f')")
        assert db.dedupe_body(conn) == 3
        left = conn.execute("SELECT kind, source, ext_id FROM body ORDER BY id").fetchall()
        assert [tuple(x) for x in left] == [("weight", "hc", "a"), ("weight", "manual", None), ("fat", "hc", "f")]
        assert db.dedupe_body(conn) == 0
