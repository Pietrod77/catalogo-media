import numpy as np
import pytest

from core.matching import calcola_candidati, classifica_match, Candidato
from db.database import connetti, init_db, trova_o_crea_persona, salva_embedding


def _vettore_normalizzato(seed: int) -> np.ndarray:
    """Genera un vettore casuale riproducibile e normalizzato L2 (come un vero embedding)."""
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    return v / np.linalg.norm(v)


def _vettore_simile(base: np.ndarray, rumore: float, seed: int) -> np.ndarray:
    """Genera un vettore vicino a 'base' (simula la stessa persona in un'altra foto)."""
    rng = np.random.default_rng(seed)
    perturbazione = rng.normal(0, rumore, 512).astype(np.float32)
    v = base + perturbazione
    return v / np.linalg.norm(v)


@pytest.fixture
def db_con_due_persone(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    vettore_mario = _vettore_normalizzato(seed=1)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    for i in range(3):
        v = _vettore_simile(vettore_mario, rumore=0.02, seed=100 + i)
        salva_embedding(conn, id_mario, v, f"mario_{i}.jpg", "batch_iniziale")

    vettore_anna = _vettore_normalizzato(seed=2)
    id_anna = trova_o_crea_persona(conn, "Anna Bianchi")
    salva_embedding(conn, id_anna, vettore_anna, "anna_0.jpg", "batch_iniziale")

    yield conn, vettore_mario, vettore_anna
    conn.close()


def test_calcola_candidati_trova_la_persona_giusta_al_primo_posto(db_con_due_persone):
    conn, vettore_mario, _ = db_con_due_persone
    nuovo_volto = _vettore_simile(vettore_mario, rumore=0.02, seed=999)

    candidati = calcola_candidati(nuovo_volto, conn)

    assert candidati[0].nome == "Mario Rossi"
    assert candidati[0].punteggio > 0.8


def test_calcola_candidati_usa_media_dei_migliori_3_embedding(db_con_due_persone):
    conn, vettore_mario, _ = db_con_due_persone
    id_mario_query = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Mario Rossi",)
    ).fetchone()[0]
    # Aggiunge un quarto embedding molto diverso per Mario: la media dei migliori 3
    # deve restare alta (il 4o embedding, peggiore, va escluso dalla media).
    vettore_outlier = _vettore_normalizzato(seed=12345)
    salva_embedding(conn, id_mario_query, vettore_outlier, "mario_outlier.jpg", "manuale")

    nuovo_volto = _vettore_simile(vettore_mario, rumore=0.02, seed=999)
    candidati = calcola_candidati(nuovo_volto, conn)

    mario = next(c for c in candidati if c.nome == "Mario Rossi")
    assert mario.punteggio > 0.8  # la media dei 3 migliori resta alta nonostante l'outlier


def test_calcola_candidati_ritorna_lista_vuota_se_db_vuoto(tmp_path):
    percorso_db = tmp_path / "volti_vuoto.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    candidati = calcola_candidati(_vettore_normalizzato(seed=1), conn)

    conn.close()
    assert candidati == []


def test_classifica_match_certo_sopra_soglia_alta():
    candidati = [Candidato(nome="Mario Rossi", punteggio=0.9, foto_riferimento="x.jpg")]
    assert classifica_match(candidati) == "certo"


def test_classifica_match_ambiguo_tra_le_soglie():
    candidati = [Candidato(nome="Mario Rossi", punteggio=0.35, foto_riferimento="x.jpg")]
    assert classifica_match(candidati) == "ambiguo"


def test_classifica_match_sconosciuto_sotto_soglia_bassa():
    candidati = [Candidato(nome="Mario Rossi", punteggio=0.1, foto_riferimento="x.jpg")]
    assert classifica_match(candidati) == "sconosciuto"


def test_classifica_match_sconosciuto_se_nessun_candidato():
    assert classifica_match([]) == "sconosciuto"
