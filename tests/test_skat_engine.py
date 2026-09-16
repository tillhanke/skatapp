"""Tests fuer das Skat-Regelwerk."""

import random
import pytest

import skat_engine as e
from skat_engine import Ansage, Karte, RegelFehler, SkatSpiel

K = Karte.aus_code


# --- Kartenmaterial ---------------------------------------------------------

def test_blatt_ist_vollstaendig():
    blatt = e.vollstaendiges_blatt()
    assert len(blatt) == 32
    assert len(set(blatt)) == 32
    assert e.augen_summe(blatt) == 120


def test_kartencode_hin_und_zurueck():
    for karte in e.vollstaendiges_blatt():
        assert K(karte.code) == karte


# --- Trumpf und Stichfarbe --------------------------------------------------

def test_unter_sind_immer_trumpf_im_farbspiel():
    for farbe in e.FARBEN:
        assert e.ist_trumpf(Karte(farbe, "U"), "Herz")
        assert e.ist_trumpf(Karte(farbe, "U"), "Grand")
        assert not e.ist_trumpf(Karte(farbe, "U"), "Null")


def test_unter_zaehlen_zur_trumpffarbe_beim_bedienen():
    # Schell-Unter ist im Herzspiel Trumpf, nicht Schell.
    assert e.stichfarbe(K("SU"), "Herz") == "Trumpf"
    assert e.stichfarbe(K("SA"), "Herz") == "Schell"
    # Im Grand ist nur der Unter Trumpf.
    assert e.stichfarbe(K("SU"), "Grand") == "Trumpf"
    assert e.stichfarbe(K("HA"), "Grand") == "Herz"
    # Im Null ist der Unter eine ganz normale Karte seiner Farbe.
    assert e.stichfarbe(K("SU"), "Null") == "Schell"


def test_matadorenreihe_laengen():
    assert len(e.matadorenreihe("Herz")) == 11
    assert len(e.matadorenreihe("Grand")) == 4
    assert e.matadorenreihe("Null") == []
    assert e.matadorenreihe("Herz")[0] == K("EU")


# --- Stichgewinn ------------------------------------------------------------

def test_hoechster_trumpf_gewinnt():
    stich = [(0, K("HA")), (1, K("SU")), (2, K("EU"))]
    assert e.stich_gewinner(stich, "Herz") == 2


def test_trumpf_sticht_fehlfarbe():
    stich = [(0, K("EA")), (1, K("E10")), (2, K("H7"))]
    assert e.stich_gewinner(stich, "Herz") == 2


def test_abwurf_gewinnt_nie():
    # Blatt-Ass ist abgeworfen, bedient nicht -> Eichel-Zehn gewinnt.
    stich = [(0, K("EK")), (1, K("BA")), (2, K("E10"))]
    assert e.stich_gewinner(stich, "Herz") == 2


def test_zehn_schlaegt_koenig_nicht_ass():
    stich = [(0, K("EK")), (1, K("E10")), (2, K("E9"))]
    assert e.stich_gewinner(stich, "Grand") == 1
    stich = [(0, K("EA")), (1, K("E10")), (2, K("E9"))]
    assert e.stich_gewinner(stich, "Grand") == 0


def test_null_reihenfolge_unter_zwischen_ober_und_zehn():
    # Im Null gilt A > K > O > U > 10 > 9 > 8 > 7.
    stich = [(0, K("E10")), (1, K("EU")), (2, K("E9"))]
    assert e.stich_gewinner(stich, "Null") == 1
    stich = [(0, K("EO")), (1, K("EU"))]
    assert e.stich_gewinner(stich, "Null") == 0


# --- Bedienzwang ------------------------------------------------------------

def test_bedienzwang_trumpf():
    hand = [K("EU"), K("HA"), K("SA"), K("B7")]
    stich = [(0, K("BU"))]          # Unter ausgespielt = Trumpf gefordert
    erlaubt = e.erlaubte_karten(hand, stich, "Herz")
    assert set(erlaubt) == {K("EU"), K("HA")}


def test_bedienzwang_fehlfarbe():
    hand = [K("EU"), K("EA"), K("E7"), K("SA")]
    stich = [(0, K("EK"))]
    erlaubt = e.erlaubte_karten(hand, stich, "Herz")
    # Eichel-Unter ist Trumpf, nicht Eichel -> bedient nicht.
    assert set(erlaubt) == {K("EA"), K("E7")}


def test_ohne_bedienung_ist_alles_erlaubt():
    hand = [K("EU"), K("SA")]
    stich = [(0, K("BK"))]
    assert set(e.erlaubte_karten(hand, stich, "Herz")) == set(hand)


# --- Spitzen ----------------------------------------------------------------

def test_spitzen_mit_und_ohne():
    assert e.berechne_spitzen([K("EU"), K("BU"), K("SU")], "Herz") == 2   # mit 2
    assert e.berechne_spitzen([K("BU"), K("HU")], "Herz") == -1           # ohne 1
    assert e.berechne_spitzen([K("SU")], "Herz") == -3                    # ohne 3
    assert e.berechne_spitzen([K("EU"), K("BU"), K("HU"), K("SU")], "Grand") == 4


def test_spitzen_laufen_im_farbspiel_in_die_trumpffarbe_weiter():
    karten = [K("EU"), K("BU"), K("HU"), K("SU"), K("HA"), K("H10")]
    assert e.berechne_spitzen(karten, "Herz") == 6
    # Ohne Herz-Zehn bricht die Reihe nach der Herz-Ass ab.
    assert e.berechne_spitzen(karten[:-1], "Herz") == 5


def test_spitzen_beim_null_immer_null():
    assert e.berechne_spitzen([K("EU"), K("BU")], "Null") == 0


