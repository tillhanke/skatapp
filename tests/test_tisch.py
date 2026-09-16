"""Tests fuer die Tischebene: Sitzordnung, Identitaet, verdeckte Karten."""

import json
import random

import pytest

import skat_engine as e
from skat_engine import RegelFehler
from tisch import Tisch, PHASE_LOBBY, PHASE_SPIEL, PHASE_PAUSE

NAMEN = {1: "Anna", 2: "Berta", 3: "Clara", 4: "Dora", 5: "Emma"}


def tisch_mit(anzahl, starten=True, seed=7):
    tisch = Tisch(code="TEST42")
    tokens = {}
    for spieler_id in list(NAMEN)[:anzahl]:
        tokens[spieler_id], _ = tisch.beitreten(spieler_id, NAMEN[spieler_id])
    if starten:
        tisch.starten(rng=random.Random(seed))
    return tisch, tokens


# --- Sitzordnung und Aussetzen ---------------------------------------------

def test_dreiertisch_alle_spielen_mit():
    tisch, _ = tisch_mit(3)
    spielend, aussetzend = tisch.aktive_positionen()
    assert aussetzend == []
    assert len(spielend) == 3


def test_vierertisch_geberin_setzt_aus():
    tisch, _ = tisch_mit(4)
    tisch.geber_index = 2
    spielend, aussetzend = tisch.aktive_positionen()
    assert aussetzend == [2]
    assert spielend == [3, 0, 1]        # Vorhand links vom Geber


def test_fuenfertisch_geberin_und_vorderfrau_setzen_aus():
    tisch, _ = tisch_mit(5)
    tisch.geber_index = 0
    spielend, aussetzend = tisch.aktive_positionen()
    # Geberin (0) und die Spielerin davor (4) setzen aus.
    assert aussetzend == [0, 4]
    assert spielend == [1, 2, 3]


def test_vorhand_sitzt_links_vom_geber():
    for anzahl in (3, 4, 5):
        tisch, _ = tisch_mit(anzahl)
        for geber in range(anzahl):
            tisch.geber_index = geber
            spielend, _ = tisch.aktive_positionen()
            assert spielend[0] == (geber + 1) % anzahl


def test_geber_rueckt_nach_jedem_spiel_weiter():
    tisch, tokens = tisch_mit(4)
    assert tisch.geber_index == 0
    tisch.phase = PHASE_PAUSE
    tisch.naechstes_spiel(rng=random.Random(1))
    assert tisch.geber_index == 1
    # Jede Spielerin kommt beim Durchrotieren einmal dran.
    gesehen = {tisch.geber_id}
    for _ in range(3):
        tisch.phase = PHASE_PAUSE
        tisch.naechstes_spiel(rng=random.Random(1))
        gesehen.add(tisch.geber_id)
    assert gesehen == set(list(NAMEN)[:4])


# --- Beitritt und Identitaet ------------------------------------------------

def test_tokens_sind_verschieden():
    _, tokens = tisch_mit(4, starten=False)
    assert len(set(tokens.values())) == 4


def test_platz_kann_nicht_doppelt_belegt_werden():
    tisch, _ = tisch_mit(3, starten=False)
    with pytest.raises(RegelFehler, match="bereits an diesem Tisch"):
        tisch.beitreten(1, "Anna")


def test_beitritt_waehrend_der_partie_fuehrt_zum_zuschauen():
    tisch, _ = tisch_mit(3)
    token, rolle = tisch.beitreten(4, "Dora")
    assert rolle == "zuschauer"
    assert [z["id"] for z in tisch.zuschauer] == [4]
    assert [s["id"] for s in tisch.spieler] == [1, 2, 3]
    # Die Sicht funktioniert trotzdem.
    assert tisch.sicht_fuer(token)["ich"]["zuschauer"] is True


