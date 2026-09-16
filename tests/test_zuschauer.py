"""Beitritt während einer laufenden Partie und bei vollem Tisch.

Niemand wird abgewiesen: wer zu spät kommt oder keinen Platz findet, schaut
zu und rückt nach, sobald es geht.
"""

import random

import pytest

import skat_engine as e
from skat_engine import RegelFehler
from tisch import Tisch, PHASE_LOBBY, PHASE_SPIEL, PHASE_PAUSE
from test_tisch import tisch_mit, NAMEN, _partie_durchspielen
from test_aufstellung import offline_setzen


# --- Beitritt während der Partie -------------------------------------------

def test_wer_zu_spaet_kommt_schaut_zu_und_spielt_ab_dem_naechsten_spiel():
    tisch, tokens = tisch_mit(3)
    token, rolle = tisch.beitreten(4, NAMEN[4])
    assert rolle == "zuschauer"

    # Mitten in die laufende Runde kann niemand einsteigen.
    assert [s["id"] for s in tisch.spieler] == [1, 2, 3]
    assert len(tisch.spiel.spieler_ids) == 3

    _partie_durchspielen(tisch, tokens, random.Random(1))
    tisch.naechstes_spiel(rng=random.Random(2))

    assert tisch.zuschauer == []
    assert [s["id"] for s in tisch.spieler] == [1, 2, 3, 4]
    assert tisch.sicht_fuer(token)["ich"]["zuschauer"] is False


def test_zuschauende_duerfen_nicht_mitspielen():
    tisch, _ = tisch_mit(3)
    token, _ = tisch.beitreten(4, NAMEN[4])
    with pytest.raises(RegelFehler, match="schaust gerade zu"):
        tisch.aktion(token, "passen")


def test_reihenfolge_des_nachrueckens_ist_die_des_beitritts():
    tisch, tokens = tisch_mit(3)
    tisch.beitreten(5, NAMEN[5])
    tisch.beitreten(4, NAMEN[4])
    assert [z["id"] for z in tisch.zuschauer] == [5, 4]

    _partie_durchspielen(tisch, tokens, random.Random(3))
    tisch.naechstes_spiel(rng=random.Random(4))
    # Beide passen noch rein - und zwar in der Reihenfolge des Wartens.
    assert [s["id"] for s in tisch.spieler] == [1, 2, 3, 5, 4]


# --- Voller Tisch -----------------------------------------------------------

def test_bei_fuenf_bleibt_es_beim_zuschauen():
    tisch, tokens = tisch_mit(5)
    token, rolle = tisch.beitreten(6, "Frieda")
    assert rolle == "zuschauer"

    sicht = tisch.sicht_fuer(token)
    assert sicht["ich"]["zuschauer"] is True
    assert sicht["ich"]["wartet_auf_platz"] is True, "Es ist kein Platz frei"
    assert sicht["platz_frei"] is False

    # Auch nach mehreren Spielen rückt niemand nach - der Tisch ist voll.
    for _ in range(2):
        _partie_durchspielen(tisch, tokens, random.Random(5))
        tisch.naechstes_spiel(rng=random.Random(6))
    assert [z["id"] for z in tisch.zuschauer] == [6]
    assert len(tisch.spieler) == 5


def test_erst_wenn_jemand_geht_rueckt_nach():
    tisch, tokens = tisch_mit(5)
    token, _ = tisch.beitreten(6, "Frieda")
    assert tisch.sicht_fuer(token)["ich"]["wartet_auf_platz"] is True

    _partie_durchspielen(tisch, tokens, random.Random(7))
    tisch.zurueck_in_die_lobby(tokens[1])
    tisch.verlassen(tokens[2])            # ein Platz wird frei

    assert [z["id"] for z in tisch.zuschauer] == []
    assert 6 in [s["id"] for s in tisch.spieler]
    assert len(tisch.spieler) == 5


def test_freier_platz_durch_entfernen_geht_an_die_wartende():
    tisch, tokens = tisch_mit(5)
    tisch.beitreten(6, "Frieda")
    offline_setzen(tisch, 4)
    tisch.spieler_entfernen(tokens[1], 4)

    ids = [s["id"] for s in tisch.spieler]
    assert 4 not in ids and 6 in ids
    assert len(ids) == 5
    assert tisch.zuschauer == []
    assert tisch.phase == PHASE_SPIEL, "Es wurde direkt neu gegeben"


def test_unter_drei_spielerinnen_hilft_eine_wartende_aus():
    tisch, tokens = tisch_mit(3)
    tisch.beitreten(4, NAMEN[4])
    offline_setzen(tisch, 3)
    tisch.spieler_entfernen(tokens[1], 3)

    # Ohne Wartende wäre hier Schluss - so geht es zu dritt weiter.
    assert [s["id"] for s in tisch.spieler] == [1, 2, 4]
    assert tisch.phase == PHASE_SPIEL


# --- Sicht der Zuschauenden -------------------------------------------------

def test_zuschauende_sehen_standardmaessig_keine_karten():
    tisch, _ = tisch_mit(3)
    token, _ = tisch.beitreten(4, NAMEN[4])
    sicht = tisch.sicht_fuer(token)

    assert sicht["darf_aufdecken"] is True
    assert sicht["aufgedeckt"] is False
    assert "alle_blaetter" not in sicht["spiel"]
    assert "ich" not in sicht["spiel"], "Zuschauende haben kein eigenes Blatt"


def test_zuschauende_koennen_aufdecken():
    tisch, _ = tisch_mit(3)
    token, _ = tisch.beitreten(4, NAMEN[4])
    sicht = tisch.sicht_fuer(token, aufdecken=True)

    assert sicht["aufgedeckt"] is True
    assert len(sicht["spiel"]["alle_blaetter"]) == 3
    assert len(sicht["spiel"]["skat"]) == 2


def test_sitzende_sehen_wer_zuschaut():
    tisch, tokens = tisch_mit(3)
    tisch.beitreten(4, NAMEN[4])
    sicht = tisch.sicht_fuer(tokens[1])
    assert [z["name"] for z in sicht["zuschauer"]] == [NAMEN[4]]
    assert sicht["zuschauer"][0]["wartet_auf_platz"] is False


# --- Sonstiges --------------------------------------------------------------

def test_zuschauende_koennen_jederzeit_gehen():
    tisch, _ = tisch_mit(3)
    token, _ = tisch.beitreten(4, NAMEN[4])
    tisch.verlassen(token)            # mitten im Spiel - für Zuschauende ok
    assert tisch.zuschauer == []


def test_niemand_sitzt_doppelt():
    tisch, _ = tisch_mit(3)
    tisch.beitreten(4, NAMEN[4])
    with pytest.raises(RegelFehler, match="bereits an diesem Tisch"):
        tisch.beitreten(4, NAMEN[4])


def test_zuschauende_ueberleben_den_neustart():
    import json
    tisch, _ = tisch_mit(3)
    token, _ = tisch.beitreten(4, NAMEN[4])

    kopie = Tisch.aus_dict(json.loads(json.dumps(tisch.als_dict())))
    assert kopie.als_dict() == tisch.als_dict()
    assert kopie.sicht_fuer(token)["ich"]["zuschauer"] is True


def test_alter_schnappschuss_ohne_zuschauer_laedt_weiter():
    """Snapshots aus der Zeit vor dieser Änderung kennen das Feld nicht."""
    import json
    tisch, _ = tisch_mit(3)
    daten = json.loads(json.dumps(tisch.als_dict()))
    del daten["zuschauer"]
    kopie = Tisch.aus_dict(daten)
    assert kopie.zuschauer == []
