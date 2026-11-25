# Backlog – FitPath

Doku: [README.md](README.md)

## Offen

### Schritt 4 – KI
- Coach mit Allowlist (Budget, Trend, Schritte, Top-Snack-Zeiten; nie Notizen).
- Foto → Schätzung (nur mit Schalter, Standard aus).
- Wochenrückblick.

### Schritt 5 – Anbindungen
- Home-Assistant-Sensoren (Punkte übrig, Trendgewicht, Streak) über Token-Endpunkt.
- Zeile im Hermes-Morgenbericht („Trend 93,5 kg, gestern 38/43 P“).
- Open-Food-Facts-Export (nur Deutschland, mit Nährwerten) wöchentlich einlesen, damit Markenprodukte auch per Suche auftauchen.
- Wochenrückblick als Obsidian-Notiz.

### Aus dem Vergleich mit anderen Apps (20.11.2026)
Verglichen mit WW, Yazio, MyFitnessPal, Lose It!, FDDB, Noom, MacroFactor. Grob nach Nutzen sortiert.
- **Vorausplanen** (WW): bis 7 Tage voraus eintragen (heute sperrt „›“ die Zukunft). Geplante Einträge zählen sofort im Ring des Tages, gestrichelt mit „geplant“, am Tag freiwillig mit ✓ bestätigen, um Mitternacht automatisch. Abend-Check nennt offene geplante Einträge; Mittags-Erinnerung ignoriert sie; Wochenreserve, Serie, XP erst nach dem Tag; „Echter Bedarf“ nur Tage ohne offene geplante Einträge. Dazu „Passt noch“ an geplanten Tagen immer zeigen. „Was passt noch?“ ist erledigt (0.22.0).
- **Markenprodukte in der Suche** (FDDB, Yazio): siehe Open-Food-Facts-Export unter Schritt 5. Bisher findet die Suche Markenprodukte nur, wenn sie schon einmal gescannt wurden.
- **Wasser** (WW, Yazio, Lifesum): Gläser antippen, Tagesziel als Ring.
- **Beliebigen Tag kopieren, Einträge verschieben** (MyFitnessPal): nicht nur „wie gestern“; falsch einsortierten Eintrag in eine andere Mahlzeit oder einen anderen Tag schieben.
- **Wochenrückblick** (WW Weekly Check-in): montags Karte mit Punkten, Trend, Training, bestem Tag; siehe auch Schritt 4 und 5.
- **Schlaf aus Health Connect** (Noom, WW): Life Dashboard kann `sleep` schicken; Zusammenhang wenig Schlaf ↔ Heißhunger in der Statistik.
- **Restaurantketten** (Yazio, FDDB): McDonald's, Burger King, Subway, Vapiano … mit veröffentlichten Nährwerten als Ergänzung zu „Auswärts“; muss gepflegt werden.
- **Einkaufsliste aus Gerichten** (Yazio, WW): Zutaten eigener Rezepte auf eine Liste.
- **Fortschrittsfotos** (Yazio, Lose It!): privat auf dem eigenen Server, Vergleich vorher/nachher.
- **Intervallfasten-Timer** (Yazio, Zero): nur bei Bedarf.
- Bewusst nicht: Community/Social, große Rezeptdatenbank (Inhalte, Lizenzen), Mikronährstoffe.

### Ideen
- Wasser trinken zählen (siehe oben).
- Receive/Writeback von Life Dashboard: Gewicht aus FitPath nach Health Connect zurückschreiben.

## Erledigt

Commit-Angaben bis 18.11.2026 beziehen sich auf das frühere Sammel-Repo, aus dem die App übernommen wurde.

