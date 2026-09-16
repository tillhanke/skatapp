"""Ein Spiel muss sich jederzeit speichern und exakt wiederherstellen lassen."""

import json
import random

import pytest

import skat_engine as e
from skat_engine import SkatSpiel
from test_vollstaendige_spiele import zufallspartie, _zufaellig_reizen


def _zustaende_gleich(a: SkatSpiel, b: SkatSpiel):
    assert a.als_dict() == b.als_dict()


@pytest.mark.parametrize("seed", range(40))
def test_beendete_partie_ueberlebt_runde_durch_json(seed):
    original = zufallspartie(seed)
    kopie = SkatSpiel.aus_dict(json.loads(json.dumps(original.als_dict())))
    _zustaende_gleich(original, kopie)
    if not original.eingepasst:
        assert kopie.ergebnis.spielwert == original.ergebnis.spielwert


@pytest.mark.parametrize("seed", range(25))
def test_mitten_im_spiel_speichern_und_weiterspielen(seed):
    """Nach dem Wiederherstellen muss identisch weitergespielt werden koennen."""
    rng = random.Random(9000 + seed)
    spiel = SkatSpiel([10, 20, 30], geber_id=30, rng=rng)
    _zufaellig_reizen(spiel, rng)
    if spiel.eingepasst:
        pytest.skip("eingepasst")

    pos = spiel.alleinspieler_pos
    spiel.hand_spielen(pos)
    spiel.ansagen(pos, e.Ansage("Grand", hand=True))

    # Mitten im dritten Stich unterbrechen.
    zuege = []
    while spiel.phase == e.PHASE_SPIELEN and len(zuege) < 8:
        am_zug = spiel.am_zug
        karte = spiel.erlaubte_karten_fuer(am_zug)[0]
        spiel.karte_spielen(am_zug, karte)
        zuege.append((am_zug, karte))

    kopie = SkatSpiel.aus_dict(json.loads(json.dumps(spiel.als_dict())))
    _zustaende_gleich(spiel, kopie)
    assert kopie.am_zug == spiel.am_zug

    # Beide identisch zu Ende spielen.
    for laufend in (spiel, kopie):
        while laufend.phase == e.PHASE_SPIELEN:
            am_zug = laufend.am_zug
            laufend.karte_spielen(am_zug, laufend.erlaubte_karten_fuer(am_zug)[0])

    assert spiel.ergebnis.spielwert == kopie.ergebnis.spielwert
    assert spiel.ergebnis.augen_alleinspieler == kopie.ergebnis.augen_alleinspieler


def test_sicht_zeigt_nur_eigene_karten():
    spiel = zufallspartie(3)
    while spiel.eingepasst:
        spiel = zufallspartie(4)
    sicht = spiel.sicht_fuer(20)
    assert sicht["ich"]["spieler_id"] == 20
    # Die oeffentliche Sicht kennt nur Kartenzahlen, keine fremden Karten.
    assert set(sicht["kartenzahl"]) == {10, 20, 30}
    assert "alle_blaetter" not in sicht


def test_vollsicht_zeigt_alles():
    spiel = zufallspartie(3)
    voll = spiel.vollsicht()
    assert set(voll["alle_blaetter"]) == {10, 20, 30}
    assert len(voll["skat"]) == 2
