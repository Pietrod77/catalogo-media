import numpy as np

from db.database import connetti, init_db, salva_embedding, trova_o_crea_persona
from scripts.propaga_modelle_in_personaggi import propaga


def _vettore_normalizzato(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    return v / np.linalg.norm(v)


def test_propaga_copia_persone_ed_embedding_di_modelle_in_personaggi(tmp_path):
    db_modelle = tmp_path / "volti_modelle.db"
    db_personaggi = tmp_path / "volti.db"
    init_db(db_modelle)

    conn = connetti(db_modelle)
    id_modella = trova_o_crea_persona(conn, "Modella Uno")
    salva_embedding(
        conn, id_modella, _vettore_normalizzato(1), "screenshot_modelle_1.jpg", "conferma_editing"
    )
    conn.close()

    risultato = propaga(db_modelle, db_personaggi)

    assert risultato == {"copiati": 1, "saltati": 0}

    conn = connetti(db_personaggi)
    persona = conn.execute("SELECT id FROM persone WHERE nome = ?", ("Modella Uno",)).fetchone()
    assert persona is not None
    embedding = conn.execute(
        "SELECT foto_origine, fonte FROM embedding WHERE person_id = ?", (persona[0],)
    ).fetchone()
    conn.close()
    assert embedding[0] == "screenshot_modelle_1.jpg"
    assert embedding[1] == "conferma_editing"


def test_propaga_non_duplica_persone_gia_presenti_in_personaggi(tmp_path):
    db_modelle = tmp_path / "volti_modelle.db"
    db_personaggi = tmp_path / "volti.db"
    init_db(db_modelle)
    init_db(db_personaggi)

    conn_modelle = connetti(db_modelle)
    id_modella = trova_o_crea_persona(conn_modelle, "Nome Condiviso")
    salva_embedding(
        conn_modelle, id_modella, _vettore_normalizzato(2), "screenshot_a.jpg", "conferma_editing"
    )
    conn_modelle.close()

    conn_personaggi = connetti(db_personaggi)
    trova_o_crea_persona(conn_personaggi, "Nome Condiviso")
    conn_personaggi.close()

    propaga(db_modelle, db_personaggi)

    conn_personaggi = connetti(db_personaggi)
    persone = conn_personaggi.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Nome Condiviso",)
    ).fetchall()
    conn_personaggi.close()
    assert len(persone) == 1


def test_propaga_e_idempotente_su_riesecuzione(tmp_path):
    db_modelle = tmp_path / "volti_modelle.db"
    db_personaggi = tmp_path / "volti.db"
    init_db(db_modelle)

    conn = connetti(db_modelle)
    id_modella = trova_o_crea_persona(conn, "Modella Due")
    salva_embedding(
        conn, id_modella, _vettore_normalizzato(3), "screenshot_modelle_2.jpg", "conferma_editing"
    )
    conn.close()

    primo_risultato = propaga(db_modelle, db_personaggi)
    secondo_risultato = propaga(db_modelle, db_personaggi)

    assert primo_risultato == {"copiati": 1, "saltati": 0}
    assert secondo_risultato == {"copiati": 0, "saltati": 1}

    conn = connetti(db_personaggi)
    embedding_totali = conn.execute("SELECT COUNT(*) FROM embedding").fetchone()[0]
    conn.close()
    assert embedding_totali == 1


def test_propaga_con_modelle_vuoto_non_fa_nulla(tmp_path):
    db_modelle = tmp_path / "volti_modelle.db"
    db_personaggi = tmp_path / "volti.db"

    risultato = propaga(db_modelle, db_personaggi)

    assert risultato == {"copiati": 0, "saltati": 0}