def test_voller_tisch_nimmt_nur_noch_zuschauende():
    tisch, _ = tisch_mit(5, starten=False)
    _, rolle = tisch.beitreten(6, "Frieda")
    assert rolle == "zuschauer"
    assert len(tisch.spieler) == 5


def test_start_braucht_mindestens_drei():
    tisch = Tisch()
    tisch.beitreten(1, "Anna")
    tisch.beitreten(2, "Berta")
    with pytest.raises(RegelFehler):
        tisch.starten()


def test_unbekanntes_token_bekommt_keine_sicht():
    tisch, _ = tisch_mit(3)
    with pytest.raises(RegelFehler, match="Unbekanntes Token"):
        tisch.sicht_fuer("ausgedacht")


def test_sitzordnung_nur_in_der_lobby():
    tisch, _ = tisch_mit(3, starten=False)
    tisch.reihenfolge_setzen([3, 1, 2])
    assert [s["id"] for s in tisch.spieler] == [3, 1, 2]
    tisch.starten(rng=random.Random(1))
    with pytest.raises(RegelFehler):
        tisch.reihenfolge_setzen([1, 2, 3])


# --- Verdeckte Information --------------------------------------------------

def test_niemand_sieht_fremde_handkarten():
    tisch, tokens = tisch_mit(3)
    for spieler_id, token in tokens.items():
        sicht = tisch.sicht_fuer(token)
        assert sicht["ich"]["id"] == spieler_id
        assert len(sicht["spiel"]["ich"]["blatt"]) == 10
        assert "alle_blaetter" not in sicht["spiel"]
        assert "skat" not in sicht["spiel"]


def test_mitspielerin_darf_nicht_aufdecken():
    """Der Aufdeck-Schalter gilt nur fuer Aussetzende."""
    tisch, tokens = tisch_mit(3)
    sicht = tisch.sicht_fuer(tokens[1], aufdecken=True)
    assert sicht["darf_aufdecken"] is False
    assert sicht["aufgedeckt"] is False
    assert "alle_blaetter" not in sicht["spiel"]


def test_aussetzende_sehen_standardmaessig_nur_den_oeffentlichen_tisch():
    tisch, tokens = tisch_mit(4)          # Geberin (Anna, Platz 0) setzt aus
    sicht = tisch.sicht_fuer(tokens[1])
    assert sicht["ich"]["setzt_aus"] is True
    assert sicht["darf_aufdecken"] is True
    assert sicht["aufgedeckt"] is False
    assert "alle_blaetter" not in sicht["spiel"]


def test_aussetzende_koennen_jederzeit_aufdecken():
    tisch, tokens = tisch_mit(4)
    sicht = tisch.sicht_fuer(tokens[1], aufdecken=True)
    assert sicht["aufgedeckt"] is True
    blaetter = sicht["spiel"]["alle_blaetter"]
    assert len(blaetter) == 3
    assert all(len(karten) == 10 for karten in blaetter.values())
    assert len(sicht["spiel"]["skat"]) == 2


def test_aussetzende_duerfen_nicht_mitspielen():
    tisch, tokens = tisch_mit(4)          # Anna setzt aus
    with pytest.raises(RegelFehler, match="sitzt nicht an diesem Tisch"):
        tisch.aktion(tokens[1], "passen")


# --- Ablauf -----------------------------------------------------------------

