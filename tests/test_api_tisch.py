"""End-to-End-Tests der Remote-Play-Schnittstelle (ohne Browser)."""

import sqlite3

import pytest

import skat_engine as e


def _spieler_ids(client):
    return {s["name"]: s["id"] for s in client.get("/api/spieler").get_json()}


def tisch_aufsetzen(client, namen):
    """Legt einen Tisch an und laesst die genannten Spielerinnen beitreten."""
    code = client.post("/api/tisch").get_json()["code"]
    ids = _spieler_ids(client)
    tokens = {}
    for name in namen:
        antwort = client.post(f"/api/tisch/{code}/beitreten",
                              json={"spieler_id": ids[name]})
        assert antwort.status_code == 201, antwort.get_json()
        tokens[ids[name]] = antwort.get_json()["token"]
    return code, tokens


def zustand(client, code, token, aufdecken=False):
    pfad = f"/api/tisch/{code}/zustand"
    if aufdecken:
        pfad += "?aufdecken=1"
    antwort = client.get(pfad, headers={"X-Skat-Token": token})
    assert antwort.status_code == 200, antwort.get_json()
    return antwort.get_json()


def aktion(client, code, token, name, daten=None):
    antwort = client.post(f"/api/tisch/{code}/aktion",
                          json={"aktion": name, "daten": daten or {}},
                          headers={"X-Skat-Token": token})
    assert antwort.status_code == 200, antwort.get_json()
    return antwort.get_json()


# --- Lobby ------------------------------------------------------------------

