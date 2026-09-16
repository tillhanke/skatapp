"""Ausführliches Protokoll der remote gespielten Partien.

Bewusst eine **eigene** Datenbankdatei: ``skat_daten.db`` bleibt unangetastet,
es gibt dort weder neue Tabellen noch neue Spalten. Wer das Protokoll nicht
braucht, kann die Datei löschen, ohne dass der Punktestand darunter leidet.

Verbunden sind beide Datenbanken nur über ``partie.spiel_id`` - die ``id`` der
Zeile in ``skat_daten.db`` → Tabelle ``spiel``. SQLite kann über Dateigrenzen
hinweg keinen Fremdschlüssel prüfen, deshalb ist das eine reine Zahl. Sie
bleibt trotzdem eindeutig: ``spiel.id`` ist AUTOINCREMENT, vergebene Nummern
werden also nie erneut verwendet.

Protokolliert wird, was sich aus dem Ergebnis allein nicht rekonstruieren
lässt: die ausgeteilten Blätter, der Skat, das Gedrückte, der Reizverlauf und
jede gespielte Karte in ihrer Reihenfolge.
"""

from __future__ import annotations

import os
import sqlite3

import skat_engine as e


def _standard_pfad() -> str:
    """Neben die Hauptdatenbank legen, damit ein Volume beide erfasst."""
    haupt = os.environ.get("SKAT_DB", "skat_daten.db")
    return os.path.join(os.path.dirname(os.path.abspath(haupt)), "skat_verlauf.db")


DB_DATEI = os.environ.get("SKAT_VERLAUF_DB") or _standard_pfad()

# Das Schema wird je Prozess einmal sichergestellt.
_schema_geprueft: set[str] = set()


SCHEMA = """
CREATE TABLE IF NOT EXISTS partie (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- id der zugehörigen Zeile in skat_daten.db -> spiel. Kein echter
    -- Fremdschlüssel: andere Datei.
    spiel_id INTEGER,
    tisch_code TEXT NOT NULL,
    sitzung_id TEXT NOT NULL,
    zeitstempel DATETIME DEFAULT CURRENT_TIMESTAMP,

    geber_id INTEGER NOT NULL,
    vorhand_id INTEGER NOT NULL,
    alleinspieler_id INTEGER,

    spielart TEXT NOT NULL,
    reizwert INTEGER NOT NULL,
    spitzen INTEGER,
    hand INTEGER DEFAULT 0,
    ouvert INTEGER DEFAULT 0,
    schneider_angesagt INTEGER DEFAULT 0,
    schwarz_angesagt INTEGER DEFAULT 0,

    skat TEXT NOT NULL,
    skat_aufgenommen INTEGER DEFAULT 0,
    gedrueckt TEXT DEFAULT '',

    augen_alleinspieler INTEGER DEFAULT 0,
    stiche_alleinspieler INTEGER DEFAULT 0,
    gewonnen INTEGER DEFAULT 0,
    ueberreizt INTEGER DEFAULT 0,
    spielwert INTEGER DEFAULT 0,

    -- Wurde das Spiel nachträglich zurückgenommen? Die Zeile in spiel ist
    -- dann weg; hier bleibt sie als Beleg stehen.
    zurueckgenommen INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS blatt (
    partie_id INTEGER NOT NULL,
    spieler_id INTEGER NOT NULL,
    position INTEGER NOT NULL,      -- 0 Vorhand, 1 Mittelhand, 2 Hinterhand
    karten TEXT NOT NULL,           -- die zehn gegebenen Karten, kommagetrennt
    PRIMARY KEY (partie_id, spieler_id)
);

CREATE TABLE IF NOT EXISTS reizen (
    partie_id INTEGER NOT NULL,
    nummer INTEGER NOT NULL,
    spieler_id INTEGER NOT NULL,
    aktion TEXT NOT NULL,           -- reizt / hoert / passt
    wert INTEGER,
    PRIMARY KEY (partie_id, nummer)
);

CREATE TABLE IF NOT EXISTS stich (
    partie_id INTEGER NOT NULL,
    nummer INTEGER NOT NULL,        -- 1 bis 10
    gewinner_id INTEGER NOT NULL,
    augen INTEGER NOT NULL,
    PRIMARY KEY (partie_id, nummer)
);

CREATE TABLE IF NOT EXISTS zug (
    partie_id INTEGER NOT NULL,
    stich INTEGER NOT NULL,
    reihenfolge INTEGER NOT NULL,   -- 0 = ausgespielt, dann im Uhrzeigersinn
    spieler_id INTEGER NOT NULL,
    karte TEXT NOT NULL,
    PRIMARY KEY (partie_id, stich, reihenfolge)
);

CREATE INDEX IF NOT EXISTS idx_partie_spiel ON partie (spiel_id);
CREATE INDEX IF NOT EXISTS idx_partie_tisch ON partie (tisch_code, id);
"""


