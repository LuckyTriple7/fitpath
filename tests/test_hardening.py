"""Befunde aus SECURITY-AUDIT.md: M1 (Webhook), M4 (SSRF), N1 (Kopplung), N2, N4, N5, Foto-Endpunkt."""

import socket

import pytest
from datetime import timedelta

from app import ai, auth, db, ingest, main, recipe_import
from tests.test_api import H, client


def _reset_ingest():
    ingest._denied.clear()
    ingest._deny_logged[:] = [0.0, 0]


def test_ingest_body_limit_without_content_length(monkeypatch):
    c = client()
    _reset_ingest()
    monkeypatch.setattr(main, "MAX_INGEST_BYTES", 1000)

    def chunks():                       # Generator = chunked, ohne Content-Length
        for _ in range(10):
            yield b"x" * 500

    assert c.post("/api/ingest/health", content=chunks()).status_code == 413
    assert c.post("/api/ingest/health", content=b"x" * 2000).status_code == 413
    c.__exit__(None, None, None)


def test_ingest_denied_is_throttled():
    c = client()
    _reset_ingest()
    with db.connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM ingest_log WHERE kind = 'denied'").fetchone()[0]
    codes = [c.post("/api/ingest/health", content=b"{}", headers={"X-Signature": "sha256=00"}).status_code
             for _ in range(ingest.DENY_PER_MINUTE + 3)]
    assert set(codes[:ingest.DENY_PER_MINUTE]) == {401}
    assert set(codes[ingest.DENY_PER_MINUTE:]) == {429}      # danach wird der Body gar nicht mehr gelesen
    with db.connect() as conn:
        after = conn.execute("SELECT COUNT(*) FROM ingest_log WHERE kind = 'denied'").fetchone()[0]
    assert after - before == 1                                 # nur ein Protokolleintrag pro Minute
    _reset_ingest()
    c.__exit__(None, None, None)


def test_ingest_check_non_ascii():
    assert ingest.check("geheim", b"{}", "sha256=ä", None) is not None
    assert ingest.check("geheim", b"{}", None, "Bearer ä") is not None
    assert ingest.check("geheim", b"{}", None, "Bearer geheim") is None


def test_bad_input_gives_400_not_500(monkeypatch):
    c = client()
    assert c.put("/api/settings", headers=H, json=[1, 2]).status_code == 400
    assert c.put("/api/settings", headers=H, content=b"null").status_code == 400
    assert c.put("/api/settings", headers=H, content=b"{kaputt").status_code == 400
    assert c.post("/api/events", headers=H, json={"kind": "craving", "intensity": "abc"}).status_code == 400
    assert c.post("/api/events", headers=H, json={"kind": "craving", "food": ["x"]}).status_code == 200
    assert c.post("/api/log", headers=H, json={"food_id": "abc", "grams": 100}).status_code == 400
    assert c.post("/api/log", headers=H, json=[1]).status_code == 400
    assert c.post("/api/onboarding", headers=H, json={"settings": [1]}).status_code == 400
    assert c.post("/api/pair/poll", headers=H, json=[1]).status_code == 400
    monkeypatch.setattr(ai, "AI_KEY", "test")
    assert c.post("/api/ai/label", headers=H, json=["x"]).status_code == 400
    assert c.post("/api/ai/label", headers=H, json={"images": ["data:text/plain;base64,AA=="]}).status_code == 400
    c.__exit__(None, None, None)


def test_link_token_only_once():
    with db.connect() as conn:
        token = auth.create_link(conn, "X").rsplit("/", 1)[1]
        assert auth.redeem(conn, token, "") is not None
        assert auth.redeem(conn, token, "") is None


def test_ssrf_blocks_cgnat_and_bad_addresses(monkeypatch):
    def fake(addr):
        return lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0))]
    for addr in ("100.64.1.1", "10.0.0.1", "127.0.0.1", "::ffff:127.0.0.1", "kaputt"):
        monkeypatch.setattr(socket, "getaddrinfo", fake(addr))
        assert recipe_import._public_host("example.org") is False, addr
    monkeypatch.setattr(socket, "getaddrinfo", fake("8.8.8.8"))
    assert recipe_import._public_host("example.org") is True


