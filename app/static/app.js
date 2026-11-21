/* FitPath – Oberfläche (ohne Framework) */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const view = $("#view");

/* Design je Gerät: system | light | dark (im Browser gespeichert, nicht auf dem Server) */
const THEME_COLOR = { dark: "#0f1115", light: "#f6f5f2" };
function applyTheme(t) {
  const root = document.documentElement;
  if (t === "light" || t === "dark") root.dataset.theme = t; else delete root.dataset.theme;
  // Statusleiste: bei fester Wahl beide Meta-Tags auf dieselbe Farbe, sonst je nach System
  $$('meta[name="theme-color"]').forEach(m => {
    m.content = THEME_COLOR[t] || (m.media.includes("dark") ? THEME_COLOR.dark : THEME_COLOR.light);
  });
}
function savedTheme() { try { return localStorage.getItem("fp_theme") || "system"; } catch (_) { return "system"; } }
applyTheme(savedTheme());

let S = null;              // Zustand vom Server
let curDay = null;         // angezeigter Tag (null = heute)
let statsRange = 30;
let weightRange = 90;
let sheetCleanup = null;   // z. B. Kamera stoppen

const MEALS = [["fruehstueck", "Frühstück", "🌅"], ["mittag", "Mittag", "🍽️"], ["abend", "Abend", "🌙"], ["snack", "Snacks", "🍎"]];
const MEAL_LABEL = Object.fromEntries(MEALS.map(([k, l]) => [k, l]));
const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const AMPEL_LABEL = { green: "leicht (< 1 kcal/g)", yellow: "mittel (1–2,4 kcal/g)", red: "energiedicht (> 2,4 kcal/g)" };

/* ---------- Helfer ---------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const num = new Intl.NumberFormat("de-DE");
const num1 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });
const numIn = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1, useGrouping: false });  // für Eingabefelder
const pad = n => String(n).padStart(2, "0");
const isPoints = () => S.settings.display !== "kcal";
const unit = () => (isPoints() ? "P" : "kcal");
function fmtVal(points, kcal) { return isPoints() ? `${num.format(points)} P` : `${num.format(Math.round(kcal))} kcal`; }
function fmtG(g) { return `${num1.format(g)} g`; }
function fmtSigned(v) { return v > 0 ? `+${num1.format(v)}` : v < 0 ? `−${num1.format(-v)}` : num1.format(0); }
function fmtDay(iso, opts = { weekday: "short", day: "2-digit", month: "2-digit" }) {
  return new Date(iso + "T12:00:00").toLocaleDateString("de-DE", opts);
}
function fmtAgo(iso) {
  if (!iso) return "–";
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 2) return "gerade eben";
  if (min < 60) return `vor ${min} Min`;
  if (min < 1440) return `vor ${Math.round(min / 60)} Std`;
  return new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
}
function addDays(iso, n) { const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function uuid() { return crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(16).slice(2); }
function vibrate(p) { try { navigator.vibrate && navigator.vibrate(p); } catch (_) { /* egal */ } }
function store(key, val) { try { if (val === undefined) return JSON.parse(localStorage.getItem(key)); localStorage.setItem(key, JSON.stringify(val)); } catch (_) { return null; } }
function mealNow() {
  const h = new Date().getHours() + new Date().getMinutes() / 60;
  if (h < 10.5) return "fruehstueck";
  if (h < 14.5) return "mittag";
  if (h < 17.5) return "snack";
  if (h < 22) return "abend";
  return "snack";
}
function parseNum(v) { const n = parseFloat(String(v ?? "").replace(",", ".")); return Number.isFinite(n) ? n : null; }

/* Uhrzeiten immer 24 Stunden (HH:MM). <input type="time"> folgt der Sprache des Browsers
   und zeigt in einem englischen Browser AM/PM – deshalb ein eigenes Textfeld. */
function timeField(id, value, optional = false) {
  return `<input type="text" class="time" id="${id}" value="${esc(value || "")}" inputmode="numeric" maxlength="5" placeholder="${optional ? "aus" : "HH:MM"}" autocomplete="off">`;
}
function normTime(v) {
  const d = String(v || "").replace(/\D/g, "");
  if (!d) return "";
  const [h, m] = d.length <= 2 ? [d, "0"] : d.length === 3 ? [d.slice(0, 1), d.slice(1)] : [d.slice(0, 2), d.slice(2, 4)];
  if (+h > 23 || +m > 59) return null;
  return `${pad(+h)}:${pad(+m)}`;
}
function bindTimes(root) {
  $$("input.time", root).forEach(i => {
    i.addEventListener("input", () => {
      const d = i.value.replace(/\D/g, "").slice(0, 4);
      i.value = d.length > 2 ? `${d.slice(0, 2)}:${d.slice(2)}` : d;
      i.classList.toggle("bad", false);
    });
    i.addEventListener("blur", () => { const t = normTime(i.value); if (t != null) i.value = t; i.classList.toggle("bad", t == null); });
  });
}
/* Dezimalzahlen mit Komma oder Punkt, unabhängig von der Browsersprache */
function decField(attrs, value) { return `<input type="text" inputmode="decimal" autocomplete="off" ${attrs} value="${value ?? ""}">`; }

function toast(msg, ms = 2600, actions = null) {
  const t = $("#toast");
  t.textContent = "";
  const span = document.createElement("span"); span.textContent = msg; t.appendChild(span);
  t.hidden = false;
  for (const a of [].concat(actions || [])) {
    const b = document.createElement("button");
    b.className = "toast-action"; b.textContent = a.label;
    b.onclick = () => { t.hidden = true; a.fn(); };
    t.appendChild(b); ms = Math.max(ms, 6000);
  }
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}

/* Punkte im Browser (gleiche Formel wie app/points.py), für die Vorschau beim Erfassen */
const F = { kcal: 35, satfat: 4, sugar: 10, alcohol: 8, protein: 10, fiber: 5 };
function scaleFood(food, g) {
  const out = {};
  for (const k of ["kcal", "protein", "fat", "satfat", "carbs", "sugar", "fiber", "alcohol", "salt"]) out[k] = (food[k] || 0) * g / 100;
  return out;
}
function rawPoints(n) {
  return Math.max(0, n.kcal / F.kcal + n.satfat / F.satfat + n.sugar / F.sugar + n.alcohol / F.alcohol - n.protein / F.protein - n.fiber / F.fiber);
}
function pointsFor(food, g) {
  if (food.zero) return 0;
  if (food.pts_100 != null) return Math.floor(food.pts_100 * g / 100 + 0.5);  // Gericht
  return Math.floor(rawPoints(scaleFood(food, g)) + 0.5);
}
function ampel(kcal100) { return kcal100 < 100 ? "green" : kcal100 <= 240 ? "yellow" : "red"; }

/* ---------- API ---------- */

class AuthError extends Error {}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", credentials: "same-origin", headers: { "x-fitpath": "1" } };
  if (opts.body !== undefined) { init.headers["content-type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  const r = await fetch(path, init);
  if (r.status === 401) throw new AuthError();
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* egal */ }
    throw new Error(msg);
  }
  return opts.raw ? r : r.json();
}

function dayParam() { return curDay && curDay !== (S && S.today) ? `?day=${curDay}` : ""; }

async function loadState() {
  try {
    S = await api("/api/state" + dayParam());
    if (!dayParam()) store("fp_state", S);
    if (S.version) $("#app-ver").textContent = "v" + S.version;
  } catch (e) {
    if (e instanceof AuthError) throw e;
    S = S || store("fp_state");
    if (!S) throw e;
  }
  return S;
}