def verbindung(pfad: str | None = None) -> sqlite3.Connection:
    """Verbindung zur Protokolldatenbank; legt sie beim ersten Mal an."""
    pfad = pfad or DB_DATEI
    ordner = os.path.dirname(os.path.abspath(pfad))
    if ordner:
        os.makedirs(ordner, exist_ok=True)

    verb = sqlite3.connect(pfad)
    verb.row_factory = sqlite3.Row
    verb.execute("PRAGMA journal_mode=WAL")
    verb.execute("PRAGMA busy_timeout=5000")

    if pfad not in _schema_geprueft:
        verb.executescript(SCHEMA)
        verb.commit()
        _schema_geprueft.add(pfad)
    return verb


def _codes(karten) -> str:
    return ",".join(k.code for k in karten)


def stiche_mit_spielern(spiel) -> list[dict]:
    """Rechnet aus, wer welche Karte gelegt hat.

    Die Engine merkt sich je Stich nur Gewinnerin und Karten in Spielfolge.
    Wer sie gelegt hat, ergibt sich aus der Ausspielenden: den ersten Stich
    spielt die Vorhand aus, danach jeweils die Gewinnerin des Stichs davor.
    """
    ergebnis = []
    ausspiel = 0                       # Vorhand beginnt
    for nummer, (gewinner, karten) in enumerate(spiel.stiche, start=1):
        zuege = [
            {
                "reihenfolge": versatz,
                "spieler_id": spiel.spieler_ids[(ausspiel + versatz) % 3],
                "karte": karte.code,
            }
            for versatz, karte in enumerate(karten)
        ]
        ergebnis.append({
            "nummer": nummer,
            "gewinner_id": spiel.spieler_ids[gewinner],
            "augen": e.augen_summe(karten),
            "zuege": zuege,
        })
        ausspiel = gewinner
    return ergebnis


