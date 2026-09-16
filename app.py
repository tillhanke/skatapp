#!/home/hanke/src/skatapp/.venv/bin/python
import json
import os
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from flask import Flask, Response, request, jsonify

import db_setup
import tisch as tisch_modul
import verlauf as verlauf_modul
from skat_engine import RegelFehler

# --- Konfiguration ---
# Pfad zur Datenbank; im Container via Umgebungsvariable auf ein gemountetes
# Verzeichnis gesetzt (WAL legt "-wal"/"-shm" neben der Datei an).
DB_DATEI = os.environ.get("SKAT_DB", "skat_daten.db")

# Seeger/Fabian: Multiplikator für „verlorene Spiele der anderen Mitspieler“ (Dreiertisch 40, Vierertisch 30).
# Diese App verwendet durchgängig Dreier-Runden (genau drei aktive Spielerinnen).
SEEGER_FABIAN_VERLUST_ANDERE = 40

# --- Undo-Status (in-memory, pro Prozess) ---
# Welche Runden haben ihr Undo bereits verbraucht? Nach einem erfolgreichen
# Zurücknehmen ist das nächste erst wieder möglich, sobald die Runde ein neues
# Spiel gespeichert hat - sonst könnte man sich rückwärts durch die Historie
# löschen.
_undo_verbraucht: set[str] = set()

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


def _start_of_current_day_local():
    """Heutiger Kalendertag, 00:00:00 (lokale Serverzeit)."""
    heute = date.today()
    return datetime.combine(heute, datetime.min.time())


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


# Je Prozess und Datenbankdatei wird das Schema einmal geprueft.
_schema_geprueft: set[str] = set()


def _schema_sicherstellen():
    """Zieht eine aeltere Datenbank automatisch nach.

    Frueher musste dafuer von Hand ``db_setup.py init`` laufen. Wer das im
    Container vergass, bekam beim ersten Remote-Tisch ein "no such table:
    tisch" um die Ohren - und zwar erst zur Laufzeit. Die Migration ist rein
    additiv, vorhandene Spiele bleiben unberuehrt.
    """
    if DB_DATEI in _schema_geprueft:
        return
    try:
        db_setup.datenbank_initialisieren(DB_DATEI, leise=True)
    except Exception:
        # Auch ein nicht beschreibbares Volume landet hier. Die eigentliche
        # Abfrage scheitert gleich danach mit einer sprechenden Meldung.
        app.logger.exception("Datenbankschema konnte nicht sichergestellt werden")
    finally:
        # Auch nach einem Fehlschlag nicht bei jeder Abfrage erneut versuchen.
        _schema_geprueft.add(DB_DATEI)


def hole_verbindung():
    """Stellt die Verbindung her und erlaubt Spaltenzugriff per Name."""
    _schema_sicherstellen()
    verbindung = sqlite3.connect(DB_DATEI, check_same_thread=False)
    # WAL erlaubt Lesen waehrend geschrieben wird - noetig, sobald mehrere
    # Remote-Tische gleichzeitig Spiele speichern.
    verbindung.execute("PRAGMA journal_mode=WAL")
    verbindung.execute("PRAGMA busy_timeout=5000")
    # Wichtig: row_factory konvertiert die Zeilen in Dictionary-ähnliche Objekte.
    # Das macht die Umwandlung in JSON für das Frontend später extrem einfach.
    verbindung.row_factory = sqlite3.Row 
    return verbindung


