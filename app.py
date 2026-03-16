#!/home/hanke/src/skatapp/.venv/bin/python
import sqlite3
from flask import Flask, request, jsonify

# --- Konfiguration ---
DB_DATEI = "skat_daten.db"

# Wir konfigurieren Flask so, dass es statische Dateien (wie index.html) 
# direkt aus dem aktuellen Ordner ('.') ausliefert.
app = Flask(__name__, static_folder='.', static_url_path='')

# --- Hilfsfunktionen ---

def hole_verbindung():
    """Stellt die Verbindung her und erlaubt Spaltenzugriff per Name."""
    verbindung = sqlite3.connect(DB_DATEI, check_same_thread=False)
    # Wichtig: row_factory konvertiert die Zeilen in Dictionary-ähnliche Objekte.
    # Das macht die Umwandlung in JSON für das Frontend später extrem einfach.
    verbindung.row_factory = sqlite3.Row 
    return verbindung


def berechne_spielwert(
    spielart,
    reizwert,
    spitzen,
    hand,
    ouvert,
    schneider_angesagt,
    schwarz_angesagt,
    schwarz_erreicht,
    augen,
):
    if spielart == "Eingepasst":
        return 0
        
    # 1. Nullspiele abhandeln
    if spielart == "Null":
        if hand and ouvert: wert = 59
        elif ouvert: wert = 46
        elif hand: wert = 35
        else: wert = 23
        
        # Bei Nullspielen interpretieren wir "augen" als Flag:
        # 0 = gewonnen, 1 = verloren
        gewonnen = (augen == 0)
        return wert if gewonnen else wert * -2

    # 2. Farbspiele und Grand
    grundwerte = {"Eichel": 12, "Blatt": 11, "Herz": 10, "Schell": 9, "Grand": 24}
    grundwert = grundwerte.get(spielart, 0)
    
    # Multiplikator berechnen: Spiel (1) + Spitzen
    multiplikator = 1 + abs(spitzen) 
    
    if hand: multiplikator += 1
    
    # Schneider wird weiterhin aus den Augen abgeleitet
    # (augen <= 30 bedeutet, man hat selbst verloren und die Gegner haben einen Schneider gespielt)
    if augen >= 90 or augen <= 30: multiplikator += 1
    if schneider_angesagt: multiplikator += 1
    # Schwarz wird NICHT mehr automatisch aus 0/120 Augen abgeleitet,
    # sondern ausschließlich über das explizite Flag "schwarz_erreicht".
    if schwarz_erreicht: multiplikator += 1
    if schwarz_angesagt: multiplikator += 1
    if ouvert: multiplikator += 1
    
    wert = grundwert * multiplikator
    
    # 3. Siegbedingungen prüfen
    gewonnen = True
    if augen <= 60: gewonnen = False
    if schneider_angesagt and augen < 90: gewonnen = False
    # Ein Schwarz-angesagtes Spiel gilt nur dann als gewonnen,
    # wenn Schwarz auch explizit als erreicht markiert wurde.
    if schwarz_angesagt and not schwarz_erreicht: gewonnen = False
    
    # 4. Überreizt? (Spielwert ist kleiner als Reizwert)
    if wert < reizwert:
        gewonnen = False
        # Wenn überreizt, muss der Wert mindestens den Reizwert erreichen
        while wert < reizwert:
            multiplikator += 1
            wert = grundwert * multiplikator
            
    # 5. Bei Verlust wird der Wert verdoppelt und abgezogen
    if not gewonnen:
        return wert * -2
        
    return wert

# --- Routen (Die API für dein Frontend) ---

@app.route('/')
def index():
    """Liefert die Startseite des Frontends aus."""
    return app.send_static_file('index.html')

@app.route('/api/spieler', methods=['GET'])
def hole_spieler():
    """Gibt eine Liste aller vordefinierten Spielerinnen zurück."""
    verbindung = hole_verbindung()
    cursor = verbindung.cursor()
    
    cursor.execute("SELECT id, name FROM spieler ORDER BY name")
    spieler_liste = [dict(row) for row in cursor.fetchall()]
    
    verbindung.close()
    return jsonify(spieler_liste)