/* Offline-Warteschlange für Einträge */
function queue() { return store("fp_queue") || []; }
async function flushQueue() {
  const q = queue();
  if (!q.length || !navigator.onLine) return;
  try {
    await api("/api/log", { method: "POST", body: q });
    store("fp_queue", []);
  } catch (_) { /* später erneut */ }
}
async function saveEntry(e) {
  e.id = e.id || uuid();
  try {
    S = await api("/api/log", { method: "POST", body: e });
    return true;
  } catch (err) {
    if (err instanceof AuthError) throw err;
    if (!navigator.onLine || err instanceof TypeError) {
      store("fp_queue", [...queue().filter(x => x.id !== e.id), e]);
      toast("Offline gespeichert – wird später übertragen");
      return true;
    }
    toast(err.message);
    return false;
  }
}
async function deleteEntry(id) {
  const q = queue();
  if (q.some(x => x.id === id)) { store("fp_queue", q.filter(x => x.id !== id)); return; }
  S = await api(`/api/log/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/* ---------- Sheet ---------- */

/* Android-Zurück-Taste schließt offene Dialoge */
function openSheet(html, onMount, tall = false) {
  const wasOpen = !$("#sheet").hidden;
  if (sheetCleanup) { sheetCleanup(); sheetCleanup = null; }
  $("#sheet-body").innerHTML = html;
  $(".sheet-panel").classList.toggle("tall", tall);
  $("#sheet").hidden = false;
  document.body.style.overflow = "hidden";
  if (!wasOpen) history.pushState({ fpSheet: 1 }, "");
  onMount && onMount($("#sheet-body"));
}
function hideSheet() {
  if (sheetCleanup) { sheetCleanup(); sheetCleanup = null; }
  $("#sheet").hidden = true;
  document.body.style.overflow = "";
}
function closeSheet() {
  hideSheet();
  if (history.state && history.state.fpSheet) history.replaceState({ fpDone: 1 }, "");
}
window.addEventListener("popstate", e => {
  if (!$("#sheet").hidden) { hideSheet(); return; }
  if (e.state && e.state.fpDone) history.back();
});
$("#sheet").addEventListener("click", e => { if (e.target.closest("[data-close]")) closeSheet(); });

function chipGroup(name, items, selected, multi = false, cls = "") {
  return `<div class="chips ${cls}" data-group="${name}" data-multi="${multi ? 1 : 0}">` + items.map(([val, label]) =>
    `<button type="button" class="chip${(multi ? (selected || []).map(String).includes(String(val)) : String(selected) === String(val)) ? " on" : ""}" data-val="${esc(val)}">${label}</button>`
  ).join("") + "</div>";
}
function bindChips(root, onChange) {
  $$("[data-group]", root).forEach(g => g.addEventListener("click", e => {
    const b = e.target.closest(".chip"); if (!b) return;
    if (g.dataset.multi === "1") b.classList.toggle("on");
    else { $$(".chip", g).forEach(c => c.classList.remove("on")); b.classList.add("on"); }
    onChange && onChange(g.dataset.group, chipVal(root, g.dataset.group));
  }));
}
function chipVal(root, name) {
  const g = $(`[data-group="${name}"]`, root);
  if (!g) return null;
  const on = $$(".chip.on", g).map(c => c.dataset.val);
  return g.dataset.multi === "1" ? on : (on[0] ?? null);
}

/* ---------- Router ---------- */

const routes = { heute: viewToday, statistik: viewStats, gewicht: viewWeight, mehr: viewMore, erfolge: viewAchievements };

async function render() {
  const route = (location.hash || "#heute").slice(1).split("?")[0];
  if (!S) {
    try { await loadState(); } catch (e) { return e instanceof AuthError ? viewLogin() : viewError(e); }
  }
  if (route.startsWith("pair=")) {                // QR-Code eines neuen Geräts gescannt
    history.replaceState(null, "", "#heute");
    if (S.settings.onboarded) viewToday();
    return openPairApprove(route.slice(5));
  }
  if (!S.settings.onboarded) { $("#tabbar").hidden = true; return viewOnboarding(); }
  $("#tabbar").hidden = false;
  $("#sos-top").hidden = false;
  if (route === "erfassen" || route === "scannen" || route === "einkauf" || route === "wiegen" || route === "sos") {
    history.replaceState(null, "", "#heute");
    viewToday();
    $$(".tabbar a").forEach(a => a.classList.toggle("active", a.dataset.tab === "heute"));
    if (route === "erfassen") openAdd(mealNow());
    if (route === "scannen") openScan(mealNow());
    if (route === "einkauf") openShop();
    if (route === "wiegen") openWeigh();
    if (route === "sos") openSOS();
    return;
  }
  $$(".tabbar a").forEach(a => a.classList.toggle("active", a.dataset.tab === route));
  (routes[route] || viewToday)();
  celebrate(pendingCelebrations());
}
$("#sos-top").onclick = () => openSOS();
window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });

let pairRun = 0;   // laufende Kopplung auf der Anmeldeseite (neue Nummer = alte stoppt)

function viewLogin() {
  $("#tabbar").hidden = true;
  $("#sos-top").hidden = true;
  const bad = location.search.includes("login=ungueltig");
  const my = ++pairRun;
  view.innerHTML = `
    <div class="card hero mt">
      <h1>Gerät verbinden</h1>
      ${bad ? `<p style="color:var(--bad)">Der Link war abgelaufen oder schon benutzt.</p>` : ""}
      <div id="pair"><p class="muted">Lade Code …</p></div>
      <details class="more mt"><summary>Erstes Gerät oder kein Gerät zur Hand?</summary>
        <p class="note">Anmeldelink auf dem Server erzeugen und öffnen:</p>
        <p class="linkbox">docker compose exec fitpath python -m app.cli link Handy</p></details>
    </div>`;
  let rid = null, until = 0, tick = null;
  const alive = () => my === pairRun && $("#pair");
  const start = async () => {
    if (!alive()) return;
    let r;
    try { r = await api("/api/pair/start", { method: "POST", body: {} }); }
    catch (e) { if (alive()) $("#pair").innerHTML = `<p style="color:var(--bad)">${esc(e.message)}</p><button class="btn" id="pair-retry">Nochmal</button>`;
      $("#pair-retry") && ($("#pair-retry").onclick = start); return; }
    if (!alive()) return;
    rid = r.rid; until = Date.now() + r.seconds * 1000;
    $("#pair").innerHTML = `<p class="muted">Auf einem schon verbundenen Gerät unter <b>Mehr → Geräte → QR scannen</b> diesen Code scannen<br>oder über <b>Code eingeben</b> diese Zahl eintippen:</p>
      <div class="pair-qr">${r.qr_svg}</div>
      <div class="pair-code">${r.code.slice(0, 3)} ${r.code.slice(3)}</div>
      <p class="note" id="pair-left"></p>`;
  };
  const poll = async () => {
    if (!alive()) return clearInterval(tick);
    const left = Math.max(0, Math.round((until - Date.now()) / 1000));
    $("#pair-left") && ($("#pair-left").textContent = `Wartet auf Freigabe … neuer Code in ${Math.floor(left / 60)}:${pad(left % 60)}`);
    if (!rid) return;
    if (!left) { rid = null; return start(); }
    let r;
    try { r = await api("/api/pair/poll", { method: "POST", body: { rid } }); } catch (_) { return; }
    if (!alive()) return;
    if (r.status === "approved") {
      clearInterval(tick); pairRun++;
      history.replaceState(null, "", "/#heute");
      S = null; toast("Verbunden ✅"); render();
    } else if (r.status === "denied") { rid = null; toast("Abgelehnt"); start(); }
    else if (r.status === "expired") { rid = null; start(); }
  };
  start();
  tick = setInterval(poll, 2000);
}

async function openPairApprove(code) {
  code = String(code || "").replace(/\D/g, "");
  let info;
  try { info = await api(`/api/pair/${code}`); } catch (e) { return toast(e.message); }
  openSheet(`<h2>🔗 Gerät verbinden?</h2>
    <p><b>${esc(info.label)}</b> möchte sich verbinden (Code ${code.slice(0, 3)} ${code.slice(3)}, angefragt vor ${info.age_s < 60 ? `${info.age_s} s` : `${Math.round(info.age_s / 60)} min`}).</p>
    ${info.same_ip ? `<p class="note">Aus demselben Netz wie dieses Gerät.</p>`
      : `<p><span class="pill warn">Andere Adresse${info.ip ? ": " + esc(info.ip) : ""}</span></p>
         <p class="note">Das neue Gerät ist in einem anderen Netz (z. B. Mobilfunk statt WLAN). Hat dir jemand diesen Code geschickt oder vorgelesen: <b>ablehnen</b>.</p>`}
    <p class="note">Nur zulassen, wenn du das gerade selbst bist und der Code auf dem neuen Gerät genauso aussieht.</p>
    <label class="f"><span>Name des Geräts</span><input type="text" id="pair-name" value="${esc(info.name)}" maxlength="40"></label>
    <div class="row nowrap mt"><button class="btn danger grow" id="pair-no">Ablehnen</button><button class="btn primary grow" id="pair-yes">Zulassen</button></div>`, root => {
    const decide = async approve => {
      try { await api(`/api/pair/${code}`, { method: "POST", body: { approve, name: $("#pair-name", root).value.trim() } }); }
      catch (e) { return toast(e.message); }
      closeSheet(); toast(approve ? "Freigegeben – das neue Gerät verbindet sich gleich" : "Abgelehnt");
      if ($("#devs")) setTimeout(loadDevices, 3000);
    };
    $("#pair-yes", root).onclick = () => decide(true);
    $("#pair-no", root).onclick = () => decide(false);
  });
}

// QR-Code des neuen Geräts in der App scannen (die Kamera-App öffnet den Link oft im Browser statt in der PWA)
const pairCodeOf = codes => {
  for (const c of codes) {
    const m = /[#&?]pair=(\d{6})/.exec(c.rawValue || "") || /^\s*(\d{3}) ?(\d{3})\s*$/.exec(c.rawValue || "");
    if (m) return m.slice(1).join("");
  }
  return null;
};
function openPairScan() {
  const live = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  if (!live) return openPairCode();
  openSheet(`<h2>🔗 QR-Code scannen</h2>
    <div class="scan" id="scan-box"><video id="cam" playsinline muted></video></div>
    <p class="note center" id="scan-hint">Kamera startet …</p>
    <button class="btn block" id="ps-code">Code stattdessen eintippen</button>`, root => {
    const hint = t => { const h = $("#scan-hint", root); if (h) h.textContent = t; };
    let done = false;
    const cam = liveScan(root, code => {
      if (done) return; done = true; cam.stop(); vibrate(60); openPairApprove(code);
    }, st => {
      if (st === "loading") hint("Scanner wird geladen …");
      else if (st === "ready") hint("QR-Code vom neuen Gerät in die Kamera halten …");
      else { $("#scan-box", root) && ($("#scan-box", root).hidden = true); hint(`${camError(st)} – Code eintippen.`); }
    }, false, QR, pairCodeOf);
    sheetCleanup = () => cam.stop();
    $("#ps-code", root).onclick = () => { cam.stop(); openPairCode(); };
  });
}

function openPairCode() {
  openSheet(`<h2>🔗 Code eingeben</h2>
    <p class="muted">Das neue Gerät zeigt beim Öffnen von FitPath einen QR-Code und eine 6-stellige Zahl.</p>
    <input type="text" inputmode="numeric" id="pc" class="big" maxlength="7" placeholder="123 456" autocomplete="off">
    <button class="btn primary block mt" id="pc-go">Weiter</button>`, root => {
    const go = () => { const c = $("#pc", root).value.replace(/\D/g, ""); if (c.length === 6) openPairApprove(c); else toast("6 Ziffern eingeben"); };
    $("#pc-go", root).onclick = go;
    $("#pc", root).onkeydown = e => { if (e.key === "Enter") go(); };
    setTimeout(() => $("#pc", root).focus(), 250);
  });
}
function viewError(e) {
  view.innerHTML = `<div class="card mt center"><div class="big-emoji">⚠️</div><p>Server nicht erreichbar.</p><p class="muted">${esc(e.message)}</p>
    <button class="btn primary" id="retry">Nochmal</button></div>`;
  $("#retry").onclick = () => { S = null; render(); };
}

/* ---------- Heute ---------- */

function ringSvg(frac, over) {
  const r = 92, c = 2 * Math.PI * r, f = Math.max(0, Math.min(frac || 0, 1));
  return `<svg viewBox="0 0 210 210" aria-hidden="true">
    <circle cx="105" cy="105" r="${r}" fill="none" stroke="var(--card-2)" stroke-width="16"/>
    ${f > 0 ? `<circle cx="105" cy="105" r="${r}" fill="none" stroke="${over ? "var(--bad)" : "var(--accent)"}" stroke-width="16" stroke-linecap="round"
      stroke-dasharray="${(c * f).toFixed(1)} ${c.toFixed(1)}"/>` : ""}</svg>`;
}

function viewToday() {
  const o = S.overview, b = o.budget, w = o.week, t = o.totals || {};
  const P = isPoints();
  const act = o.activity || {};
  const budget = P ? b.points : b.target;
  const bonus = P ? (act.act_points || 0) : (act.act_kcal || 0);
  const used = P ? (t.points || 0) : Math.round(t.kcal || 0);
  const left = P ? w.today_left_points : w.today_left_kcal;
  const reserve = P ? w.reserve_points : w.reserve_kcal;
  const fromRes = P ? w.from_reserve_points : w.from_reserve_kcal;
  const isToday = o.day === S.today;
  const over = left < 0 && fromRes < -left;
  const weekDays = Object.fromEntries(w.days.map(d => [d.day, d]));
  const monday = w.start;

  view.innerHTML = `
    <div class="daynav"><button class="btn icon small-icon" id="prev" aria-label="Tag zurück">‹</button>
      <b>${isToday ? "Heute" : fmtDay(o.day, { weekday: "long", day: "2-digit", month: "2-digit" })}</b>
      <button class="btn icon small-icon" id="next" aria-label="Tag vor" ${isToday ? "disabled" : ""}>›</button></div>
    <div class="card hero">
      <div class="ring toggle" id="ring" role="button" tabindex="0" aria-label="Anzeige umschalten auf ${P ? "Kalorien" : "Punkte"}">${ringSvg(used / Math.max(budget + bonus, 1), over)}
        <div class="t${over ? " over" : ""}"><b>${num.format(left)}</b><span>${P ? "Punkte übrig" : "kcal übrig"}</span>
          <small class="used"><b>${num.format(used)}</b> verbraucht</small></div></div>
      ${left < 0 && fromRes ? `<p><span class="pill warn">${num.format(fromRes)} ${unit()} aus der Wochenreserve</span></p>` : ""}
      <div class="tiles three">
        <div class="tile"><div class="v">${num.format(budget)}</div><div class="l">Budget</div></div>
        <div class="tile"><div class="v">${bonus ? "+" + num.format(bonus) : "0"}</div><div class="l">Aktivität</div></div>
        <div class="tile"><div class="v">${num.format(reserve)}</div><div class="l">Reserve Woche</div></div>
      </div>
      <div class="week" id="week">${WEEKDAYS.map((wd, i) => {
        const day = addDays(monday, i), d = weekDays[day];
        const cls = day > S.today ? "future" : !d || !d.entries ? "" : (P ? d.left_points : d.left_kcal) >= 0 ? "ok" : "over";
        return `<div class="${cls}${day === o.day ? " cur" : ""}" data-day="${day}">${wd}<b>${d && d.entries ? num.format(P ? d.points : d.kcal) : "–"}</b></div>`;
      }).join("")}</div>
    </div>
    ${challengeHtml()}
    ${levelHtml()}
    ${fitsHtml(left)}
    ${quickHtml()}
    ${MEALS.map(([key, label, icon]) => mealHtml(key, label, icon)).join("")}
    ${activityHtml()}
    ${weightMiniHtml()}`;

  const ring = $("#ring");
  ring.onclick = toggleDisplay;
  ring.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleDisplay(); } };
  $("#prev").onclick = () => goDay(addDays(o.day, -1));
  $("#next").onclick = () => !isToday && goDay(addDays(o.day, 1));
  $("#week").onclick = e => { const d = e.target.closest("[data-day]"); if (d && d.dataset.day <= S.today) goDay(d.dataset.day); };
  $$("[data-add]").forEach(bt => (bt.onclick = () => openAdd(bt.dataset.add)));
  $$("[data-entry]").forEach(li => (li.onclick = () => {
    const e = o.entries.find(x => x.id === li.dataset.entry);
    if (e) openEntry(e);
  }));
  $$("[data-quick]").forEach(bt => (bt.onclick = () => quickAdd(+bt.dataset.quick)));
  $$("[data-fit]").forEach(bt => (bt.onclick = () => fitAdd(bt.dataset.fit)));
  $$("[data-copy]").forEach(bt => (bt.onclick = () => openCopy(bt.dataset.copy)));
  $$("[data-keep]").forEach(bt => (bt.onclick = () => {
    const meal = bt.dataset.keep, list = o.entries.filter(e => e.meal === meal && e.food_id);
    openTemplateEdit({ name: TPL_NAME[meal], meal, items: list.map(e => ({ food_id: e.food_id, grams: e.grams, portion: e.portion, name: e.name, points: e.points, kcal: e.kcal })) });
  }));
  $$("[data-tpl]").forEach(bt => (bt.onclick = () => {
    const t = (S.templates || []).find(x => x.id === bt.dataset.tpl);
    if (t) logTemplate(t, bt.dataset.meal);
  }));
  bindChallenge();
  $("#act-card") && ($("#act-card").onclick = e => {
    const li = e.target.closest("[data-workout]");
    if (li) return openWorkout(((o.activity || {}).workouts || []).find(x => x.id === li.dataset.workout));
    if (e.target.closest("#train-add")) return openWorkout();
    openSteps();
  });
  $("#weigh-btn") && ($("#weigh-btn").onclick = e => { e.preventDefault(); openWeigh(); });
}

// Tipp auf den Ring: Punkte <-> kcal. Sofort umschalten, dann speichern;
// der Server liefert den Stand von heute, deshalb nur die Einstellung übernehmen.
async function toggleDisplay() {
  const prev = S.settings.display, next = isPoints() ? "kcal" : "points";
  S.settings.display = next;
  vibrate(15);
  viewToday();
  try {
    const r = await api("/api/settings", { method: "PUT", body: { display: next } });
    S.settings = r.settings;
    if (!curDay) store("fp_state", S);
  } catch (e) {
    S.settings.display = prev;
    viewToday();
    toast("Offline – Anzeige nicht gespeichert");
  }
}

async function goDay(day) {
  curDay = day === S.today ? null : day;
  try { await loadState(); } catch (e) { return toast("Offline – Tag nicht geladen"); }
  viewToday();
}

/* „Was passt noch?“: eigene Favoriten, Zuletzt und gespeicherte Mahlzeiten, die in die übrigen Punkte passen.
   Ab 15 Uhr, nur heute. Satt machendes zuerst (grüne Ampel, viel Eiweiß je kcal), dazu ein 0-Punkte-Lebensmittel. */
const FITS_FROM_HOUR = 15;
function fitList(left) {
  const P = isPoints(), val = x => P ? x.points : x.kcal;
  const ok = (S.fits || []).filter(x => val(x) <= left);
  const zero = ok.find(x => x.zero);
  const score = x => ({ green: 2, yellow: 1, red: 0 }[x.ampel] || 0) + Math.min(x.protein / Math.max(x.kcal, 1) * 100 / 4, 2)
    + (x.fav ? 0.5 : 0) + Math.min(val(x) / Math.max(left, 1), 1);
  const rest = ok.filter(x => !x.zero && val(x) > 0).sort((a, b) => score(b) - score(a)).slice(0, 5);
  return zero ? [...rest, zero] : rest;
}
function fitsHtml(left) {
  const P = isPoints();
  if (curDay || new Date().getHours() < FITS_FROM_HOUR || left < (P ? 2 : 70)) return "";
  const list = fitList(left);
  if (!list.length) return "";
  return `<div class="card" style="padding:12px 16px"><div class="spread"><h3 style="margin:0">💡 Passt noch</h3><small>${num.format(left)} ${unit()} übrig · ein Tipp → ${esc(MEAL_LABEL[mealNow()])}</small></div>
    <div class="chips scroll" style="margin-top:8px">${list.map(x => `<button class="chip" data-fit="${x.kind}:${esc(String(x.id))}">${x.kind === "tpl" ? "⭐ " : ""}${esc(shortName(x.name))}${x.kind === "food" ? ` · ${x.portion ? esc(x.portion) : fmtG(x.grams)}` : ""} · ${x.zero && P ? "0 P" : fmtVal(x.points, x.kcal)}</button>`).join("")}</div></div>`;
}
async function fitAdd(key) {
  const [kind, id] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
  const x = (S.fits || []).find(f => f.kind === kind && String(f.id) === id); if (!x) return;
  if (kind === "tpl") { const t = (S.templates || []).find(t => t.id === id); return t && logTemplate(t, mealNow()); }
  const e = { id: uuid(), food_id: x.id, grams: x.grams, portion: x.portion, meal: mealNow(), day: S.today };
  vibrate(30);
  if (!(await saveEntry(e))) return;
  viewToday();
  toast(`${shortName(x.name)} erfasst`, 6000, [{ label: "Rückgängig", fn: async () => { await deleteEntry(e.id); viewToday(); } }]);
}

function quickHtml() {
  const r = (S.recent || []).slice(0, 8);
  if (!r.length) return "";
  return `<div class="card" style="padding:12px 16px"><div class="spread"><h3 style="margin:0">⚡ Nochmal</h3><small>ein Tipp → ${esc(MEAL_LABEL[mealNow()])}</small></div>
    <div class="chips scroll" style="margin-top:8px">${r.map(f => `<button class="chip" data-quick="${f.id}">${esc(shortName(f.name))} · ${f.last_portion ? esc(f.last_portion) : fmtG(f.last_grams)}</button>`).join("")}</div></div>`;
}
function shortName(n) { const s = n.split(",")[0]; return s.length > 26 ? s.slice(0, 25) + "…" : s; }

async function quickAdd(foodId) {
  const f = S.recent.find(x => x.id === foodId); if (!f) return;
  const e = { id: uuid(), food_id: f.id, grams: f.last_grams, portion: f.last_portion, meal: mealNow(), day: curDay || S.today };
  vibrate(30);
  if (!(await saveEntry(e))) return;
  viewToday();
  toast(`${shortName(f.name)} erfasst`, 6000, [{ label: "Rückgängig", fn: async () => { await deleteEntry(e.id); viewToday(); } }]);
}

function prevHtml(key) {
  const p = (S.overview.prev || {})[key];
  if (!p || !p.count) return `<div class="empty-line">Noch nichts erfasst.</div>`;
  const what = p.names.join(", ") + (p.count > p.names.length ? ` +${p.count - p.names.length}` : "");
  return `<div class="empty-line" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">Gestern: ${esc(what)}</div>`;
}

// Fenster „Wie gestern“: Einträge vom Vortag ansehen, einzelne rausnehmen, Rest übernehmen
function openCopy(meal) {
  const p = (S.overview.prev || {})[meal]; if (!p || !p.count) return;
  const items = p.items || [];
  const keep = new Set(items.map(it => it.id));
  openSheet(`<h2>↺ ${esc(MEAL_LABEL[meal])} wie gestern</h2>
    <p class="note" style="margin-top:0">Was du nicht nochmal willst, mit ✕ rausnehmen. Der Eintrag von gestern bleibt dabei erhalten.</p>
    <ul class="list" id="cp-items"></ul>
    <div class="row nowrap mt"><button class="btn" id="cp-cancel">Abbrechen</button><button class="btn primary grow" id="cp-save"></button></div>`, root => {
    const draw = () => {
      const sel = items.filter(it => keep.has(it.id));
      $("#cp-items", root).innerHTML = sel.length ? sel.map(it => `<li><span class="dot ${it.ampel || "green"}"></span>
        <div class="bd"><b>${esc(it.name)}</b><div class="meta">${it.portion ? esc(it.portion) + " · " : ""}${fmtG(it.grams || 0)}</div></div>
        <span class="val">${fmtVal(it.points, it.kcal || 0)}</span>
        <button class="btn icon small-icon" data-rm="${esc(it.id)}" aria-label="Rausnehmen">✕</button></li>`).join("")
        : `<li><div class="bd muted">Nichts mehr ausgewählt.</div></li>`;
      const pts = sel.reduce((a, it) => a + it.points, 0), kcal = sel.reduce((a, it) => a + (it.kcal || 0), 0);
      const btn = $("#cp-save", root);
      btn.disabled = !sel.length;
      btn.textContent = sel.length ? `${sel.length === items.length ? "Alles" : sel.length} übernehmen · ${fmtVal(pts, kcal)}` : "Übernehmen";
    };
    $("#cp-items", root).onclick = e => { const b = e.target.closest("[data-rm]"); if (b) { keep.delete(b.dataset.rm); draw(); } };
    $("#cp-cancel", root).onclick = closeSheet;
    $("#cp-save", root).onclick = () => { closeSheet(); copyMeal(meal, keep.size < items.length ? [...keep] : null); };
    draw();
  });
}

async function copyMeal(meal, ids = null) {
  const o = S.overview, before = new Set(o.entries.map(e => e.id));
  const body = { from: o.prev_day, to: o.day, meal };
  if (ids) body.ids = ids;
  try { S = await api("/api/log/copy", { method: "POST", body }); }
  catch (e) { return toast(e.message); }
  const added = S.overview.entries.filter(e => !before.has(e.id)).map(e => e.id);
  vibrate(30); lists = null; viewToday();
  toast(`${MEAL_LABEL[meal]} wie gestern übernommen`, 6000, [{ label: "Rückgängig", fn: async () => {
    for (const id of added) { try { await deleteEntry(id); } catch (_) { /* weiter */ } }
    viewToday();
  } }]);
}

/* ---------- Gespeicherte Mahlzeiten ---------- */

const TPL_NAME = { fruehstueck: "Mein Frühstück", mittag: "Mein Mittagessen", abend: "Mein Abendessen", snack: "Mein Snack" };

async function logTemplate(t, meal, skip = []) {
  let r;
  try { r = await api(`/api/templates/${encodeURIComponent(t.id)}/log`, { method: "POST", body: { meal, day: curDay || S.today, skip } }); }
  catch (e) { return toast(e.message); }
  const added = r.added || []; delete r.added; S = r;
  vibrate(30); lists = null; viewToday();
  toast(`${t.name} erfasst`, 6000, [{ label: "Rückgängig", fn: async () => {
    for (const id of added) { try { await deleteEntry(id); } catch (_) { /* weiter */ } }
    viewToday();
  } }]);
}

const tplRow = (it, i, btn) => `<li><span class="dot ${it.ampel || "green"}"></span>
  <div class="bd"><b>${esc(it.name || "")}</b><div class="meta">${it.portion ? esc(it.portion) + " · " : ""}${fmtG(it.grams)}</div></div>
  <span class="val">${fmtVal(it.points || 0, it.kcal || 0)}</span>${btn ? `<button class="btn icon small-icon" data-rm="${i}" aria-label="Rausnehmen">✕</button>` : ""}</li>`;

// Vorschau zum Erfassen: einzelnes diesmal weglassen, dann in die gewählte Mahlzeit übernehmen
function openTemplate(t, meal) {
  const skip = new Set();
  openSheet(`<h2>⭐ ${esc(t.name)}</h2>
    ${chipGroup("meal", MEALS.map(([k, l, i]) => [k, `${i} ${l}`]), meal, false, "scroll")}
    <ul class="list" id="tp-items"></ul>
    <p class="note">Mit ✕ diesmal weglassen, die gespeicherte Mahlzeit bleibt, wie sie ist.</p>
    <button class="btn primary block" id="tp-log"></button>
    <div class="row nowrap mt"><button class="btn grow" id="tp-edit">Bearbeiten</button><button class="btn danger" id="tp-del">Löschen</button></div>`, root => {
    bindChips(root);
    const draw = () => {
      const sel = t.items.filter((_, i) => !skip.has(i));
      $("#tp-items", root).innerHTML = t.items.map((it, i) => skip.has(i) ? "" : tplRow(it, i, true)).join("") || `<li><div class="bd muted">Nichts mehr ausgewählt.</div></li>`;
      const btn = $("#tp-log", root);
      btn.disabled = !sel.length;
      btn.textContent = sel.length ? `Erfassen · ${fmtVal(sel.reduce((a, x) => a + x.points, 0), sel.reduce((a, x) => a + x.kcal, 0))}` : "Erfassen";
    };
    $("#tp-items", root).onclick = e => { const b = e.target.closest("[data-rm]"); if (b) { skip.add(+b.dataset.rm); draw(); } };
    $("#tp-log", root).onclick = () => { closeSheet(); logTemplate(t, chipVal(root, "meal") || meal, [...skip]); };
    $("#tp-edit", root).onclick = () => openTemplateEdit(t);
    $("#tp-del", root).onclick = async () => { if (await deleteTemplate(t)) { closeSheet(); viewToday(); } };
    draw();
  });
}

// Neu (aus einer Mahlzeit auf Heute) oder bearbeiten: Name, Standard-Mahlzeit, Lebensmittel rausnehmen
function openTemplateEdit(t, done = null) {
  const items = t.items.map(x => ({ ...x }));
  const others = (S.templates || []).filter(x => x.id !== t.id).map(x => x.name.toLowerCase());
  openSheet(`<h2>${t.id ? "Mahlzeit bearbeiten" : "☆ Als Mahlzeit merken"}</h2>
    <label class="f"><span>Name</span><input type="text" id="te-name" maxlength="60" value="${esc(t.name || "")}"></label>
    <p class="note" id="te-same" hidden>Eine Mahlzeit mit diesem Namen gibt es schon. Speichern ersetzt sie.</p>
    <label class="f"><span>Auf Heute anbieten bei</span></label>
    ${chipGroup("tmeal", [...MEALS.map(([k, l, i]) => [k, `${i} ${l}`]), ["", "nirgends"]], t.meal || "", false, "scroll")}
    <ul class="list" id="te-items"></ul>
    <p class="note">Ergänzen: Mahlzeit auf Heute erfassen, dort anpassen und mit ☆ unter demselben Namen neu merken.</p>
    <div class="row nowrap">${t.id ? `<button class="btn danger" id="te-del">Löschen</button>` : ""}<button class="btn primary grow" id="te-save">Speichern</button></div>`, root => {
    bindChips(root);
    const name = $("#te-name", root);
    const draw = () => {
      $("#te-items", root).innerHTML = items.map((it, i) => tplRow(it, i, items.length > 1)).join("");
      $("#te-save", root).disabled = !items.length;
    };
    name.oninput = () => { $("#te-same", root).hidden = !t.id ? !others.includes(name.value.trim().toLowerCase()) : true; };
    name.oninput();
    $("#te-items", root).onclick = e => { const b = e.target.closest("[data-rm]"); if (b) { items.splice(+b.dataset.rm, 1); draw(); } };
    $("#te-save", root).onclick = async () => {
      const body = { name: name.value.trim(), meal: chipVal(root, "tmeal") || null,
        items: items.map(({ food_id, grams, portion }) => ({ food_id, grams, portion })) };
      try { S = await api(t.id ? `/api/templates/${encodeURIComponent(t.id)}` : "/api/templates", { method: t.id ? "PUT" : "POST", body }); }
      catch (e) { return toast(e.message); }
      lists = null;
      if (done) done(); else { closeSheet(); viewToday(); }
      toast(t.id ? "Gespeichert" : `„${body.name}“ gemerkt${body.meal ? ` – steht bei ${MEAL_LABEL[body.meal]} bereit` : ""}`);
    };
    $("#te-del", root) && ($("#te-del", root).onclick = async () => {
      if (!await deleteTemplate(t)) return;
      if (done) done(); else { closeSheet(); viewToday(); }
    });
    draw();
  });
}

async function deleteTemplate(t) {
  if (!confirm(`„${t.name}“ löschen? Schon erfasste Einträge bleiben.`)) return false;
  try { S = await api(`/api/templates/${encodeURIComponent(t.id)}`, { method: "DELETE" }); } catch (e) { toast(e.message); return false; }
  lists = null; toast("Mahlzeit gelöscht");
  return true;
}

function mealHtml(key, label, icon) {
  const list = S.overview.entries.filter(e => e.meal === key);
  const sumP = list.reduce((a, e) => a + e.points, 0), sumK = list.reduce((a, e) => a + (e.kcal || 0), 0);
  const prev = (S.overview.prev || {})[key], canCopy = !list.length && prev && prev.count;
  const tpls = list.length ? [] : (S.templates || []).filter(t => t.meal === key).slice(0, 3);
  return `<div class="card meal"><div class="card-head"><h2>${icon} ${label}</h2>
      <div class="row nowrap"><span class="sum">${list.length ? fmtVal(sumP, sumK) : ""}</span>
      ${canCopy ? `<button class="btn icon small-icon" data-copy="${key}" aria-label="${label} wie gestern" title="Wie gestern">↺</button>` : ""}
      ${list.length ? `<button class="btn icon small-icon" data-keep="${key}" aria-label="${label} als Mahlzeit merken" title="Als Mahlzeit merken">☆</button>` : ""}
      <button class="btn icon small-icon" data-add="${key}" aria-label="${label} erfassen">+</button></div></div>
    ${list.length ? `<ul class="list">${list.map(e => `<li class="tap" data-entry="${esc(e.id)}"><span class="dot ${e.ampel}"></span>
      <div class="bd"><b>${esc(e.name)}</b><div class="meta">${e.portion ? esc(e.portion) + " · " : ""}${fmtG(e.grams)}${isPoints() ? ` · ${Math.round(e.kcal || 0)} kcal` : ""}</div></div>
      <span class="val">${e.zero ? `<span class="zero">0 P</span>` : fmtVal(e.points, e.kcal || 0)}</span></li>`).join("")}</ul>`
      : prevHtml(key)}
    ${tpls.length ? `<div class="chips scroll" style="margin-top:8px">${tpls.map(t => `<button class="chip" data-tpl="${esc(t.id)}" data-meal="${key}">⭐ ${esc(t.name)} · ${fmtVal(t.points, t.kcal)}</button>`).join("")}</div>` : ""}</div>`;
}

function activityHtml() {
  const a = S.overview.activity, goal = S.settings.steps_goal || 8000;
  const steps = a && a.steps ? a.steps : 0;
  const src = !a || !a.source ? "Tippen zum Eintragen – oder Health Connect unter Mehr verbinden" :
    a.source === "hc" ? `Health Connect · ${fmtAgo(a.updated)}` : "von Hand eingetragen";
  const ws = (a && a.workouts) || [];
  return `<div class="card" id="act-card" style="cursor:pointer"><div class="card-head"><h2>👟 ${num.format(steps)} Schritte</h2>
    <small>${a && a.act_points ? `+${isPoints() ? a.act_points + " P" : a.act_kcal + " kcal"}` : `Ziel ${num.format(goal)}`}</small></div>
    <div class="progress${steps >= goal ? " good" : ""}"><i style="width:${Math.min(steps / goal, 1) * 100}%"></i></div>
    <small>${esc(src)}</small>
    ${ws.length ? `<ul class="list mt">${ws.map(w => `<li class="tap" data-workout="${esc(w.id)}"><span style="font-size:1.4rem">${w.icon}</span>
      <div class="bd"><b>${esc(w.name)}</b><div class="meta">${fmtMin(w.minutes)} · ${esc(w.intensity)}${w.source === "hc" ? " · ⌚ Uhr" : ""}</div></div>
      <span class="val">${workoutVal(w)}</span></li>`).join("")}</ul>` : ""}
    ${a && a.train_capped ? `<p class="note">Tagesgrenze von ${S.training.max_points_day} Trainingspunkten erreicht.</p>` : ""}
    <button class="btn small block mt" id="train-add">＋ Training</button></div>`;
}
function fmtMin(m) {
  m = Math.round(m);
  return m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}` : `${m} min`;
}
function workoutVal(w) {
  if (w.duplicate) return `<span class="muted">doppelt</span>`;
  if (!w.kcal && w.covered_steps) return `<span class="muted">über Schritte</span>`;
  return `+${fmtVal(w.points, w.kcal)}`;
}

/* ---------- Training ---------- */

// Vorschau wie auf dem Server (training.day_credit): kcal über Ruhe × 50 %, schon gezählte Schritte abgezogen
function trainCredit(kind, inten, minutes, freeSteps) {
  const T = S.training, sp = T.sports[kind], kg = S.overview.budget.weight;
  const met = sp.met[Math.max(0, T.intensities.findIndex(x => x[0] === inten))];
  const net = Math.max(0, met - 1) * kg * minutes / 60;
  const covered = Math.min(Math.floor(sp.spm * minutes), Math.max(0, freeSteps));
  const kcal = Math.max(0, net - covered * kg * T.kcal_per_step_kg) * T.credit;
  return { met, kcal, covered, points: Math.floor(kcal / T.kcal_per_point + 0.5) };
}

function openWorkout(w = null) {
  const T = S.training; if (!T) return;
  const a = S.overview.activity || {};
  const free = (a.extra_steps || 0) - (a.workouts || []).filter(x => !w || x.id !== w.id).reduce((n, x) => n + (x.covered_steps || 0), 0);
  const hc = !!(w && w.source === "hc");
  const kind = w ? w.kind : (store("fp_sport") || "schwimmen");
  const cap = t => t[0].toUpperCase() + t.slice(1);
  openSheet(`<h2>${w ? `${w.icon} Training` : "💪 Training eintragen"}</h2>
    ${hc ? `<p class="note" style="margin-top:0">Von der Uhr über Health Connect${w.title ? ` · „${esc(w.title)}“` : ""} · ${new Date(w.start).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", hour12: false })} Uhr · ${fmtMin(w.minutes)}. Stimmt die Sportart nicht, hier ändern.</p>` : ""}
    ${w && w.duplicate ? `<p class="note" style="color:var(--warn)">Diese Einheit steckt schon in einer anderen (zwei Apps haben sie nach Health Connect geschrieben) und zählt deshalb nicht.</p>` : ""}
    <label class="f"><span>Sportart</span></label>
    ${chipGroup("kind", Object.entries(T.sports).map(([k, sp]) => [k, `${sp.icon} ${esc(sp.name)}`]), kind)}
    ${hc ? "" : `<label class="f mt"><span>Dauer in Minuten</span>${decField('class="big" id="t-min"', numIn.format(w ? w.minutes : 30))}</label>
      ${chipGroup("quick", [15, 30, 45, 60, 90].map(m => [m, `${m} min`]), w ? null : 30)}`}
    <label class="f mt"><span>Intensität</span></label>
    ${chipGroup("inten", T.intensities.map(([k]) => [k, cap(k)]), w ? w.intensity : "mittel")}
    <p class="note" id="t-hint"></p>
    <div class="amount-preview"><div class="big" id="t-pv"></div><small id="t-pv2"></small></div>
    <div class="row nowrap mt">${w ? `<button class="btn danger" id="t-del">Löschen</button>` : ""}<button class="btn primary grow" id="t-save">${w ? "Speichern" : "Eintragen"}</button></div>
    <p class="note">Gezählt wird nur, was über dem Ruheverbrauch liegt, davon die Hälfte, wie bei den Schritten. Schritte, die beim Gehen, Laufen oder Wandern schon gezählt haben, zieht FitPath ab. Höchstens ${T.max_points_day} Trainingspunkte am Tag.</p>`, root => {
    const minutes = () => hc ? w.minutes : (parseNum($("#t-min", root).value) || 0);
    const update = () => {
      const k = chipVal(root, "kind"), i = chipVal(root, "inten"), m = minutes();
      const r = trainCredit(k, i, m, free);
      $("#t-pv", root).textContent = w && w.duplicate ? "zählt nicht" : `+${fmtVal(r.points, r.kcal)}`;
      $("#t-pv2", root).textContent = r.covered ? `${num.format(r.covered)} Schritte davon zählen schon über den Schrittbonus`
        : `Belastung ${num1.format(r.met)} MET · ${Math.round(r.kcal)} kcal gutgeschrieben`;
      $("#t-hint", root).textContent = (T.intensities.find(x => x[0] === i) || [, ""])[1];
      $("#t-save", root).disabled = !hc && !(m >= 3 && m <= 720);
    };
    bindChips(root, g => { if (g === "quick") $("#t-min", root).value = chipVal(root, "quick"); update(); });
    $("#t-min", root) && ($("#t-min", root).oninput = () => { $$('[data-group="quick"] .chip', root).forEach(c => c.classList.remove("on")); update(); });
    update();
    $("#t-save", root).onclick = async () => {
      const body = { kind: chipVal(root, "kind"), intensity: chipVal(root, "inten") };
      if (!hc) body.minutes = minutes();
      try {
        S = w ? await api(`/api/workouts/${encodeURIComponent(w.id)}`, { method: "PUT", body })
          : await api("/api/workouts", { method: "POST", body: { ...body, id: uuid(), day: S.overview.day } });
      } catch (e) { return toast(e.message); }
      store("fp_sport", body.kind);
      vibrate(30); closeSheet(); viewToday();
      toast(w ? "Gespeichert" : "Training eingetragen");
    };
    $("#t-del", root) && ($("#t-del", root).onclick = async () => {
      try { S = await api(`/api/workouts/${encodeURIComponent(w.id)}`, { method: "DELETE" }); } catch (e) { return toast(e.message); }
      closeSheet(); viewToday();
      toast(hc ? "Ausgeblendet – kommt auch mit der Uhr nicht wieder" : "Gelöscht");
    });
  });
}

// „Mitte März“ statt eines genauen Tages: das Tempo schwankt
function fmtAbout(iso) {
  const d = new Date(iso + "T12:00:00"), day = d.getDate();
  const part = day <= 10 ? "Anfang" : day <= 20 ? "Mitte" : "Ende";
  const year = d.getFullYear() !== new Date().getFullYear() ? ` ${d.getFullYear()}` : "";
  return `${part} ${d.toLocaleDateString("de-DE", { month: "long" })}${year}`;
}
function forecastHtml(f, goal) {
  if (!f) return "";
  if (f.stalled) return `<p class="note">📅 Prognose gerade nicht möglich: Der Trend zeigt seit drei Wochen nicht nach unten. Plateaus sind normal, oft geht es danach wieder runter.</p>`;
  const when = f.far ? "in mehr als fünf Jahren" : `etwa <b>${fmtAbout(f.date)}</b> (in ${f.weeks} ${f.weeks === 1 ? "Woche" : "Wochen"})`;
  const base = f.basis === "plan" ? `mit deinem geplanten Tempo von ${num1.format(f.per_week)} kg pro Woche`
    : `bei deinem Tempo von ${num1.format(f.per_week)} kg pro Woche${f.capped ? " (gedeckelt auf 1 % pro Woche, am Anfang ist viel Wasser dabei)" : ""}`;
  return `<p class="note">📅 ${num1.format(goal)} kg ${base}: ${when}.${f.basis === "plan" ? " Genauer, sobald drei Wochen Wiegewerte da sind." : ""}</p>`;
}

function weightMiniHtml() {
  const b = S.body;
  if (!b || !b.trend) return "";
  const weighDay = (S.settings.weigh_days || []).includes((new Date().getDay() + 6) % 7);
  return `<a class="card" href="#gewicht" style="display:block;text-decoration:none;color:inherit">
    <div class="card-head"><h2>⚖️ ${num1.format(b.trend)} kg</h2><small>Trend${b.rate != null ? ` · ${fmtSigned(b.rate)} kg/Woche` : ""}</small></div>
    ${b.weight ? `<small style="display:block;margin-bottom:6px">Waage ${b.weighed_today ? "heute" : fmtDay(b.day)}: <b>${num1.format(b.weight)} kg</b></small>` : ""}
    ${b.progress != null ? `<div class="progress"><i style="width:${b.progress * 100}%"></i></div><small>${num1.format(b.lost)} kg geschafft · Ziel ${num1.format(b.goal)} kg${b.forecast && b.forecast.date ? ` etwa ${fmtAbout(b.forecast.date)}` : ""}</small>` : ""}
    ${!b.weighed_today && weighDay ? `<div class="mt"><button class="btn small primary" id="weigh-btn">Heute wiegen</button></div>` : ""}</a>`;
}

/* ---------- Motivation: Level, Challenge, Abzeichen ---------- */

function levelHtml() {
  const m = S.motivation; if (!m) return "";
  const x = m.xp;
  return `<a class="card" href="#erfolge" style="display:block;text-decoration:none;color:inherit;padding:12px 16px">
    <div class="spread"><b>🌱 Level ${x.level} · ${esc(x.name)}</b><small>${num.format(x.points)} XP${m.streak > 1 ? ` · 🔥 ${m.streak} Tage` : ""} ›</small></div>
    <div class="progress"><i style="width:${(x.progress * 100).toFixed(1)}%"></i></div></a>`;
}

function challengeHtml() {
  const c = S.motivation && S.motivation.challenge; if (!c) return "";
  const left = Math.max(0, Math.round((new Date(c.ends + "T23:59:59") - Date.now()) / 86400e3));
  return `<div class="card" style="padding:12px 16px${c.done ? ";border-color:var(--good)" : ""}">
    <div class="spread"><b>${c.icon} ${esc(c.title)}</b><small>${c.done ? `✓ +${c.xp} XP` : `noch ${left} ${left === 1 ? "Tag" : "Tage"}`}</small></div>
    <div class="progress${c.done ? " good" : ""}"><i style="width:${c.progress / c.target * 100}%"></i></div>
    <div class="spread"><small class="muted">Wochen-Challenge · ${c.progress} von ${c.target} · zählt automatisch</small>
      ${c.done ? "" : `<button class="btn small" id="ch-skip">Andere</button>`}</div></div>`;
}
function bindChallenge() {
  $("#ch-skip") && ($("#ch-skip").onclick = async () => {
    try { S = await api("/api/challenge/skip", { method: "POST" }); } catch (e) { return toast(e.message); }
    viewToday();
  });
}

function viewAchievements() {
  const m = S.motivation, x = m.xp;
  view.innerHTML = `<div class="card hero"><div class="big-emoji">🌱</div>
      <h1>Level ${x.level} · ${esc(x.name)}</h1><p class="muted">${num.format(x.points)} XP · noch ${num.format(Math.max(0, x.high - x.points))} bis Level ${x.level + 1}</p>
      <div class="progress"><i style="width:${x.progress * 100}%"></i></div>
      <div class="tiles three mt"><div class="tile"><div class="v">🔥 ${m.streak}</div><div class="l">Tage in Folge</div></div>
        <div class="tile"><div class="v">${m.best_streak}</div><div class="l">längste Serie</div></div>
        <div class="tile"><div class="v">${m.challenges_done}</div><div class="l">Challenges geschafft</div></div></div></div>
    ${challengeHtml()}
    <div class="card"><h2>🏅 Abzeichen</h2><div class="badges">${m.badges.map(b => `<div class="badge${b.unlocked ? "" : " off"}" title="${esc(b.title)}">
      <span class="e">${b.icon}</span>${esc(b.title)}${b.unlocked ? `<small class="muted">${fmtDay(b.unlocked.slice(0, 10), { day: "2-digit", month: "2-digit" })}</small>`
        : `<div class="progress"><i style="width:${b.progress * 100}%"></i></div>`}</div>`).join("")}</div></div>
    <div class="card"><h2>So entstehen die XP</h2><ul class="list">${x.parts.map(p => `<li><div class="bd"><b>${esc(p.label)}</b><div class="meta">${num.format(p.count)} × ${p.each} XP</div></div><span class="val">${num.format(p.xp)}</span></li>`).join("")}</ul></div>`;
  bindChallenge();
}

/* Konfetti bei neuem Abzeichen, Level-Aufstieg und geschaffter Challenge */
function pendingCelebrations() {
  const m = S.motivation; if (!m) return [];
  const unlocked = m.badges.filter(b => b.unlocked).map(b => b.id);
  const ch = m.challenge && m.challenge.done ? `${m.challenge.week}:${m.challenge.id}` : null;
  const seen = store("fp_seen");
  const now = { unlocked, level: m.xp.level, challenges: ch ? [ch] : [] };
  if (!seen) { store("fp_seen", now); return []; }   // erster Start: nichts nachholen
  const out = [];
  unlocked.filter(id => !seen.unlocked.includes(id)).forEach(id => {
    const b = m.badges.find(x => x.id === id); out.push({ icon: b.icon, title: b.title, text: "Neues Abzeichen!" });
  });
  if (m.xp.level > (seen.level || 1)) out.push({ icon: "🌱", title: `Level ${m.xp.level}: ${m.xp.name}`, text: "Du kommst voran. Weiter so!" });
  if (ch && !(seen.challenges || []).includes(ch)) out.push({ icon: "🏁", title: "Challenge geschafft!", text: `${m.challenge.title} · +${m.challenge.xp} XP` });
  store("fp_seen", { unlocked, level: Math.max(now.level, seen.level || 1), challenges: [...new Set([...(seen.challenges || []), ...now.challenges])].slice(-30) });
  return out;
}
function celebrate(items) {
  if (!items.length || $(".celebrate")) return;
  const [it, ...rest] = items;
  const wrap = document.createElement("div");
  wrap.className = "celebrate";
  wrap.innerHTML = `<canvas></canvas><div class="celebrate-card"><div class="big-emoji">${it.icon}</div><h1>${esc(it.title)}</h1>
    <p class="muted">${esc(it.text)}</p><button class="btn primary block mt">Weiter</button></div>`;
  document.body.appendChild(wrap);
  vibrate([80, 50, 80, 50, 160]);
  const canvas = wrap.querySelector("canvas"), ctx = canvas.getContext("2d");
  const W = canvas.width = innerWidth * devicePixelRatio, H = canvas.height = innerHeight * devicePixelRatio;
  const colors = ["#ff8a3d", "#4ade80", "#fbbf24", "#f87171", "#60a5fa", "#a78bfa"];
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const parts = reduce ? [] : Array.from({ length: 160 }, () => ({
    x: W / 2 + (Math.random() - .5) * W * .2, y: H * .35, vx: (Math.random() - .5) * 26 * devicePixelRatio,
    vy: (-Math.random() * 22 - 6) * devicePixelRatio, s: (5 + Math.random() * 6) * devicePixelRatio,
    r: Math.random() * 6, vr: (Math.random() - .5) * .4, c: colors[Math.floor(Math.random() * colors.length)] }));
  let frame = 0, raf;
  const tick = () => {
    ctx.clearRect(0, 0, W, H);
    parts.forEach(p => {
      p.vy += .55 * devicePixelRatio; p.vx *= .99; p.x += p.vx; p.y += p.vy; p.r += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.fillStyle = p.c; ctx.fillRect(-p.s / 2, -p.s / 4, p.s, p.s / 2); ctx.restore();
    });
    if (++frame < 220) raf = requestAnimationFrame(tick);
  };
  if (parts.length) tick();
  wrap.querySelector("button").onclick = () => { cancelAnimationFrame(raf); wrap.remove(); celebrate(rest); };
}

/* ---------- Heißhunger-SOS ---------- */

const SOS_TIPS = ["Ein großes Glas Wasser trinken – Durst fühlt sich oft wie Hunger an.", "Zähne putzen: danach schmeckt Süßes kaum.",
  "Zehn Minuten raus an die Luft oder einmal um den Block.", "Einen Tee kochen und bewusst trinken.", "Jemanden anrufen oder eine Nachricht schreiben.",
  "Hände beschäftigen: aufräumen, abwaschen, ein Rätsel.", "Heißhunger ist eine Welle: Sie steigt, erreicht einen Gipfel und ebbt nach wenigen Minuten ab.",
  "Wenn doch etwas: Obst oder Gemüse kosten 0 Punkte."];

let swapCat = null;   // Lieber-Tausch-Katalog, einmal je Sitzung geladen

function swapVal(x) {
  return isPoints() ? (x.points ? `${x.points} P` : `<span class="zero">0 P</span>`) : `${x.kcal} kcal`;
}

function swapCard(c) {
  const P = isPoints(), o = S.overview, t = c.treat;
  const left = o.day === S.today ? (P ? o.week.today_left_points : o.week.today_left_kcal) : null;
  let hint = "";
  if (t && left != null) {
    const cost = P ? t.points : t.kcal, unit = P ? "P" : "kcal";
    hint = left >= cost ? `Du hast heute noch ${left} ${unit} – das passt rein. Langsam essen, ohne Handy oder Fernseher.`
      : `Du hast heute noch ${left} ${unit} – das wären ${cost - Math.max(left, 0)} ${unit} drüber (geht aus der Wochenreserve).`;
  }
  return `<div class="card" style="border-color:var(--accent)"><small class="muted">Lieber so – Lust auf ${esc(c.label)}</small>
    <ul class="list">${c.swaps.map(x => `<li class="tap" data-swap="${esc(x.key)}"><div class="bd"><b>${esc(x.name)}</b>
      <div class="meta">${esc(x.tip)}${x.uses ? ` · ${x.uses}× gewählt` : ""}</div></div><span class="val">${swapVal(x)}</span></li>`).join("")}</ul>
    <p class="note">Tippen = als Snack erfassen und Heißhunger als überstanden zählen.</p>
    ${t ? `<div class="spread mt"><div><b>Oder bewusst genießen:</b> ${esc(t.name)} = ${swapVal(t)}<div class="note">${hint}</div></div></div>
      <button class="btn block mt" id="sos-treat">🍫 Bewusst genießen und erfassen</button>` : ""}</div>`;
}

function openSOS() {
  const s = S.settings, triggers = s.craving_triggers || [];
  const id = uuid(), started = Date.now(), total = 600;
  let timer = null, trigger = null, intensity = 6, food = null;
  const save = async (resisted, swap = null) => {
    const body = { id, kind: "craving", trigger, intensity, resisted, food: food && food.key, swap, duration_s: Math.round((Date.now() - started) / 1000) };
    try { S = await api("/api/events", { method: "POST", body }); } catch (e) { toast(e.message); }
  };
  const logParts = async parts => {
    for (const p of parts) {
      if (!(await saveEntry({ id: uuid(), food_id: p.food_id, grams: p.grams, portion: p.portion, meal: "snack", day: S.today }))) return false;
    }
    lists = null;
    return true;
  };
  openSheet(`<h2>🍫 Heißhunger</h2>
    <p class="muted">Was ist gerade los?</p>
    ${chipGroup("trig", triggers.map(t => [t, esc(t)]), null)}
    <label class="f"><span>Wie stark? <b id="int-v">${intensity}</b> von 10</span><input type="range" min="1" max="10" value="${intensity}" id="int"></label>
    <div id="sos-plan"></div>
    <div id="sos-food"></div>
    <div id="sos-swap"></div>
    <div class="center"><div class="ring">${ringSvg(1, false)}<div class="t"><b id="sos-clock">10:00</b><span>Welle aussitzen</span></div></div></div>
    <p class="center" id="sos-tip">${esc(SOS_TIPS[0])}</p>
    <div class="row nowrap mt"><button class="btn grow" id="sos-ate">Doch gegessen</button><button class="btn primary grow" id="sos-ok">💪 Geschafft</button></div>
    <button class="btn block mt" data-close>Abbrechen (nichts speichern)</button>`, root => {
    const showPlan = () => {
      const plan = trigger && (s.plans || {})[trigger];
      $("#sos-plan", root).innerHTML = trigger ? (plan ? `<div class="card" style="border-color:var(--accent)"><small class="muted">Dein Plan bei ${esc(trigger)}</small><p><b>${esc(plan)}</b></p></div>`
        : `<p class="note">Noch kein Plan für ${esc(trigger)} – unter <b>Mehr → Wenn-Dann-Pläne</b> anlegen.</p>`) : "";
    };
    bindChips(root, (_, v) => { trigger = v; showPlan(); });
    const showFoods = () => {
      if (!swapCat || !swapCat.length) return;
      $("#sos-food", root).innerHTML = `<p class="muted">Worauf hast du Lust?</p><div class="chips">${swapCat.map(c =>
        `<button type="button" class="chip${food && food.key === c.key ? " on" : ""}" data-food="${esc(c.key)}">${c.emoji} ${esc(c.label)}</button>`).join("")}</div>`;
    };
    const showSwaps = () => {
      $("#sos-swap", root).innerHTML = food ? swapCard(food) : "";
      const tb = $("#sos-treat", root);
      tb && (tb.onclick = async () => {
        if (!(await logParts(food.treat.parts))) return;
        await save(false, "genuss"); closeSheet(); viewToday(); toast("Bewusst genießen – ist erfasst. Kein schlechtes Gewissen.");
      });
    };
    $("#sos-food", root).onclick = e => {
      const b = e.target.closest("[data-food]"); if (!b) return;
      food = food && food.key === b.dataset.food ? null : swapCat.find(c => c.key === b.dataset.food);
      showFoods(); showSwaps();
    };
    $("#sos-swap", root).onclick = async e => {
      const li = e.target.closest("[data-swap]"); if (!li || !food) return;
      const x = food.swaps.find(w => w.key === li.dataset.swap);
      if (!x || !(await logParts(x.parts))) return;
      await save(true, x.key); swapCat = null; closeSheet(); viewToday();
      toast(`Guter Tausch: ${x.name} erfasst. +15 XP 💪`); celebrate(pendingCelebrations());
    };
    if (swapCat) showFoods();
    else api("/api/swaps").then(c => { swapCat = c; showFoods(); }).catch(() => { /* offline: ohne Tausch-Vorschläge */ });
    $("#int", root).oninput = e => { intensity = +e.target.value; $("#int-v", root).textContent = intensity; };
    let tip = 0;
    timer = setInterval(() => {
      const left = Math.max(0, total - Math.round((Date.now() - started) / 1000));
      $("#sos-clock", root).textContent = `${pad(Math.floor(left / 60))}:${pad(left % 60)}`;
      $(".ring", root).firstElementChild.outerHTML = ringSvg(left / total, false);
      if ((total - left) % 30 === 0 && left < total) $("#sos-tip", root).textContent = SOS_TIPS[++tip % SOS_TIPS.length];
      if (!left) { clearInterval(timer); vibrate([100, 50, 100]); $("#sos-tip", root).textContent = "Zehn Minuten geschafft – die Welle ist vorbei. Wie geht's dir jetzt?"; }
    }, 1000);
    sheetCleanup = () => clearInterval(timer);
    $("#sos-ok", root).onclick = async () => { await save(true); swapCat = null; closeSheet(); viewToday(); toast("Stark! +15 XP 💪"); celebrate(pendingCelebrations()); };
    $("#sos-ate", root).onclick = async () => { await save(false); closeSheet(); viewToday(); toast("Kein Drama. Trag's ein, dann bleibt die Übersicht ehrlich."); openAdd("snack", food ? food.search : ""); };
  });
}

function plansHtml(s) {
  return (s.craving_triggers || []).map(t => `<div class="row nowrap" style="margin:6px 0"><label class="f grow" style="margin:0"><span>Wenn <b>${esc(t)}</b>, dann …</span>
    <input type="text" data-plan="${esc(t)}" value="${esc((s.plans || {})[t] || "")}" maxlength="200"></label>
    <button class="btn icon small-icon" data-rmtrig="${esc(t)}" aria-label="Auslöser entfernen" style="align-self:flex-end">✕</button></div>`).join("");
}
function bindPlans() {
  const collect = () => ({
    craving_triggers: $$("[data-plan]").map(i => i.dataset.plan),
    plans: Object.fromEntries($$("[data-plan]").map(i => [i.dataset.plan, i.value.trim()]).filter(([, v]) => v)),
  });
  const redraw = data => { $("#plans").innerHTML = plansHtml({ ...S.settings, ...data }); bindRm(); };
  const bindRm = () => $$("[data-rmtrig]").forEach(b => (b.onclick = () => {
    const c = collect(); c.craving_triggers = c.craving_triggers.filter(t => t !== b.dataset.rmtrig); delete c.plans[b.dataset.rmtrig]; redraw(c);
  }));
  bindRm();
  $("#add-trigger").onclick = () => {
    const t = $("#new-trigger").value.trim(); if (!t) return;
    const c = collect(); if (!c.craving_triggers.includes(t)) c.craving_triggers.push(t);
    $("#new-trigger").value = ""; redraw(c);
  };
  $("#plans-save").onclick = async () => {
    try { S = await api("/api/settings", { method: "PUT", body: collect() }); toast("Pläne gespeichert"); } catch (e) { toast(e.message); }
  };
}

/* ---------- Statistik: BMI und Heißhunger ---------- */

const BMI_CLASSES = [[0, 18.5, "Untergewicht", "var(--warn)"], [18.5, 25, "Normalgewicht", "var(--good)"], [25, 30, "Übergewicht", "var(--warn)"],
  [30, 35, "Adipositas Grad I", "var(--bad)"], [35, 40, "Adipositas Grad II", "var(--bad)"], [40, 99, "Adipositas Grad III", "var(--bad)"]];
function bmiClass(v) { return BMI_CLASSES.find(([lo, hi]) => v >= lo && v < hi) || BMI_CLASSES[BMI_CLASSES.length - 1]; }

function bmiHtml(weights) {
  const h = (S.settings.height_cm || 0) / 100, b = S.body;
  if (!h || !b || !b.bmi) return "";
  const bmi = b.bmi, goalBmi = b.goal ? b.goal / (h * h) : null, c = bmiClass(bmi);
  const pos = v => Math.max(0, Math.min(100, (v - 15) / 25 * 100));   // Skala 15 … 40
  const seg = BMI_CLASSES.filter(([lo]) => lo < 40).map(([lo, hi, , col]) => `<i style="left:${pos(Math.max(lo, 15))}%;width:${pos(Math.min(hi, 40)) - pos(Math.max(lo, 15))}%;background:${col}"></i>`).join("");
  const series = weights.map(w => ({ day: w.day, bmi: Math.round(w.trend / (h * h) * 10) / 10 }));
  const n25 = (25 * h * h).toFixed(1).replace(".", ",");
  return `<div class="card"><div class="card-head"><h2>📏 BMI</h2><small>Größe ${num.format(S.settings.height_cm)} cm</small></div>
    <div class="spread"><div><div style="font-size:2rem;font-weight:800">${num1.format(bmi)}</div><small style="color:${c[3]}">${c[2]}</small></div>
      ${goalBmi ? `<div style="text-align:right"><div style="font-size:1.2rem;font-weight:700">${num1.format(goalBmi)}</div><small class="muted">beim Zielgewicht ${num1.format(b.goal)} kg</small></div>` : ""}</div>
    <div class="bmi-scale">${seg}<b style="left:${pos(bmi)}%"></b>${goalBmi ? `<u style="left:${pos(goalBmi)}%"></u>` : ""}</div>
    <div class="spread note" style="font-size:.72rem"><span>15</span><span>18,5</span><span>25</span><span>30</span><span>35</span><span>40</span></div>
    ${series.length >= 2 ? chartBMI(series) : ""}
    <p class="note">Normalgewicht (BMI unter 25) beginnt bei deiner Größe unter ${n25} kg. Der BMI berücksichtigt keine Muskelmasse und ist nur ein grober Richtwert (Einteilung nach WHO).</p></div>`;
}

function chartBMI(series) {
  const W = 340, H = 120, P = 30;
  const vals = series.map(s => s.bmi);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1) { lo -= .5; hi += .5; }
  const t0 = new Date(series[0].day).getTime(), t1 = new Date(series[series.length - 1].day).getTime() || t0 + 1;
  const X = d => P + (new Date(d).getTime() - t0) / Math.max(t1 - t0, 1) * (W - P - 6), Y = v => 8 + (hi - v) / (hi - lo) * (H - 24);
  const path = series.map((s, i) => `${i ? "L" : "M"}${X(s.day).toFixed(1)},${Y(s.bmi).toFixed(1)}`).join("");
  const lines = [25, 30, 35].filter(v => v > lo && v < hi).map(v => `<line x1="${P}" x2="${W}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="var(--warn)" stroke-dasharray="4 3"/><text x="0" y="${(Y(v) + 3).toFixed(1)}">${v}</text>`).join("");
  return `<svg class="chart mt" viewBox="0 0 ${W} ${H}" role="img" aria-label="BMI-Verlauf">
    <text x="0" y="12">${num1.format(hi)}</text><text x="0" y="${H - 12}">${num1.format(lo)}</text>${lines}
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

function cravingHtml(c) {
  if (!c || !c.total) return `<div class="card"><div class="card-head"><h2>🍫 Heißhunger</h2></div>
    <p class="note">Noch kein Heißhunger erfasst. Wenn er kommt: oben auf <b>🍫 SOS</b> – Plan, 10-Minuten-Timer, und die App lernt deine kritischen Zeiten.</p></div>`;
  const rate = Math.round(c.resisted / c.total * 100);
  return `<div class="card"><div class="card-head"><h2>🍫 Heißhunger</h2><small>${c.resisted} von ${c.total} überstanden</small></div>
    <div class="progress good"><i style="width:${rate}%"></i></div><small>${rate} % ausgesessen</small>
    ${c.triggers.length ? `<ul class="list mt">${c.triggers.map(t => `<li><div class="bd"><b>${esc(t.trigger)}</b><div class="meta">${t.count}× · ${t.resisted} überstanden</div></div></li>`).join("")}</ul>` : ""}
    ${(c.foods || []).length ? `<p class="muted mt">Lust auf</p><ul class="list">${c.foods.map(f => `<li><div class="bd"><b>${f.emoji} ${esc(f.label)}</b><div class="meta">${f.count}× · ${f.swapped}× getauscht${f.best ? ` · am liebsten: ${esc(f.best)}` : ""}</div></div></li>`).join("")}</ul>` : ""}
    ${c.hours.length ? `<p class="note">Typische Zeiten: ${c.hours.map(h => `${h.hour}–${h.hour + 1} Uhr`).join(", ")}.${S.settings.snack_push ? " FitPath erinnert etwa 15 Minuten vorher." : ""}</p>` : ""}</div>`;
}

/* ---------- Erfassen: Suche ---------- */

let lists = null;
let addTab = "recent";

function openAdd(meal, query = "") {
  let timer = null, seq = 0;
  openSheet(`<div class="sheet-search">
      ${chipGroup("meal", MEALS.map(([k, l, i]) => [k, `${i} ${l}`]), meal, false, "scroll")}
      <div class="row nowrap" style="margin-top:8px"><input type="search" id="q" class="grow" placeholder="Lebensmittel suchen …" autocomplete="off" enterkeyhint="search">
        ${S.ai ? `<button class="btn icon" id="ai-text" aria-label="Per Text erfassen">✨</button>` : ""}
        <button class="btn icon" id="scan" aria-label="Barcode scannen">📷</button></div>
    </div>
    <div id="add-tabs"></div>
    <div id="results"></div>
    <div class="row nowrap mt"><button class="btn grow" id="recipe">🍲 Gericht anlegen</button><button class="btn grow" id="custom">✏️ Eigenes Lebensmittel</button></div>`, root => {
    const q = $("#q", root), res = $("#results", root);
    const curMeal = () => chipVal(root, "meal") || meal;
    bindChips(root);
    const showLists = async () => {
      $("#add-tabs", root).innerHTML = `<div class="tabs">${[["recent", "Zuletzt"], ["favorites", "Favoriten"], ["meals", "⭐ Mahlzeiten"], ["custom", "Eigene"], ["eatout", "🍽️ Auswärts"]]
        .map(([k, l]) => `<button data-t="${k}" class="${addTab === k ? "on" : ""}">${l}</button>`).join("")}</div>`;
      $$("[data-t]", root).forEach(b => (b.onclick = () => { addTab = b.dataset.t; showLists(); }));
      if (!lists) {
        res.innerHTML = `<div class="empty">Lade …</div>`;
        try { lists = await api("/api/foods/lists"); } catch (_) { res.innerHTML = `<div class="empty">Offline – Suche geht nur mit Verbindung.</div>`; return; }
      }
      const items = lists[addTab] || [];
      if (addTab === "eatout") { res.innerHTML = eatoutList(items); return; }
      if (addTab === "meals") {
        const t = S.templates || [];
        res.innerHTML = t.length ? `<ul class="list">${t.map(x => `<li class="tap" data-tpl-open="${esc(x.id)}"><span style="font-size:1.3rem">⭐</span>
          <div class="bd"><b>${esc(x.name)}</b><div class="meta">${esc(x.items.map(i => shortName(i.name)).join(", "))}</div></div>
          <span class="val">${fmtVal(x.points, x.kcal)}</span></li>`).join("")}</ul>`
          : `<div class="empty">Noch keine Mahlzeiten gemerkt. Auf Heute bei einer Mahlzeit mit Einträgen auf ☆ tippen.</div>`;
        return;
      }
      res.innerHTML = items.length ? foodList(items) : `<div class="empty">${addTab === "recent" ? "Noch nichts gegessen – such oben nach einem Lebensmittel." :
        addTab === "favorites" ? "Noch keine Favoriten. Tipp beim Erfassen auf ☆." : "Noch keine eigenen Lebensmittel oder gescannten Produkte."}</div>`;
    };
    const runSearch = async () => {
      const term = q.value.trim(), my = ++seq;
      if (!term) { showLists(); return; }
      $("#add-tabs", root).innerHTML = "";
      try {
        const hits = await api(`/api/foods/search?q=${encodeURIComponent(term)}`);
        if (my !== seq) return;
        res._hits = hits;
        res.innerHTML = hits.length ? foodList(hits) : `<div class="empty">Nichts gefunden. Anders schreiben, scannen oder eigenes anlegen.</div>`;
      } catch (_) { res.innerHTML = `<div class="empty">Offline – Suche geht nur mit Verbindung.</div>`; }
    };
    q.oninput = () => { clearTimeout(timer); timer = setTimeout(runSearch, 180); };
    res.onclick = async e => {
      const tp = e.target.closest("[data-tpl-open]");
      if (tp) { const t = (S.templates || []).find(x => x.id === tp.dataset.tplOpen); return t && openTemplate(t, curMeal()); }
      const li = e.target.closest("[data-food]"); if (!li) return;
      const all = [...(lists ? [...lists.recent, ...lists.favorites, ...lists.custom, ...(lists.eatout || [])] : [])];
      let food = all.find(f => f.id === +li.dataset.food) || (res._hits || []).find(f => f.id === +li.dataset.food);
      if (!food) { try { food = await api(`/api/foods/${li.dataset.food}`); } catch (err) { return toast(err.message); } }
      openAmount(food, curMeal());
    };
    $("#scan", root).onclick = () => openScan(curMeal());
    $("#ai-text", root) && ($("#ai-text", root).onclick = () => openTextEntry(curMeal(), q.value.trim()));
    $("#recipe", root).onclick = () => openRecipe(null, curMeal());
    $("#custom", root).onclick = () => openCustom({ name: q.value.trim() }, curMeal());
    if (query) { q.value = query; runSearch(); } else showLists();
    setTimeout(() => q.focus(), 250);
  }, true);
}

/* Auswärts: Teller nach Gruppe, mit kcal und Punkten der normalen Größe */
function eatoutList(items) {
  if (!items.length) return `<div class="empty">Keine Teller vorhanden.</div>`;
  const P = isPoints();
  let html = "", group = null;
  for (const f of items) {
    if (f.group !== group) { if (group !== null) html += "</ul>"; group = f.group; html += `<h3 class="muted" style="margin:12px 0 4px">${esc(group)}</h3><ul class="list">`; }
    html += `<li class="tap" data-food="${f.id}"><span class="dot ${f.ampel}"></span>
      <div class="bd"><b>${f.fav ? "★ " : ""}${esc(f.name)}</b><div class="meta">normal ${num.format(f.normal_g)} g · ${num.format(f.normal_kcal)} kcal</div></div>
      <span class="val">${P ? `${f.normal_points} P` : `${num.format(f.normal_kcal)} kcal`}</span></li>`;
  }
  return html + `</ul><p class="note">Aus BLS-Bausteinen zusammengesetzt, Pfannengerichte mit Fettzuschlag. Echte Portionen schwanken stark.</p>`;
}

function foodList(items) {
  return `<ul class="list">${items.map(f => `<li class="tap" data-food="${f.id}"><span class="dot ${f.ampel}"></span>
    <div class="bd"><b>${f.fav ? "★ " : ""}${esc(f.name)}</b><div class="meta">${f.brand ? esc(f.brand) + " · " : ""}${Math.round(f.kcal || 0)} kcal/100 g${f.source === "off" ? " · 📦" : f.source === "custom" ? " · ✏️" : f.source === "recipe" ? " · 🍲 Gericht" : f.source === "eatout" ? " · 🍽️" : ""}</div></div>
    <span class="val">${f.zero ? `<span class="zero">0 P</span>` : isPoints() ? `${f.points_100} P` : ""}<div class="meta" style="font-weight:400">${f.last_grams ? fmtG(f.last_grams) : "je 100 g"}</div></span></li>`).join("")}</ul>`;
}

/* ---------- Erfassen: Menge ---------- */

function openAmount(food, meal, entry = null, back = null) {
  const portions = [...(food.portions || [])];
  const def = portions[food.source === "eatout" && portions[1] ? 1 : 0];   // Teller: „normal“ statt „klein“
  let grams = entry ? entry.grams : (food.last_grams || (def ? def.g : 100));
  let portion = entry ? entry.portion : (food.last_grams ? food.last_portion : (def ? def.name : null));
  let count = 1;
  const multi = portion && /^(\d+(?:,5)?)× (.+)$/.exec(portion);
  if (multi) { count = parseNum(multi[1]); portion = multi[2]; }
  if (portion && !portions.some(p => p.name === portion)) portion = null;
  const src = { bls: "BLS 4.0", off: "Open Food Facts", custom: "Eigenes", recipe: "Gericht", eatout: "🍽️ Auswärts" }[food.source] || "";

  openSheet(`${back ? `<button class="linkbtn" id="back" style="margin-bottom:6px">‹ Zurück zum Einkauf</button>` : ""}
    <div class="spread"><h2 style="margin:0">${esc(food.name)}</h2>
      <button class="btn icon small-icon" id="fav" aria-label="Favorit">${food.fav ? "★" : "☆"}</button></div>
    <div class="row" style="margin-top:4px"><span class="pill">${esc(src)}</span>${food.brand ? `<span class="pill">${esc(food.brand)}</span>` : ""}
      <span class="pill"><span class="dot ${food.ampel}"></span>${AMPEL_LABEL[food.ampel]}</span>${food.zero ? `<span class="pill good">0 Punkte</span>` : ""}</div>
    <div class="amount-preview"><div class="big" id="pv"></div><small id="pv2"></small></div>
    <div class="nutr" id="nutr"></div>
    ${portions.length ? `<div class="chips" id="portions">${portions.map((p, i) => `<button class="chip" data-p="${i}">${esc(p.name)}</button>`).join("")}
      <button class="chip" data-p="g">Gramm</button></div>` : ""}
    <div class="row nowrap mt">
      <div class="stepper" id="stepper" ${portion ? "" : "hidden"}><button class="btn icon small-icon" id="minus">−</button><b id="cnt">${num1.format(count)}</b><button class="btn icon small-icon" id="plus">+</button></div>
      <label class="grow" style="display:block">${decField('class="big" id="grams"', numIn.format(grams))}</label>
      <span class="muted">g</span></div>
    ${chipGroup("meal", MEALS.map(([k, l, i]) => [k, `${i} ${l}`]), entry ? entry.meal : meal, false, "scroll mt")}
    <div class="why" id="why"></div>
    ${food.source === "eatout" ? `<p class="note">Restaurant-Portionen sind oft größer und fetter als gedacht. Im Zweifel die größere Portion nehmen.</p>` : ""}
    <div class="row nowrap mt">${entry ? `<button class="btn danger" id="del">Löschen</button>` : ""}<button class="btn primary grow" id="save">${entry ? "Speichern" : "Erfassen"}</button></div>
    <details class="more mt"><summary>Mehr zu diesem Lebensmittel</summary>
      <label class="switch"><span>Zählt 0 Punkte</span><input type="checkbox" id="zero" ${food.zero ? "checked" : ""}></label>
      <div class="row nowrap"><input type="text" id="pname" placeholder="Eigene Portion, z. B. „Mein Becher“" class="grow"><button class="btn small" id="psave">Portion merken</button></div>
      ${food.source === "custom" || food.source === "off" ? `<button class="btn block mt" id="edit">Nährwerte bearbeiten</button>` : ""}
      ${food.source === "recipe" ? `<button class="btn block mt" id="edit-recipe">🍲 Gericht bearbeiten</button>` : ""}
      ${food.source === "eatout" ? `<div id="eatout-parts" class="mt"></div>` : ""}
      <p class="note">Je 100 g: ${Math.round(food.kcal || 0)} kcal · Eiweiß ${num1.format(food.protein || 0)} g · Fett ${num1.format(food.fat || 0)} g (ges. ${num1.format(food.satfat || 0)} g) · KH ${num1.format(food.carbs || 0)} g · Zucker ${num1.format(food.sugar || 0)} g · Ballaststoffe ${num1.format(food.fiber || 0)} g${food.alcohol ? ` · Alkohol ${num1.format(food.alcohol)} g` : ""}${food.code && food.source === "bls" ? ` · BLS ${esc(food.code)}` : ""}</p>
    </details>`, root => {
    const gi = $("#grams", root);
    if (food.source === "eatout") {
      // Zusammensetzung der normalen Größe nachladen (steht nicht in den Listen)
      api(`/api/foods/${food.id}`).then(f => {
        const r = f.eatout, el = $("#eatout-parts", root);
        if (!r || !el) return;
        el.innerHTML = `<small class="muted">So setzt sich „normal“ (${num.format(r.total_g)} g) zusammen:</small><ul class="list">${r.items.map(it =>
          `<li><div class="bd"><b>${it.fat_extra ? "Fettzuschlag (Restaurant): " : ""}${esc(it.name)}</b></div><span class="val">${num.format(it.grams)} g</span></li>`).join("")}</ul>`;
      }).catch(() => {});
    }
    const markPortion = () => $$("#portions .chip", root).forEach(c => c.classList.toggle("on",
      c.dataset.p === "g" ? !portion : portions[+c.dataset.p] && portions[+c.dataset.p].name === portion));
    const update = () => {
      grams = parseNum(gi.value) || 0;
      const n = scaleFood(food, grams), p = pointsFor(food, grams);
      $("#pv", root).textContent = isPoints() ? `${p} P` : `${Math.round(n.kcal)} kcal`;
      $("#pv2", root).textContent = isPoints() ? `${Math.round(n.kcal)} kcal` : (food.zero ? "0 Punkte" : `${p} Punkte`);
      $("#nutr", root).innerHTML = [["Eiweiß", n.protein], ["Fett", n.fat], ["KH", n.carbs], ["Zucker", n.sugar], ["Ballast.", n.fiber]]
        .map(([l, v]) => `<div><b>${num1.format(v)}</b>${l}</div>`).join("");
      $("#why", root).innerHTML = food.zero ? "0-Punkte-Lebensmittel: frisches Obst und Gemüse zählen nicht." :
        food.pts_100 != null ? "Gericht: Punkte aus den Zutaten, 0-Punkte-Zutaten (Gemüse, Obst) zählen nicht mit." :
        `So entstehen die Punkte: ${num1.format(n.kcal / F.kcal)} (kcal) + ${num1.format(n.satfat / F.satfat)} (ges. Fett) + ${num1.format(n.sugar / F.sugar)} (Zucker)${n.alcohol ? ` + ${num1.format(n.alcohol / F.alcohol)} (Alkohol)` : ""} − ${num1.format(n.protein / F.protein)} (Eiweiß) − ${num1.format(n.fiber / F.fiber)} (Ballaststoffe)`;
      $("#save", root).disabled = !(grams > 0 && grams <= 5000);
    };
    const setPortion = (p, c = count) => {
      portion = p ? p.name : null; count = Math.min(Math.max(0.5, c), 50);   // halbe Schritte
      $("#stepper", root).hidden = !p; $("#cnt", root).textContent = num1.format(count);
      if (p) gi.value = numIn.format(Math.round(p.g * count * 10) / 10);
      markPortion(); update();
    };
    markPortion(); update(); bindChips(root);
    $("#portions") && ($("#portions").onclick = e => {
      const c = e.target.closest("[data-p]"); if (!c) return;
      if (c.dataset.p === "g") { setPortion(null); gi.focus(); gi.select(); } else setPortion(portions[+c.dataset.p], 1);
    });
    $("#minus", root).onclick = () => { const p = portions.find(x => x.name === portion); if (p) setPortion(p, count - 0.5); };
    $("#plus", root).onclick = () => { const p = portions.find(x => x.name === portion); if (p) setPortion(p, count + 0.5); };
    gi.oninput = () => { if (portion) { portion = null; $("#stepper", root).hidden = true; markPortion(); } update(); };
    $("#save", root).onclick = async () => {
      const label = portion ? (count !== 1 ? `${num1.format(count)}× ${portion}` : portion) : null;
      const e = { id: entry ? entry.id : uuid(), food_id: food.id, grams, portion: label, meal: chipVal(root, "meal") || meal, day: entry ? entry.day : (curDay || S.today) };
      if (!(await saveEntry(e))) return;
      vibrate(30); lists = null;
      closeSheet(); viewToday();
      toast(entry ? "Gespeichert" : `${shortName(food.name)} erfasst`);
      if (back) back();
    };
    $("#del", root) && ($("#del", root).onclick = async () => {
      try { await deleteEntry(entry.id); } catch (err) { return toast(err.message); }
      closeSheet(); viewToday();
      toast("Gelöscht", 6000, [{ label: "Rückgängig", fn: async () => { await saveEntry({ ...entry, portion: entry.portion }); viewToday(); } }]);
    });
    $("#back", root) && ($("#back", root).onclick = back);
    $("#fav", root).onclick = async () => {
      try { const f = await api(`/api/foods/${food.id}`, { method: "PUT", body: { fav: !food.fav } }); food.fav = f.fav; lists = null; }
      catch (err) { return toast(err.message); }
      $("#fav", root).textContent = food.fav ? "★" : "☆"; toast(food.fav ? "Als Favorit gemerkt" : "Favorit entfernt");
    };
    $("#zero", root).onchange = async ev => {
      try { const f = await api(`/api/foods/${food.id}`, { method: "PUT", body: { zero: ev.target.checked } }); food.zero = f.zero; update(); }
      catch (err) { toast(err.message); }
    };
    $("#psave", root).onclick = async () => {
      const name = $("#pname", root).value.trim();
      if (!name || !(grams > 0)) return toast("Name und Menge angeben");
      const own = (food.portions || []).filter(p => p.name !== name).slice(0, 3);
      try { const f = await api(`/api/foods/${food.id}`, { method: "PUT", body: { portions: [{ name, g: grams }, ...own] } }); food.portions = f.portions; }
      catch (err) { return toast(err.message); }
      toast("Portion gemerkt"); openAmount(food, chipVal(root, "meal") || meal, entry, back);
    };
    $("#edit", root) && ($("#edit", root).onclick = () => openCustom(food, chipVal(root, "meal") || meal));
    $("#edit-recipe", root) && ($("#edit-recipe", root).onclick = async () => {
      try { openRecipe(await api(`/api/recipes/${food.id}`), chipVal(root, "meal") || meal); } catch (e) { toast(e.message); }
    });
  });
}

async function openEntry(e) {
  let food = null;
  if (e.food_id) { try { food = await api(`/api/foods/${e.food_id}`); } catch (_) { /* offline */ } }
  if (!food) return toast("Offline – Bearbeiten geht nur mit Verbindung");
  openAmount(food, e.meal, e);
}

/* ---------- Gericht aus Zutaten ---------- */

function openRecipe(rec, meal, done = null) {
  const items = rec ? rec.recipe.items.map(i => ({ ...i })) : [];
  const cache = {};   // food_id -> Lebensmittel (für die Vorschau)
  let servings = rec ? rec.recipe.servings : 2, timer = null, seq = 0;
  openSheet(`<h2>🍲 ${rec ? "Gericht bearbeiten" : "Gericht anlegen"}</h2>
    ${rec ? "" : `<div class="row nowrap"><input type="url" id="r-link" class="grow" placeholder="🔗 Rezept-Link (Cookidoo, Chefkoch …)" autocomplete="off">
      <button class="btn small" id="r-import">Holen</button></div><p class="note">Oder von Hand: Zutaten unten suchen und antippen.</p>`}
    <label class="f"><span>Name</span><input type="text" id="r-name" maxlength="120" value="${esc(rec ? rec.name : "")}" placeholder="z. B. Chili con Carne"></label>
    <div class="grid2"><label class="f"><span>Portionen</span>
      <div class="stepper"><button class="btn icon small-icon" id="r-minus">−</button><b id="r-serv">${num1.format(servings)}</b><button class="btn icon small-icon" id="r-plus">+</button></div></label>
      <label class="f"><span>Gewicht fertig (g, optional)</span>${decField('id="r-total" placeholder="Summe der Zutaten"', rec && rec.recipe.total_g ? numIn.format(rec.recipe.total_g) : "")}</label></div>
    <h3 class="mt">Zutaten</h3>
    <ul class="list" id="r-items"></ul>
    <input type="search" id="r-q" placeholder="Zutat suchen und antippen …" autocomplete="off">
    <div id="r-hits"></div>
    <div class="card" id="r-sum" style="text-align:center"></div>
    <p class="note">Gemüse und Obst bleiben auch im Gericht 0 Punkte. „Gewicht fertig“ nur angeben, wenn du den Topf wiegst – dann stimmen die Portionen auch bei verkochtem Wasser.</p>
    <div class="row nowrap mt">${rec ? `<button class="btn danger" id="r-del">Löschen</button>` : ""}<button class="btn primary grow" id="r-save">Speichern</button></div>`, root => {
    const draw = () => {
      $("#r-items", root).innerHTML = items.length ? items.map((it, i) => `<li><div class="bd"><b>${esc(it.name)}</b></div>
        ${decField(`data-g="${i}" style="width:92px;flex:none;text-align:right"`, numIn.format(it.grams))}<span class="muted">g</span>
        <button class="btn icon small-icon" data-rm="${i}" aria-label="Entfernen">✕</button></li>`).join("") : `<li><div class="bd muted">Noch keine Zutaten.</div></li>`;
      $$("[data-g]", root).forEach(inp => (inp.oninput = () => { items[+inp.dataset.g].grams = parseNum(inp.value) || 0; summary(); }));
      $$("[data-rm]", root).forEach(b => (b.onclick = () => { items.splice(+b.dataset.rm, 1); draw(); }));
      summary();
    };
    const summary = () => {
      const raw = items.reduce((a, it) => a + (it.grams || 0), 0);
      const total = parseNum($("#r-total", root).value) || raw;
      let kcal = 0, pts = 0, known = true;
      for (const it of items) {
        const f = cache[it.food_id];
        if (!f) { known = false; continue; }
        const n = scaleFood(f, it.grams || 0);
        kcal += n.kcal; if (!f.zero) pts += rawPoints(n);
      }
      $("#r-serv", root).textContent = num1.format(servings);
      $("#r-sum", root).innerHTML = items.length ? `<small class="muted">Pro Portion (${num.format(Math.round(total / servings))} g)</small>
        <div style="font-size:1.8rem;font-weight:800">${known ? (isPoints() ? `${Math.floor(pts / servings + 0.5)} P` : `${Math.round(kcal / servings)} kcal`) : "…"}</div>
        <small>${known ? `${Math.round(kcal / servings)} kcal · ganzes Gericht ${num.format(Math.round(kcal))} kcal` : "wird nach dem Speichern berechnet"}</small>` : `<small class="muted">Zutaten hinzufügen</small>`;
    };
    // Zutaten eines vorhandenen Gerichts für die Vorschau laden
    Promise.all(items.map(it => api(`/api/foods/${it.food_id}`).then(f => (cache[f.id] = f)).catch(() => null))).then(summary);
    $("#r-import", root) && ($("#r-import", root).onclick = async () => {
      const url = $("#r-link", root).value.trim();
      if (!url) return toast("Link einfügen, z. B. aus Cookidoo über „Teilen“");
      const btn = $("#r-import", root); btn.disabled = true; btn.textContent = "Lese …";
      try { openRecipeImport(await api("/api/recipes/import", { method: "POST", body: { url } }), meal); }
      catch (e) { toast(e.message); btn.disabled = false; btn.textContent = "Holen"; }
    });
    $("#r-minus", root).onclick = () => { servings = Math.max(0.5, servings - 0.5); summary(); };
    $("#r-plus", root).onclick = () => { servings = Math.min(50, servings + 0.5); summary(); };
    $("#r-total", root).oninput = summary;
    $("#r-q", root).oninput = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const term = $("#r-q", root).value.trim(), my = ++seq;
        if (!term) { $("#r-hits", root).innerHTML = ""; return; }
        try {
          const hits = (await api(`/api/foods/search?q=${encodeURIComponent(term)}`)).filter(h => h.source !== "recipe" && h.source !== "eatout").slice(0, 8);
          if (my !== seq) return;
          hits.forEach(h => (cache[h.id] = h));
          $("#r-hits", root).innerHTML = hits.length ? foodList(hits) : `<div class="empty">Nichts gefunden.</div>`;
        } catch (_) { $("#r-hits", root).innerHTML = `<div class="empty">Offline</div>`; }
      }, 180);
    };
    $("#r-hits", root).onclick = e => {
      const li = e.target.closest("[data-food]"); if (!li) return;
      const f = cache[+li.dataset.food];
      const g = f.portions && f.portions[0] ? f.portions[0].g : 100;
      items.push({ food_id: f.id, name: f.name, grams: g });
      $("#r-q", root).value = ""; $("#r-hits", root).innerHTML = "";
      draw(); vibrate(20);
    };
    $("#r-save", root).onclick = async () => {
      const body = { name: $("#r-name", root).value.trim(), servings, total_g: parseNum($("#r-total", root).value),
                     items: items.map(it => ({ food_id: it.food_id, grams: it.grams })) };
      if (!body.name) return toast("Name fehlt");
      if (!items.length) return toast("Mindestens eine Zutat");
      try {
        const f = rec ? await api(`/api/recipes/${rec.id}`, { method: "PUT", body }) : await api("/api/recipes", { method: "POST", body });
        lists = null; toast("Gericht gespeichert"); done ? done() : openAmount(f, meal);
      } catch (e) { toast(e.message); }
    };
    $("#r-del", root) && ($("#r-del", root).onclick = async () => {
      if (!confirm("Gericht löschen? Bereits erfasste Einträge bleiben.")) return;
      let r;
      try { r = await api(`/api/foods/${rec.id}`, { method: "DELETE" }); } catch (e) { return toast(e.message); }
      lists = null; done ? done() : closeSheet(); toast(`Gericht ${r.result}`);
    });
    draw();
  }, true);
}

/* ---------- Rezept-Import per Link ---------- */

function openRecipeImport(prop, meal) {
  const items = prop.items.map(it => ({ ...it, pick: 0 }));
  let servings = prop.servings;
  const host = (() => { try { return new URL(prop.url).hostname.replace(/^www\./, ""); } catch (_) { return "Rezeptseite"; } })();
  openSheet(`<h2>🔗 Rezept übernehmen</h2>
    <p class="note">Von ${esc(host)}. Prüf kurz die Zuordnung – jede Zutat wird ein Lebensmittel aus der Datenbank, damit Zucker, Fett und 0-Punkte-Gemüse stimmen.</p>
    <label class="f"><span>Name</span><input type="text" id="i-name" maxlength="120" value="${esc(prop.name)}"></label>
    <div class="grid2"><label class="f"><span>Portionen${prop.servings_known ? "" : " (bitte prüfen)"}</span>
      <div class="stepper"><button class="btn icon small-icon" id="i-minus">−</button><b id="i-serv">${num1.format(servings)}</b><button class="btn icon small-icon" id="i-plus">+</button></div></label>
      <label class="f"><span>Gewicht fertig (g, optional)</span>${decField('id="i-total" placeholder="Summe der Zutaten"', prop.total_g ? numIn.format(prop.total_g) : "")}</label></div>
    <ul class="list" id="i-items"></ul>
    <div class="card" id="i-sum" style="text-align:center"></div>
    <button class="btn primary block" id="i-save">Als Gericht speichern</button>
    ${prop.nutrition && prop.nutrition.kcal ? `<button class="btn block mt" id="i-simple">Nur die Werte von ${esc(host)} übernehmen</button>
      <p class="note">Dann fehlen meist Zucker und gesättigtes Fett, die Punkte fallen etwas zu niedrig aus, und Gemüse zählt mit.</p>` : ""}`, root => {
    const food = it => it.candidates[it.pick];
    const draw = () => {
      $("#i-items", root).innerHTML = items.map((it, i) => `<li style="flex-wrap:wrap">
        <input type="checkbox" data-use="${i}" ${it.use ? "checked" : ""} ${it.candidates.length ? "" : "disabled"} style="width:22px;height:22px;accent-color:var(--accent);flex:none">
        <div class="bd"><div class="meta">${esc(it.line)}</div>
          ${it.candidates.length ? `<select data-pick="${i}" style="margin-top:4px">${it.candidates.map((c, k) => `<option value="${k}" ${k === it.pick ? "selected" : ""}>${esc(c.name)} · ${Math.round(c.kcal || 0)} kcal/100 g${c.zero ? " · 0 P" : ""}</option>`).join("")}</select>`
            : `<div class="meta" style="color:var(--warn)">Kein Treffer für „${esc(it.search)}“</div>`}</div>
        ${decField(`data-g="${i}" style="width:80px;flex:none;text-align:right"`, numIn.format(it.grams))}<span class="muted">g</span>
        <button class="btn icon small-icon" data-find="${i}" aria-label="Anders suchen">🔎</button></li>`).join("");
      summary();
    };
    const summary = () => {
      const used = items.filter(it => it.use && it.candidates.length);
      let kcal = 0, pts = 0;
      used.forEach(it => { const f = food(it), n = scaleFood(f, it.grams || 0); kcal += n.kcal; if (!f.zero) pts += rawPoints(n); });
      $("#i-serv", root).textContent = num1.format(servings);
      const site = prop.nutrition && prop.nutrition.kcal ? (prop.nutrition_scope === "total" ? prop.nutrition.kcal / servings : prop.nutrition.kcal) : null;
      const ours = kcal / servings, diff = site ? Math.round((ours - site) / site * 100) : null;
      $("#i-sum", root).innerHTML = `<small class="muted">Pro Portion</small>
        <div style="font-size:1.8rem;font-weight:800">${isPoints() ? `${Math.floor(pts / servings + .5)} P` : `${Math.round(ours)} kcal`}</div>
        <small>${Math.round(ours)} kcal laut Zuordnung${site ? ` · ${Math.round(site)} kcal laut ${esc(host)} (${diff > 0 ? "+" : ""}${diff} %)` : ""}</small>
        ${site && Math.abs(diff) > 25 ? `<p class="note" style="color:var(--warn)">Größere Abweichung – Mengen oder Portionen prüfen.</p>` : ""}`;
    };
    root.addEventListener("change", e => {
      const t = e.target;
      if (t.dataset.use) { items[+t.dataset.use].use = t.checked; summary(); }
      if (t.dataset.pick) { items[+t.dataset.pick].pick = +t.value; summary(); }
    });
    root.addEventListener("input", e => {
      const t = e.target;
      if (t.dataset.g) { items[+t.dataset.g].grams = parseNum(t.value) || 0; summary(); }
      if (t.id === "i-total") summary();
    });
    root.addEventListener("click", async e => {
      const b = e.target.closest("[data-find]"); if (!b) return;
      const it = items[+b.dataset.find];
      const term = (prompt("Suchbegriff für diese Zutat:", it.search) || "").trim(); if (!term) return;
      try { it.candidates = (await api(`/api/foods/search?q=${encodeURIComponent(term)}`)).filter(h => h.source !== "recipe" && h.source !== "eatout").slice(0, 5); }
      catch (err) { return toast(err.message); }
      it.search = term; it.pick = 0; it.use = it.candidates.length > 0; draw();
    });
    $("#i-minus", root).onclick = () => { servings = Math.max(0.5, servings - 0.5); summary(); };
    $("#i-plus", root).onclick = () => { servings = Math.min(50, servings + 0.5); summary(); };
    $("#i-save", root).onclick = async () => {
      const used = items.filter(it => it.use && it.candidates.length && it.grams > 0);
      if (!used.length) return toast("Mindestens eine Zutat auswählen");
      const body = { name: $("#i-name", root).value.trim() || prop.name, servings, total_g: parseNum($("#i-total", root).value),
                     source_url: prop.url, items: used.map(it => ({ food_id: food(it).id, grams: it.grams })) };
      try { const f = await api("/api/recipes", { method: "POST", body }); lists = null; toast("Gericht gespeichert"); openAmount(f, meal); }
      catch (err) { toast(err.message); }
    };
    $("#i-simple", root) && ($("#i-simple", root).onclick = async () => {
      // Werte der Seite: bei bekanntem Gesamtgewicht echt je 100 g, sonst 1 Portion = 100 g als Rechengröße
      const n = prop.nutrition, total = parseNum($("#i-total", root).value);
      const whole = k => (n[k] || 0) * (prop.nutrition_scope === "total" ? 1 : servings);
      const per100 = k => total ? whole(k) / total * 100 : whole(k) / servings;
      const body = { name: `${$("#i-name", root).value.trim() || prop.name} (Werte ${host})`, serving_g: total ? total / servings : 100 };
      ["kcal", "protein", "fat", "satfat", "carbs", "sugar", "fiber"].forEach(k => { if (n[k] != null) body[k] = Math.round(per100(k) * 10) / 10; });
      try { const f = await api("/api/foods", { method: "POST", body }); lists = null; toast("Übernommen"); openAmount(f, meal); }
      catch (err) { toast(err.message); }
    });
    draw();
  }, true);
}

/* ---------- Erfassen per Text (KI) ---------- */

function openTextEntry(meal, preset = "") {
  openSheet(`<h2>✨ Per Text erfassen</h2>
    <label class="f"><span>Was hast du gegessen oder getrunken?</span>
      <textarea id="t-text" maxlength="500" placeholder="z. B. 2 Brötchen mit Butter und Gouda, Kaffee mit Milch">${esc(preset)}</textarea></label>
    <button class="btn primary block" id="t-go">Vorschläge holen</button>
    <p class="note">Nur dieser Text geht an die KI (über LiteLLM), sonst nichts aus FitPath. Erfasst wird erst nach deiner Bestätigung.</p>
    <div id="t-out"></div>`, root => {
    const go = async () => {
      const text = $("#t-text", root).value.trim();
      if (text.length < 3) return toast("Bitte kurz beschreiben");
      const btn = $("#t-go", root); btn.disabled = true; btn.textContent = "KI denkt nach …";
      let d;
      try { d = await api("/api/ai/parse", { method: "POST", body: { text } }); }
      catch (e) { btn.disabled = false; btn.textContent = "Vorschläge holen"; return toast(e.message); }
      btn.disabled = false; btn.textContent = "Neu vorschlagen";
      showProposals(root, d, d.meal || meal);
    };
    $("#t-go", root).onclick = go;
    setTimeout(() => $("#t-text", root).focus(), 250);
  }, true);
}

function showProposals(root, d, meal) {
  const out = $("#t-out", root);
  if (!d.items.length) { out.innerHTML = `<div class="empty">Nichts erkannt – anders formulieren.</div>`; return; }
  out.innerHTML = `${chipGroup("t-meal", MEALS.map(([k, l, i]) => [k, `${i} ${l}`]), meal, false, "scroll mt")}
    <ul class="list">${d.items.map((it, i) => `<li style="flex-wrap:wrap">
      <input type="checkbox" data-on="${i}" ${it.candidates.length ? "checked" : "disabled"} style="width:22px;height:22px;accent-color:var(--accent);flex:none">
      <div class="bd"><b>${esc(it.label)}</b>
        ${it.candidates.length ? `<select data-c="${i}" style="margin-top:6px">${it.candidates.map((c, k) =>
          `<option value="${k}">${esc(c.name)}${c.brand ? " (" + esc(c.brand) + ")" : ""} · ${c.zero ? "0 P" : isPoints() ? c.points_100 + " P" : Math.round(c.kcal) + " kcal"}/100 g</option>`).join("")}</select>`
          : `<div class="meta">Nichts Passendes gefunden („${esc(it.search)}“) – bitte über die Suche erfassen.</div>`}</div>
      ${it.candidates.length ? `${decField(`data-gr="${i}" style="width:84px;flex:none;text-align:right"`, numIn.format(it.grams))}<span class="muted">g</span>
        <span class="val" data-pv="${i}"></span>` : ""}</li>`).join("")}</ul>
    <div class="card" style="text-align:center"><small class="muted">Zusammen</small><div style="font-size:1.6rem;font-weight:800" id="t-sum"></div></div>
    <button class="btn primary block" id="t-save">Erfassen</button>`;
  bindChips(out);
  const pick = i => d.items[i].candidates[+($(`[data-c="${i}"]`, out) || { value: 0 }).value];
  const grams = i => parseNum($(`[data-gr="${i}"]`, out).value) || 0;
  const refresh = () => {
    let sp = 0, sk = 0;
    d.items.forEach((it, i) => {
      if (!it.candidates.length) return;
      const f = pick(i), g = grams(i), p = pointsFor(f, g), k = scaleFood(f, g).kcal;
      $(`[data-pv="${i}"]`, out).textContent = fmtVal(p, k);
      if ($(`[data-on="${i}"]`, out).checked) { sp += p; sk += k; }
    });
    $("#t-sum", out).textContent = isPoints() ? `${sp} P · ${Math.round(sk)} kcal` : `${Math.round(sk)} kcal`;
  };
  out.oninput = refresh; out.onchange = refresh; refresh();
  $("#t-save", out).onclick = async () => {
    const m = chipVal(out, "t-meal") || meal, day = curDay || S.today;
    const list = d.items.map((it, i) => ({ it, i })).filter(({ it, i }) => it.candidates.length && $(`[data-on="${i}"]`, out).checked && grams(i) > 0)
      .map(({ it, i }) => ({ id: uuid(), food_id: pick(i).id, grams: grams(i), portion: it.label.slice(0, 40), meal: m, day }));
    if (!list.length) return toast("Nichts ausgewählt");
    try { await api("/api/log", { method: "POST", body: list }); await loadState(); }
    catch (e) { return toast(e.message); }
    vibrate(30); lists = null; closeSheet(); viewToday();
    toast(`${list.length} ${list.length === 1 ? "Eintrag" : "Einträge"} erfasst`);
  };
}

/* ---------- Eigenes Lebensmittel ---------- */

const NUTR_FIELDS = [["kcal", "Energie (kcal)"], ["protein", "Eiweiß (g)"], ["fat", "Fett (g)"], ["satfat", "davon gesättigt (g)"],
  ["carbs", "Kohlenhydrate (g)"], ["sugar", "davon Zucker (g)"], ["fiber", "Ballaststoffe (g)"], ["salt", "Salz (g)"], ["alcohol", "Alkohol (g)"]];

/* Foto verkleinern (längste Seite 1600 px, JPEG): reicht für kleine Schrift, hält die Anfrage klein */
const num2In = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2, useGrouping: false });   // KI-Werte wie auf der Packung (Salz 0,45)

async function photoDataUrl(file, max = 1600) {
  const bmp = await createImageBitmap(file);
  const f = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const cv = document.createElement("canvas");
  cv.width = Math.round(bmp.width * f); cv.height = Math.round(bmp.height * f);
  cv.getContext("2d").drawImage(bmp, 0, 0, cv.width, cv.height);
  bmp.close && bmp.close();
  return cv.toDataURL("image/jpeg", 0.85);
}

function openCustom(food, meal, hint = "", done = null) {
  const editing = food && food.id && (food.source === "custom" || food.source === "off");
  openSheet(`<h2>${editing ? "Lebensmittel bearbeiten" : "Eigenes Lebensmittel"}</h2>
    ${hint ? `<p class="note">${esc(hint)}</p>` : ""}
    ${S.ai ? `<button class="btn block" id="c-photo">📷 Packung fotografieren – KI liest die Nährwerte</button>
      <input type="file" accept="image/*" capture="environment" id="c-file" hidden>
      <div id="c-ai"></div>` : ""}
    <label class="f"><span>Name</span><input type="text" id="c-name" value="${esc(food.name || "")}" maxlength="120"></label>
    <div class="grid2"><label class="f"><span>Marke (optional)</span><input type="text" id="c-brand" value="${esc(food.brand || "")}"></label>
      <label class="f"><span>Barcode (optional)</span><input type="text" inputmode="numeric" id="c-code" value="${esc(food.code && food.source !== "bls" ? food.code : "")}"></label></div>
    <p class="note">Nährwerte <b>je 100 g</b> (bzw. 100 ml) – steht auf der Packung.</p>
    <div class="grid2">${NUTR_FIELDS.map(([k, l]) => `<label class="f"><span>${l}</span>${decField(`data-n="${k}"`, food[k] != null ? numIn.format(food[k]) : "")}</label>`).join("")}
      <label class="f"><span>Portion (g, optional)</span>${decField('id="c-serv"', food.serving_g != null ? numIn.format(food.serving_g) : "")}</label></div>
    ${editing && food.source === "off" ? `<p class="note">Hinweis: Änderungen an Open-Food-Facts-Produkten speichert FitPath als eigenes Lebensmittel mit gleichem Barcode.</p>` : ""}
    <div class="row nowrap mt">${editing && food.source === "custom" ? `<button class="btn danger" id="c-del">Löschen</button>` : ""}<button class="btn primary grow" id="c-save">Speichern</button></div>`, root => {
    const fileIn = $("#c-file", root);
    fileIn && ($("#c-photo", root).onclick = () => fileIn.click());
    fileIn && (fileIn.onchange = async () => {
      const file = fileIn.files[0]; fileIn.value = "";
      if (!file) return;
      const btn = $("#c-photo", root), box = $("#c-ai", root);
      btn.disabled = true; btn.textContent = "⏳ KI liest die Packung …";
      try {
        const r = await api("/api/ai/label", { method: "POST", body: { images: [await photoDataUrl(file)] } });
        const filled = [];
        for (const [k, l] of NUTR_FIELDS) {
          if (r[k] == null) continue;
          const i = $(`[data-n="${k}"]`, root); i.value = num2In.format(r[k]); i.classList.add("ai-filled"); filled.push(l.replace(/ \(.*/, ""));
        }
        if (r.serving_g != null && !$("#c-serv", root).value) $("#c-serv", root).value = numIn.format(r.serving_g);
        if (r.name && !$("#c-name", root).value.trim()) $("#c-name", root).value = r.name;
        if (r.brand && !$("#c-brand", root).value.trim()) $("#c-brand", root).value = r.brand;
        const missName = !$("#c-name", root).value.trim();
        box.innerHTML = `<div class="card" style="border-color:${r.warnings.length ? "var(--warn)" : "var(--accent)"}">
          ${filled.length ? `<p><b>${filled.length} Werte übernommen</b> – bitte mit der Packung vergleichen.</p>` : `<p><b>Keine Nährwerte gefunden.</b> Die Tabelle gerade und nah fotografieren.</p>`}
          ${r.warnings.map(w => `<p class="note" style="color:var(--warn)">⚠️ ${esc(w)}</p>`).join("")}
          ${missName ? `<p class="note">Name nicht lesbar – eintippen oder die Vorderseite fotografieren.</p>` : ""}</div>`;
      } catch (err) { toast(err.message); }
      btn.disabled = false; btn.textContent = "📷 Weiteres Foto (z. B. Vorderseite für den Namen)";
    });
    $("#c-save", root).onclick = async () => {
      const body = { name: $("#c-name", root).value, brand: $("#c-brand", root).value, code: $("#c-code", root).value, serving_g: parseNum($("#c-serv", root).value) };
      $$("[data-n]", root).forEach(i => { body[i.dataset.n] = i.value === "" ? null : parseNum(i.value); });
      if (!body.name.trim()) return toast("Name fehlt");
      if (body.kcal == null) return toast("kcal je 100 g fehlen");
      try {
        const f = editing && food.source === "custom"
          ? await api(`/api/foods/${food.id}`, { method: "PUT", body })
          : await api("/api/foods", { method: "POST", body });
        lists = null; toast("Gespeichert"); done ? done() : openAmount(f, meal);
      } catch (err) { toast(err.message); }
    };
    $("#c-del", root) && ($("#c-del", root).onclick = async () => {
      if (!confirm("Lebensmittel löschen? Bereits erfasste Einträge bleiben.")) return;
      let r;
      try { r = await api(`/api/foods/${food.id}`, { method: "DELETE" }); } catch (err) { return toast(err.message); }
      lists = null; done ? done() : closeSheet(); toast(`Lebensmittel ${r.result}`);
    });
  });
}

/* ---------- Barcode ---------- */

// Barcode-Erkennung: eingebaut (Chrome auf Android) oder ZXing als WebAssembly vom eigenen Server
// (Safari/iPhone, Firefox). Die rund 1 MB werden erst beim ersten Scannen geladen.
const EAN = ["ean_13", "ean_8", "upc_a", "upc_e"];
const QR = ["qr_code"];
const detectors = {};   // Formate → Promise<Detector>; nach dem Hintergrund neu anlegen (Android verliert sonst den Dienst)
function loadScript(src) {
  return new Promise((ok, fail) => {
    const el = document.createElement("script");
    el.src = src; el.onload = ok; el.onerror = () => fail(new Error("Scanner nicht geladen"));
    document.head.appendChild(el);
  });
}
function barcodeDetector(want = EAN, fresh = false) {
  const key = want.join();
  if (fresh) delete detectors[key];
  const p = detectors[key] = detectors[key] || (async () => {
    if ("BarcodeDetector" in window) {
      try {
        const sup = await BarcodeDetector.getSupportedFormats();
        const formats = want.filter(f => sup.includes(f));
        if (formats.length) return new BarcodeDetector({ formats });
      } catch (_) { /* dann ZXing */ }
    }
    if (!window.BarcodeDetectionAPI) await loadScript("/vendor/barcode-detector-3.2.3.js");
    const lib = window.BarcodeDetectionAPI;
    lib.prepareZXingModule({
      overrides: { locateFile: (path, prefix) => path.endsWith(".wasm") ? "/vendor/zxing_reader-3.1.6.wasm" : prefix + path },
      fireImmediately: true,
    });
    return new lib.BarcodeDetector({ formats: want });
  })();
  p.catch(() => { if (detectors[key] === p) delete detectors[key]; });
  return p;
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") for (const k in detectors) delete detectors[k];
});
// detect() mit Zeitlimit: nach dem Aufwachen bleibt die Erkennung sonst ohne Antwort hängen
const detectWithin = (det, src, ms = 2500) => Promise.race([det.detect(src),
  new Promise((_, fail) => setTimeout(() => fail(new Error("timeout")), ms))]);
const eanOf = codes => (codes.find(x => /^\d{8,14}$/.test(x.rawValue)) || {}).rawValue;

// Live-Kamera im Element #cam mit Barcode-Erkennung. onCode(code) bei jedem Treffer, onState("loading" | "ready" | Fehler).
// Liefert sofort ein Objekt mit stop(). wake: Bildschirm anlassen (Einkaufsmodus), wo der Browser es kann.
function liveScan(root, onCode, onState, wake = false, formats = EAN, pick = eanOf) {
  const ctl = { stream: null, timer: null, stopped: false, lock: null };
  ctl.stop = () => {
    ctl.stopped = true; clearInterval(ctl.timer);
    if (ctl.stream) ctl.stream.getTracks().forEach(t => t.stop());
    ctl.stream = null;
    if (ctl.lock) { ctl.lock.release().catch(() => {}); ctl.lock = null; }
  };
  (async () => {
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) return onState(new Error("keine Kamera"));
    try {
      const detP = barcodeDetector(formats);   // lädt parallel zum Kamerastart
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false });
      if (ctl.stopped || $("#sheet").hidden) { stream.getTracks().forEach(t => t.stop()); return; }
      ctl.stream = stream;
      const v = $("#cam", root); v.srcObject = stream; await v.play();
      onState("loading");
      let det = await detP;
      if (ctl.stopped) return;
      if (wake && navigator.wakeLock) { try { ctl.lock = await navigator.wakeLock.request("screen"); } catch (_) { /* egal */ } }
      onState("ready");
      let busy = false, fails = 0, warm = false;   // erster Aufruf darf dauern (ZXing lädt WASM)
      ctl.timer = setInterval(async () => {
        if (ctl.stopped || busy) return;
        if (v.paused) v.play().catch(() => {});
        if (v.readyState < 2) return;
        busy = true;
        try {
          const native = window.BarcodeDetector && det instanceof window.BarcodeDetector;
          const c = pick(await detectWithin(det, v, warm || native ? 2500 : 20000)); fails = 0; warm = true;
          if (c && !ctl.stopped) onCode(c);
        } catch (_) {
          // hängt oder scheitert wiederholt (typisch nach dem Hintergrund): Erkennung neu anlegen
          if (++fails >= 2) { fails = 0; warm = false; try { det = await barcodeDetector(formats, true); } catch (_) { /* nächster Versuch */ } }
        }
        busy = false;
      }, 250);
    } catch (err) { ctl.stop(); onState(err || new Error("Kamera")); }
  })();
  return ctl;
}
const camError = err => err && err.name === "NotAllowedError" ? "Kamera nicht erlaubt" : "Live-Scan geht hier nicht";

function openScan(meal) {
  const live = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  openSheet(`<h2>📷 Barcode scannen</h2>
    ${live ? `<div class="scan" id="scan-box"><video id="cam" playsinline muted></video><div class="frame"></div></div>` : ""}
    <p class="note center" id="scan-hint">${live ? "Kamera startet …" : "Foto vom Barcode machen oder die Zahl darunter eintippen."}</p>
    <button class="btn block" id="snap">📸 Foto vom Barcode</button>
    <input type="file" accept="image/*" capture="environment" id="snap-file" hidden>
    <div class="row nowrap mt"><input type="text" inputmode="numeric" id="code" class="grow" placeholder="Zahl unter dem Strichcode"><button class="btn primary" id="go">Suchen</button></div>
    <button class="btn block mt" id="to-shop">🛒 Einkaufsmodus: viele Produkte nacheinander anschauen</button>`, async root => {
    let cam = null, done = false;
    const hint = t => { const h = $("#scan-hint", root); if (h) h.textContent = t; };
    const stop = () => { if (cam) cam.stop(); };
    sheetCleanup = stop;
    $("#to-shop", root).onclick = () => { stop(); openShop(); };
    const lookup = async code => {
      if (done) return; done = true; stop(); vibrate(60);
      hint(`Suche ${code} …`);
      let r;
      try { r = await api(`/api/foods/barcode/${encodeURIComponent(code)}`); } catch (err) { done = false; return toast(err.message); }
      if (r.status === "found") { lists = null; return openAmount(r.food, meal); }
      if (r.status === "unknown") return openCustom({ code, name: r.name || "" }, meal, `Bei Open Food Facts nicht gefunden (oder ohne Nährwerte). ${S.ai ? "Nährwerttabelle fotografieren oder Werte abtippen" : "Werte von der Packung abtippen"} – beim nächsten Scan kennt FitPath das Produkt.`);
      done = false;
      toast(r.status === "busy" ? "Zu viele Abfragen – kurz warten" : r.status === "invalid" ? "Barcode ungültig" : "Open Food Facts nicht erreichbar");
    };
    $("#go", root).onclick = () => { const c = $("#code", root).value.replace(/\D/g, ""); if (c.length >= 6) lookup(c); else toast("Barcode zu kurz"); };

    // Foto: die Kamera-App stellt scharf und liefert volle Auflösung, braucht keine Kamera-Erlaubnis im Browser
    $("#snap", root).onclick = () => { stop(); $("#scan-box", root) && ($("#scan-box", root).hidden = true); $("#snap-file", root).click(); };
    $("#snap-file", root).onchange = async ev => {
      const file = ev.target.files && ev.target.files[0]; ev.target.value = "";
      if (!file) return;
      hint("Lese Barcode aus dem Foto …");
      try {
        const det = await barcodeDetector(EAN, true);
        let code = eanOf(await detectWithin(det, file, 8000));
        if (!code) {   // sehr große Fotos: verkleinert noch einmal versuchen
          const bmp = await createImageBitmap(file), k = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
          const cv = document.createElement("canvas"); cv.width = Math.round(bmp.width * k); cv.height = Math.round(bmp.height * k);
          cv.getContext("2d").drawImage(bmp, 0, 0, cv.width, cv.height);
          code = eanOf(await detectWithin(det, cv, 8000));
        }
        if (code) return lookup(code);
        hint("Kein Barcode erkannt. Näher ran, gerade halten, oder die Zahl eintippen.");
      } catch (err) { hint("Foto nicht lesbar – Zahl unten eintippen."); }
    };

    if (!live) return;
    cam = liveScan(root, lookup, st => {
      if (st === "loading") hint("Scanner wird geladen …");
      else if (st === "ready") hint("Barcode in den Rahmen halten …");
      else { $("#scan-box", root) && ($("#scan-box", root).hidden = true); hint(`${camError(st)} – Foto vom Barcode machen oder Zahl eintippen.`); }
    });
  });
}

/* ---------- Einkaufsmodus: Kamera bleibt an, jedes Produkt kommt in die Liste ---------- */

// Liste bleibt, solange die App offen ist (auch nach „Erfassen“ und zurück)
const shop = { items: [], queue: [], waitUntil: 0, timer: null, render: null };

function shopAdd(code) {
  const now = Date.now(), have = shop.items.find(x => x.code === code);
  if (have) {   // schon in der Liste: nach oben holen, nicht neu fragen
    const still = now - have.seen < 4000; have.seen = now;
    if (still) return;   // liegt noch im Bild: nichts tun, erst nach 4 s Pause wieder nach oben
    shop.items = [have, ...shop.items.filter(x => x !== have)];
    vibrate(20); return shop.render && shop.render(code);
  }
  vibrate(60);
  shop.items.unshift({ code, seen: now, status: "loading" });
  shop.items = shop.items.slice(0, 60);
  shopLookup(shop.items[0]);
}

async function shopLookup(it) {
  if (Date.now() < shop.waitUntil) { it.status = "queued"; shop.queue.push(it); return shopTick(); }
  it.status = "loading"; shop.render && shop.render();
  let r;
  try { r = await api(`/api/foods/barcode/${encodeURIComponent(it.code)}`); }
  catch (_) { it.status = "offline"; return shop.render && shop.render(); }
  if (r.status === "busy") {
    shop.waitUntil = Date.now() + (r.retry || 10) * 1000;
    it.status = "queued"; shop.queue.push(it);
    return shopTick();
  }
  if (r.status === "found") { it.status = "found"; it.food = r.food; lists = null; }
  else if (r.status === "unknown") { it.status = "unknown"; it.name = r.name || ""; }
  else it.status = r.status === "invalid" ? "invalid" : "offline";
  shop.render && shop.render();
}

// Wartezeit von Open Food Facts herunterzählen, danach die Warteschlange abarbeiten
function shopTick() {
  shop.render && shop.render();
  if (shop.timer) return;
  shop.timer = setInterval(() => {
    if (Date.now() >= shop.waitUntil) {
      clearInterval(shop.timer); shop.timer = null;
      const q = shop.queue.splice(0);
      q.forEach(it => shopLookup(it));
    }
    shop.render && shop.render();
  }, 1000);
}

function shopRow(it) {
  const P = isPoints();
  const amount = (g, label) => g ? `${label} ${num.format(g)}&nbsp;g&nbsp;= <strong>${P ? pointsFor(it.food, g) + " P" : Math.round(it.food.kcal * g / 100) + " kcal"}</strong>` : "";
  if (it.status === "found") {
    const f = it.food, extra = [amount(f.serving_g, "Portion"), f.package_g && f.package_g !== f.serving_g ? amount(f.package_g, "Packung") : ""].filter(Boolean).join(" · ");
    return `<li class="tap" data-shop="${esc(it.code)}"><span class="dot ${f.ampel}"></span>
      <div class="bd"><b>${esc(f.name)}</b><div class="meta">${[f.brand ? esc(f.brand) : "", extra].filter(Boolean).join(" · ")}</div></div>
      <span class="val">${f.zero ? `<span class="zero">0 P</span>` : P ? `${f.points_100} P` : `${Math.round(f.kcal)} kcal`}<div class="meta" style="font-weight:400">je 100 g</div></span></li>`;
  }
  const txt = { loading: "wird gesucht …", queued: "kommt gleich …", unknown: "unbekannt – antippen zum Anlegen",
    offline: "nicht erreichbar – antippen für neuen Versuch", invalid: "Barcode ungültig" }[it.status];
  return `<li class="tap" data-shop="${esc(it.code)}"><span class="dot" style="background:var(--card-2)"></span>
    <div class="bd"><b>${it.name ? esc(it.name) : esc(it.code)}</b><div class="meta">${txt}</div></div>
    <span class="val muted">${it.status === "unknown" ? "?" : it.status === "loading" || it.status === "queued" ? "…" : "!"}</span></li>`;
}

function openShop() {
  const live = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  openSheet(`<div class="spread"><h2 style="margin:0">🛒 Einkauf</h2><button class="btn small" id="shop-done">Fertig</button></div>
    ${live ? `<div class="scan shop" id="scan-box"><video id="cam" playsinline muted></video><div class="frame"></div></div>` : ""}
    <p class="note center" id="scan-hint" style="margin:4px 0">${live ? "Kamera startet …" : "Live-Scan geht hier nicht."}</p>
    <div class="shop-wait" id="shop-wait" hidden></div>
    <ul class="list" id="shop-list"></ul>
    <div class="row nowrap mt" id="shop-foot"><button class="btn small" id="shop-clear">Liste leeren</button>
      <small class="muted grow" style="text-align:right">Antippen zum Erfassen</small></div>`, root => {
    let cam = null;
    const hint = t => { const h = $("#scan-hint", root); if (h) h.textContent = t; };
    shop.render = flash => {
      if (!$("#shop-list", root) || !root.isConnected) return;
      $("#shop-list", root).innerHTML = shop.items.length ? shop.items.map(shopRow).join("")
        : `<li><div class="bd muted">Noch nichts gescannt. Barcode in den Rahmen halten, die Kamera bleibt an.</div></li>`;
      $("#shop-foot", root).hidden = !shop.items.length;
      const wait = Math.ceil((shop.waitUntil - Date.now()) / 1000), box = $("#shop-wait", root);
      box.hidden = !(wait > 0 && shop.queue.length);
      if (!box.hidden) box.innerHTML = `⏳ <b>Bitte kurz warten.</b> Open Food Facts erlaubt FitPath nur 10 Abfragen pro Minute. ${shop.queue.length} ${shop.queue.length === 1 ? "Produkt wird" : "Produkte werden"} in ${wait} s nachgeladen. Schon bekannte Produkte gehen sofort.`;
      if (flash) { const li = $(`[data-shop="${CSS.escape(flash)}"]`, root); li && li.classList.add("flash"); }
    };
    const stop = () => { if (cam) cam.stop(); };
    sheetCleanup = () => { stop(); shop.render = null; };
    shop.render();
    const reopen = () => openShop();
    $("#shop-done", root).onclick = closeSheet;
    $("#shop-clear", root).onclick = () => { shop.items = []; shop.queue = []; shop.render(); };
    $("#shop-list", root).onclick = e => {
      const li = e.target.closest("[data-shop]"); if (!li) return;
      const it = shop.items.find(x => x.code === li.dataset.shop); if (!it) return;
      if (it.status === "found") { stop(); return openAmount(it.food, mealNow(), null, reopen); }
      if (it.status === "unknown") { stop(); return openCustom({ code: it.code, name: it.name || "" }, mealNow(), "Bei Open Food Facts nicht gefunden. Werte von der Packung abtippen – beim nächsten Scan kennt FitPath das Produkt."); }
      if (it.status === "offline") shopLookup(it);
    };
    if (!live) return;
    cam = liveScan(root, shopAdd, st => {
      if (st === "loading") hint("Scanner wird geladen …");
      else if (st === "ready") hint("Einfach ein Produkt nach dem anderen in den Rahmen halten.");
      else { $("#scan-box", root) && ($("#scan-box", root).hidden = true); hint(`${camError(st)}.`); }
    }, true);
  }, true);
}

/* ---------- Schritte von Hand ---------- */

function openSteps() {
  const a = S.overview.activity;
  if (a && a.source === "hc") {
    return openSheet(`<h2>👟 Schritte</h2><p>${num.format(a.steps || 0)} Schritte laut Health Connect (${fmtAgo(a.updated)}).</p>
      ${a.active_kcal ? `<p class="note">Aktive kcal laut Health Connect: ${Math.round(a.active_kcal)}. FitPath rechnet bewusst vorsichtiger: ${num.format(a.extra_steps)} Schritte über deiner Grundlinie von ${num.format(S.settings.steps_baseline)}, davon die Hälfte gutgeschrieben = ${a.step_kcal} kcal.</p>` : ""}
      <button class="btn block" data-close>Schließen</button>`);
  }
  openSheet(`<h2>👟 Schritte eintragen</h2>
    <label class="f"><span>Schritte ${S.overview.day === S.today ? "heute" : fmtDay(S.overview.day)}</span><input type="number" inputmode="numeric" class="big" id="steps" value="${a ? a.steps || "" : ""}"></label>
    <p class="note">Über ${num.format(S.settings.steps_baseline)} Schritten gibt's Aktivitätspunkte. Automatisch geht's mit Health Connect (Mehr → Health Connect).</p>
    <button class="btn primary block" id="save">Speichern</button>`, root => {
    $("#save", root).onclick = async () => {
      try { S = await api("/api/activity", { method: "POST", body: { day: S.overview.day, steps: parseInt($("#steps", root).value || "0", 10) } }); }
      catch (err) { return toast(err.message); }
      closeSheet(); viewToday();
    };
  });
}

/* ---------- Gewicht ---------- */

function openWeigh() {
  const last = S.body && S.body.weight;
  openSheet(`<h2>⚖️ Eintragen</h2>
    ${chipGroup("kind", [["weight", "Gewicht"], ["fat", "Körperfett %"], ["waist", "Bauchumfang cm"]], "weight")}
    <label class="f"><span id="w-label">Gewicht in kg</span>${decField('class="big" id="w-val"', last ? numIn.format(last) : "")}</label>
    <label class="f"><span>Tag</span><select id="w-day">${Array.from({ length: 14 }, (_, i) => addDays(S.today, -i)).map((d, i) =>
      `<option value="${d}">${i === 0 ? "Heute" : i === 1 ? "Gestern" : fmtDay(d, { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" })}</option>`).join("")}</select></label>
    <p class="note">Am besten morgens nach dem Aufstehen, vor dem Frühstück. FitPath rechnet mit dem Trend, einzelne Ausreißer stören nicht.</p>
    <button class="btn primary block" id="w-save">Speichern</button>`, root => {
    bindChips(root, (_, v) => {
      $("#w-label", root).textContent = { weight: "Gewicht in kg", fat: "Körperfett in %", waist: "Bauchumfang in cm" }[v];
      $("#w-val", root).value = v === "weight" && last ? numIn.format(last) : "";
    });
    $("#w-save", root).onclick = async () => {
      try { S = await api("/api/body", { method: "POST", body: { kind: chipVal(root, "kind"), value: $("#w-val", root).value, day: $("#w-day", root).value } }); }
      catch (err) { return toast(err.message); }
      closeSheet(); toast("Gespeichert"); render();
    };
  });
}

async function viewWeight() {
  const b = S.body;
  view.innerHTML = `<div class="card hero">
      <div class="label muted">Trendgewicht</div>
      <div style="font-size:2.6rem;font-weight:800">${b.trend ? num1.format(b.trend) + " kg" : "–"}</div>
      <small>${b.weight ? `Waage zuletzt ${num1.format(b.weight)} kg (${fmtDay(b.day)})` : "Noch kein Wiegewert"}</small>
      <div class="tiles three mt">
        <div class="tile"><div class="v">${fmtSigned(-(b.lost || 0))}</div><div class="l">kg seit Start</div></div>
        <div class="tile"><div class="v">${b.rate != null ? fmtSigned(b.rate) : "–"}</div><div class="l">kg pro Woche</div></div>
        <div class="tile"><div class="v">${b.bmi ? num1.format(b.bmi) : "–"}</div><div class="l">BMI</div></div>
      </div>
      <button class="btn primary block mt" id="add-w">Eintragen</button>
    </div>
    ${b.progress != null ? `<div class="card"><div class="card-head"><h2>🎯 Ziel ${num1.format(b.goal)} kg</h2><small>${Math.round(b.progress * 100)} %</small></div>
      <div class="progress"><i style="width:${b.progress * 100}%"></i></div>
      <div class="chips mt">${b.milestones.map(m => `<span class="pill${m.done ? " good" : ""}">${m.done ? "✓ " : ""}${m.goal ? "Ziel" : `−${m.pct} %`} · ${num1.format(m.kg)} kg</span>`).join("")}</div>
      ${forecastHtml(b.forecast, b.goal)}
      <p class="note">Schon −5 % Körpergewicht senken Blutdruck und Blutzucker messbar.</p></div>` : ""}
    <div id="bmi"></div>
    <div class="card"><div class="card-head"><h2>📈 Verlauf</h2></div>
      <div class="tabs" id="wr">${[30, 90, 365].map(d => `<button data-d="${d}" class="${weightRange === d ? "on" : ""}">${d === 365 ? "1 Jahr" : d + " Tage"}</button>`).join("")}</div>
      <div id="wchart"><div class="empty">Lade …</div></div>
      <div class="legend"><span><i style="background:var(--accent)"></i>Trend</span><span><i style="background:var(--muted)"></i>Waage</span></div></div>
    <div class="card"><div class="card-head"><h2>Einträge</h2></div><div id="wlist"></div></div>`;
  $("#add-w").onclick = openWeigh;
  $$("#wr button").forEach(bt => (bt.onclick = () => { weightRange = +bt.dataset.d; viewWeight(); }));
  let data;
  try { data = await api(`/api/body?days=${weightRange}`); } catch (_) { $("#wchart").innerHTML = `<div class="empty">Offline</div>`; return; }
  $("#wchart").innerHTML = chartWeight(data.series, b.goal);
  $("#bmi").outerHTML = bmiHtml(data.series) || "<div></div>";
  const icons = { manual: "✋", hc: "📲" }, labels = { weight: "kg", fat: "% Fett", waist: "cm Bauch" };
  $("#wlist").innerHTML = data.entries.length ? `<ul class="list">${data.entries.slice(0, 40).map(e => `<li><span class="ic">${icons[e.source] || ""}</span>
    <div class="bd"><b>${num1.format(e.value)} ${labels[e.kind]}</b><div class="meta">${fmtDay(e.day, { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" })}${e.source === "hc" ? " · Health Connect" : ""}</div></div>
    <button class="btn small danger" data-del="${e.id}">🗑</button></li>`).join("")}</ul>` : `<div class="empty">Noch keine Einträge.</div>`;
  $$("[data-del]").forEach(bt => (bt.onclick = async () => {
    if (!confirm("Eintrag löschen?")) return;
    S = await api(`/api/body/${bt.dataset.del}`, { method: "DELETE" }); viewWeight();
  }));
}

function chartWeight(series, goal) {
  if (series.length < 2) return `<div class="empty">Ab zwei Wiegetagen erscheint hier der Verlauf.</div>`;
  const W = 340, H = 160, P = 30;
  const vals = series.flatMap(s => [s.weight, s.trend]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 2) { lo -= 1; hi += 1; }
  const t0 = new Date(series[0].day).getTime(), t1 = new Date(series[series.length - 1].day).getTime() || t0 + 1;
  const X = d => P + (new Date(d).getTime() - t0) / Math.max(t1 - t0, 1) * (W - P - 6);
  const Y = v => 8 + (hi - v) / (hi - lo) * (H - 28);
  const path = series.map((s, i) => `${i ? "L" : "M"}${X(s.day).toFixed(1)},${Y(s.trend).toFixed(1)}`).join("");
  const ticks = [lo, (lo + hi) / 2, hi].map(v => `<line x1="${P}" x2="${W}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="var(--line)" stroke-dasharray="3 3"/><text x="0" y="${(Y(v) + 3).toFixed(1)}">${num1.format(v)}</text>`).join("");
  const first = series[0].day, last = series[series.length - 1].day;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Gewichtsverlauf">${ticks}
    ${series.map(s => `<circle cx="${X(s.day).toFixed(1)}" cy="${Y(s.weight).toFixed(1)}" r="2.5" fill="var(--muted)"><title>${s.day}: ${s.weight} kg</title></circle>`).join("")}
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
    <text x="${P}" y="${H - 4}">${fmtDay(first, { day: "2-digit", month: "2-digit" })}</text><text x="${W}" y="${H - 4}" text-anchor="end">${fmtDay(last, { day: "2-digit", month: "2-digit" })}</text></svg>`;
}

/* ---------- Statistik ---------- */

async function viewStats() {
  view.innerHTML = `<div class="tabs" id="sr">${[7, 30, 90].map(d => `<button data-d="${d}" class="${statsRange === d ? "on" : ""}">${d} Tage</button>`).join("")}</div><div id="st"><div class="loading">Lade …</div></div>`;
  $$("#sr button").forEach(bt => (bt.onclick = () => { statsRange = +bt.dataset.d; viewStats(); }));
  let d;
  try { d = await api(`/api/stats?days=${statsRange}`); } catch (_) { $("#st").innerHTML = `<div class="empty">Offline – Statistik braucht Verbindung.</div>`; return; }
  const P = isPoints(), b = d.budget, a = d.avg;
  const w = d.weights, dw = w.length >= 2 ? w[w.length - 1].trend - w[0].trend : null;
  const protTarget = Math.round(b.weight * 1.0), fibTarget = 30, none = !d.logged_days;
  $("#st").innerHTML = `
    ${none ? `<p class="note center">Durchschnitte zählen ab dem ersten abgeschlossenen Tag mit Einträgen – heute läuft noch.</p>` : ""}
    <div class="tiles four">
      <div class="tile"><div class="v">${none ? "–" : P ? num1.format(a.points) : num.format(a.kcal)}</div><div class="l">Ø ${P ? "Punkte" : "kcal"} pro Tag</div></div>
      <div class="tile"><div class="v">${d.in_budget}/${d.logged_days}</div><div class="l">Tage im Budget</div></div>
      <div class="tile"><div class="v">${a.steps ? num.format(a.steps) : "–"}</div><div class="l">Ø Schritte</div></div>
      <div class="tile"><div class="v">${dw != null ? fmtSigned(dw) : "–"}</div><div class="l">kg Trend im Zeitraum</div></div>
    </div>
    ${adaptiveHtml(d.adaptive, P)}
    <div class="card"><div class="card-head"><h2>${P ? "Punkte" : "kcal"} pro Tag</h2><small>Budget ${P ? b.points + " P" : num.format(b.target) + " kcal"}</small></div>
      ${chartDaily(d.days, P ? "points" : "kcal", P ? b.points : b.target, P ? "act_points" : "act_kcal")}
      <div class="legend"><span><i style="background:var(--good)"></i>im Budget</span><span><i style="background:var(--bad)"></i>drüber</span><span><i style="background:var(--muted)"></i>Budget + Aktivität</span></div></div>
    <div class="card"><div class="card-head"><h2>🥗 Nährstoffe</h2><small>Ø pro erfasstem Tag</small></div>
      ${none ? `<div class="empty">Noch kein abgeschlossener Tag.</div>` : `${hbar("Eiweiß", a.protein, protTarget, "g", `Richtwert ≈ ${protTarget} g (1 g je kg) – macht satt und schützt die Muskeln`)}
      ${hbar("Ballaststoffe", a.fiber, fibTarget, "g", "Richtwert 30 g (DGE)")}
      ${hbar("Fett", a.fat, null, "g")}${hbar("Kohlenhydrate", a.carbs, null, "g")}
      <p class="note">Ø ${num.format(a.kcal)} kcal pro Tag.</p>`}</div>
    <div class="card"><div class="card-head"><h2>🚦 Energiedichte</h2><small>Anteil an den kcal</small></div>
      <div class="stack"><i style="width:${d.ampel.green * 100}%;background:var(--good)"></i><i style="width:${d.ampel.yellow * 100}%;background:var(--warn)"></i><i style="width:${d.ampel.red * 100}%;background:var(--bad)"></i></div>
      <div class="legend"><span><i style="background:var(--good)"></i>leicht ${Math.round(d.ampel.green * 100)} %</span><span><i style="background:var(--warn)"></i>mittel ${Math.round(d.ampel.yellow * 100)} %</span><span><i style="background:var(--bad)"></i>dicht ${Math.round(d.ampel.red * 100)} %</span></div>
      <p class="note">Leichte Lebensmittel (viel Wasser und Ballaststoffe) füllen den Magen mit wenig Energie.</p></div>
    ${cravingHtml(d.cravings)}
    <div class="card"><div class="card-head"><h2>🏆 Größte Punkte-Lieferanten</h2></div>
      ${d.top.length ? `<ul class="list">${d.top.map(x => `<li><div class="bd"><b>${esc(x.name)}</b><div class="meta">${x.count}× · ${num.format(x.kcal)} kcal</div></div><span class="val">${P ? x.points + " P" : num.format(x.kcal) + " kcal"}</span></li>`).join("")}</ul>` : `<div class="empty">Noch keine Einträge.</div>`}</div>
    <div class="card"><div class="card-head"><h2>👟 Schritte</h2><small>Ziel ${num.format(S.settings.steps_goal)}</small></div>${chartSteps(d.days, S.settings.steps_goal)}</div>
    ${trainingStatsHtml(d.training, d.days, P)}`;
  bindAdaptive(d.adaptive);
}

function trainingStatsHtml(t, days, P) {
  const head = `<div class="card-head"><h2>💪 Training</h2><small>im Zeitraum</small></div>`;
  if (!t || !t.sports.length) return `<div class="card">${head}<div class="empty">Noch kein Training im Zeitraum. Auf Heute in der Karte „Schritte“ über ＋ Training eintragen, Einheiten von der Uhr kommen über Health Connect.</div></div>`;
  const min = S.training ? S.training.train_day_minutes : 20;
  return `<div class="card">${head}
    <div class="tiles three"><div class="tile"><div class="v">${t.days}</div><div class="l">Trainingstage</div></div>
      <div class="tile"><div class="v">${t.minutes >= 60 ? `${num1.format(t.minutes / 60)} h` : `${t.minutes} min`}</div><div class="l">Training</div></div>
      <div class="tile"><div class="v">+${P ? num.format(t.points) : num.format(t.kcal)}</div><div class="l">${P ? "Punkte" : "kcal"} gutgeschrieben</div></div></div>
    ${chartTraining(days, min)}
    <ul class="list">${t.sports.map(x => `<li><span style="font-size:1.4rem">${x.icon}</span><div class="bd"><b>${esc(x.name)}</b>
      <div class="meta">${x.count}× · ${fmtMin(x.minutes)}</div></div>
      <span class="val">${!x.kcal && x.kind === "gehen" ? `<span class="muted">über Schritte</span>` : `+${fmtVal(x.points, x.kcal)}`}</span></li>`).join("")}</ul>
    <p class="note">Trainingstag ab ${min} Minuten, Spazieren zählt über die Schritte. Je Tag höchstens ${S.training ? S.training.max_points_day : 15} Trainingspunkte, deshalb kann die Summe oben kleiner sein als die Liste.</p></div>`;
}

function chartTraining(days, min) {
  const W = 340, H = 110, P = 30, n = days.length;
  const max = Math.max(60, ...days.map(x => x.train_minutes || 0));
  const bw = (W - P) / n, Y = v => H - 16 - v / max * (H - 26);
  const bars = days.map((x, i) => x.train_minutes ? `<rect x="${(P + i * bw + bw * .14).toFixed(1)}" y="${Y(x.train_minutes).toFixed(1)}" width="${Math.max(bw * .72, 1).toFixed(1)}" height="${(x.train_minutes / max * (H - 26)).toFixed(1)}" rx="2" fill="${x.train_minutes >= min ? "var(--good)" : "var(--accent)"}"><title>${x.day}: ${x.train_minutes} min</title></rect>` : "").join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Trainingsminuten pro Tag">
    <line x1="${P}" x2="${W}" y1="${Y(min).toFixed(1)}" y2="${Y(min).toFixed(1)}" stroke="var(--muted)" stroke-dasharray="4 3"/>
    <text x="0" y="${(Y(min) + 3).toFixed(1)}">${min}′</text>${bars}</svg>`;
}