def hole_letztes_spiel(sitzung_id):
    """Lädt das zuletzt gespeicherte Spiel EINER Runde.

    Ohne die Einschränkung auf die Sitzung würde eine Runde das Spiel einer
    anderen zurücknehmen, sobald zwei Tische gleichzeitig laufen.
    """
    verbindung = hole_verbindung()
    cursor = verbindung.cursor()
    cursor.execute(
        """
        SELECT id, geber_id
        FROM spiel
        WHERE sitzung_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (sitzung_id,),
    )
    zeile = cursor.fetchone()
    verbindung.close()
    return zeile


def darf_zuruecknehmen(sitzung_id):
    """Gibt es in dieser Runde ein Spiel, das zurückgenommen werden darf?"""
    if not sitzung_id or sitzung_id in _undo_verbraucht:
        return False
    return hole_letztes_spiel(sitzung_id) is not None


def _spiel_zuruecknehmen(sitzung_id):
    """Entfernt das letzte Spiel einer Runde. Gibt (Antwortdaten, Status) zurück."""
    if not sitzung_id:
        return {"error": "Ohne Runden-Kennung kann kein Spiel zurückgenommen werden."}, 400

    if sitzung_id in _undo_verbraucht:
        return {"error": "Das letzte Spiel wurde bereits zurückgenommen."}, 409

    zeile = hole_letztes_spiel(sitzung_id)
    if zeile is None:
        return {"error": "In dieser Runde gibt es kein Spiel, das zurückgenommen werden kann."}, 400

    verbindung = hole_verbindung()
    verbindung.execute("DELETE FROM spiel WHERE id = ?", (zeile["id"],))
    verbindung.commit()
    verbindung.close()

    _undo_verbraucht.add(sitzung_id)

    return {
        "status": "erfolg",
        "entfernte_spiel_id": zeile["id"],
        "geber_id": zeile["geber_id"],
    }, 200


def _parse_bool_query_param(value):
    """Parst Query-Parameter zu bool (1/0, true/false, ja/nein)."""
    if value is None:
        return None
    normalisiert = str(value).strip().lower()
    if normalisiert in ("1", "true", "ja", "yes"):
        return True
    if normalisiert in ("0", "false", "nein", "no"):
        return False
    return None


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


@app.route('/suche')
def suche_seite():
    """Liefert die Suchseite des Frontends aus."""
    return app.send_static_file('suche.html')


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
    
    sitzung_id = daten.get('sitzung_id')

    sql = '''
        INSERT INTO spiel (
            aktive_spieler_ids, geber_id, einzelspieler_id, 
            spielart, reizwert, spitzen, hand, ouvert, 
            schneider_angesagt, schwarz_angesagt, schwarz_erreicht,
            augen, spielwert, sitzung_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    
    werte = (
        daten['aktive_spieler_ids'], daten['geber_id'], daten.get('einzelspieler_id'), 
        daten['spielart'], daten['reizwert'], daten.get('spitzen'),
        daten.get('hand', 0), daten.get('ouvert', 0), 
        daten.get('schneider_angesagt', 0), daten.get('schwarz_angesagt', 0),
        daten.get('schwarz_erreicht', 0),
        daten['augen'], spielwert, sitzung_id
    )
    
    cursor.execute(sql, werte)
    verbindung.commit()
    verbindung.close()

    # Nach erfolgreichem Speichern darf diese Runde wieder einmal zurücknehmen.
    _undo_verbraucht.discard(sitzung_id)
    return jsonify({"status": "erfolg", "spielwert": spielwert}), 201


@app.route('/api/spiel/undo', methods=['POST'])
def undo_letztes_spiel():
    """Entfernt das zuletzt gespeicherte Spiel DIESER Runde.

    Die Runde wird über ``sitzung_id`` identifiziert; ohne sie würde am
    falschen Tisch gelöscht. Pro Runde ist das Zurücknehmen einmal möglich
    und danach erst wieder, nachdem ein neues Spiel gespeichert wurde.
    """
    daten = request.get_json(silent=True) or {}
    antwort, status = _spiel_zuruecknehmen(daten.get('sitzung_id'))
    return jsonify(antwort), status


@app.route('/api/spiele/suche', methods=['GET'])
def suche_spiele():
    """Sucht Spiele anhand optionaler Filter und sortiert neueste zuerst."""
    verbindung = hole_verbindung()
    cursor = verbindung.cursor()

    where_parts = []
    params = []

    einzelspieler_id = request.args.get('einzelspieler_id', type=int)
    if einzelspieler_id is not None:
        where_parts.append("sp.einzelspieler_id = ?")
        params.append(einzelspieler_id)

    ergebnis = request.args.get('ergebnis')
    if ergebnis == "gewonnen":
        where_parts.append("sp.spielwert > 0")
    elif ergebnis == "verloren":
        where_parts.append("sp.spielwert < 0")

    spielart = request.args.get('spielart')
    if spielart:
        where_parts.append("sp.spielart = ?")
        params.append(spielart)

    schneider_angesagt = _parse_bool_query_param(request.args.get('schneider_angesagt'))
    if schneider_angesagt is True:
        where_parts.append("sp.schneider_angesagt = 1")
    elif schneider_angesagt is False:
        where_parts.append("sp.schneider_angesagt = 0")

    schwarz_angesagt = _parse_bool_query_param(request.args.get('schwarz_angesagt'))
    if schwarz_angesagt is True:
        where_parts.append("sp.schwarz_angesagt = 1")
    elif schwarz_angesagt is False:
        where_parts.append("sp.schwarz_angesagt = 0")

    schwarz_erreicht = _parse_bool_query_param(request.args.get('schwarz_erreicht'))
    if schwarz_erreicht is True:
        where_parts.append("sp.schwarz_erreicht = 1")
    elif schwarz_erreicht is False:
        where_parts.append("sp.schwarz_erreicht = 0")

    schneider_erreicht = _parse_bool_query_param(request.args.get('schneider_erreicht'))
    schneider_expr = (
        "(sp.spielart NOT IN ('Null', 'Eingepasst') AND (sp.augen >= 90 OR sp.augen <= 30))"
    )
    if schneider_erreicht is True:
        where_parts.append(schneider_expr)
    elif schneider_erreicht is False:
        where_parts.append(f"NOT {schneider_expr}")

    datum_von = request.args.get('datum_von')
    if datum_von:
        where_parts.append("date(sp.zeitstempel) >= date(?)")
        params.append(datum_von)

    datum_bis = request.args.get('datum_bis')
    if datum_bis:
        where_parts.append("date(sp.zeitstempel) <= date(?)")
        params.append(datum_bis)

    sql = """
        SELECT
            sp.id,
            sp.zeitstempel,
            sp.spielart,
            sp.reizwert,
            sp.spielwert,
            sp.augen,
            sp.einzelspieler_id,
            sp.aktive_spieler_ids,
            sp.schneider_angesagt,
            sp.schwarz_angesagt,
            sp.schwarz_erreicht,
            COALESCE(spi.name, 'Eingepasst') AS einzelspieler_name,
            CASE WHEN sp.spielwert > 0 THEN 1 ELSE 0 END AS gewonnen,
            CASE
                WHEN sp.spielart NOT IN ('Null', 'Eingepasst')
                     AND (sp.augen >= 90 OR sp.augen <= 30)
                THEN 1
                ELSE 0
            END AS schneider_erreicht
        FROM spiel sp
        LEFT JOIN spieler spi ON sp.einzelspieler_id = spi.id
    """

    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)

    sql += " ORDER BY sp.zeitstempel DESC, sp.id DESC"

    cursor.execute(sql, params)
    spiele = [dict(row) for row in cursor.fetchall()]
    verbindung.close()
    return jsonify(spiele)


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
    ab_tag = _start_of_current_day_local().strftime("%Y-%m-%d %H:%M:%S")
    punktestand_monat = hole_punktestand_mit_zeitfilter(cursor, ab_monat)
    punktestand_woche = hole_punktestand_mit_zeitfilter(cursor, ab_woche)
    punktestand_tag = hole_punktestand_mit_zeitfilter(cursor, ab_tag)

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

    verbindung.close()

    # Zurücknehmen bezieht sich immer auf die eigene Runde. Ohne Angabe einer
    # Runde (z. B. reine Dashboard-Ansicht) gibt es nichts zurückzunehmen.
    undo_moeglich = darf_zuruecknehmen(request.args.get('sitzung_id'))
    
    return jsonify({
        "punktestand": punktestand,
        "punktestand_monat": punktestand_monat,
        "punktestand_woche": punktestand_woche,
        "punktestand_tag": punktestand_tag,
        "historie": historie,
        "undo_moeglich": undo_moeglich,
    })


# ===========================================================================
#  Remote-Play: Tische, Aktionen, Server-Sent-Events
# ===========================================================================

# Laufende Tische liegen im Prozessspeicher; jede Aenderung wird zusaetzlich
# als JSON-Snapshot in die Tabelle "tisch" geschrieben. Deshalb laeuft die App
# im Container bewusst mit genau EINEM gunicorn-Worker.
_tische: dict[str, tisch_modul.Tisch] = {}
_tisch_sperre = threading.RLock()

# Wie oft der SSE-Strom nach Aenderungen schaut bzw. ein Lebenszeichen sendet.
_SSE_TAKT_SEKUNDEN = 0.4
_SSE_PING_SEKUNDEN = 15


def _tisch_speichern(tisch):
    verbindung = hole_verbindung()
    verbindung.execute(
        """
        INSERT INTO tisch (code, zustand, version, zuletzt_aktiv)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(code) DO UPDATE SET
            zustand = excluded.zustand,
            version = excluded.version,
            zuletzt_aktiv = CURRENT_TIMESTAMP
        """,
        (tisch.code, json.dumps(tisch.als_dict()), tisch.version),
    )
    verbindung.commit()
    verbindung.close()


def _tisch_holen(code):
    """Tisch aus dem Speicher holen oder aus dem Snapshot wiederherstellen."""
    code = (code or "").strip().upper()
    if not code:
        return None
    with _tisch_sperre:
        if code in _tische:
            return _tische[code]
        verbindung = hole_verbindung()
        zeile = verbindung.execute(
            "SELECT zustand FROM tisch WHERE code = ? AND geschlossen = 0", (code,)
        ).fetchone()
        verbindung.close()
        if zeile is None:
            return None
        tisch = tisch_modul.Tisch.aus_dict(json.loads(zeile["zustand"]))
        _tische[code] = tisch
        return tisch


def _token_aus_request(code):
    """Token aus Body, Header oder Cookie - nie aus der URL, ausser fuer SSE.

    EventSource kann keine Header setzen, deshalb wird beim Beitritt zusaetzlich
    ein Cookie gesetzt, das der Ereignisstrom mitbenutzt.
    """
    daten = request.get_json(silent=True) or {}
    return (
        daten.get("token")
        or request.headers.get("X-Skat-Token")
        or request.cookies.get(f"skat_token_{code}")
        or request.args.get("token")
    )


def _tisch_und_token(code):
    """Fuer alles, was nur Sitzende duerfen (starten, geben, entfernen, ...)."""
    tisch = _tisch_holen(code)
    if tisch is None:
        raise LookupError(f"Kein Tisch mit dem Code {code!r}.")
    token = _token_aus_request((code or "").strip().upper())
    if tisch.spieler_nach_token(token) is None:
        raise PermissionError("Du sitzt nicht an diesem Tisch.")
    return tisch, token


def _tisch_und_teilnehmer(code):
    """Fuer Zuschauen und Gehen - Sitzende wie Zuschauende.

    Bewusst getrennt von _tisch_und_token: wer nur zuschaut, soll den Tisch
    sehen und ihn verlassen koennen, aber nicht die Partie steuern.
    """
    tisch = _tisch_holen(code)
    if tisch is None:
        raise LookupError(f"Kein Tisch mit dem Code {code!r}.")
    token = _token_aus_request((code or "").strip().upper())
    eintrag, _ = tisch.teilnehmer_nach_token(token)
    if eintrag is None:
        raise PermissionError("Du gehoerst nicht zu diesem Tisch.")
    return tisch, token


@app.errorhandler(RegelFehler)
def _regelfehler_beantworten(fehler):
    return jsonify({"error": str(fehler)}), 400


@app.errorhandler(LookupError)
def _nicht_gefunden_beantworten(fehler):
    return jsonify({"error": str(fehler)}), 404


@app.errorhandler(PermissionError)
def _verboten_beantworten(fehler):
    return jsonify({"error": str(fehler)}), 403


@app.route('/spielen')
def spielen_seite():
    """Remote-Play-Oberflaeche. Der Einladungslink hat die Form /spielen?code=ABC123."""
    return app.send_static_file('spielen.html')


@app.route('/api/tisch', methods=['POST'])
def tisch_anlegen():
    tisch = tisch_modul.Tisch()
    with _tisch_sperre:
        _tische[tisch.code] = tisch
    _tisch_speichern(tisch)
    return jsonify({"code": tisch.code}), 201


@app.route('/api/tisch/<code>', methods=['GET'])
def tisch_uebersicht(code):
    """Oeffentliche Lobby-Info: wer sitzt schon, wer kann noch beitreten.

    Bewusst ohne Token - diese Seite sieht man ueber den Einladungslink,
    bevor man einen Platz hat. Karten stehen hier nicht drin.
    """
    tisch = _tisch_holen(code)
    if tisch is None:
        raise LookupError(f"Kein Tisch mit dem Code {code!r}.")

    verbindung = hole_verbindung()
    alle = [dict(z) for z in verbindung.execute("SELECT id, name FROM spieler ORDER BY name")]
    verbindung.close()

    belegt = {s["id"] for s in tisch.spieler + tisch.zuschauer}
    token = _token_aus_request(tisch.code)
    eigener, zuschauend = tisch.teilnehmer_nach_token(token)

    # Niemand wird abgewiesen - aber wer jetzt kommt, schaut womoeglich erst zu.
    if tisch.phase == tisch_modul.PHASE_LOBBY and tisch.platz_frei():
        beitritt_als = "spieler"
    elif not tisch.platz_frei():
        beitritt_als = "zuschauer_voll"
    else:
        beitritt_als = "zuschauer_partie_laeuft"

    return jsonify({
        "code": tisch.code,
        "phase": tisch.phase,
        "version": tisch.version,
        "sitzend": [{"id": s["id"], "name": s["name"]} for s in tisch.spieler],
        "zuschauer": [{"id": z["id"], "name": z["name"]} for z in tisch.zuschauer],
        "frei": [s for s in alle if s["id"] not in belegt],
        "voll": not tisch.platz_frei(),
        "beitritt_als": beitritt_als,
        "ich": None if eigener is None else {
            "id": eigener["id"], "name": eigener["name"],
            "rolle": "zuschauer" if zuschauend else "spieler",
        },
    })


@app.route('/api/tisch/<code>/beitreten', methods=['POST'])
def tisch_beitreten(code):
    tisch = _tisch_holen(code)
    if tisch is None:
        raise LookupError(f"Kein Tisch mit dem Code {code!r}.")

    daten = request.get_json(silent=True) or {}
    spieler_id = daten.get("spieler_id")
    if spieler_id is None:
        raise RegelFehler("Es fehlt die Angabe, wer beitreten moechte.")

    verbindung = hole_verbindung()
    zeile = verbindung.execute(
        "SELECT id, name FROM spieler WHERE id = ?", (int(spieler_id),)
    ).fetchone()
    verbindung.close()
    if zeile is None:
        raise RegelFehler("Diese Spielerin steht nicht in der Datenbank.")

    token, rolle = tisch.beitreten(zeile["id"], zeile["name"])
    _tisch_speichern(tisch)

    antwort = jsonify({
        "token": token,
        "spieler_id": zeile["id"],
        "name": zeile["name"],
        "rolle": rolle,
        # Warum nur zuschauen? Danach richtet sich der Hinweis im Browser.
        "grund": None if rolle == "spieler" else (
            "voll" if not tisch.platz_frei() else "partie_laeuft"
        ),
    })
    # Cookie, damit der Ereignisstrom (EventSource) sich ausweisen kann.
    antwort.set_cookie(
        f"skat_token_{tisch.code}", token,
        max_age=60 * 60 * 24 * 7, samesite="Lax", httponly=False, path="/",
    )
    return antwort, 201


@app.route('/api/tisch/<code>/reihenfolge', methods=['POST'])
def tisch_reihenfolge(code):
    tisch, _ = _tisch_und_token(code)
    daten = request.get_json(silent=True) or {}
    tisch.reihenfolge_setzen([int(i) for i in daten.get("reihenfolge", [])])
    _tisch_speichern(tisch)
    return jsonify({"status": "erfolg", "version": tisch.version})


@app.route('/api/tisch/<code>/starten', methods=['POST'])
def tisch_starten(code):
    tisch, _ = _tisch_und_token(code)
    tisch.starten()
    _tisch_speichern(tisch)
    return jsonify({"status": "erfolg", "version": tisch.version})


@app.route('/api/tisch/<code>/naechstes', methods=['POST'])
def tisch_naechstes_spiel(code):
    tisch, _ = _tisch_und_token(code)
    tisch.naechstes_spiel()
    _tisch_speichern(tisch)
    return jsonify({"status": "erfolg", "version": tisch.version})


@app.route('/api/tisch/<code>/zustand', methods=['GET'])
def tisch_zustand(code):
    tisch, token = _tisch_und_teilnehmer(code)
    aufdecken = _parse_bool_query_param(request.args.get('aufdecken')) or False
    return jsonify(tisch.sicht_fuer(token, aufdecken))


@app.route('/api/tisch/<code>/aktion', methods=['POST'])
def tisch_aktion(code):
    # Zuschauende kommen bis hierher, damit Tisch.aktion() ihnen erklaeren
    # kann, dass sie ab dem naechsten Spiel dabei sind - statt eines nackten
    # "du sitzt nicht an diesem Tisch".
    tisch, token = _tisch_und_teilnehmer(code)
    daten = request.get_json(silent=True) or {}
    name = daten.get("aktion")
    if not name:
        raise RegelFehler("Es fehlt die Angabe, welche Aktion gemeint ist.")

    ergebnis = tisch.aktion(token, name, daten.get("daten"))

    # Ist ein Spiel zu Ende, wandert es sofort in dieselbe Tabelle wie die
    # von Hand eingetragenen Spiele - nur mit quelle = 'remote'.
    if ergebnis.get("beendet"):
        spiel_id = _spiel_zeile_speichern(ergebnis["beendet"])
        _protokolliere_still(tisch, spiel_id)

    _tisch_speichern(tisch)
    return jsonify({
        "status": "erfolg",
        "version": tisch.version,
        "beendet": ergebnis.get("beendet"),
    })


def _spiel_zeile_speichern(zeile):
    """Schreibt ein remote gespieltes Spiel in die Tabelle ``spiel``.

    Gibt die vergebene id zurueck - das Protokoll in der zweiten Datenbank
    verweist darauf.
    """
    verbindung = hole_verbindung()
    zeiger = verbindung.execute(
        """
        INSERT INTO spiel (
            aktive_spieler_ids, geber_id, einzelspieler_id,
            spielart, reizwert, spitzen, hand, ouvert,
            schneider_angesagt, schwarz_angesagt, schwarz_erreicht,
            augen, spielwert, quelle, sitzung_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            zeile["aktive_spieler_ids"], zeile["geber_id"], zeile["einzelspieler_id"],
            zeile["spielart"], zeile["reizwert"], zeile["spitzen"],
            zeile["hand"], zeile["ouvert"], zeile["schneider_angesagt"],
            zeile["schwarz_angesagt"], zeile["schwarz_erreicht"],
            zeile["augen"], zeile["spielwert"], zeile["quelle"],
            zeile["sitzung_id"],
        ),
    )
    spiel_id = zeiger.lastrowid
    verbindung.commit()
    verbindung.close()
    _undo_verbraucht.discard(zeile["sitzung_id"])
    return spiel_id


