# FitPath

Persönliche Abnehm-App als PWA für eine Person, selbst gehostet mit Docker. Statt reinem Kalorienzählen gibt es ein eigenes Punktesystem (umschaltbar auf kcal). Schritte, Training, Gewicht und Körperfett kommen automatisch aus Health Connect.


## Installation

Voraussetzungen: Docker mit Compose (mit `${A:-${B}}` in der `compose.yml`, also ein aktuelles Compose v2), eine Domain mit HTTPS über einen Reverse Proxy (PWA, Kamera, Push und der Health-Connect-Webhook brauchen HTTPS).

```bash
mkdir -p /opt/docker/stacks/fitpath && cd /opt/docker/stacks/fitpath
# compose.yml und .env.example aus diesem Repo hierher kopieren
cp .env.example .env            # FITPATH_PUBLIC_URL anpassen, KI-Key optional
mkdir -p data && chown 10001 data   # gehört sonst root, dann kann die App nicht schreiben
docker compose up -d
docker compose logs fitpath     # erwartet: "BLS importiert: 7140 Lebensmittel"
docker compose exec fitpath python -m app.cli link Handy     # Anmeldelink erzeugen
```

Den Link auf dem Handy öffnen, **Verbinden** tippen, Onboarding durchgehen, „Zum Startbildschirm hinzufügen“.

Reverse Proxy: auf `http://127.0.0.1:8800` weiterleiten (Port über `FITPATH_PORT` änderbar). Bot-Schutz (z. B. Anubis) für diese Adresse ausschalten, sonst scheitern API-Aufrufe, Service Worker, Push-Klicks und der Health-Connect-Webhook. Erlaubte Größe von Anfragen mindestens 16 MB (z. B. nginx `client_max_body_size 16m;`), sonst bricht das Nachladen der Health-Connect-Vergangenheit mit `413` ab.

Soll der Container ein bestehendes Docker-Netz erreichen (z. B. das des KI-Proxys), `compose.override.example.yml` nach `compose.override.yml` kopieren und anpassen. Die Datei lädt `docker compose` (auch Dockge) automatisch mit.

## Einrichten mit Dockge

1. In Dockge **+ Compose**, Stack-Name `fitpath`.
2. Den Inhalt von [`compose.yml`](compose.yml) in das Feld für die Compose-Datei kopieren. Ohne Zugriff auf die Kommandozeile des Servers die Zeile `- ./data:/data` durch `- fitpath_data:/data` ersetzen und die drei auskommentierten Zeilen ganz unten einkommentieren:
   ```yaml
   volumes:
     fitpath_data:
   ```
   Ein benanntes Volume übernimmt den richtigen Eigentümer aus dem Image. Ein Ordner `./data`, den Docker selbst anlegt, gehört dagegen root, und die App kann nicht hineinschreiben (sie meldet das beim Start im Log).