/* Adaptiver Bedarf: echter Verbrauch aus Einträgen und Gewicht (app/adaptive.py) */
function adaptiveHtml(a, P) {
  if (!a) return "";
  const head = `<div class="card-head"><h2>🔥 Echter Bedarf</h2><small>letzte ${a.window_days} Tage</small></div>`;
  const adj = a.adjust ? `<p class="note">Aktive Korrektur: <b>${a.adjust > 0 ? "+" : "−"}${num.format(Math.abs(a.adjust))} kcal</b> pro Tag. <button class="linkbtn" id="adj-reset">Zurücksetzen</button></p>` : "";
  if (a.status === "early") return `<div class="card">${head}
    <p class="note">Ab ${a.min_days} Tagen mit Einträgen und ${a.min_weighins} Wiegewerten rechnet FitPath aus, wie viel du wirklich verbrauchst, statt nur nach Formel. Bisher: ${a.days} ${a.days === 1 ? "Tag" : "Tage"}, ${a.weighins} Wiegewerte.</p>${adj}</div>`;
  if (a.status === "gaps") return `<div class="card">${head}
    <p class="note">Zu wenige vollständig erfasste Tage: ${a.logged} von ${a.days}, nötig sind ${a.need_logged}. Ein Tag zählt ab zwei Mahlzeiten und ${num.format(800)} kcal, sonst wäre der Verbrauch zu niedrig geschätzt.</p>${adj}</div>`;
  const conf = { hoch: "good", mittel: "warn", niedrig: "bad" }[a.confidence];
  const now = a.model + a.adjust + a.activity;
  const diff = a.suggested - a.adjust;
  const effect = P ? `${a.points_new} statt ${a.points_now} Punkte` : `Ziel ${num.format(a.target_new)} statt ${num.format(a.target_now)} kcal`;
  return `<div class="card">${head}
    <div class="spread"><div><div style="font-size:1.8rem;font-weight:800">≈ ${num.format(a.real)} kcal</div><small>pro Tag, ± ${num.format(a.error)} kcal</small></div>
      <span class="pill ${conf}">Sicherheit ${a.confidence}</span></div>
    <p class="note">Ø ${num.format(a.intake)} kcal gegessen an ${a.logged} von ${a.days} Tagen, Gewicht ${fmtSigned(a.kg_per_week)} kg pro Woche. FitPath rechnet bisher mit ${num.format(now)} kcal (Formel ${num.format(a.model)}${a.adjust ? `, Korrektur ${a.adjust > 0 ? "+" : "−"}${num.format(Math.abs(a.adjust))}` : ""}${a.activity ? `, Aktivität ${num.format(a.activity)}` : ""}).</p>
    ${a.suggest ? `<button class="btn primary block" id="adj-apply">Budget anpassen: ${diff > 0 ? "+" : "−"}${num.format(Math.abs(diff))} kcal pro Tag (${effect})</button>`
      : a.confidence === "niedrig" ? `<p class="note">Für einen Vorschlag noch zu unsicher, das Gewicht schwankt stark. Regelmäßiger wiegen hilft.</p>`
      : `<p class="note">✅ Passt: Rechnung und Wirklichkeit liegen nah beieinander.</p>`}
    ${adj}
    <p class="note">Stimmt nur, wenn du alles erfasst, auch 0-Punkte-Lebensmittel. Ein Kilo Körperfett ≈ ${num.format(7700)} kcal.</p></div>`;
}

