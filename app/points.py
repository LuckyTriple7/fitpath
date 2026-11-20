"""Punktesystem, 0-Punkte-Regeln, Tagesbudget, Wochenreserve und Aktivität.

Alle Faktoren stehen hier an einer Stelle. Einträge im Tagebuch speichern die
Nährwerte als Schnappschuss; Punkte werden immer daraus berechnet. Eine
geänderte Formel rechnet alte Tage also sauber neu.

Formel je Eintrag (Gramm der gegessenen Menge):

    Punkte = kcal/35 + ges. Fett/4 + Zucker/10 + Alkohol/8 − Eiweiß/10 − Ballaststoffe/5

nicht unter 0, auf ganze Punkte gerundet. Gesättigtes Fett, Zucker und
Alkohol kosten extra, Eiweiß und Ballaststoffe machen satt und geben einen
Abzug. Frisches Obst und Gemüse zählen 0 Punkte.
"""

import re
from datetime import date, timedelta

KCAL_PER_POINT = 35
SATFAT_PER_POINT = 4
SUGAR_PER_POINT = 10
ALCOHOL_PER_POINT = 8
PROTEIN_PER_POINT = 10
FIBER_PER_POINT = 5

ZERO_ALLOWANCE_KCAL = 200      # kcal pro Tag, die 0-Punkte-Lebensmittel im Schnitt liefern
# Budget-Umrechnung: Wer satt machend isst (viel Eiweiß und Ballaststoffe, wenig Zucker),
# bekommt rund 45–50 kcal je Punkt, bei typischer Mischkost sind es gut 30. Mit 40 kcal je
# Budgetpunkt bleibt bei guter Auswahl ein Defizit, bei schlechter wird es eng.
KCAL_PER_BUDGET_POINT = 40
RESERVE_CAP_POINTS = 4         # so viele ungenutzte Tagespunkte wandern höchstens in die Reserve
RESERVE_CAP_KCAL = RESERVE_CAP_POINTS * KCAL_PER_POINT
KCAL_PER_KG = 7700             # Energiegehalt von 1 kg Körperfett (Näherung)
MAX_LOSS_SHARE_WEEK = 0.01     # höchstens 1 % des Körpergewichts pro Woche
KCAL_FLOOR = {"m": 1500, "w": 1200}
KCAL_PER_STEP_PER_KG = 0.0005  # ≈ 0,04 kcal je Schritt bei 80 kg (Gehen)
ACTIVITY_CREDIT = 0.5          # nur die Hälfte der Schätzung wird gutgeschrieben

ACTIVITY_LEVELS = {
    1.2: "Sitzend (Büro, wenig Bewegung)",
    1.375: "Leicht aktiv (Alltag zu Fuß, etwas stehen)",
    1.55: "Mäßig aktiv (viel auf den Beinen)",
    1.725: "Sehr aktiv (körperliche Arbeit)",
}


# ---------- Punkte je Eintrag ----------

def raw_points(n: dict) -> float:
    """Punkte für Nährwerte in Gramm (bereits auf die Menge umgerechnet)."""
    g = lambda k: float(n.get(k) or 0)  # noqa: E731
    value = (g("kcal") / KCAL_PER_POINT + g("satfat") / SATFAT_PER_POINT + g("sugar") / SUGAR_PER_POINT
             + g("alcohol") / ALCOHOL_PER_POINT - g("protein") / PROTEIN_PER_POINT - g("fiber") / FIBER_PER_POINT)
    return max(0.0, value)


def round_points(value: float) -> int:
    return int(value + 0.5)


def entry_points(entry: dict) -> int:
    if entry.get("zero"):
        return 0
    if entry.get("points_raw") is not None:   # Gerichte: vorab berechnet, 0-Punkte-Zutaten ausgenommen
        return round_points(float(entry["points_raw"]))
    return round_points(raw_points(entry))


def scale(food: dict, grams: float) -> dict:
    """Nährwerte je 100 g auf eine Menge umrechnen."""
    f = grams / 100.0
    return {k: round(float(food.get(k) or 0) * f, 3) for k in
            ("kcal", "protein", "fat", "satfat", "carbs", "sugar", "fiber", "alcohol", "salt")}


def ampel(kcal_per_100g) -> str:
    """Energiedichte: grün < 1 kcal/g, gelb bis 2,4, rot darüber."""
    k = float(kcal_per_100g or 0)
    if k < 100:
        return "green"
    if k <= 240:
        return "yellow"
    return "red"


# ---------- 0-Punkte-Regeln (BLS-Hauptgruppen) ----------

ZERO_EXCLUDE = re.compile(
    r"saft|nektar|getrocknet|gezuckert|gesüßt|kandiert|sirup|chips|frittiert|mus\b|konfitüre|"
    r"in öl|sahne|creme|gebacken|paniert|mit fett|püree|soße|sauce", re.I)


