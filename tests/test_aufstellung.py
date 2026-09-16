"""Tisch verlassen und Offline-Spielerinnen entfernen."""

import random
import time

import pytest

import skat_engine as e
from skat_engine import RegelFehler
from tisch import Tisch, VERBINDUNG_TIMEOUT, PHASE_LOBBY, PHASE_SPIEL, PHASE_PAUSE
from test_tisch import tisch_mit, NAMEN, _partie_durchspielen


def offline_setzen(tisch, spieler_id):
    """Lässt eine Spielerin so aussehen, als sei sie weggebrochen."""
    for eintrag in tisch.spieler:
        if eintrag["id"] == spieler_id:
            eintrag["gesehen"] = time.time() - VERBINDUNG_TIMEOUT - 5
            return
    raise AssertionError(f"{spieler_id} sitzt nicht am Tisch")


# --- Verbindungsstatus ------------------------------------------------------

def test_offline_wird_erkannt():
    tisch, _ = tisch_mit(3)
    assert all(s["verbunden"] for s in tisch._spieler_liste())
    offline_setzen(tisch, 2)
    status = {s["id"]: s["verbunden"] for s in tisch._spieler_liste()}
    assert status == {1: True, 2: False, 3: True}


def test_statuswechsel_zaehlt_als_aenderung():
    """Sonst sähen die anderen den Abbruch nie - es wird ja nichts geschoben."""
    tisch, _ = tisch_mit(3)
    tisch.verbindungen_pruefen()
    vorher = tisch.version

    assert tisch.verbindungen_pruefen() is False
    assert tisch.version == vorher, "Ohne Wechsel keine neue Version"

    offline_setzen(tisch, 2)
    assert tisch.verbindungen_pruefen() is True
    assert tisch.version > vorher


# --- Tisch verlassen --------------------------------------------------------

def test_zurueck_in_die_lobby_gibt_die_aufstellung_frei():
    tisch, tokens = tisch_mit(4)
    _partie_durchspielen(tisch, tokens, random.Random(1))
    assert tisch.phase == PHASE_PAUSE

    tisch.zurueck_in_die_lobby(tokens[1])
    assert tisch.phase == PHASE_LOBBY
    assert tisch.spiel is None

    # Jetzt lässt sich die Runde umbauen.
    tisch.verlassen(tokens[2])
    assert [s["id"] for s in tisch.spieler] == [1, 3, 4]
    tisch.beitreten(5, "Emma")
    tisch.reihenfolge_setzen([5, 1, 3, 4])
    assert [s["id"] for s in tisch.spieler] == [5, 1, 3, 4]

    tisch.starten(rng=random.Random(2))
    assert tisch.phase == PHASE_SPIEL


def test_ergebnisse_der_runde_bleiben_erhalten():
    tisch, tokens = tisch_mit(3)
    _partie_durchspielen(tisch, tokens, random.Random(3))
    vorher = list(tisch.ergebnisse)
    tisch.zurueck_in_die_lobby(tokens[1])
    assert tisch.ergebnisse == vorher, "Gespielt ist gespielt"


def test_verlassen_nicht_mitten_im_spiel():
    tisch, tokens = tisch_mit(3)
    assert tisch.phase == PHASE_SPIEL
    with pytest.raises(RegelFehler, match="erst nach einem Spiel"):
        tisch.zurueck_in_die_lobby(tokens[1])


def test_verlassen_braucht_einen_platz_am_tisch():
    tisch, _ = tisch_mit(3)
    with pytest.raises(RegelFehler):
        tisch.zurueck_in_die_lobby("erfunden")


# --- Spielerin entfernen ----------------------------------------------------

def test_online_spielerin_kann_nicht_entfernt_werden():
    tisch, tokens = tisch_mit(4)
    with pytest.raises(RegelFehler, match="online"):
        tisch.spieler_entfernen(tokens[1], 2)
    assert len(tisch.spieler) == 4


