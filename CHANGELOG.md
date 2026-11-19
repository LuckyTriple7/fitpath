# Changelog

Alle nennenswerten Änderungen an FitPath. Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/): Hauptversion bei Änderungen, die beim Update Handarbeit brauchen, Nebenversion bei neuen Funktionen, Patch bei Fehlerbehebungen. Solange die Version mit 0 beginnt, ist FitPath noch in schneller Entwicklung.

Neue Einträge kommen unter „Unveröffentlicht“. `python tools/release.py X.Y.Z` macht daraus eine Version. Versionen vor 0.4.0 entstanden im früheren Sammel-Repo und haben hier keinen Git-Tag.

## [Unveröffentlicht]

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
