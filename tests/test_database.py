import sqlite3

import numpy as np
import pytest

from db.database import (
    init_db,
    connetti,
    trova_o_crea_persona,
    salva_embedding,
    registra_scarto,
    foto_gia_processata,
    embedding_da_sincronizzare,
    segna_sincronizzato,
    leggi_sync_stato,
    aggiorna_sync_stato,
    esporta_persone_dopo,
    esporta_embedding_dopo,
)


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


def test_foto_gia_processata_ritorna_false_se_nessuna_riga(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    risultato = foto_gia_processata(conn, "foto_mai_vista.jpg")
    conn.close()
    assert risultato is False


def test_foto_gia_processata_ritorna_true_dopo_salva_embedding(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    person_id = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = np.random.rand(512).astype(np.float32)

    salva_embedding(conn, person_id, vettore, "foto_salvata.jpg", "batch_iniziale")

    risultato = foto_gia_processata(conn, "foto_salvata.jpg")
    conn.close()
    assert risultato is True


def test_foto_gia_processata_ritorna_true_dopo_registra_scarto(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    registra_scarto(conn, "foto_scartata.jpg", "nessun_volto")

    risultato = foto_gia_processata(conn, "foto_scartata.jpg")
    conn.close()
    assert risultato is True


def test_init_db_su_db_vecchio_aggiunge_colonna_sincronizzato(tmp_path):
    percorso_db = tmp_path / "vecchio.db"
    conn = sqlite3.connect(str(percorso_db))
    conn.executescript(
        """
        CREATE TABLE persone (id INTEGER PRIMARY KEY, nome TEXT UNIQUE NOT NULL, note TEXT,
            creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE embedding (id INTEGER PRIMARY KEY, person_id INTEGER NOT NULL REFERENCES persone(id),
            vettore BLOB NOT NULL, foto_origine TEXT NOT NULL, fonte TEXT NOT NULL,
            creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        """
    )
    conn.commit()
    conn.close()

    init_db(percorso_db)

    conn = connetti(percorso_db)
    colonne = [riga[1] for riga in conn.execute("PRAGMA table_info(embedding)").fetchall()]
    conn.close()
    assert "sincronizzato" in colonne


def test_init_db_migrazione_colonna_e_idempotente(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    init_db(percorso_db)  # seconda chiamata non deve sollevare errori

    conn = connetti(percorso_db)
    colonne = [riga[1] for riga in conn.execute("PRAGMA table_info(embedding)").fetchall()]
    conn.close()
    assert colonne.count("sincronizzato") == 1


def test_init_db_crea_tabella_sync_stato(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)

    conn = connetti(percorso_db)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tabelle = {riga[0] for riga in cursor.fetchall()}
    conn.close()
    assert "sync_stato" in tabelle


def test_salva_embedding_default_sincronizzato_true(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    person_id = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = np.random.rand(512).astype(np.float32)

    embedding_id = salva_embedding(conn, person_id, vettore, "foto.jpg", "batch_iniziale")

    riga = conn.execute(
        "SELECT sincronizzato FROM embedding WHERE id = ?", (embedding_id,)
    ).fetchone()
    conn.close()
    assert riga[0] == 1


def test_salva_embedding_sincronizzato_false(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    person_id = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = np.random.rand(512).astype(np.float32)

    embedding_id = salva_embedding(
        conn, person_id, vettore, "foto.jpg", "conferma_editing", sincronizzato=False
    )

    riga = conn.execute(
        "SELECT sincronizzato FROM embedding WHERE id = ?", (embedding_id,)
    ).fetchone()
    conn.close()
    assert riga[0] == 0


def test_embedding_da_sincronizzare_ritorna_solo_le_pendenti(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = np.random.rand(512).astype(np.float32)
    salva_embedding(conn, id_mario, vettore, "sincronizzata.jpg", "batch_iniziale")
    embedding_id_pendente = salva_embedding(
        conn, id_mario, vettore, "pendente.jpg", "conferma_editing", sincronizzato=False
    )

    pendenti = embedding_da_sincronizzare(conn)
    conn.close()

    assert len(pendenti) == 1
    assert pendenti[0]["id"] == embedding_id_pendente
    assert pendenti[0]["nome"] == "Mario Rossi"
    assert pendenti[0]["foto_origine"] == "pendente.jpg"
    assert pendenti[0]["fonte"] == "conferma_editing"
    assert len(pendenti[0]["vettore"]) == 512


def test_segna_sincronizzato_aggiorna_la_riga(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = np.random.rand(512).astype(np.float32)
    embedding_id = salva_embedding(
        conn, id_mario, vettore, "pendente.jpg", "conferma_editing", sincronizzato=False
    )

    segna_sincronizzato(conn, embedding_id)

    riga = conn.execute(
        "SELECT sincronizzato FROM embedding WHERE id = ?", (embedding_id,)
    ).fetchone()
    conn.close()
    assert riga[0] == 1


def test_leggi_sync_stato_crea_riga_singleton_se_assente(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    stato = leggi_sync_stato(conn)
    conn.close()

    assert stato == (0, 0)


def test_aggiorna_sync_stato_persiste_valori(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    aggiorna_sync_stato(conn, 5, 10)
    stato = leggi_sync_stato(conn)
    conn.close()

    assert stato == (5, 10)


def test_esporta_persone_dopo_filtra_per_id(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    id_prima = trova_o_crea_persona(conn, "Prima Persona")
    trova_o_crea_persona(conn, "Seconda Persona")

    risultato = esporta_persone_dopo(conn, id_prima)
    conn.close()

    assert [p["nome"] for p in risultato] == ["Seconda Persona"]


def test_esporta_embedding_dopo_include_vettore_come_lista(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    vettore_originale = np.random.rand(512).astype(np.float32)
    salva_embedding(conn, id_mario, vettore_originale, "foto.jpg", "batch_iniziale")

    risultato = esporta_embedding_dopo(conn, 0)
    conn.close()

    assert len(risultato) == 1
    riga = risultato[0]
    assert riga["nome"] == "Mario Rossi"
    assert riga["foto_origine"] == "foto.jpg"
    assert riga["fonte"] == "batch_iniziale"
    assert np.allclose(riga["vettore"], vettore_originale.tolist())
