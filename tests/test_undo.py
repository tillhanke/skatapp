"""Zurücknehmen darf immer nur die eigene Runde treffen.

Vorher löschte /api/spiel/undo das global letzte Spiel. Liefen zwei Runden
gleichzeitig, nahm die eine der anderen das Spiel weg.
"""

import random
import sqlite3

import pytest

import skat_engine as e
from test_api_tisch import tisch_aufsetzen, zustand, aktion, _partie_ueber_api_spielen


def spiel_speichern(client, sitzung_id, augen=80, spieler="1,2,3"):
    """Trägt ein Spiel von Hand ein, wie es das Formular tut."""
    antwort = client.post("/api/spiel", json={
        "aktive_spieler_ids": spieler,
        "geber_id": 1,
        "einzelspieler_id": int(spieler.split(",")[0]),
        "spielart": "Grand",
        "reizwert": 18,
        "spitzen": 1,
        "augen": augen,
        "sitzung_id": sitzung_id,
    })
    assert antwort.status_code == 201, antwort.get_json()
    return antwort.get_json()


def undo(client, sitzung_id):
    return client.post("/api/spiel/undo", json={"sitzung_id": sitzung_id})


def spiele_in_db(pfad):
    verbindung = sqlite3.connect(pfad)
    verbindung.row_factory = sqlite3.Row
    zeilen = [dict(z) for z in verbindung.execute(
        "SELECT id, sitzung_id, augen FROM spiel ORDER BY id")]
    verbindung.close()
    return zeilen


# --- Kernfall: zwei Runden gleichzeitig ------------------------------------

def test_undo_trifft_nur_die_eigene_runde(client, testdb):
    """Der Fehler, um den es geht: Runde A nimmt Runde B das Spiel weg."""
    spiel_speichern(client, "lokal:A", augen=70)
    spiel_speichern(client, "lokal:B", augen=80)
    spiel_speichern(client, "lokal:A", augen=90)
    # Reihenfolge in der DB: A(70), B(80), A(90) - global zuletzt ist A(90).

    antwort = undo(client, "lokal:B")
    assert antwort.status_code == 200

    uebrig = spiele_in_db(testdb)
    assert [(z["sitzung_id"], z["augen"]) for z in uebrig] == [
        ("lokal:A", 70), ("lokal:A", 90),
    ], "Es muss das Spiel von B verschwinden, nicht das global letzte von A"


def test_undo_ohne_eigenes_spiel_geht_nicht(client, testdb):
    spiel_speichern(client, "lokal:A")
    antwort = undo(client, "lokal:B")
    assert antwort.status_code == 400
    assert len(spiele_in_db(testdb)) == 1, "Fremde Spiele bleiben unberührt"


def test_undo_ohne_runde_wird_abgelehnt(client, testdb):
    spiel_speichern(client, "lokal:A")
    antwort = client.post("/api/spiel/undo", json={})
    assert antwort.status_code == 400
    assert len(spiele_in_db(testdb)) == 1


def test_altbestand_ohne_runde_ist_nicht_zuruecknehmbar(client, testdb):
    """Spiele aus der Zeit vor den Sitzungen haben sitzung_id NULL."""
    verbindung = sqlite3.connect(testdb)
    verbindung.execute(
        "INSERT INTO spiel (aktive_spieler_ids, geber_id, spielart, reizwert,"
        " augen, spielwert) VALUES ('1,2,3', 1, 'Grand', 18, 80, 48)"
    )
    verbindung.commit()
    verbindung.close()

    assert client.post("/api/spiel/undo", json={"sitzung_id": None}).status_code == 400
    assert len(spiele_in_db(testdb)) == 1


# --- Nur einmal pro Spiel ---------------------------------------------------

def test_zweites_undo_erst_nach_neuem_spiel(client, testdb):
    """Sonst könnte man sich rückwärts durch die ganze Historie löschen."""
    spiel_speichern(client, "lokal:A", augen=70)
    spiel_speichern(client, "lokal:A", augen=80)

    assert undo(client, "lokal:A").status_code == 200
    zweites = undo(client, "lokal:A")
    assert zweites.status_code == 409
    assert "bereits zurückgenommen" in zweites.get_json()["error"]

    # Das erste Spiel steht noch.
    assert [z["augen"] for z in spiele_in_db(testdb)] == [70]

    # Nach einem neuen Spiel ist Zurücknehmen wieder erlaubt.
    spiel_speichern(client, "lokal:A", augen=95)
    assert undo(client, "lokal:A").status_code == 200
    assert [z["augen"] for z in spiele_in_db(testdb)] == [70]


def test_undo_sperre_gilt_je_runde(client, testdb):
    """Dass A sein Undo verbraucht hat, darf B nicht blockieren."""
    spiel_speichern(client, "lokal:A")
    spiel_speichern(client, "lokal:B")
    assert undo(client, "lokal:A").status_code == 200
    assert undo(client, "lokal:A").status_code == 409
    assert undo(client, "lokal:B").status_code == 200, "B hat sein eigenes Undo"


# --- undo_moeglich im Dashboard --------------------------------------------

