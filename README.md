### SkatApp – Punkteverwaltung für Skatrunden

Die **SkatApp** ist eine kleine Web‑Anwendung auf Basis von Flask und SQLite, mit der Skatspiele erfasst und ausgewertet werden können. Über ein einfaches Web‑Frontend (`index.html`) lassen sich Spiele eintragen, Punktestände anzeigen und die letzten Spiele nachvollziehen.

---

### Voraussetzungen

- **Variante ohne Docker**
  - Python **3.12** (oder kompatibel)
  - `pip` zum Installieren von Python‑Paketen
- **Variante mit Docker**
  - Docker
  - Docker Compose (bzw. `docker compose`)

Die Daten werden in einer lokalen SQLite‑Datei `skat_daten.db` gespeichert.

---

### Installation & lokaler Start (ohne Docker)

1. **Repository klonen** (bzw. Projektverzeichnis bereitstellen):

   ```bash
   cd /Users/hanke/src/skatapp
   ```

2. **(Empfohlen) Virtuelle Umgebung anlegen und aktivieren**:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Abhängigkeiten installieren** (falls noch nicht geschehen):

   ```bash
   pip install -r requirements.txt
   ```

4. **Datenbank initialisieren / erstellen**

   Mit dem Skript `db_setup.py` kannst du eine neue Datenbank anlegen (bzw. die Struktur sicherstellen) **und direkt Spielerinnen eintragen**.

   - **Neue Datenbank mit initialen Spielerinnen anlegen**:

     ```bash
     python db_setup.py init --spielerinnen "Anna" "Berta" "Clara"
     ```

     Dadurch wird (falls nicht vorhanden) eine Datei `skat_daten.db` erzeugt, die Tabellen werden angelegt und die angegebenen Namen in die Tabelle `spieler` eingetragen. Doppelte Namen werden automatisch übersprungen.

   - **Alternative Datenbankdatei verwenden** (z. B. für Tests):

     ```bash
     python db_setup.py --db test_skat.db init --spielerinnen "Anna" "Berta"
     ```

   - **Später weitere Spielerinnen hinzufügen**:

     ```bash
     python db_setup.py add --spielerinnen "Dora" "Emma"
     ```

     Über `add` kannst du jederzeit zusätzliche Spielerinnen zu einer bestehenden Datenbank hinzufügen. Bereits vorhandene Namen bleiben unverändert.

5. **Server starten**

   Es gibt zwei typische Varianten:

   - **Direkt mit Flask‑Dev‑Server (über `run.sh`)**:

     ```bash
     chmod +x run.sh
     ./run.sh
     ```

     Der Server läuft dann standardmäßig unter `http://127.0.0.1:5001/`.

   - **Direkt mit Python (ohne `run.sh`)**:

     ```bash
     python app.py
     ```

     Der Server läuft dann unter `http://127.0.0.1:5000/`.

6. **App im Browser nutzen**

   - Entweder `http://127.0.0.1:5000/` oder `http://127.0.0.1:5001/` im Browser öffnen (abhängig davon, wie der Server gestartet wurde).
   - Im Frontend können nun:
     - Spielerinnen ausgewählt bzw. Spiele erfasst werden,
     - Punktestände und Historie eingesehen werden,
     - das letzte Spiel (falls möglich) per Undo wieder entfernt werden.

---

### Start mit Docker & Docker Compose

1. **Datenbank vorbereiten (optional aber empfohlen):**

   ```bash
   SKAT_DB=data/skat_daten.db python db_setup.py init
   ```

   Damit liegt die Datenbank mit der richtigen Struktur unter `data/`. Dieses
   Verzeichnis wird anschließend in den Container gemountet.

   > **Umstieg von einem älteren Setup:** Früher wurde die einzelne Datei
   > `skat_daten.db` gemountet. Einmalig verschieben:
   > `mkdir -p data && mv skat_daten.db data/`

2. **Container starten:**

   Im Projektverzeichnis:

   ```bash
   docker compose up --build -d
   ```

   - Das Image wird über das `Dockerfile` gebaut.
   - Der Containerport **5000** wird auf dem Host als **5002** bereitgestellt.
   - Das Verzeichnis `./data` wird in den Container gemountet; die Datenbank liegt darin als `data/skat_daten.db` und bleibt auf dem Host persistent.

3. **App im Browser öffnen:**

   - `http://localhost:5002/` im Browser aufrufen.
   - Die Bedienung der App erfolgt wie bei der lokalen Variante über das Web‑Frontend.

4. **Container stoppen:**

   ```bash
   docker compose down
   ```

---

### Datenbank & Persistenz

- Die Anwendung verwendet eine SQLite‑Datenbankdatei **`skat_daten.db`**.
- Der Pfad lässt sich über die Umgebungsvariable **`SKAT_DB`** überschreiben;
  im Container zeigt sie auf `/app/data/skat_daten.db`.
