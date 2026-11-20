# Changelog

Alle nennenswerten Änderungen an FitPath. Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/): Hauptversion bei Änderungen, die beim Update Handarbeit brauchen, Nebenversion bei neuen Funktionen, Patch bei Fehlerbehebungen. Solange die Version mit 0 beginnt, ist FitPath noch in schneller Entwicklung.

Neue Einträge kommen unter „Unveröffentlicht“. `python tools/release.py X.Y.Z` macht daraus eine Version. Versionen vor 0.4.0 entstanden im früheren Sammel-Repo und haben hier keinen Git-Tag.

## [Unveröffentlicht]

### Behoben
- Suche auf dem iPhone: Schickt die Tastatur „ö“, „ä“, „ü“ als zwei Zeichen (Buchstabe + Trema), fand die Suche nichts. Das wird jetzt vereinheitlicht.
- Synonyme greifen schon beim Tippen (ab 6 Zeichen, z. B. „Pizzabröt“), mit Bindestrich („Pizza-Brötchen“) und mit ae/oe/ue („Pizzabroetchen“, „Kaese“). Vorher nur beim vollständigen Wort.

## [0.22.1] – 2026-11-20

### Behoben
- „Pizzabrötchen“ (auch „Pizza Brötchen“, „Pizzasemmel“) findet jetzt die Pizzabaguettes aus dem BLS (mit Tomaten und Käse, mit Kochschinken, mit Gemüse und Schafskäse).
- Pizzabaguette bot „1 Pizza“ (350 g) als Portion an. Jetzt: „1 Pizzabrötchen (Hälfte)“ mit 75 g und „½ Pizzabaguette“ mit 125 g.

## [0.22.0] – 2026-11-20

### Neu
- **💡 Passt noch** auf Heute (ab 15 Uhr, ab 2 übrigen Punkten bzw. 70 kcal): Vorschläge aus deinen Favoriten, zuletzt Gegessenem und gespeicherten Mahlzeiten in der üblichen Menge, die in die übrigen Punkte passen. Satt machendes zuerst (grüne Ampel, viel Eiweiß), dazu ein 0-Punkte-Lebensmittel (sonst ein Apfel). Ein Tipp erfasst, mit „Rückgängig“.

## [0.21.0] – 2026-11-20

### Neu
- **Gespeicherte Mahlzeiten**: Bei einer Mahlzeit mit Einträgen auf ☆ tippen und als „Mein Frühstück“ o. Ä. merken. Ist die Mahlzeit leer, steht sie dort als Chip bereit, ein Tipp erfasst alles (mit „Rückgängig“). Im Erfassen-Fenster unter „⭐ Mahlzeiten“ lässt sich vorher einzelnes weglassen und die Mahlzeit bearbeiten oder löschen. Gleicher Name ersetzt die alte, so lässt sie sich ergänzen. Die Nährwerte kommen beim Erfassen immer frisch aus der Datenbank.
- **Prognose fürs Zielgewicht**: Gewicht-Seite und Gewichtskarte auf Heute zeigen, wann das Ziel beim aktuellen Tempo ungefähr erreicht ist („etwa Mitte März“). Grundlage ist der Trend der letzten drei Wochen, vorher das geplante Tempo. Schneller als 1 % pro Woche wird nicht gerechnet, und bei einem Plateau gibt es keine Prognose.

## [0.20.0] – 2026-11-20

### Neu
- **Einkaufsmodus** (im Scan-Fenster oder über `#einkauf`): Die Kamera bleibt an, jedes gescannte Produkt landet mit Punkten je 100 g, je Portion und je Packung in einer Liste. Antippen öffnet das Erfassen, „Zurück zum Einkauf“ führt mit der Liste zurück. Der Bildschirm bleibt dabei an, wo der Browser es unterstützt.
- Mehr als 10 neue Produkte pro Minute: Hinweis „Bitte kurz warten“ mit Countdown, die Produkte werden danach automatisch nachgeladen (Limit von Open Food Facts). Schon bekannte Produkte gehen sofort.
- Packungsgröße aus Open Food Facts wird gespeichert (für neu gescannte Produkte).

### Geändert
- Gescannte Produkte erscheinen unter Erfassen → „Eigene“ erst, wenn sie einmal erfasst, als Favorit markiert oder mit eigener Portion versehen wurden. Nur angeschaute Produkte bleiben gespeichert (der nächste Scan geht sofort) und sind über die Suche zu finden.

## [0.19.0] – 2026-11-20

