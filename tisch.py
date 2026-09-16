"""Tischverwaltung fuer das Remote-Play.

Ein ``Tisch`` ist eine Runde von drei bis fuenf Spielerinnen, die sich ueber
einen Raumcode zusammenfindet. Er kennt die Sitzordnung, wer gibt, wer
aussetzt, und haelt das gerade laufende ``SkatSpiel``.

Die Regeln des Kartenspiels stehen in ``skat_engine``; hier geht es nur um
den Tisch drumherum. Datenbankzugriff macht ``app.py`` - dieses Modul
liefert nur JSON-faehige Zustaende.
"""

from __future__ import annotations

import random
import secrets
import time

import skat_engine as e
from skat_engine import Ansage, Karte, RegelFehler, SkatSpiel

# Ohne 0/O und 1/I - Codes werden vorgelesen und abgetippt.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LAENGE = 6

PHASE_LOBBY = "lobby"
PHASE_SPIEL = "spiel"
PHASE_PAUSE = "pause"      # Spiel beendet, wartet auf das naechste Geben

# Nach so vielen Sekunden ohne Lebenszeichen gilt eine Spielerin als offline.
# Niemand fliegt deswegen raus - es ist nur die Grundlage fuer die Anzeige und
# dafuer, ob der Tisch jemanden entfernen darf.
VERBINDUNG_TIMEOUT = 30


def neuer_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LAENGE))


def neuer_token() -> str:
    return secrets.token_urlsafe(24)