- Die Datenbank läuft im **WAL‑Modus**. SQLite legt dafür `-wal`‑ und
  `-shm`‑Dateien neben der Datenbank an. Deshalb wird im Docker‑Setup ein
  **Verzeichnis** (`./data`) gemountet und nicht mehr die einzelne Datei.
- Beim Betrieb mit Docker wird das Verzeichnis `./data` als Volume eingebunden, damit Daten beim Neustart erhalten bleiben.
- Das Skript `db_setup.py` richtet die notwendigen Tabellen (z. B. `spieler`, `spiel`) ein. Dieses Skript sollte einmalig vor dem ersten Start ausgeführt werden, sofern die Datenbank noch nicht existiert.

---

### Nutzung der App 

- **Spielerinnen verwalten**: Die vordefinierten Spielerinnen werden aus der Tabelle `spieler` geladen und im Frontend angeboten.
- **Spiele erfassen**:
  - Drei aktive Spielerinnen auswählen (eine davon ist die Einzelspielerin).
  - Geberin, Spielart (Farbspiel, Grand, Null, Eingepasst), Reizwert, Spitzen sowie Optionen wie Hand, Ouvert, Schneider/Schwarz (angesagt/erreicht) und Augen eintragen.
  - Das Spiel wird gespeichert, der Spielwert nach Skat‑Logik berechnet und der Punktestand aktualisiert.
- **Punktestand & Historie ansehen**:
  - Die App zeigt den aktuellen Punktestand pro Spielerin (Gesamtpunkte, Anzahl Spiele etc.).
  - Die letzten Spiele mit Spielart, Reizwert, Spielwert und Beteiligten sind einsehbar.
- **Undo des letzten Spiels**:
  - Über die Undo‑Funktion kann **genau das zuletzt gespeicherte Spiel der eigenen
    Runde** einmalig zurückgenommen werden.
  - Das Zurücknehmen wirkt **immer nur auf die eigene Runde**. Jede Partie – ob
    lokal eingetippt oder remote gespielt – bekommt beim Start eine Kennung, die
    an jedem Spiel mitgespeichert wird (Spalte `sitzung_id`, Format
    `lokal:<uuid>` bzw. `tisch:<RAUMCODE>`). Laufen zwei Runden gleichzeitig,
    kann keine der anderen ein Spiel wegnehmen.
  - Nach einem erfolgreichen Undo ist ein weiteres Undo erst wieder möglich,
    nachdem die Runde ein neues Spiel gespeichert hat. Sonst ließe sich die
    Historie rückwärts durchlöschen.
  - Am Remote‑Tisch geht das Zurücknehmen nur **zwischen zwei Spielen**, bevor neu
    gegeben wurde – danach ist nicht mehr eindeutig, was „das letzte Spiel“ ist.
    Die zurückgenommene Runde wird anschließend von derselben Geberin wiederholt.
  - Spiele aus der Zeit vor den Runden‑Kennungen haben `sitzung_id = NULL` und
    lassen sich nicht mehr zurücknehmen.

---

### Remote-Play (im Aufbau)

Für das Spielen über mehrere Geräte hinweg entsteht ein eigenes Regelwerk in
`skat_engine.py`. Es ist bewusst frei von Flask, Datenbank und Netzwerk: die
Klasse `SkatSpiel` bildet ein komplettes Spiel (Geben, Reizen, Drücken,
Ansagen, zehn Stiche) als Zustandsautomat ab und prüft jeden Zug.

Gespielt wird nach offiziellen Regeln **ohne Hausregeln**:

- Der Skat zählt für die Spitzen mit – auch beim Handspiel. Weil die Spitzen
  aus allen zwölf Karten ermittelt werden, ändert das Drücken sie nicht.
- **Schwarz** bedeutet **alle zehn Stiche**, nicht nur 120 Augen.
- Kontra/Re gibt es nicht.
- Schneider, Schwarz und Ouvert können nur aus der Hand angesagt werden;
  Ouvert schließt Schwarz (und damit Schneider) ein. Null Ouvert ist auch ohne
  Hand möglich.

Ein abgeschlossenes Spiel liefert ein `Ergebnis`, dessen Felder genau den
Spalten der Tabelle `spiel` entsprechen. Remote gespielte Partien landen damit
in derselben Statistik wie die von Hand eingetragenen.

#### Beitreten, zuschauen, Aufstellung ändern

Der Einladungslink hat die Form `/spielen?code=ABC123`; der Code lässt sich auch
von Hand eintippen. Abgewiesen wird niemand:

