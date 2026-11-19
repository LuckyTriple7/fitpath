# Sicherheitsaudit FitPath

| | |
|---|---|
| Datum | 18.11.2026 |
| Geprüfter Stand | `313a4de` (v0.9.0) |
| Umfang | gesamte Anwendung (`app/`), Frontend (`app/static/`), Container- und CI-Konfiguration |
| Methode | manuelles Code-Review + dynamische Prüfung gegen eine Test-Instanz (36 Tests grün) |
| Ergebnis | **keine kritische Lücke**; 4 mittlere, 9 niedrige Befunde |

## Fazit

Für eine selbst gehostete Einzelpersonen-App ist das Sicherheitsniveau **gut bis solide**: Tokens statt Passwörter, Hashes in der Datenbank, CSRF-Schutz, saubere CSP, durchgängig parametrisierte SQL-Queries und ein gehärteter Container. Es wurden **keine Auth-Umgehung, keine SQL-Injection und kein XSS** gefunden.

Die ernsthaften Restrisiken liegen bei **Verfügbarkeit (unauthentifizierter Webhook)**, **Dateirechten und Verschlüsselung der Gesundheitsdaten** sowie **TLS-Absicherung**; dazu kommen Robustheits- und Härtungsthemen.

---

## Befunde

### Übersicht

| ID | Schwere | Thema | Ort |
|---|---|---|---|
| M1 | Mittel | Unauthentifizierter Webhook als DoS-Vektor | `app/main.py`, `app/ingest.py` |
| M2 | Mittel | Gesundheitsdaten weltlesbar, unverschlüsselt | `app/db.py`, `app/backup.py` |
| M3 | Mittel | TLS/HSTS vollständig dem Proxy überlassen | `app/main.py`, `app/auth.py` |
| M4 | Mittel | SSRF-Schutz per DNS-Auflösung (Rebinding) | `app/recipe_import.py` |
| N1 | Niedrig | Kopplung: globale Limits, Code-Phishing | `app/auth.py`, `app/main.py` |
| N2 | Niedrig | Einmal-Link nicht atomar einmalig | `app/auth.py` |
| N3 | Niedrig | Session-Handling (400 Tage, keine Rotation) | `app/auth.py`, `app/main.py` |
| N4 | Niedrig | Unauthentifizierte 500er | `app/ingest.py`, `app/main.py` |
| N5 | Niedrig | Authentifizierte 500er durch fehlende Typprüfung | `app/main.py` |
| N6 | Niedrig | Informationspreisgabe (Version, Konfigzustand) | `app/main.py`, `app/ingest.py` |
| N7 | Niedrig | Kein Mehrbenutzerbetrieb | gesamt |
| N8 | Niedrig | Lieferkette (CI, Pinning, Scanning) | `.github/workflows/image.yml`, `Dockerfile` |
| N9 | Niedrig | Logs und Offline-Cache | `app/main.py`, `app/static/app.js` |

---

### M1 – Unauthentifizierter Webhook ist ein DoS-Vektor

**Ort:** `app/main.py:625-648`, `app/ingest.py:83-91`

- Jede abgelehnte Anfrage schreibt eine Zeile in `ingest_log` – ohne Rate-Limit. Verifiziert: 5 Testanfragen → 5 Zeilen. Ein Angreifer kann die Tabelle und das Log fluten und den einzigen SQLite-Writer beschäftigen.
- Der Body wird **vor** der Signaturprüfung bis 12 MB in den RAM gelesen (`await request.body()`). Bei `mem_limit: 192m` genügen wenige parallele Requests ohne bzw. mit falschem `Content-Length`, um den Container vom OOM-Killer abschießen zu lassen.
- Es gibt keinerlei Throttling pro IP.

**Empfehlung:** Rate-Limit (z. B. 10/min pro IP, global 60/min) vor dem Body-Read; `log_denied` drosseln (max. ein Eintrag pro Minute); Body als Stream mit hartem Limit lesen und die Signatur über den Stream prüfen. Alternativ das Deny-Logging ganz aus dem Request-Pfad nehmen.

### M2 – Gesundheitsdaten liegen weltlesbar auf der Platte

**Ort:** `app/db.py:227-249`, `app/backup.py:20-35`

- Verifiziert: `fitpath.db` wird mit **0644** angelegt, Backups ebenso; das Datenverzeichnis ist bei manuellem `mkdir` typischerweise 0755. Auf dem Host kann damit jeder lokale Benutzer Gewicht, Tagebuch und Heißhunger-Protokoll lesen.
- Keine Verschlüsselung at rest, keine Retention-Löschung für Nutzerdaten; `ingest_log` speichert zusätzlich 14 Tage Roh-Health-Daten.