class Tisch:
    def __init__(self, code: str | None = None):
        self.code = code or neuer_code()
        self.spieler: list[dict] = []      # {id, name, token, gesehen}
        # Wer waehrend einer laufenden Partie dazukommt oder keinen Platz mehr
        # findet, wartet hier - in der Reihenfolge des Beitritts.
        self.zuschauer: list[dict] = []
        self.geber_index = 0
        self.phase = PHASE_LOBBY
        self.spiel: SkatSpiel | None = None
        self.ergebnisse: list[dict] = []   # abgeschlossene Spiele dieser Runde
        self.version = 0
        self.erstellt = time.time()

    # -- Spielerverwaltung -------------------------------------------------

    @property
    def sitzung_id(self) -> str:
        """Kennung dieser Runde für die Tabelle ``spiel``.

        Damit trifft "letztes Spiel zurücknehmen" nur diesen Tisch und nicht
        die Partie, die gerade woanders läuft.
        """
        return f"tisch:{self.code}"

    MAX_SPIELER = 5

    def _spieler_nach_id(self, spieler_id):
        for eintrag in self.spieler:
            if eintrag["id"] == spieler_id:
                return eintrag
        return None

    def _am_tisch_nach_id(self, spieler_id):
        """Sitzende und Zuschauende zusammen."""
        for eintrag in self.spieler + self.zuschauer:
            if eintrag["id"] == spieler_id:
                return eintrag
        return None

    def spieler_nach_token(self, token):
        """Nur Sitzende - wer hier auftaucht, darf auch spielen."""
        for eintrag in self.spieler:
            if secrets.compare_digest(eintrag["token"], token or ""):
                return eintrag
        return None

    def teilnehmer_nach_token(self, token):
        """Sitzende und Zuschauende. Gibt (Eintrag, ist_zuschauer) zurueck."""
        for eintrag in self.spieler:
            if secrets.compare_digest(eintrag["token"], token or ""):
                return eintrag, False
        for eintrag in self.zuschauer:
            if secrets.compare_digest(eintrag["token"], token or ""):
                return eintrag, True
        return None, False

    def ist_zuschauer(self, token) -> bool:
        _, zuschauend = self.teilnehmer_nach_token(token)
        return zuschauend

    def platz_frei(self) -> bool:
        return len(self.spieler) < self.MAX_SPIELER

    def beitreten(self, spieler_id: int, name: str) -> tuple[str, str]:
        """Dem Tisch beitreten. Gibt (Token, Rolle) zurueck.

        Rolle ist "spieler" oder "zuschauer". Niemand wird abgewiesen:

        * In der Lobby und mit freiem Platz sitzt man direkt mit am Tisch.
        * Laeuft gerade eine Partie, schaut man zu und rueckt zum naechsten
          Spiel nach - mitten in eine laufende Runde kann niemand einsteigen,
          die Karten sind schon verteilt.
        * Sitzen bereits fuenf, bleibt es beim Zuschauen, bis ein Platz frei
          wird. Mehr als fuenf kann ein Skattisch nicht sinnvoll aufnehmen.

        Das Token ist der einzige Nachweis, wer man ist - ohne es bekommt
        niemand fremde Handkarten zu sehen.
        """
        if self._am_tisch_nach_id(spieler_id) is not None:
            raise RegelFehler(
                f"{name} ist bereits an diesem Tisch. "
                "Zum Wiedereinsteigen den urspruenglichen Link im selben Browser oeffnen."
            )

        eintrag = {
            "id": spieler_id, "name": name,
            "token": neuer_token(), "gesehen": time.time(),
        }

        if self.phase == PHASE_LOBBY and self.platz_frei():
            self.spieler.append(eintrag)
            rolle = "spieler"
        else:
            self.zuschauer.append(eintrag)
            rolle = "zuschauer"

        self._geaendert()
        return eintrag["token"], rolle

    def _zuschauer_nachruecken(self) -> list[str]:
        """Laesst Wartende aufruecken, solange Plaetze frei sind.

        In Beitrittsreihenfolge, damit wer laenger wartet auch zuerst
        drankommt. Wird vor jedem Geben und beim Zurueckgehen in die Lobby
        aufgerufen.
        """
        nachgerueckt = []
        while self.zuschauer and self.platz_frei():
            eintrag = self.zuschauer.pop(0)
            self.spieler.append(eintrag)
            nachgerueckt.append(eintrag["name"])
        return nachgerueckt

    def verlassen(self, token: str) -> None:
        """Platz freigeben. Zuschauende koennen jederzeit gehen."""
        eintrag, zuschauend = self.teilnehmer_nach_token(token)
        if eintrag is None:
            return

        if zuschauend:
            self.zuschauer.remove(eintrag)
            self._geaendert()
            return

        if self.phase != PHASE_LOBBY:
            raise RegelFehler("Waehrend einer laufenden Partie kann der Tisch nicht verlassen werden.")
        self.spieler.remove(eintrag)
        # Ein freier Platz gehoert der naechsten Wartenden.
        self._zuschauer_nachruecken()
        self._geaendert()

    def gesehen(self, token: str) -> None:
        """Lebenszeichen vermerken - auch von Zuschauenden."""
        eintrag, _ = self.teilnehmer_nach_token(token)
        if eintrag is not None:
            eintrag["gesehen"] = time.time()

    def ist_verbunden(self, eintrag: dict) -> bool:
        return (time.time() - eintrag["gesehen"]) < VERBINDUNG_TIMEOUT

    def verbindungen_pruefen(self) -> bool:
        """Prueft, ob jemand online oder offline gegangen ist.

        Muss regelmaessig aufgerufen werden - sonst faellt ein stiller
        Verbindungsabbruch niemandem auf, weil ohne Zustandsaenderung auch
        keine Sicht neu berechnet wird. Gibt True zurueck, wenn sich etwas
        geaendert hat; dann wurde die Version hochgezaehlt und alle bekommen
        die neue Anzeige geschoben.
        """
        geaendert = False
        for eintrag in self.spieler + self.zuschauer:
            verbunden = self.ist_verbunden(eintrag)
            if eintrag.get("war_verbunden") != verbunden:
                eintrag["war_verbunden"] = verbunden
                geaendert = True
        if geaendert:
            self._geaendert()
        return geaendert

    def reihenfolge_setzen(self, reihenfolge_ids: list[int]) -> None:
        """Sitzordnung festlegen (nur in der Lobby)."""
        if self.phase != PHASE_LOBBY:
            raise RegelFehler("Die Sitzordnung steht nach dem Start fest.")
        if sorted(reihenfolge_ids) != sorted(s["id"] for s in self.spieler):
            raise RegelFehler("Die Reihenfolge muss genau die sitzenden Spielerinnen enthalten.")
        self.spieler.sort(key=lambda s: reihenfolge_ids.index(s["id"]))
        self._geaendert()

    # -- Sitzordnung, Geber, Aussetzende ----------------------------------

    def aktive_positionen(self) -> tuple[list[int], list[int]]:
        """(spielende Sitzplaetze ab Vorhand, aussetzende Sitzplaetze).

        Gleiche Regel wie bisher im Frontend: am Vierertisch setzt die Geberin
        aus, am Fuenfertisch zusaetzlich die Spielerin vor ihr.
        """
        anzahl = len(self.spieler)
        geber = self.geber_index
        if anzahl == 3:
            aussetzend = set()
        elif anzahl == 4:
            aussetzend = {geber}
        elif anzahl == 5:
            aussetzend = {geber, (geber - 1) % anzahl}
        else:
            raise RegelFehler("Ein Tisch braucht drei bis fuenf Spielerinnen.")

        # Vorhand sitzt links von der Geberin.
        rundlauf = [(geber + 1 + i) % anzahl for i in range(anzahl)]
        spielend = [pos for pos in rundlauf if pos not in aussetzend]
        return spielend, sorted(aussetzend)

    @property
    def geber_id(self):
        return self.spieler[self.geber_index]["id"] if self.spieler else None

    def setzt_aus(self, spieler_id) -> bool:
        if self.spiel is None:
            return False
        _, aussetzend = self.aktive_positionen()
        return any(self.spieler[pos]["id"] == spieler_id for pos in aussetzend)

    # -- Partieverlauf -----------------------------------------------------

    def starten(self, rng=None) -> None:
        if self.phase != PHASE_LOBBY:
            raise RegelFehler("Die Partie laeuft bereits.")
        self._zuschauer_nachruecken()
        if not 3 <= len(self.spieler) <= self.MAX_SPIELER:
            raise RegelFehler("Zum Starten werden drei bis fuenf Spielerinnen gebraucht.")
        self.phase = PHASE_SPIEL
        self._geben(rng)

    def naechstes_spiel(self, rng=None) -> None:
        if self.phase != PHASE_PAUSE:
            raise RegelFehler("Es laeuft noch ein Spiel.")
        # Wer waehrend des letzten Spiels dazugekommen ist, spielt ab jetzt mit.
        self._zuschauer_nachruecken()
        self.geber_index = (self.geber_index + 1) % len(self.spieler)
        self.phase = PHASE_SPIEL
        self._geben(rng)

    def _geben(self, rng=None) -> None:
        spielend, _ = self.aktive_positionen()
        ids = [self.spieler[pos]["id"] for pos in spielend]
        self.spiel = SkatSpiel(ids, geber_id=self.geber_id, rng=rng or random.Random())
        self._geaendert()

    # -- Aktionen ----------------------------------------------------------

    _AKTIONEN = {
        "reizen", "hoeren", "passen", "skat_aufnehmen", "hand_spielen",
        "druecken", "ansagen", "karte_spielen",
    }

    def aktion(self, token: str, name: str, daten: dict | None = None) -> dict:
        """Fuehrt einen Spielzug aus. Gibt das Ergebnis zurueck, falls das
        Spiel dadurch endet."""
        daten = daten or {}
        eintrag, zuschauend = self.teilnehmer_nach_token(token)
        if eintrag is None:
            raise RegelFehler("Unbekanntes Token - bitte dem Tisch neu beitreten.")
        if zuschauend:
            raise RegelFehler(
                "Du schaust gerade zu und bist ab dem naechsten Spiel dabei."
            )
        if self.spiel is None or self.phase != PHASE_SPIEL:
            raise RegelFehler("Gerade laeuft kein Spiel.")
        if name not in self._AKTIONEN:
            raise RegelFehler(f"Unbekannte Aktion: {name!r}")

        pos = self.spiel.position_von(eintrag["id"])  # wirft, wenn aussetzend

        if name == "reizen":
            self.spiel.reizen(pos, int(daten["wert"]))
        elif name == "hoeren":
            self.spiel.hoeren(pos)
        elif name == "passen":
            self.spiel.passen(pos)
        elif name == "skat_aufnehmen":
            self.spiel.skat_aufnehmen(pos)
        elif name == "hand_spielen":
            self.spiel.hand_spielen(pos)
        elif name == "druecken":
            self.spiel.druecken(pos, [Karte.aus_code(c) for c in daten["karten"]])
        elif name == "ansagen":
            self.spiel.ansagen(pos, Ansage(
                spielart=daten["spielart"],
                hand=bool(daten.get("hand")),
                ouvert=bool(daten.get("ouvert")),
                schneider_angesagt=bool(daten.get("schneider_angesagt")),
                schwarz_angesagt=bool(daten.get("schwarz_angesagt")),
            ))
        elif name == "karte_spielen":
            self.spiel.karte_spielen(pos, Karte.aus_code(daten["karte"]))

        beendet = None
        if self.spiel.phase == e.PHASE_BEENDET:
            beendet = self._spiel_abschliessen()

        self._geaendert()
        return {"beendet": beendet}

    def _spiel_abschliessen(self) -> dict:
        """Baut die Zeile fuer die Tabelle ``spiel``."""
        erg = self.spiel.ergebnis
        spielend, _ = self.aktive_positionen()
        aktive_ids = [self.spieler[pos]["id"] for pos in spielend]

        zeile = {
            "aktive_spieler_ids": ",".join(str(i) for i in aktive_ids),
            "geber_id": self.geber_id,
            "einzelspieler_id": None if erg.eingepasst else self.spiel.alleinspieler_id,
            "spielart": erg.spielart,
            "reizwert": erg.reizwert,
            "spitzen": erg.spitzen,
            "hand": erg.hand,
            "ouvert": erg.ouvert,
            "schneider_angesagt": erg.schneider_angesagt,
            "schwarz_angesagt": erg.schwarz_angesagt,
            "schwarz_erreicht": erg.schwarz_erreicht,
            "augen": erg.augen,
            "spielwert": erg.spielwert,
            "quelle": "remote",
            "sitzung_id": self.sitzung_id,
        }
        self.ergebnisse.append({
            "zeile": zeile,
            "gewonnen": erg.gewonnen,
            "augen_alleinspieler": erg.augen_alleinspieler,
            "stiche_alleinspieler": erg.stiche_alleinspieler,
            "ueberreizt": erg.ueberreizt,
            "alleinspieler_id": self.spiel.alleinspieler_id,
        })
        self.phase = PHASE_PAUSE
        return zeile

    def zurueck_in_die_lobby(self, token: str) -> None:
        """Beendet die laufende Runde und oeffnet die Aufstellung wieder.

        Nur zwischen zwei Spielen. In der Lobby koennen Spielerinnen gehen,
        dazukommen und die Sitzordnung neu legen. Die bisherigen Ergebnisse
        der Runde bleiben stehen - gespielt ist gespielt.
        """
        if self.spieler_nach_token(token) is None:
            raise RegelFehler("Du sitzt nicht an diesem Tisch.")
        if self.phase == PHASE_LOBBY:
            return
        if self.phase != PHASE_PAUSE:
            raise RegelFehler(
                "Das geht erst nach einem Spiel, nicht mitten in einer Runde."
            )
        self.phase = PHASE_LOBBY
        self.spiel = None
        self.geber_index = 0
        self._zuschauer_nachruecken()
        self._geaendert()

    def spieler_entfernen(self, token: str, ziel_id: int) -> dict:
        """Entfernt eine offline gegangene Spielerin vom Tisch.

        Das laufende Spiel wird dabei verworfen - es waere sonst unspielbar.
        Es ist noch nicht gespeichert, geht also auch nicht in die Statistik
        ein. Danach wird sofort neu gegeben, sofern noch mindestens drei
        Leute sitzen; sonst geht es zurueck in die Lobby.
        """
        if self.spieler_nach_token(token) is None:
            raise RegelFehler("Du sitzt nicht an diesem Tisch.")

        ziel = self._spieler_nach_id(ziel_id)
        if ziel is None:
            raise RegelFehler("Diese Spielerin sitzt nicht an diesem Tisch.")
        if secrets.compare_digest(ziel["token"], token):
            raise RegelFehler(
                "Dich selbst kannst du so nicht entfernen - verlasse den Tisch "
                "in der Lobby."
            )
        if self.ist_verbunden(ziel):
            raise RegelFehler(
                f"{ziel['name']} ist gerade online und kann nicht entfernt werden."
            )

        # Reihenfolge und Geberin festhalten, bevor die Liste schrumpft.
        alte_reihenfolge = [s["id"] for s in self.spieler]
        alter_geber = self.geber_id

        self.spieler.remove(ziel)
        self.spiel = None
        # Der frei gewordene Platz geht an die naechste Wartende.
        self._zuschauer_nachruecken()

        if len(self.spieler) < 3:
            self.phase = PHASE_LOBBY
            self.geber_index = 0
            self._geaendert()
            return {"entfernt": ziel["name"], "weiter": "lobby"}

        # Es gibt neu - also gibt die naechste verbliebene Spielerin nach der
        # bisherigen Geberin. Das gilt auch dann, wenn die Geberin selbst weg ist.
        verbleibend = {s["id"] for s in self.spieler if s["id"] in alte_reihenfolge}
        start = alte_reihenfolge.index(alter_geber)
        naechster = next(
            alte_reihenfolge[(start + schritt) % len(alte_reihenfolge)]
            for schritt in range(1, len(alte_reihenfolge) + 1)
            if alte_reihenfolge[(start + schritt) % len(alte_reihenfolge)] in verbleibend
        )
        self.geber_index = [s["id"] for s in self.spieler].index(naechster)

        self.phase = PHASE_SPIEL
        self._geben()
        return {"entfernt": ziel["name"], "weiter": "neues_spiel"}

    def kann_zuruecknehmen(self) -> bool:
        """Darf gerade das letzte Spiel zurückgenommen werden?

        Nur zwischen zwei Spielen: läuft schon wieder eines, wäre nicht mehr
        eindeutig, was "das letzte Spiel" ist, und die Geberin ließe sich
        nicht mehr sauber zurückdrehen.
        """
        return self.phase == PHASE_PAUSE and bool(self.ergebnisse)

    def zuruecknehmen_pruefen(self) -> None:
        """Wirft, wenn gerade nicht zurückgenommen werden darf."""
        if self.phase != PHASE_PAUSE:
            raise RegelFehler(
                "Zurücknehmen geht nur direkt nach einem Spiel, bevor neu gegeben wurde."
            )
        if not self.ergebnisse:
            raise RegelFehler("An diesem Tisch wurde noch kein Spiel beendet.")

    def letztes_spiel_zuruecknehmen(self) -> dict:
        """Nimmt das gerade beendete Spiel am Tisch zurück."""
        self.zuruecknehmen_pruefen()
        entfernt = self.ergebnisse.pop()
        # Das nächste Geben rückt die Geberin weiter. Damit die zurückgenommene
        # Runde von derselben Geberin wiederholt wird, einen Platz zurückdrehen.
        self.geber_index = (self.geber_index - 1) % len(self.spieler)
        self._geaendert()
        return entfernt

    # -- Sichten -----------------------------------------------------------

    def _spieler_liste(self) -> list[dict]:
        spielend, aussetzend = ([], [])
        if self.spiel is not None and 3 <= len(self.spieler) <= 5:
            spielend, aussetzend = self.aktive_positionen()
        return [
            {
                "id": s["id"],
                "name": s["name"],
                "position": pos,
                "ist_geber": pos == self.geber_index,
                "setzt_aus": pos in aussetzend,
                "spielt_mit": pos in spielend,
                # Nur ein Hinweis fuer die Anzeige - von allein fliegt niemand
                # raus, aber Offline-Sitzende darf der Tisch entfernen.
                "verbunden": self.ist_verbunden(s),
            }
            for pos, s in enumerate(self.spieler)
        ]

    def _zuschauer_liste(self) -> list[dict]:
        return [
            {
                "id": z["id"],
                "name": z["name"],
                "verbunden": self.ist_verbunden(z),
                # Rueckt nur nach, wenn ueberhaupt ein Platz frei wird.
                "wartet_auf_platz": not self.platz_frei(),
            }
            for z in self.zuschauer
        ]

    def sicht_fuer(self, token: str, aufdecken: bool = False) -> dict:
        eintrag, zuschauend = self.teilnehmer_nach_token(token)
        if eintrag is None:
            raise RegelFehler("Unbekanntes Token - bitte dem Tisch neu beitreten.")
        self.gesehen(token)

        zustand = {
            "code": self.code,
            "version": self.version,
            "phase": self.phase,
            "spieler": self._spieler_liste(),
            "geber_id": self.geber_id,
            "ich": {"id": eintrag["id"], "name": eintrag["name"]},
            "ergebnisse": self.ergebnisse[-10:],
            "reizwerte": e.REIZWERTE,
            "sitzung_id": self.sitzung_id,
            "undo_moeglich": self.kann_zuruecknehmen(),
            "zuschauer": self._zuschauer_liste(),
            "platz_frei": self.platz_frei(),
        }
        zustand["ich"]["zuschauer"] = zuschauend
        if zuschauend:
            # Warum man zuschaut, entscheidet, worauf man wartet.
            zustand["ich"]["wartet_auf_platz"] = not self.platz_frei()

        if self.spiel is None:
            zustand["spiel"] = None
            # In der Lobby wird ohnehin gleich nachgerueckt.
            zustand["darf_aufdecken"] = False
            return zustand

        if zuschauend:
            # Zuschauende sehen dasselbe wie Aussetzende: von Haus aus nur den
            # oeffentlichen Tisch, auf Wunsch alles.
            zustand["darf_aufdecken"] = True
            zustand["spiel"] = (
                self.spiel.vollsicht() if aufdecken else self.spiel.oeffentlicher_zustand()
            )
            zustand["aufgedeckt"] = bool(aufdecken)
            return zustand

        setzt_aus = self.setzt_aus(eintrag["id"])
        zustand["ich"]["setzt_aus"] = setzt_aus
        # Aufdecken darf nur, wer selbst nicht mitspielt.
        zustand["darf_aufdecken"] = setzt_aus
        if setzt_aus:
            zustand["spiel"] = self.spiel.vollsicht() if aufdecken else self.spiel.oeffentlicher_zustand()
            zustand["aufgedeckt"] = bool(aufdecken)
        else:
            zustand["spiel"] = self.spiel.sicht_fuer(eintrag["id"])
            zustand["aufgedeckt"] = False
        return zustand

    # -- Zustand sichern ---------------------------------------------------

    def _geaendert(self) -> None:
        self.version += 1

    def als_dict(self) -> dict:
        return {
            "code": self.code,
            "spieler": [dict(s) for s in self.spieler],
            "zuschauer": [dict(z) for z in self.zuschauer],
            "geber_index": self.geber_index,
            "phase": self.phase,
            "spiel": None if self.spiel is None else self.spiel.als_dict(),
            "ergebnisse": self.ergebnisse,
            "version": self.version,
            "erstellt": self.erstellt,
        }

    @classmethod
    def aus_dict(cls, daten: dict) -> "Tisch":
        tisch = cls(code=daten["code"])
        tisch.spieler = [dict(s) for s in daten["spieler"]]
        # Aeltere Schnappschuesse kennen noch keine Zuschauenden.
        tisch.zuschauer = [dict(z) for z in daten.get("zuschauer", [])]
        tisch.geber_index = daten["geber_index"]
        tisch.phase = daten["phase"]
        tisch.spiel = None if daten["spiel"] is None else SkatSpiel.aus_dict(daten["spiel"])
        tisch.ergebnisse = daten["ergebnisse"]
        tisch.version = daten["version"]
        tisch.erstellt = daten.get("erstellt", time.time())
        return tisch