### Neu
- Statistik zeigt das Training: Trainingstage, Trainingszeit, gutgeschriebene Punkte (oder kcal), Minuten pro Tag als Balken (grün ab 20 Minuten) und eine Liste je Sportart.
- „So rechnet FitPath“ (Mehr → Anzeige) erklärt die Trainingspunkte.

## [0.18.1] – 2026-11-20

### Neu
- Im Ring auf Heute steht unter „übrig“ jetzt auch, wie viel heute schon verbraucht ist (Punkte oder kcal).

## [0.18.0] – 2026-11-20

### Neu
- Barcode-Scanner auf dem iPhone (Safari, auch als installierte App) und in Firefox: Ohne eingebaute Erkennung lädt FitPath beim ersten Scannen die Erkennung ZXing als WebAssembly vom eigenen Server (rund 1 MB, danach im Cache). Android nutzt weiter die eingebaute.
- **📸 Foto vom Barcode**: öffnet die Kamera-App, der Barcode wird aus dem Foto gelesen. Hilft, wenn der Live-Scan nicht scharf stellt oder die Kamera im Browser nicht erlaubt ist.

### Behoben
- Bei Lebensmitteln ohne Portionen (z. B. Weintraube) stand ein Zähler mit „1“ da, Plus und Minus taten nichts. Ausgeblendete Elemente bleiben jetzt wirklich unsichtbar.
- Weintrauben haben Portionen: 1 Handvoll (80 g) und 1 Schale (150 g).

### Sicherheit
- Die CSP erlaubt zusätzlich `'wasm-unsafe-eval'` (nur WebAssembly übersetzen, kein `eval()` für JavaScript).

## [0.17.0] – 2026-11-20

### Neu
- Training bringt Aktivitätspunkte. In der Karte „Schritte“ gibt es **＋ Training**: Sportart (15 zur Wahl, darunter Schwimmen, Radfahren, Laufen, Krafttraining, Yoga, Aquafitness), Dauer und Intensität, mit Vorschau der Punkte. Gezählt wird nur der Verbrauch über Ruhe, davon die Hälfte, höchstens 15 Punkte am Tag.
- Einheiten von der Uhr kommen automatisch über Health Connect. Dafür in Life Dashboard den Zugriff auf „Exercise“ erlauben. Sportart und Intensität lassen sich in FitPath ändern, Löschen blendet eine Einheit dauerhaft aus.
- Keine Doppelzählung: Spazieren zählt über die Schritte, bei Laufen und Wandern werden die schon gezählten Schritte abgezogen. Haben zwei Apps dieselbe Einheit geschrieben, zählt sie einmal („doppelt“).
- Trainingstage geben 10 XP (ab 20 Minuten, Spazieren zählt nicht), dazu die Abzeichen „Erstes Training“, „10 Trainingstage“ und „5× schwimmen“.

## [0.16.0] – 2026-11-20

### Geändert
- „Wie gestern“ auf der Startseite ist jetzt ein kleiner ↺-Knopf neben dem +, überall gleich groß. Ein Tipp öffnet ein Fenster mit den Einträgen von gestern. Was du nicht nochmal willst, nimmst du mit ✕ raus, der Rest wird übernommen. Gestern bleibt dabei unverändert.
- Portionen gehen in halben Schritten (0,5 · 1 · 1,5 …): beim Erfassen mit dem Portions-Zähler und bei eigenen Gerichten (anlegen und per Link übernehmen).

## [0.15.1] – 2026-11-19

### Behoben
- Knöpfe nebeneinander (z. B. „Gericht anlegen“ und „Eigenes Lebensmittel“) waren auf dem Handy unterschiedlich hoch, weil langer Text umbrach. Jetzt bleiben sie einzeilig und gleich hoch, die Schrift wird bei Bedarf kleiner (bis 75 %). Reicht das nicht, bricht der Text um, und die Knöpfe in der Zeile bleiben trotzdem gleich hoch.

## [0.15.0] – 2026-11-19

### Hinzugefügt
- **Auswärts essen:** Neuer Tab **🍽️ Auswärts** beim Erfassen mit 38 fertigen Tellern in typischen Restaurant-Größen, von Döner und Currywurst über Gyros, Schnitzel und Pizza bis Bami Goreng und Sushi. Größe klein, normal oder groß. Die Teller sind aus BLS-Bausteinen zusammengesetzt, Pfannengerichte bekommen einen Fettzuschlag. Die Zusammensetzung ist einsehbar, die Teller finden sich auch über die Suche.

## [0.14.0] – 2026-11-19

