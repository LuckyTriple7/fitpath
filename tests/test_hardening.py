"""Befunde aus SECURITY-AUDIT.md: M1 (Webhook), N2, N4, N5, M4 (ValueError/CGNAT), Foto-Endpunkt."""

import socket

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
