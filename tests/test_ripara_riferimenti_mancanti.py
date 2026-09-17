import numpy as np

from db.database import connetti, init_db, salva_embedding, trova_o_crea_persona
from scripts.ripara_riferimenti_mancanti import ripara


def _vettore_normalizzato(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    return v / np.linalg.norm(v)


def test_ripara_trova_e_ricopia_file_con_stesso_nome(tmp_path):
    percorso_db = tmp_path / "volti.db"
    init_db(percorso_db)
    cartella_ricerca = tmp_path / "ricerca"
    cartella_ricerca.mkdir()
    file_vero = cartella_ricerca / "foto1.jpg"
    file_vero.write_bytes(b"contenuto vero")
    cartella_destinazione = tmp_path / "destinazione"

    conn = connetti(percorso_db)
    id_persona = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(
        conn, id_persona, _vettore_normalizzato(1), "/percorso/non/esiste/foto1.jpg", "conferma_editing"
    )
    conn.close()

    conn = connetti(percorso_db)
    risultato = ripara(conn, cartella_ricerca, cartella_destinazione)

    assert risultato == {"riparati": 1, "non_trovati": 0, "gia_ok": 0}
    nuovo_percorso = conn.execute("SELECT foto_origine FROM embedding").fetchone()[0]
    conn.close()
    assert nuovo_percorso == str(cartella_destinazione / "foto1.jpg")
    assert (cartella_destinazione / "foto1.jpg").read_bytes() == b"contenuto vero"


def test_ripara_non_tocca_righe_gia_a_posto(tmp_path):
    percorso_db = tmp_path / "volti.db"
    init_db(percorso_db)
    cartella_ricerca = tmp_path / "ricerca"
    cartella_ricerca.mkdir()
    cartella_destinazione = tmp_path / "destinazione"
    cartella_destinazione.mkdir()
    foto_esistente = cartella_destinazione / "gia_ok.jpg"
    foto_esistente.write_bytes(b"gia' presente")

    conn = connetti(percorso_db)
    id_persona = trova_o_crea_persona(conn, "Anna Bianchi")
    salva_embedding(
        conn, id_persona, _vettore_normalizzato(2), str(foto_esistente), "conferma_editing"
    )
    conn.close()

    conn = connetti(percorso_db)
    risultato = ripara(conn, cartella_ricerca, cartella_destinazione)

    assert risultato == {"riparati": 0, "non_trovati": 0, "gia_ok": 1}
    conn.close()


def test_ripara_segnala_non_trovati_senza_fallire(tmp_path):
    percorso_db = tmp_path / "volti.db"
    init_db(percorso_db)
    cartella_ricerca = tmp_path / "ricerca"
    cartella_ricerca.mkdir()
    cartella_destinazione = tmp_path / "destinazione"

    conn = connetti(percorso_db)
    id_persona = trova_o_crea_persona(conn, "Qualcuno")
    salva_embedding(
        conn, id_persona, _vettore_normalizzato(3), "/percorso/perso/introvabile.jpg", "batch_iniziale"
    )
    conn.close()

    conn = connetti(percorso_db)
    risultato = ripara(conn, cartella_ricerca, cartella_destinazione)

    assert risultato == {"riparati": 0, "non_trovati": 1, "gia_ok": 0}
    percorso_invariato = conn.execute("SELECT foto_origine FROM embedding").fetchone()[0]
    conn.close()
    assert percorso_invariato == "/percorso/perso/introvabile.jpg"


def test_ripara_cerca_ricorsivamente_in_sottocartelle(tmp_path):
    percorso_db = tmp_path / "volti.db"
    init_db(percorso_db)
    cartella_ricerca = tmp_path / "ricerca"
    sottocartella = cartella_ricerca / "sessioni" / "modelle" / "conferme"
    sottocartella.mkdir(parents=True)
    file_vero = sottocartella / "foto_annidata.jpg"
    file_vero.write_bytes(b"contenuto annidato")
    cartella_destinazione = tmp_path / "destinazione"

    conn = connetti(percorso_db)
    id_persona = trova_o_crea_persona(conn, "Nome Test")
    salva_embedding(
        conn,
        id_persona,
        _vettore_normalizzato(4),
        "/vecchio/percorso/foto_annidata.jpg",
        "conferma_editing",
    )
    conn.close()

    conn = connetti(percorso_db)
    risultato = ripara(conn, cartella_ricerca, cartella_destinazione)
    conn.close()

    assert risultato == {"riparati": 1, "non_trovati": 0, "gia_ok": 0}