### Hinzugefügt
- **Echter Bedarf** in der Statistik: Aus den Einträgen und dem Gewichtsverlauf der letzten 28 Tage schätzt FitPath, wie viel du wirklich verbrauchst (mit ± kcal und Sicherheitsgrad), und vergleicht das mit der Formel. Bei mindestens 100 kcal Abweichung gibt es den Knopf **Budget anpassen**. Er setzt eine Korrektur des Bedarfs (höchstens ± 500 kcal), die sich jederzeit zurücksetzen lässt. Braucht 14 Tage mit Einträgen und 6 Wiegewerten.

## [0.13.0] – 2026-11-19

### Geändert
- Python 3.15 statt 3.13 im Image (Basisimage `python:3.15-slim`, per Digest gepinnt).
- HTTP-Client `httpx` durch `httpx2` ersetzt. Das ist die von Pydantic gepflegte Fortführung, `httpx` bekam seit Dezember 2024 kein stabiles Release mehr. Die API ist gleich, Starlette empfiehlt `httpx2` bereits.
- CI testet mit der Python-Version aus dem Dockerfile. Ein Dependabot-PR für ein neues Basisimage wird damit auch mit der neuen Version getestet. Test-Werkzeuge stehen in `requirements-dev.txt` und werden ebenfalls von Dependabot aktualisiert.

## [0.12.2] – 2026-11-19

### Sicherheit
- Abhängigkeiten aktualisiert: FastAPI 0.165.0 (bringt Starlette 1.10.0), Uvicorn 0.54.0, pywebpush 2.5.0, tzdata 2026.6. Starlette 0.46.2 hatte bekannte Lücken, für FitPath relevant vor allem CVE-2025-62727: Ein präparierter `Range`-Header konnte die Auslieferung der App-Dateien ohne Anmeldung ausbremsen (Audit N8).
- CI: Actions per Commit-SHA und Basisimage per Digest gepinnt, `pip-audit` prüft bei jedem Lauf und wöchentlich auf bekannte Lücken, Dependabot schlägt Updates vor (Audit N8).
- `/healthz` verrät die Version nicht mehr, der Webhook antwortet bei Ablehnung nur „nicht autorisiert“ (der Grund steht weiter unter **Mehr → Health Connect**) (Audit N6).
- KI-Fehler landen ohne Antworttext im Log, der die Eingabe wiederholen konnte (Audit N9).

### Geändert
- Die Version neben dem Logo erscheint erst nach der Anmeldung.
- README: neuer Abschnitt „Sicherheit“ (eine Instanz pro Person, HTTPS über den Proxy, Daten auf Server und Gerät) (Audit N7).

## [0.12.1] – 2026-11-19

### Behoben
- Heute: Die Gewichtskarte zeigte nur das Trendgewicht. Das bewegt sich bewusst langsam (geglättet), deshalb sah ein neuer Wiegewert so aus, als wäre er nicht angekommen. Jetzt steht darunter auch der letzte Wert der Waage mit Datum („Waage heute: 93,8 kg“).

## [0.12.0] – 2026-11-19

### Hinzugefügt
- **Mehr → Geräte:** „Abmelden“ jetzt auch für das Gerät, an dem du gerade sitzt. Löscht Session und Push-Abo und entfernt die zwischengespeicherten Daten aus dem Browser.

### Sicherheit
- Geräte, die 180 Tage nicht benutzt wurden, werden automatisch abgemeldet. Ein kopiertes Cookie gilt damit nicht mehr unbegrenzt. Änderbar mit `SESSION_IDLE_DAYS` (Audit N3).

## [0.11.2] – 2026-11-19

### Sicherheit
- Rezept-Import verbindet sich direkt mit der geprüften öffentlichen IP (Host-Header und TLS-Zertifikat bleiben beim Namen). Ein DNS-Rebinding kann den Abruf nicht mehr ins Heimnetz umlenken (Audit M4).
- Kopplung neuer Geräte: Limits gelten jetzt je IP (5 Anfragen pro Minute, 3 offene), ein Angreifer kann die Kopplung nicht mehr für alle sperren. Hinter einem Reverse Proxy (z. B. NPMPlus) zählt die Adresse aus `X-Forwarded-For`/`X-Real-IP`, aber nur, wenn die Verbindung aus einem privaten Netz kommt (Audit N1).
- Beim Zulassen zeigt FitPath, ob das neue Gerät im selben Netz ist, sonst dessen Adresse mit Warnung vor weitergegebenen Codes (Audit N1).
- Zwei gleichzeitige Abfragen einer freigegebenen Kopplung ergeben nur noch eine Session.

## [0.11.1] – 2026-11-19

