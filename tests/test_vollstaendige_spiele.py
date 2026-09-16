"""Vollstaendige Zufallspartien: Invarianten und Abgleich mit der bestehenden App.

Der wichtigste Test hier ist ``test_spielwert_stimmt_mit_app_ueberein``: die
Engine rechnet den Spielwert unabhaengig aus, und dieselben Eingaben werden
durch ``app.berechne_spielwert`` geschickt - die Funktion, die bisher die
manuell eingetippten Spiele bewertet. Weichen beide ab, ist eine von beiden
falsch.
"""

import random
import pytest

import skat_engine as e
from skat_engine import Ansage, Karte, SkatSpiel

import app as skat_app


def _zufaellig_reizen(spiel, rng):
    """Reizt zufaellig, aber regelkonform, bis das Reizen beendet ist."""
    while spiel.phase == e.PHASE_REIZEN:
        pos = spiel.am_zug
        if spiel.reiz_erwartet == "antwort":
            if rng.random() < 0.5:
                spiel.hoeren(pos)
            else:
                spiel.passen(pos)
            continue
        naechster = e.naechster_reizwert(spiel.reiz_gebot)
        # Nicht zu hoch reizen, sonst ist fast jedes Spiel ueberreizt.
        if naechster is None or naechster > 60 or rng.random() < 0.35:
            spiel.passen(pos)
        else:
            spiel.reizen(pos, naechster)


def _zufaellige_ansage(spiel, rng):
    spielart = rng.choice(list(e.SPIELARTEN_MIT_TRUMPF) + ["Null"])
    if spiel.skat_aufgenommen:
        if spielart == "Null":
            return Ansage("Null", ouvert=rng.random() < 0.3)
        return Ansage(spielart)
    if spielart == "Null":
        return Ansage("Null", hand=True, ouvert=rng.random() < 0.3)
    wurf = rng.random()
    if wurf < 0.65:
        return Ansage(spielart, hand=True)
    if wurf < 0.85:
        return Ansage(spielart, hand=True, schneider_angesagt=True)
    if wurf < 0.95:
        return Ansage(spielart, hand=True, schwarz_angesagt=True)
    return Ansage(spielart, hand=True, ouvert=True)


def zufallspartie(seed):
    """Spielt eine komplette Partie mit zufaelligen, aber legalen Zuegen."""
    rng = random.Random(seed)
    spiel = SkatSpiel([10, 20, 30], geber_id=30, rng=rng)
    _zufaellig_reizen(spiel, rng)
    if spiel.eingepasst:
        return spiel

    pos = spiel.alleinspieler_pos
    if rng.random() < 0.7:
        spiel.skat_aufnehmen(pos)
        zu_druecken = rng.sample(spiel.blaetter[pos], 2)
        spiel.druecken(pos, zu_druecken)
    else:
        spiel.hand_spielen(pos)

    spiel.ansagen(pos, _zufaellige_ansage(spiel, rng))

    while spiel.phase == e.PHASE_SPIELEN:
        am_zug = spiel.am_zug
        spiel.karte_spielen(am_zug, rng.choice(spiel.erlaubte_karten_fuer(am_zug)))

    return spiel


ALLE_PARTIEN = [zufallspartie(seed) for seed in range(400)]
GESPIELTE = [s for s in ALLE_PARTIEN if not s.eingepasst]


def test_es_entstehen_ueberhaupt_spiele():
    assert len(GESPIELTE) > 200, "Zu wenige Zufallspartien kommen ueber das Reizen hinaus"
    arten = {s.ansage.spielart for s in GESPIELTE}
    assert arten >= {"Grand", "Null"} and len(arten) >= 5


@pytest.mark.parametrize("spiel", ALLE_PARTIEN, ids=lambda s: s.spielart)
def test_partie_endet_sauber(spiel):
    assert spiel.phase == e.PHASE_BEENDET
    assert spiel.ergebnis is not None
    assert spiel.am_zug is None


@pytest.mark.parametrize("spiel", GESPIELTE, ids=lambda s: s.spielart)
def test_alle_karten_bleiben_erhalten(spiel):
    gespielt = [k for _, karten in spiel.stiche for k in karten]
    rest = [k for blatt in spiel.blaetter for k in blatt]
    skat = spiel.gedrueckt if spiel.skat_aufgenommen else spiel.urskat
    alle = gespielt + rest + skat
    assert len(alle) == 32
    assert len(set(alle)) == 32


