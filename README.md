# FitPath

Persönliche Abnehm-App als PWA für eine Person, selbst gehostet mit Docker (Schwester-App von QuitPath). Statt reinem Kalorienzählen gibt es ein eigenes Punktesystem (umschaltbar auf kcal). Schritte, Gewicht und Körperfett kommen automatisch aus Health Connect.


## Installation

Voraussetzungen: Docker mit Compose, eine Domain mit HTTPS über einen Reverse Proxy (PWA, Kamera, Push und der Health-Connect-Webhook brauchen HTTPS), Zugriff auf das private Image.

```bash
# einmalig: am privaten Image-Speicher anmelden
# (GitHub → Settings → Developer settings → Personal access tokens (classic), nur Recht read:packages)
docker login ghcr.io -u <github-benutzer>

mkdir -p /opt/docker/stacks/fitpath && cd /opt/docker/stacks/fitpath
# compose.yml und .env.example aus diesem Repo hierher kopieren
cp .env.example .env            # FITPATH_PUBLIC_URL anpassen, KI-Key optional
mkdir -p data && chown 10001 data
docker compose up -d
docker compose logs fitpath     # erwartet: "BLS importiert: 7140 Lebensmittel"
docker compose exec fitpath python -m app.cli link Handy     # Anmeldelink erzeugen
```

Den Link auf dem Handy öffnen, **Verbinden** tippen, Onboarding durchgehen, „Zum Startbildschirm hinzufügen“.

Reverse Proxy: auf `http://127.0.0.1:8800` weiterleiten (Port über `FITPATH_PORT` änderbar). Bot-Schutz (z. B. Anubis) für diese Adresse ausschalten, sonst scheitern API-Aufrufe, Service Worker, Push-Klicks und der Health-Connect-Webhook. Erlaubte Größe von Anfragen mindestens 16 MB (z. B. nginx `client_max_body_size 16m;`), sonst bricht das Nachladen der Health-Connect-Vergangenheit mit `413` ab.

Soll der Container ein bestehendes Docker-Netz erreichen (z. B. das des KI-Proxys), `compose.override.example.yml` nach `compose.override.yml` kopieren und anpassen. Die Datei lädt `docker compose` (auch Dockge) automatisch mit.

## Update

Bei jedem Push auf `main` baut GitHub Actions nach den Tests ein neues Image (`linux/amd64` und `linux/arm64`) und legt es als `ghcr.io/luckytriple7/fitpath:latest` ab, dazu ein Tag je Commit (`sha-…`) und je Version (`v1.2.3` → `1.2.3`). Neue Datenbank-Spalten ergänzt die App beim Start selbst.

```bash
cd /opt/docker/stacks/fitpath && docker compose pull && docker compose up -d
```

In Dockge reicht **Update**. Zurück auf einen älteren Stand: in `compose.yml` statt `latest` ein `sha-…`-Tag eintragen.

## Funktionen

| Bereich | Inhalt |
|---|---|
| Heute | Ring mit übrigen Punkten (oder kcal), Budget, Aktivitätspunkte, Wochenreserve, Wochenleiste Mo–So, Mahlzeiten (Frühstück, Mittag, Abend, Snacks), „Nochmal“-Leiste (ein Tipp erfasst die zuletzt gegessene Menge), Schritte, Trendgewicht, Tage vor und zurück |
| Erfassen | Suche in rund 7.140 BLS-Lebensmitteln plus eigenen, Listen „Zuletzt“, „Favoriten“, „Eigene“, Barcode per Kamera (`BarcodeDetector` in Chrome für Android, sonst Zahl eintippen), Portionen (Scheibe, Stück, Glas …) mit Anzahl, Live-Vorschau mit Erklärung der Punkte, eigene Portionen merken, 0-Punkte-Schalter je Lebensmittel |
| Eigene Lebensmittel | Nährwerte je 100 g von der Packung, optional mit Barcode; unbekannte Barcodes landen direkt im Formular |
| Wie gestern | Leere Mahlzeit zeigt „Gestern: …“ mit Knopf **↺ Wie gestern**: übernimmt alle Einträge dieser Mahlzeit vom Vortag, mit „Rückgängig“ |
| Gerichte | Aus Zutaten (Suche, Gramm je Zutat), Portionen, optional Gewicht nach dem Kochen; erscheint in Suche und unter „Eigene“ und wird wie ein Lebensmittel erfasst. 0-Punkte-Zutaten bleiben 0 Punkte |
| Per Text (KI) | ✨ im Erfassen-Blatt: „2 Brötchen mit Butter und Gouda, Kaffee mit Milch“ → KI zerlegt in Lebensmittel mit Menge, FitPath schlägt je Posten 5 Treffer aus der eigenen DB vor; Auswahl, Gramm und Mahlzeit änderbar, erfasst wird erst nach Bestätigung |
| Gewicht | Trendgewicht (geglättet), Tempo kg/Woche, BMI, Ziel mit Meilensteinen (−5 %, −10 %), Verlauf 30/90/365 Tage, Körperfett und Bauchumfang |
| Statistik | Punkte oder kcal pro Tag gegen Budget, Tage im Budget, Ø Eiweiß/Ballaststoffe mit Richtwert, Energiedichte-Ampel, größte Punkte-Lieferanten, Schritte |
| Health Connect | Webhook für Life Dashboard Companion: Schritte (Tagessummen), Gewicht, Körperfett, Löschungen, Verlauf nachladen |
| Push | Wiegen (Wochentage wählbar), „noch nichts erfasst“ am Mittag, Abend-Check; Ruhezeiten und Höchstzahl pro Tag |
| Offline | App-Hülle und letzter Zustand aus dem Cache, Einträge warten in einer Warteschlange |

