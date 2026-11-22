"""Durchstich über die API: Anmeldung, Onboarding, Suche, Eintrag, Gewicht, Webhook."""

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app import auth, db, main

H = {"x-fitpath": "1"}


def client():
    c = TestClient(main.app)
    c.__enter__()   # lifespan: DB, BLS-Seed, VAPID
    with db.connect() as conn:
        url = auth.create_link(conn, "Test")
    path = url.replace("http://testserver", "")
    # GET (z. B. Link-Vorschau eines Messengers) zeigt nur die Bestätigung und verbraucht nichts
    for _ in range(2):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 200 and "Verbinden" in r.text
    r = c.post(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    # danach ist der Link verbraucht
    assert c.get(path, follow_redirects=False).headers["location"] == "/?login=ungueltig"
    assert c.get("/auth/<script>", follow_redirects=False).status_code in (303, 404)
    return c


def test_flow():
    c = client()
    assert c.get("/api/state").status_code == 200
    from app import __version__
    assert c.get("/healthz").json() == {"ok": True}
    assert c.get("/api/state").json()["version"] == __version__
    assert c.post("/api/onboarding", json={}).status_code == 403          # ohne App-Header
    r = c.post("/api/budget/preview", headers=H, json={"start_weight": 95, "height_cm": 178, "birth_year": 1975})
    assert r.json()["points"] > 30
    r = c.post("/api/onboarding", headers=H, json={"settings": {
        "sex": "m", "birth_year": 1975, "height_cm": 178, "start_weight": 95, "goal_weight": 85,
        "activity": 1.375, "mode": "lose", "pace": 0.5, "display": "points"}})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["settings"]["onboarded"] and s["body"]["weight"] == 95
    assert s["overview"]["budget"]["points"] == 44

    hits = c.get("/api/foods/search", params={"q": "apfel"}).json()
    assert hits and hits[0]["name"].lower().startswith("apfel")
    apfel = next(h for h in hits if h["name"] == "Apfel roh")
    assert apfel["zero"] and apfel["portions"][0]["g"] == 150
    brot = c.get("/api/foods/search", params={"q": "roggenvollkornbrot"}).json()[0]
    assert not brot["zero"] and brot["portions"][0]["name"] == "1 Scheibe"

    r = c.post("/api/log", headers=H, json={"id": "e1", "food_id": brot["id"], "grams": 100, "meal": "fruehstueck"})
    ov = r.json()["overview"]
    assert ov["entries"][0]["points"] > 0
    used = ov["totals"]["points"]
    assert ov["week"]["today_left_points"] == 44 - used
    # gleiche id = ändern, kein zweiter Eintrag
    r = c.post("/api/log", headers=H, json={"id": "e1", "food_id": brot["id"], "grams": 50, "meal": "fruehstueck"})
    assert len(r.json()["overview"]["entries"]) == 1
    c.post("/api/log", headers=H, json={"id": "e2", "food_id": apfel["id"], "grams": 150, "meal": "snack"})
    st = c.get("/api/state").json()
    assert any(e["zero"] and e["points"] == 0 for e in st["overview"]["entries"])
    assert st["recent"][0]["last_grams"] in (50, 150)
    # „Zuletzt“ passend zur Mahlzeit: Brot nur beim Frühstück, Apfel nur bei Snacks
    bm = c.get("/api/foods/lists").json()["by_meal"]
    assert [f["id"] for f in bm["fruehstueck"]] == [brot["id"]]
    assert [f["id"] for f in bm["snack"]] == [apfel["id"]]
    assert bm["abend"] == []

    # eigenes Lebensmittel mit Barcode, danach per Barcode gefunden (ohne Netz)
    f = c.post("/api/foods", headers=H, json={"name": "Proteinriegel", "kcal": 350, "protein": 30, "sugar": 5,
                                              "code": "4001234567890", "serving_g": 45}).json()
    assert f["portions"][0]["g"] == 45
    assert c.get("/api/foods/barcode/4001234567890").json()["status"] == "found"
    c.put(f"/api/foods/{f['id']}", headers=H, json={"fav": True})
    assert c.get("/api/foods/lists").json()["favorites"][0]["name"] == "Proteinriegel"

    r = c.post("/api/body", headers=H, json={"kind": "weight", "value": "94,2"})
    assert r.json()["body"]["count"] == 1   # gleicher Tag: erstes Wiegen zählt
    assert c.get("/api/stats?days=7").json()["logged_days"] == 0   # heute zählt noch nicht

    # Webhook: ohne Geheimnis abgelehnt, dann mit Signatur
    body = json.dumps({"source": "health_connect", "sequence": 1,
                       "daily_totals": [{"date": st["today"], "steps": 11000}]}).encode()
    assert c.post("/api/ingest/health", content=body).status_code == 401
    assert c.get("/api/ingest/pair").status_code == 404
    pair = c.post("/api/ingest/secret", headers=H).json()
    secret = pair["secret"]
    assert pair["qr_svg"].startswith("<svg") and pair["app_link"].startswith("lifedashboard://pair#")
    assert c.get("/api/ingest/pair").json()["secret"] == secret
    r = c.post("/api/ingest/health", content=body, headers={"X-Signature": "sha256=00"})
    assert r.status_code == 401 and r.json()["detail"] == "nicht autorisiert"   # Grund nicht nach außen
    last = c.get("/api/ingest/status").json()["last"][0]
    assert last["kind"] == "denied" and last["summary"]["reason"]               # aber im Protokoll
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    r = c.post("/api/ingest/health", content=body, headers={"X-Signature": sig, "content-type": "application/json"})
    assert r.status_code == 200 and r.json()["days"] == 1
    st = c.get("/api/state").json()
    assert st["overview"]["activity"]["steps"] == 11000
    assert st["overview"]["activity"]["act_points"] > 0
    assert "ingest_secret" not in st["settings"]
    assert c.get("/api/export").status_code == 200

    # Gerät umbenennen
    dev = c.get("/api/devices").json()[0]
    assert c.put(f"/api/devices/{dev['id']}", headers=H, json={"name": "  PC  "}).status_code == 200
    assert c.get("/api/devices").json()[0]["name"] == "PC"
    assert c.put(f"/api/devices/{dev['id']}", headers=H, json={"name": ""}).status_code == 400
    assert c.put("/api/devices/9999", headers=H, json={"name": "X"}).status_code == 404
    c.__exit__(None, None, None)


def test_pairing_with_code():
    old = client()                                  # schon verbundenes Gerät
    new = TestClient(main.app)                      # neues Gerät ohne Cookie
    assert new.get("/api/state").status_code == 401
    assert new.post("/api/pair/start", json={}).status_code == 403          # ohne App-Header
    ua = {**H, "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"}
    r = new.post("/api/pair/start", headers=ua, json={}).json()
    code, rid = r["code"], r["rid"]
    assert len(code) == 6 and r["link"].endswith(f"/#pair={code}") and "<svg" in r["qr_svg"]
    assert new.post("/api/pair/poll", headers=H, json={"rid": rid}).json() == {"status": "pending"}
    assert new.get(f"/api/pair/{code}").status_code == 401                 # freigeben nur angemeldet
    info = old.get(f"/api/pair/{code}").json()
    assert info["label"] == "Windows · Chrome" and info["name"] == "Windows"
    assert old.get("/api/pair/000000x").status_code == 404
    assert old.post(f"/api/pair/{code}", json={"approve": True}).status_code == 403   # ohne App-Header
    assert old.post(f"/api/pair/{code}", headers=H, json={"approve": True, "name": "Büro-PC"}).json() == {"ok": True}
    assert old.get(f"/api/pair/{code}").status_code == 404                 # nur einmal freigeben
    assert new.post("/api/pair/poll", headers=H, json={"rid": "falsch"}).json() == {"status": "expired"}
    r = new.post("/api/pair/poll", headers=H, json={"rid": rid})
    assert r.json() == {"status": "approved"} and auth.COOKIE in r.cookies
    assert new.get("/api/state").status_code == 200
    assert "Büro-PC" in [d["name"] for d in old.get("/api/devices").json()]
    assert new.post("/api/pair/poll", headers=H, json={"rid": rid}).json() == {"status": "expired"}   # verbraucht
    # ablehnen
    other = TestClient(main.app)
    r = other.post("/api/pair/start", headers=H, json={}).json()
    old.post(f"/api/pair/{r['code']}", headers=H, json={"approve": False})
    assert other.post("/api/pair/poll", headers=H, json={"rid": r["rid"]}).json() == {"status": "denied"}
    assert other.get("/api/state").status_code == 401
    old.__exit__(None, None, None)


def test_pairing_limits():
    c = TestClient(main.app)
    c.__enter__()
    auth._pair_calls.clear()
    with db.connect() as conn:
        conn.execute("DELETE FROM pair_requests")
    # je IP höchstens PAIR_MAX_PENDING_IP offene Anfragen (der TestClient hat immer dieselbe Adresse)
    codes = [c.post("/api/pair/start", headers=H, json={}).status_code for _ in range(auth.PAIR_MAX_PENDING_IP + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {200}
    auth._pair_calls.clear()
    with db.connect() as conn:                       # abgelaufene Anfragen werden aufgeräumt
        conn.execute("UPDATE pair_requests SET expires = '2000-01-01T00:00:00+00:00'")
        auth._pair_cleanup(conn)
        assert conn.execute("SELECT COUNT(*) FROM pair_requests").fetchone()[0] == 0
    c.__exit__(None, None, None)
