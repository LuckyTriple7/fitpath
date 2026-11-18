"""Rezept-Import per Link: Zutatenzeilen, schema.org-Daten, Schutz vor internen Adressen, API."""

import pytest
from fastapi.testclient import TestClient

from app import auth, db, main, recipe_import as ri

H = {"x-fitpath": "1"}

PAGE = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, {"@type": "Recipe", "name": "Linsen-Eintopf",
 "recipeYield": "4 Portionen", "nutrition": {"@type": "NutritionInformation", "calories": "380 kcal",
 "proteinContent": "18 g", "fatContent": "9 g", "carbohydrateContent": "50 g"},
 "recipeIngredient": ["1 Zwiebel, halbiert", "2 Knoblauchzehen", "2 EL Olivenöl", "250 g Linsen gekocht",
  "400 g Kartoffeln, in Stücken", "800 g Wasser", "1 &frac12; TL Salz", "nach Belieben Petersilie"]}]}
</script></head><body></body></html>"""


def test_parse_line():
    assert ri.parse_line("2 EL Olivenöl")["grams"] == 24
    assert ri.parse_line("1 Zwiebel, halbiert") == {"line": "1 Zwiebel, halbiert", "name": "Zwiebel", "amount": 1.0, "grams": 80.0}
    assert ri.parse_line("40 - 60 g Kartoffeln")["grams"] == 50
    assert ri.parse_line("1 ½ TL Salz")["grams"] == 7.5
    assert ri.parse_line("2 - 2 ½ TL Rapskernöl")["grams"] == 11.2
    assert ri.parse_line("3 Knoblauchzehen")["name"] == "Knoblauchzehen"
    assert ri.parse_line("1 Dose gehackte Tomaten (400 g)")["grams"] == 400


def test_parse_recipe_graph_and_yield():
    r = ri.parse_recipe(PAGE)
    assert r["name"] == "Linsen-Eintopf" and r["servings"] == 4 and r["yield_g"] is None
    assert r["nutrition"]["kcal"] == 380 and "sugar" not in r["nutrition"]
    assert "1 ½ TL Salz" in r["ingredients"]
    r2 = ri.parse_recipe(PAGE.replace('"4 Portionen"', '"755 g"'))
    assert r2["yield_g"] == 755 and r2["servings"] is None
    with pytest.raises(ri.ImportError_):
        ri.parse_recipe("<html>kein Rezept</html>")


def test_private_addresses_blocked():
    for url in ("http://127.0.0.1/x", "http://localhost:8800/", "http://192.168.1.10/", "file:///etc/passwd", "ftp://x.org/"):
        with pytest.raises(ri.ImportError_):
            ri.fetch(url)


def test_import_api(monkeypatch):
    c = TestClient(main.app)
    c.__enter__()
    with db.connect() as conn:
        url = auth.create_link(conn, "Test")
    c.post(url.replace("http://testserver", ""), follow_redirects=False)
    monkeypatch.setattr(ri, "fetch", lambda u: (u, PAGE))
    assert c.post("/api/recipes/import", headers=H, json={"url": "kein link"}).status_code == 400
    r = c.post("/api/recipes/import", headers=H, json={"url": "Schau mal: https://rezepte.example.org/linsen"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["servings"] == 4 and d["nutrition_scope"] == "portion" and d["url"] == "https://rezepte.example.org/linsen"
    by = {it["line"]: it for it in d["items"]}
    assert by["1 Zwiebel, halbiert"]["candidates"][0]["name"] == "Speisezwiebel roh"
    assert by["2 Knoblauchzehen"]["candidates"][0]["name"].startswith("Knoblauch")
    assert not by["800 g Wasser"]["use"] and not by["nach Belieben Petersilie"]["use"]
    # Speichern über den normalen Gerichte-Weg, Quelle bleibt erhalten
    used = [it for it in d["items"] if it["use"]]
    rec = c.post("/api/recipes", headers=H, json={"name": d["name"], "servings": 4, "source_url": d["url"],
                                                   "items": [{"food_id": it["candidates"][0]["id"], "grams": it["grams"]} for it in used]}).json()
    assert rec["recipe"]["source_url"] == "https://rezepte.example.org/linsen" and rec["portions"][0]["name"].startswith("1 Portion")
    c.__exit__(None, None, None)