function bindAdaptive(a) {
  const set = async (v, msg) => {
    try { S = await api("/api/settings", { method: "PUT", body: { tdee_adjust: v } }); toast(msg); viewStats(); }
    catch (e) { toast(e.message); }
  };
  $("#adj-apply") && ($("#adj-apply").onclick = () => set(a.suggested, "Budget angepasst"));
  $("#adj-reset") && ($("#adj-reset").onclick = () => { if (confirm("Korrektur zurücksetzen? Das Budget folgt dann wieder nur der Formel.")) set(0, "Korrektur entfernt"); });
}

function hbar(label, v, target, u, note = "") {
  const pct = target ? Math.min(v / target, 1) * 100 : null;
  return `<div class="hbar"><div class="top"><span>${label}</span><b>${num.format(v)} ${u}${target ? ` <small class="muted">/ ${target}</small>` : ""}</b></div>
    ${pct != null ? `<div class="bar"><i style="width:${pct}%;${pct >= 100 ? "background:var(--good)" : ""}"></i></div>` : ""}${note ? `<small>${note}</small>` : ""}</div>`;
}

function chartDaily(days, key, budget, actKey) {
  if (!days.some(x => x.entries)) return `<div class="empty">Noch keine Einträge im Zeitraum.</div>`;
  const W = 340, H = 150, P = 26, n = days.length;
  const max = Math.max(budget * 1.3, ...days.map(x => x[key]), ...days.map(x => budget + (x[actKey] || 0)));
  const bw = (W - P) / n, Y = v => H - 16 - v / max * (H - 26);
  const bars = days.map((x, i) => {
    if (!x.entries) return "";
    const lim = budget + (x[actKey] || 0), h = x[key] / max * (H - 26);
    return `<rect x="${(P + i * bw + bw * .14).toFixed(1)}" y="${Y(x[key]).toFixed(1)}" width="${Math.max(bw * .72, 1).toFixed(1)}" height="${h.toFixed(1)}" rx="2" fill="${x[key] <= lim ? "var(--good)" : "var(--bad)"}"><title>${x.day}: ${x[key]}</title></rect>
      ${x[actKey] ? `<line x1="${(P + i * bw).toFixed(1)}" x2="${(P + (i + 1) * bw).toFixed(1)}" y1="${Y(lim).toFixed(1)}" y2="${Y(lim).toFixed(1)}" stroke="var(--muted)" stroke-width="1.5"/>` : ""}`;
  }).join("");
  const labels = days.map((x, i) => (n <= 10 || i % Math.ceil(n / 7) === 0) ? `<text x="${(P + i * bw + bw / 2).toFixed(1)}" y="${H - 3}" text-anchor="middle">${x.day.slice(8, 10)}.${x.day.slice(5, 7)}</text>` : "").join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Verbrauch pro Tag">
    <line x1="${P}" x2="${W}" y1="${Y(budget).toFixed(1)}" y2="${Y(budget).toFixed(1)}" stroke="var(--muted)" stroke-dasharray="4 3"/>
    <text x="0" y="${(Y(budget) + 3).toFixed(1)}">${num.format(budget)}</text>${bars}${labels}</svg>`;
}

function chartSteps(days, goal) {
  if (!days.some(x => x.steps)) return `<div class="empty">Noch keine Schritte. Health Connect verbinden oder von Hand eintragen.</div>`;
  const W = 340, H = 120, P = 30, n = days.length;
  const max = Math.max(goal * 1.2, ...days.map(x => x.steps || 0));
  const bw = (W - P) / n, Y = v => H - 16 - v / max * (H - 26);
  const bars = days.map((x, i) => x.steps ? `<rect x="${(P + i * bw + bw * .14).toFixed(1)}" y="${Y(x.steps).toFixed(1)}" width="${Math.max(bw * .72, 1).toFixed(1)}" height="${(x.steps / max * (H - 26)).toFixed(1)}" rx="2" fill="${x.steps >= goal ? "var(--good)" : "var(--accent)"}"><title>${x.day}: ${x.steps}</title></rect>` : "").join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Schritte pro Tag">
    <line x1="${P}" x2="${W}" y1="${Y(goal).toFixed(1)}" y2="${Y(goal).toFixed(1)}" stroke="var(--muted)" stroke-dasharray="4 3"/>
    <text x="0" y="${(Y(goal) + 3).toFixed(1)}">${num.format(goal / 1000)}k</text>${bars}</svg>`;
}