## Punktesystem

Je Eintrag aus den Nährwerten der gegessenen Menge (Gramm):

```
Punkte = kcal/35 + ges. Fett/4 + Zucker/10 + Alkohol/8 − Eiweiß/10 − Ballaststoffe/5
```

nicht unter 0, auf ganze Punkte gerundet. Beispiele: Croissant 60 g ≈ 9, Cola 0,33 l ≈ 7, Bier 0,5 l ≈ 8, Reis gekocht 200 g ≈ 7, Nüsse 30 g ≈ 5, Magerquark 250 g ≈ 3, Hähnchenbrust 150 g ≈ 1.

- **0 Punkte**: frisches Obst und Gemüse, Pilze, Sprossen, gegarte Hülsenfrüchte, erkannt über die BLS-Hauptgruppe (F, G, K7, H6, H7) und höchstens 90 kcal/100 g; Saft, Trockenobst, Gezuckertes, Frittiertes ausgenommen. Pro Lebensmittel änderbar.
- **kcal-Ziel**: Grundumsatz nach Mifflin-St Jeor × Aktivitätsfaktor (1,2 bis 1,725) − Defizit (Tempo × 7.700 kcal ÷ 7). Untergrenze 1.500 kcal (Männer) bzw. 1.200 kcal (Frauen), Tempo höchstens 1 % des Körpergewichts pro Woche. Gerechnet mit dem Trendgewicht.
- **Tagesbudget** = (kcal-Ziel − 200) ÷ 40. Satt machende Kost bringt etwa 45–50 kcal je Punkt, typische Mischkost gut 30; mit 40 bleibt bei guter Auswahl ein Defizit.
- **Wochenreserve**: Von jedem vergangenen Tag der Woche mit Einträgen wandern bis zu 4 ungenutzte Punkte (bzw. 140 kcal) in die Reserve, ein überzogener Tag zieht ab. Tage ohne Eintrag zählen nicht. Montag beginnt neu.
- **Aktivität**: Schritte über der Grundlinie (Standard 5.000) × Gewicht × 0,0005 kcal, davon 50 % gutgeschrieben. Die aktiven kcal aus Health Connect werden gespeichert, aber nicht verrechnet (zu unzuverlässig).

Gerichte speichern zusätzlich Rohpunkte je 100 g (`foods.pts_100`), berechnet ohne 0-Punkte-Zutaten; ein Eintrag übernimmt sie als `food_log.points_raw`. Wird ein Gericht später geändert, bleiben schon erfasste Einträge wie sie waren.

Alle Faktoren stehen in `app/points.py`. Einträge speichern die Nährwerte als Schnappschuss; Punkte werden immer daraus berechnet, eine geänderte Formel rechnet also alte Tage mit. Die Vorschau im Browser (`app/static/app.js`, `rawPoints`) nutzt dieselbe Formel.

## Datenquellen

| Quelle | Lizenz | Weg |
|---|---|---|
| Bundeslebensmittelschlüssel (BLS) 4.0 | CC BY 4.0, Herausgeber Max Rubner-Institut | `seed/bls40.csv.gz` (210 KB, 7.140 Lebensmittel, Werte je 100 g), beim ersten Start importiert |
| Open Food Facts | ODbL | nur Barcode-Abfrage (`/api/v2/product/<code>`), Ergebnis lokal gespeichert; höchstens 10 Abfragen/min (erlaubt 15). Keine Suche über die API (deren Regeln verbieten Suche beim Tippen) |

Zitierweise BLS: Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS), Version 4.0 – Deutsche Nährstoffdatenbank. Karlsruhe. DOI: 10.25826/Data20251217-134202-0