def zero_auto(code: str | None, name: str, kcal) -> bool:
    """Frisches Obst und Gemüse, Pilze, Sprossen und gekochte Hülsenfrüchte zählen 0 Punkte."""
    if not code or not code[:1].isalpha():
        return False
    k = float(kcal or 0)
    group, sub = code[0], code[:2]
    if ZERO_EXCLUDE.search(name or ""):
        return False
    if group == "F" and sub not in ("F8", "F9"):
        return k <= 90
    if group == "G" and sub != "G8":
        return k <= 90
    if sub == "K7":          # Pilze
        return k <= 60
    if sub == "H6":          # Sprossen
        return k <= 60
    if sub == "H7" and "gekocht" in (name or "").lower():   # Hülsenfrüchte gegart
        return k <= 150
    return False


# ---------- Budget ----------

def age(birth_year: int, today: date | None = None) -> int:
    today = today or date.today()
    return max(16, min(today.year - int(birth_year), 100))


def bmr(sex: str, weight: float, height_cm: float, years: int) -> float:
    """Grundumsatz nach Mifflin-St Jeor."""
    base = 10 * weight + 6.25 * height_cm - 5 * years
    return base + (5 if sex == "m" else -161)


def kcal_target(s: dict, weight: float, today: date | None = None) -> dict:
    sex = "w" if s.get("sex") == "w" else "m"
    b = bmr(sex, weight, float(s.get("height_cm") or 175), age(s.get("birth_year") or 1975, today))
    # Korrektur aus dem adaptiven Bedarf (app/adaptive.py), nur nach Bestätigung durch den Nutzer
    adjust = int(s.get("tdee_adjust") or 0)
    tdee = b * float(s.get("activity") or 1.375) + adjust
    pace = 0.0
    if s.get("mode", "lose") == "lose":
        pace = min(float(s.get("pace") or 0.5), weight * MAX_LOSS_SHARE_WEEK)
    deficit = pace * KCAL_PER_KG / 7
    floor = KCAL_FLOOR[sex]
    target = max(tdee - deficit, floor)
    return {
        "bmr": round(b), "tdee": round(tdee), "adjust": adjust, "deficit": round(tdee - target),
        "target": round(target), "floor": floor, "floor_hit": tdee - deficit < floor,
        "pace": round((tdee - target) * 7 / KCAL_PER_KG, 2),
    }


def points_budget(kcal: float) -> int:
    """Tagesbudget in Punkten: (kcal-Ziel − Anteil 0-Punkte-Lebensmittel) ÷ 40."""
    return max(10, round_points((kcal - ZERO_ALLOWANCE_KCAL) / KCAL_PER_BUDGET_POINT))


# ---------- Aktivität ----------

def activity_bonus(steps, weight: float, baseline: int) -> dict:
    """Bonus aus Schritten über der Grundlinie. Nur die Hälfte wird gutgeschrieben,
    weil Schätzungen den Verbrauch meist überschätzen."""
    extra = max(0, int(steps or 0) - int(baseline or 0))
    estimate = extra * weight * KCAL_PER_STEP_PER_KG
    credited = estimate * ACTIVITY_CREDIT
    return {"extra_steps": extra, "kcal_estimate": round(estimate), "kcal": round(credited), "kcal_raw": credited,
            "points": round_points(credited / KCAL_PER_POINT)}


# ---------- Woche und Reserve ----------

def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_summary(days: dict, today: date, budget_points: int, budget_kcal: int) -> dict:
    """days: {JJJJ-MM-TT: {"points", "kcal", "entries", "act_points", "act_kcal"}}.

    Reserve: Für jeden vergangenen Tag dieser Woche mit mindestens einem Eintrag
    wandert der Rest (Budget + Aktivität − verbraucht) in die Reserve, höchstens
    RESERVE_CAP je Tag. Ein überzogener Tag zieht von der Reserve ab. Tage ohne
    Eintrag zählen nicht (sonst wächst die Reserve, wenn man nichts erfasst).
    """
    start = week_start(today)
    res_p, res_k = 0, 0.0
    per_day = []
    d = start
    while d <= today:
        key = d.isoformat()
        x = days.get(key) or {}
        used_p, used_k = int(x.get("points") or 0), float(x.get("kcal") or 0)
        act_p, act_k = int(x.get("act_points") or 0), float(x.get("act_kcal") or 0)
        left_p = budget_points + act_p - used_p
        left_k = budget_kcal + act_k - used_k
        if d < today and x.get("entries"):
            res_p += min(left_p, RESERVE_CAP_POINTS)
            res_k += min(left_k, RESERVE_CAP_KCAL)
        per_day.append({"day": key, "points": used_p, "kcal": round(used_k), "entries": int(x.get("entries") or 0),
                        "left_points": left_p, "left_kcal": round(left_k)})
        d += timedelta(days=1)
    t = days.get(today.isoformat()) or {}
    left_p = budget_points + int(t.get("act_points") or 0) - int(t.get("points") or 0)
    left_k = budget_kcal + float(t.get("act_kcal") or 0) - float(t.get("kcal") or 0)
    return {
        "start": start.isoformat(),
        "reserve_points": res_p,
        "reserve_kcal": round(res_k),
        "today_left_points": left_p,
        "today_left_kcal": round(left_k),
        "from_reserve_points": min(-left_p, max(res_p, 0)) if left_p < 0 else 0,
        "from_reserve_kcal": round(min(-left_k, max(res_k, 0))) if left_k < 0 else 0,
        "days": per_day,
    }
