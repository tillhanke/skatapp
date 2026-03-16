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

   Du kannst lokal einmal `python db_setup.py` ausführen, damit `skat_daten.db` mit der richtigen Struktur vorliegt. Diese Datei wird anschließend in den Container gemountet.

2. **Container starten:**

   Im Projektverzeichnis:

   ```bash
   docker compose up --build -d
   ```

   - Das Image wird über das `Dockerfile` gebaut.
   - Der Containerport **5000** wird auf dem Host als **5002** bereitgestellt.
   - Die Datei `skat_daten.db` wird in den Container gemountet und bleibt auf dem Host persistent.

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
- Beim Betrieb mit Docker wird diese Datei über ein Volume (`./skat_daten.db:/app/skat_daten.db`) in den Container eingebunden, damit Daten beim Neustart erhalten bleiben.
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
  - Über die Undo‑Funktion kann **genau das zuletzt gespeicherte Spiel** einmalig zurückgenommen werden.
  - Nach einem erfolgreichen Undo ist ein weiteres Undo erst wieder möglich, nachdem ein neues Spiel gespeichert wurde.

---

### Entwicklungshinweise

- **Backend**: `Flask`‑App in `app.py`, API‑Endpunkte laufen unter `/api/...`.
- **Frontend**: Statische Dateien (`index.html`, `script.js`, `style.css`) werden direkt von Flask ausgeliefert.
- **Produktiver Betrieb** (im Container): Die App wird mit `gunicorn` im Container gestartet (`CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]`).