def _partie_durchspielen(tisch, tokens, rng):
    """Spielt das laufende Spiel mit zufaelligen, legalen Zuegen zu Ende."""
    def token_fuer(pos):
        return tokens[tisch.spiel.spieler_ids[pos]]

    while tisch.phase == PHASE_SPIEL:
        spiel = tisch.spiel
        pos = spiel.am_zug
        token = token_fuer(pos)

        if spiel.phase == e.PHASE_REIZEN:
            if spiel.reiz_erwartet == "antwort":
                tisch.aktion(token, "hoeren" if rng.random() < 0.5 else "passen")
            else:
                naechster = e.naechster_reizwert(spiel.reiz_gebot)
                if naechster is None or naechster > 40 or rng.random() < 0.4:
                    tisch.aktion(token, "passen")
                else:
                    tisch.aktion(token, "reizen", {"wert": naechster})
        elif spiel.phase == e.PHASE_SKAT:
            tisch.aktion(token, "skat_aufnehmen" if rng.random() < 0.7 else "hand_spielen")
        elif spiel.phase == e.PHASE_DRUECKEN:
            karten = [k.code for k in rng.sample(spiel.blaetter[pos], 2)]
            tisch.aktion(token, "druecken", {"karten": karten})
        elif spiel.phase == e.PHASE_ANSAGE:
            art = rng.choice(list(e.SPIELARTEN_MIT_TRUMPF))
            tisch.aktion(token, "ansagen", {"spielart": art, "hand": not spiel.skat_aufgenommen})
        elif spiel.phase == e.PHASE_SPIELEN:
            karte = rng.choice(spiel.erlaubte_karten_fuer(pos)).code
            tisch.aktion(token, "karte_spielen", {"karte": karte})


@pytest.mark.parametrize("anzahl", [3, 4, 5])
def test_komplette_partie_am_tisch(anzahl):
    rng = random.Random(100 + anzahl)
    tisch, tokens = tisch_mit(anzahl, seed=anzahl)
    _partie_durchspielen(tisch, tokens, rng)

    assert tisch.phase == PHASE_PAUSE
    assert len(tisch.ergebnisse) == 1
    zeile = tisch.ergebnisse[0]["zeile"]

    assert zeile["quelle"] == "remote"
    assert len(zeile["aktive_spieler_ids"].split(",")) == 3
    assert zeile["geber_id"] == tisch.geber_id
    if zeile["spielart"] != "Eingepasst":
        assert zeile["einzelspieler_id"] in [
            int(i) for i in zeile["aktive_spieler_ids"].split(",")
        ]


def test_mehrere_spiele_hintereinander():
    rng = random.Random(5)
    tisch, tokens = tisch_mit(4)
    for runde in range(4):
        _partie_durchspielen(tisch, tokens, rng)
        assert len(tisch.ergebnisse) == runde + 1
        tisch.naechstes_spiel(rng=rng)
    # Jede Spielerin war einmal Geberin.
    geber = {erg["zeile"]["geber_id"] for erg in tisch.ergebnisse}
    assert len(geber) == 4


def test_version_steigt_bei_jeder_aenderung():
    tisch, tokens = tisch_mit(3)
    vorher = tisch.version
    tisch.aktion(tokens[tisch.spiel.spieler_ids[tisch.spiel.am_zug]], "passen")
    assert tisch.version > vorher


# --- Persistenz -------------------------------------------------------------

def test_tisch_ueberlebt_serverneustart():
    rng = random.Random(11)
    tisch, tokens = tisch_mit(4)
    # Ein paar Zuege machen, dann "Neustart" simulieren.
    for _ in range(3):
        spiel = tisch.spiel
        pos = spiel.am_zug
        token = tokens[spiel.spieler_ids[pos]]
        if spiel.reiz_erwartet == "antwort":
            tisch.aktion(token, "hoeren")
        else:
            tisch.aktion(token, "reizen", {"wert": e.naechster_reizwert(spiel.reiz_gebot)})

    wiederhergestellt = Tisch.aus_dict(json.loads(json.dumps(tisch.als_dict())))

    assert wiederhergestellt.als_dict() == tisch.als_dict()
    # Die alten Tokens funktionieren weiter - Wiedereinstieg per Link.
    for spieler_id, token in tokens.items():
        sicht = wiederhergestellt.sicht_fuer(token)
        assert sicht["ich"]["id"] == spieler_id
    # Und es kann normal weitergespielt werden.
    _partie_durchspielen(wiederhergestellt, tokens, rng)
    assert wiederhergestellt.phase == PHASE_PAUSE