- **In der Lobby und mit freiem Platz** sitzt man direkt mit am Tisch.
- **Während einer laufenden Partie** schaut man zu und rückt zum nächsten Spiel
  nach – mitten in eine Runde kann niemand einsteigen, die Karten sind verteilt.
- **Bei fünf Sitzenden** bleibt es beim Zuschauen, bis ein Platz frei wird.
  Mehr als fünf nimmt ein Skattisch nicht auf. Nachgerückt wird in der
  Reihenfolge des Beitritts.

Zuschauende sehen wie Aussetzende von Haus aus nur den öffentlichen Tisch und
können auf Wunsch alle Blätter, den Skat und die Stiche aufdecken.

#### Spielverlauf-Protokoll (zweite Datenbank)

Von jeder remote gespielten Partie wird zusätzlich der komplette Verlauf
festgehalten – in einer **eigenen Datei** `skat_verlauf.db` neben der
Hauptdatenbank. **`skat_daten.db` bleibt davon völlig unberührt:** keine neuen
Tabellen, keine neuen Spalten, keine Migration. Wer das Protokoll nicht
braucht, kann die Datei löschen, ohne dass der Punktestand darunter leidet.
Der Pfad lässt sich über `SKAT_VERLAUF_DB` überschreiben.

Festgehalten wird, was sich aus dem Ergebnis allein nicht rekonstruieren lässt:

| Tabelle  | Inhalt |
|----------|--------|
| `partie` | Kopfdaten: Ansage, Reizwert, Spitzen, Skat, Gedrücktes, Ergebnis |
| `blatt`  | die zehn ausgeteilten Karten je Spielerin |
| `reizen` | der vollständige Reizverlauf |
| `stich`  | Gewinnerin und Augen je Stich |
| `zug`    | jede gespielte Karte mit Spielerin und Reihenfolge |

Verbunden sind beide Datenbanken nur über `partie.spiel_id` – die `id` der
Zeile in `skat_daten.db` → `spiel`. Über Dateigrenzen hinweg kann SQLite keinen
Fremdschlüssel prüfen, die Nummer bleibt aber eindeutig, weil `spiel.id`
per AUTOINCREMENT nie neu vergeben wird. Abfragen über beide hinweg gehen mit
`ATTACH`:

```sql
ATTACH DATABASE 'data/skat_daten.db' AS haupt;
SELECT p.id, s.spielart, s.spielwert, p.augen_alleinspieler
FROM partie p JOIN haupt.spiel s ON s.id = p.spiel_id
ORDER BY p.id;
```

Ein zurückgenommenes Spiel verschwindet aus `spiel`, bleibt im Protokoll aber
als Beleg stehen und wird nur mit `zurueckgenommen = 1` markiert – gespielt
wurde es ja. Schlägt das Protokollieren fehl, wird das Spiel trotzdem normal
gewertet; die Zugabe darf den Tisch nicht aufhalten.

Nach jedem Spiel holt **„Tisch verlassen“** die Runde zurück in die Lobby, wo
Plätze frei werden, neue Spielerinnen dazukommen und die Sitzordnung neu gelegt
werden kann. Bricht die Verbindung einer Spielerin ab, lässt sie sich über das
kleine Kreuz an ihrem Namen vom Tisch nehmen; das laufende Spiel wird dabei
verworfen und nicht gewertet.

### Tests

```bash
pip install -r requirements.txt
pytest
```

Die Testsuite spielt unter anderem mehrere hundert vollständige Zufallspartien
durch und vergleicht den von der Engine berechneten Spielwert mit
`app.berechne_spielwert` – der Funktion, die bisher die manuell eingetippten
Spiele bewertet. Weichen beide ab, ist eine von beiden falsch.

Zusätzlich gibt es gestellte Blätter (`tests/test_gestellte_blaetter.py`) für
Fälle, die zufälliges Spiel praktisch nie erzeugt – etwa ein Alleinspieler, der
alle zehn Stiche macht. Dafür nimmt `SkatSpiel` optional ein vorgegebenes
Kartendeck entgegen (`blatt=...`), womit sich auch gemeldete Partien exakt
nachstellen lassen.

---

### Entwicklungshinweise

- **Backend**: `Flask`‑App in `app.py`, API‑Endpunkte laufen unter `/api/...`.
- **Frontend**: Statische Dateien (`index.html`, `script.js`, `style.css`) werden direkt von Flask ausgeliefert.
- **Produktiver Betrieb** (im Container): Die App wird mit `gunicorn` und einem
  `gevent`‑Worker gestartet. Der `gevent`‑Worker ist Voraussetzung für die
  langlebigen Server‑Sent‑Event‑Verbindungen des Remote‑Play.
- Bewusst läuft **genau ein Worker** (`-w 1`): Der Zustand laufender Tische liegt
  im Prozessspeicher und darf nicht über mehrere Worker verteilt werden.