### Sicherheit
- Health-Connect-Webhook: Der Body wird jetzt mit hartem Limit gelesen, auch ohne `Content-Length` (chunked). Nach 20 abgelehnten Anfragen pro Minute antwortet FitPath mit 429, ohne den Body zu lesen, höchstens 2 Uploads laufen gleichzeitig. Abgelehnte Anfragen landen nur noch einmal pro Minute im Protokoll (Audit M1).
- Alle JSON-Endpunkte lesen den Body mit Limit (2 MB, Foto 8 MB) und antworten bei kaputtem JSON, falschem Typ oder ungültigen Feldern mit 400 statt 500 (Audit N4, N5).
- Anmeldelink wird in einem Schritt gelesen und gelöscht, zwei gleichzeitige Klicks ergeben nicht mehr zwei Sessions (Audit N2).
- Rezept-Import lässt nur noch öffentliche Adressen zu (`is_global`, sperrt damit auch CGNAT 100.64.0.0/10) (Audit M4, teilweise).

## [0.11.0] – 2026-11-19

### Hinzugefügt
- Heute: Tipp auf den Ring schaltet die Anzeige zwischen Punkten und kcal um. Die Einstellung unter **Mehr → Anzeige** bleibt.

## [0.10.0] – 2026-11-18

### Hinzugefügt
- Nährwerte vom Foto: Kennt der Barcode-Scan ein Produkt nicht, liest die KI die Nährwerttabelle vom Foto ab und füllt das Formular „Eigenes Lebensmittel“ vor (je 100 g, mit Name, Marke und Portion, wenn lesbar). Plausibilitätsprüfung mit Hinweis „bitte prüfen“. Nur mit eingerichteter KI und einem Modell, das Bilder versteht.

## [0.9.0] – 2026-11-18

### Hinzugefügt
- Neues Gerät per QR-Code oder Code verbinden (wie WhatsApp Web): Das neue Gerät zeigt beim Öffnen einen QR-Code und eine 6-stellige Zahl. Auf einem verbundenen Gerät scannen oder unter **Mehr → Geräte → Code eingeben** eintippen, dann **Zulassen** – fertig, ohne Link abzutippen. Der Anmeldelink bleibt als Rückfall.

### Behoben
- Die Tab-Leiste war auf der Anmelde- und Einrichtungsseite sichtbar, obwohl sie ausgeblendet sein sollte.

## [0.8.0] – 2026-11-18

### Hinzugefügt
- Heißhunger-SOS mit Lieber-Tausch: „Worauf hast du Lust?“ (Schokolade, Chips, Eis, Gummibärchen, Kekse, Cola/Limo) zeigt günstigere Alternativen mit Punkten aus dem BLS. Antippen erfasst den Tausch als Snack und zählt den Heißhunger als überstanden; oft gewählte Tausche rutschen nach oben.
- „Bewusst genießen“: kleine Menge des Originals mit Hinweis, ob sie heute noch ins Budget passt.
- „Doch gegessen“ öffnet das Erfassen gleich mit passender Suche (z. B. Schokolade).
- Statistik: Heißhunger je Gelüst, wie oft getauscht und welcher Tausch am liebsten.

## [0.7.1] – 2026-11-18

### Behoben

- Erfolge, Erfahrungspunkte und Tage in Folge zählen erst ab dem Einrichtungstag. Nachgeladene ältere Daten (z. B. ein Jahr Schritte und Gewicht über „Verlauf senden“ im Life Dashboard) schalteten bisher massenhaft Abzeichen frei. Beim ersten Start nach dem Update werden die Abzeichen einmalig neu berechnet.

## [0.7.0] – 2026-11-18

### Hinzugefügt
- Rezept-Import per Link (Cookidoo, Chefkoch und andere Seiten mit schema.org-Rezeptdaten): Zutaten werden in Gramm umgerechnet und Lebensmitteln zugeordnet (mit KI genauer), Prüfliste mit kcal-Vergleich, Rückfall auf die Werte der Seite.
- Such-Synonyme für Rezept-Zutaten (Mehl, Zucker, Salz, Sahne, Rapsöl, Brühe, Knoblauchzehen …).

## [0.6.1] – 2026-11-18

### Hinzugefügt
- Heißhunger-SOS: Knopf „Abbrechen“, schließt ohne zu speichern.

## [0.6.0] – 2026-11-18

### Hinzugefügt
- Level und Erfahrungspunkte, 16 Abzeichen, Wochen-Challenge mit automatischer Zählung, Konfetti; Übersicht **Erfolge**.
- Heißhunger-SOS (Knopf oben): Auslöser, eigener Wenn-Dann-Plan, 10-Minuten-Timer, Ergebnis wird gespeichert; Pläne unter **Mehr → Wenn-Dann-Pläne**.
- Push etwa 15 Minuten vor typischen Snack-Uhrzeiten (abschaltbar).
- BMI mit WHO-Skala, Verlauf und BMI beim Zielgewicht im Tab **Gewicht**.
- Heißhunger-Auswertung in der Statistik.
- Versionsnummer oben neben dem Logo.