Seed neu erzeugen (z. B. bei BLS 4.1): ZIP von <https://www.blsdb.de/download> laden, dann auf einem Rechner mit `openpyxl`:

```bash
python tools/bls_convert.py BLS_4_0_Daten_2025_DE.xlsx seed/bls40.csv.gz
```

Danach im Container `python -m app.cli import-bls` (eigene Favoriten, Portionen und 0-Punkte-Schalter bleiben erhalten).

Die Suche läuft im Speicher, nicht per Datenbank-Volltext: Deutsche Komposita tragen das Hauptwort hinten („Roggenbrot“ ist Brot, „Brotaufstrich“ nicht). Ein Treffer am Wortende des ersten Begriffs zählt deshalb fast so viel wie ein exaktes Wort. Dazu kommen Synonyme (`SYNONYMS` in `app/foods.py`, z. B. „brezel“ → „Laugengebäck mit Hagelsalz“, „hüttenkäse“ → „Körniger Frischkäse“, „nudeln“ → „Teigwaren eifrei, gekocht“; bei Nudeln, Reis und Kartoffeln steht die gekochte Variante vorn), ein Bonus, wenn der Name genau dem Suchwort entspricht, Favoriten und Häufigkeit.

## Health Connect

Schritte, Gewicht und Körperfett schickt die Android-App **Life Dashboard Companion** (F-Droid, MIT, Repo `owen282000/life-dashboard-companion-app`) direkt an FitPath, ohne Home Assistant.

1. In Life Dashboard Health-Connect-Zugriff für Schritte, Gewicht, Körperfett, aktive Kalorien erlauben.
2. In FitPath **Mehr → Health Connect → Einrichten** (später **Koppeln**). Am PC erscheint ein QR-Code: mit der Handy-Kamera oder in Life Dashboard unter **Add destination → Scan a pairing code** scannen. Ist FitPath auf dem Handy offen, öffnet **In Life Dashboard öffnen** die Kopplung direkt. Dort **Pair** tippen.
3. Life Dashboard schickt sofort einen signierten Test-Ping; in FitPath steht „Test empfangen“. **Send history** lädt die Vergangenheit nach.
4. **Daily totals in payload** anlassen (Standard), Intervall 15 Minuten.

Das Geheimnis (43 Zeichen) von Hand abzutippen geht unter **Von Hand eintragen**, ist aber fehleranfällig (falsches Zeichen = 401). Der Koppel-Link folgt `docs/pairing.md` von Life Dashboard (`https://owen282000.github.io/life-dashboard-companion-app/pair#v=1&url=…&secret=…`, alles im Fragment, das nie an einen Server geht); der QR-Code entsteht serverseitig mit `segno`. Abgelehnte Lieferungen landen mit Grund (keine Signatur, Signatur passt nicht, kein Geheimnis eingerichtet) in `ingest_log` und unter **Letzte Lieferungen**; die 401-Antwort nennt den Grund ebenfalls.

Technik (`app/ingest.py`): Signatur `X-Signature: sha256=<HMAC-SHA256>` über den rohen Body; alternativ `Authorization: Bearer <Geheimnis>` als eigener Header. Schritte kommen aus `daily_totals` (Aggregat-API von Health Connect, keine Doppelzählung von Handy und Uhr); für ein Datum gilt die Lieferung mit der höchsten `sequence`, eine schon verarbeitete `sequence` wird übersprungen. `weight` und `body_fat` werden über ihre `uuid` gespeichert, `deleted_records` entfernt sie wieder. Die letzten Lieferungen (14 Tage, Rohdaten gekürzt auf 32 KB) stehen in der Tabelle `ingest_log` und unter **Mehr → Health Connect → Letzte Lieferungen**.

Größe: Eine Lieferung kann einige MB haben (vor allem beim Nachladen der Vergangenheit). FitPath nimmt bis 12 MB an. Zeigt das Zustellprotokoll der App `413`, im Reverse Proxy die erlaubte Größe erhöhen (z. B. `client_max_body_size 16m;`).

## KI und Datenschutz

Erfassen per Text läuft optional über einen OpenAI-kompatiblen Proxy wie LiteLLM (`FITPATH_LITELLM_URL`, `FITPATH_LITELLM_KEY`, Modell `claude-haiku-5-5`, Header `x-caveman-style: off`, keine `temperature`). Ohne Key (`FITPATH_LITELLM_KEY` leer) ist ✨ ausgeblendet. An die KI geht **nur der eingegebene Text**, keine weiteren Daten aus der App. Die KI liefert Suchbegriffe in BLS-Sprache und geschätzte Mengen (`app/ai.py`, `PARSE_SYSTEM`); welches Lebensmittel erfasst wird, entscheidet die Suche in der eigenen DB und am Ende der Nutzer.

