"""
Skat-Regelwerk fuer das Remote-Spiel.

Reines Python, ohne Flask, ohne Datenbank, ohne Netzwerk: eine Klasse
``SkatSpiel`` bildet genau EIN Spiel (eine Runde von Geben bis zum 10. Stich)
als Zustandsautomat ab. Der Server ruft nur Aktionsmethoden auf und fragt
Sichten ab; alle Regelpruefungen passieren hier.

Gespielt wird nach offiziellen Regeln ohne Hausregeln:
  * Der Skat zaehlt fuer die Spitzen mit - auch beim Handspiel.
  * Schwarz bedeutet ALLE zehn Stiche, nicht nur 120 Augen.
  * Kontra/Re gibt es nicht.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable

# --- Kartenmaterial ---------------------------------------------------------

FARBEN = ("Eichel", "Blatt", "Herz", "Schell")
RAENGE = ("A", "10", "K", "O", "U", "9", "8", "7")

AUGEN_JE_RANG = {"A": 11, "10": 10, "K": 4, "O": 3, "U": 2, "9": 0, "8": 0, "7": 0}
GRUNDWERTE = {"Eichel": 12, "Blatt": 11, "Herz": 10, "Schell": 9, "Grand": 24}

# Kurzcodes fuer JSON/Transport: Farbinitiale + Rang, z.B. "EU", "H10", "SA".
_FARB_CODE = {"Eichel": "E", "Blatt": "B", "Herz": "H", "Schell": "S"}
_CODE_FARBE = {code: farbe for farbe, code in _FARB_CODE.items()}

# Reihenfolgen (absteigend, staerkste zuerst)
_TRUMPF_FARBREIHE = ("A", "10", "K", "O", "9", "8", "7")
_FEHLFARBREIHE = ("A", "10", "K", "O", "9", "8", "7")
_NULLREIHE = ("A", "K", "O", "U", "10", "9", "8", "7")

SPIELARTEN_MIT_TRUMPF = ("Eichel", "Blatt", "Herz", "Schell", "Grand")


class RegelFehler(ValueError):
    """Ein Spielzug verstoesst gegen die Regeln oder kommt zur falschen Zeit."""


@dataclass(frozen=True, order=True)
class Karte:
    farbe: str
    rang: str

    @property
    def augen(self) -> int:
        return AUGEN_JE_RANG[self.rang]

    @property
    def code(self) -> str:
        return _FARB_CODE[self.farbe] + self.rang

    @staticmethod
    def aus_code(code: str) -> "Karte":
        if not code or code[0] not in _CODE_FARBE or code[1:] not in RAENGE:
            raise RegelFehler(f"Unbekannter Kartencode: {code!r}")
        return Karte(_CODE_FARBE[code[0]], code[1:])

    def __repr__(self) -> str:  # kompakt in Testausgaben
        return self.code


def vollstaendiges_blatt() -> list[Karte]:
    return [Karte(f, r) for f in FARBEN for r in RAENGE]


def augen_summe(karten: Iterable[Karte]) -> int:
    return sum(k.augen for k in karten)


# --- Kartenordnung ----------------------------------------------------------

def ist_trumpf(karte: Karte, spielart: str) -> bool:
    if spielart == "Null":
        return False
    if karte.rang == "U":
        return True
    if spielart == "Grand":
        return False
    return karte.farbe == spielart


def stichfarbe(karte: Karte, spielart: str) -> str:
    """Farbe, der eine Karte beim Bedienen zugerechnet wird.

    Wichtig: Unter gehoeren im Trumpfspiel zum Trumpf, nicht zu ihrer Farbe.
    """
    if ist_trumpf(karte, spielart):
        return "Trumpf"
    return karte.farbe


def matadorenreihe(spielart: str) -> list[Karte]:
    """Trumpfkarten absteigend: Eichel-Unter zuerst."""
    if spielart == "Null":
        return []
    reihe = [Karte(f, "U") for f in FARBEN]
    if spielart != "Grand":
        reihe += [Karte(spielart, r) for r in _TRUMPF_FARBREIHE]
    return reihe


def kartenstaerke(karte: Karte, spielart: str) -> int:
    """Vergleichswert innerhalb der jeweiligen Kategorie (hoeher = staerker)."""
    if spielart == "Null":
        return len(_NULLREIHE) - _NULLREIHE.index(karte.rang)
    if ist_trumpf(karte, spielart):
        reihe = matadorenreihe(spielart)
        return 100 + (len(reihe) - reihe.index(karte))
    return len(_FEHLFARBREIHE) - _FEHLFARBREIHE.index(karte.rang)


def _schlaegt(neu: Karte, bisher: Karte, gefordert: str, spielart: str) -> bool:
    neu_trumpf = ist_trumpf(neu, spielart)
    alt_trumpf = ist_trumpf(bisher, spielart)
    if neu_trumpf != alt_trumpf:
        return neu_trumpf
    if neu_trumpf:
        return kartenstaerke(neu, spielart) > kartenstaerke(bisher, spielart)
    # Beide Fehlfarbe: nur wer bedient, kann ueberhaupt gewinnen.
    if neu.farbe != gefordert:
        return False
    if bisher.farbe != gefordert:
        return True
    return kartenstaerke(neu, spielart) > kartenstaerke(bisher, spielart)


def stich_gewinner(stich: list[tuple[int, Karte]], spielart: str) -> int:
    """stich: [(position, Karte), ...] in Spielreihenfolge. Gibt die Position zurueck."""
    if not stich:
        raise RegelFehler("Leerer Stich hat keinen Gewinner.")
    gefordert = stichfarbe(stich[0][1], spielart)
    bester_pos, beste_karte = stich[0]
    for pos, karte in stich[1:]:
        if _schlaegt(karte, beste_karte, gefordert, spielart):
            bester_pos, beste_karte = pos, karte
    return bester_pos


def erlaubte_karten(hand: Iterable[Karte], stich: list[tuple[int, Karte]], spielart: str) -> list[Karte]:
    hand = list(hand)
    if not stich:
        return hand
    gefordert = stichfarbe(stich[0][1], spielart)
    bedienbar = [k for k in hand if stichfarbe(k, spielart) == gefordert]
    return bedienbar if bedienbar else hand


def sortiere_blatt(karten: Iterable[Karte], spielart: str | None = None) -> list[Karte]:
    """Bringt ein Blatt in die Reihenfolge, in der man es auf der Hand hält.

    Das ist eine reine Anzeigereihenfolge und hat mit der Kartenstärke im Stich
    nichts zu tun: sie sortiert nach Farbe, damit man sein Blatt lesen kann.

    * Ohne Ansage und beim Grand: erst alle Unter (Eichel, Blatt, Herz, Schell),
      danach die Farben der Reihe nach, je Farbe Ass, Zehn, König, Ober, 9, 8, 7.
    * Beim Farbspiel: erst alle Unter, dann die Trumpffarbe, dann die übrigen
      Farben - also der komplette Trumpf zusammenhängend am Anfang.
    * Beim Null gibt es keinen Trumpf; die Unter stehen als normale Karten in
      ihrer Farbe, und es gilt die Nullreihenfolge Ass, König, Ober, Unter,
      Zehn, 9, 8, 7.
    """
    karten = list(karten)

    if spielart == "Null":
        return sorted(
            karten,
            key=lambda k: (FARBEN.index(k.farbe), _NULLREIHE.index(k.rang)),
        )

    # Beim Farbspiel rückt die Trumpffarbe direkt hinter die Unter.
    if spielart in FARBEN:
        farbfolge = [spielart] + [f for f in FARBEN if f != spielart]
    else:
        farbfolge = list(FARBEN)

    def schluessel(karte: Karte):
        if karte.rang == "U":
            # Alle Unter zuerst, untereinander in der Matadorenreihenfolge.
            return (0, FARBEN.index(karte.farbe), 0)
        return (1, farbfolge.index(karte.farbe), _TRUMPF_FARBREIHE.index(karte.rang))

    return sorted(karten, key=schluessel)


def _codes_sortiert(karten: Iterable[Karte], spielart: str | None = None) -> list[str]:
    return [k.code for k in sortiere_blatt(karten, spielart)]


def berechne_spitzen(karten: Iterable[Karte], spielart: str) -> int:
    """Spitzen als Vorzeichenzahl: +N = 'mit N', -N = 'ohne N'.

    Grundlage sind immer die zwoelf Karten (Blatt + Skat), auch beim Handspiel.
    Weil der Skat dazugehoert, ist das Ergebnis vom Druecken unabhaengig.
    """
    if spielart == "Null":
        return 0
    reihe = matadorenreihe(spielart)
    besitz = set(karten)
    mit = reihe[0] in besitz
    anzahl = 0
    for karte in reihe:
        if (karte in besitz) != mit:
            break
        anzahl += 1
    return anzahl if mit else -anzahl


# --- Reizwerte --------------------------------------------------------------

def _moegliche_reizwerte() -> list[int]:
    werte = {23, 35, 46, 59}  # Nullspiele (Null, Hand, Ouvert, Hand Ouvert)
    for grundwert in GRUNDWERTE.values():
        # Multiplikator max. 18: mit 11 + Spiel + Hand + Schneider + Schneider
        # angesagt + Schwarz + Schwarz angesagt + Ouvert
        for multiplikator in range(2, 19):
            werte.add(grundwert * multiplikator)
    return sorted(w for w in werte if w >= 18)


REIZWERTE = _moegliche_reizwerte()
_REIZWERT_SET = set(REIZWERTE)


def naechster_reizwert(aktuell: int) -> int | None:
    for wert in REIZWERTE:
        if wert > aktuell:
            return wert
    return None


# --- Spielwert --------------------------------------------------------------

NULLWERTE = {
    (False, False): 23,   # (hand, ouvert)
    (False, True): 46,
    (True, False): 35,
    (True, True): 59,
}


@dataclass
class Ansage:
    """Was der Alleinspieler ansagt."""

    spielart: str
    hand: bool = False
    ouvert: bool = False
    schneider_angesagt: bool = False
    schwarz_angesagt: bool = False

    def validiert(self) -> "Ansage":
        """Prueft die Ansage und ergaenzt implizierte Ansagen.

        Offizielle Regeln: Schneider/Schwarz/Ouvert nur aus der Hand. Ouvert
        verpflichtet zu allen Stichen, schliesst also Schwarz (und damit
        Schneider) ein. Beim Nullspiel ist Ouvert auch ohne Hand erlaubt,
        Schneider/Schwarz dagegen sinnlos.
        """
        if self.spielart not in SPIELARTEN_MIT_TRUMPF and self.spielart != "Null":
            raise RegelFehler(f"Unbekannte Spielart: {self.spielart!r}")

        if self.spielart == "Null":
            if self.schneider_angesagt or self.schwarz_angesagt:
                raise RegelFehler("Beim Nullspiel gibt es kein Schneider oder Schwarz.")
            return Ansage("Null", self.hand, self.ouvert, False, False)

        if not self.hand and (self.ouvert or self.schneider_angesagt or self.schwarz_angesagt):
            raise RegelFehler(
                "Schneider, Schwarz und Ouvert sind nur beim Handspiel moeglich."
            )

        schwarz = self.schwarz_angesagt or self.ouvert
        schneider = self.schneider_angesagt or schwarz
        return Ansage(self.spielart, self.hand, self.ouvert, schneider, schwarz)


@dataclass
class Ergebnis:
    """Abschluss eines Spiels - direkt in die Tabelle ``spiel`` schreibbar."""

    eingepasst: bool
    spielart: str
    reizwert: int
    spitzen: int
    hand: int
    ouvert: int
    schneider_angesagt: int
    schwarz_angesagt: int
    schwarz_erreicht: int
    augen: int                    # DB-Konvention (beim Null: 0 = gewonnen, 1 = verloren)
    spielwert: int
    gewonnen: bool
    # Zusatzinfos fuer die Anzeige, nicht fuer die DB
    augen_alleinspieler: int = 0
    stiche_alleinspieler: int = 0
    ueberreizt: bool = False


def berechne_spielwert_engine(
    ansage: Ansage,
    spitzen: int,
    reizwert: int,
    augen_alleinspieler: int,
    stiche_alleinspieler: int,
) -> tuple[int, bool, bool]:
    """Unabhaengige Spielwertberechnung nach offiziellen Regeln.

    Rueckgabe: (spielwert, gewonnen, ueberreizt). Der Spielwert ist bereits
    vorzeichenbehaftet (Verlust = -2x).
    """
    if ansage.spielart == "Null":
        basis = NULLWERTE[(bool(ansage.hand), bool(ansage.ouvert))]
        gewonnen = stiche_alleinspieler == 0
        ueberreizt = reizwert > basis
        if ueberreizt:
            gewonnen = False
        return (basis if gewonnen else -2 * basis), gewonnen, ueberreizt

    grundwert = GRUNDWERTE[ansage.spielart]

    schneider_erreicht = augen_alleinspieler >= 90
    schneider_kassiert = augen_alleinspieler <= 30
    schwarz_erreicht = stiche_alleinspieler == 10
    schwarz_kassiert = stiche_alleinspieler == 0

    stufen = abs(spitzen) + 1                      # Spitzen + "Spiel"
    if ansage.hand:
        stufen += 1
    if schneider_erreicht or schneider_kassiert:
        stufen += 1
    if ansage.schneider_angesagt:
        stufen += 1
    if schwarz_erreicht or schwarz_kassiert:
        stufen += 1
    if ansage.schwarz_angesagt:
        stufen += 1
    if ansage.ouvert:
        stufen += 1

    gewonnen = augen_alleinspieler >= 61
    if ansage.schneider_angesagt and not schneider_erreicht:
        gewonnen = False
    if ansage.schwarz_angesagt and not schwarz_erreicht:
        gewonnen = False

    wert = grundwert * stufen

    ueberreizt = wert < reizwert
    if ueberreizt:
        gewonnen = False
        # Verloren wird zum naechsten Vielfachen des Grundwerts, das den
        # Reizwert erreicht.
        while grundwert * stufen < reizwert:
            stufen += 1
        wert = grundwert * stufen

    return (wert if gewonnen else -2 * wert), gewonnen, ueberreizt


# --- Zustandsautomat fuer ein Spiel -----------------------------------------

PHASE_REIZEN = "reizen"
PHASE_SKAT = "skat_entscheidung"
PHASE_DRUECKEN = "druecken"
PHASE_ANSAGE = "ansage"
PHASE_SPIELEN = "spielen"
PHASE_BEENDET = "beendet"


class SkatSpiel:
    """Ein einzelnes Spiel: Geben, Reizen, Druecken, Ansagen, zehn Stiche.

    Positionen sind 0 = Vorhand, 1 = Mittelhand, 2 = Hinterhand. Wer am
    Vierer-/Fuenfertisch aussetzt und wer gibt, entscheidet die Tischebene -
    hier kommen nur die drei aktiven Spielerinnen an, bereits in Spielreihenfolge.
    """

    def __init__(self, spieler_ids, geber_id=None, rng=None, blatt=None):
        """``blatt`` erlaubt ein vorgegebenes Kartendeck in Gebereihenfolge -
        gedacht fuer Tests und das Nachstellen gemeldeter Spiele."""
        if len(spieler_ids) != 3 or len(set(spieler_ids)) != 3:
            raise RegelFehler("Ein Skatspiel braucht genau drei verschiedene Spielerinnen.")

        self.spieler_ids = list(spieler_ids)
        self.geber_id = geber_id if geber_id is not None else self.spieler_ids[2]

        if blatt is None:
            blatt = vollstaendiges_blatt()
            (rng or random.Random()).shuffle(blatt)
        else:
            blatt = list(blatt)
            if len(blatt) != 32 or len(set(blatt)) != 32:
                raise RegelFehler("Ein vorgegebenes Blatt braucht 32 verschiedene Karten.")

        # Geben nach Regel: 3 - Skat(2) - 4 - 3
        self.blaetter: list[list[Karte]] = [[], [], []]
        zeiger = 0
        for pos in range(3):
            self.blaetter[pos] += blatt[zeiger:zeiger + 3]
            zeiger += 3
        self.skat: list[Karte] = blatt[zeiger:zeiger + 2]
        zeiger += 2
        for anzahl in (4, 3):
            for pos in range(3):
                self.blaetter[pos] += blatt[zeiger:zeiger + anzahl]
                zeiger += anzahl

        # Urblatt festhalten: Blatt + Skat sind die Grundlage fuer die Spitzen.
        self.urblaetter = [list(karten) for karten in self.blaetter]
        self.urskat = list(self.skat)

        # Reizen
        self.phase = PHASE_REIZEN
        self.reiz_gebot = 0
        self.reiz_stufe = 1          # 1: MH gegen VH, 2: HH gegen Sieger, 3: VH allein
        self.reiz_sager: int | None = 1
        self.reiz_hoerer: int | None = 0
        self.reiz_erwartet = "gebot"  # "gebot" oder "antwort"
        self.reiz_verlauf: list[tuple[int, str, int]] = []

        # Ergebnis des Reizens
        self.alleinspieler_pos: int | None = None
        self.reizwert = 0
        self.ansage: Ansage | None = None
        self.skat_aufgenommen = False
        self.gedrueckt: list[Karte] = []

        # Stichspiel
        self.aktueller_stich: list[tuple[int, Karte]] = []
        self.stiche: list[tuple[int, list[Karte]]] = []
        self.ausspiel_pos = 0

        self.eingepasst = False
        self.ergebnis: Ergebnis | None = None

    # -- Hilfen ------------------------------------------------------------

    def position_von(self, spieler_id) -> int:
        try:
            return self.spieler_ids.index(spieler_id)
        except ValueError:
            raise RegelFehler(f"Spielerin {spieler_id!r} sitzt nicht an diesem Tisch.")

    @property
    def alleinspieler_id(self):
        if self.alleinspieler_pos is None:
            return None
        return self.spieler_ids[self.alleinspieler_pos]

    @property
    def spielart(self) -> str:
        if self.eingepasst:
            return "Eingepasst"
        return self.ansage.spielart if self.ansage else ""

    @property
    def am_zug(self) -> int | None:
        """Position, die als naechstes handeln muss (None wenn beendet)."""
        if self.phase == PHASE_REIZEN:
            return self.reiz_sager if self.reiz_erwartet == "gebot" else self.reiz_hoerer
        if self.phase in (PHASE_SKAT, PHASE_DRUECKEN, PHASE_ANSAGE):
            return self.alleinspieler_pos
        if self.phase == PHASE_SPIELEN:
            if not self.aktueller_stich:
                return self.ausspiel_pos
            return (self.aktueller_stich[-1][0] + 1) % 3
        return None

    def _pruefe_am_zug(self, pos: int) -> None:
        if pos != self.am_zug:
            raise RegelFehler("Nicht am Zug.")

    def _pruefe_phase(self, *erlaubt: str) -> None:
        if self.phase not in erlaubt:
            raise RegelFehler(f"Aktion in Phase {self.phase!r} nicht moeglich.")

    # -- Reizen ------------------------------------------------------------

    def reizen(self, pos: int, wert: int) -> None:
        """Der Sager nennt einen Reizwert (oder Vorhand uebernimmt mit 18)."""
        self._pruefe_phase(PHASE_REIZEN)
        if self.reiz_erwartet != "gebot":
            raise RegelFehler("Es wird eine Antwort erwartet, kein neues Gebot.")
        self._pruefe_am_zug(pos)
        if wert not in _REIZWERT_SET:
            raise RegelFehler(f"{wert} ist kein gueltiger Reizwert.")
        if wert <= self.reiz_gebot:
            raise RegelFehler(f"Gebot muss ueber {self.reiz_gebot} liegen.")

        self.reiz_gebot = wert
        self.reiz_verlauf.append((pos, "reizt", wert))

        if self.reiz_hoerer is None:
            # Stufe 3: Vorhand uebernimmt ohne Gegengebot.
            self._reizen_fertig(pos)
            return

        self.reiz_erwartet = "antwort"

    def hoeren(self, pos: int) -> None:
        """Der Hoerer haelt das Gebot ("ja")."""
        self._pruefe_phase(PHASE_REIZEN)
        if self.reiz_erwartet != "antwort":
            raise RegelFehler("Gerade ist kein Gebot zu beantworten.")
        self._pruefe_am_zug(pos)
        self.reiz_verlauf.append((pos, "hoert", self.reiz_gebot))
        self.reiz_erwartet = "gebot"

    def passen(self, pos: int) -> None:
        """Sager gibt auf, oder Hoerer nimmt das Gebot nicht an."""
        self._pruefe_phase(PHASE_REIZEN)
        self._pruefe_am_zug(pos)
        self.reiz_verlauf.append((pos, "passt", self.reiz_gebot))

        if self.reiz_erwartet == "antwort":
            # Hoerer steigt aus -> der Sager hat die Stufe gewonnen.
            sieger = self.reiz_sager
        else:
            # Sager steigt aus -> der Hoerer hat die Stufe gewonnen.
            sieger = self.reiz_hoerer

        if sieger is None:
            # Stufe 3: Vorhand will nicht -> eingepasst.
            self._eingepasst()
            return

        self._stufe_beenden(sieger)

    def _stufe_beenden(self, sieger_pos: int) -> None:
        if self.reiz_stufe == 1:
            self.reiz_stufe = 2
            self.reiz_sager = 2           # Hinterhand reizt den Sieger
            self.reiz_hoerer = sieger_pos
            self.reiz_erwartet = "gebot"
            return

        if self.reiz_stufe == 2 and self.reiz_gebot == 0:
            # Niemand hat je gereizt: Vorhand darf das Spiel zu 18 nehmen.
            self.reiz_stufe = 3
            self.reiz_sager = 0
            self.reiz_hoerer = None
            self.reiz_erwartet = "gebot"
            return

        self._reizen_fertig(sieger_pos)

    def _reizen_fertig(self, sieger_pos: int) -> None:
        self.alleinspieler_pos = sieger_pos
        self.reizwert = self.reiz_gebot or 18
        self.phase = PHASE_SKAT

    def _eingepasst(self) -> None:
        self.eingepasst = True
        self.phase = PHASE_BEENDET
        self.ergebnis = Ergebnis(
            eingepasst=True, spielart="Eingepasst", reizwert=0, spitzen=0,
            hand=0, ouvert=0, schneider_angesagt=0, schwarz_angesagt=0,
            schwarz_erreicht=0, augen=0, spielwert=0, gewonnen=False,
        )

    # -- Skat, Druecken, Ansage -------------------------------------------

    def skat_aufnehmen(self, pos: int) -> list[Karte]:
        self._pruefe_phase(PHASE_SKAT)
        self._pruefe_am_zug(pos)
        self.blaetter[pos] += self.skat
        self.skat_aufgenommen = True
        self.phase = PHASE_DRUECKEN
        return list(self.urskat)

    def hand_spielen(self, pos: int) -> None:
        self._pruefe_phase(PHASE_SKAT)
        self._pruefe_am_zug(pos)
        self.skat_aufgenommen = False
        self.phase = PHASE_ANSAGE

    def druecken(self, pos: int, karten: Iterable[Karte]) -> None:
        self._pruefe_phase(PHASE_DRUECKEN)
        self._pruefe_am_zug(pos)
        karten = list(karten)
        if len(karten) != 2 or len(set(karten)) != 2:
            raise RegelFehler("Es muessen genau zwei verschiedene Karten gedrueckt werden.")
        hand = self.blaetter[pos]
        for karte in karten:
            if karte not in hand:
                raise RegelFehler(f"{karte} liegt nicht auf der Hand.")
        for karte in karten:
            hand.remove(karte)
        self.gedrueckt = karten
        self.phase = PHASE_ANSAGE

    def ansagen(self, pos: int, ansage: Ansage) -> None:
        self._pruefe_phase(PHASE_ANSAGE)
        self._pruefe_am_zug(pos)
        ansage = ansage.validiert()
        if self.skat_aufgenommen and ansage.hand:
            raise RegelFehler("Nach dem Aufnehmen des Skats ist kein Handspiel mehr moeglich.")
        if not self.skat_aufgenommen and not ansage.hand:
            raise RegelFehler("Ohne Skataufnahme ist es zwingend ein Handspiel.")
        self.ansage = ansage
        self.phase = PHASE_SPIELEN
        self.ausspiel_pos = 0            # Vorhand spielt den ersten Stich aus

    # -- Stichspiel --------------------------------------------------------

    def erlaubte_karten_fuer(self, pos: int) -> list[Karte]:
        if self.phase != PHASE_SPIELEN or pos != self.am_zug:
            return []
        return erlaubte_karten(self.blaetter[pos], self.aktueller_stich, self.ansage.spielart)

    def karte_spielen(self, pos: int, karte: Karte) -> None:
        self._pruefe_phase(PHASE_SPIELEN)
        self._pruefe_am_zug(pos)
        if karte not in self.blaetter[pos]:
            raise RegelFehler(f"{karte} liegt nicht auf der Hand.")
        if karte not in erlaubte_karten(self.blaetter[pos], self.aktueller_stich, self.ansage.spielart):
            raise RegelFehler(f"{karte} bedient nicht.")

        self.blaetter[pos].remove(karte)
        self.aktueller_stich.append((pos, karte))

        if len(self.aktueller_stich) < 3:
            return

        gewinner = stich_gewinner(self.aktueller_stich, self.ansage.spielart)
        self.stiche.append((gewinner, [k for _, k in self.aktueller_stich]))
        self.aktueller_stich = []
        self.ausspiel_pos = gewinner

        if self._vorzeitig_entschieden() or len(self.stiche) == 10:
            self._abschliessen()

    def _vorzeitig_entschieden(self) -> bool:
        """Beim Nullspiel ist nach dem ersten Stich des Alleinspielers Schluss."""
        if self.ansage.spielart != "Null":
            return False
        return any(gewinner == self.alleinspieler_pos for gewinner, _ in self.stiche)

    # -- Abschluss ---------------------------------------------------------

    def _abschliessen(self) -> None:
        pos = self.alleinspieler_pos
        ansage = self.ansage

        gewonnene_stiche = [karten for gewinner, karten in self.stiche if gewinner == pos]
        stiche_alleinspieler = len(gewonnene_stiche)

        # Der Skat gehoert immer dem Alleinspieler - gedrueckt oder nicht.
        skat_karten = self.gedrueckt if self.skat_aufgenommen else self.urskat
        augen_alleinspieler = augen_summe(
            [k for karten in gewonnene_stiche for k in karten]
        ) + augen_summe(skat_karten)

        spitzen = berechne_spitzen(self.urblaetter[pos] + self.urskat, ansage.spielart)

        spielwert, gewonnen, ueberreizt = berechne_spielwert_engine(
            ansage, spitzen, self.reizwert, augen_alleinspieler, stiche_alleinspieler
        )

        # "schwarz_erreicht" wird symmetrisch gefuehrt - genau wie die
        # bestehende App Schneider aus "augen >= 90 oder <= 30" ableitet.
        # Wird der Alleinspieler selbst schwarz gespielt, zaehlt der Multiplikator
        # ebenfalls. Die Gewinnbedingung bleibt korrekt, weil null Stiche
        # zwangslaeufig null Augen bedeuten.
        schwarz_flag = 1 if stiche_alleinspieler in (0, 10) else 0

        if ansage.spielart == "Null":
            augen_db = 0 if gewonnen else 1
            schwarz_flag = 0
        else:
            augen_db = augen_alleinspieler

        self.ergebnis = Ergebnis(
            eingepasst=False,
            spielart=ansage.spielart,
            reizwert=self.reizwert,
            spitzen=spitzen,
            hand=1 if ansage.hand else 0,
            ouvert=1 if ansage.ouvert else 0,
            schneider_angesagt=1 if ansage.schneider_angesagt else 0,
            schwarz_angesagt=1 if ansage.schwarz_angesagt else 0,
            schwarz_erreicht=schwarz_flag,
            augen=augen_db,
            spielwert=spielwert,
            gewonnen=gewonnen,
            augen_alleinspieler=augen_alleinspieler,
            stiche_alleinspieler=stiche_alleinspieler,
            ueberreizt=ueberreizt,
        )
        self.phase = PHASE_BEENDET

    # -- Sichten -----------------------------------------------------------

    def oeffentlicher_zustand(self) -> dict:
        """Alles, was jede Spielerin sehen darf."""
        return {
            "phase": self.phase,
            "spieler_ids": list(self.spieler_ids),
            "geber_id": self.geber_id,
            "am_zug_id": None if self.am_zug is None else self.spieler_ids[self.am_zug],
            "reiz_gebot": self.reiz_gebot,
            "reiz_erwartet": self.reiz_erwartet if self.phase == PHASE_REIZEN else None,
            "reiz_verlauf": [
                {"spieler_id": self.spieler_ids[p], "aktion": a, "wert": w}
                for p, a, w in self.reiz_verlauf
            ],
            "alleinspieler_id": self.alleinspieler_id,
            "reizwert": self.reizwert,
            # Oeffentlich: am echten Tisch sieht jede, ob der Skat genommen wurde.
            "skat_aufgenommen": self.skat_aufgenommen,
            "spielart": self.spielart or None,
            "ansage": None if self.ansage is None else {
                "spielart": self.ansage.spielart,
                "hand": self.ansage.hand,
                "ouvert": self.ansage.ouvert,
                "schneider_angesagt": self.ansage.schneider_angesagt,
                "schwarz_angesagt": self.ansage.schwarz_angesagt,
            },
            "aktueller_stich": [
                {"spieler_id": self.spieler_ids[p], "karte": k.code}
                for p, k in self.aktueller_stich
            ],
            "stiche_anzahl": len(self.stiche),
            "letzter_stich": (
                [k.code for k in self.stiche[-1][1]] if self.stiche else []
            ),
            "kartenzahl": {
                self.spieler_ids[p]: len(self.blaetter[p]) for p in range(3)
            },
            "beendet": self.phase == PHASE_BEENDET,
        }

    def sicht_fuer(self, spieler_id) -> dict:
        """Zustand aus Sicht EINER Spielerin - nur deren eigene Karten."""
        pos = self.position_von(spieler_id)
        zustand = self.oeffentlicher_zustand()
        zustand["ich"] = {
            "spieler_id": spieler_id,
            "position": pos,
            "blatt": _codes_sortiert(self.blaetter[pos], self.spielart or None),
            "bin_am_zug": pos == self.am_zug,
            "erlaubte_karten": [k.code for k in self.erlaubte_karten_fuer(pos)],
            "bin_alleinspieler": pos == self.alleinspieler_pos,
        }

        # Während der Ansage soll sich das Blatt schon beim Durchprobieren
        # umsortieren. Der Server liefert dazu alle Reihenfolgen mit, damit
        # der Browser die Regeln weiterhin nicht kennen muss.
        if self.phase == PHASE_ANSAGE and pos == self.alleinspieler_pos:
            zustand["ich"]["blatt_je_spielart"] = {
                art: _codes_sortiert(self.blaetter[pos], art)
                for art in list(SPIELARTEN_MIT_TRUMPF) + ["Null"]
            }

        # Ouvert: das Blatt des Alleinspielers liegt offen.
        if self.ansage and self.ansage.ouvert and self.alleinspieler_pos is not None:
            zustand["offenes_blatt"] = {
                "spieler_id": self.alleinspieler_id,
                "karten": _codes_sortiert(
                    self.blaetter[self.alleinspieler_pos], self.spielart or None
                ),
            }

        # Nur der Alleinspieler sieht den aufgenommenen Skat.
        if self.skat_aufgenommen and pos == self.alleinspieler_pos and self.phase == PHASE_DRUECKEN:
            zustand["skat"] = _codes_sortiert(self.urskat, self.spielart or None)

        if self.phase == PHASE_BEENDET and self.ergebnis is not None:
            zustand["ergebnis"] = self.ergebnis.__dict__ | {
                "skat": [k.code for k in self.urskat],
                "gedrueckt": [k.code for k in self.gedrueckt],
            }
        return zustand

    # -- Serialisierung ----------------------------------------------------
    # Damit ein laufendes Spiel einen Serverneustart uebersteht und Spielerinnen
    # jederzeit wieder einsteigen koennen.

    def als_dict(self) -> dict:
        return {
            "spieler_ids": list(self.spieler_ids),
            "geber_id": self.geber_id,
            "blaetter": [[k.code for k in b] for b in self.blaetter],
            "skat": [k.code for k in self.skat],
            "urblaetter": [[k.code for k in b] for b in self.urblaetter],
            "urskat": [k.code for k in self.urskat],
            "phase": self.phase,
            "reiz_gebot": self.reiz_gebot,
            "reiz_stufe": self.reiz_stufe,
            "reiz_sager": self.reiz_sager,
            "reiz_hoerer": self.reiz_hoerer,
            "reiz_erwartet": self.reiz_erwartet,
            "reiz_verlauf": [list(e) for e in self.reiz_verlauf],
            "alleinspieler_pos": self.alleinspieler_pos,
            "reizwert": self.reizwert,
            "ansage": None if self.ansage is None else self.ansage.__dict__,
            "skat_aufgenommen": self.skat_aufgenommen,
            "gedrueckt": [k.code for k in self.gedrueckt],
            "aktueller_stich": [[p, k.code] for p, k in self.aktueller_stich],
            "stiche": [[gew, [k.code for k in karten]] for gew, karten in self.stiche],
            "ausspiel_pos": self.ausspiel_pos,
            "eingepasst": self.eingepasst,
            "ergebnis": None if self.ergebnis is None else dict(self.ergebnis.__dict__),
        }

    @classmethod
    def aus_dict(cls, daten: dict) -> "SkatSpiel":
        spiel = cls.__new__(cls)
        spiel.spieler_ids = list(daten["spieler_ids"])
        spiel.geber_id = daten["geber_id"]
        spiel.blaetter = [[Karte.aus_code(c) for c in b] for b in daten["blaetter"]]
        spiel.skat = [Karte.aus_code(c) for c in daten["skat"]]
        spiel.urblaetter = [[Karte.aus_code(c) for c in b] for b in daten["urblaetter"]]
        spiel.urskat = [Karte.aus_code(c) for c in daten["urskat"]]
        spiel.phase = daten["phase"]
        spiel.reiz_gebot = daten["reiz_gebot"]
        spiel.reiz_stufe = daten["reiz_stufe"]
        spiel.reiz_sager = daten["reiz_sager"]
        spiel.reiz_hoerer = daten["reiz_hoerer"]
        spiel.reiz_erwartet = daten["reiz_erwartet"]
        spiel.reiz_verlauf = [tuple(e) for e in daten["reiz_verlauf"]]
        spiel.alleinspieler_pos = daten["alleinspieler_pos"]
        spiel.reizwert = daten["reizwert"]
        spiel.ansage = None if daten["ansage"] is None else Ansage(**daten["ansage"])
        spiel.skat_aufgenommen = daten["skat_aufgenommen"]
        spiel.gedrueckt = [Karte.aus_code(c) for c in daten["gedrueckt"]]
        spiel.aktueller_stich = [(p, Karte.aus_code(c)) for p, c in daten["aktueller_stich"]]
        spiel.stiche = [
            (gew, [Karte.aus_code(c) for c in karten]) for gew, karten in daten["stiche"]
        ]
        spiel.ausspiel_pos = daten["ausspiel_pos"]
        spiel.eingepasst = daten["eingepasst"]
        spiel.ergebnis = None if daten["ergebnis"] is None else Ergebnis(**daten["ergebnis"])
        return spiel

    def vollsicht(self) -> dict:
        """Alle Blaetter offen - fuer den Zuschauermodus der Aussetzenden."""
        zustand = self.oeffentlicher_zustand()
        art = self.spielart or None
        zustand["alle_blaetter"] = {
            self.spieler_ids[p]: _codes_sortiert(self.blaetter[p], art) for p in range(3)
        }
        zustand["skat"] = _codes_sortiert(self.urskat, art)
        zustand["gedrueckt"] = _codes_sortiert(self.gedrueckt, art)
        zustand["alle_stiche"] = [
            {"gewinner_id": self.spieler_ids[gew], "karten": [k.code for k in karten]}
            for gew, karten in self.stiche
        ]
        return zustand
