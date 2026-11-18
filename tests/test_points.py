from datetime import date

from app import points


def pts(**n):
    return points.round_points(points.raw_points(n))


def test_samples_from_plan():
    # Werte grob nach BLS, Menge bereits eingerechnet
    assert pts(kcal=250, satfat=7.5, sugar=6, protein=5, fiber=1.5) == 9          # Croissant 60 g
    assert pts(kcal=139, sugar=35) == 7                                           # Cola 0,33 l
    assert pts(kcal=215, alcohol=20, sugar=0, protein=2.5) == 8                   # Bier 0,5 l
    assert pts(kcal=260, protein=5, fiber=0.8) == 7                               # Reis gekocht 200 g
    assert pts(kcal=190, satfat=2, protein=6, fiber=3, sugar=1.5) == 5            # Nüsse 30 g
    assert pts(kcal=170, protein=30, sugar=10) == 3                               # Magerquark 250 g
    assert pts(kcal=165, satfat=0.6, protein=35) == 1                             # Hähnchenbrust 150 g


def test_never_negative():
    assert points.raw_points({"kcal": 10, "protein": 30}) == 0


def test_zero_flag_wins():
    assert points.entry_points({"kcal": 500, "zero": 1}) == 0


def test_zero_rules():
    assert points.zero_auto("F110100", "Apfel roh", 58)
    assert not points.zero_auto("F110400", "Apfel getrocknet", 242)
    assert not points.zero_auto("F110600", "Apfelsaft", 44)
    assert not points.zero_auto("F503100", "Avocado roh", 132)
    assert points.zero_auto("G310100", "Broccoli roh", 35)
    assert not points.zero_auto("G830000", "Sahne-Meerrettich Konserve", 289)
    assert points.zero_auto("K710100", "Champignon roh", 28)
    assert not points.zero_auto("B100100", "Roggenvollkornbrot", 193)
    assert not points.zero_auto(None, "Eigenes", 10)


def test_ampel():
    assert points.ampel(58) == "green"
    assert points.ampel(200) == "yellow"
    assert points.ampel(450) == "red"


def test_kcal_target_and_floor():
    s = {"sex": "m", "birth_year": 1975, "height_cm": 178, "activity": 1.375, "mode": "lose", "pace": 0.5}
    t = points.kcal_target(s, 95, date(2026, 11, 18))
    # BMR = 950 + 1112,5 − 255 + 5 = 1812,5; TDEE ≈ 2492; Defizit 550
    assert t["bmr"] == 1812
    assert t["tdee"] == 2492
    assert t["target"] == 1942
    assert not t["floor_hit"]
    small = {"sex": "w", "birth_year": 1950, "height_cm": 150, "activity": 1.2, "mode": "lose", "pace": 1.0}
    t2 = points.kcal_target(small, 50, date(2026, 11, 18))
    assert t2["target"] == 1200 and t2["floor_hit"]
    keep = {**s, "mode": "keep"}
    assert points.kcal_target(keep, 95, date(2026, 11, 18))["deficit"] == 0


def test_pace_capped_at_one_percent():
    s = {"sex": "m", "birth_year": 1975, "height_cm": 178, "activity": 1.375, "mode": "lose", "pace": 1.0}
    t = points.kcal_target(s, 60, date(2026, 11, 18))
    assert t["pace"] <= 0.6 + 0.01


def test_points_budget():
    assert points.points_budget(1942) == 44
    assert points.points_budget(500) == 10


def test_activity_bonus():
    b = points.activity_bonus(12000, 90, 5000)
    assert b["extra_steps"] == 7000
    assert b["kcal_estimate"] == 315
    assert b["kcal"] == 158
    assert b["points"] == 5
    assert points.activity_bonus(3000, 90, 5000)["points"] == 0


def test_week_reserve():
    # Mittwoch: Mo 40 von 50 (Reserve +4, gedeckelt), Di ohne Eintrag (zählt nicht), heute 55
    days = {
        "2026-11-16": {"points": 40, "kcal": 1500, "entries": 5},
        "2026-11-18": {"points": 55, "kcal": 2100, "entries": 6},
    }
    w = points.week_summary(days, date(2026, 11, 18), 50, 1900)
    assert w["start"] == "2026-11-16"
    assert w["reserve_points"] == 4
    assert w["today_left_points"] == -5
    assert w["from_reserve_points"] == 4
    assert w["reserve_kcal"] == 140


def test_week_overdraw_reduces_reserve():
    days = {"2026-11-16": {"points": 60, "entries": 3}, "2026-11-17": {"points": 45, "entries": 3}}
    w = points.week_summary(days, date(2026, 11, 18), 50, 1900)
    assert w["reserve_points"] == -10 + 4