def test_tisch_anlegen_und_beitreten(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    assert len(code) == 6
    uebersicht = client.get(f"/api/tisch/{code}").get_json()
    assert [s["name"] for s in uebersicht["sitzend"]] == ["Anna", "Berta", "Clara"]
    assert {s["name"] for s in uebersicht["frei"]} == {"Dora", "Emma"}


def test_unbekannter_code_gibt_404(client):
    assert client.get("/api/tisch/XXXXXX").status_code == 404


def test_code_ist_nicht_case_sensitiv(client):
    code, _ = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    assert client.get(f"/api/tisch/{code.lower()}").status_code == 200


def test_derselbe_platz_nicht_zweimal(client):
    code, _ = tisch_aufsetzen(client, ["Anna", "Berta"])
    ids = _spieler_ids(client)
    antwort = client.post(f"/api/tisch/{code}/beitreten", json={"spieler_id": ids["Anna"]})
    assert antwort.status_code == 400
    assert "bereits an diesem Tisch" in antwort.get_json()["error"]


def test_start_erst_ab_drei(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta"])
    token = next(iter(tokens.values()))
    antwort = client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": token})
    assert antwort.status_code == 400


# --- Zugriffsschutz ---------------------------------------------------------

def test_ohne_token_kein_zustand(client):
    code, _ = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    # Der Testclient sammelt die Beitritts-Cookies ein - fuer diese Pruefung
    # muss der Jar leer sein, sonst weist man sich unbeabsichtigt aus.
    client.delete_cookie(f"skat_token_{code}")
    assert client.get(f"/api/tisch/{code}/zustand").status_code == 403


def test_fremdes_token_wird_abgewiesen(client):
    code, _ = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    antwort = client.get(f"/api/tisch/{code}/zustand",
                         headers={"X-Skat-Token": "erfunden"})
    assert antwort.status_code == 403


def test_jede_sicht_zeigt_nur_die_eigenen_karten(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})

    gesehene_blaetter = []
    for token in tokens.values():
        daten = zustand(client, code, token)
        blatt = daten["spiel"]["ich"]["blatt"]
        assert len(blatt) == 10
        assert "alle_blaetter" not in daten["spiel"]
        gesehene_blaetter.append(set(blatt))

    # Die drei Blaetter sind disjunkt - niemand sieht fremde Karten.
    assert not (gesehene_blaetter[0] & gesehene_blaetter[1])
    assert not (gesehene_blaetter[0] & gesehene_blaetter[2])
    assert not (gesehene_blaetter[1] & gesehene_blaetter[2])


def test_aufdecken_nur_fuer_aussetzende(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara", "Dora"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})

    aussetzende, mitspielende = [], []
    for token in tokens.values():
        daten = zustand(client, code, token)
        (aussetzende if daten["ich"]["setzt_aus"] else mitspielende).append(token)

    assert len(aussetzende) == 1 and len(mitspielende) == 3

    # Mitspielende bekommen trotz Wunsch nichts aufgedeckt.
    for token in mitspielende:
        daten = zustand(client, code, token, aufdecken=True)
        assert daten["aufgedeckt"] is False
        assert "alle_blaetter" not in daten["spiel"]

    # Aussetzende schon - aber nur auf ausdrueckliche Anfrage.
    standard = zustand(client, code, aussetzende[0])
    assert "alle_blaetter" not in standard["spiel"]
    offen = zustand(client, code, aussetzende[0], aufdecken=True)
    assert offen["aufgedeckt"] is True
    assert len(offen["spiel"]["alle_blaetter"]) == 3
    assert len(offen["spiel"]["skat"]) == 2


# --- Kompletter Durchlauf ---------------------------------------------------

def _partie_ueber_api_spielen(client, code, tokens, rng):
    """Spielt ueber die HTTP-Schnittstelle, ohne die Engine direkt anzufassen."""
    while True:
        # Sicht der Spielerin holen, die am Zug ist. Aussetzende haben in
        # ihrer Sicht gar kein Blatt, deshalb ueber die oeffentliche am_zug_id.
        am_zug_token, sicht = None, None
        for token in tokens.values():
            daten = zustand(client, code, token)
            if daten["phase"] != "spiel":
                return daten
            if daten["spiel"]["am_zug_id"] == daten["ich"]["id"]:
                am_zug_token, sicht = token, daten
                break
        assert am_zug_token is not None, "Niemand ist am Zug"

        spiel = sicht["spiel"]
        phase = spiel["phase"]

        if phase == e.PHASE_REIZEN:
            if spiel["reiz_erwartet"] == "antwort":
                aktion(client, code, am_zug_token, "hoeren" if rng.random() < 0.5 else "passen")
            else:
                naechster = e.naechster_reizwert(spiel["reiz_gebot"])
                if naechster is None or naechster > 36 or rng.random() < 0.4:
                    aktion(client, code, am_zug_token, "passen")
                else:
                    aktion(client, code, am_zug_token, "reizen", {"wert": naechster})
        elif phase == e.PHASE_SKAT:
            aktion(client, code, am_zug_token,
                   "skat_aufnehmen" if rng.random() < 0.7 else "hand_spielen")
        elif phase == e.PHASE_DRUECKEN:
            blatt = spiel["ich"]["blatt"]
            assert len(blatt) == 12, "Nach dem Aufnehmen sind es zwoelf Karten"
            aktion(client, code, am_zug_token, "druecken", {"karten": blatt[:2]})
        elif phase == e.PHASE_ANSAGE:
            # Wer den Skat genommen hat, spielt zwingend kein Handspiel.
            hand = not spiel["skat_aufgenommen"]
            aktion(client, code, am_zug_token, "ansagen",
                   {"spielart": rng.choice(list(e.SPIELARTEN_MIT_TRUMPF)), "hand": hand})
        elif phase == e.PHASE_SPIELEN:
            aktion(client, code, am_zug_token, "karte_spielen",
                   {"karte": rng.choice(spiel["ich"]["erlaubte_karten"])})


@pytest.mark.parametrize("anzahl", [3, 4, 5])
def test_komplette_partie_landet_in_der_statistik(client, testdb, anzahl):
    import random
    rng = random.Random(40 + anzahl)
    namen = ["Anna", "Berta", "Clara", "Dora", "Emma"][:anzahl]
    code, tokens = tisch_aufsetzen(client, namen)
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})

    _partie_ueber_api_spielen(client, code, tokens, rng)

    verbindung = sqlite3.connect(testdb)
    verbindung.row_factory = sqlite3.Row
    zeilen = [dict(z) for z in verbindung.execute("SELECT * FROM spiel")]
    verbindung.close()

    assert len(zeilen) == 1
    zeile = zeilen[0]
    assert zeile["quelle"] == "remote"
    assert len(zeile["aktive_spieler_ids"].split(",")) == 3

    # Der Spielwert muss der bestehenden App-Formel entsprechen.
    import app as skat_app
    assert zeile["spielwert"] == skat_app.berechne_spielwert(
        zeile["spielart"], zeile["reizwert"], zeile["spitzen"], zeile["hand"],
        zeile["ouvert"], zeile["schneider_angesagt"], zeile["schwarz_angesagt"],
        zeile["schwarz_erreicht"], zeile["augen"],
    )

    # Und das bestehende Dashboard zeigt sie mit an.
    stand = client.get("/api/stand").get_json()
    assert len(stand["historie"]) == 1
    assert sum(s["gesamtspiele"] for s in stand["punktestand"]) == 3


