"""Gezielt gestellte Blaetter fuer Faelle, die Zufallspartien kaum erzeugen.

Vor allem: der Alleinspieler gewinnt ALLE zehn Stiche. Zufaelliges Spiel
erreicht das praktisch nie, es ist aber der teuerste Multiplikator-Pfad.
"""

import pytest

import skat_engine as e
from skat_engine import Ansage, Karte, SkatSpiel
import app as skat_app

K = Karte.aus_code


def deck_bauen(hand0, hand1, hand2, skat):
    """Baut ein Deck so, dass das regelkonforme Geben (3-Skat-4-3) genau
    diese Blaetter ergibt."""
    for name, karten, erwartet in (
        ("hand0", hand0, 10), ("hand1", hand1, 10),
        ("hand2", hand2, 10), ("skat", skat, 2),
    ):
        assert len(karten) == erwartet, f"{name} braucht {erwartet} Karten"

    deck = [None] * 32
    abschnitte = [
        (0, hand0[0:3]), (3, hand1[0:3]), (6, hand2[0:3]),
        (9, skat),
        (11, hand0[3:7]), (15, hand1[3:7]), (19, hand2[3:7]),
        (23, hand0[7:10]), (26, hand1[7:10]), (29, hand2[7:10]),
    ]
    for start, karten in abschnitte:
        for versatz, karte in enumerate(karten):
            deck[start + versatz] = karte
    assert len(set(deck)) == 32, "Blatt enthaelt doppelte Karten"
    return deck


def spiel_mit(hand0, hand1, hand2, skat):
    return SkatSpiel([10, 20, 30], geber_id=30,
                     blatt=deck_bauen(hand0, hand1, hand2, skat))


def _app_wert(erg):
    return skat_app.berechne_spielwert(
        erg.spielart, erg.reizwert, erg.spitzen, erg.hand, erg.ouvert,
        erg.schneider_angesagt, erg.schwarz_angesagt, erg.schwarz_erreicht,
        erg.augen,
    )


# Vorhand haelt alle vier Unter und fast alle Herz -> unschlagbares Herzspiel.
UNSCHLAGBAR = [K(c) for c in
               ("EU", "BU", "HU", "SU", "HA", "H10", "HK", "HO", "H9", "H8")]
SKAT_DAZU = [K("H7"), K("EA")]
GEGNER_1 = [K(c) for c in ("E10", "EK", "EO", "E9", "E8", "E7", "BA", "B10", "BK", "BO")]
GEGNER_2 = [K(c) for c in ("B9", "B8", "B7", "SA", "S10", "SK", "SO", "S9", "S8", "S7")]


def _vorhand_wird_alleinspieler(spiel):
    spiel.passen(1)
    spiel.passen(2)
    spiel.reizen(0, 18)          # Vorhand uebernimmt zu 18
    assert spiel.alleinspieler_pos == 0


def _alle_stiche_durchspielen(spiel):
    while spiel.phase == e.PHASE_SPIELEN:
        pos = spiel.am_zug
        erlaubt = spiel.erlaubte_karten_fuer(pos)
        if pos == spiel.alleinspieler_pos:
            # Alleinspieler zieht die staerkste erlaubte Karte.
            karte = max(erlaubt, key=lambda k: e.kartenstaerke(k, spiel.ansage.spielart))
        else:
            karte = erlaubt[0]
        spiel.karte_spielen(pos, karte)


def test_alleinspieler_gewinnt_alle_zehn_stiche():
    spiel = spiel_mit(UNSCHLAGBAR, GEGNER_1, GEGNER_2, SKAT_DAZU)
    _vorhand_wird_alleinspieler(spiel)
    spiel.hand_spielen(0)
    spiel.ansagen(0, Ansage("Herz", hand=True))
    _alle_stiche_durchspielen(spiel)

    erg = spiel.ergebnis
    assert erg.stiche_alleinspieler == 10
    assert erg.augen_alleinspieler == 120
    assert erg.schwarz_erreicht == 1
    assert erg.gewonnen
    # mit 11 (alle vier Unter plus die ganze Herzfarbe inkl. Skat)
    assert erg.spitzen == 11
    # Herz(10) x (11 Spitzen + Spiel + Hand + Schneider + Schwarz) = 10 x 15
    assert erg.spielwert == 150
    assert _app_wert(erg) == erg.spielwert


def test_schwarz_angesagt_und_erreicht():
    spiel = spiel_mit(UNSCHLAGBAR, GEGNER_1, GEGNER_2, SKAT_DAZU)
    _vorhand_wird_alleinspieler(spiel)
    spiel.hand_spielen(0)
    spiel.ansagen(0, Ansage("Herz", hand=True, schwarz_angesagt=True))
    _alle_stiche_durchspielen(spiel)

    erg = spiel.ergebnis
    assert erg.gewonnen and erg.schwarz_erreicht == 1
    assert erg.schneider_angesagt == 1        # Schwarz schliesst Schneider ein
    # 10 x (11 + Spiel + Hand + Schneider + Schneider angesagt + Schwarz + Schwarz angesagt)
    assert erg.spielwert == 170
    assert _app_wert(erg) == erg.spielwert


