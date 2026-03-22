#!/home/hanke/src/skatapp/.venv/bin/python
import sqlite3
from datetime import date, datetime, timedelta
from flask import Flask, request, jsonify

# --- Konfiguration ---
DB_DATEI = "skat_daten.db"

# Seeger/Fabian: Multiplikator für „verlorene Spiele der anderen Mitspieler“ (Dreiertisch 40, Vierertisch 30).
# Diese App verwendet durchgängig Dreier-Runden (genau drei aktive Spielerinnen).
SEEGER_FABIAN_VERLUST_ANDERE = 40

# --- Undo-Status (in-memory, pro Prozess) ---
# Merkt sich, für welches Spiel (id) die Undo-Funktion bereits genutzt wurde.
_last_undo_game_id = None

# Wir konfigurieren Flask so, dass es statische Dateien (wie index.html) 
# direkt aus dem aktuellen Ordner ('.') ausliefert.
app = Flask(__name__, static_folder='.', static_url_path='')

# --- Hilfsfunktionen ---

def _start_of_current_month_local():
    """Lokaler Kalendertag 1 des aktuellen Monats, 00:00:00."""
    heute = date.today()
    erster = heute.replace(day=1)
    return datetime.combine(erster, datetime.min.time())


def _start_of_current_week_monday_local():
    """Lokaler Montag der aktuellen Woche, 00:00:00 (Woche beginnt montags)."""
    heute = date.today()
    montag = heute - timedelta(days=heute.weekday())
    return datetime.combine(montag, datetime.min.time())


def _ergaenze_seeger_fabian(zeilen):
    """
    Wertung nach Seeger/Fabian:
    Spielpunkte + (eigene gewonnene − eigene verlorene Solospiele) × 50
    + (Summe der als Alleinspieler verlorenen Spiele der übrigen Spielerinnen) × k
    (k = 40 Dreiertisch, 30 Vierertisch; hier Dreiertisch).
    """
    for z in zeilen:
        z["seeger_fabian"] = (
            z["gesamtpunkte"]
            + (z["solo_gewonnen"] - z["solo_verloren"]) * 50
            + z["andere_solo_verloren"] * SEEGER_FABIAN_VERLUST_ANDERE
        )
        del z["solo_gewonnen"]
        del z["solo_verloren"]
        del z["andere_solo_verloren"]
    return zeilen


def hole_punktestand_mit_zeitfilter(cursor, ab_zeitstempel_str):
    """
    Wie Gesamtstand, aber nur Spiele mit zeitstempel >= ab_zeitstempel_str.
    ab_zeitstempel_str: 'YYYY-MM-DD HH:MM:SS' (lokale Serverzeit).
    """
    cursor.execute(
        """
        SELECT
            s.id,
            s.name,
            COALESCE((
                SELECT SUM(sp.spielwert)
                FROM spiel sp
                WHERE sp.einzelspieler_id = s.id
                  AND sp.zeitstempel >= ?
            ), 0) AS gesamtpunkte,
            (
                SELECT COUNT(*)
                FROM spiel sp
                WHERE sp.einzelspieler_id = s.id
                  AND sp.zeitstempel >= ?
            ) AS gespielte_spiele,
            (
                SELECT COUNT(*)
                FROM spiel sp
                WHERE (',' || sp.aktive_spieler_ids || ',') LIKE '%,' || s.id || ',%'
                  AND sp.zeitstempel >= ?
            ) AS gesamtspiele,
            (
                SELECT COUNT(*)
                FROM spiel sp
                WHERE sp.einzelspieler_id = s.id
                  AND sp.spielwert > 0
                  AND sp.zeitstempel >= ?
            ) AS solo_gewonnen,
            (
                SELECT COUNT(*)
                FROM spiel sp
                WHERE sp.einzelspieler_id = s.id
                  AND sp.spielwert < 0
                  AND sp.zeitstempel >= ?
            ) AS solo_verloren,
            (
                SELECT COUNT(*)
                FROM spiel sp
                WHERE sp.einzelspieler_id IS NOT NULL
                  AND sp.einzelspieler_id != s.id
                  AND sp.spielwert < 0
                  AND (',' || sp.aktive_spieler_ids || ',') LIKE '%,' || s.id || ',%'
                  AND sp.zeitstempel >= ?
            ) AS andere_solo_verloren
        FROM spieler s
        ORDER BY gesamtpunkte DESC
        """,
        (ab_zeitstempel_str,) * 6,
    )
    return _ergaenze_seeger_fabian([dict(row) for row in cursor.fetchall()])


def hole_verbindung():
    """Stellt die Verbindung her und erlaubt Spaltenzugriff per Name."""
    verbindung = sqlite3.connect(DB_DATEI, check_same_thread=False)
    # Wichtig: row_factory konvertiert die Zeilen in Dictionary-ähnliche Objekte.
    # Das macht die Umwandlung in JSON für das Frontend später extrem einfach.
    verbindung.row_factory = sqlite3.Row 
    return verbindung


def hole_letztes_spiel():
    """Lädt das zuletzt gespeicherte Spiel (nach id)."""
    verbindung = hole_verbindung()
    cursor = verbindung.cursor()
    cursor.execute(
        """
        SELECT id, geber_id
        FROM spiel
        ORDER BY id DESC
        LIMIT 1
        """
    )
    zeile = cursor.fetchone()
    verbindung.close()
    return zeile


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
    global _last_undo_game_id
    daten = request.json

    aktive_str = daten.get('aktive_spieler_ids', '')
    aktive_ids_liste = [teil.strip() for teil in aktive_str.split(',') if teil.strip()]
    if len(aktive_ids_liste) != 3:
        return jsonify(
            {
                "error": "aktive_spieler_ids muss genau drei Spielerinnen enthalten.",
                "aktive_spieler_ids": aktive_str,
            }
        ), 400

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

    # Nach erfolgreichem Speichern ist Undo für dieses neue Spiel wieder möglich.
    _last_undo_game_id = None
    return jsonify({"status": "erfolg", "spielwert": spielwert}), 201


