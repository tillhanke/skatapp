"""Eine ältere Datenbank muss sich von selbst nachziehen.

Ausgangspunkt war ein echter Fehler: der Container lief mit einer Datenbank
aus der Zeit vor dem Remote-Play, und der erste Tisch scheiterte mit
"no such table: tisch". Von Hand ``db_setup.py init`` laufen zu lassen war
eine Bringschuld, an die niemand denkt.
"""

import sqlite3

import pytest

import db_setup


# Genau das Schema, das die App vor dem Remote-Play hatte.
ALTES_SCHEMA = """
CREATE TABLE spieler (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);
CREATE TABLE spiel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeitstempel DATETIME DEFAULT CURRENT_TIMESTAMP,
    aktive_spieler_ids TEXT NOT NULL,
    geber_id INTEGER NOT NULL,
    einzelspieler_id INTEGER,
    spielart TEXT NOT NULL,
    reizwert INTEGER NOT NULL,
    spitzen INTEGER,
    hand INTEGER DEFAULT 0,
    ouvert INTEGER DEFAULT 0,
    schneider_angesagt INTEGER DEFAULT 0,
    schwarz_angesagt INTEGER DEFAULT 0,
    schwarz_erreicht INTEGER DEFAULT 0,
    spielwert INTEGER NOT NULL,
    augen INTEGER NOT NULL
);
"""


@pytest.fixture
def alte_db(tmp_path):
    """Datenbank im alten Stand, mit echten Bestandsdaten."""
    pfad = str(tmp_path / "alt.db")
    verb = sqlite3.connect(pfad)
    verb.executescript(ALTES_SCHEMA)
    verb.executemany("INSERT INTO spieler (name) VALUES (?)",
                     [("Anna",), ("Berta",), ("Clara",)])
    verb.executemany(
        "INSERT INTO spiel (aktive_spieler_ids, geber_id, einzelspieler_id,"
        " spielart, reizwert, spitzen, augen, spielwert)"
        " VALUES ('1,2,3', 1, ?, 'Grand', 18, 1, ?, ?)",
        [(1, 80, 48), (2, 55, -96), (3, 95, 72)],
    )
    verb.commit()
    verb.close()
    return pfad


def spalten(pfad, tabelle):
    verb = sqlite3.connect(pfad)
    namen = {z[1] for z in verb.execute(f"PRAGMA table_info({tabelle})")}
    verb.close()
    return namen


def tabellen(pfad):
    verb = sqlite3.connect(pfad)
    namen = {z[0] for z in verb.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    verb.close()
    return namen


def test_ausgangslage_ist_wirklich_alt(alte_db):
    assert "tisch" not in tabellen(alte_db)
    assert "quelle" not in spalten(alte_db, "spiel")
    assert "sitzung_id" not in spalten(alte_db, "spiel")


def test_app_zieht_das_schema_beim_ersten_zugriff_nach(alte_db, monkeypatch):
    """Der eigentliche Fehler: /api/tisch lief gegen eine Datenbank ohne tisch."""
    import app as skat_app
    monkeypatch.setattr(skat_app, "DB_DATEI", alte_db)
    skat_app._schema_geprueft.clear()
    skat_app._tische.clear()

    client = skat_app.app.test_client()
    antwort = client.post("/api/tisch")
    assert antwort.status_code == 201, antwort.get_data(as_text=True)

    assert "tisch" in tabellen(alte_db)
    assert {"quelle", "sitzung_id"} <= spalten(alte_db, "spiel")


def test_bestandsdaten_ueberleben_die_migration(alte_db, monkeypatch):
    import app as skat_app
    monkeypatch.setattr(skat_app, "DB_DATEI", alte_db)
    skat_app._schema_geprueft.clear()

    client = skat_app.app.test_client()
    stand = client.get("/api/stand").get_json()

    assert {s["name"] for s in stand["punktestand"]} == {"Anna", "Berta", "Clara"}
    assert len(stand["historie"]) == 3
    # Punkte unverändert: 48 + (-96) + 72
    assert sum(s["gesamtpunkte"] for s in stand["punktestand"]) == 24

    verb = sqlite3.connect(alte_db)
    # Altbestand bekommt die Voreinstellung, keine erfundene Sitzung.
    herkunft = verb.execute("SELECT DISTINCT quelle FROM spiel").fetchall()
    sitzungen = verb.execute("SELECT DISTINCT sitzung_id FROM spiel").fetchall()
    verb.close()
    assert herkunft == [("manuell",)]
    assert sitzungen == [(None,)]


def test_halb_migrierte_datenbank_wird_vervollstaendigt(alte_db):
    """Der Fall, der hier tatsächlich vorlag: quelle da, sitzung_id fehlt."""
    verb = sqlite3.connect(alte_db)
    verb.execute("ALTER TABLE spiel ADD COLUMN quelle TEXT DEFAULT 'manuell'")
    verb.commit()
    verb.close()

    db_setup.datenbank_initialisieren(alte_db, leise=True)

    assert {"quelle", "sitzung_id"} <= spalten(alte_db, "spiel")
    assert "tisch" in tabellen(alte_db)


def test_migration_ist_mehrfach_aufrufbar(alte_db):
    for _ in range(3):
        db_setup.datenbank_initialisieren(alte_db, leise=True)

    verb = sqlite3.connect(alte_db)
    anzahl = verb.execute("SELECT COUNT(*) FROM spiel").fetchone()[0]
    verb.close()
    assert anzahl == 3, "Wiederholte Migration darf nichts doppeln oder löschen"


def test_ganz_neue_datenbank_entsteht_vollstaendig(tmp_path, monkeypatch):
    import app as skat_app
    pfad = str(tmp_path / "neu" / "frisch.db")
    monkeypatch.setattr(skat_app, "DB_DATEI", pfad)
    skat_app._schema_geprueft.clear()
    skat_app._tische.clear()

    client = skat_app.app.test_client()
    assert client.post("/api/tisch").status_code == 201
    assert {"spieler", "spiel", "tisch"} <= tabellen(pfad)