/* ---------- Eigene Gerichte, Mahlzeiten und Lebensmittel verwalten (Mehr) ---------- */

let ownTab = "recipes";
async function openOwn() {
  const back = () => openOwn();
  let own;
  try { own = (await api("/api/foods/lists")).custom; } catch (e) { return toast(e.message); }
  const groups = {
    recipes: own.filter(f => f.source === "recipe"),
    meals: S.templates || [],
    foods: own.filter(f => f.source === "custom"),
  };
  const tabs = [["recipes", "🍲 Gerichte"], ["meals", "⭐ Mahlzeiten"], ["foods", "✏️ Lebensmittel"]];
  const row = (id, title, meta, val) => `<li class="tap" data-own="${esc(String(id))}"><div class="bd"><b>${esc(title)}</b><div class="meta">${meta}</div></div>
    ${val ? `<span class="val">${val}</span>` : ""}<button class="btn icon small-icon" data-own-rm="${esc(String(id))}" aria-label="${esc(title)} löschen">🗑</button></li>`;
  const body = () => {
    const items = groups[ownTab];
    if (!items.length) return `<div class="empty">${{ recipes: "Noch keine Gerichte. Unten eins anlegen oder beim Erfassen per Rezept-Link übernehmen.",
      meals: "Noch keine Mahlzeiten gemerkt. Auf Heute bei einer Mahlzeit mit Einträgen auf ☆ tippen.",
      foods: "Noch keine eigenen Lebensmittel." }[ownTab]}</div>`;
    return `<ul class="list">${items.map(x => ownTab === "meals"
      ? row(x.id, x.name, esc(x.items.map(i => shortName(i.name)).join(", ")), fmtVal(x.points, x.kcal))
      : row(x.id, x.name, `${x.brand ? esc(x.brand) + " · " : ""}${Math.round(x.kcal || 0)} kcal/100 g`, "")).join("")}</ul>`;
  };
  openSheet(`<h2>Eigene Sachen</h2>
    <div class="tabs" id="own-tabs">${tabs.map(([k, l]) => `<button data-t="${k}" class="${ownTab === k ? "on" : ""}">${l} (${groups[k].length})</button>`).join("")}</div>
    <div id="own-list">${body()}</div>
    <p class="note">Antippen zum Bearbeiten. Löschen lässt schon erfasste Einträge unverändert.</p>
    <div class="row nowrap mt"><button class="btn grow" id="own-recipe">🍲 Gericht anlegen</button><button class="btn grow" id="own-food">✏️ Eigenes Lebensmittel</button></div>`, root => {
    const draw = () => {
      $$("#own-tabs [data-t]", root).forEach(b => b.classList.toggle("on", b.dataset.t === ownTab));
      $("#own-list", root).innerHTML = body();
    };
    $("#own-tabs", root).onclick = e => { const b = e.target.closest("[data-t]"); if (b) { ownTab = b.dataset.t; draw(); } };
    $("#own-list", root).onclick = async e => {
      const rm = e.target.closest("[data-own-rm]"), li = e.target.closest("[data-own]");
      if (!li) return;
      const id = li.dataset.own;
      if (ownTab === "meals") {
        const t = groups.meals.find(x => x.id === id); if (!t) return;
        if (rm) { if (await deleteTemplate(t)) back(); return; }
        return openTemplateEdit(t, back);
      }
      const f = groups[ownTab].find(x => String(x.id) === id); if (!f) return;
      if (rm) {
        if (!confirm(`„${f.name}“ löschen? Schon erfasste Einträge bleiben.`)) return;
        try { const r = await api(`/api/foods/${f.id}`, { method: "DELETE" }); lists = null; toast(`${f.source === "recipe" ? "Gericht" : "Lebensmittel"} ${r.result}`); }
        catch (err) { return toast(err.message); }
        return back();
      }
      try {
        if (f.source === "recipe") openRecipe(await api(`/api/recipes/${f.id}`), mealNow(), back);
        else openCustom(await api(`/api/foods/${f.id}`), mealNow(), "", back);
      } catch (err) { toast(err.message); }
    };
    $("#own-recipe", root).onclick = () => openRecipe(null, mealNow(), back);
    $("#own-food", root).onclick = () => openCustom({ name: "" }, mealNow(), "", back);
  }, true);
}

