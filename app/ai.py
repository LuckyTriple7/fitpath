"""KI über einen OpenAI-kompatiblen Endpunkt: Erfassen per Text, Rezept-Zutaten, Nährwerte vom Foto.

Ablauf: Die KI zerlegt eine freie Beschreibung („2 Brötchen mit Käse und Kaffee mit Milch“)
in Lebensmittel mit geschätzter Menge und einem Suchbegriff in der Sprache einer deutschen
Nährwerttabelle. FitPath sucht jeden Begriff in der eigenen Datenbank und schlägt die
besten Treffer vor. Erfasst wird erst, wenn der Nutzer bestätigt.

Nährwerte vom Foto: Die KI liest die Nährwerttabelle einer Packung ab (je 100 g) und füllt
das Formular „Eigenes Lebensmittel“ vor. Gespeichert wird erst, wenn der Nutzer prüft.
Das Modell muss Bilder verstehen (z. B. Claude Haiku/Sonnet, GPT-4o-mini).

Datenschutz: An die KI geht nur der eingegebene Text bzw. das Foto, sonst nichts aus der App.
Fotos werden nicht gespeichert.
"""

import json
import os
import re

import httpx

from . import diary, foods

def _env(*names: str, default: str = "") -> str:
    """Erster gesetzter Wert; die alten Namen (LITELLM_…) gelten weiter."""
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return default


# KI über einen OpenAI-kompatiblen Endpunkt (LiteLLM, OpenRouter, OpenAI, Ollama …).
# Adresse mit oder ohne /v1. Ohne Key ist die KI aus (Ollama: beliebigen Key eintragen).
AI_URL = _env("AI_BASE_URL", "LITELLM_URL", default="http://litellm:4000").rstrip("/")
AI_KEY = _env("AI_API_KEY", "LITELLM_API_KEY")
CHAT_URL = AI_URL + ("/chat/completions" if AI_URL.endswith("/v1") else "/v1/chat/completions")
MODEL_FAST = _env("AI_MODEL_FAST", "FITPATH_MODEL_FAST", default="claude-haiku-5-5")

HEADERS = {"Content-Type": "application/json",
           # schaltet ein Proxy-Plugin für knappe Antworten ab, andere Anbieter ignorieren den Header
           "x-caveman-style": "off"}
if AI_KEY:
    HEADERS["Authorization"] = f"Bearer {AI_KEY}"
try:  # zusätzliche Header als JSON, z. B. {"HTTP-Referer": "https://…"} für OpenRouter
    HEADERS.update({str(k): str(v) for k, v in json.loads(_env("AI_HEADERS", default="{}")).items()})
except (ValueError, AttributeError):
    print("AI_HEADERS ist kein JSON-Objekt, ignoriert", flush=True)


PARSE_SYSTEM = """Du zerlegst eine Beschreibung von Essen und Trinken in einzelne Lebensmittel.
Antworte ausschließlich mit JSON, ohne Text davor oder danach:
{"meal": "fruehstueck" | "mittag" | "abend" | "snack" | null,
 "items": [{"label": "...", "search": "...", "grams": 123}]}

- label: der Teil der Beschreibung mit Menge, z. B. "2 Brötchen", "Schuss Milch".
- search: Suchbegriff wie in einer deutschen Nährwerttabelle (Bundeslebensmittelschlüssel):
  Grundform, Einzahl, ohne Mengenangabe, Zubereitung dazu, wenn klar.
  Beispiele: "Weizenbrötchen", "Roggenmischbrot", "Gouda", "Butter", "Vollmilch", "Milch fettarm",
  "Kaffee (Getränk)", "Hühnerei gekocht", "Spiegelei", "Teigwaren eifrei gekocht", "Reis gekocht",
  "Kartoffel gekocht", "Hähnchen Brustfilet gebraten", "Apfel roh", "Banane roh", "Joghurt mild",
  "Pils", "Colagetränk", "Pizza Margherita", "Bratwurst", "Pommes frites".
  Bei Markenprodukten die Produktart (z. B. "Nuss-Nougat-Creme" statt Markenname).
- grams: geschätzte gegessene Menge in Gramm (Getränke: ml ≈ g). Übliche Mengen:
  Brötchen 60, Scheibe Brot 50, Scheibe Toast 25, Scheibe Käse 25, Scheibe Wurst 15, Ei 55,
  Butter fürs Brot 10, Marmelade/Honig 20, Tasse Kaffee 150, Schuss Milch 15, Glas 200,
  Flasche Bier 500, Teller Nudeln gekocht 250, Portion Reis gekocht 200, Kartoffel 80,
  Apfel 150, Banane 120, EL Öl 10, Riegel 50, Stück Kuchen 120, Kugel Eis 60.
- Zusammengesetzte Gerichte in Hauptzutaten zerlegen, wenn es kein übliches Fertiggericht ist.
- meal nur setzen, wenn die Beschreibung es nennt („zum Frühstück“, „mittags“ …), sonst null.
- Wasser, ungesüßter Tee und Gewürze weglassen."""


