"""Einkaufsmodus: Packungsgröße aus Open Food Facts, nur angeschaute Produkte nicht unter „Eigene“."""

import httpx2

from app import db, foods
from tests.test_recipes_ai import H, client


def test_off_map_package_and_serving():
    base = {"product_name": "Skyr", "nutriments": {"energy-kcal_100g": 63, "proteins_100g": 11}}
    m = foods.off_map({**base, "serving_quantity": "150", "product_quantity": "500", "product_quantity_unit": "g"})
    assert m["serving_g"] == 150 and m["package_g"] == 500
    assert foods.off_map({**base, "product_quantity": 1000, "product_quantity_unit": "ml"})["package_g"] == 1000
    # unbekannte Einheit oder Unsinn: keine Packung
    assert foods.off_map({**base, "product_quantity": 6, "product_quantity_unit": "Stück"})["package_g"] is None
    assert foods.off_map({**base, "product_quantity": "abc"})["package_g"] is None


class Resp:
    status_code = 200

    def __init__(self, product):
        self.product = product

    def json(self):
        return {"status": 1, "product": self.product}


def test_scanned_only_not_in_custom(monkeypatch):
    c = client()
    with db.connect() as conn:
        conn.execute("DELETE FROM foods WHERE source = 'off'")
    foods._off_calls.clear()
    monkeypatch.setattr(httpx2, "get", lambda *a, **kw: Resp({
        "product_name": "Fruchtjoghurt Erdbeere", "brands": "Testmarke", "serving_quantity": 150,
        "product_quantity": 500, "product_quantity_unit": "g",
        "nutriments": {"energy-kcal_100g": 98, "sugars_100g": 13, "fat_100g": 3, "saturated-fat_100g": 2,
                       "proteins_100g": 3.5}}))
    r = c.get("/api/foods/barcode/4000000000017").json()
    assert r["status"] == "found" and r["new"] and r["food"]["package_g"] == 500 and r["food"]["points_100"] > 0
    fid = r["food"]["id"]
    # zweiter Scan kommt aus dem Cache (kein Open-Food-Facts-Aufruf mehr)
    monkeypatch.setattr(httpx2, "get", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("nicht online fragen")))
    assert c.get("/api/foods/barcode/4000000000017").json()["food"]["id"] == fid

    custom = lambda: [f["id"] for f in c.get("/api/foods/lists").json()["custom"]]  # noqa: E731
    assert fid not in custom()                                   # nur angeschaut
    assert any(h["id"] == fid for h in c.get("/api/foods/search", params={"q": "fruchtjoghurt erdbeere"}).json())
    c.post("/api/log", headers=H, json={"id": "shop1", "food_id": fid, "grams": 150, "meal": "snack"})
    assert fid in custom()                                       # einmal erfasst
    c.delete("/api/log/shop1", headers=H)
    assert fid not in custom()
    c.put(f"/api/foods/{fid}", headers=H, json={"fav": True})
    assert fid in custom()                                       # Favorit
    c.__exit__(None, None, None)


def test_busy_tells_how_long_to_wait(monkeypatch):
    import time
    c = client()
    foods._off_calls[:] = [time.monotonic() - 50] + [time.monotonic()] * (foods.OFF_PER_MINUTE - 1)
    r = c.get("/api/foods/barcode/4000000000024").json()
    assert r["status"] == "busy" and 1 <= r["retry"] <= 11 and r["limit"] == foods.OFF_PER_MINUTE
    foods._off_calls.clear()
    c.__exit__(None, None, None)
