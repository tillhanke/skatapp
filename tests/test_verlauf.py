"""Zweitprotokoll der Remote-Partien in eigener Datenbank.

Wichtigste Eigenschaft: aus dem Protokoll muss sich die Partie exakt
nachstellen lassen - Blätter, Skat, Reizverlauf und jede gespielte Karte.
Und: skat_daten.db bleibt dabei unverändert.
"""

import random
import sqlite3

import pytest

import skat_engine as e
import verlauf
from skat_engine import Karte, SkatSpiel
from test_tisch import tisch_mit, NAMEN, _partie_durchspielen

K = Karte.aus_code


@pytest.fixture
def protokoll(tmp_path):
    return str(tmp_path / "verlauf.db")


def gespielter_tisch(seed=5, anzahl=3):
    tisch, tokens = tisch_mit(anzahl, seed=seed)
    _partie_durchspielen(tisch, tokens, random.Random(seed))
    return tisch


# --- Schema -----------------------------------------------------------------

def test_datenbank_wird_bei_bedarf_angelegt(protokoll, tmp_path):
    verb = verlauf.verbindung(protokoll)
    tabellen = {z[0] for z in verb.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    verb.close()
    assert {"partie", "blatt", "reizen", "stich", "zug"} <= tabellen


def test_hauptdatenbank_wird_nicht_angefasst(client, testdb):
    """Kein neues Feld, keine neue Tabelle in skat_daten.db."""
    verb = sqlite3.connect(testdb)
    vorher_tabellen = {z[0] for z in verb.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    vorher_spalten = {z[1] for z in verb.execute("PRAGMA table_info(spiel)")}
    verb.close()

    from test_api_tisch import tisch_aufsetzen, _partie_ueber_api_spielen
    code, tokens = tisch_aufsetzen(client, ["Anna", "Berta", "Clara"])
    erster = next(iter(tokens.values()))
    client.post(f"/api/tisch/{code}/starten", headers={"X-Skat-Token": erster})
    _partie_ueber_api_spielen(client, code, tokens, random.Random(61))

    verb = sqlite3.connect(testdb)
    nachher_tabellen = {z[0] for z in verb.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    nachher_spalten = {z[1] for z in verb.execute("PRAGMA table_info(spiel)")}
    verb.close()

    assert nachher_tabellen == vorher_tabellen
    assert nachher_spalten == vorher_spalten


# --- Inhalt -----------------------------------------------------------------

def test_protokoll_haelt_blaetter_skat_und_zuege_fest(protokoll):
    tisch = gespielter_tisch()
    spiel = tisch.spiel
    partie_id = verlauf.protokolliere(tisch, spiel_id=4711, pfad=protokoll)

    daten = verlauf.lade_partie(partie_id, pfad=protokoll)
    assert daten["spiel_id"] == 4711
    assert daten["tisch_code"] == tisch.code
    assert daten["sitzung_id"] == f"tisch:{tisch.code}"
    assert daten["geber_id"] == spiel.geber_id
    assert daten["vorhand_id"] == spiel.spieler_ids[0]

    # Die ausgeteilten Blätter, nicht die Reste nach dem Drücken.
    for eintrag in daten["blaetter"]:
        pos = eintrag["position"]
        assert eintrag["spieler_id"] == spiel.spieler_ids[pos]
        assert eintrag["karten"].split(",") == [k.code for k in spiel.urblaetter[pos]]
        assert len(eintrag["karten"].split(",")) == 10

    assert daten["skat"].split(",") == [k.code for k in spiel.urskat]
    if spiel.skat_aufgenommen:
        assert daten["gedrueckt"].split(",") == [k.code for k in spiel.gedrueckt]
    else:
        assert daten["gedrueckt"] == ""


def test_alle_32_karten_sind_im_protokoll_auffindbar(protokoll):
    tisch = gespielter_tisch(seed=8)
    partie_id = verlauf.protokolliere(tisch, spiel_id=1, pfad=protokoll)
    daten = verlauf.lade_partie(partie_id, pfad=protokoll)

    alle = []
    for eintrag in daten["blaetter"]:
        alle += eintrag["karten"].split(",")
    alle += daten["skat"].split(",")
    assert sorted(alle) == sorted(k.code for k in e.vollstaendiges_blatt())


def test_reizverlauf_wird_vollstaendig_festgehalten(protokoll):
    tisch = gespielter_tisch(seed=9)
    spiel = tisch.spiel
    partie_id = verlauf.protokolliere(tisch, spiel_id=2, pfad=protokoll)
    daten = verlauf.lade_partie(partie_id, pfad=protokoll)

    assert len(daten["reizen"]) == len(spiel.reiz_verlauf)
    for eintrag, (pos, aktion, wert) in zip(daten["reizen"], spiel.reiz_verlauf):
        assert eintrag["spieler_id"] == spiel.spieler_ids[pos]
        assert eintrag["aktion"] == aktion
        assert eintrag["wert"] == wert


def test_zuege_stehen_in_der_richtigen_reihenfolge(protokoll):
    tisch = gespielter_tisch(seed=11)
    spiel = tisch.spiel
    partie_id = verlauf.protokolliere(tisch, spiel_id=3, pfad=protokoll)
    daten = verlauf.lade_partie(partie_id, pfad=protokoll)

    assert len(daten["stiche"]) == len(spiel.stiche)
    for eintrag, (gewinner, karten) in zip(daten["stiche"], spiel.stiche):
        assert eintrag["gewinner_id"] == spiel.spieler_ids[gewinner]
        assert [z["karte"] for z in eintrag["zuege"]] == [k.code for k in karten]
        assert [z["reihenfolge"] for z in eintrag["zuege"]] == list(range(len(karten)))


def test_wer_welche_karte_legte_wird_korrekt_abgeleitet(protokoll):
    """Die Engine merkt sich das nicht - es wird aus der Ausspielfolge errechnet."""
    tisch = gespielter_tisch(seed=13)
    spiel = tisch.spiel
    partie_id = verlauf.protokolliere(tisch, spiel_id=5, pfad=protokoll)
    daten = verlauf.lade_partie(partie_id, pfad=protokoll)

    # Gegenprobe: jede Spielerin darf nur Karten gelegt haben, die sie hatte.
    hatte = {
        spiel.spieler_ids[pos]: set(k.code for k in spiel.urblaetter[pos])
        for pos in range(3)
    }
    # Der Alleinspieler bekommt den Skat dazu und drückt zwei Karten weg.
    if spiel.skat_aufgenommen:
        hatte[spiel.alleinspieler_id] |= {k.code for k in spiel.urskat}
        hatte[spiel.alleinspieler_id] -= {k.code for k in spiel.gedrueckt}

    for stich in daten["stiche"]:
        for zug in stich["zuege"]:
            assert zug["karte"] in hatte[zug["spieler_id"]], (
                f"{zug['spieler_id']} hat {zug['karte']} nie besessen"
            )
            hatte[zug["spieler_id"]].discard(zug["karte"])

    # Der erste Stich wird von der Vorhand ausgespielt.
    assert daten["stiche"][0]["zuege"][0]["spieler_id"] == spiel.spieler_ids[0]
    # Jeder weitere vom Gewinner des vorherigen.
    for vorher, danach in zip(daten["stiche"], daten["stiche"][1:]):
        assert danach["zuege"][0]["spieler_id"] == vorher["gewinner_id"]


def test_augen_der_stiche_ergeben_120(protokoll):
    tisch = gespielter_tisch(seed=17)
    while tisch.spiel.ansage is None or tisch.spiel.ansage.spielart == "Null":
        tisch = gespielter_tisch(seed=random.randint(1, 999))
    partie_id = verlauf.protokolliere(tisch, spiel_id=6, pfad=protokoll)
    daten = verlauf.lade_partie(partie_id, pfad=protokoll)

    if len(daten["stiche"]) == 10:
        in_stichen = sum(s["augen"] for s in daten["stiche"])
        # Beiseite liegen am Ende die gedrückten Karten - der aufgenommene
        # Skat selbst ist ins Blatt gewandert und wurde mitgespielt.
        beiseite = daten["gedrueckt"] if daten["skat_aufgenommen"] else daten["skat"]
        assert in_stichen + e.augen_summe([K(c) for c in beiseite.split(",")]) == 120


# --- Nachstellen ------------------------------------------------------------

def test_partie_laesst_sich_aus_dem_protokoll_nachstellen(protokoll):
    """Der eigentliche Zweck: das Spiel exakt wiederholen können."""
    tisch = gespielter_tisch(seed=23)
    original = tisch.spiel
    if original.eingepasst:
        pytest.skip("eingepasst - kein Stichspiel")

    partie_id = verlauf.protokolliere(tisch, spiel_id=7, pfad=protokoll)
    daten = verlauf.lade_partie(partie_id, pfad=protokoll)

    # Deck aus dem Protokoll zusammensetzen und exakt so wieder geben.
    haende = [[K(c) for c in eintrag["karten"].split(",")]
              for eintrag in sorted(daten["blaetter"], key=lambda x: x["position"])]
    skat = [K(c) for c in daten["skat"].split(",")]

    deck = [None] * 32
    for start, karten in (
        (0, haende[0][0:3]), (3, haende[1][0:3]), (6, haende[2][0:3]),
        (9, skat),
        (11, haende[0][3:7]), (15, haende[1][3:7]), (19, haende[2][3:7]),
        (23, haende[0][7:10]), (26, haende[1][7:10]), (29, haende[2][7:10]),
    ):
        for versatz, karte in enumerate(karten):
            deck[start + versatz] = karte

    nachbau = SkatSpiel(original.spieler_ids, geber_id=daten["geber_id"], blatt=deck)
    assert [[k.code for k in b] for b in nachbau.urblaetter] == \
           [[k.code for k in b] for b in original.urblaetter]
    assert [k.code for k in nachbau.urskat] == [k.code for k in original.urskat]

    # Reizen nachspielen
    for eintrag in daten["reizen"]:
        pos = nachbau.spieler_ids.index(eintrag["spieler_id"])
        if eintrag["aktion"] == "reizt":
            nachbau.reizen(pos, eintrag["wert"])
        elif eintrag["aktion"] == "hoert":
            nachbau.hoeren(pos)
        else:
            nachbau.passen(pos)
    assert nachbau.alleinspieler_id == original.alleinspieler_id
    assert nachbau.reizwert == original.reizwert

    # Skat, Drücken, Ansage
    pos = nachbau.alleinspieler_pos
    if daten["skat_aufgenommen"]:
        nachbau.skat_aufnehmen(pos)
        nachbau.druecken(pos, [K(c) for c in daten["gedrueckt"].split(",")])
    else:
        nachbau.hand_spielen(pos)
    nachbau.ansagen(pos, e.Ansage(
        spielart=daten["spielart"], hand=bool(daten["hand"]),
        ouvert=bool(daten["ouvert"]),
        schneider_angesagt=bool(daten["schneider_angesagt"]),
        schwarz_angesagt=bool(daten["schwarz_angesagt"]),
    ))

    # Jede Karte in der protokollierten Reihenfolge
    for stich in daten["stiche"]:
        for zug in stich["zuege"]:
            spieler_pos = nachbau.spieler_ids.index(zug["spieler_id"])
            nachbau.karte_spielen(spieler_pos, K(zug["karte"]))

    assert nachbau.phase == e.PHASE_BEENDET
    assert nachbau.ergebnis.spielwert == original.ergebnis.spielwert
    assert nachbau.ergebnis.augen_alleinspieler == original.ergebnis.augen_alleinspieler
    assert nachbau.ergebnis.stiche_alleinspieler == original.ergebnis.stiche_alleinspieler


# --- Zurücknehmen -----------------------------------------------------------

def test_zurueckgenommene_partie_bleibt_als_beleg_stehen(protokoll):
    tisch = gespielter_tisch(seed=29)
    partie_id = verlauf.protokolliere(tisch, spiel_id=99, pfad=protokoll)

    assert verlauf.als_zurueckgenommen_markieren(99, pfad=protokoll) == 1
    daten = verlauf.lade_partie(partie_id, pfad=protokoll)
    assert daten["zurueckgenommen"] == 1
    assert daten["blaetter"], "Das Protokoll bleibt vollständig erhalten"


def test_eingepasste_partie_wird_auch_protokolliert(protokoll):
    tisch, tokens = tisch_mit(3, seed=3)
    for pos in (1, 2, 0):
        tisch.aktion(tokens[tisch.spiel.spieler_ids[pos]], "passen")
    assert tisch.spiel.eingepasst

    partie_id = verlauf.protokolliere(tisch, spiel_id=12, pfad=protokoll)
    daten = verlauf.lade_partie(partie_id, pfad=protokoll)
    assert daten["spielart"] == "Eingepasst"
    assert daten["stiche"] == []
    assert len(daten["reizen"]) == 3, "Der Reizverlauf ist gerade hier interessant"
    assert len(daten["blaetter"]) == 3, "Die Blätter sind trotzdem festgehalten"
