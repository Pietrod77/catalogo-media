import sqlite3
from pathlib import Path

from db.database import init_db, connetti


def test_init_db_crea_le_tre_tabelle(tmp_path):
    percorso_db = tmp_path / "volti_test.db"

    init_db(percorso_db)

    conn = connetti(percorso_db)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tabelle = {riga[0] for riga in cursor.fetchall()}
    conn.close()

    assert {"persone", "embedding", "log_scarti"}.issubset(tabelle)


def test_init_db_e_idempotente(tmp_path):
    percorso_db = tmp_path / "volti_test.db"

    init_db(percorso_db)
    init_db(percorso_db)  # non deve sollevare errori se richiamata due volte

    conn = connetti(percorso_db)
    cursor = conn.execute("SELECT COUNT(*) FROM persone")
    assert cursor.fetchone()[0] == 0
    conn.close()


def test_connetti_usa_journal_mode_default_non_wal(tmp_path):
    percorso_db = tmp_path / "volti_test.db"

    init_db(percorso_db)
    conn = connetti(percorso_db)
    modalita = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()

    assert modalita.lower() != "wal"