@app.route('/api/tisch/<code>/lobby', methods=['POST'])
def tisch_zurueck_in_die_lobby(code):
    """Beendet die Runde und gibt die Aufstellung wieder frei."""
    tisch, token = _tisch_und_token(code)
    tisch.zurueck_in_die_lobby(token)
    _tisch_speichern(tisch)
    return jsonify({"status": "erfolg", "phase": tisch.phase, "version": tisch.version})


@app.route('/api/tisch/<code>/verlassen', methods=['POST'])
def tisch_verlassen(code):
    """Gibt den eigenen Platz frei. Zuschauende koennen jederzeit gehen."""
    tisch, token = _tisch_und_teilnehmer(code)
    tisch.verlassen(token)
    _tisch_speichern(tisch)
    return jsonify({"status": "erfolg", "version": tisch.version})


@app.route('/api/tisch/<code>/entfernen', methods=['POST'])
def tisch_spieler_entfernen(code):
    """Entfernt eine offline gegangene Spielerin und gibt sofort neu."""
    tisch, token = _tisch_und_token(code)
    daten = request.get_json(silent=True) or {}
    spieler_id = daten.get("spieler_id")
    if spieler_id is None:
        raise RegelFehler("Es fehlt die Angabe, wer entfernt werden soll.")

    ergebnis = tisch.spieler_entfernen(token, int(spieler_id))
    _tisch_speichern(tisch)
    return jsonify(dict(ergebnis, status="erfolg", phase=tisch.phase,
                        version=tisch.version))