def test_sich_selbst_entfernen_geht_nicht():
    tisch, tokens = tisch_mit(4)
    offline_setzen(tisch, 1)
    with pytest.raises(RegelFehler, match="Dich selbst"):
        tisch.spieler_entfernen(tokens[1], 1)


def test_entfernen_braucht_einen_platz_am_tisch():
    tisch, _ = tisch_mit(4)
    offline_setzen(tisch, 2)
    with pytest.raises(RegelFehler):
        tisch.spieler_entfernen("erfunden", 2)


def test_bei_vier_spielerinnen_geht_es_zu_dritt_weiter():
    tisch, tokens = tisch_mit(4)
    offline_setzen(tisch, 3)
    ergebnis = tisch.spieler_entfernen(tokens[1], 3)

    assert ergebnis == {"entfernt": NAMEN[3], "weiter": "neues_spiel"}
    assert [s["id"] for s in tisch.spieler] == [1, 2, 4]
    assert tisch.phase == PHASE_SPIEL
    assert tisch.spiel is not None, "Es wurde sofort neu gegeben"
    assert len(tisch.spiel.spieler_ids) == 3


def test_bei_drei_spielerinnen_geht_es_in_die_lobby():
    tisch, tokens = tisch_mit(3)
    offline_setzen(tisch, 3)
    ergebnis = tisch.spieler_entfernen(tokens[1], 3)

    assert ergebnis["weiter"] == "lobby"
    assert tisch.phase == PHASE_LOBBY
    assert tisch.spiel is None
    assert [s["id"] for s in tisch.spieler] == [1, 2]

    # Zu zweit lässt sich nicht starten, aber jemand kann nachrücken.
    with pytest.raises(RegelFehler):
        tisch.starten()
    tisch.beitreten(4, NAMEN[4])
    tisch.starten(rng=random.Random(5))
    assert tisch.phase == PHASE_SPIEL


def test_laufendes_spiel_wird_verworfen_und_nicht_gewertet():
    tisch, tokens = tisch_mit(4)
    offline_setzen(tisch, 3)
    tisch.spieler_entfernen(tokens[1], 3)
    assert tisch.ergebnisse == [], "Das abgebrochene Spiel zählt nicht"


def test_geberin_rueckt_normal_weiter():
    tisch, tokens = tisch_mit(5)
    tisch.geber_index = 0                    # Anna gibt
    offline_setzen(tisch, 4)                 # Dora sitzt nicht auf Platz 1
    tisch.spieler_entfernen(tokens[1], 4)
    # Nach Anna (Platz 0) ist Berta (id 2) dran.
    assert tisch.geber_id == 2


def test_entfernte_geberin_gibt_an_die_naechste_ab():
    tisch, tokens = tisch_mit(5)
    tisch.geber_index = 2                    # Clara (id 3) gibt
    offline_setzen(tisch, 3)
    tisch.spieler_entfernen(tokens[1], 3)
    # Nach Clara käme Dora (id 4) - die gibt jetzt.
    assert tisch.geber_id == 4
    assert [s["id"] for s in tisch.spieler] == [1, 2, 4, 5]


@pytest.mark.parametrize("anzahl", [4, 5])
def test_nach_dem_entfernen_ist_der_tisch_spielbar(anzahl):
    tisch, tokens = tisch_mit(anzahl)
    ziel = list(NAMEN)[anzahl - 1]
    offline_setzen(tisch, ziel)
    tisch.spieler_entfernen(tokens[1], ziel)

    uebrige = {s["id"]: tokens[s["id"]] for s in tisch.spieler}
    _partie_durchspielen(tisch, uebrige, random.Random(7))
    assert tisch.phase == PHASE_PAUSE
    assert len(tisch.ergebnisse) == 1


def test_token_der_entfernten_spielerin_gilt_nicht_mehr():
    tisch, tokens = tisch_mit(4)
    offline_setzen(tisch, 3)
    tisch.spieler_entfernen(tokens[1], 3)
    with pytest.raises(RegelFehler, match="Unbekanntes Token"):
        tisch.sicht_fuer(tokens[3])
