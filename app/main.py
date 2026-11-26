"""FitPath – persönliche Abnehm-App (FastAPI)."""

import asyncio
import html
import json
import os
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx2
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from . import __version__, adaptive, ai, auth, eatout, backup, body, db, diary, foods, ingest, meals, motivation, plan, points, push, recipe_import, review, swaps, training

STATIC = os.path.join(os.path.dirname(__file__), "static")
MAX_INGEST_BYTES = 12 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_LABEL_BYTES = 8_000_000
# Höchstens so viele Webhook-Bodys gleichzeitig im Speicher (mem_limit 192m)
INGEST_SLOTS = asyncio.Semaphore(2)


@asynccontextmanager
async def lifespan(app):
    db.init()
    with db.connect() as conn:
        foods.ensure_seed(conn)
        eatout.sync(conn)
    push.ensure_vapid()
    tasks = [asyncio.create_task(push.loop()), asyncio.create_task(backup.loop())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       # wasm-unsafe-eval: nur WebAssembly übersetzen (Barcode-Erkennung), kein eval() für JavaScript
       "script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; manifest-src 'self'; worker-src 'self'; media-src 'self' blob:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


@app.middleware("http")
async def headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    # Kamera nur für den Barcode-Scanner auf der eigenen Seite
    resp.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------- Statische Dateien (ohne Anmeldung: enthalten keine Daten) ----------

def _static(name: str, media: str | None = None, cache: str = "no-cache"):
    return FileResponse(os.path.join(STATIC, name), media_type=media, headers={"Cache-Control": cache})


@app.get("/")
def index():
    return _static("index.html", "text/html")


@app.get("/app.js")
def app_js():
    return _static("app.js", "text/javascript")


@app.get("/styles.css")
def styles():
    return _static("styles.css", "text/css")


@app.get("/sw.js")
def sw():
    return _static("sw.js", "text/javascript")


@app.get("/icons.svg")
def icons_svg():
    # Linien-Icons für den Stil „Sachlich“ (tools/icons.py); no-cache, damit neue Icons sofort ankommen
    return _static("icons.svg", "image/svg+xml")


@app.get("/manifest.webmanifest")
def manifest():
    return _static("manifest.webmanifest", "application/manifest+json")


# Barcode-Erkennung für Safari/iPhone und Schrift (siehe static/vendor/LICENSE.txt). Feste Liste, Version im Namen,
# deshalb darf der Browser die Dateien ein Jahr behalten.
VENDOR = {"barcode-detector-3.2.3.js": "text/javascript", "zxing_reader-3.1.6.wasm": "application/wasm",
          "inter-latin-wght-5.1.0.woff2": "font/woff2"}         # Schrift für den Stil „Sachlich“


@app.get("/vendor/{name}")
def vendor(name: str):
    if name not in VENDOR:
        raise HTTPException(404)
    return _static(f"vendor/{name}", VENDOR[name], "public, max-age=31536000, immutable")


@app.get("/icons/{name}")
def icons(name: str):
    if not re.fullmatch(r"[a-z0-9-]+\.(png|svg)", name):
        raise HTTPException(404)
    path = os.path.join(STATIC, "icons", name)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})


@app.get("/healthz")
def healthz():
    # ohne Version: ohne Anmeldung erreichbar, die Version sehen angemeldete Geräte in /api/state
    return {"ok": True}


