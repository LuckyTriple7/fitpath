"""Suche: Alltagsbegriffe finden die BLS-Bezeichnung."""

from app import db, foods


def setup_module():
    db.init()
    with db.connect() as conn:
        foods.ensure_seed(conn)


def top(q):
    with db.connect() as conn:
        return foods.search(conn, q, 3)[0]


def test_everyday_terms():
    assert top("brezel")["name"] == "Laugengebäck mit Hagelsalz"
    assert top("brezel")["portions"][0]["name"] == "1 Brezel"
    assert top("hüttenkäse")["name"].startswith("Körniger Frischkäse")
    assert top("nudeln")["name"] == "Teigwaren eifrei, gekocht"
    assert top("reis")["name"] == "Reis gekocht"
    assert top("hamburger")["name"] == "Hamburger"
    assert top("eis")["name"] == "Vanilleeis"
    assert top("roggenvollkornbrot")["name"].startswith("Roggenvollkornbrot")


def test_grapes_have_portions_not_wine():
    p = top("weintraube")
    assert p["name"].startswith("Weintraube") and p["portions"][0]["name"] == "1 Handvoll"