@app.route('/api/tisch/<code>/undo', methods=['POST'])
def tisch_undo(code):
    """Nimmt das zuletzt an diesem Tisch gespielte Spiel zurück."""
    tisch, _ = _tisch_und_token(code)

    # Erst prüfen, ob der Tisch überhaupt zurücknehmen darf - sonst wäre die
    # Zeile schon gelöscht, während der Tisch unverändert bliebe.
    tisch.zuruecknehmen_pruefen()

    antwort, status = _spiel_zuruecknehmen(tisch.sitzung_id)
    if status != 200:
        return jsonify(antwort), status

    tisch.letztes_spiel_zuruecknehmen()
    _verlauf_zuruecknehmen_still(antwort["entfernte_spiel_id"])
    _tisch_speichern(tisch)
    return jsonify(dict(antwort, version=tisch.version)), 200


def _protokolliere_still(tisch, spiel_id):
    """Schreibt den Spielverlauf ins Zweitprotokoll.

    Bewusst abgesichert: das Protokoll ist eine Zugabe. Geht dabei etwas
    schief, ist das Spiel trotzdem gespielt und in skat_daten.db gezaehlt -
    der Tisch darf daran nicht haengenbleiben.
    """
    try:
        return verlauf_modul.protokolliere(tisch, spiel_id)
    except Exception:
        app.logger.exception("Spielverlauf konnte nicht protokolliert werden")
        return None