@pytest.mark.parametrize("spiel", GESPIELTE, ids=lambda s: s.spielart)
def test_stichzahl_und_augen(spiel):
    if spiel.ansage.spielart == "Null":
        # Null kann vorzeitig enden, sobald der Alleinspieler einen Stich macht.
        assert 1 <= len(spiel.stiche) <= 10
        return

    assert len(spiel.stiche) == 10
    erg = spiel.ergebnis
    gegner_augen = 120 - erg.augen_alleinspieler
    assert 0 <= erg.augen_alleinspieler <= 120
    assert erg.augen_alleinspieler + gegner_augen == 120
    assert 0 <= erg.stiche_alleinspieler <= 10


@pytest.mark.parametrize("spiel", GESPIELTE, ids=lambda s: s.spielart)
def test_jeder_stich_hat_drei_karten_und_einen_gewinner(spiel):
    for gewinner, karten in spiel.stiche:
        assert len(karten) == 3
        assert gewinner in (0, 1, 2)


@pytest.mark.parametrize("spiel", GESPIELTE, ids=lambda s: s.spielart)
def test_spielwert_stimmt_mit_app_ueberein(spiel):
    """Kernabgleich: Engine-Rechnung gegen die bestehende App-Formel."""
    erg = spiel.ergebnis
    aus_app = skat_app.berechne_spielwert(
        erg.spielart,
        erg.reizwert,
        erg.spitzen,
        erg.hand,
        erg.ouvert,
        erg.schneider_angesagt,
        erg.schwarz_angesagt,
        erg.schwarz_erreicht,
        erg.augen,
    )
    assert aus_app == erg.spielwert, (
        f"Engine {erg.spielwert} != App {aus_app} bei {erg}"
    )


@pytest.mark.parametrize("spiel", GESPIELTE, ids=lambda s: s.spielart)
def test_gewinnbedingungen(spiel):
    erg = spiel.ergebnis
    if erg.ueberreizt:
        assert not erg.gewonnen
        return
    if erg.spielart == "Null":
        assert erg.gewonnen == (erg.stiche_alleinspieler == 0)
        return
    erwartet = erg.augen_alleinspieler >= 61
    if erg.schneider_angesagt and erg.augen_alleinspieler < 90:
        erwartet = False
    if erg.schwarz_angesagt and erg.stiche_alleinspieler < 10:
        erwartet = False
    assert erg.gewonnen == erwartet


@pytest.mark.parametrize("spiel", GESPIELTE, ids=lambda s: s.spielart)
def test_schwarz_braucht_alle_zehn_stiche(spiel):
    """Hausregel-frei: Schwarz heisst zehn Stiche, nicht 120 Augen."""
    erg = spiel.ergebnis
    if erg.spielart == "Null":
        return
    if erg.schwarz_erreicht:
        assert erg.stiche_alleinspieler in (0, 10)


@pytest.mark.parametrize("spiel", GESPIELTE, ids=lambda s: s.spielart)
def test_spitzen_unabhaengig_vom_druecken(spiel):
    """Der Skat zaehlt mit, also aendert Druecken die Spitzen nicht."""
    erg = spiel.ergebnis
    if erg.spielart == "Null":
        assert erg.spitzen == 0
        return
    pos = spiel.alleinspieler_pos
    aus_zwoelf = e.berechne_spitzen(
        spiel.urblaetter[pos] + spiel.urskat, erg.spielart
    )
    assert erg.spitzen == aus_zwoelf
    assert 1 <= abs(erg.spitzen) <= (4 if erg.spielart == "Grand" else 11)


def test_bedienzwang_wurde_nie_verletzt():
    """Spielt Partien nach und prueft jede gelegte Karte gegen die Regel."""
    for seed in range(60):
        rng = random.Random(10_000 + seed)
        spiel = SkatSpiel([10, 20, 30], geber_id=30, rng=rng)
        _zufaellig_reizen(spiel, rng)
        if spiel.eingepasst:
            continue
        pos = spiel.alleinspieler_pos
        spiel.hand_spielen(pos)
        spiel.ansagen(pos, Ansage(rng.choice(list(e.SPIELARTEN_MIT_TRUMPF)), hand=True))

        haende = [list(b) for b in spiel.blaetter]
        stich = []
        while spiel.phase == e.PHASE_SPIELEN:
            am_zug = spiel.am_zug
            erlaubt = e.erlaubte_karten(haende[am_zug], stich, spiel.ansage.spielart)
            karte = rng.choice(erlaubt)
            # Wenn bedient werden kann, muss bedient werden.
            if stich:
                gefordert = e.stichfarbe(stich[0][1], spiel.ansage.spielart)
                kann_bedienen = any(
                    e.stichfarbe(k, spiel.ansage.spielart) == gefordert
                    for k in haende[am_zug]
                )
                if kann_bedienen:
                    assert e.stichfarbe(karte, spiel.ansage.spielart) == gefordert

            spiel.karte_spielen(am_zug, karte)
            haende[am_zug].remove(karte)
            stich.append((am_zug, karte))
            if len(stich) == 3:
                stich = []