**Empfehlung:** `os.umask(0o077)` in `db.init()`/`backup.run()`, `os.makedirs(DATA_DIR, mode=0o700)` und `chmod 600` auf DB und Backups. Für Gesundheitsdaten (DSGVO Art. 9) zusätzlich Volume-/Host-Verschlüsselung dokumentieren.

### M3 – TLS wird komplett dem Reverse Proxy überlassen

**Ort:** `app/main.py:41-52`, `app/auth.py:30-32`

- Kein `Strict-Transport-Security`-Header (verifiziert). Caddy/nginx setzen HSTS nicht automatisch.
- Das Cookie heißt `fp_session` ohne `__Host-`-Präfix; `COOKIE_SECURE` lässt sich per Env auf `false` stellen, und `PUBLIC_URL` wird nicht auf `https://` geprüft – ein Fehlsetup fällt nicht auf.

**Empfehlung:** HSTS im Proxy **oder** in der Middleware setzen; `__Host-fp_session` verwenden; beim Start warnen bzw. abbrechen, wenn `PUBLIC_URL` nicht mit `https://` beginnt und `COOKIE_SECURE` aktiv ist.

### M4 – SSRF-Schutz beim Rezept-Import ist umgehbar (DNS-Rebinding)

**Ort:** `app/recipe_import.py:72-106`

- `_public_host()` löst DNS auf, `httpx` löst danach **erneut** auf → klassische TOCTOU-/Rebinding-Lücke; die tatsächlich verbundene IP wird nicht geprüft.
- `100.64.0.0/10` (CGNAT, in manchen Netzen intern) gilt als „erlaubt" (verifiziert). Besser wäre `ip.is_global`.
- Ein IPv6-`getaddrinfo`-Ergebnis mit Zonen-ID (`fe80::1%eth0`) lässt `ip_address()` mit `ValueError` abstürzen → 500.

Ausnutzbar nur mit gültiger Session, daher nicht hoch.

**Empfehlung:** Verbindung über einen Resolver-Hook an die geprüfte IP binden (httpx-Transport mit eigener Auflösung) oder `is_global` plus Allowlist; `ValueError` abfangen.

### N1 – Kopplung: globale Limits und Code-Phishing

**Ort:** `app/auth.py:104-133`, `app/main.py:728-739`

Die Limits (20/min, 30 offen) sind **global**, nicht pro IP – ein Angreifer kann die Kopplung für alle blockieren. Zusätzlich ist der Ablauf anfällig für Social Engineering: Wer ein fremdes Gerät zum Scannen oder Code-Eintippen bewegt, bekommt nach „Zulassen" eine Session. Es gibt kein Gegenstück zum WhatsApp-Sicherheitscode (Bestätigung am neuen Gerät); das UI zeigt nur den User-Agent, der fälschbar ist.

### N2 – Einmal-Link ist nicht atomar einmalig

**Ort:** `app/auth.py:61-69`

`SELECT` → `DELETE`, ohne `rowcount`-Prüfung: Zwei parallele POSTs können beide eine Session erhalten.

**Empfehlung:** `DELETE ... RETURNING` oder zuerst `DELETE` und nur bei `rowcount == 1` fortfahren.

### N3 – Session-Handling

**Ort:** `app/auth.py:30`, `app/main.py:723-725`

400 Tage Gültigkeit, keine Rotation, kein serverseitiges Ablaufdatum, kein Logout des aktuellen Geräts in der UI. Der Login-Token steht im Pfad (`/auth/<token>`) und landet damit in Proxy-Access-Logs und Browser-History; `Referrer-Policy: no-referrer` hilft nur gegen Fremdseiten.

### N4 – Unauthentifizierte 500er

**Ort:** `app/ingest.py:61-76`, `app/main.py:628`

`Authorization: Bearer <nicht-ASCII>` oder `X-Signature: sha256=<nicht-ASCII>` lässt `hmac.compare_digest` mit `TypeError` abstürzen (verifiziert); ein kaputter `Content-Length` lässt `int()` werfen (verifiziert: 500). Kein Datenabfluss, aber Log-Rauschen und ein billiger Fehlerpfad ohne Auth.

### N5 – Authentifizierte 500er durch fehlende Typprüfung