@app.route('/api/spiel/undo', methods=['POST'])
def undo_letztes_spiel():
    """
    Entfernt genau das zuletzt gespeicherte Spiel.

    Die Funktion kann pro Spiel nur einmal genutzt werden:
    Wurde das aktuelle letzte Spiel bereits zurückgenommen, ist ein weiteres Undo
    erst nach dem nächsten neu gespeicherten Spiel möglich.
    """
    global _last_undo_game_id

    zeile = hole_letztes_spiel()
    if zeile is None:
        return jsonify({"error": "Kein Spiel vorhanden, das zurückgenommen werden kann."}), 400

    last_id = zeile["id"]
    geber_id = zeile["geber_id"]

    # Wurde für dieses Spiel bereits ein Undo ausgeführt?
    if _last_undo_game_id == last_id:
        return jsonify({"error": "Das letzte Spiel wurde bereits zurückgenommen."}), 409

    verbindung = hole_verbindung()
    cursor = verbindung.cursor()
    cursor.execute("DELETE FROM spiel WHERE id = ?", (last_id,))
    verbindung.commit()
    verbindung.close()

    _last_undo_game_id = last_id

    return jsonify(
        {
            "status": "erfolg",
            "entfernte_spiel_id": last_id,
            "geber_id": geber_id,
        }
    ), 200

@app.route('/api/stand', methods=['GET'])
def hole_punktestand():
    """Berechnet den aktuellen Punktestand und lädt die letzten 10 Spiele."""
    global _last_undo_game_id
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
            ) AS gesamtspiele,
            (
                SELECT COUNT(*)
                FROM spiel sp
                WHERE sp.einzelspieler_id = s.id AND sp.spielwert > 0
            ) AS solo_gewonnen,
            (
                SELECT COUNT(*)
                FROM spiel sp
                WHERE sp.einzelspieler_id = s.id AND sp.spielwert < 0
            ) AS solo_verloren,
            (
                SELECT COUNT(*)
                FROM spiel sp
                WHERE sp.einzelspieler_id IS NOT NULL
                  AND sp.einzelspieler_id != s.id
                  AND sp.spielwert < 0
                  AND (',' || sp.aktive_spieler_ids || ',') LIKE '%,' || s.id || ',%'
            ) AS andere_solo_verloren
        FROM spieler s
        ORDER BY gesamtpunkte DESC
    ''')
    punktestand = _ergaenze_seeger_fabian([dict(row) for row in cursor.fetchall()])

    ab_monat = _start_of_current_month_local().strftime("%Y-%m-%d %H:%M:%S")
    ab_woche = _start_of_current_week_monday_local().strftime("%Y-%m-%d %H:%M:%S")
    punktestand_monat = hole_punktestand_mit_zeitfilter(cursor, ab_monat)
    punktestand_woche = hole_punktestand_mit_zeitfilter(cursor, ab_woche)

    # Mapping Spieler-ID -> Name für spätere Anzeige (z.B. Gegenspielerinnen)
    spieler_id_zu_name = {eintrag["id"]: eintrag["name"] for eintrag in punktestand}

    # 2. Historie: Die letzten 10 Spiele abrufen
    cursor.execute('''
        SELECT 
            sp.id, 
            sp.zeitstempel, 
            sp.spielart, 
            sp.reizwert, 
            sp.spielwert, 
            sp.einzelspieler_id,
            sp.aktive_spieler_ids,
            COALESCE(spi.name, 'Eingepasst') AS einzelspieler_name
        FROM spiel sp
        LEFT JOIN spieler spi ON sp.einzelspieler_id = spi.id
        ORDER BY sp.id DESC LIMIT 10
    ''')
    historie_zeilen = cursor.fetchall()

    historie = []
    for zeile in historie_zeilen:
        eintrag = dict(zeile)

        aktive_str = eintrag.get("aktive_spieler_ids") or ""
        aktive_ids = [int(teil) for teil in aktive_str.split(",") if teil.strip()]
        einzel_id = eintrag.get("einzelspieler_id")

        gegner_ids = []
        if einzel_id is not None:
            gegner_ids = [sid for sid in aktive_ids if sid != einzel_id]

        gegner_namen = [
            spieler_id_zu_name.get(sid, f"Spielerin {sid}") for sid in gegner_ids
        ]

        eintrag["gegnerinnen"] = ", ".join(gegner_namen)
        historie.append(eintrag)

    # Prüfen, ob das Zurücknehmen des letzten Spiels aktuell möglich ist.
    # Basis: letztes Spiel = höchste id in der Historie.
    undo_moeglich = False
    if historie_zeilen:
        letztes_spiel_id = historie_zeilen[0]["id"]
        undo_moeglich = (_last_undo_game_id != letztes_spiel_id)
    
    verbindung.close()
    
    return jsonify({
        "punktestand": punktestand,
        "punktestand_monat": punktestand_monat,
        "punktestand_woche": punktestand_woche,
        "historie": historie,
        "undo_moeglich": undo_moeglich,
    })


# --- Server Start ---

if __name__ == '__main__':
    # Startet den Server im Entwicklungsmodus auf Port 5000
    print("Starte Skat-Backend auf http://127.0.0.1:5000")
    app.run(debug=True, port=5000, threaded=False, use_reloader=False)
