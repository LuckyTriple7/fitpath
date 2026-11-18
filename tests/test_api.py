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
    assert r.status_code == 401 and "passt nicht" in r.json()["detail"]
    assert c.get("/api/ingest/status").json()["last"][0]["kind"] == "denied"
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