CONFIRM_PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>FitPath verbinden</title>
<style>body{{margin:0;min-height:100dvh;display:flex;align-items:center;justify-content:center;background:#0f1115;color:#eef1f6;
font:16px/1.45 system-ui,sans-serif;padding:16px;box-sizing:border-box}}main{{max-width:380px;width:100%;text-align:center;
background:#1a1e28;border:1px solid #2c3243;border-radius:20px;padding:28px 20px}}img{{border-radius:18px}}
p{{color:#98a1b3}}button{{width:100%;min-height:52px;border:0;border-radius:14px;background:#ff8a3d;color:#2a1300;
font:inherit;font-weight:700;font-size:1.1rem;cursor:pointer;margin-top:12px}}</style></head>
<body><main><img src="/icons/icon-192.png" width="72" height="72" alt=""><h1>FitPath verbinden</h1>
<p>Dieses Gerät{name} mit FitPath verbinden? Der Link gilt nur einmal.</p>
<form method="post" action="/auth/{token}"><button type="submit">Verbinden</button></form></main></body></html>"""


@app.get("/auth/{token}")
def auth_link(token: str):
    """Nur Bestätigungsseite. Link-Vorschauen von Messengern und Browsern rufen den Link
    per GET ab; würde schon das den Link einlösen, wäre er für das Handy verbraucht."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", token):
        return RedirectResponse("/?login=ungueltig", status_code=303)
    with db.connect() as conn:
        name = auth.peek(conn, token)
    if name is None:
        return RedirectResponse("/?login=ungueltig", status_code=303)
    label = f" ({html.escape(name)})" if name else ""
    return HTMLResponse(CONFIRM_PAGE.format(name=label, token=token),
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@app.post("/auth/{token}")
def auth_confirm(token: str, request: Request):
    with db.connect() as conn:
        session = auth.redeem(conn, token, request.headers.get("user-agent", ""))
    if not session:
        return RedirectResponse("/?login=ungueltig", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    _set_session(resp, session)
    return resp


# ---------- Hilfen ----------

async def _read_body(request: Request, limit: int) -> bytes:
    """Body mit hartem Limit lesen. Content-Length allein reicht nicht (chunked hat keinen)."""
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) > limit:
                raise HTTPException(413, "zu groß")
        except ValueError:
            raise HTTPException(400, "Content-Length ungültig")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(413, "zu groß")
    return bytes(body)


async def _json(request: Request, limit: int = MAX_JSON_BYTES, allow_list: bool = False):
    """JSON-Body als Objekt (oder Liste, wenn erlaubt), sonst 400 statt 500."""
    try:
        data = json.loads(await _read_body(request, limit))
    except ValueError:
        raise HTTPException(400, "kein gültiges JSON")
    if isinstance(data, dict) or (allow_list and isinstance(data, list)):
        return data
    raise HTTPException(400, "JSON-Objekt erwartet")


def _clean_text(v, n=120):
    return str(v or "").strip()[:n]


def _clean_time(v):
    if not isinstance(v, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ValueError("Uhrzeit HH:MM erwartet")
    return v


def _day(v) -> str:
    try:
        return db.parse_day(str(v)).isoformat()
    except ValueError:
        raise HTTPException(400, "Datum JJJJ-MM-TT erwartet")


def _range(lo, hi, cast=float):
    def check(v):
        v = cast(v)
        if not lo <= v <= hi:
            raise ValueError
        return v
    return check


VALIDATORS = {
    "sex": lambda v: "w" if v == "w" else "m",
    "birth_year": _range(1920, 2010, int),
    "height_cm": _range(120, 230),
    "start_weight": _range(35, 350),
    "goal_weight": _range(35, 350),
    "activity": lambda v: min(points.ACTIVITY_LEVELS, key=lambda k: abs(k - float(v))),
    "mode": lambda v: "keep" if v == "keep" else "lose",
    "pace": _range(0.1, 1.0),
    "tdee_adjust": lambda v: max(-500, min(500, int(round(float(v) / 50)) * 50)),
    "display": lambda v: "kcal" if v == "kcal" else "points",
    "steps_baseline": _range(0, 20000, int),
    "steps_goal": _range(1000, 40000, int),
    "push_enabled": bool,
    "quiet_start": _clean_time,
    "quiet_end": _clean_time,
    "push_max_per_day": _range(0, 10, int),
    "weigh_time": _clean_time,
    "weigh_days": lambda v: sorted({int(x) for x in list(v) if 0 <= int(x) <= 6}),
    "lunch_reminder": lambda v: _clean_time(v) if v else "",
    "evening_time": lambda v: _clean_time(v) if v else "",
    "snack_push": bool,
    "craving_triggers": lambda v: [t for t in dict.fromkeys(_clean_text(x, 40) for x in list(v)[:20]) if t],
    "review_seen": lambda v: db.parse_day(str(v)).isoformat(),      # Wochenrückblick: Montag der gesehenen Woche
    "plans": lambda v: {_clean_text(k, 40): _clean_text(t, 200) for k, t in list(dict(v).items())[:20]
                        if _clean_text(k, 40) and _clean_text(t, 200)},
}


def _save_plan(conn, key: str, value) -> None:
    """Refeed-Tage und Pausen (plan.py): brauchen das heutige Datum und die bisherigen Werte."""
    s, today = db.get_settings(conn), db.parse_day(db.today())
    if key == "pauses":
        db.set_setting(conn, "pauses", plan.clean_pauses(value, today))
    elif key == "refeed_days":
        days = plan.clean_days(value)
        db.set_setting(conn, "refeed_plan", plan.set_refeed(s, days, today))
        # ein Tausch für diese oder nächste Woche passt nicht mehr zu den neuen Tagen
        db.set_setting(conn, "refeed_weeks", {k: v for k, v in (s.get("refeed_weeks") or {}).items()
                                              if k < plan.monday(today).isoformat()})
    elif key == "refeed_week":
        v = dict(value)
        days = None if v.get("days") is None else plan.clean_days(v["days"])
        db.set_setting(conn, "refeed_weeks", plan.set_week(s, db.parse_day(v["week"]), days, today))


PLAN_KEYS = ("pauses", "refeed_days", "refeed_week")


def _save_settings(conn, data: dict) -> None:
    if not isinstance(data, dict):
        raise HTTPException(400, "Einstellungen als Objekt erwartet")
    for key, value in data.items():
        if key not in VALIDATORS and key not in PLAN_KEYS:
            continue
        try:
            if key in PLAN_KEYS:
                _save_plan(conn, key, value)
            else:
                db.set_setting(conn, key, VALIDATORS[key](value))
        except (TypeError, ValueError, KeyError):
            raise HTTPException(400, f"ungültiger Wert für {key}")


def _state(conn, day: str | None = None) -> dict:
    s = db.get_settings(conn)
    day = day or db.today()
    return {
        "settings": db.public_settings(s),
        "today": db.today(),
        "overview": (ov := diary.overview(conn, s, day)),
        "plan": plan.info(s, ov["budget"], db.parse_day(db.today())),
        "week_review": review.teaser(conn, s),
        "motivation": motivation.state(conn, s),
        "body": body.summary(conn, s),
        "recent": foods.recent(conn, 12),
        "templates": (tpl := meals.list_all(conn)),
        "fits": meals.fit_candidates(conn, tpl),
        "vapid_key": push.public_key(),
        "activity_levels": points.ACTIVITY_LEVELS,
        "training": training.catalog(),
        "ai": ai.available(),
        "version": __version__,
        "server_time": db.iso(db.now_utc()),
    }


# ---------- Zustand und Einstellungen ----------

@app.get("/api/state")
def get_state(day: str | None = None, device=Depends(auth.require)):
    with db.connect() as conn:
        state = _state(conn, _day(day) if day else None)
    state["device"] = {"id": device["id"], "name": device["name"]}
    return state


@app.put("/api/settings")
async def put_settings(request: Request, device=Depends(auth.require)):
    data = await _json(request)
    with db.connect() as conn:
        _save_settings(conn, data)
        return _state(conn)


@app.post("/api/onboarding")
async def onboarding(request: Request, device=Depends(auth.require)):
    data = await _json(request)
    with db.connect() as conn:
        _save_settings(conn, data.get("settings", {}))
        s = db.get_settings(conn)
        if not s.get("start_date"):
            db.set_setting(conn, "start_date", db.today())
        # Startgewicht als ersten Wiegewert eintragen, wenn es heute noch keinen gibt
        today = db.today()
        if not conn.execute("SELECT 1 FROM body WHERE kind = 'weight' AND day = ?", (today,)).fetchone():
            conn.execute("INSERT INTO body (ts, day, kind, value, source) VALUES (?, ?, 'weight', ?, 'manual')",
                         (db.iso(db.now_utc()), today, float(s["start_weight"])))
        db.set_setting(conn, "onboarded", True)
        return _state(conn)


@app.post("/api/budget/preview")
async def budget_preview(request: Request, device=Depends(auth.require)):
    """Budget für Onboarding und Ziele berechnen, ohne zu speichern."""
    data = await _json(request)
    with db.connect() as conn:
        s = db.get_settings(conn)
    for key, value in (data or {}).items():
        if key in VALIDATORS:
            try:
                s[key] = VALIDATORS[key](value)
            except (TypeError, ValueError):
                raise HTTPException(400, f"ungültiger Wert für {key}")
    kt = points.kcal_target(s, float(s["start_weight"]))
    return {**kt, "points": points.points_budget(kt["target"])}


# ---------- Lebensmittel ----------

@app.get("/api/foods/search")
def food_search(q: str = "", device=Depends(auth.require)):
    with db.connect() as conn:
        return foods.search(conn, q[:80])


@app.get("/api/foods/lists")
def food_lists(device=Depends(auth.require)):
    with db.connect() as conn:
        return {"recent": foods.recent(conn, 30), "by_meal": {m: foods.recent(conn, 30, m) for m in diary.MEALS},
                "favorites": foods.favorites(conn), "custom": foods.custom(conn),
                "eatout": eatout.plates(conn)}


@app.get("/api/foods/barcode/{code}")
def food_barcode(code: str, device=Depends(auth.require)):
    with db.connect() as conn:
        return foods.barcode(conn, code)


@app.get("/api/foods/{food_id}")
def food_get(food_id: int, device=Depends(auth.require)):
    with db.connect() as conn:
        f = foods.get(conn, food_id)
        if f and f["source"] == "eatout":
            f["eatout"] = eatout.recipe_of(conn, food_id)      # Zusammensetzung für die Anzeige
    if not f:
        raise HTTPException(404, "unbekannt")
    return f


@app.post("/api/foods")
async def food_create(request: Request, device=Depends(auth.require)):
    data = await _json(request)
    with db.connect() as conn:
        try:
            fid = foods.create_custom(conn, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return foods.get(conn, fid)


@app.put("/api/foods/{food_id}")
async def food_update(food_id: int, request: Request, device=Depends(auth.require)):
    data = await _json(request)
    with db.connect() as conn:
        try:
            foods.update_food(conn, food_id, data)
        except LookupError:
            raise HTTPException(404, "unbekannt")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return foods.get(conn, food_id)


@app.get("/api/recipes/{food_id}")
def recipe_get(food_id: int, device=Depends(auth.require)):
    with db.connect() as conn:
        r = foods.get_recipe(conn, food_id)
    if not r:
        raise HTTPException(404, "unbekannt")
    return r


@app.post("/api/recipes")
async def recipe_create(request: Request, device=Depends(auth.require)):
    data = await _json(request)
    with db.connect() as conn:
        try:
            fid = foods.save_recipe(conn, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return foods.get_recipe(conn, fid)


@app.post("/api/recipes/import")
async def recipe_import_link(request: Request, device=Depends(auth.require)):
    """Rezept-Link → Vorschlag (Zutaten mit Treffern). Gespeichert wird erst über POST /api/recipes."""
    data = await _json(request)
    url = _clean_text(data.get("url"), 500)
    m = re.search(r"https?://\S+", url)
    if not m:
        raise HTTPException(400, "Bitte einen Rezept-Link einfügen")
    url = m.group(0)
    try:
        page_url, page = await asyncio.to_thread(recipe_import.fetch, url)
        parsed = recipe_import.parse_recipe(page)
    except recipe_import.ImportError_ as exc:
        raise HTTPException(400, str(exc))
    except httpx2.HTTPError:
        raise HTTPException(502, "Seite nicht erreichbar")
    terms = None
    if ai.available():
        try:
            terms = await ai.parse_ingredients(parsed["ingredients"])
        except Exception as exc:   # ohne KI geht es mit der eigenen Erkennung weiter
            print(f"KI-Zutaten: {exc}", flush=True)
    with db.connect() as conn:
        return recipe_import.from_parsed(conn, page_url, parsed, terms)


@app.put("/api/recipes/{food_id}")
async def recipe_update(food_id: int, request: Request, device=Depends(auth.require)):
    data = await _json(request)
    with db.connect() as conn:
        try:
            foods.save_recipe(conn, data, food_id)
        except LookupError:
            raise HTTPException(404, "unbekannt")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return foods.get_recipe(conn, food_id)


@app.post("/api/ai/parse")
async def ai_parse(request: Request, device=Depends(auth.require)):
    """Freitext → Vorschläge aus der eigenen Datenbank. Erfasst wird erst nach Bestätigung."""
    if not ai.available():
        raise HTTPException(503, "KI nicht eingerichtet (LiteLLM-Key fehlt)")
    data = await _json(request)
    text = _clean_text(data.get("text"), 500)
    if len(text) < 3:
        raise HTTPException(400, "Bitte beschreiben, was du gegessen hast")
    try:
        return await ai.parse_meal(db.connect, text)
    except (ValueError, KeyError) as exc:
        print(f"KI-Antwort nicht lesbar: {exc}", flush=True)
        raise HTTPException(502, "KI-Antwort nicht verstanden – bitte anders formulieren")
    except Exception as exc:
        print(f"KI-Fehler: {exc}", flush=True)
        raise HTTPException(502, "KI nicht erreichbar")


LABEL_IMAGE = re.compile(r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$")


@app.post("/api/ai/label")
async def ai_label(request: Request, device=Depends(auth.require)):
    """Foto(s) einer Packung → Nährwerte je 100 g zum Vorausfüllen. Fotos werden nicht gespeichert."""
    if not ai.available():
        raise HTTPException(503, "KI nicht eingerichtet")
    data = await _json(request, MAX_LABEL_BYTES)
    images = [str(i) for i in list(data.get("images") or [])[:2]]
    if not images or not all(len(i) <= 3_500_000 and LABEL_IMAGE.match(i) for i in images):
        raise HTTPException(400, "Foto fehlt oder ungültig")
    try:
        return await ai.read_label(images)
    except (ValueError, KeyError) as exc:
        print(f"KI-Antwort (Foto) nicht lesbar: {exc}", flush=True)
        raise HTTPException(502, "KI konnte das Foto nicht auswerten – schärfer oder näher fotografieren")
    except Exception as exc:
        print(f"KI-Fehler (Foto): {exc}", flush=True)
        raise HTTPException(502, "KI nicht erreichbar oder versteht keine Bilder")


@app.delete("/api/foods/{food_id}")
def food_delete(food_id: int, device=Depends(auth.require)):
    with db.connect() as conn:
        return {"result": foods.delete_food(conn, food_id)}


# ---------- Tagebuch ----------

def _clean_entry(conn, data: dict) -> dict:
    if not isinstance(data, dict):
        raise HTTPException(400, "Eintrag als Objekt erwartet")
    meal = data.get("meal") if data.get("meal") in diary.MEALS else "snack"
    try:
        grams = float(data.get("grams"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Menge fehlt")
    if not 0 < grams <= 5000:
        raise HTTPException(400, "Menge 1–5000 g")
    ts = db.now_utc()
    if data.get("ts"):
        try:
            ts = db.parse(str(data["ts"]))
        except ValueError:
            raise HTTPException(400, "Zeit ungültig")
    day = _day(data["day"]) if data.get("day") else db.local_day(ts)
    try:
        food = foods.get(conn, int(data["food_id"])) if data.get("food_id") else None
    except (TypeError, ValueError):
        raise HTTPException(400, "Lebensmittel unbekannt")
    if not food:
        raise HTTPException(400, "Lebensmittel unbekannt")
    return {
        "id": _clean_text(data.get("id"), 40) or str(uuid.uuid4()),
        "ts": db.iso(ts), "day": day, "meal": meal, "food_id": food["id"],
        "name": food["name"] + (f" ({food['brand']})" if food.get("brand") else ""),
        "grams": round(grams, 1), "portion": _clean_text(data.get("portion"), 40) or None,
        "zero": 1 if food["zero"] else 0, **points.scale(food, grams),
        "points_raw": round(food["pts_100"] * grams / 100, 4) if food.get("pts_100") is not None else None,
    }


def _upsert_entry(conn, e: dict) -> None:
    conn.execute(
        "INSERT INTO food_log (id, ts, day, meal, food_id, name, grams, portion, kcal, protein, fat, satfat, carbs, sugar, "
        "fiber, alcohol, salt, zero, points_raw, created) VALUES (:id, :ts, :day, :meal, :food_id, :name, :grams, :portion, "
        ":kcal, :protein, :fat, :satfat, :carbs, :sugar, :fiber, :alcohol, :salt, :zero, :points_raw, :created) "
        "ON CONFLICT(id) DO UPDATE SET day = excluded.day, meal = excluded.meal, grams = excluded.grams, "
        "portion = excluded.portion, kcal = excluded.kcal, protein = excluded.protein, fat = excluded.fat, "
        "satfat = excluded.satfat, carbs = excluded.carbs, sugar = excluded.sugar, fiber = excluded.fiber, "
        "alcohol = excluded.alcohol, salt = excluded.salt, zero = excluded.zero, points_raw = excluded.points_raw",
        {"points_raw": None, **e, "created": db.iso(db.now_utc())})


@app.post("/api/log")
async def log_add(request: Request, device=Depends(auth.require)):
    """Ein Eintrag oder eine Liste (Offline-Warteschlange). Gleiche id = ändern."""
    data = await _json(request, allow_list=True)
    items = data if isinstance(data, list) else [data]
    day = None
    with db.connect() as conn:
        for item in items[:200]:
            e = _clean_entry(conn, item)
            _upsert_entry(conn, e)
            day = e["day"]
        return _state(conn, day if not isinstance(data, list) else None)


@app.get("/api/log")
def log_day(day: str, device=Depends(auth.require)):
    """Einträge eines Tages, zum Übernehmen in einen anderen Tag."""
    day = _day(day)
    with db.connect() as conn:
        return {"day": day, "entries": diary.entries(conn, day)}


@app.post("/api/log/copy")
async def log_copy(request: Request, device=Depends(auth.require)):
    """Mahlzeit eines Tages (oder den ganzen Tag) auf einen anderen Tag kopieren.
    to_meal: Einträge der Mahlzeit in eine andere Mahlzeit übernehmen (Reste vom Abend zum Mittag)."""
    data = await _json(request)
    src, dst = _day(data.get("from")), _day(data.get("to"))
    if dst > db.today():
        raise HTTPException(400, "Tage in der Zukunft gehen noch nicht")
    meal = data.get("meal") if data.get("meal") in diary.MEALS else None
    to_meal = data.get("to_meal") if meal and data.get("to_meal") in diary.MEALS else None
    ids = data.get("ids")   # optional: nur diese Einträge übernehmen
    ids = {str(i) for i in ids} if isinstance(ids, list) else None
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM food_log WHERE day = ?" + (" AND meal = ?" if meal else ""),
                            (src, meal) if meal else (src,)).fetchall()
        for r in rows:
            if ids is not None and r["id"] not in ids:
                continue
            e = dict(r)
            e.update(id=str(uuid.uuid4()), day=dst, ts=db.iso(db.now_utc()), meal=to_meal or e["meal"])
            _upsert_entry(conn, e)
        return _state(conn, dst)


# ---------- Gespeicherte Mahlzeiten ----------

@app.post("/api/templates")
async def template_add(request: Request, device=Depends(auth.require)):
    """Neue Mahlzeit merken; gleicher Name ersetzt die vorhandene."""
    data = await _json(request)
    with db.connect() as conn:
        try:
            meals.save(conn, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return _state(conn)


@app.put("/api/templates/{tid}")
async def template_put(tid: str, request: Request, device=Depends(auth.require)):
    data = await _json(request)
    with db.connect() as conn:
        try:
            meals.save(conn, data, tid)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        return _state(conn)


@app.delete("/api/templates/{tid}")
def template_delete(tid: str, device=Depends(auth.require)):
    with db.connect() as conn:
        if not meals.delete(conn, tid):
            raise HTTPException(404, "Mahlzeit nicht gefunden")
        return _state(conn)


@app.post("/api/templates/{tid}/log")
async def template_log(tid: str, request: Request, device=Depends(auth.require)):
    """Mahlzeit als Einträge erfassen (Nährwerte frisch aus der Datenbank). skip: Positionen, die diesmal fehlen."""
    data = await _json(request)
    day = _day(data.get("day") or db.today())
    meal = data.get("meal") if data.get("meal") in diary.MEALS else "snack"
    with db.connect() as conn:
        try:
            items = meals.items_for_log(conn, tid, data.get("skip") or [])
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        if not items:
            raise HTTPException(400, "Nichts ausgewählt")
        added = []
        for it in items:
            e = _clean_entry(conn, {**it, "meal": meal, "day": day})
            _upsert_entry(conn, e)
            added.append(e["id"])
        return {**_state(conn, day), "added": added}


@app.delete("/api/log/{eid}")
def log_delete(eid: str, device=Depends(auth.require)):
    with db.connect() as conn:
        row = conn.execute("SELECT day FROM food_log WHERE id = ?", (eid,)).fetchone()
        conn.execute("DELETE FROM food_log WHERE id = ?", (eid,))
        return _state(conn, row["day"] if row else None)


# ---------- Körper und Aktivität ----------

@app.post("/api/body")
async def body_add(request: Request, device=Depends(auth.require)):
    data = await _json(request)
    kind = data.get("kind") if data.get("kind") in ("weight", "fat", "waist") else None
    if not kind:
        raise HTTPException(400, "kind ungültig")
    limits = {"weight": (30, 400), "fat": (1, 75), "waist": (40, 250)}[kind]
    try:
        value = float(str(data.get("value")).replace(",", "."))
    except (TypeError, ValueError):
        raise HTTPException(400, "Wert fehlt")
    if not limits[0] <= value <= limits[1]:
        raise HTTPException(400, f"Wert {limits[0]}–{limits[1]} erwartet")
    ts = db.now_utc()
    if data.get("day"):
        day = _day(data["day"])
        if day != db.today():
            ts = db.parse(f"{day}T08:00:00")
    with db.connect() as conn:
        conn.execute("INSERT INTO body (ts, day, kind, value, source) VALUES (?, ?, ?, ?, 'manual')",
                     (db.iso(ts), db.local_day(ts), kind, round(value, 2)))
        return _state(conn)


@app.get("/api/body")
def body_list(days: int = 90, device=Depends(auth.require)):
    with db.connect() as conn:
        since = (db.parse_day(db.today()) - timedelta(days=max(1, min(days, 3650)))).isoformat()
        rows = [dict(r) for r in conn.execute(
            "SELECT id, ts, day, kind, value, source FROM body WHERE day >= ? ORDER BY ts DESC LIMIT 1000", (since,))]
        series = [w for w in body.trend_series(body.daily_weights(conn)) if w["day"] >= since]
    return {"entries": rows, "series": series}


@app.delete("/api/body/{bid}")
def body_delete(bid: int, device=Depends(auth.require)):
    with db.connect() as conn:
        conn.execute("DELETE FROM body WHERE id = ?", (bid,))
        return _state(conn)


@app.post("/api/activity")
async def activity_add(request: Request, device=Depends(auth.require)):
    """Schritte von Hand (wenn Health Connect fehlt)."""
    data = await _json(request)
    day = _day(data.get("day") or db.today())
    try:
        steps = int(data.get("steps"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Schritte fehlen")
    if not 0 <= steps <= 200_000:
        raise HTTPException(400, "Schritte 0–200000")
    with db.connect() as conn:
        conn.execute("INSERT INTO activity (day, source, steps, updated) VALUES (?, 'manual', ?, ?) "
                     "ON CONFLICT(day, source) DO UPDATE SET steps = excluded.steps, updated = excluded.updated",
                     (day, steps, db.iso(db.now_utc())))
        return _state(conn, day)


@app.post("/api/workouts")
async def workout_add(request: Request, device=Depends(auth.require)):
    """Training von Hand eintragen."""
    data = await _json(request)
    day = _day(data.get("day") or db.today())
    with db.connect() as conn:
        try:
            training.add_manual(conn, data, day)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Schon gespeichert") from None
        return _state(conn, day)


@app.put("/api/workouts/{wid}")
async def workout_put(wid: str, request: Request, device=Depends(auth.require)):
    """Sportart, Intensität und (nur bei Hand-Einträgen) Dauer ändern."""
    data = await _json(request)
    with db.connect() as conn:
        try:
            day = training.update(conn, wid, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        if day is None:
            raise HTTPException(404, "Training nicht gefunden")
        return _state(conn, day)


@app.delete("/api/workouts/{wid}")
def workout_delete(wid: str, device=Depends(auth.require)):
    with db.connect() as conn:
        day = training.delete(conn, wid)
        if day is None:
            raise HTTPException(404, "Training nicht gefunden")
        return _state(conn, day)


@app.get("/api/stats")
def stats(days: int = 30, device=Depends(auth.require)):
    with db.connect() as conn:
        s = db.get_settings(conn)
        d = diary.history(conn, s, max(7, min(days, 365)))
        d["cravings"] = motivation.craving_stats(conn, d["days"][0]["day"])
        d["adaptive"] = adaptive.estimate(conn, s)
        return d


@app.get("/api/review/week")
def review_week(start: str | None = None, device=Depends(auth.require)):
    """Wochenrückblick; ohne start die letzte abgeschlossene Woche. Die laufende Woche geht auch (Zwischenstand)."""
    today = db.parse_day(db.today())
    first = db.parse_day(_day(start)) if start else review.last_monday(today)
    if first > today:
        raise HTTPException(400, "Woche liegt in der Zukunft")
    with db.connect() as conn:
        return review.week(conn, db.get_settings(conn), first)


# ---------- Motivation: Heißhunger und Challenge ----------

def _clean_event(data: dict) -> dict:
    if data.get("kind") != "craving":
        raise HTTPException(400, "kind ungültig")
    ts = db.now_utc()
    if data.get("ts"):
        try:
            ts = db.parse(str(data["ts"]))
        except ValueError:
            raise HTTPException(400, "Zeit ungültig")
    def num(k, lo, hi):
        v = data.get(k)
        if v in (None, ""):
            return None
        try:
            return max(lo, min(int(v), hi))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{k} ungültig")
    return {"id": _clean_text(data.get("id"), 40) or str(uuid.uuid4()), "ts": db.iso(ts), "kind": "craving",
            "trigger": _clean_text(data.get("trigger"), 40) or None, "intensity": num("intensity", 1, 10),
            "resisted": None if data.get("resisted") is None else (1 if data["resisted"] else 0),
            "duration_s": num("duration_s", 0, 86400), "created": db.iso(db.now_utc()),
            "food": data["food"] if isinstance(data.get("food"), str) and data["food"] in swaps.KEYS else None,
            "swap": _clean_text(data.get("swap"), 40) or None}


@app.post("/api/events")
async def event_add(request: Request, device=Depends(auth.require)):
    """Heißhunger (SOS). Gleiche id = ändern."""
    e = _clean_event(await _json(request))
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO events (id, ts, kind, trigger, intensity, resisted, duration_s, created, food, swap) VALUES "
            "(:id, :ts, :kind, :trigger, :intensity, :resisted, :duration_s, :created, :food, :swap) ON CONFLICT(id) "
            "DO UPDATE SET trigger = excluded.trigger, intensity = excluded.intensity, resisted = excluded.resisted, "
            "duration_s = excluded.duration_s, food = excluded.food, swap = excluded.swap", e)
        return _state(conn)


@app.get("/api/events")
def event_list(days: int = 30, device=Depends(auth.require)):
    with db.connect() as conn:
        since = db.iso(db.now_utc() - timedelta(days=max(1, min(days, 3650))))
        return [dict(r) for r in conn.execute("SELECT * FROM events WHERE ts >= ? ORDER BY ts DESC LIMIT 500", (since,))]


@app.delete("/api/events/{eid}")
def event_delete(eid: str, device=Depends(auth.require)):
    with db.connect() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (eid,))
        return _state(conn)


@app.get("/api/swaps")
def swap_catalog(device=Depends(auth.require)):
    """Lieber-Tausch je Gelüst mit Punkten, oft gewählte zuerst."""
    with db.connect() as conn:
        return swaps.catalog(conn)


@app.post("/api/challenge/skip")
def challenge_skip(device=Depends(auth.require)):
    with db.connect() as conn:
        motivation.skip_challenge(conn, db.get_settings(conn))
        return _state(conn)


# ---------- Health Connect (Life Dashboard Companion) ----------

@app.post("/api/ingest/health")
async def ingest_health(request: Request):
    """Webhook ohne Cookie: geprüft per HMAC-Signatur oder Bearer-Header."""
    # Vor dem Lesen bremsen: nach vielen Fehlversuchen und bei zu vielen parallelen Uploads
    if ingest.too_many_denied() or INGEST_SLOTS.locked():
        raise HTTPException(429, "zu viele Anfragen", headers={"Retry-After": "60"})
    async with INGEST_SLOTS:
        raw = await _read_body(request, MAX_INGEST_BYTES)
    with db.connect() as conn:
        secret = db.get_settings(conn).get("ingest_secret")
        reason = ingest.check(secret, raw, request.headers.get("x-signature"), request.headers.get("authorization"))
        if reason:
            ingest.log_denied(conn, reason, len(raw))
    if reason:
        # Grund nur im Protokoll (Mehr → Health Connect), nach außen nicht verraten, ob ein Geheimnis eingerichtet ist
        raise HTTPException(401, "nicht autorisiert")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "kein JSON")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Objekt erwartet")
    with db.connect() as conn:
        return ingest.apply(conn, payload, raw)


@app.get("/api/ingest/status")
def ingest_status(device=Depends(auth.require)):
    with db.connect() as conn:
        s = db.get_settings(conn)
        return {**ingest.status(conn), "configured": bool(s.get("ingest_secret")), "url": INGEST_URL}


INGEST_URL = f"{auth.PUBLIC_URL}/api/ingest/health"


@app.post("/api/ingest/secret")
def ingest_secret(device=Depends(auth.require)):
    """Neues Geheimnis erzeugen; das alte gilt ab sofort nicht mehr."""
    with db.connect() as conn:
        return ingest.pair_info(INGEST_URL, ingest.new_secret(conn))


@app.get("/api/ingest/pair")
def ingest_pair(device=Depends(auth.require)):
    """Koppel-Code (QR) für das vorhandene Geheimnis – nur für angemeldete Geräte."""
    with db.connect() as conn:
        secret = db.get_settings(conn).get("ingest_secret")
    if not secret:
        raise HTTPException(404, "noch kein Geheimnis")
    return ingest.pair_info(INGEST_URL, secret)


# ---------- Push ----------

@app.post("/api/push/subscribe")
async def push_subscribe(request: Request, device=Depends(auth.require)):
    data = await _json(request)
    endpoint = str(data.get("endpoint", ""))
    keys = data.get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(400, "Abo ungültig")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO push_subs (endpoint, p256dh, auth, device_id, created) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth, "
            "device_id = excluded.device_id",
            (endpoint, keys["p256dh"], keys["auth"], device["id"], db.iso(db.now_utc())))
    return {"ok": True}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request, device=Depends(auth.require)):
    data = await _json(request)
    with db.connect() as conn:
        conn.execute("DELETE FROM push_subs WHERE endpoint = ?", (str(data.get("endpoint", "")),))
    return {"ok": True}


@app.post("/api/push/test")
def push_test(device=Depends(auth.require)):
    with db.connect() as conn:
        n = push.send(conn, "FitPath", "Test-Benachrichtigung – funktioniert! 💪", "/")
    return {"sent": n}


# ---------- Geräte ----------

@app.get("/api/devices")
def devices(device=Depends(auth.require)):
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, created, last_seen FROM devices ORDER BY id")]
    for r in rows:
        r["current"] = r["id"] == device["id"]
    return rows


def _set_session(resp: Response, session: str) -> None:
    resp.set_cookie(auth.COOKIE, session, max_age=auth.COOKIE_DAYS * 86400, httponly=True,
                    secure=auth.COOKIE_SECURE, samesite="lax", path="/")


@app.post("/api/pair/start")
def pair_start(request: Request):
    """Ohne Anmeldung: neues Gerät fordert eine Kopplung an (Code und QR-Code)."""
    if request.headers.get("x-fitpath") != "1":
        raise HTTPException(403, "Header fehlt")
    with db.connect() as conn:
        r = auth.pair_start(conn, request.headers.get("user-agent", ""), auth.client_ip(request))
    if not r:
        raise HTTPException(429, "Gerade zu viele Anfragen – in einer Minute nochmal")
    import segno
    link = f"{auth.PUBLIC_URL}/#pair={r['code']}"
    return {**r, "link": link, "qr_svg": segno.make(link, error="m").svg_inline(scale=7, border=3, dark="#000", light="#fff")}


@app.post("/api/pair/poll")
async def pair_poll(request: Request, response: Response):
    if request.headers.get("x-fitpath") != "1":
        raise HTTPException(403, "Header fehlt")
    data = await _json(request)
    with db.connect() as conn:
        status, session = auth.pair_poll(conn, str(data.get("rid") or ""))
    if session:
        _set_session(response, session)
    return {"status": status}


@app.get("/api/pair/{code}")
def pair_info(code: str, request: Request, device=Depends(auth.require)):
    with db.connect() as conn:
        info = auth.pair_info(conn, code, auth.client_ip(request))
    if not info:
        raise HTTPException(404, "Code unbekannt oder abgelaufen")
    return info


@app.post("/api/pair/{code}")
async def pair_decide(code: str, request: Request, device=Depends(auth.require)):
    data = await _json(request)
    with db.connect() as conn:
        if not auth.pair_decide(conn, code, bool(data.get("approve")), _clean_text(data.get("name"), 40)):
            raise HTTPException(404, "Code unbekannt oder abgelaufen")
    return {"ok": True}


@app.post("/api/devices/link")
async def device_link(request: Request, device=Depends(auth.require)):
    data = await _json(request)
    with db.connect() as conn:
        return {"url": auth.create_link(conn, _clean_text(data.get("name"), 40)),
                "minutes": auth.LINK_MINUTES}


@app.put("/api/devices/{did}")
async def device_rename(did: int, request: Request, device=Depends(auth.require)):
    data = await _json(request)
    name = _clean_text(data.get("name"), 40)
    if not name:
        raise HTTPException(400, "Name fehlt")
    with db.connect() as conn:
        if not conn.execute("UPDATE devices SET name = ? WHERE id = ?", (name, did)).rowcount:
            raise HTTPException(404, "unbekannt")
    return {"ok": True}


@app.delete("/api/devices/{did}")
def device_delete(did: int, device=Depends(auth.require)):
    with db.connect() as conn:
        auth.remove_device(conn, did)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response, device=Depends(auth.require)):
    """Dieses Gerät abmelden: Session und Push-Abo löschen, Cookie entfernen."""
    with db.connect() as conn:
        auth.remove_device(conn, device["id"])
    response.delete_cookie(auth.COOKIE, path="/", secure=auth.COOKIE_SECURE, httponly=True, samesite="lax")
    return {"ok": True}


# ---------- Export ----------

@app.get("/api/export")
def export(device=Depends(auth.require)):
    with db.connect() as conn:
        data = {
            "exported": db.iso(db.now_utc()),
            "settings": db.public_settings(db.get_settings(conn)),
            "food_log": [dict(r) for r in conn.execute("SELECT * FROM food_log ORDER BY ts")],
            "body": [dict(r) for r in conn.execute("SELECT * FROM body ORDER BY ts")],
            "activity": [dict(r) for r in conn.execute("SELECT * FROM activity ORDER BY day")],
            "workouts": [dict(r) for r in conn.execute("SELECT * FROM workouts ORDER BY start")],
            "meal_templates": [dict(r) for r in conn.execute("SELECT * FROM meal_templates ORDER BY name")],
            "events": [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY ts")],
            "foods_own": [dict(r) for r in conn.execute(
                "SELECT * FROM foods WHERE source IN ('custom', 'off') OR fav = 1 OR zero_user IS NOT NULL "
                "OR portions IS NOT NULL ORDER BY id")],
        }
    return JSONResponse(data, headers={
        "Content-Disposition": f'attachment; filename="fitpath-{db.today()}.json"'})