def test_ssrf_connects_to_checked_ip(monkeypatch):
    """DNS-Rebinding: Nach der Prüfung darf httpx2 nicht neu auflösen, sondern muss die geprüfte IP nehmen."""
    import httpx2
    answers = iter(["93.184.216.34", "127.0.0.1"])        # erste Auflösung öffentlich, zweite intern
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers), 0))])
    seen = {}

    def handler(request):
        seen.update(host=request.url.host, header=request.headers["host"], sni=request.extensions.get("sni_hostname"))
        return httpx2.Response(200, text="<html></html>")

    real = httpx2.Client
    monkeypatch.setattr(httpx2, "Client", lambda **kw: real(transport=httpx2.MockTransport(handler), **kw))
    recipe_import.fetch("https://rezepte.example/kuchen")
    assert seen == {"host": "93.184.216.34", "header": "rezepte.example", "sni": "rezepte.example"}


class _Req:
    def __init__(self, peer, headers):
        self.client = type("C", (), {"host": peer})()
        self.headers = headers


def test_client_ip_trusts_only_private_proxy():
    xff = {"x-forwarded-for": "6.6.6.6, 203.0.113.7"}
    assert auth.client_ip(_Req("172.18.0.1", xff)) == "203.0.113.7"          # über NPMPlus: rechter Eintrag
    assert auth.client_ip(_Req("172.18.0.1", {"x-real-ip": "203.0.113.8"})) == "203.0.113.8"
    assert auth.client_ip(_Req("8.8.4.4", xff)) == "8.8.4.4"                 # direkt aus dem Internet: fälschbar
    assert auth.client_ip(_Req("172.18.0.1", {"x-forwarded-for": "kaputt"})) == "172.18.0.1"


def test_pairing_limit_per_ip():
    auth._pair_calls.clear()
    with db.connect() as conn:
        conn.execute("DELETE FROM pair_requests")
        for _ in range(auth.PAIR_MAX_PENDING_IP):
            assert auth.pair_start(conn, "", "203.0.113.1")
        assert auth.pair_start(conn, "", "203.0.113.1") is None              # Angreifer ausgebremst …
        r = auth.pair_start(conn, "Mozilla/5.0 (Android)", "198.51.100.2")   # … andere kommen weiter durch
        assert r
        assert auth.pair_info(conn, r["code"], "198.51.100.2")["same_ip"] is True
        info = auth.pair_info(conn, r["code"], "203.0.113.9")
        assert info["same_ip"] is False and info["ip"] == "198.51.100.2"
        conn.execute("DELETE FROM pair_requests")
    auth._pair_calls.clear()
    for _ in range(auth.PAIR_PER_MINUTE_IP):
        assert auth._pair_allowed("203.0.113.3")
    assert not auth._pair_allowed("203.0.113.3")
    assert auth._pair_allowed("203.0.113.4")
    auth._pair_calls.clear()


def test_logout_current_device():
    c = client()
    assert c.get("/api/state").status_code == 200
    assert c.post("/api/logout", json={}).status_code == 403              # ohne App-Header (CSRF)
    r = c.post("/api/logout", headers=H, json={})
    assert r.status_code == 200 and "fp_session" in r.headers.get("set-cookie", "")
    assert c.get("/api/state").status_code == 401
    c.__exit__(None, None, None)


def test_idle_sessions_expire():
    c = client()
    did = next(d["id"] for d in c.get("/api/devices").json() if d["current"])
    old = db.iso(db.now_utc() - timedelta(days=auth.SESSION_IDLE_DAYS + 1))
    with db.connect() as conn:
        conn.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (old, did))
    assert c.get("/api/state").status_code == 401                          # zu lange nicht benutzt
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM devices WHERE id = ?", (did,)).fetchone()[0] == 0

    other = client()                                                       # andere ungenutzte Geräte räumt prune_idle weg
    with db.connect() as conn:
        conn.execute("UPDATE devices SET last_seen = ? WHERE id != ?", (old, max(r[0] for r in conn.execute("SELECT id FROM devices"))))
        assert auth.prune_idle(conn) >= 1
        assert conn.execute("SELECT COUNT(*) FROM devices WHERE last_seen = ?", (old,)).fetchone()[0] == 0
    assert other.get("/api/state").status_code == 200
    c.__exit__(None, None, None)
    other.__exit__(None, None, None)


def test_no_info_leak_without_login(monkeypatch):
    import asyncio
    import httpx2
    c = client()
    assert "version" not in c.get("/healthz").json()
    assert "version" in c.get("/api/state").json()
    # KI-Fehler: der Antworttext (kann die Eingabe enthalten) landet nicht in der Meldung
    resp = httpx2.Response(400, json={"error": {"type": "invalid_request_error", "message": "Ich aß 3 Kekse"}})

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return resp
    monkeypatch.setattr(httpx2, "AsyncClient", FakeClient)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(ai._complete("s", "Ich aß 3 Kekse"))
    assert str(exc.value) == "LiteLLM 400 (invalid_request_error)"
    c.__exit__(None, None, None)