/* ---------- Mehr ---------- */

async function viewMore() {
  const s = S.settings, b = S.overview.budget;
  view.innerHTML = `
    <div class="card"><div class="card-head"><h2>🎯 Ziele und Profil</h2><button class="btn small" id="edit-goals">Ändern</button></div>
      <p>${s.mode === "keep" ? "Gewicht halten" : `Abnehmen, ${num1.format(s.pace)} kg pro Woche`} · Ziel ${num1.format(s.goal_weight)} kg</p>
      <p class="note">Grundumsatz ${num.format(b.bmr)} kcal × Aktivität ${String(s.activity).replace(".", ",")}${b.adjust ? ` ${b.adjust > 0 ? "+" : "−"} ${num.format(Math.abs(b.adjust))} kcal Korrektur (Statistik → Echter Bedarf)` : ""} = ${num.format(b.tdee)} kcal Bedarf${b.deficit ? ` − ${num.format(b.deficit)} kcal Defizit` : ""} = <b>${num.format(b.target)} kcal</b> = <b>${b.points} Punkte</b> pro Tag (bei ${num1.format(b.weight)} kg).
      ${b.floor_hit ? `Untergrenze ${num.format(b.floor)} kcal greift – weniger wäre auf Dauer nicht gesund.` : ""}</p></div>
    <div class="card"><div class="card-head"><h2>🍲 Eigene Sachen</h2><button class="btn small" id="own">Verwalten</button></div>
      <p class="note">Gerichte, gemerkte Mahlzeiten und eigene Lebensmittel ansehen, bearbeiten oder löschen.</p></div>
    <div class="card"><h2>Anzeige</h2>${chipGroup("display", [["points", "Punkte"], ["kcal", "Kalorien"]], s.display)}
      <label class="f mt"><span>Design (nur dieses Gerät)</span></label>
      ${chipGroup("theme", [["system", "📱 System"], ["light", "☀️ Hell"], ["dark", "🌙 Dunkel"]], savedTheme())}
      <details class="more mt"><summary>So rechnet FitPath</summary>
        <p class="note"><b>Punkte je Eintrag</b> = kcal ÷ 35 + gesättigtes Fett ÷ 4 + Zucker ÷ 10 + Alkohol ÷ 8 − Eiweiß ÷ 10 − Ballaststoffe ÷ 5 (Gramm, nie unter 0, gerundet). Eiweiß und Ballaststoffe machen satt und senken die Punkte, Zucker, gesättigtes Fett und Alkohol erhöhen sie.</p>
        <p class="note"><b>0 Punkte</b>: frisches Obst und Gemüse, Pilze, Sprossen, gegarte Hülsenfrüchte (nicht Saft, Trockenobst, Konserven mit Zucker). Pro Lebensmittel änderbar.</p>
        <p class="note"><b>Tagesbudget</b> = (kcal-Ziel − 200 kcal für 0-Punkte-Lebensmittel) ÷ 40. Wer satt machend isst, kommt damit auf sein kcal-Ziel, bei viel Zucker und Fett wird es knapper – genau so ist es gedacht. kcal-Ziel nach Mifflin-St Jeor, nie unter ${num.format(b.floor)} kcal, Abnahme höchstens 1 % des Gewichts pro Woche.</p>
        <p class="note"><b>Wochenreserve</b>: Von jedem erfassten Tag wandern bis zu 4 ungenutzte Punkte in die Reserve, ein überzogener Tag zieht ab. Montag beginnt sie neu.</p>
        <p class="note"><b>Aktivität</b>: Schritte über ${num.format(s.steps_baseline)} geben Punkte. Geschätzt ≈ 0,0005 kcal je Schritt und kg, davon nur die Hälfte – Schätzungen sind meist zu hoch.</p>
        <p class="note"><b>Training</b>: (Belastung in MET − 1) × kg × Stunden, also nur der Verbrauch über Ruhe, davon die Hälfte, höchstens ${S.training ? S.training.max_points_day : 15} Punkte am Tag. Schritte, die beim Gehen, Laufen oder Wandern schon gezählt haben, werden abgezogen.</p>
      </details></div>
    <div class="card"><h2>👟 Schritte</h2>
      <div class="grid2"><label class="f"><span>Grundlinie</span><input type="number" id="s-base" value="${s.steps_baseline}" step="500"></label>
      <label class="f"><span>Tagesziel</span><input type="number" id="s-goal" value="${s.steps_goal}" step="500"></label></div>
      <p class="note">Die Grundlinie steckt schon im Alltags-Bedarf. Erst Schritte darüber geben Aktivitätspunkte.</p>
      <button class="btn small" id="s-save">Speichern</button></div>
    <div class="card"><div class="card-head"><h2>📲 Health Connect</h2><span class="pill${s.ingest_configured ? " good" : ""}">${s.ingest_configured ? "eingerichtet" : "aus"}</span></div>
      <div id="hc"><div class="empty">Lade …</div></div></div>
    <div class="card"><h2>🔔 Erinnerungen</h2>
      <p id="push-state" class="note">…</p>
      <div class="row"><button class="btn small primary" id="push-on">Auf diesem Gerät aktivieren</button><button class="btn small" id="push-test">Test</button></div>
      <label class="switch"><span>Erinnerungen senden</span><input type="checkbox" id="p-en" ${s.push_enabled ? "checked" : ""}></label>
      <label class="switch"><span>Vor typischen Snack-Zeiten erinnern<br><small class="muted">lernt aus Snack-Einträgen und Heißhunger der letzten 3 Wochen</small></span><input type="checkbox" id="p-snack" ${s.snack_push ? "checked" : ""}></label>
      <label class="f"><span>Wiegen an</span></label>${chipGroup("weigh_days", WEEKDAYS.map((d, i) => [i, d]), s.weigh_days, true)}
      <div class="grid3"><label class="f"><span>Wiegen um</span>${timeField("p-weigh", s.weigh_time)}</label>
        <label class="f"><span>Nichts erfasst um</span>${timeField("p-lunch", s.lunch_reminder, true)}</label>
        <label class="f"><span>Abend-Check um</span>${timeField("p-eve", s.evening_time, true)}</label></div>
      <div class="grid3"><label class="f"><span>Ruhe ab</span>${timeField("p-qs", s.quiet_start)}</label>
        <label class="f"><span>Ruhe bis</span>${timeField("p-qe", s.quiet_end)}</label>
        <label class="f"><span>Höchstens/Tag</span><input type="number" id="p-max" value="${s.push_max_per_day}" min="0" max="10"></label></div>
      <p class="note">Uhrzeiten im 24-Stunden-Format, z. B. 07:30 oder 2030. Leer = Erinnerung aus.</p>
      <button class="btn small" id="p-save">Speichern</button></div>
    <div class="card"><div class="card-head"><h2>🧭 Wenn-Dann-Pläne</h2><a class="btn small" href="#erfolge">🏅 Erfolge</a></div>
      <p class="note">Für jeden Heißhunger-Auslöser eine feste Ersatzhandlung. Im SOS erscheint der passende Plan.</p>
      <div id="plans">${plansHtml(s)}</div>
      <div class="row nowrap mt"><input type="text" id="new-trigger" class="grow" maxlength="40" placeholder="Neuer Auslöser, z. B. Feierabend"><button class="btn small" id="add-trigger">+</button></div>
      <button class="btn small mt" id="plans-save">Speichern</button></div>
    <div class="card"><div class="card-head"><h2>📱 Geräte</h2><div class="row nowrap"><button class="btn small primary" id="dev-scan">QR scannen</button><button class="btn small" id="dev-code">Code eingeben</button></div></div><div id="devs"></div>
      <p class="note">Neues Gerät: dort FitPath öffnen, hier auf <b>QR scannen</b> tippen oder die Zahl über <b>Code eingeben</b> eintippen. Ohne zweites Gerät geht auch ein <button class="linkbtn" id="dev-link">Anmeldelink</button>.</p></div>
    <div class="card"><h2>💾 Daten</h2><a class="btn small" href="/api/export">Export als JSON</a></div>
    <div class="card"><div class="card-head"><h2>ℹ️ Quellen</h2><span class="pill">FitPath ${esc(S.version || "")}</span></div>
      <p class="note">Nährwerte: <b>Bundeslebensmittelschlüssel (BLS) 4.0</b>, Max Rubner-Institut (2025), Karlsruhe, DOI 10.25826/Data20251217-134202-0, Lizenz CC BY 4.0. Markenprodukte per Barcode: <b>Open Food Facts</b> (ODbL).</p>
      <p class="note">FitPath ersetzt keine ärztliche Beratung. Bei Vorerkrankungen, Schwangerschaft oder Essstörungen das Vorgehen mit Arzt oder Ärztin abstimmen.</p></div>`;

  bindChips(view, async (group, val) => {
    if (group === "theme") {
      try { localStorage.setItem("fp_theme", val); } catch (_) { /* privates Fenster: gilt bis zum Neuladen */ }
      applyTheme(val);
      return;
    }
    if (group === "display") { S = await api("/api/settings", { method: "PUT", body: { display: val } }); toast(val === "kcal" ? "Anzeige in kcal" : "Anzeige in Punkten"); }
  });
  $("#edit-goals").onclick = openGoals;
  $("#own").onclick = openOwn;
  bindPlans();
  $("#s-save").onclick = async () => {
    try { S = await api("/api/settings", { method: "PUT", body: { steps_baseline: +$("#s-base").value, steps_goal: +$("#s-goal").value } }); toast("Gespeichert"); }
    catch (e) { toast(e.message); }
  };
  bindTimes(view);
  $("#p-save").onclick = async () => {
    const t = id => normTime($(id).value);
    const times = { weigh_time: t("#p-weigh"), lunch_reminder: t("#p-lunch"), evening_time: t("#p-eve"), quiet_start: t("#p-qs"), quiet_end: t("#p-qe") };
    if (Object.values(times).some(v => v == null) || !times.weigh_time || !times.quiet_start || !times.quiet_end) {
      return toast("Uhrzeit als HH:MM eingeben, z. B. 07:30");
    }
    try {
      S = await api("/api/settings", { method: "PUT", body: {
        push_enabled: $("#p-en").checked, snack_push: $("#p-snack").checked, weigh_days: chipVal(view, "weigh_days").map(Number), ...times,
        push_max_per_day: +$("#p-max").value } });
      toast("Gespeichert");
    } catch (e) { toast(e.message); }
  };
  $("#push-on").onclick = enablePush;
  $("#push-test").onclick = async () => { const r = await api("/api/push/test", { method: "POST" }); toast(r.sent ? `An ${r.sent} Gerät(e) gesendet` : "Kein Gerät angemeldet"); };
  $("#dev-code").onclick = openPairCode;
  $("#dev-scan").onclick = openPairScan;
  $("#dev-link").onclick = async () => {
    const name = prompt("Name des Geräts (z. B. Tablet):", "") ?? null; if (name === null) return;
    const r = await api("/api/devices/link", { method: "POST", body: { name } });
    openSheet(`<h2>Neues Gerät verbinden</h2><p>Diesen Link auf dem neuen Gerät öffnen (${r.minutes} Minuten gültig, nur einmal):</p>
      <p class="linkbox">${esc(r.url)}</p><button class="btn block" id="cp">Kopieren</button><button class="btn block mt" data-close>Fertig</button>`,
      root => { $("#cp", root).onclick = () => navigator.clipboard.writeText(r.url).then(() => toast("Kopiert")); });
  };
  pushStatus(); loadDevices(); loadHC();
}

