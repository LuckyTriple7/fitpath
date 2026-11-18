# Backlog – FitPath

Doku: [README.md](README.md)

## Offen

### Schritt 4 – KI
- Coach mit Allowlist (Budget, Trend, Schritte, Top-Snack-Zeiten; nie Notizen).
- Foto → Schätzung (nur mit Schalter, Standard aus).
- Wochenrückblick.
- Adaptiver Bedarf: ab 14 Tagen mit Einträgen Ø Zufuhr − (Trendänderung × 7.700) ÷ Tage, mit Sicherheitsgrad; Vorschlag, den Budget-Faktor anzupassen.

### Schritt 5 – Anbindungen
- Home-Assistant-Sensoren (Punkte übrig, Trendgewicht, Streak) über Token-Endpunkt.
- Zeile im Hermes-Morgenbericht („Trend 93,5 kg, gestern 38/43 P“).
- Open-Food-Facts-Export (nur Deutschland, mit Nährwerten) wöchentlich einlesen, damit Markenprodukte auch per Suche auftauchen.
- Wochenrückblick als Obsidian-Notiz.

### Ideen
- Wasser trinken zählen.
- Receive/Writeback von Life Dashboard: Gewicht aus FitPath nach Health Connect zurückschreiben.

## Erledigt

Commit-Angaben bis 18.11.2026 beziehen sich auf das frühere Sammel-Repo, aus dem die App übernommen wurde.

- **18.11.2026** Grundversion (Schritt 1 und 2): Onboarding mit Budget-Vorschau, Punktesystem mit kcal-Umschalter, BLS 4.0 als Seed (7.140 Lebensmittel, CC BY 4.0), Suche mit Kompositum-Logik und Synonymen, Portionen, Favoriten, eigene Lebensmittel, Barcode per Kamera mit Open-Food-Facts-Cache, Tagebuch je Mahlzeit mit „Nochmal“-Leiste, Wochenreserve, Aktivitätspunkte aus Schritten, Trendgewicht mit Meilensteinen, Statistik, Health-Connect-Webhook für Life Dashboard Companion (HMAC, sequence, uuid, Löschungen), Push-Erinnerungen, Offline-Warteschlange, Tests
- **18.11.2026** In Betrieb genommen. Nachbesserungen am ersten Tag: Anmeldelink mit Bestätigungsseite (Link-Vorschau hatte ihn verbraucht), Geräte umbenennen, Uhrzeiten/Zahlen/Datum unabhängig von der Browsersprache (vorher AM/PM), Koppeln mit Life Dashboard per QR-Code (Geheimnis abtippen gab 401), Diagnose je Datentyp und Grund bei abgelehnten Lieferungen
- **18.11.2026** „Wie gestern“ je Mahlzeit, Gerichte aus Zutaten (0-Punkte-Zutaten bleiben frei, Gewicht nach dem Kochen optional), Erfassen per Text über LiteLLM (KI zerlegt, Suche schlägt vor, Nutzer bestätigt); Synonyme für Hackfleisch, Zwiebel, Kidneybohnen
- **18.11.2026** Schritt 3 Motivation: Level/XP, Abzeichen, Wochen-Challenge, Konfetti, Heißhunger-SOS mit Wenn-Dann-Plänen, Snack-Push; BMI im Tab Gewicht; Version neben dem Logo
- **18.11.2026** Rezept-Import per Link (Cookidoo u. a.) mit Zutaten-Zuordnung und kcal-Vergleich
