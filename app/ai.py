"""Erfassen per Text über einen OpenAI-kompatiblen KI-Endpunkt.

Ablauf: Die KI zerlegt eine freie Beschreibung („2 Brötchen mit Käse und Kaffee mit Milch“)
in Lebensmittel mit geschätzter Menge und einem Suchbegriff in der Sprache einer deutschen
Nährwerttabelle. FitPath sucht jeden Begriff in der eigenen Datenbank und schlägt die
besten Treffer vor. Erfasst wird erst, wenn der Nutzer bestätigt.

Datenschutz: An die KI geht nur der eingegebene Text, sonst nichts aus der App.
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


async def _complete(system: str, user: str, max_tokens: int = 700) -> str:
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