@app.route('/api/spiel', methods=['POST'])
def speichere_spiel():
    daten = request.json
    verbindung = hole_verbindung()
    cursor = verbindung.cursor()
    
    # Den Spielwert berechnen!
    spielwert = berechne_spielwert(
        daten['spielart'], daten['reizwert'], daten.get('spitzen', 0),
        daten.get('hand', 0), daten.get('ouvert', 0),
        daten.get('schneider_angesagt', 0), daten.get('schwarz_angesagt', 0),
        daten.get('schwarz_erreicht', 0), daten['augen']
    )
    
    sql = '''
        INSERT INTO spiel (
            aktive_spieler_ids, geber_id, einzelspieler_id, 
            spielart, reizwert, spitzen, hand, ouvert, 
            schneider_angesagt, schwarz_angesagt, schwarz_erreicht,
            augen, spielwert
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    
    werte = (
        daten['aktive_spieler_ids'], daten['geber_id'], daten.get('einzelspieler_id'), 
        daten['spielart'], daten['reizwert'], daten.get('spitzen'),
        daten.get('hand', 0), daten.get('ouvert', 0), 
        daten.get('schneider_angesagt', 0), daten.get('schwarz_angesagt', 0),
        daten.get('schwarz_erreicht', 0),
        daten['augen'], spielwert
    )
    
    cursor.execute(sql, werte)
    verbindung.commit()
    verbindung.close()
    return jsonify({"status": "erfolg", "spielwert": spielwert}), 201

@app.route('/api/stand', methods=['GET'])
def hole_punktestand():
    """Berechnet den aktuellen Punktestand und lädt die letzten 10 Spiele."""
    verbindung = hole_verbindung()
    cursor = verbindung.cursor()
    
    # 1. Gesamtpunkte und Spielanzahlen je Spielerin berechnen
    # - gesamtpunkte: Summe der Spielwerte als Einzelspielerin
    # - gespielte_spiele: Anzahl der Spiele als Einzelspielerin
    # - gesamtspiele: Anzahl aller Spiele, an denen die Spielerin beteiligt war
    cursor.execute('''
        SELECT
            s.id,
            s.name,
            COALESCE((
                SELECT SUM(sp.spielwert)
                FROM spiel sp
                WHERE sp.einzelspieler_id = s.id
            ), 0) AS gesamtpunkte,
            (
                SELECT COUNT(*)
                FROM spiel sp
                WHERE sp.einzelspieler_id = s.id
            ) AS gespielte_spiele,
            (
                SELECT COUNT(*)
                FROM spiel sp
                WHERE (',' || sp.aktive_spieler_ids || ',') LIKE '%,' || s.id || ',%'
            ) AS gesamtspiele
        FROM spieler s
        ORDER BY gesamtpunkte DESC
    ''')
    punktestand = [dict(row) for row in cursor.fetchall()]
    
    # 2. Historie: Die letzten 10 Spiele abrufen
    cursor.execute('''
        SELECT 
            sp.id, 
            sp.zeitstempel, 
            sp.spielart, 
            sp.reizwert, 
            sp.spielwert, 
            sp.einzelspieler_id,
            COALESCE(spi.name, 'Eingepasst') AS einzelspieler_name
        FROM spiel sp
        LEFT JOIN spieler spi ON sp.einzelspieler_id = spi.id
        ORDER BY sp.id DESC LIMIT 10
    ''')
    historie = [dict(row) for row in cursor.fetchall()]
    
    verbindung.close()
    
    return jsonify({
        "punktestand": punktestand,
        "historie": historie
    })


# --- Server Start ---

if __name__ == '__main__':
    # Startet den Server im Entwicklungsmodus auf Port 5000
    print("Starte Skat-Backend auf http://127.0.0.1:5000")
    app.run(debug=True, port=5000, threaded=False, use_reloader=False)