3. Im Feld **.env** mindestens `FITPATH_PUBLIC_URL=https://…` eintragen, für die KI optional `FITPATH_AI_URL`, `FITPATH_AI_KEY`, `FITPATH_AI_MODEL` (Beispiele in [`.env.example`](.env.example)).
4. **Deploy**. Im Log erscheint beim ersten Start „BLS importiert: 7140 Lebensmittel“, der Container wird nach etwa 20 Sekunden „healthy“.
5. Anmeldelink fürs erste Gerät: beim Container `fitpath` das Terminal öffnen (Symbol `>_`, Shell `sh`) und `python -m app.cli link Handy` eingeben. Den Link auf dem Handy öffnen und **Verbinden** tippen. Weitere Geräte koppelst du danach per QR-Code oder Code (siehe [Anmeldung](#anmeldung)).
6. Reverse Proxy auf `http://127.0.0.1:8800` einrichten (siehe oben).

Updates holt der Knopf **Update** im Stack. Sicherung beim benannten Volume: die Daten liegen unter `/var/lib/docker/volumes/fitpath_fitpath_data/_data`, die App legt dort täglich eine Kopie nach `backup/`; zusätzlich Export als JSON unter **Mehr → Daten**.

## Update

Versionen nach SemVer, Änderungen im [CHANGELOG.md](CHANGELOG.md). Die Version steht in `app/__init__.py` und in der App neben dem Logo und unter **Mehr**.

| Ereignis | Image-Tags | Gedacht für |
|---|---|---|
| Release-Tag `vX.Y.Z` | `X.Y.Z`, `X.Y`, `latest` (+ GitHub-Release mit dem Changelog-Abschnitt) | Betrieb |
| Push auf `main` | `main`, `sha-…` | Zwischenstand zum Ausprobieren |

`compose.yml` nutzt `latest`, holt also nur Releases:

```bash
cd /opt/docker/stacks/fitpath && docker compose pull && docker compose up -d
```

In Dockge reicht **Update**. Eine Version festhalten oder zurückgehen: in `compose.yml` statt `latest` z. B. `1.2.3` eintragen. Neue Datenbank-Spalten ergänzt die App beim Start selbst.

Release machen (Einträge stehen unter „Unveröffentlicht“ im Changelog):

```bash
python tools/release.py 1.2.3     # Version setzen, Changelog datieren, Commit und Tag
git push --follow-tags            # GitHub testet, prüft Tag = Version, baut das Image, legt das Release an
```

## Funktionen

| Bereich | Inhalt |
|---|---|
| Heute | Ring mit übrigen Punkten (oder kcal), Budget, Aktivitätspunkte, Wochenreserve, Wochenleiste Mo–So, Mahlzeiten (Frühstück, Mittag, Abend, Snacks), „Nochmal“-Leiste (ein Tipp erfasst die zuletzt gegessene Menge), „💡 Passt noch“ ab 15 Uhr (eigene Favoriten, Zuletzt und gespeicherte Mahlzeiten in üblicher Menge, die in die übrigen Punkte passen; satt machendes zuerst, ein 0-Punkte-Lebensmittel dabei), Wochen-Challenge, Level, Schritte und Training, Trendgewicht, Tage vor und zurück. Oben neben dem Logo steht die Version |
| Erfassen | Suche in rund 7.140 BLS-Lebensmitteln plus eigenen, Listen „Zuletzt“, „Favoriten“, „Eigene“, „Auswärts“, Barcode per Kamera live oder per Foto (eingebautes `BarcodeDetector` in Chrome für Android, sonst ZXing als WebAssembly vom eigenen Server, z. B. Safari auf dem iPhone; immer auch Zahl eintippen), unbekannte Produkte per Foto der Nährwerttabelle (KI füllt das Formular vor), Portionen (Scheibe, Stück, Glas …) mit Anzahl, Live-Vorschau mit Erklärung der Punkte, eigene Portionen merken, 0-Punkte-Schalter je Lebensmittel |
| Einkaufsmodus | Im Scan-Fenster **🛒 Einkaufsmodus** (oder `#einkauf`, auf Android auch als App-Verknüpfung): Die Kamera bleibt an, jedes erkannte Produkt kommt mit Punkten je 100 g, je Portion und je Packung in eine Liste (neuestes oben, derselbe Code erst nach 4 s Pause erneut). Antippen öffnet das Erfassen mit „Zurück zum Einkauf“, die Liste bleibt, solange die App offen ist. Wird das Open-Food-Facts-Limit erreicht, erscheint „Bitte kurz warten“ mit Countdown, die Codes werden danach automatisch nachgeladen. Bildschirm bleibt an, wo der Browser es kann. Nur angeschaute Produkte bleiben im Cache, erscheinen aber erst unter „Eigene“, wenn sie erfasst, Favorit oder mit eigener Portion versehen sind |
| Eigene Lebensmittel | Nährwerte je 100 g von der Packung, optional mit Barcode; unbekannte Barcodes landen direkt im Formular |
| Gespeicherte Mahlzeiten | ☆ in einer Mahlzeit mit Einträgen merkt sie unter einem Namen („Mein Frühstück“), mit Standard-Mahlzeit. In der leeren Mahlzeit auf Heute steht sie als Chip, ein Tipp erfasst alles (mit „Rückgängig“). Im Erfassen-Blatt Tab „⭐ Mahlzeiten“: Vorschau, einzelnes diesmal weglassen, bearbeiten, löschen. Gleicher Name ersetzt die alte. Gespeichert sind nur Lebensmittel, Menge und Portion, die Nährwerte kommen beim Erfassen frisch aus der Datenbank (`app/meals.py`) |
| Übernehmen | Leere Mahlzeit zeigt „Gestern: …“ und neben dem + einen Knopf **↺**. Er öffnet ein Fenster mit den Einträgen dieser Mahlzeit von gestern; oben lassen sich Vorgestern, derselbe Wochentag letzte Woche oder ein beliebiger früherer Tag wählen, darunter eine andere Mahlzeit (Reste vom Abend zum Mittag) oder „Ganzer Tag“ (jeder Eintrag in seine Mahlzeit). Mit ✕ rausnehmen, was nicht nochmal soll, der Rest wird übernommen (mit „Rückgängig“). Der Quelltag bleibt unverändert |
| Verschieben, kopieren | Eintrag antippen: andere Mahlzeit oder anderen Tag (nicht in der Zukunft) wählen und speichern verschiebt ihn; „Kopieren“ trägt ihn zusätzlich dort ein (mit „Rückgängig“) |
| Refeed und Pausen | Mehr → **🍝 Refeed-Tage**: bis zu 2 feste Wochentage (z. B. Sa/So) auf Erhaltung, die übrigen Tage etwas knapper, die Woche bleibt gleich; „Nur diese Woche anders“ tauscht einmalig. Mehr → **⏸ Pausen**: 🌴 Urlaub (nichts erfassen, keine Erinnerungen, Serie läuft weiter) oder Diätpause (1–2 Wochen auf Erhaltung, weiter erfassen), auch im Voraus oder nachträglich. Auf Heute erscheint eine Karte dazu, der Wochenstreifen zeigt 🍝/🌴/⏸. Rechnung siehe [Punktesystem](#punktesystem) |
| Training | Karte „Schritte“ auf Heute: **+ Training** mit 15 Sportarten (Schwimmen, Rad, Laufen, Kraft, Yoga …), Dauer und Intensität (leicht, mittel, hart), Vorschau der Punkte. Einheiten von der Uhr kommen über Health Connect, Sportart und Intensität lassen sich ändern, Löschen blendet sie aus. Rechnung siehe [Punktesystem](#punktesystem) |
| Gerichte | Aus Zutaten (Suche, Gramm je Zutat) oder per **Rezept-Link** (Cookidoo, Chefkoch und andere Seiten mit schema.org-Rezeptdaten), Portionen, optional Gewicht nach dem Kochen; erscheint in Suche und unter „Eigene“ und wird wie ein Lebensmittel erfasst. 0-Punkte-Zutaten bleiben 0 Punkte |
| Auswärts | Tab **🍽️ Auswärts** im Erfassen-Blatt: 38 fertige Teller in typischen Restaurant-Größen (Imbiss, Pizza, Griechisch, Deutsch, Italienisch, Asiatisch, Salat), z. B. Döner, Gyros mit Pommes, Schnitzel Wiener Art, Pizza Margherita, Bami Goreng. Größe klein/normal/groß (75/100/130 %), vorgewählt ist normal. Zusammengesetzt aus BLS-Bausteinen (wo der BLS das ganze Gericht kennt, direkt dieses), Pfannengerichte mit 10–15 g Fettzuschlag, weil Restaurants fetter kochen; die Zusammensetzung steht unter „Mehr zu diesem Lebensmittel“. Auch über die Suche zu finden. Die Liste steht in `app/eatout.py` |
| Per Text (KI) | ✨ im Erfassen-Blatt: „2 Brötchen mit Butter und Gouda, Kaffee mit Milch“ → KI zerlegt in Lebensmittel mit Menge, FitPath schlägt je Posten 5 Treffer aus der eigenen DB vor; Auswahl, Gramm und Mahlzeit änderbar, erfasst wird erst nach Bestätigung |
| Gewicht | Trendgewicht (geglättet), Tempo kg/Woche, Ziel mit Meilensteinen (−5 %, −10 %) und Prognose („etwa Mitte März“: Trend der letzten 3 Wochen, vorher geplantes Tempo, höchstens 1 % pro Woche, keine Prognose bei Plateau), BMI mit WHO-Skala, Verlauf und BMI beim Zielgewicht, Verlauf 30/90/365 Tage, Körperfett und Bauchumfang |
| Motivation | Level und Erfahrungspunkte, 19 Abzeichen (Tage in Folge, Tage im Budget, Schrittziel, Training, Schwimmen, −2/−5/−10 %, Zielgewicht …), Wochen-Challenge mit automatischer Zählung und „Andere“, Konfetti bei neuem Abzeichen, Level oder geschaffter Challenge; Übersicht unter **Erfolge** (Mehr → Wenn-Dann-Pläne → 🏅 oder Level-Karte auf Heute) |
| Heißhunger-SOS | Knopf **🍫 SOS** oben: Auslöser wählen, Stärke, eigener Wenn-Dann-Plan, 10-Minuten-Timer mit Tipps, „Geschafft“ (+15 XP), „Doch gegessen“ (öffnet das Erfassen mit passender Suche) oder „Abbrechen“ (nichts gespeichert); Pläne und Auslöser unter **Mehr → Wenn-Dann-Pläne** |
| Lieber-Tausch | Im SOS „Worauf hast du Lust?“ (Schokolade, Chips, Eis, Gummibärchen, Kekse, Cola/Limo): 3–4 günstigere Alternativen mit Punkten aus dem BLS, z. B. bei Schokolade Bitterschokolade, Schoko-Quark, heißer Kakao oder Banane mit Kakao. Antippen erfasst den Tausch als Snack und zählt als überstanden (+15 XP); oft gewählte stehen oben. Dazu „Bewusst genießen“: kleine Menge des Originals mit Hinweis, ob sie heute ins Budget passt. Die Liste steht in `app/swaps.py` |
| Statistik | Echter Bedarf aus Einträgen und Gewicht (siehe [Punktesystem](#punktesystem)), Punkte oder kcal pro Tag gegen Budget, Tage im Budget, Ø Eiweiß/Ballaststoffe mit Richtwert, Energiedichte-Ampel, Heißhunger (überstanden, Auslöser, worauf Lust und wie oft getauscht, typische Uhrzeiten), größte Punkte-Lieferanten, Schritte, Training (Trainingstage, Zeit, Punkte, Minuten pro Tag, je Sportart) |
| Wochenrückblick | Montags bis mittwochs auf Heute eine Karte zur letzten Woche (Tage im Budget, Bilanz, Trend), bis man sie öffnet oder wegklickt (gilt auf allen Geräten). Der Rückblick selbst, auch jederzeit über **🗓 Wochenrückblick** in der Statistik: Tage im Budget, Bilanz der Woche, Trendgewicht vorher/nachher, Wochenstreifen (Tipp öffnet den Tag), bester Tag, Ø Punkte im Vergleich zur Vorwoche, Ø Makros mit Richtwerten und Tipps, Schritte und Training je Sportart. Mit ‹ › frühere Wochen; Urlaubstage zählen nicht mit (`app/review.py`) |
| Health Connect | Webhook für Life Dashboard Companion: Schritte (Tagessummen), Trainingseinheiten, Gewicht, Körperfett, Löschungen, Verlauf nachladen |
| Push | Wiegen (Wochentage wählbar), „noch nichts erfasst“ am Mittag, etwa 15 Minuten vor typischen Snack-Uhrzeiten (gelernt aus Snack-Einträgen und Heißhunger der letzten 3 Wochen, ab 3 Tagen je Stunde), Abend-Check; Ruhezeiten und Höchstzahl pro Tag |
| Design | Hell und dunkel nach Systemeinstellung, unter **Mehr → Anzeige** pro Gerät fest wählbar (System / Hell / Dunkel, gespeichert im Browser); Statusleisten-Farbe passend |
| Stil | Ebenfalls unter **Mehr → Anzeige** pro Gerät: **Lebendig** (bunte Emojis, runde Formen, warmes Orange) oder **Sachlich** (einfarbige Linien-Icons, klare Kanten, kühle Farben mit Blau als Akzent, Schrift Inter, kompakter Tagesring mit Zahlen daneben). Beide Stile gibt es hell und dunkel |
| Offline | App-Hülle und letzter Zustand aus dem Cache, Einträge warten in einer Warteschlange |

## Rezept-Import per Link

Unter **Erfassen → 🍲 Gericht anlegen** einen Rezept-Link einfügen (in der Cookidoo-App über „Teilen“). FitPath ruft die Seite einmal ab und liest die eingebetteten Rezeptdaten (schema.org „Recipe“): Name, Ausbeute, Zutaten, Nährwerte. Jede Zutatenzeile wird in Gramm umgerechnet („2 EL Olivenöl“ = 24 g, „1 Zwiebel“ = 80 g, Spannen wie „40 – 60 g“ = Mittelwert, englische Zutaten werden übersetzt) und einem Lebensmittel der Datenbank zugeordnet; ist eine KI eingerichtet, schlägt sie Suchbegriffe und Mengen vor. Wasser und „nach Belieben“-Zutaten sind abgewählt. In der Prüfliste lassen sich Treffer, Gramm und Portionen ändern (🔎 sucht neu); daneben steht die kcal-Angabe der Seite zur Kontrolle, ab 25 % Abweichung mit Hinweis.

Gespeichert wird ein normales Gericht mit allen Nährwerten (Gemüse bleibt 0 Punkte), die Quelle steht mit im Gericht. Rückfall: **Nur die Werte der Seite übernehmen** legt ein Lebensmittel aus den Nährwerten der Seite an; dort fehlen meist Zucker und gesättigtes Fett.

Abgerufen werden nur öffentliche Adressen (kein Zugriff aufs Heimnetz), höchstens 3 MB, auf Klick des Nutzers.

## Motivation

Erfahrungspunkte entstehen aus den Daten selbst: je erfasstem Tag 10, je Tag im Budget 10 (abgeschlossene Tage), je Tag mit erreichtem Schrittziel 10, je Wiegetag 5, je überstandenem Heißhunger 15, je Abzeichen 50, je geschaffter Wochen-Challenge 50. Gezählt wird ab dem Einrichtungstag (`start_date`, gesetzt beim Onboarding): ältere Daten, etwa ein nachgeladenes Jahr aus Health Connect, erscheinen in Statistik und Verlauf, bringen aber keine Abzeichen und keine Erfahrungspunkte. Ein einmal erreichtes Abzeichen bleibt, auch wenn z. B. das Gewicht später wieder steigt (gespeichert in `unlocked`). Die Wochen-Challenge wechselt jede Woche (Montag), „Andere“ zieht die nächste; geschafft ist sie, sobald die Zählung das Ziel erreicht.

## Punktesystem

Je Eintrag aus den Nährwerten der gegessenen Menge (Gramm):

```
Punkte = kcal/35 + ges. Fett/4 + Zucker/10 + Alkohol/8 − Eiweiß/10 − Ballaststoffe/5
```

nicht unter 0, auf ganze Punkte gerundet. Beispiele: Croissant 60 g ≈ 9, Cola 0,33 l ≈ 7, Bier 0,5 l ≈ 8, Reis gekocht 200 g ≈ 7, Nüsse 30 g ≈ 5, Magerquark 250 g ≈ 3, Hähnchenbrust 150 g ≈ 1.

- **0 Punkte**: frisches Obst und Gemüse, Pilze, Sprossen, gegarte Hülsenfrüchte, erkannt über die BLS-Hauptgruppe (F, G, K7, H6, H7) und höchstens 90 kcal/100 g; Saft, Trockenobst, Gezuckertes, Frittiertes ausgenommen. Pro Lebensmittel änderbar.
- **kcal-Ziel**: Grundumsatz nach Mifflin-St Jeor × Aktivitätsfaktor (1,2 bis 1,725) ± Korrektur aus dem echten Bedarf − Defizit (Tempo × 7.700 kcal ÷ 7). Untergrenze 1.500 kcal (Männer) bzw. 1.200 kcal (Frauen), Tempo höchstens 1 % des Körpergewichts pro Woche. Gerechnet mit dem Trendgewicht.
- **Echter Bedarf** (Statistik): Ab 14 Tagen mit Einträgen und 6 Wiegewerten schätzt FitPath den tatsächlichen Verbrauch der letzten 28 Tage: Ø Zufuhr an vollständig erfassten Tagen (ab zwei Mahlzeiten und 800 kcal, mindestens 70 % der Tage) − Gewichtsänderung × 7.700 kcal/kg. Die Gewichtsänderung kommt aus einer Regressionsgeraden über die Wiegewerte, ihre Streuung ergibt die Unsicherheit (± kcal) und den Sicherheitsgrad. Weicht der Verbrauch um mindestens 100 kcal von Formel plus Aktivität ab, schlägt FitPath eine Korrektur vor (`tdee_adjust`, in 50er-Schritten, höchstens ± 500 kcal). Übernommen wird sie nur auf Knopfdruck und lässt sich jederzeit zurücksetzen. Voraussetzung: alles erfassen, auch 0-Punkte-Lebensmittel (`app/adaptive.py`). Nach einem eingetragenen Urlaub beginnt der Zeitraum frühestens am 4. Tag danach.
- **Tagesbudget** = (kcal-Ziel − 200) ÷ 40. Satt machende Kost bringt etwa 45–50 kcal je Punkt, typische Mischkost gut 30; mit 40 bleibt bei guter Auswahl ein Defizit.
- **Wochenreserve**: Von jedem vergangenen Tag der Woche mit Einträgen wandern bis zu 4 ungenutzte Punkte (bzw. 140 kcal) in die Reserve, ein überzogener Tag zieht ab. Tage ohne Eintrag und Urlaubstage zählen nicht. Montag beginnt neu. Grundlage ist das Budget des jeweiligen Tages.
- **Refeed-Tage** (`app/plan.py`, nur beim Abnehmen): An bis zu 2 festen Wochentagen gilt der Bedarf statt des Ziels. Die übrigen Tage tragen das Defizit mit: Ziel − Refeed-Tage × (Bedarf − Ziel) ÷ übrige Tage, die Wochensumme bleibt gleich. Beispiel Bedarf 2.700, Ziel 2.150 kcal, Sa/So: Refeed 2.700, Mo–Fr 1.930 kcal. Kämen die übrigen Tage unter die Untergrenze, bleiben sie dort und die Refeed-Tage bekommen nur das Freiwerdende (unter 100 kcal mehr: kein Refeed). In Wochen mit Pause gibt es keinen Refeed. Eine Änderung gilt ab der laufenden Woche, frühere Wochen bleiben. Grundlage: Campbell u. a. 2020 (2 Refeed-Tage je Woche bei gleichem Wochendefizit).
- **Pausen** (`app/plan.py`): Diätpause (höchstens 28 Tage) = Budget auf Bedarf, alles andere wie gewohnt. Urlaub (höchstens 60 Tage) = keine Erinnerungen; Urlaubstage reißen die Serie nicht ab und zählen nicht für Wochenreserve, Tage im Budget und Durchschnitte der Statistik. Der Echte Bedarf rechnet erst ab dem 4. Tag nach dem Urlaub wieder (Wasser vom Urlaubsessen).
- **Aktivität**: Schritte über der Grundlinie (Standard 5.000) × Gewicht × 0,0005 kcal, davon 50 % gutgeschrieben. Die aktiven kcal aus Health Connect werden gespeichert, aber nicht verrechnet (zu unzuverlässig).
- **Training** (`app/training.py`): (MET − 1) × Gewicht × Stunden, also nur der Verbrauch über Ruhe, davon 50 % gutgeschrieben, höchstens 15 Punkte am Tag. MET je Sportart und Intensität gerundet nach dem Compendium of Physical Activities (2024), z. B. Schwimmen 4,8 / 5,8 / 9,8. Keine Doppelzählung mit den Schritten: Bei Gehen, Laufen und Wandern werden die Schritte der Einheit geschätzt (100 bzw. 160 je Minute) und abgezogen, soweit der Schrittbonus sie an dem Tag schon gutgeschrieben hat. Spazieren zählt deshalb praktisch nur über die Schritte; bringt es vormittags noch Punkte, wandern sie in den Schrittbonus, sobald man über die Grundlinie kommt (das Fenster der Einheit erklärt das). Überlappen sich zwei Einheiten aus Health Connect zu mindestens der Hälfte (zwei Apps haben dieselbe geschrieben), zählt nur die erste. Trainingstag (+10 XP): mindestens 20 Minuten Training ohne Spazieren.

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

1. In Life Dashboard Health-Connect-Zugriff für Schritte, Training (Exercise), Gewicht, Körperfett, aktive Kalorien erlauben.
2. In FitPath **Mehr → Health Connect → Einrichten** (später **Koppeln**). Am PC erscheint ein QR-Code: mit der Handy-Kamera oder in Life Dashboard unter **Add destination → Scan a pairing code** scannen. Ist FitPath auf dem Handy offen, öffnet **In Life Dashboard öffnen** die Kopplung direkt. Dort **Pair** tippen.
3. Life Dashboard schickt sofort einen signierten Test-Ping; in FitPath steht „Test empfangen“. **Send history** lädt die Vergangenheit nach.
4. **Daily totals in payload** anlassen (Standard), Intervall 15 Minuten.

Das Geheimnis (43 Zeichen) von Hand abzutippen geht unter **Von Hand eintragen**, ist aber fehleranfällig (falsches Zeichen = 401). Der Koppel-Link folgt `docs/pairing.md` von Life Dashboard (`https://owen282000.github.io/life-dashboard-companion-app/pair#v=1&url=…&secret=…`, alles im Fragment, das nie an einen Server geht); der QR-Code entsteht serverseitig mit `segno`. Abgelehnte Lieferungen landen mit Grund (keine Signatur, Signatur passt nicht, kein Geheimnis eingerichtet) in `ingest_log` und unter **Letzte Lieferungen**; die 401-Antwort nennt den Grund ebenfalls.

Technik (`app/ingest.py`): Signatur `X-Signature: sha256=<HMAC-SHA256>` über den rohen Body; alternativ `Authorization: Bearer <Geheimnis>` als eigener Header. Schritte kommen aus `daily_totals` (Aggregat-API von Health Connect, keine Doppelzählung von Handy und Uhr); für ein Datum gilt die Lieferung mit der höchsten `sequence`, eine schon verarbeitete `sequence` wird übersprungen. `weight` und `body_fat` werden über ihre `uuid` gespeichert, `deleted_records` entfernt sie wieder. Trainingseinheiten kommen aus `exercise` (Sportart über `name`, sonst die Typnummer; Dauer aus `duration_seconds`, unter 3 Minuten wird ignoriert) und werden über ihre `uuid` in der Tabelle `workouts` gespeichert. Die letzten Lieferungen (14 Tage, Rohdaten gekürzt auf 32 KB) stehen in der Tabelle `ingest_log` und unter **Mehr → Health Connect → Letzte Lieferungen**.

Größe: Eine Lieferung kann einige MB haben (vor allem beim Nachladen der Vergangenheit). FitPath nimmt bis 12 MB an. Zeigt das Zustellprotokoll der App `413`, im Reverse Proxy die erlaubte Größe erhöhen (z. B. `client_max_body_size 16m;`).

## KI und Datenschutz

Erfassen per Text läuft optional über einen beliebigen OpenAI-kompatiblen Endpunkt: LiteLLM, OpenRouter, OpenAI, ein lokales Ollama … (`FITPATH_AI_URL` mit oder ohne `/v1`, `FITPATH_AI_KEY`, `FITPATH_AI_MODEL`, Standard `claude-haiku-5-5`, Beispiele in `.env.example`; Header `x-caveman-style: off`, keine `temperature`). Ohne Key ist ✨ ausgeblendet (Ollama braucht keinen, dann einen beliebigen eintragen). An die KI geht **nur der eingegebene Text**, keine weiteren Daten aus der App. Die KI liefert Suchbegriffe in BLS-Sprache und geschätzte Mengen (`app/ai.py`, `PARSE_SYSTEM`); welches Lebensmittel erfasst wird, entscheidet die Suche in der eigenen DB und am Ende der Nutzer.

**Nährwerte vom Foto:** Kennt der Barcode-Scan ein Produkt nicht, gibt es im Formular „Eigenes Lebensmittel“ den Knopf **📷 Packung fotografieren**. Das Handy verkleinert das Foto (längste Seite 1.600 px, JPEG), FitPath schickt es an dasselbe Modell, die KI liest die Werte **je 100 g** ab (nie je Portion; kJ wird zu kcal, Alkohol % vol zu Gramm) und dazu Name, Marke und Portionsgröße, wenn lesbar. Die Werte landen markiert im Formular, gespeichert wird erst nach dem Prüfen. Ein zweites Foto (z. B. Vorderseite) ergänzt nur leere Felder wie den Namen. FitPath prüft die Antwort: Werte außerhalb sinnvoller Grenzen fallen weg, „davon gesättigt/Zucker“ größer als Fett/Kohlenhydrate gilt als verlesen, und passen die kcal nicht zu Eiweiß, Fett und Kohlenhydraten (mehr als 20 % bzw. 25 kcal daneben), erscheint „bitte prüfen“ (`app/ai.py`, `LABEL_SYSTEM`, `clean_label`). Das Modell muss Bilder verstehen (Claude Haiku/Sonnet, GPT-4o-mini …; bei reinen Textmodellen kommt „KI versteht keine Bilder“). An die KI geht nur das Foto, gespeichert wird es nicht. Kosten mit Haiku: etwa 0,1–0,3 Cent je Foto.

Bei LiteLLM einen eigenen virtuellen Key mit kleinem Budget anlegen, der nur das gewählte Modell darf.

## Anmeldung

Kein Passwort. Zwei Wege:

**QR-Code oder Code (weitere Geräte):** Ein Gerät ohne Anmeldung zeigt beim Öffnen von FitPath einen QR-Code und eine 6-stellige Zahl (5 Minuten gültig, danach automatisch neu). Auf einem schon verbundenen Gerät den QR-Code mit der Kamera scannen (öffnet `…/#pair=123456`) oder unter **Mehr → Geräte → Code eingeben** die Zahl eintippen. Das verbundene Gerät zeigt Betriebssystem und Browser der Anfrage („Windows · Chrome“), ob sie aus demselben Netz kommt (sonst die fremde Adresse mit Warnung) und fragt nach einem Namen; nach **Zulassen** ist das neue Gerät innerhalb von 2 Sekunden angemeldet. Sicherheit: Freigeben kann nur ein angemeldetes Gerät; das Cookie bekommt nur der Browser, der die Anfrage gestellt hat (er hält dafür ein zufälliges Geheimnis, der Code allein nützt nichts). An deine Geräte wird nichts geschickt, solange du nicht selbst scannst oder tippst. Höchstens 5 neue Anfragen pro Minute und 3 offene je IP, insgesamt 60 pro Minute und 100 offene (`app/auth.py`, `PAIR_*`). Hinter einem Reverse Proxy zählt die Adresse aus `X-Forwarded-For`/`X-Real-IP`, aber nur bei Verbindungen aus einem privaten Netz.

**Einmal-Link (erstes Gerät):** Der Server erzeugt einen Einmal-Link, 15 Minuten gültig, nur einmal nutzbar. Der Link öffnet zuerst eine Bestätigungsseite; eingelöst wird er erst mit **Verbinden** (POST). Grund: Messenger und Browser rufen Links für die Vorschau per GET ab und hätten ihn sonst verbraucht, bevor das Handy ihn öffnet. Danach bleibt das Gerät 400 Tage per Session-Cookie angemeldet (`HttpOnly`, `Secure`, `SameSite=Lax`). In der DB liegen nur SHA-256-Hashes.

```bash
docker compose exec fitpath python -m app.cli link Handy     # Link erzeugen
docker compose exec fitpath python -m app.cli devices        # Geräte
docker compose exec fitpath python -m app.cli revoke <id>    # Gerät abmelden
docker compose exec fitpath python -m app.cli rename <id> PC # Gerät umbenennen
docker compose exec fitpath python -m app.cli import-bls     # BLS-Seed neu einlesen
```

Unter **Mehr → Geräte** lassen sich Geräte umbenennen (✏️) und abmelden, auch das Gerät, an dem du gerade sitzt (löscht dort auch die zwischengespeicherten Daten). Geräte, die 180 Tage nicht benutzt wurden, meldet FitPath von selbst ab (änderbar mit der Umgebungsvariable `SESSION_IDLE_DAYS`). Dort gibt es auch weiterhin einen Anmeldelink, falls kein zweites Gerät zur Hand ist. Der Name kommt sonst aus dem Link (`link Handy` heißt „Handy“, egal welches Gerät ihn öffnet), ohne Namen aus dem Browser.

Uhrzeiten und Zahlen gibt die App unabhängig von der Browsersprache ein: Uhrzeiten als eigenes 24-Stunden-Feld (HH:MM, „2030“ wird 20:30), Kommazahlen mit Komma oder Punkt, Tage als deutsche Auswahl. Die eingebauten Felder `type="time"`/`type="date"` zeigen in einem englischen Browser AM/PM bzw. MM/TT.

## Dateien

| Datei | Inhalt |
|---|---|
| `app/main.py` | FastAPI: Routen, Validierung, Sicherheits-Header (CSP, Kamera nur für die eigene Seite) |
| `app/db.py` | SQLite-Schema, Einstellungen, Zeitfunktionen |
| `app/points.py` | Punkte-Formel, 0-Punkte-Regeln, kcal-Ziel, Budget, Aktivität, Wochenreserve |
| `app/plan.py` | Budget je Tag: Refeed-Tage, Diätpause, Urlaub |
| `app/static/vendor/` | Barcode-Erkennung für Browser ohne `BarcodeDetector`: `barcode-detector` 3.2.3 (IIFE-Ponyfill) und `zxing-wasm` 3.1.6, beide MIT, Herkunft und Prüfsummen in `LICENSE.txt`. Dazu die Schrift Inter (OFL) für den Stil „Sachlich“. Ausgeliefert nur über die feste Liste `VENDOR` in `app/main.py` |
| `app/meals.py` | Gespeicherte Mahlzeiten: prüfen, speichern (gleicher Name ersetzt), Punkte mit aktuellen Nährwerten, Positionen fürs Erfassen |
| `app/training.py` | Sportarten mit MET, Zuordnung der Health-Connect-Typen, Trainingspunkte, doppelte Einheiten |
| `app/foods.py` | BLS-Import, Suche, Portionen, eigene Lebensmittel, Open-Food-Facts-Barcodes |
| `app/diary.py` | Tagessummen, Übersicht „Heute“, Verlauf für die Statistik |
| `app/review.py` | Wochenrückblick einer Woche (Mo–So) und Hinweis darauf auf „Heute“ |
| `app/body.py` | Trendgewicht, Tempo, Meilensteine |
| `app/recipe_import.py` | Rezept-Link: Abruf, schema.org-Daten, Zutaten in Gramm und Zuordnung |
| `app/motivation.py` | XP, Level, Abzeichen, Wochen-Challenge, Heißhunger-Auswertung, Snack-Uhrzeiten |
| `app/swaps.py` | Lieber-Tausch: Alternativen je Gelüst (BLS-Codes), Reihenfolge nach Nutzung |
| `app/ingest.py` | Health-Connect-Webhook, Koppel-Link, Diagnose |
| `app/ai.py` | Erfassen per Text über LiteLLM |
| `app/push.py` | VAPID (erzeugt beim ersten Start), Erinnerungen alle 5 Minuten |
| `app/auth.py`, `app/cli.py`, `app/backup.py` | Einmal-Links, Kopplung per QR-Code/Code, Geräte, Kommandozeile, tägliche Sicherung |
| `app/static/` | PWA: `index.html`, `app.js`, `styles.css`, `sw.js`, Manifest, Icons; `icons.svg` = Linien-Icons (Lucide, ISC) für den Stil „Sachlich“ |
| `tools/icons.py` | Baut `icons.svg` aus der Zuordnung `EMOJI_ICON` in `app.js` (Emoji → Lucide-Name), lädt dazu von lucide-static |
| `seed/bls40.csv.gz` | BLS 4.0 in kompakter Form |
| `tools/bls_convert.py` | BLS-Excel → Seed (nur lokal, braucht `openpyxl`) |
| `tests/` | `pytest`: Formel, Budget, Reserve, Trend, Webhook, Gerichte, KI-Erfassung, beide Stile vollständig, API-Durchstich (läuft auch in GitHub Actions vor dem Image-Bau) |
| `.github/workflows/image.yml` | Tests, Image für amd64/arm64 nach ghcr.io, Release bei Tag |
| `CHANGELOG.md`, `tools/release.py` | Änderungen je Version, Release vorbereiten |

**Zwei Stile:** Neue Oberfläche muss in „Lebendig“ und „Sachlich“ (je hell und dunkel) passen. Farben, Radien und Schatten nur über die CSS-Variablen in `styles.css` (`--card`, `--accent`, `--radius`, `--r-md`, `--r-sm`, `--r-pill`, `--shadow` …); eigene Formen im Block „Stil Sachlich“ am Ende nachziehen. Jedes neue Emoji in `EMOJI_ICON` (`app.js`) eintragen und `python tools/icons.py` laufen lassen; `tests/test_style.py` meldet Vergessenes.

Tests lokal: `python -m venv venv && venv/bin/pip install -r requirements.txt pytest && venv/bin/python -m pytest -q tests`

Daten: `./data` im Stack-Ordner (`fitpath.db`, `vapid_private.pem`); diesen Ordner ins Backup aufnehmen. Die App legt täglich um 23:20 eine konsistente Kopie nach `data/backup/fitpath-JJJJ-MM-TT.db` (14 Tage). Export als JSON unter **Mehr → Daten**.

Wiederherstellen: Container stoppen, gewünschte Kopie nach `data/fitpath.db` kopieren (Eigentümer UID `10001`), `fitpath.db-wal` und `fitpath.db-shm` löschen, Container starten.


## Sicherheit

- **Eine Instanz pro Person.** Jedes verbundene Gerät hat vollen Zugriff: Geräte verwalten, Export, Health-Connect-Geheimnis neu erzeugen. Rollen oder getrennte Konten gibt es nicht. Wer FitPath zu zweit nutzen will, startet zwei Container.
- **HTTPS macht der Reverse Proxy** (z. B. NPMPlus, Caddy). Dort auch HSTS einschalten. `COOKIE_SECURE` bleibt auf `true`, `PUBLIC_URL` beginnt mit `https://`.
- **Daten auf dem Server** liegen unverschlüsselt in `data/` (SQLite und tägliche Sicherungen). Auf einem Server, den andere mitbenutzen, oder wenn Sicherungen den Server verlassen: Verschlüsselung auf Ebene von Platte oder Volume.
- **Daten auf dem Gerät:** Für den Offline-Betrieb merkt sich der Browser den letzten Stand (auch Gewicht) im `localStorage`. **Abmelden** unter **Mehr → Geräte** löscht ihn.
- **Logs** enthalten keine Eingaben: Bei KI-Fehlern stehen nur Statuscode und Fehlertyp drin.
- Prüfbericht und Stand der Umsetzung: [SECURITY-AUDIT.md](SECURITY-AUDIT.md).

## Hinweis

FitPath ersetzt keine ärztliche Beratung. Die Untergrenzen beim kcal-Ziel und beim Tempo sind bewusst fest eingebaut.

## Lizenz

MIT, siehe [LICENSE](LICENSE). Die Nährwerte stammen aus dem Bundeslebensmittelschlüssel 4.0 (Max Rubner-Institut, CC BY 4.0, Quellenangabe in der App unter **Mehr → Quellen**), Markenprodukte aus Open Food Facts (ODbL).