def test_ouvert_gewonnen():
    spiel = spiel_mit(UNSCHLAGBAR, GEGNER_1, GEGNER_2, SKAT_DAZU)
    _vorhand_wird_alleinspieler(spiel)
    spiel.hand_spielen(0)
    spiel.ansagen(0, Ansage("Herz", hand=True, ouvert=True))
    _alle_stiche_durchspielen(spiel)

    erg = spiel.ergebnis
    assert erg.gewonnen
    # 10 x (11 + Spiel + Hand + Schneider + Schneider ang + Schwarz + Schwarz ang + Ouvert)
    assert erg.spielwert == 180
    assert _app_wert(erg) == erg.spielwert


def test_ouvert_deckt_das_blatt_des_alleinspielers_auf():
    spiel = spiel_mit(UNSCHLAGBAR, GEGNER_1, GEGNER_2, SKAT_DAZU)
    _vorhand_wird_alleinspieler(spiel)
    spiel.hand_spielen(0)
    spiel.ansagen(0, Ansage("Herz", hand=True, ouvert=True))

    sicht_gegner = spiel.sicht_fuer(20)
    assert "offenes_blatt" in sicht_gegner
    assert len(sicht_gegner["offenes_blatt"]["karten"]) == 10


def test_alleinspieler_wird_schwarz_gespielt():
    """Null Stiche fuer den Alleinspieler: Multiplikator zaehlt trotzdem."""
    # Die Gegner halten alle Trumpfkarten, der Alleinspieler nichts davon.
    schwach = [K(c) for c in ("EA", "E10", "EK", "EO", "E9", "E8", "E7", "BA", "B10", "BK")]
    stark_1 = [K(c) for c in ("EU", "BU", "HU", "SU", "HA", "H10", "HK", "HO", "H9", "H8")]
    stark_2 = [K(c) for c in ("H7", "SA", "S10", "SK", "SO", "S9", "S8", "S7", "BO", "B9")]
    skat = [K("B8"), K("B7")]

    spiel = spiel_mit(schwach, stark_1, stark_2, skat)
    _vorhand_wird_alleinspieler(spiel)
    spiel.hand_spielen(0)
    spiel.ansagen(0, Ansage("Herz", hand=True))

    while spiel.phase == e.PHASE_SPIELEN:
        pos = spiel.am_zug
        erlaubt = spiel.erlaubte_karten_fuer(pos)
        if pos == spiel.alleinspieler_pos:
            karte = erlaubt[0]
        else:
            karte = max(erlaubt, key=lambda k: e.kartenstaerke(k, "Herz"))
        spiel.karte_spielen(pos, karte)

    erg = spiel.ergebnis
    assert erg.stiche_alleinspieler == 0
    assert not erg.gewonnen
    assert erg.schwarz_erreicht == 1, "Schwarz gegen den Alleinspieler zaehlt mit"
    # Keine einzige der elf Herz-Trumpfkarten - auch nicht im Skat: ohne 11.
    assert erg.spitzen == -11
    # 10 x (11 + Spiel + Hand + Schneider + Schwarz) = 150, verloren -> -300
    assert erg.spielwert == -300
    assert _app_wert(erg) == erg.spielwert


def test_null_verloren_sobald_ein_stich_faellt():
    spiel = spiel_mit(UNSCHLAGBAR, GEGNER_1, GEGNER_2, SKAT_DAZU)
    _vorhand_wird_alleinspieler(spiel)
    spiel.hand_spielen(0)
    spiel.ansagen(0, Ansage("Null", hand=True))
    _alle_stiche_durchspielen(spiel)

    erg = spiel.ergebnis
    assert not erg.gewonnen
    assert erg.augen == 1, "DB-Konvention beim Null: 1 = verloren"
    assert erg.spielwert == -70        # Null Hand 35, verloren -> x-2
    assert _app_wert(erg) == erg.spielwert
    assert len(spiel.stiche) < 10, "Null endet, sobald der Alleinspieler sticht"


def test_ueberreizt_ist_verloren_auch_ohne_gegenstich():
    """Wer hoeher reizt, als sein Spiel wert ist, verliert - hier ein Null zu 24."""
    spiel = spiel_mit(UNSCHLAGBAR, GEGNER_1, GEGNER_2, SKAT_DAZU)
    # Vorhand haelt bis 24 und bekommt das Spiel.
    for wert in (18, 20, 22, 23, 24):
        spiel.reizen(1, wert)
        spiel.hoeren(0)
    spiel.passen(1)
    spiel.passen(2)
    assert spiel.alleinspieler_pos == 0 and spiel.reizwert == 24

    spiel.skat_aufnehmen(0)
    spiel.druecken(0, [K("EA"), K("H7")])
    spiel.ansagen(0, Ansage("Null"))       # Null zaehlt 23 < Reizwert 24
    _alle_stiche_durchspielen(spiel)

    erg = spiel.ergebnis
    assert erg.ueberreizt
    assert not erg.gewonnen
    assert erg.spielwert == -46            # 23 x -2
    assert _app_wert(erg) == erg.spielwert
