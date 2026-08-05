import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core.volti import VoltoRilevato
from db.database import connetti, init_db, salva_embedding, trova_o_crea_persona
from scripts.rinomina_batch import _sanitizza_nome, rinomina_da_cartella


def _vettore_normalizzato(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    return v / np.linalg.norm(v)


def _vettore_con_similarita(base: np.ndarray, similarita: float, seed: int) -> np.ndarray:
    """Costruisce un vettore normalizzato con cosine similarity esatta rispetto a base
    (per testare in modo deterministico i confini certo/ambiguo/sconosciuto)."""
    rng = np.random.default_rng(seed)
    casuale = rng.random(512).astype(np.float32)
    ortogonale = casuale - np.dot(casuale, base) * base
    ortogonale = ortogonale / np.linalg.norm(ortogonale)
    vettore = similarita * base + np.sqrt(1 - similarita**2) * ortogonale
    return vettore.astype(np.float32)


def _crea_immagine_prova(percorso: Path, dimensione=(100, 100)) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", dimensione, color="blue").save(percorso)


@pytest.fixture
def db_di_prova(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    return percorso_db


def test_sanitizza_nome_sostituisce_spazi():
    assert _sanitizza_nome("Mario Rossi") == "Mario_Rossi"


def test_sanitizza_nome_rimuove_caratteri_non_validi():
    assert _sanitizza_nome("Mario/Rossi:Test") == "Mario_Rossi_Test"


def test_volto_con_match_certo(db_di_prova, tmp_path, monkeypatch):
    vettore = _vettore_normalizzato(seed=1)
    conn = connetti(db_di_prova)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(conn, id_mario, vettore, "mario_0.jpg", "batch_iniziale")
    conn.close()

    volto_finto = VoltoRilevato(vettore=vettore, bbox=(10, 10, 50, 50), score=0.9)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_finto])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto1.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto1_Mario_Rossi_100.jpg"
    assert riepilogo["certo"] == 1
    assert riepilogo["foto_totali"] == 1


def test_volto_con_match_ambiguo(db_di_prova, tmp_path, monkeypatch):
    base = _vettore_normalizzato(seed=2)
    vettore_query = _vettore_con_similarita(base, 0.38, seed=3)
    conn = connetti(db_di_prova)
    id_anna = trova_o_crea_persona(conn, "Anna Bianchi")
    salva_embedding(conn, id_anna, base, "anna_0.jpg", "batch_iniziale")
    conn.close()

    volto_finto = VoltoRilevato(vettore=vettore_query, bbox=(10, 10, 50, 50), score=0.9)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_finto])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto2.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto2_Anna_Bianchi_38_DA_VERIFICARE.jpg"
    assert riepilogo["ambiguo"] == 1


def test_volto_sconosciuto(db_di_prova, tmp_path, monkeypatch):
    base = _vettore_normalizzato(seed=4)
    vettore_query = _vettore_con_similarita(base, 0.10, seed=5)
    conn = connetti(db_di_prova)
    id_persona = trova_o_crea_persona(conn, "Qualcun Altro")
    salva_embedding(conn, id_persona, base, "altro_0.jpg", "batch_iniziale")
    conn.close()

    volto_finto = VoltoRilevato(vettore=vettore_query, bbox=(10, 10, 50, 50), score=0.9)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_finto])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto3.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto3_sconosciuto.jpg"
    assert riepilogo["sconosciuto"] == 1


def test_nessun_volto_rilevato(db_di_prova, tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto4.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto4_NESSUN_VOLTO.jpg"
    assert riepilogo["nessun_volto"] == 1


def test_due_volti_stessa_foto_segmenti_incatenati(db_di_prova, tmp_path, monkeypatch):
    v1 = _vettore_normalizzato(seed=6)
    v2 = _vettore_normalizzato(seed=7)
    conn = connetti(db_di_prova)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(conn, id_mario, v1, "mario_0.jpg", "batch_iniziale")
    id_anna = trova_o_crea_persona(conn, "Anna Bianchi")
    salva_embedding(conn, id_anna, v2, "anna_0.jpg", "batch_iniziale")
    conn.close()

    volto1 = VoltoRilevato(vettore=v1, bbox=(0, 0, 40, 40), score=0.9)
    volto2 = VoltoRilevato(vettore=v2, bbox=(50, 50, 90, 90), score=0.9)
    monkeypatch.setattr(
        "scripts.rinomina_batch.rileva_volti", lambda percorso: [volto1, volto2]
    )

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto5.jpg")

    rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto5_Mario_Rossi_100_Anna_Bianchi_100.jpg"


def test_struttura_sottocartelle_rispecchiata(db_di_prova, tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "evento1" / "foto6.jpg")

    rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    percorso_atteso = cartella_output / "evento1" / "foto6_NESSUN_VOLTO.jpg"
    assert percorso_atteso.exists()


def test_file_originale_non_toccato(db_di_prova, tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    percorso_originale = cartella_input / "foto7.jpg"
    _crea_immagine_prova(percorso_originale)

    rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    assert percorso_originale.exists()
    assert list(cartella_input.glob("*.jpg")) == [percorso_originale]


def test_immagine_illeggibile_non_blocca_le_altre(db_di_prova, tmp_path, monkeypatch):
    def _rileva_volti_finto(percorso):
        if "corrotta" in str(percorso):
            raise ValueError("immagine non leggibile")
        return []

    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", _rileva_volti_finto)

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "corrotta.jpg")
    _crea_immagine_prova(cartella_input / "normale.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    assert riepilogo["errore_lettura_immagine"] == 1
    assert riepilogo["foto_totali"] == 2
    assert (cartella_output / "normale_NESSUN_VOLTO.jpg").exists()
    assert not list(cartella_output.glob("corrotta*"))


def test_eccezione_non_valueerror_non_blocca_batch(db_di_prova, tmp_path, monkeypatch):
    """Verifica che eccezioni non-ValueError (e.g. da shutil.copy2) non abortono il batch."""

    real_copy2 = shutil.copy2

    def _shutil_copy2_finto(src, dst):
        if "errore" in str(src):
            raise RuntimeError("Errore disco simulato")
        real_copy2(src, dst)

    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])
    monkeypatch.setattr("scripts.rinomina_batch.shutil.copy2", _shutil_copy2_finto)

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "errore.jpg")
    _crea_immagine_prova(cartella_input / "ok.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    assert riepilogo["errore_lettura_immagine"] == 1
    assert riepilogo["foto_totali"] == 2
    assert (cartella_output / "ok_NESSUN_VOLTO.jpg").exists()
    assert not list(cartella_output.glob("errore*"))


def test_eccezione_da_segmento_per_volto_non_blocca_batch(db_di_prova, tmp_path, monkeypatch):
    """Verifica che eccezioni da _segmento_per_volto (e.g. SQLite error da calcola_candidati) non abortono il batch."""

    def _segmento_per_volto_finto(volto, conn):
        raise RuntimeError("Errore SQLite simulato da calcola_candidati")

    volto_finto = VoltoRilevato(vettore=_vettore_normalizzato(seed=10), bbox=(10, 10, 50, 50), score=0.9)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_finto] if "errore" in str(percorso) else [])
    monkeypatch.setattr("scripts.rinomina_batch._segmento_per_volto", _segmento_per_volto_finto)

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "errore.jpg")
    _crea_immagine_prova(cartella_input / "ok.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    assert riepilogo["errore_lettura_immagine"] == 1
    assert riepilogo["foto_totali"] == 2
    assert (cartella_output / "ok_NESSUN_VOLTO.jpg").exists()
    assert not list(cartella_output.glob("errore*"))