- **18.11.2026** Grundversion (Schritt 1 und 2): Onboarding mit Budget-Vorschau, Punktesystem mit kcal-Umschalter, BLS 4.0 als Seed (7.140 Lebensmittel, CC BY 4.0), Suche mit Kompositum-Logik und Synonymen, Portionen, Favoriten, eigene Lebensmittel, Barcode per Kamera mit Open-Food-Facts-Cache, Tagebuch je Mahlzeit mit „Nochmal“-Leiste, Wochenreserve, Aktivitätspunkte aus Schritten, Trendgewicht mit Meilensteinen, Statistik, Health-Connect-Webhook für Life Dashboard Companion (HMAC, sequence, uuid, Löschungen), Push-Erinnerungen, Offline-Warteschlange, Tests
- **18.11.2026** In Betrieb genommen. Nachbesserungen am ersten Tag: Anmeldelink mit Bestätigungsseite (Link-Vorschau hatte ihn verbraucht), Geräte umbenennen, Uhrzeiten/Zahlen/Datum unabhängig von der Browsersprache (vorher AM/PM), Koppeln mit Life Dashboard per QR-Code (Geheimnis abtippen gab 401), Diagnose je Datentyp und Grund bei abgelehnten Lieferungen
- **18.11.2026** „Wie gestern“ je Mahlzeit, Gerichte aus Zutaten (0-Punkte-Zutaten bleiben frei, Gewicht nach dem Kochen optional), Erfassen per Text über LiteLLM (KI zerlegt, Suche schlägt vor, Nutzer bestätigt); Synonyme für Hackfleisch, Zwiebel, Kidneybohnen
- **18.11.2026** Schritt 3 Motivation: Level/XP, Abzeichen, Wochen-Challenge, Konfetti, Heißhunger-SOS mit Wenn-Dann-Plänen, Snack-Push; BMI im Tab Gewicht; Version neben dem Logo
- **18.11.2026** Rezept-Import per Link (Cookidoo u. a.) mit Zutaten-Zuordnung und kcal-Vergleich
- **18.11.2026** Lieber-Tausch im Heißhunger-SOS: Alternativen je Gelüst mit Punkten, „Bewusst genießen“ mit Budget-Hinweis, Auswertung in der Statistik (0.8.0)
- **18.11.2026** Neues Gerät per QR-Code oder 6-stelligem Code verbinden, Freigabe auf einem verbundenen Gerät (0.9.0)
- **18.11.2026** Nährwerte vom Foto der Packung (KI liest die Tabelle, Formular vorausgefüllt, Plausibilitätsprüfung)
- **19.11.2026** Tipp auf den Ring schaltet Punkte/kcal um (0.11.0)
- **19.11.2026** Sicherheitsaudit umgesetzt: Webhook gegen DoS, 400 statt 500 bei kaputten Eingaben, Rezept-Import gegen DNS-Rebinding, Kopplungs-Limits je IP mit Netz-Hinweis, atomare Einmal-Links (0.11.1, 0.11.2), Session-Ablauf nach 180 Tagen und „Abmelden“ fürs aktuelle Gerät (0.12.0), Abhängigkeiten mit bekannten Lücken aktualisiert, Lieferkette gepinnt, pip-audit und Dependabot (0.12.2)
- **19.11.2026** Gewichtskarte auf „Heute“ zeigt auch den Wert der Waage (0.12.1)
- **19.11.2026** Python 3.15, `httpx2` statt `httpx`, CI testet mit der Python-Version des Images (0.13.0)
- **19.11.2026** Echter Bedarf: Verbrauch aus Einträgen und Gewicht, Vorschlag zur Korrektur des Budgets (0.14.0)
- **19.11.2026** Auswärts essen: 38 Restaurant-Teller aus BLS-Bausteinen mit Größe klein/normal/groß und Fettzuschlag
- **20.11.2026** „Wie gestern“ als ↺-Knopf mit Auswahlfenster, Portionen in 0,5er-Schritten (0.16.0)
- **20.11.2026** Trainingspunkte nach MET, von Hand und über Health Connect, ohne Doppelzählung mit Schritten (0.17.0)
- **20.11.2026** Barcode-Scanner fürs iPhone (ZXing als WebAssembly), Foto vom Barcode, Zähler bei Lebensmitteln ohne Portionen behoben (0.18.0); „verbraucht“ im Ring (0.18.1)
- **20.11.2026** Training in der Statistik (0.19.0), Einkaufsmodus mit Warte-Hinweis beim Open-Food-Facts-Limit (0.20.0)
- **20.11.2026** Gespeicherte Mahlzeiten („Mein Frühstück“ mit einem Tipp), Prognose fürs Zielgewicht (0.21.0)
- **20.11.2026** „💡 Passt noch“: Vorschläge aus eigenen Sachen, die in die übrigen Punkte passen
- **25.11.2026** Doppelte Gewichte aus Health Connect (mehrere Apps) nur einmal (0.25.1); Refeed-Tage, Urlaub und Diätpause mit Budget je Tag