def test_tisch_ueberlebt_neustart_des_prozesses(client):
    """Nach Verlust des Speichers wird der Tisch aus dem Snapshot geladen."""
    import app as skat_app
    import random

    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})
    vorher = {t: zustand(client, code, t)["spiel"]["ich"]["blatt"] for t in tokens.values()}

    skat_app._tische.clear()             # "Serverneustart"

    for token, blatt in vorher.items():
        assert zustand(client, code, token)["spiel"]["ich"]["blatt"] == blatt

    # Weiterspielen funktioniert.
    ergebnis = _partie_ueber_api_spielen(client, code, tokens, random.Random(3))
    assert ergebnis["phase"] == "pause"


# --- Aufstellung ändern -----------------------------------------------------

def _offline_machen(code, spieler_id):
    """Simuliert einen Verbindungsabbruch über die Prozessdaten."""
    import time
    import app as skat_app
    import tisch as tisch_modul
    tisch = skat_app._tische[code]
    for eintrag in tisch.spieler:
        if eintrag["id"] == spieler_id:
            eintrag["gesehen"] = time.time() - tisch_modul.VERBINDUNG_TIMEOUT - 5
            return
    raise AssertionError("nicht am Tisch")


def test_tisch_verlassen_oeffnet_die_aufstellung(client):
    import random
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})
    _partie_ueber_api_spielen(client, code, tokens, random.Random(31))

    antwort = client.post(f"/api/tisch/{code}/lobby", headers={"X-Skat-Token": erster})
    assert antwort.status_code == 200
    assert antwort.get_json()["phase"] == "lobby"

    # Jetzt darf wieder beigetreten und der Platz geräumt werden.
    uebersicht = client.get(f"/api/tisch/{code}").get_json()
    assert {s["name"] for s in uebersicht["frei"]} == {"Dora", "Emma"}

    ids = _spieler_ids(client)
    assert client.post(f"/api/tisch/{code}/beitreten",
                       json={"spieler_id": ids["Dora"]}).status_code == 201


def test_platz_freigeben_nur_in_der_lobby(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))

    assert client.post(f"/api/tisch/{code}/verlassen",
                       headers={"X-Skat-Token": erster}).status_code == 200
    assert len(client.get(f"/api/tisch/{code}").get_json()["sitzend"]) == 2

    # Während einer laufenden Partie geht es nicht.
    ids = _spieler_ids(client)
    client.post(f"/api/tisch/{code}/beitreten", json={"spieler_id": ids["Anna"]})
    uebrig = next(t for s, t in tokens.items() if s != ids["Anna"])
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": uebrig})
    assert client.post(f"/api/tisch/{code}/verlassen",
                       headers={"X-Skat-Token": uebrig}).status_code == 400


def test_offline_spielerin_entfernen_und_weiterspielen(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara", "Dora"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})

    ids = _spieler_ids(client)
    _offline_machen(code, ids["Dora"])

    # Die Anzeige meldet sie als offline.
    sicht = zustand(client, code, erster)
    tomke = next(s for s in sicht["spieler"] if s["id"] == ids["Dora"])
    assert tomke["verbunden"] is False

    antwort = client.post(f"/api/tisch/{code}/entfernen",
                          json={"spieler_id": ids["Dora"]},
                          headers={"X-Skat-Token": erster})
    assert antwort.status_code == 200, antwort.get_json()
    assert antwort.get_json()["weiter"] == "neues_spiel"

    nachher = zustand(client, code, erster)
    assert nachher["phase"] == "spiel"
    assert len(nachher["spieler"]) == 3
    assert nachher["ergebnisse"] == [], "Das abgebrochene Spiel zählt nicht"


def test_online_spielerin_laesst_sich_nicht_entfernen(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara", "Dora"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})

    ids = _spieler_ids(client)
    antwort = client.post(f"/api/tisch/{code}/entfernen",
                          json={"spieler_id": ids["Dora"]},
                          headers={"X-Skat-Token": erster})
    assert antwort.status_code == 400
    assert "online" in antwort.get_json()["error"]


def test_entfernen_unter_drei_fuehrt_in_die_lobby(client, testdb):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})

    ids = _spieler_ids(client)
    _offline_machen(code, ids["Clara"])
    antwort = client.post(f"/api/tisch/{code}/entfernen",
                          json={"spieler_id": ids["Clara"]},
                          headers={"X-Skat-Token": erster})
    assert antwort.get_json()["weiter"] == "lobby"
    assert zustand(client, code, erster)["phase"] == "lobby"

    verbindung = sqlite3.connect(testdb)
    anzahl = verbindung.execute("SELECT COUNT(*) FROM spiel").fetchone()[0]
    verbindung.close()
    assert anzahl == 0, "Ein abgebrochenes Spiel darf nicht in der Statistik landen"


