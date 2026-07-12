import sqlite3

import pytest

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


def test_connetti_attiva_foreign_keys(tmp_path):
    percorso_db = tmp_path / "volti_test.db"

    init_db(percorso_db)
    conn = connetti(percorso_db)
    stato = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.close()

    assert stato == 1


def test_foreign_key_person_id_inesistente_solleva_integrity_error(tmp_path):
    percorso_db = tmp_path / "volti_test.db"

    init_db(percorso_db)
    conn = connetti(percorso_db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO embedding (person_id, vettore, foto_origine, fonte) "
                "VALUES (?, ?, ?, ?)",
                (999, b"\x00", "foto.jpg", "test"),
            )
    finally:
        conn.close()


import numpy as np

from db.database import trova_o_crea_persona, salva_embedding, registra_scarto


def test_trova_o_crea_persona_crea_nuova_persona(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    person_id = trova_o_crea_persona(conn, "Mario Rossi")

    riga = conn.execute(
        "SELECT nome FROM persone WHERE id = ?", (person_id,)
    ).fetchone()
    conn.close()
    assert riga[0] == "Mario Rossi"


def test_trova_o_crea_persona_riusa_persona_esistente(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    primo_id = trova_o_crea_persona(conn, "Mario Rossi")
    secondo_id = trova_o_crea_persona(conn, "Mario Rossi")

    conteggio = conn.execute("SELECT COUNT(*) FROM persone").fetchone()[0]
    conn.close()
    assert primo_id == secondo_id
    assert conteggio == 1


def test_salva_embedding_inserisce_e_recupera_vettore(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    person_id = trova_o_crea_persona(conn, "Mario Rossi")
    vettore_originale = np.random.rand(512).astype(np.float32)

    embedding_id = salva_embedding(
        conn, person_id, vettore_originale, "foto.jpg", "batch_iniziale"
    )

    riga = conn.execute(
        "SELECT vettore, person_id, foto_origine, fonte FROM embedding WHERE id = ?",
        (embedding_id,),
    ).fetchone()
    conn.close()
    vettore_recuperato = np.frombuffer(riga[0], dtype=np.float32)
    assert np.array_equal(vettore_recuperato, vettore_originale)
    assert riga[1] == person_id
    assert riga[2] == "foto.jpg"
    assert riga[3] == "batch_iniziale"


def test_registra_scarto_inserisce_riga(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    scarto_id = registra_scarto(conn, "foto_scartata.jpg", "nessun_volto")

    riga = conn.execute(
        "SELECT foto, motivo FROM log_scarti WHERE id = ?", (scarto_id,)
    ).fetchone()
    conn.close()
    assert riga[0] == "foto_scartata.jpg"
    assert riga[1] == "nessun_volto"
