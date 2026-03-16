#!/home/hanke/src/skatapp/.venv/bin/python
import sqlite3
import argparse

# --- Konfiguration ---
DB_DATEI = "skat_daten.db"

# --- Datenbank-Funktionen ---

def hole_verbindung():
    """Stellt die Verbindung zur lokalen SQLite-Datenbank her."""
    return sqlite3.connect(DB_DATEI)


def setze_db_datei(pfad):
    """Setzt die zu verwendende Datenbankdatei global."""
    global DB_DATEI
    DB_DATEI = pfad

def datenbank_initialisieren():
    """Erstellt die Tabellen, falls sie noch nicht existieren."""
    verbindung = hole_verbindung()
    cursor = verbindung.cursor()

    # Tabelle für die Spielerinnen erstellen
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spieler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    # Tabelle für die einzelnen Skatspiele erstellen
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spiel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zeitstempel DATETIME DEFAULT CURRENT_TIMESTAMP,
            
            -- Wer war am Tisch? (Kommagetrennte IDs, z.B. "1,2,3")
            aktive_spieler_ids TEXT NOT NULL, 
            
            -- Spielrollen
            geber_id INTEGER NOT NULL,
            einzelspieler_id INTEGER, -- Kann NULL sein, wenn eingepasst wurde
            
            -- Spieldetails
            spielart TEXT NOT NULL,   -- z.B. 'Farbspiel', 'Grand', 'Null', 'Eingepasst'
            reizwert INTEGER NOT NULL,
            spitzen INTEGER,          -- z.B. 2 (für "mit 2"), -1 (für "ohne 1")
            
            -- Extras (1 = Ja, 0 = Nein)
            hand INTEGER DEFAULT 0,
            ouvert INTEGER DEFAULT 0,
            schneider_angesagt INTEGER DEFAULT 0,
            schwarz_angesagt INTEGER DEFAULT 0,
            schwarz_erreicht INTEGER DEFAULT 0,
            
            -- Das Ergebnis
            spielwert INTEGER NOT NULL,  -- Der errechnete Spielwert
            augen INTEGER NOT NULL       -- Eingeholte Punkte
        )
    ''')

    # Schema-Migration für bestehende Datenbanken:
    # Versuche, die Spalte "schwarz_erreicht" nachträglich hinzuzufügen,
    # falls sie noch nicht existiert.
    try:
        cursor.execute(
            'ALTER TABLE spiel ADD COLUMN schwarz_erreicht INTEGER DEFAULT 0'
        )
    except sqlite3.OperationalError:
        # Spalte existiert bereits oder ALTER TABLE ist nicht nötig.
        pass

    verbindung.commit()
    verbindung.close()
    print("Datenbank und Tabellen wurden erfolgreich initialisiert.")


def spieler_hinzufuegen(namen_liste):
    """Fügt vordefinierte Spielerinnen in die Datenbank ein."""
    verbindung = hole_verbindung()
    cursor = verbindung.cursor()

    for name in namen_liste:
        try:
            # INSERT OR IGNORE verhindert Fehler, falls der Name schon existiert
            cursor.execute("INSERT OR IGNORE INTO spieler (name) VALUES (?)", (name,))
        except sqlite3.Error as e:
            print(f"Fehler beim Einfügen von {name}: {e}")

    verbindung.commit()
    verbindung.close()
    print(f"Spielerinnen {namen_liste} wurden in der Datenbank registriert.")


def weitere_spielerinnen_hinzufuegen(namen_liste):
    """
    Fügt zusätzliche Spielerinnen zu einer bereits bestehenden Datenbank hinzu.

    Die Funktion kann jederzeit aufgerufen werden, auch wenn bereits Spiele
    oder Spieler:innen in der Datenbank vorhanden sind. Durch
    INSERT OR IGNORE werden doppelte Namen automatisch übersprungen.
    """
    spieler_hinzufuegen(namen_liste)


def _baue_arg_parser():
    parser = argparse.ArgumentParser(
        description="Initialisiert eine Skat-Datenbank und fügt Spielerinnen hinzu."
    )

    parser.add_argument(
        "--db",
        dest="db_datei",
        default=DB_DATEI,
        help=f"Pfad zur Datenbankdatei (Standard: {DB_DATEI})",
    )

    subparsers = parser.add_subparsers(dest="befehl", required=True)

    # Befehl: init – neue/ggf. leere DB initialisieren und Spielerinnen setzen
    parser_init = subparsers.add_parser(
        "init",
        help=(
            "Neue Datenbank initialisieren (oder bestehende Struktur sicherstellen) "
            "und eine Liste von Spielerinnen eintragen."
        ),
    )
    parser_init.add_argument(
        "--spielerinnen",
        nargs="+",
        metavar="NAME",
        help="Namen der Spielerinnen, die initial in die Datenbank eingetragen werden sollen.",
    )

    # Befehl: add – weitere Spielerinnen zu bestehender DB hinzufügen
    parser_add = subparsers.add_parser(
        "add",
        help="Weitere Spielerinnen zu einer bestehenden Datenbank hinzufügen.",
    )
    parser_add.add_argument(
        "--spielerinnen",
        nargs="+",
        required=True,
        metavar="NAME",
        help="Namen der zusätzlichen Spielerinnen.",
    )

    return parser


def main():
    parser = _baue_arg_parser()
    args = parser.parse_args()

    # ggf. alternative DB-Datei setzen
    if args.db_datei:
        setze_db_datei(args.db_datei)

    if args.befehl == "init":
        # Tabellen anlegen (falls nicht vorhanden)
        datenbank_initialisieren()

        # Optional initiale Spielerinnen eintragen
        if args.spielerinnen:
            spieler_hinzufuegen(args.spielerinnen)
    elif args.befehl == "add":
        weitere_spielerinnen_hinzufuegen(args.spielerinnen)
    else:
        # Sollte durch required=True bei subparsers eigentlich nie passieren
        parser.print_help()


# --- Hauptprogramm ---


if __name__ == "__main__":
    main()