INGREDIENT_SYSTEM = """Du bekommst die Zutatenliste eines Rezepts, eine Zutat pro Zeile mit Nummer.
Antworte ausschließlich mit JSON: {"items": [{"i": 0, "search": "...", "grams": 123}]}, ein Eintrag je Zeile, gleiche Reihenfolge.
- search: Suchbegriff wie in einer deutschen Nährwerttabelle (Bundeslebensmittelschlüssel), deutsch, Grundform,
  Einzahl, roh, wenn nicht anders angegeben. Beispiele: "Speisezwiebel roh", "Karotte", "Süßkartoffel roh",
  "Hähnchen Schenkel", "Rapsöl", "Gemüsebrühe", "Schlagsahne", "Butter", "Weizenmehl", "Zucker", "Vollmilch".
  Englische Zutaten übersetzen.
- grams: Menge der Zeile in Gramm (Flüssigkeit ml ≈ g). Spannen: Mittelwert. Ohne Menge: übliche Menge für ein Rezept.
  Stückgewichte: Zwiebel 80, Knoblauchzehe 4, Karotte 70, Ei 55, Kartoffel 80, EL 12, TL 5, Prise 0,5."""


async def parse_ingredients(lines: list) -> list:
    """Je Zutat {search, grams} oder leer, Reihenfolge wie die Eingabe."""
    text = "\n".join(f"{i}: {l}" for i, l in enumerate(lines))
    data = extract_json(await _complete(INGREDIENT_SYSTEM, text, max_tokens=1500))
    out = [{} for _ in lines]
    for it in data.get("items") or []:
        try:
            i = int(it.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(out):
            g = it.get("grams")
            out[i] = {"search": str(it.get("search") or "")[:80],
                      "grams": float(g) if isinstance(g, (int, float)) and 0 < g <= 10000 else None}
    return out


def available() -> bool:
    return bool(AI_KEY)


async def _complete(system: str, user, max_tokens: int = 700) -> str:
    """user: Text oder OpenAI-Inhaltsliste (Text und Bilder)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10)) as client:
        resp = await client.post(
            CHAT_URL, headers=HEADERS,
            # keine temperature: claude-sonnet-5-5 lehnt Werte ≠ 1 ab
            json={"model": MODEL_FAST, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    if resp.status_code != 200:
        raise RuntimeError(f"LiteLLM {resp.status_code}: {resp.text[:300]}")
    content = resp.json()["choices"][0].get("message", {}).get("content")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return (content or "").strip()


LABEL_SYSTEM = """Du liest Fotos einer Lebensmittelverpackung ab: Nährwerttabelle und/oder Vorderseite.
Antworte ausschließlich mit JSON, ohne Text davor oder danach:
{"name": "...", "brand": "...", "kcal": 0, "kj": 0, "protein": 0, "fat": 0, "satfat": 0, "carbs": 0,
 "sugar": 0, "fiber": 0, "salt": 0, "alcohol_vol": 0, "serving_g": 0, "note": "..."}

- Nährwerte immer aus der Spalte je 100 g bzw. 100 ml, nie je Portion. Gibt es nur Werte je Portion,
  rechne auf 100 g um, wenn die Portionsgröße angegeben ist, und schreib das in note.
- kcal und kj so, wie sie dastehen (eines darf null sein). Komma als Dezimaltrenner beachten ("3,5" = 3.5).
- satfat = "davon gesättigte Fettsäuren", sugar = "davon Zucker", fiber = "Ballaststoffe".
- "< 0,5 g" oder "Spuren": den Zahlenwert ohne Zeichen (0.5) bzw. 0.
- alcohol_vol: Alkohol in % vol, nur bei Getränken mit Angabe.
- serving_g: Portionsgröße in g oder ml, wenn angegeben ("1 Riegel = 40 g" → 40).
- name: Produktbezeichnung auf Deutsch, kurz, ohne Marke (z. B. "Proteinriegel Schoko-Erdnuss"); brand: Marke.
- Was nicht lesbar oder nicht abgebildet ist: null. Nichts erfinden, nichts schätzen.
- note: kurzer deutscher Hinweis nur bei Unsicherheit (unscharf, abgeschnitten, nur je Portion), sonst null."""

LABEL_LIMITS = {"kcal": 900, "protein": 100, "fat": 100, "satfat": 100, "carbs": 100, "sugar": 100,
                "fiber": 100, "salt": 100}


def _num(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    m = re.search(r"\d+(?:[.,]\d+)?", str(v))      # "< 0,5 g", "ca. 12" → Zahl
    return float(m.group(0).replace(",", ".")) if m else None


def clean_label(raw: dict) -> dict:
    """KI-Antwort prüfen: Zahlen in Grenzen, kJ → kcal, Alkohol % vol → g, Plausibilität."""
    out = {"name": str(raw.get("name") or "").strip()[:120] or None,
           "brand": str(raw.get("brand") or "").strip()[:80] or None}
    for k, limit in LABEL_LIMITS.items():
        v = _num(raw.get(k))
        out[k] = round(v, 2) if v is not None and 0 <= v <= limit else None
    kj = _num(raw.get("kj"))
    if out["kcal"] is None and kj and 0 < kj <= 3800:
        out["kcal"] = round(kj / 4.184, 1)
    vol = _num(raw.get("alcohol_vol"))
    out["alcohol"] = round(vol * 0.789, 2) if vol and 0 < vol <= 80 else None
    s = _num(raw.get("serving_g"))
    out["serving_g"] = s if s and 0 < s <= 5000 else None
    for part, whole in (("satfat", "fat"), ("sugar", "carbs")):
        if out[part] is not None and out[whole] is not None and out[part] > out[whole] + 0.1:
            out[part] = None                       # „davon“ größer als das Ganze: verlesen
    warn = []
    note = str(raw.get("note") or "").strip()
    if note and note.lower() not in ("null", "none"):
        warn.append(note[:200])
    if out["kcal"] is not None and None not in (out["protein"], out["fat"], out["carbs"]):
        calc = 4 * out["protein"] + 4 * out["carbs"] + 9 * out["fat"] + 2 * (out["fiber"] or 0) + 7 * (out["alcohol"] or 0)
        if abs(calc - out["kcal"]) > max(25, 0.2 * out["kcal"]):
            warn.append(f"kcal passen nicht zu Eiweiß, Fett und Kohlenhydraten (ergibt etwa {round(calc)} kcal) – bitte prüfen.")
    out["found"] = sum(out[k] is not None for k in LABEL_LIMITS)
    out["warnings"] = warn
    return out


async def read_label(images: list) -> dict:
    content = [{"type": "text", "text": "Lies die Angaben von diesen Fotos ab."}]
    content += [{"type": "image_url", "image_url": {"url": url}} for url in images]
    return clean_label(extract_json(await _complete(LABEL_SYSTEM, content, max_tokens=600)))


def extract_json(text: str) -> dict:
    """Erstes JSON-Objekt aus der Antwort (auch wenn es in ```json … ``` steht)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("keine JSON-Antwort")
    return json.loads(m.group(0))


def match_items(conn, parsed: dict) -> dict:
    """Vorschläge aus der eigenen Datenbank zu den Begriffen der KI."""
    out = []
    for it in list(parsed.get("items") or [])[:15]:
        if not isinstance(it, dict):
            continue
        search = str(it.get("search") or it.get("label") or "").strip()[:80]
        try:
            grams = max(1.0, min(float(it.get("grams") or 100), 3000.0))
        except (TypeError, ValueError):
            grams = 100.0
        hits = foods.search(conn, search, 5) if search else []
        out.append({"label": str(it.get("label") or search)[:80], "search": search, "grams": round(grams),
                    "candidates": hits})
    meal = parsed.get("meal") if parsed.get("meal") in diary.MEALS else None
    return {"meal": meal, "items": out}


async def parse_meal(conn_factory, text: str) -> dict:
    parsed = extract_json(await _complete(PARSE_SYSTEM, text))
    with conn_factory() as conn:
        return match_items(conn, parsed)