async function loadHC() {
  let st;
  try { st = await api("/api/ingest/status"); } catch (_) { $("#hc").textContent = "Offline"; return; }
  const last = st.last.find(x => x.kind === "sync");
  const denied = st.last[0] && st.last[0].kind === "denied" ? st.last[0] : null;
  const label = x => x.kind === "test" ? "✅ Test empfangen" : x.kind === "sync" ? `Sync #${x.seq ?? "–"}` : x.kind === "denied" ? "⛔ Abgelehnt" : x.kind;
  const detail = x => x.kind === "sync" ? `${x.summary.steps_last && x.summary.steps_last.steps != null ? ` · ${num.format(x.summary.steps_last.steps)} Schritte (${fmtDay(x.summary.steps_last.date, { day: "2-digit", month: "2-digit" })})` : ""} · Gewichte ${x.summary.weight || 0} · Fettwerte ${x.summary.body_fat || 0}${x.summary.backfill ? " · Verlauf" : ""}`
    : x.kind === "denied" ? ` · ${esc(x.summary.reason || "")}` : "";
  $("#hc").innerHTML = `
    ${st.configured ? `<p>Letzte Lieferung: <b>${last ? fmtAgo(last.ts) : "noch keine"}</b>${st.last_weight ? ` · letztes Gewicht ${num1.format(st.last_weight.value)} kg (${fmtDay(st.last_weight.day, { day: "2-digit", month: "2-digit" })})` : ""}</p>
      ${st.has_diag ? `<ul class="list">${st.types.map(t => `<li><span class="ic">${t.ok ? "✅" : "⚠️"}</span><div class="bd"><b>${t.label}</b><div class="meta">${esc(t.state)}</div></div></li>`).join("")}</ul>`
        : last ? `<p class="note">Details je Datentyp (Berechtigung, Datensätze) erscheinen nach der nächsten Lieferung.</p>` : ""}` :
      `<p class="note">Schritte, Gewicht und Körperfett kommen automatisch, wenn die App <b>Life Dashboard Companion</b> (F-Droid, kostenlos, Open Source) Health Connect an FitPath schickt.</p>`}
    ${denied ? `<p class="note" style="color:var(--bad)">Zuletzt abgelehnt (${fmtAgo(denied.ts)}): ${esc(denied.summary.reason || "")}. Am einfachsten neu koppeln.</p>` : ""}
    <div class="row">${st.configured ? `<button class="btn small primary" id="hc-pair">Koppeln (QR-Code)</button><button class="btn small" id="hc-secret">Neues Geheimnis</button>`
      : `<button class="btn small primary" id="hc-secret">Einrichten</button>`}</div>
    <details class="more"><summary>Anleitung</summary><ol class="note">
      <li>Life Dashboard Companion aus F-Droid installieren, Health-Connect-Zugriff erlauben für <b>Schritte, Gewicht, Körperfett, aktive Kalorien</b>.</li>
      <li>In FitPath <b>Koppeln</b> tippen. Am PC den QR-Code mit dem Handy scannen (Kamera oder in Life Dashboard <b>Add destination → Scan a pairing code</b>). Ist FitPath auf dem Handy offen: <b>In Life Dashboard öffnen</b>.</li>
      <li>In Life Dashboard <b>Pair</b> tippen. Die App schickt sofort einen Test, hier erscheint „Test empfangen“.</li>
      <li><b>Daily totals in payload</b> anlassen (Standard). Für die Vergangenheit: <b>Send history</b> (z. B. 30 Tage).</li></ol>
      <p class="note">Von Hand geht es auch: Adresse <span class="linkbox" style="display:inline-block">${esc(st.url)}</span> unter <b>Health → Webhook</b>, Geheimnis bei <b>HMAC signing secret</b>.</p></details>
    ${st.last.length ? `<details class="more"${denied ? " open" : ""}><summary>Letzte Lieferungen</summary><ul class="list">${st.last.map(x => `<li><div class="bd"><b>${label(x)}</b>
      <div class="meta">${fmtAgo(x.ts)}${detail(x)}</div></div></li>`).join("")}</ul></details>` : ""}`;
  $("#hc-pair") && ($("#hc-pair").onclick = async () => {
    try { openPair(await api("/api/ingest/pair"), false); } catch (e) { toast(e.message); }
  });
  $("#hc-secret").onclick = async () => {
    if (st.configured && !confirm("Neues Geheimnis erzeugen? Das alte gilt dann nicht mehr – danach in Life Dashboard neu koppeln.")) return;
    try { const r = await api("/api/ingest/secret", { method: "POST" }); S.settings.ingest_configured = true; openPair(r, true); }
    catch (e) { toast(e.message); }
  };
}