# --- Reizleiter -------------------------------------------------------------

def test_reizleiter_beginnt_korrekt():
    assert e.REIZWERTE[:12] == [18, 20, 22, 23, 24, 27, 30, 33, 35, 36, 40, 44]
    for null_wert in (23, 35, 46, 59):
        assert null_wert in e.REIZWERTE
    assert 19 not in e.REIZWERTE and 21 not in e.REIZWERTE


# --- Reizen -----------------------------------------------------------------

def neues_spiel(seed=1):
    return SkatSpiel([10, 20, 30], geber_id=30, rng=random.Random(seed))


def test_geben_verteilt_korrekt():
    spiel = neues_spiel()
    assert [len(b) for b in spiel.blaetter] == [10, 10, 10]
    assert len(spiel.skat) == 2
    alle = [k for b in spiel.blaetter for k in b] + spiel.skat
    assert len(set(alle)) == 32


def test_mittelhand_reizt_vorhand_weg():
    spiel = neues_spiel()
    assert spiel.am_zug == 1                 # Mittelhand sagt an
    spiel.reizen(1, 18)
    assert spiel.am_zug == 0                 # Vorhand antwortet
    spiel.passen(0)
    # Jetzt reizt Hinterhand gegen Mittelhand.
    assert spiel.am_zug == 2
    spiel.passen(2)
    assert spiel.phase == e.PHASE_SKAT
    assert spiel.alleinspieler_pos == 1
    assert spiel.reizwert == 18


def test_vorhand_haelt_und_gewinnt():
    spiel = neues_spiel()
    spiel.reizen(1, 18)
    spiel.hoeren(0)                          # Vorhand haelt 18
    spiel.reizen(1, 20)
    spiel.hoeren(0)                          # Vorhand haelt 20
    spiel.passen(1)                          # Mittelhand gibt auf
    assert spiel.am_zug == 2                 # Hinterhand gegen Vorhand
    spiel.passen(2)
    assert spiel.alleinspieler_pos == 0
    assert spiel.reizwert == 20


def test_alle_passen_vorhand_uebernimmt_zu_18():
    spiel = neues_spiel()
    spiel.passen(1)
    assert spiel.am_zug == 2
    spiel.passen(2)
    # Vorhand darf jetzt zu 18 uebernehmen.
    assert spiel.am_zug == 0
    spiel.reizen(0, 18)
    assert spiel.alleinspieler_pos == 0
    assert spiel.reizwert == 18


def test_alle_passen_auch_vorhand_ist_eingepasst():
    spiel = neues_spiel()
    spiel.passen(1)
    spiel.passen(2)
    spiel.passen(0)
    assert spiel.eingepasst
    assert spiel.phase == e.PHASE_BEENDET
    assert spiel.ergebnis.spielart == "Eingepasst"
    assert spiel.ergebnis.spielwert == 0


def test_hinterhand_reizt_beide_weg():
    spiel = neues_spiel()
    spiel.reizen(1, 18)
    spiel.hoeren(0)
    spiel.passen(1)
    # Stufe 2: Hinterhand gegen Vorhand, Gebot steht auf 18.
    assert spiel.am_zug == 2
    spiel.reizen(2, 20)
    spiel.passen(0)
    assert spiel.alleinspieler_pos == 2
    assert spiel.reizwert == 20


def test_falsche_spielerin_darf_nicht_reizen():
    spiel = neues_spiel()
    with pytest.raises(RegelFehler):
        spiel.reizen(0, 18)
    with pytest.raises(RegelFehler):
        spiel.reizen(2, 18)


def test_gebot_muss_steigen_und_auf_der_leiter_liegen():
    spiel = neues_spiel()
    spiel.reizen(1, 20)
    spiel.hoeren(0)
    with pytest.raises(RegelFehler):
        spiel.reizen(1, 20)
    with pytest.raises(RegelFehler):
        spiel.reizen(1, 21)


# --- Ansage -----------------------------------------------------------------

def test_ouvert_impliziert_schwarz_und_schneider():
    a = Ansage("Grand", hand=True, ouvert=True).validiert()
    assert a.schwarz_angesagt and a.schneider_angesagt


def test_ansagen_nur_aus_der_hand():
    with pytest.raises(RegelFehler):
        Ansage("Herz", hand=False, schneider_angesagt=True).validiert()
    with pytest.raises(RegelFehler):
        Ansage("Herz", hand=False, ouvert=True).validiert()


def test_null_ouvert_auch_ohne_hand():
    a = Ansage("Null", hand=False, ouvert=True).validiert()
    assert a.ouvert and not a.hand


def test_null_kennt_kein_schneider():
    with pytest.raises(RegelFehler):
        Ansage("Null", hand=True, schwarz_angesagt=True).validiert()


def test_nach_skataufnahme_kein_handspiel():
    spiel = neues_spiel()
    spiel.reizen(1, 18); spiel.passen(0); spiel.passen(2)
    spiel.skat_aufnehmen(1)
    spiel.druecken(1, spiel.blaetter[1][:2])
    with pytest.raises(RegelFehler):
        spiel.ansagen(1, Ansage("Herz", hand=True))


def test_druecken_braucht_zwei_eigene_karten():
    spiel = neues_spiel()
    spiel.reizen(1, 18); spiel.passen(0); spiel.passen(2)
    spiel.skat_aufnehmen(1)
    assert len(spiel.blaetter[1]) == 12
    with pytest.raises(RegelFehler):
        spiel.druecken(1, spiel.blaetter[1][:1])
    fremd = [k for k in spiel.blaetter[0]][:2]
    with pytest.raises(RegelFehler):
        spiel.druecken(1, fremd)
    spiel.druecken(1, spiel.blaetter[1][:2])
    assert len(spiel.blaetter[1]) == 10