**Ort:** `app/main.py:196`, `:428`, `:573`, `:748`

Alle verifiziert:

- `PUT /api/settings` mit Liste oder `null` → 500
- `POST /api/events` mit `intensity: "abc"` → 500
- `POST /api/log` mit `food_id: "abc"` → 500
- `POST /api/pair/poll` mit Nicht-Objekt-JSON → 500

**Empfehlung:** `TypeError`/`ValueError` jeweils in 400 übersetzen.

### N6 – Informationspreisgabe

**Ort:** `app/main.py:96-98`, `app/ingest.py:63-76`

`/healthz` und `/api/state` liefern die Version (verifiziert: `0.9.0`); die 401-Antwort des Webhooks verrät, ob ein Geheimnis eingerichtet ist. Für ein privates Setup vertretbar, für eine öffentlich erreichbare Instanz unnötig.

### N7 – Kein Mehrbenutzerbetrieb

Jedes gekoppelte Gerät hat Vollzugriff: Geräte löschen und umbenennen, Export, Geheimnis rotieren. Das ist bewusst, muss aber klar dokumentiert sein – die Instanz darf nicht von mehreren Personen geteilt werden.

### N8 – Lieferkette

**Ort:** `.github/workflows/image.yml`, `Dockerfile`

Actions nur per Major-Tag (`@v7`), Basisimage `python:3.13-slim` ohne Digest, keine Hashes in `requirements.txt`, kein Dependency- oder Image-Scanning, keine SBOM. Positiv: Die Workflow-Permissions sind eng gefasst.

### N9 – Logs und Offline-Cache

**Ort:** `app/main.py:398`, `:401`, `app/static/app.js`

KI-Fehler werden inklusive Antworttext geloggt; der Service Worker cached `/` und `app.js`, `localStorage` hält `fp_state` inklusive Gewichtsdaten im Klartext auf dem Gerät.

---

## Was bereits gut ist

- 256-Bit-Tokens, in der Datenbank nur SHA-256-Hashes; `secrets` statt `random`; Kopplungscode mit `secrets.randbelow`.
- CSRF-Schutz über Pflicht-Header (`x-fitpath`) bei allen schreibenden Methoden – ohne CORS-Middleware wirksam; GET-Routen sind (bis auf `last_seen` und den Barcode-Abruf) lesend.
- CSP ohne `unsafe-inline` für Skripte, `frame-ancestors 'none'`, `nosniff`, `no-referrer`, `Permissions-Policy` nur Kamera.
- SQL durchgängig parametrisiert (auch die `IN (...)`-Liste); kein `eval`/`exec`/`pickle`.
- Frontend: `esc()` konsequent; die wenigen unescaped Interpolationen sind Zahlen, Konstanten oder serverseitig erzeugtes SVG mit Env-Daten.
- Webhook: HMAC über den Rohbody mit `compare_digest`, alternativ Bearer; das Secret wird nie über `public_settings` ausgeliefert.
- SSRF-Grundschutz (Schema, Ports 80/443, private/loopback/link-local/reserved, max. 3 Redirects, 3 MB) und Rate-Limit für Open Food Facts.
- Container: non-root (UID 10001), `read_only`, `cap_drop: ALL`, `no-new-privileges`, `mem_limit`, Port nur auf `127.0.0.1`, VAPID-Key `0600`.
- Keine Secrets im Repo; `.dockerignore` schließt `.env` aus; `--no-server-header`.

---

## Priorisierte To-dos

1. **M1:** Rate-Limit und Body-Streaming-Limit vor der Signaturprüfung, Deny-Logging drosseln.
2. **M2:** `umask(0o077)`, Verzeichnis 0700, DB und Backups 0600.
3. **M3:** HSTS (Proxy oder App), `__Host-`-Cookie, HTTPS-Check für `PUBLIC_URL`.
4. **M4:** SSRF-Check an die tatsächlich verbundene IP binden (`is_global`, `ValueError` abfangen).
5. **N2/N4/N5:** Robustheits-Patches (atomares Löschen des Link-Tokens, `TypeError`/`ValueError` → 400).
6. **N1:** Kopplungs-Limits pro IP und ein Bestätigungsschritt am neuen Gerät.
7. **N8:** Actions per Commit-SHA pinnen, Image-Digest pinnen, `pip-audit`/Trivy in die CI.

---

## Stand der Umsetzung (19.11.2026)