function openPair(r, fresh) {
  const phone = /Android|iPhone|iPad/i.test(navigator.userAgent);
  openSheet(`<h2>📲 Mit Life Dashboard koppeln</h2>
    ${fresh ? `<p class="note">Neues Geheimnis erzeugt – das alte gilt nicht mehr.</p>` : ""}
    ${phone ? `<a class="btn primary block" href="${esc(r.app_link)}">In Life Dashboard öffnen</a>
      <p class="note">Öffnet in Life Dashboard die Seite <b>Pair with this receiver?</b> – dort <b>Pair</b> tippen.</p>` : ""}
    <div class="center mt"><div style="display:inline-block;background:#fff;border-radius:12px;padding:6px;line-height:0">${r.qr_svg}</div></div>
    <p class="note center">${phone ? "Oder diesen Code von einem anderen Handy scannen." : "Mit der Handy-Kamera scannen oder in Life Dashboard unter <b>Add destination → Scan a pairing code</b>, dann <b>Pair</b> tippen."}</p>
    <p class="note">Der Code enthält das Geheimnis – nicht weitergeben und keinen Screenshot verschicken.</p>
    <details class="more"><summary>Von Hand eintragen</summary>
      <label class="f"><span>Adresse (Health → Webhook)</span><span class="linkbox" style="display:block">${esc(r.url)}</span></label><button class="btn small" id="cp-url">Adresse kopieren</button>
      <label class="f"><span>HMAC signing secret</span><span class="linkbox" style="display:block">${esc(r.secret)}</span></label><button class="btn small" id="cp-sec">Geheimnis kopieren</button></details>
    <button class="btn block mt" data-close>Fertig</button>`, root => {
    const copy = t => navigator.clipboard.writeText(t).then(() => toast("Kopiert"), () => toast("Kopieren nicht erlaubt"));
    $("#cp-url", root).onclick = () => copy(r.url);
    $("#cp-sec", root).onclick = () => copy(r.secret);
  });
  sheetCleanup = () => loadHC();
}

function goalsForm(o) {
  const lv = S.activity_levels || {};
  return `<label class="f"><span>Geschlecht (für die Formel)</span></label>
    ${chipGroup("sex", [["m", "Mann"], ["w", "Frau"]], o.sex)}
    <div class="grid3"><label class="f"><span>Geburtsjahr</span><input type="number" id="g-by" value="${o.birth_year}" min="1920" max="2010"></label>
      <label class="f"><span>Größe (cm)</span><input type="number" id="g-h" value="${o.height_cm}" min="120" max="230"></label>
      <label class="f"><span>Startgewicht</span>${decField('id="g-sw"', numIn.format(o.start_weight))}</label></div>
    <label class="f"><span>Zielgewicht (kg)</span>${decField('id="g-gw"', numIn.format(o.goal_weight))}</label>
    <label class="f"><span>Modus</span></label>${chipGroup("mode", [["lose", "Abnehmen"], ["keep", "Gewicht halten"]], o.mode)}
    <label class="f"><span>Tempo (kg pro Woche)</span></label>${chipGroup("pace", [["0.25", "0,25 sanft"], ["0.5", "0,5 empfohlen"], ["0.75", "0,75 zügig"]], String(o.pace))}
    <label class="f"><span>Alltag (ohne Sport, Schritte und Training zählen extra)</span></label>
    ${chipGroup("activity", Object.entries(lv).map(([k, l]) => [k, esc(l.split(" (")[0])]), String(o.activity))}
    <p class="note" id="g-act-hint"></p>
    <div class="card" style="text-align:center" id="g-prev"></div>`;
}
function goalsRead(root) {
  return {
    sex: chipVal(root, "sex"), birth_year: +$("#g-by", root).value, height_cm: parseNum($("#g-h", root).value),
    start_weight: parseNum($("#g-sw", root).value), goal_weight: parseNum($("#g-gw", root).value),
    mode: chipVal(root, "mode"), pace: parseNum(chipVal(root, "pace")), activity: parseNum(chipVal(root, "activity")),
  };
}
function bindGoals(root) {
  const lv = S.activity_levels || {};
  const refresh = async () => {
    const v = goalsRead(root);
    $("#g-act-hint", root).textContent = lv[String(v.activity)] || "";
    try {
      const p = await api("/api/budget/preview", { method: "POST", body: v });
      $("#g-prev", root).innerHTML = `<small class="muted">Dein Tagesbudget</small><div style="font-size:2rem;font-weight:800">${p.points} Punkte</div>
        <small>≈ ${num.format(p.target)} kcal · Bedarf ${num.format(p.tdee)} kcal${p.deficit ? ` · Defizit ${num.format(p.deficit)} kcal ≈ ${num1.format(p.pace)} kg/Woche` : ""}</small>
        ${p.floor_hit ? `<p class="note">Untergrenze ${num.format(p.floor)} kcal greift.</p>` : ""}`;
    } catch (e) { $("#g-prev", root).innerHTML = `<small class="muted">${esc(e.message)}</small>`; }
  };
  bindChips(root, refresh);
  $$("input", root).forEach(i => i.addEventListener("change", refresh));
  refresh();
}

function openGoals() {
  openSheet(`<h2>🎯 Ziele und Profil</h2>${goalsForm(S.settings)}<button class="btn primary block" id="g-save">Speichern</button>`, root => {
    bindGoals(root);
    $("#g-save", root).onclick = async () => {
      try { S = await api("/api/settings", { method: "PUT", body: goalsRead(root) }); } catch (e) { return toast(e.message); }
      closeSheet(); toast("Gespeichert"); viewMore();
    };
  }, true);
}

async function loadDevices() {
  try {
    const ds = await api("/api/devices");
    $("#devs").innerHTML = `<ul class="list">${ds.map(d => `<li><span class="ic">📱</span><div class="bd"><b>${esc(d.name)}${d.current ? ' <span class="pill good">dieses</span>' : ""}</b>
      <div class="meta">seit ${fmtDay(d.created.slice(0, 10))} · zuletzt ${d.last_seen ? fmtAgo(d.last_seen) : "–"}</div></div>
      <button class="btn icon small-icon" data-ren="${d.id}" aria-label="Umbenennen">✏️</button>
      <button class="btn small danger" ${d.current ? 'id="logout"' : `data-dev="${d.id}"`}>Abmelden</button></li>`).join("")}</ul>`;
    $("#logout") && ($("#logout").onclick = logout);
    $$("[data-dev]").forEach(b => (b.onclick = async () => { if (!confirm("Gerät abmelden?")) return; await api(`/api/devices/${b.dataset.dev}`, { method: "DELETE" }); loadDevices(); }));
    $$("[data-ren]").forEach(b => (b.onclick = async () => {
      const d = ds.find(x => x.id === +b.dataset.ren);
      const name = (prompt("Neuer Name des Geräts:", d.name) || "").trim();
      if (!name || name === d.name) return;
      try { await api(`/api/devices/${d.id}`, { method: "PUT", body: { name } }); toast("Umbenannt"); }
      catch (e) { toast(e.message); }
      loadDevices();
    }));
  } catch (_) { $("#devs").textContent = "Offline"; }
}

async function logout() {
  if (!confirm("Dieses Gerät abmelden? Zum Weiterarbeiten musst du es danach neu verbinden.")) return;
  try { await api("/api/logout", { method: "POST", body: {} }); }
  catch (e) { if (!(e instanceof AuthError)) return toast(e.message); }
  // zwischengespeicherte Daten (u. a. Gewicht) nicht auf dem Gerät lassen
  try { localStorage.removeItem("fp_state"); } catch (_) { /* egal */ }
  S = null;
  viewLogin();
}

/* ---------- Push ---------- */

function b64ToUint8(b64) {
  const p = "=".repeat((4 - b64.length % 4) % 4);
  const raw = atob((b64 + p).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map(ch => ch.charCodeAt(0)));
}
async function pushStatus() {
  const el = $("#push-state"); if (!el) return;
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) { el.textContent = "Dieser Browser kann keine Push-Nachrichten."; return; }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  el.textContent = sub ? "✅ Auf diesem Gerät aktiv." : (Notification.permission === "denied" ? "❌ Im Browser blockiert – in den Website-Einstellungen erlauben." : "Auf diesem Gerät noch nicht aktiv.");
}
async function enablePush() {
  try {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { toast("Benachrichtigungen nicht erlaubt"); return pushStatus(); }
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToUint8(S.vapid_key) });
    await api("/api/push/subscribe", { method: "POST", body: sub.toJSON() });
    toast("Benachrichtigungen aktiv 🔔");
  } catch (e) { toast("Fehler: " + e.message); }
  pushStatus();
}

/* ---------- Onboarding ---------- */

function viewOnboarding() {
  const o = store("fp_onb") || { step: 0, ...S.settings };
  const steps = [
    () => `<div class="center"><img src="/icons/icon-512.png" width="96" height="96" alt="" style="border-radius:22px"><h1 class="mt">Willkommen bei FitPath</h1>
      <p class="muted">Leichter werden ohne Verbote: ein Punktesystem, das satt machende Lebensmittel belohnt, Schritte und Gewicht automatisch aus Health Connect und eine ehrliche Statistik.</p>
      <p class="muted">Ein paar Angaben für dein Tagesbudget – alles lässt sich später ändern.</p></div>`,
    () => `<h2>Dein Ziel</h2>${goalsForm(o)}`,
    () => `<h2>Anzeige</h2>
      ${chipGroup("display", [["points", "Punkte (empfohlen)"], ["kcal", "Kalorien"]], o.display)}
      <p class="note mt"><b>Punkte</b> rechnen Kalorien, Zucker, gesättigtes Fett und Alkohol ein und ziehen Eiweiß und Ballaststoffe ab. So zählt ein Magerquark weniger als ein Croissant mit gleich vielen Kalorien. Frisches Obst und Gemüse kosten nichts.</p>
      <p class="note"><b>Kalorien</b> zeigen dasselbe Budget in kcal, dazu eine Ampel nach Energiedichte. Umschalten geht jederzeit unter Mehr.</p>
      <p class="note">FitPath ersetzt keine ärztliche Beratung. Das Budget fällt nie unter eine gesunde Untergrenze.</p>`,
  ];
  const step = Math.min(o.step || 0, steps.length - 1);
  view.innerHTML = `<div class="steps">${steps.map((_, i) => `<i class="${i === step ? "on" : ""}"></i>`).join("")}</div>
    <div class="card" id="onb">${steps[step]()}</div>
    <div class="row nowrap">${step ? `<button class="btn" id="back">Zurück</button>` : ""}<button class="btn primary grow" id="nextb">${step === steps.length - 1 ? "Los geht's" : "Weiter"}</button></div>`;
  const root = $("#onb");
  if (step === 1) bindGoals(root); else bindChips(root);
  const collect = () => {
    if (step === 1) Object.assign(o, goalsRead(root));
    if (step === 2) o.display = chipVal(root, "display");
  };
  $("#back") && ($("#back").onclick = () => { collect(); o.step = step - 1; store("fp_onb", o); viewOnboarding(); });
  $("#nextb").onclick = async () => {
    collect();
    if (step === 1 && !(o.start_weight > 30 && o.height_cm > 100 && o.goal_weight > 30)) return toast("Größe und Gewichte angeben");
    if (step < steps.length - 1) { o.step = step + 1; store("fp_onb", o); return viewOnboarding(); }
    const keys = ["sex", "birth_year", "height_cm", "start_weight", "goal_weight", "mode", "pace", "activity", "display"];
    try {
      S = await api("/api/onboarding", { method: "POST", body: { settings: Object.fromEntries(keys.map(k => [k, o[k]])) } });
      store("fp_onb", null); location.hash = "#heute"; render();
    } catch (e) { toast(e.message); }
  };
}

/* ---------- Start ---------- */

function setNet() { $("#netstate").hidden = navigator.onLine; }
window.addEventListener("online", () => { setNet(); flushQueue().then(() => { S = null; render(); }); });
window.addEventListener("offline", setNet);
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState !== "visible" || !S || !$("#sheet").hidden) return;
  try {
    const before = S.today;
    await flushQueue();
    await loadState();
    if (S.today !== before) curDay = null;
    const r = (location.hash || "#heute").slice(1);
    if (r === "heute" || r === "") viewToday();
  } catch (_) { /* egal */ }
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

/* Knöpfe nebeneinander bleiben gleich hoch: Passt der Text nicht in eine Zeile, wird die Schrift
   kleiner (bis 75 %). Reicht das nicht, bricht er wie bisher um, statt abgeschnitten zu werden. */
const FIT_SEL = ".row > .btn:not(.icon), .card-head .btn:not(.icon)";
const FIT_MIN = 0.75;
function fitButtons() {
  for (const b of document.querySelectorAll(FIT_SEL)) {
    if (!b.offsetParent) continue;                       // unsichtbar, z. B. in zugeklapptem <details>
    b.classList.add("fit");
    b.style.fontSize = "";
    if (b.scrollWidth <= b.clientWidth) continue;
    const cs = getComputedStyle(b), base = parseFloat(cs.fontSize);
    const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
    let size = Math.max(base * FIT_MIN, base * (b.clientWidth - pad) / (b.scrollWidth - pad));
    b.style.fontSize = size + "px";
    while (b.scrollWidth > b.clientWidth && size > base * FIT_MIN) { size = Math.max(base * FIT_MIN, size - 0.5); b.style.fontSize = size + "px"; }
    if (b.scrollWidth > b.clientWidth) { b.classList.remove("fit"); b.style.fontSize = ""; }
  }
}
let fitQueued = false;
function queueFit() {
  if (fitQueued) return;
  fitQueued = true;
  requestAnimationFrame(() => { fitQueued = false; fitButtons(); });
}
// Jede neu gezeichnete Ansicht oder jedes Blatt prüfen; fitButtons selbst ändert nur Attribute, löst also nichts erneut aus
new MutationObserver(queueFit).observe(document.body, { childList: true, subtree: true });
addEventListener("resize", queueFit);
document.addEventListener("toggle", queueFit, true);     // <details> aufgeklappt: Knöpfe darin jetzt messbar
setNet();
flushQueue().finally(render);