Bei LiteLLM einen eigenen virtuellen Key mit kleinem Budget anlegen, der nur das gewählte Modell darf.

## Anmeldung

Kein Passwort. Der Server erzeugt einen Einmal-Link, 15 Minuten gültig, nur einmal nutzbar. Der Link öffnet zuerst eine Bestätigungsseite; eingelöst wird er erst mit **Verbinden** (POST). Grund: Messenger und Browser rufen Links für die Vorschau per GET ab und hätten ihn sonst verbraucht, bevor das Handy ihn öffnet. Danach bleibt das Gerät 400 Tage per Session-Cookie angemeldet (`HttpOnly`, `Secure`, `SameSite=Lax`). In der DB liegen nur SHA-256-Hashes.

```bash
docker compose exec fitpath python -m app.cli link Handy     # Link erzeugen
docker compose exec fitpath python -m app.cli devices        # Geräte
docker compose exec fitpath python -m app.cli revoke <id>    # Gerät abmelden
docker compose exec fitpath python -m app.cli rename <id> PC # Gerät umbenennen
docker compose exec fitpath python -m app.cli import-bls     # BLS-Seed neu einlesen
```

Weitere Geräte lassen sich in der App unter **Mehr → Geräte** verbinden und dort mit ✏️ umbenennen. Der Name kommt sonst aus dem Link (`link Handy` heißt „Handy“, egal welches Gerät ihn öffnet), ohne Namen aus dem Browser.

Uhrzeiten und Zahlen gibt die App unabhängig von der Browsersprache ein: Uhrzeiten als eigenes 24-Stunden-Feld (HH:MM, „2030“ wird 20:30), Kommazahlen mit Komma oder Punkt, Tage als deutsche Auswahl. Die eingebauten Felder `type="time"`/`type="date"` zeigen in einem englischen Browser AM/PM bzw. MM/TT.

## Dateien

| Datei | Inhalt |
|---|---|
| `app/main.py` | FastAPI: Routen, Validierung, Sicherheits-Header (CSP, Kamera nur für die eigene Seite) |
| `app/db.py` | SQLite-Schema, Einstellungen, Zeitfunktionen |
| `app/points.py` | Punkte-Formel, 0-Punkte-Regeln, kcal-Ziel, Budget, Aktivität, Wochenreserve |
| `app/foods.py` | BLS-Import, Suche, Portionen, eigene Lebensmittel, Open-Food-Facts-Barcodes |
| `app/diary.py` | Tagessummen, Übersicht „Heute“, Verlauf für die Statistik |
| `app/body.py` | Trendgewicht, Tempo, Meilensteine |
| `app/ingest.py` | Health-Connect-Webhook, Koppel-Link, Diagnose |
| `app/ai.py` | Erfassen per Text über LiteLLM |
| `app/push.py` | VAPID (erzeugt beim ersten Start), Erinnerungen alle 5 Minuten |
| `app/auth.py`, `app/cli.py`, `app/backup.py` | Einmal-Links, Geräte, Kommandozeile, tägliche Sicherung (aus QuitPath) |
| `app/static/` | PWA: `index.html`, `app.js`, `styles.css`, `sw.js`, Manifest, Icons |
| `seed/bls40.csv.gz` | BLS 4.0 in kompakter Form |
| `tools/bls_convert.py` | BLS-Excel → Seed (nur lokal, braucht `openpyxl`) |
| `tests/` | `pytest`: Formel, Budget, Reserve, Trend, Webhook, Gerichte, KI-Erfassung, API-Durchstich (läuft auch in GitHub Actions vor dem Image-Bau) |
| `.github/workflows/image.yml` | Tests, dann Image für amd64/arm64 nach ghcr.io |

Tests lokal: `python -m venv venv && venv/bin/pip install -r requirements.txt pytest && venv/bin/python -m pytest -q tests`

Daten: `./data` im Stack-Ordner (`fitpath.db`, `vapid_private.pem`); diesen Ordner ins Backup aufnehmen. Die App legt täglich um 23:20 eine konsistente Kopie nach `data/backup/fitpath-JJJJ-MM-TT.db` (14 Tage). Export als JSON unter **Mehr → Daten**.

Wiederherstellen: Container stoppen, gewünschte Kopie nach `data/fitpath.db` kopieren (Eigentümer UID `10001`), `fitpath.db-wal` und `fitpath.db-shm` löschen, Container starten.


## Hinweis

FitPath ersetzt keine ärztliche Beratung. Die Untergrenzen beim kcal-Ziel und beim Tempo sind bewusst fest eingebaut.
