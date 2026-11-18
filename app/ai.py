"""Erfassen per Text über LiteLLM.

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

LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000").rstrip("/")
LITELLM_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_FAST = os.environ.get("FITPATH_MODEL_FAST", "claude-haiku-5-5")
HEADERS = {"Authorization": f"Bearer {LITELLM_KEY}", "x-caveman-style": "off"}

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


def available() -> bool:
    return bool(LITELLM_KEY)


async def _complete(system: str, user: str, max_tokens: int = 700) -> str:
    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10)) as client:
        resp = await client.post(
            f"{LITELLM_URL}/v1/chat/completions", headers=HEADERS,
            # keine temperature: claude-sonnet-5-5 lehnt Werte ≠ 1 ab (Stolperstein aus QuitPath)
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
