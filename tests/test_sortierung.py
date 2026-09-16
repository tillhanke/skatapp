"""Anzeigereihenfolge des Blattes.

Reine Darstellungsfrage: das Blatt soll sich lesen lassen wie auf der Hand,
also nach Farben gebündelt - nicht nach Stichstärke.
"""

import pytest

import skat_engine as e
from skat_engine import Karte

K = Karte.aus_code


def sortiert(codes, spielart=None):
    return [k.code for k in e.sortiere_blatt([K(c) for c in codes], spielart)]


VOLLES_BLATT = [f"{f}{r}" for f in "EBHS" for r in ("A", "10", "K", "O", "U", "9", "8", "7")]


def test_ohne_ansage_erst_alle_unter_dann_die_farben():
    """Genau die Reihenfolge aus der Anforderung."""
    assert sortiert(VOLLES_BLATT) == [
        "EU", "BU", "HU", "SU",
        "EA", "E10", "EK", "EO", "E9", "E8", "E7",
        "BA", "B10", "BK", "BO", "B9", "B8", "B7",
        "HA", "H10", "HK", "HO", "H9", "H8", "H7",
        "SA", "S10", "SK", "SO", "S9", "S8", "S7",
    ]


def test_grand_aendert_nichts():
    assert sortiert(VOLLES_BLATT, "Grand") == sortiert(VOLLES_BLATT)


@pytest.mark.parametrize("trumpf", ["Eichel", "Blatt", "Herz", "Schell"])
def test_farbspiel_zieht_die_trumpffarbe_nach_vorn(trumpf):
    reihenfolge = sortiert(VOLLES_BLATT, trumpf)

    # Erst die vier Unter, unabhängig von der Trumpffarbe.
    assert reihenfolge[:4] == ["EU", "BU", "HU", "SU"]

    # Danach die Trumpffarbe komplett, in Ass-Zehn-König-Ober-9-8-7.
    kuerzel = {"Eichel": "E", "Blatt": "B", "Herz": "H", "Schell": "S"}[trumpf]
    erwartet = [f"{kuerzel}{r}" for r in ("A", "10", "K", "O", "9", "8", "7")]
    assert reihenfolge[4:11] == erwartet

    # Der Trumpf hängt also lückenlos zusammen.
    assert all(k.startswith(kuerzel) or k.endswith("U") for k in reihenfolge[:11])

    # Die übrigen Farben folgen in der üblichen Reihenfolge.
    rest_farben = [k[0] for k in reihenfolge[11:]]
    assert rest_farben == sorted(rest_farben, key="EBHS".index)


def test_null_nutzt_die_nullreihenfolge_und_kennt_keinen_trumpf():
    assert sortiert(VOLLES_BLATT, "Null") == [
        "EA", "EK", "EO", "EU", "E10", "E9", "E8", "E7",
        "BA", "BK", "BO", "BU", "B10", "B9", "B8", "B7",
        "HA", "HK", "HO", "HU", "H10", "H9", "H8", "H7",
        "SA", "SK", "SO", "SU", "S10", "S9", "S8", "S7",
    ]


def test_beispiel_aus_der_anforderung():
    blatt = ["S7", "EU", "H10", "BU", "EA", "SU", "HU", "E7", "BA", "HK", "SO", "E10"]
    assert sortiert(blatt) == [
        "EU", "BU", "HU", "SU", "EA", "E10", "E7", "BA", "H10", "HK", "SO", "S7",
    ]
    assert sortiert(blatt, "Herz") == [
        "EU", "BU", "HU", "SU", "H10", "HK", "EA", "E10", "E7", "BA", "SO", "S7",
    ]


def test_sortierung_verliert_und_erfindet_keine_karten():
    for spielart in (None, "Grand", "Null", "Eichel", "Blatt", "Herz", "Schell"):
        ergebnis = sortiert(VOLLES_BLATT, spielart)
        assert sorted(ergebnis) == sorted(VOLLES_BLATT)


def test_sicht_liefert_das_blatt_bereits_sortiert():
    """Der Browser soll nicht nachsortieren müssen."""
    import random
    spiel = e.SkatSpiel([10, 20, 30], geber_id=30, rng=random.Random(4))
    blatt = spiel.sicht_fuer(10)["ich"]["blatt"]
    assert blatt == [k.code for k in e.sortiere_blatt([K(c) for c in blatt])]

    # Nach der Ansage richtet sie sich nach der Trumpffarbe.
    spiel.passen(1)
    spiel.passen(2)
    spiel.reizen(0, 18)
    spiel.hand_spielen(0)
    spiel.ansagen(0, e.Ansage("Herz", hand=True))

    blatt = spiel.sicht_fuer(10)["ich"]["blatt"]
    unter = [k for k in blatt if k.endswith("U")]
    assert blatt[:len(unter)] == unter, "Unter stehen vorn"
    nach_untern = blatt[len(unter):]
    herz = [k for k in nach_untern if k.startswith("H")]
    assert nach_untern[:len(herz)] == herz, "Trumpffarbe folgt direkt"


def test_ansage_liefert_alle_reihenfolgen_zur_auswahl():
    """Beim Ansagen soll sich das Blatt schon beim Durchprobieren umsortieren."""
    import random
    spiel = e.SkatSpiel([10, 20, 30], geber_id=30, rng=random.Random(6))
    spiel.passen(1)
    spiel.passen(2)
    spiel.reizen(0, 18)
    spiel.hand_spielen(0)

    ich = spiel.sicht_fuer(10)["ich"]
    varianten = ich["blatt_je_spielart"]
    assert set(varianten) == {"Eichel", "Blatt", "Herz", "Schell", "Grand", "Null"}

    for art, codes in varianten.items():
        assert sorted(codes) == sorted(ich["blatt"]), f"{art}: andere Karten"
        erwartet = [k.code for k in e.sortiere_blatt([K(c) for c in codes], art)]
        assert codes == erwartet

    # Mitspielerinnen bekommen die Auswahl nicht - sie sagen ja nichts an.
    assert "blatt_je_spielart" not in spiel.sicht_fuer(20)["ich"]


def test_reihenfolgen_nur_waehrend_der_ansage():
    import random
    spiel = e.SkatSpiel([10, 20, 30], geber_id=30, rng=random.Random(6))
    assert "blatt_je_spielart" not in spiel.sicht_fuer(10)["ich"], "nicht beim Reizen"

    spiel.passen(1)
    spiel.passen(2)
    spiel.reizen(0, 18)
    spiel.hand_spielen(0)
    spiel.ansagen(0, e.Ansage("Grand", hand=True))
    assert "blatt_je_spielart" not in spiel.sicht_fuer(10)["ich"], "nicht im Stichspiel"