| ID | Stand |
|---|---|
| M1 | **behoben:** Body mit hartem Limit als Stream (auch chunked), 429 nach 20 Ablehnungen pro Minute vor dem Lesen, höchstens 2 parallele Uploads, Ablehnungen höchstens einmal pro Minute im Protokoll |
| M2 | **akzeptiert:** Server wird nur vom Betreiber genutzt. Neu bewerten, wenn Backups den Server verlassen |
| M3 | **akzeptiert:** NPMPlus übernimmt HTTPS und HSTS. Voraussetzung: HSTS am Proxy-Host aktiv, `COOKIE_SECURE` bleibt `true`, `PUBLIC_URL` mit `https://` |
| M4 | **behoben:** `is_global` statt Einzelprüfungen (sperrt CGNAT), ungültige Adressen abgefangen (v0.11.1). Verbindung direkt zur geprüften IP mit Host-Header und `sni_hostname`, kein zweites Auflösen mehr (v0.11.2). Hinweis: Eine IPv6-Zonen-ID führt unter Python ≥ 3.9 nicht zum `ValueError`, `ip_address()` versteht sie |
| N2 | **behoben:** `DELETE … RETURNING` |
| N4 | **behoben:** `compare_digest` über Bytes, ungültige `Content-Length` → 400 |
| N5 | **behoben:** alle JSON-Endpunkte über `_json()` (Limit, Typprüfung), Feldfehler → 400 |
| N1 | **behoben:** Limits je IP (5/min, 3 offen) zusätzlich zu den globalen (60/min, 100 offen). Client-IP aus `X-Forwarded-For`/`X-Real-IP` nur bei Verbindung aus privatem Netz. Freigabedialog zeigt „selbes Netz“ oder die fremde Adresse mit Warnung (v0.11.2). Restrisiko: Wer aus demselben Netz kommt oder den Nutzer überredet, trotz Warnung zuzulassen |
| N3 | **teilweise:** Abmeldung nach 180 Tagen ohne Nutzung (`SESSION_IDLE_DAYS`), „Abmelden“ für das aktuelle Gerät (v0.12.0). Bewusst nicht: Rotation des Session-Tokens (bei einer Ein-Personen-App kaum Nutzen). Login-Token im Pfad bleibt (einmalig, 15 Minuten gültig) |
| N6 | **behoben:** `/healthz` ohne Version, Webhook-401 einheitlich „nicht autorisiert“ (Grund nur im Protokoll für angemeldete Geräte) (v0.12.2) |
| N7 | **dokumentiert:** README-Abschnitt „Sicherheit“: eine Instanz pro Person (v0.12.2) |
| N8 | **behoben:** Actions per Commit-SHA, Basisimage per Digest, `pip-audit` in der CI (auch wöchentlich), Dependabot für Actions, Docker und pip. Der erste `pip-audit`-Lauf fand 7 Lücken in Starlette 0.46.2 (u. a. CVE-2025-62727, Range-DoS auf `FileResponse` ohne Anmeldung). Behoben durch FastAPI 0.165.0 / Starlette 1.10.0 (v0.12.2). Bewusst nicht: Hashes in `requirements.txt`, SBOM, Image-Scan mit Trivy |
| N9 | **behoben/akzeptiert:** KI-Fehler ohne Antworttext im Log (v0.12.2). Der Offline-Stand im `localStorage` bleibt (nötig für den Offline-Betrieb), „Abmelden“ löscht ihn (v0.12.0) |

### Nachtrag v0.10.0: Foto-Endpunkt `/api/ai/label`

Nicht im ursprünglichen Umfang. Befunde: Größenprüfung nur über `Content-Length`, Nicht-Objekt-JSON → 500 (beides behoben, Limit 8 MB über `_json()`). Kein Limit für KI-Aufrufe (nur mit gültiger Session ausnutzbar, offen). Die Fotos gehen an den KI-Anbieter hinter LiteLLM und werden in FitPath nicht gespeichert.

---

## Grenzen der Prüfung

- Geprüft wurde der Code, nicht die konkrete Produktionsumgebung (Reverse-Proxy-Konfiguration, Firewall, Host-Härtung, Backup-Aufbewahrung).
- Kein Penetrationstest gegen eine laufende Instanz; die dynamischen Prüfungen liefen gegen eine lokale Test-Instanz mit `TestClient`.
- Abhängigkeiten wurden für den ursprünglichen Bericht nicht auf bekannte CVEs gescannt. Nachgeholt am 19.11.2026 mit `pip-audit` (siehe N8).