## [0.5.1] – 2026-11-18

### Hinzugefügt
- Anleitung „Einrichten mit Dockge“ im README, Variante mit benanntem Volume in `compose.yml`.
- Klare Meldung beim Start, wenn der Datenordner nicht beschreibbar ist (statt „unable to open database file“), mit der Lösung.

### Geändert
- Repo und Image sind öffentlich (MIT-Lizenz); `docker login` ist nicht mehr nötig.

## [0.5.0] – 2026-11-18

### Geändert
- KI-Anbindung an jeden OpenAI-kompatiblen Endpunkt (LiteLLM, OpenRouter, OpenAI, Ollama …): neue Variablen `FITPATH_AI_URL`, `FITPATH_AI_KEY`, `FITPATH_AI_MODEL`, `FITPATH_AI_HEADERS`; Adresse mit oder ohne `/v1`. Die alten `FITPATH_LITELLM_…`-Namen gelten weiter.

## [0.4.0] – 2026-11-18

### Hinzugefügt
- Eigenes Repo; GitHub Actions testet und baut Images für `linux/amd64` und `linux/arm64` nach `ghcr.io/luckytriple7/fitpath`. Update per `docker compose pull` oder Dockge.
- Versionsnummer unter **Mehr → Quellen** und in `/healthz`, dieses Changelog, Releases auf GitHub.
- Suche kennt rund 40 Alltagsbegriffe, die der BLS anders nennt: „brezel“ → Laugengebäck mit Hagelsalz, „hüttenkäse“ → Körniger Frischkäse, „gummibärchen“ → Fruchtgummi, „eis“ → Vanilleeis, „weizen“ → Hefeweizen u. a.
- Portion „1 Laugenstange/-brötchen“.

### Geändert
- Nudeln, Reis und Kartoffeln: in der Suche steht die gekochte Variante vorn.
- Ein exakter Namenstreffer steht vor längeren Namen („Hamburger“ vor „Hamburger Rauchfleisch“).
- `compose.yml` nutzt das fertige Image; Port, KI-Adresse und Zeitzone per `.env`, eigene Docker-Netze per `compose.override.yml`.

## [0.3.0] – 2026-11-18

### Hinzugefügt
- **↺ Wie gestern**: übernimmt eine Mahlzeit vom Vortag, mit Rückgängig.
- Gerichte aus Zutaten mit Portionen und optionalem Gewicht nach dem Kochen; 0-Punkte-Zutaten bleiben 0 Punkte.
- Erfassen per Text über einen KI-Proxy (z. B. LiteLLM): die KI zerlegt die Beschreibung, die eigene Suche schlägt Treffer vor, erfasst wird erst nach Bestätigung.
- Synonyme für Hackfleisch, Zwiebel, Kidneybohnen.

## [0.2.0] – 2026-11-18

### Hinzugefügt
- Koppeln mit Life Dashboard Companion per QR-Code oder Knopf „In Life Dashboard öffnen“.
- Diagnose je Health-Connect-Datentyp und Grund bei abgelehnten Lieferungen.
- Geräte umbenennen (Mehr → Geräte, `app.cli rename`).

### Geändert
- Anmeldelink öffnet zuerst eine Bestätigungsseite; Link-Vorschauen von Messengern haben ihn sonst verbraucht.
- Uhrzeiten (24 Stunden), Datum und Kommazahlen unabhängig von der Browsersprache.

## [0.1.0] – 2026-11-18

### Hinzugefügt
- Abnehm-PWA mit eigenem Punktesystem (umschaltbar auf kcal mit Energiedichte-Ampel), Tagesbudget nach Mifflin-St Jeor mit Untergrenzen, Wochenreserve, Aktivitätspunkte aus Schritten.
- Lebensmittel aus dem Bundeslebensmittelschlüssel 4.0 (7.140 Einträge, CC BY 4.0), Suche mit Kompositum-Logik, Portionen, Favoriten, eigene Lebensmittel.
- Barcode per Kamera mit Open-Food-Facts-Abfrage.
- Trendgewicht mit Meilensteinen, Statistik.
- Health-Connect-Webhook für Life Dashboard Companion (HMAC-Signatur, Tagessummen, Gewicht, Körperfett, Löschungen).
- Einmal-Link-Anmeldung, Push-Erinnerungen, Offline-Warteschlange, tägliche Sicherung, JSON-Export.