def test_entfernte_spielerin_kommt_nicht_mehr_an_den_zustand(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara", "Dora"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})

    ids = _spieler_ids(client)
    _offline_machen(code, ids["Dora"])
    client.post(f"/api/tisch/{code}/entfernen", json={"spieler_id": ids["Dora"]},
                headers={"X-Skat-Token": erster})

    antwort = client.get(f"/api/tisch/{code}/zustand",
                         headers={"X-Skat-Token": tokens[ids["Dora"]]})
    assert antwort.status_code == 403


# --- Beitritt als Zuschauerin ----------------------------------------------

def beitreten(client, code, name):
    ids = _spieler_ids(client)
    antwort = client.post(f"/api/tisch/{code}/beitreten", json={"spieler_id": ids[name]})
    assert antwort.status_code == 201, antwort.get_json()
    return antwort.get_json()


def test_beitritt_waehrend_der_partie_ist_zuschauen(client):
    import random
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})

    # Die Lobby-Übersicht sagt vorher schon, worauf man sich einlässt.
    assert client.get(f"/api/tisch/{code}").get_json()["beitritt_als"] == "zuschauer_partie_laeuft"

    daten = beitreten(client, code, "Dora")
    assert daten["rolle"] == "zuschauer"
    assert daten["grund"] == "partie_laeuft"

    sicht = zustand(client, code, daten["token"])
    assert sicht["ich"]["zuschauer"] is True
    assert sicht["ich"]["wartet_auf_platz"] is False, "Platz ist da, nur das Spiel läuft"
    assert "ich" not in sicht["spiel"]

    # Mitspielen geht nicht.
    antwort = client.post(f"/api/tisch/{code}/aktion",
                          json={"aktion": "passen", "daten": {}},
                          headers={"X-Skat-Token": daten["token"]})
    assert antwort.status_code == 400
    assert "schaust gerade zu" in antwort.get_json()["error"]

    # Ab dem nächsten Spiel ist sie dabei.
    _partie_ueber_api_spielen(client, code, tokens, random.Random(41))
    client.post(f"/api/tisch/{code}/naechstes", headers={"X-Skat-Token": erster})

    nachher = zustand(client, code, daten["token"])
    assert nachher["ich"]["zuschauer"] is False
    assert len(nachher["spieler"]) == 4
    assert nachher["zuschauer"] == []


def test_voller_tisch_meldet_das_und_nimmt_nur_zuschauende(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara", "Dora", "Emma"])
    uebersicht = client.get(f"/api/tisch/{code}").get_json()
    assert uebersicht["voll"] is True
    assert uebersicht["beitritt_als"] == "zuschauer_voll"

    import db_setup
    db_setup.spieler_hinzufuegen(["Frieda"])
    daten = beitreten(client, code, "Frieda")
    assert daten["rolle"] == "zuschauer"
    assert daten["grund"] == "voll"

    sicht = zustand(client, code, daten["token"])
    assert sicht["ich"]["wartet_auf_platz"] is True
    assert sicht["platz_frei"] is False


def test_wartende_rueckt_nach_wenn_ein_platz_frei_wird(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara", "Dora", "Emma"])
    import db_setup
    db_setup.spieler_hinzufuegen(["Frieda"])
    jonas = beitreten(client, code, "Frieda")
    assert zustand(client, code, jonas["token"])["ich"]["wartet_auf_platz"] is True

    ids = _spieler_ids(client)
    client.post(f"/api/tisch/{code}/verlassen",
                headers={"X-Skat-Token": tokens[ids["Emma"]]})

    sicht = zustand(client, code, jonas["token"])
    assert sicht["ich"]["zuschauer"] is False, "Frieda sitzt jetzt mit am Tisch"
    assert {s["name"] for s in sicht["spieler"]} == {"Anna", "Berta", "Clara", "Dora", "Frieda"}


def test_sitzende_sehen_die_zuschauenden(client):
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})
    beitreten(client, code, "Dora")

    sicht = zustand(client, code, erster)
    assert [z["name"] for z in sicht["zuschauer"]] == ["Dora"]