def test_undo_moeglich_haengt_an_der_runde(client):
    spiel_speichern(client, "lokal:A")

    def moeglich(sitzung=None):
        pfad = "/api/stand" + (f"?sitzung_id={sitzung}" if sitzung else "")
        return client.get(pfad).get_json()["undo_moeglich"]

    assert moeglich("lokal:A") is True
    assert moeglich("lokal:B") is False, "Fremde Runde darf nichts zurücknehmen"
    assert moeglich() is False, "Ohne Runde (reines Dashboard) gibt es kein Undo"

    undo(client, "lokal:A")
    assert moeglich("lokal:A") is False, "Nach dem Undo erst wieder nach neuem Spiel"


# --- Remote-Tisch -----------------------------------------------------------

def test_tisch_nimmt_eigenes_spiel_zurueck(client, testdb):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})
    _partie_ueber_api_spielen(client, code, tokens, random.Random(8))

    assert len(spiele_in_db(testdb)) == 1
    sicht = zustand(client, code, erster)
    assert sicht["undo_moeglich"] is True
    assert sicht["sitzung_id"] == f"tisch:{code}"

    antwort = client.post(f"/api/tisch/{code}/undo", headers={"X-Skat-Token": erster})
    assert antwort.status_code == 200, antwort.get_json()

    assert spiele_in_db(testdb) == []
    nachher = zustand(client, code, erster)
    assert nachher["ergebnisse"] == []
    assert nachher["undo_moeglich"] is False


def test_tisch_wiederholt_mit_derselben_geberin(client):
    """Nach dem Zurücknehmen gibt dieselbe Spielerin noch einmal."""
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara", "Dora"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})
    _partie_ueber_api_spielen(client, code, tokens, random.Random(9))

    geber_vorher = zustand(client, code, erster)["geber_id"]
    client.post(f"/api/tisch/{code}/undo", headers={"X-Skat-Token": erster})
    client.post(f"/api/tisch/{code}/naechstes", headers={"X-Skat-Token": erster})

    assert zustand(client, code, erster)["geber_id"] == geber_vorher


def test_tisch_undo_nur_zwischen_zwei_spielen(client, testdb):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})

    # Mitten im laufenden Spiel: nicht erlaubt.
    assert zustand(client, code, erster)["undo_moeglich"] is False
    antwort = client.post(f"/api/tisch/{code}/undo", headers={"X-Skat-Token": erster})
    assert antwort.status_code == 400
    assert "bevor neu gegeben" in antwort.get_json()["error"]

    _partie_ueber_api_spielen(client, code, tokens, random.Random(10))
    client.post(f"/api/tisch/{code}/naechstes", headers={"X-Skat-Token": erster})

    # Es läuft wieder ein Spiel - das alte ist jetzt nicht mehr zurücknehmbar.
    antwort = client.post(f"/api/tisch/{code}/undo", headers={"X-Skat-Token": erster})
    assert antwort.status_code == 400
    assert len(spiele_in_db(testdb)) == 1, "Das gespeicherte Spiel bleibt erhalten"


def test_tisch_undo_braucht_einen_platz_am_tisch(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})
    _partie_ueber_api_spielen(client, code, tokens, random.Random(11))

    antwort = client.post(f"/api/tisch/{code}/undo",
                          headers={"X-Skat-Token": "erfunden"})
    assert antwort.status_code == 403


def test_lokale_runde_kann_tisch_nichts_wegnehmen(client, testdb):
    """Der ursprüngliche Fehler, jetzt über die Tischgrenze hinweg."""
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})
    _partie_ueber_api_spielen(client, code, tokens, random.Random(12))

    # Danach trägt jemand anders lokal ein Spiel ein und nimmt es zurück.
    spiel_speichern(client, "lokal:woanders", augen=99)
    assert undo(client, "lokal:woanders").status_code == 200

    uebrig = spiele_in_db(testdb)
    assert len(uebrig) == 1
    assert uebrig[0]["sitzung_id"] == f"tisch:{code}", "Das Remote-Spiel muss bleiben"


def test_tisch_kann_sich_nicht_rueckwaerts_durchloeschen(client, testdb):
    """Zwei Spiele am Tisch, zweimal zurücknehmen: das zweite muss scheitern.

    Sonst liefe genau der Fehler wieder auf, den die Sperre verhindern soll -
    nur eben tischweise.
    """
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})

    _partie_ueber_api_spielen(client, code, tokens, random.Random(21))
    client.post(f"/api/tisch/{code}/naechstes", headers={"X-Skat-Token": erster})
    _partie_ueber_api_spielen(client, code, tokens, random.Random(22))
    assert len(spiele_in_db(testdb)) == 2

    assert client.post(f"/api/tisch/{code}/undo",
                       headers={"X-Skat-Token": erster}).status_code == 200

    # Jetzt steht noch ein Spiel am Tisch - trotzdem ist Schluss.
    sicht = zustand(client, code, erster)
    assert len(sicht["ergebnisse"]) == 1
    zweites = client.post(f"/api/tisch/{code}/undo", headers={"X-Skat-Token": erster})
    assert zweites.status_code == 409
    assert len(spiele_in_db(testdb)) == 1, "Das erste Spiel bleibt erhalten"

    # Nach dem nächsten gespielten Spiel geht es wieder.
    client.post(f"/api/tisch/{code}/naechstes", headers={"X-Skat-Token": erster})
    _partie_ueber_api_spielen(client, code, tokens, random.Random(23))
    assert client.post(f"/api/tisch/{code}/undo",
                       headers={"X-Skat-Token": erster}).status_code == 200