def protokolliere(tisch, spiel_id: int | None, pfad: str | None = None) -> int:
    """Schreibt das gerade beendete Spiel eines Tisches ins Protokoll.

    Gibt die ``partie.id`` zurück. Muss aufgerufen werden, solange
    ``tisch.spiel`` noch das beendete Spiel hält - also vor dem nächsten Geben.
    """
    spiel = tisch.spiel
    if spiel is None or spiel.ergebnis is None:
        raise ValueError("Am Tisch ist gerade kein beendetes Spiel.")

    erg = spiel.ergebnis
    ansage = spiel.ansage

    verb = verbindung(pfad)
    try:
        zeiger = verb.execute(
            """
            INSERT INTO partie (
                spiel_id, tisch_code, sitzung_id,
                geber_id, vorhand_id, alleinspieler_id,
                spielart, reizwert, spitzen,
                hand, ouvert, schneider_angesagt, schwarz_angesagt,
                skat, skat_aufgenommen, gedrueckt,
                augen_alleinspieler, stiche_alleinspieler,
                gewonnen, ueberreizt, spielwert
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                spiel_id, tisch.code, tisch.sitzung_id,
                spiel.geber_id, spiel.spieler_ids[0], spiel.alleinspieler_id,
                erg.spielart, erg.reizwert, erg.spitzen,
                erg.hand, erg.ouvert, erg.schneider_angesagt, erg.schwarz_angesagt,
                _codes(spiel.urskat), 1 if spiel.skat_aufgenommen else 0,
                _codes(spiel.gedrueckt),
                erg.augen_alleinspieler, erg.stiche_alleinspieler,
                1 if erg.gewonnen else 0, 1 if erg.ueberreizt else 0, erg.spielwert,
            ),
        )
        partie_id = zeiger.lastrowid

        verb.executemany(
            "INSERT INTO blatt (partie_id, spieler_id, position, karten) VALUES (?, ?, ?, ?)",
            [
                (partie_id, spiel.spieler_ids[pos], pos, _codes(spiel.urblaetter[pos]))
                for pos in range(3)
            ],
        )

        verb.executemany(
            "INSERT INTO reizen (partie_id, nummer, spieler_id, aktion, wert) VALUES (?, ?, ?, ?, ?)",
            [
                (partie_id, nummer, spiel.spieler_ids[pos], aktion, wert)
                for nummer, (pos, aktion, wert) in enumerate(spiel.reiz_verlauf, start=1)
            ],
        )

        stiche = stiche_mit_spielern(spiel)
        verb.executemany(
            "INSERT INTO stich (partie_id, nummer, gewinner_id, augen) VALUES (?, ?, ?, ?)",
            [(partie_id, s["nummer"], s["gewinner_id"], s["augen"]) for s in stiche],
        )
        verb.executemany(
            "INSERT INTO zug (partie_id, stich, reihenfolge, spieler_id, karte) VALUES (?, ?, ?, ?, ?)",
            [
                (partie_id, s["nummer"], z["reihenfolge"], z["spieler_id"], z["karte"])
                for s in stiche for z in s["zuege"]
            ],
        )
        verb.commit()
        return partie_id
    finally:
        verb.close()


def als_zurueckgenommen_markieren(spiel_id: int, pfad: str | None = None) -> int:
    """Markiert ein zurückgenommenes Spiel, statt das Protokoll zu löschen.

    Gespielt wurde es ja - es zählt nur nicht mehr. Die Zeile in ``spiel`` ist
    weg, ``spiel_id`` zeigt also ins Leere; weil ids nie neu vergeben werden,
    kann sie aber niemals ein anderes Spiel meinen.
    """
    verb = verbindung(pfad)
    try:
        zeiger = verb.execute(
            "UPDATE partie SET zurueckgenommen = 1 WHERE spiel_id = ?", (spiel_id,)
        )
        verb.commit()
        return zeiger.rowcount
    finally:
        verb.close()


def lade_partie(partie_id: int, pfad: str | None = None) -> dict | None:
    """Liest eine protokollierte Partie vollständig zurück."""
    verb = verbindung(pfad)
    try:
        kopf = verb.execute("SELECT * FROM partie WHERE id = ?", (partie_id,)).fetchone()
        if kopf is None:
            return None

        daten = dict(kopf)
        daten["blaetter"] = [
            dict(z) for z in verb.execute(
                "SELECT * FROM blatt WHERE partie_id = ? ORDER BY position", (partie_id,))
        ]
        daten["reizen"] = [
            dict(z) for z in verb.execute(
                "SELECT * FROM reizen WHERE partie_id = ? ORDER BY nummer", (partie_id,))
        ]
        stiche = [
            dict(z) for z in verb.execute(
                "SELECT * FROM stich WHERE partie_id = ? ORDER BY nummer", (partie_id,))
        ]
        zuege = [
            dict(z) for z in verb.execute(
                "SELECT * FROM zug WHERE partie_id = ? ORDER BY stich, reihenfolge",
                (partie_id,))
        ]
        for s in stiche:
            s["zuege"] = [z for z in zuege if z["stich"] == s["nummer"]]
        daten["stiche"] = stiche
        return daten
    finally:
        verb.close()
