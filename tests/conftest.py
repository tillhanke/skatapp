import sys
from pathlib import Path

# Projektwurzel importierbar machen, damit "import skat_engine" / "import app" geht.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import pytest


@pytest.fixture
def testdb(tmp_path, monkeypatch):
    """Frische Datenbank mit Spielerinnen, auf die App und db_setup zeigen."""
    import app as skat_app
    import db_setup

    pfad = str(tmp_path / "test_skat.db")
    monkeypatch.setattr(db_setup, "DB_DATEI", pfad)
    db_setup.datenbank_initialisieren()
    db_setup.spieler_hinzufuegen(["Anna", "Berta", "Clara", "Dora", "Emma"])

    monkeypatch.setattr(skat_app, "DB_DATEI", pfad)

    # Das Zweitprotokoll liegt sonst neben der echten Datenbank - Tests
    # dürfen dort nichts hineinschreiben.
    import verlauf
    monkeypatch.setattr(verlauf, "DB_DATEI", str(tmp_path / "test_verlauf.db"))

    # Beide Zustände leben im Prozess, nicht in der Datenbank, und müssen
    # zwischen den Tests zurückgesetzt werden.
    skat_app._tische.clear()
    skat_app._undo_verbraucht.clear()
    yield pfad
    skat_app._tische.clear()
    skat_app._undo_verbraucht.clear()


@pytest.fixture
def client(testdb):
    import app as skat_app
    skat_app.app.config.update(TESTING=True)
    return skat_app.app.test_client()