def _verlauf_zuruecknehmen_still(spiel_id):
    try:
        verlauf_modul.als_zurueckgenommen_markieren(spiel_id)
    except Exception:
        app.logger.exception("Zuruecknahme konnte im Protokoll nicht vermerkt werden")


@app.route('/api/tisch/<code>/ereignisse', methods=['GET'])
def tisch_ereignisse(code):
    """Server-Sent-Events: schiebt bei jeder Zustandsaenderung die neue Sicht.

    Jede Spielerin bekommt ihre eigene, gefilterte Sicht - der Strom ist kein
    Rundruf eines gemeinsamen Zustands.
    """
    tisch, token = _tisch_und_teilnehmer(code)
    aufdecken = _parse_bool_query_param(request.args.get('aufdecken')) or False
    tisch_code = tisch.code

    def strom():
        letzte_version = None
        letztes_lebenszeichen = time.time()
        while True:
            aktueller = _tisch_holen(tisch_code)
            if aktueller is None:
                yield "event: ende\ndata: {}\n\n"
                return

            # Der offene Strom IST das Lebenszeichen. Ohne diese Zeile gälten
            # alle als offline, sobald eine Weile niemand am Zug ist - denn
            # ohne Zustandsänderung würde auch keine Sicht berechnet.
            aktueller.gesehen(token)

            # Fällt dabei auf, dass jemand offline gegangen ist, zählt das als
            # Zustandsänderung: die anderen sollen den Hinweis sofort sehen.
            aktueller.verbindungen_pruefen()

            if aktueller.spieler_nach_token(token) is None:
                # Zwischenzeitlich vom Tisch entfernt worden.
                yield "event: ende\ndata: {}\n\n"
                return

            if aktueller.version != letzte_version:
                letzte_version = aktueller.version
                nutzlast = json.dumps(aktueller.sicht_fuer(token, aufdecken))
                yield f"event: zustand\ndata: {nutzlast}\n\n"
                letztes_lebenszeichen = time.time()
            elif time.time() - letztes_lebenszeichen > _SSE_PING_SEKUNDEN:
                # Kommentarzeile haelt Proxys und Mobilfunk-NAT offen.
                yield ": ping\n\n"
                letztes_lebenszeichen = time.time()

            time.sleep(_SSE_TAKT_SEKUNDEN)

    return Response(
        strom(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # nginx nicht puffern lassen
        },
    )


# --- Server Start ---

if __name__ == '__main__':
    # Startet den Server im Entwicklungsmodus auf Port 5000
    print("Starte Skat-Backend auf http://127.0.0.1:5000")
    # threaded=True ist noetig: die SSE-Verbindungen bleiben dauerhaft offen.
    app.run(debug=True, port=5000, threaded=True, use_reloader=False)
