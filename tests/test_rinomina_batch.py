import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core.volti import VoltoRilevato
from db.database import connetti, init_db, salva_embedding, trova_o_crea_persona
from scripts.rinomina_batch import _formatta_riepilogo_breve, _sanitizza_nome, main, rinomina_da_cartella


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


def test_volto_area_piccola_trattato_come_nessun_volto(db_di_prova, tmp_path, monkeypatch):
    vettore = _vettore_normalizzato(seed=50)
    conn = connetti(db_di_prova)
    id_persona = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(conn, id_persona, vettore, "mario_0.jpg", "batch_iniziale")
    conn.close()

    # Immagine di prova 100x100 (area 10000). bbox (10,10,12,12) -> area 4,
    # rapporto 4/10000 = 0.04%, ben sotto la soglia RAPPORTO_AREA_MINIMO (0.4%).
    volto_piccolo = VoltoRilevato(vettore=vettore, bbox=(10, 10, 12, 12), score=0.9)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_piccolo])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto_sfocata.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto_sfocata_NESSUN_VOLTO.jpg"
    assert riepilogo["nessun_volto"] == 1
    assert riepilogo["certo"] == 0
    assert riepilogo["scartati_piccoli_sfondo"] == 1


def test_volto_valido_e_volto_scartato_stessa_foto(db_di_prova, tmp_path, monkeypatch):
    v1 = _vettore_normalizzato(seed=60)
    v2 = _vettore_normalizzato(seed=61)
    conn = connetti(db_di_prova)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(conn, id_mario, v1, "mario_0.jpg", "batch_iniziale")
    id_anna = trova_o_crea_persona(conn, "Anna Bianchi")
    salva_embedding(conn, id_anna, v2, "anna_0.jpg", "batch_iniziale")
    conn.close()

    # Immagine di prova 100x100 (area 10000). volto_valido bbox (0,0,40,40) ->
    # area 1600, rapporto 16% (tenuto). volto_scartato bbox (10,10,12,12) ->
    # area 4, rapporto 0.04% (scartato, sotto RAPPORTO_AREA_MINIMO 0.4%).
    volto_valido = VoltoRilevato(vettore=v1, bbox=(0, 0, 40, 40), score=0.9)
    volto_scartato = VoltoRilevato(vettore=v2, bbox=(10, 10, 12, 12), score=0.9)
    monkeypatch.setattr(
        "scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_valido, volto_scartato]
    )

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto_mista.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto_mista_Mario_Rossi_100.jpg"
    assert riepilogo["certo"] == 1
    assert riepilogo["scartati_piccoli_sfondo"] == 1


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

    assert riepilogo["errore_copia"] == 1
    assert riepilogo["errore_lettura_immagine"] == 0
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

    assert riepilogo["errore_riconoscimento"] == 1
    assert riepilogo["errore_lettura_immagine"] == 0
    assert riepilogo["foto_totali"] == 2
    assert (cartella_output / "ok_NESSUN_VOLTO.jpg").exists()
    assert not list(cartella_output.glob("errore*"))


def test_main_fallisce_se_db_mancante(tmp_path, monkeypatch):
    """main() deve fermarsi con errore prima di elaborare qualunque foto se il
    DB di default non esiste, invece di lasciare che connetti() lo crei vuoto
    silenziosamente."""
    cartella_input = tmp_path / "input"
    cartella_input.mkdir()
    cartella_output = tmp_path / "output"
    percorso_db_inesistente = tmp_path / "non_esiste.db"

    monkeypatch.setattr("scripts.rinomina_batch.PERCORSO_DB_DEFAULT", percorso_db_inesistente)

    def _rinomina_da_cartella_non_deve_essere_chiamata(*args, **kwargs):
        pytest.fail("rinomina_da_cartella non deve essere chiamata se il DB manca")

    monkeypatch.setattr(
        "scripts.rinomina_batch.rinomina_da_cartella",
        _rinomina_da_cartella_non_deve_essere_chiamata,
    )
    monkeypatch.setattr(
        sys, "argv", ["rinomina_batch.py", str(cartella_input), str(cartella_output)]
    )

    codice_uscita = main()

    assert codice_uscita == 1
    assert not percorso_db_inesistente.exists()


def test_main_avvisa_se_db_vuoto_ma_procede(tmp_path, monkeypatch, capsys):
    """Un DB esistente ma senza embedding non deve bloccare l'esecuzione, ma deve
    stampare un avviso perché tutte le foto risulteranno sconosciute."""
    percorso_db = tmp_path / "vuoto.db"
    init_db(percorso_db)

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto_a.jpg")

    monkeypatch.setattr("scripts.rinomina_batch.PERCORSO_DB_DEFAULT", percorso_db)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])
    monkeypatch.setattr(
        sys, "argv", ["rinomina_batch.py", str(cartella_input), str(cartella_output)]
    )

    codice_uscita = main()

    catturato = capsys.readouterr()
    assert codice_uscita == 0
    assert "Attenzione" in catturato.out
    assert (cartella_output / "foto_a_NESSUN_VOLTO.jpg").exists()


def test_molti_volti_overflow_nome_file_troncato(db_di_prova, tmp_path, monkeypatch):
    """Una foto con molte facce (es. foto di gruppo) non deve produrre un nome
    file che supera il limite di lunghezza del filesystem: oltre il budget i
    segmenti in eccesso vengono sostituiti da un marcatore _ALTRI_<N>."""
    conn = connetti(db_di_prova)
    volti_finti = []
    for indice in range(20):
        vettore = _vettore_normalizzato(seed=1000 + indice)
        id_persona = trova_o_crea_persona(conn, f"Persona Numero{indice:02d}")
        salva_embedding(conn, id_persona, vettore, f"persona{indice}_0.jpg", "batch_iniziale")
        volti_finti.append(
            VoltoRilevato(vettore=vettore, bbox=(indice, indice, indice + 10, indice + 10), score=0.9)
        )
    conn.close()

    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: volti_finti)

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "gruppo.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    nome_file = file_output[0].name
    assert len(nome_file.encode("utf-8")) <= 200
    assert "_ALTRI_" in nome_file
    assert nome_file.endswith(".jpg")
    # il marcatore deve precedere l'estensione (fine del nome troncato)
    corpo, _, estensione = nome_file.rpartition(".")
    assert corpo.split("_ALTRI_")[-1].isdigit()
    assert riepilogo["certo"] == 20


def test_rerun_pulisce_file_obsoleti_stessa_foto(tmp_path, monkeypatch):
    """Ri-eseguire lo script sulla stessa cartella di output dopo che il DB è
    cambiato non deve lasciare accumulati vecchi file con nomi contraddittori
    per la stessa foto sorgente (es. _sconosciuto rimasto accanto al nuovo
    _Nome_Cognome_NN dopo che la persona è stata aggiunta al DB)."""
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto_multi.jpg")

    vettore = _vettore_normalizzato(seed=2000)
    volto_finto = VoltoRilevato(vettore=vettore, bbox=(10, 10, 50, 50), score=0.9)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_finto])

    # primo run: la persona non è ancora nel DB -> sconosciuto
    rinomina_da_cartella(cartella_input, cartella_output, percorso_db)
    assert (cartella_output / "foto_multi_sconosciuto.jpg").exists()

    # il DB viene aggiornato: la stessa persona ora ha un match certo
    conn = connetti(percorso_db)
    id_persona = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(conn, id_persona, vettore, "mario_0.jpg", "batch_iniziale")
    conn.close()

    # secondo run sulla stessa cartella di output
    rinomina_da_cartella(cartella_input, cartella_output, percorso_db)

    file_output = list(cartella_output.glob("foto_multi_*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto_multi_Mario_Rossi_100.jpg"


def test_pulizia_non_cancella_output_di_foto_con_stem_simile(tmp_path, monkeypatch):
    """Bug: la pulizia dei doppioni prima di copiare IMG_1234.jpg usava il glob
    f"{foto.stem}_*{foto.suffix}", che cattura anche l'output di IMG_1234_2.jpg
    (il cui nome inizia comunque con "IMG_1234_") e lo cancellava per errore,
    anche se appartiene a una foto sorgente diversa e non correlata.

    In un run senza errori il problema si "autoguarisce" (IMG_1234_2.jpg viene
    comunque rielaborata più avanti nello stesso run e il suo output ricreato),
    quindi per dimostrare la perdita di dati permanente qui si simula un
    errore di copia per IMG_1234_2.jpg nel secondo run: il suo output
    precedente (valido) deve sopravvivere alla pulizia fatta durante
    l'elaborazione di IMG_1234.jpg, che la precede in ordine alfabetico."""
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "IMG_1234.jpg")
    _crea_immagine_prova(cartella_input / "IMG_1234_2.jpg")

    # primo run: un volto viene rilevato in entrambe le foto ma il DB è vuoto
    # -> nessun candidato possibile, quindi entrambe risultano sconosciute
    # (non "NESSUN_VOLTO", che richiederebbe nessun volto rilevato)
    volto_sconosciuto_1234 = VoltoRilevato(
        vettore=_vettore_normalizzato(seed=2900), bbox=(10, 10, 50, 50), score=0.9
    )
    volto_sconosciuto_1234_2 = VoltoRilevato(
        vettore=_vettore_normalizzato(seed=2901), bbox=(10, 10, 50, 50), score=0.9
    )

    def _rileva_volti_primo_run(percorso):
        if percorso.name == "IMG_1234.jpg":
            return [volto_sconosciuto_1234]
        return [volto_sconosciuto_1234_2]

    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", _rileva_volti_primo_run)
    rinomina_da_cartella(cartella_input, cartella_output, percorso_db)
    assert (cartella_output / "IMG_1234_sconosciuto.jpg").exists()
    assert (cartella_output / "IMG_1234_2_sconosciuto.jpg").exists()

    # il DB viene aggiornato: ora IMG_1234.jpg ha un match certo
    vettore = _vettore_normalizzato(seed=3000)
    conn = connetti(percorso_db)
    id_persona = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(conn, id_persona, vettore, "mario_0.jpg", "batch_iniziale")
    conn.close()

    volto_finto = VoltoRilevato(vettore=vettore, bbox=(10, 10, 50, 50), score=0.9)

    def _rileva_volti_finto(percorso):
        if percorso.name == "IMG_1234.jpg":
            return [volto_finto]
        return []

    real_copy2 = shutil.copy2

    def _copy2_finto(src, dst):
        # la ricopia di IMG_1234_2.jpg fallisce in questo run: se la pulizia
        # avesse già cancellato indebitamente il suo output precedente, la
        # perdita sarebbe permanente e silenziosa
        if Path(src).name == "IMG_1234_2.jpg":
            raise RuntimeError("Errore disco simulato")
        real_copy2(src, dst)

    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", _rileva_volti_finto)
    monkeypatch.setattr("scripts.rinomina_batch.shutil.copy2", _copy2_finto)

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, percorso_db)

    assert riepilogo["errore_copia"] == 1
    assert (cartella_output / "IMG_1234_Mario_Rossi_100.jpg").exists()
    # l'output precedente di IMG_1234_2.jpg non deve essere stato cancellato
    # dalla pulizia dei doppioni fatta durante l'elaborazione di IMG_1234.jpg
    assert (cartella_output / "IMG_1234_2_sconosciuto.jpg").exists()


def test_formatta_riepilogo_breve_conteggi_base():
    riepilogo = {
        "foto_totali": 150,
        "certo": 78,
        "ambiguo": 14,
        "sconosciuto": 40,
        "nessun_volto": 18,
        "scartati_piccoli_sfondo": 5,
        "errore_lettura_immagine": 0,
        "errore_riconoscimento": 0,
        "errore_copia": 0,
    }
    testo = _formatta_riepilogo_breve(riepilogo)
    assert testo == (
        "150 foto — 92 nomi trovati (78 certi, 14 da verificare), "
        "40 sconosciuti, 18 senza volto a fuoco"
    )
    assert "150 foto" in testo
    assert "92 nomi trovati (78 certi, 14 da verificare)" in testo
    assert "40 sconosciuti" in testo
    assert "18 senza volto a fuoco" in testo
    assert "errori" not in testo


def test_formatta_riepilogo_breve_include_riga_errori_se_presenti():
    riepilogo = {
        "foto_totali": 10,
        "certo": 5,
        "ambiguo": 0,
        "sconosciuto": 3,
        "nessun_volto": 1,
        "scartati_piccoli_sfondo": 0,
        "errore_lettura_immagine": 2,
        "errore_riconoscimento": 0,
        "errore_copia": 0,
    }
    testo = _formatta_riepilogo_breve(riepilogo)
    assert "2 errori (dettagli in terminale)" in testo


def test_formatta_riepilogo_breve_singolare_con_conteggi_a_uno():
    """Verifica che le parole flesse (nome/nomi, certo/certi,
    sconosciuto/sconosciuti, errore/errori) usino la forma singolare corretta
    quando il conteggio è 1 — "foto" non si flette e "senza volto a fuoco"
    non è interessato da questa correzione."""
    riepilogo_nome_singolare = {
        "foto_totali": 1,
        "certo": 1,
        "ambiguo": 0,
        "sconosciuto": 0,
        "nessun_volto": 0,
        "scartati_piccoli_sfondo": 0,
        "errore_lettura_immagine": 0,
        "errore_riconoscimento": 0,
        "errore_copia": 0,
    }
    testo = _formatta_riepilogo_breve(riepilogo_nome_singolare)
    assert "1 nome trovato (1 certo, 0 da verificare)" in testo

    riepilogo_sconosciuto_singolare = {
        "foto_totali": 1,
        "certo": 0,
        "ambiguo": 0,
        "sconosciuto": 1,
        "nessun_volto": 0,
        "scartati_piccoli_sfondo": 0,
        "errore_lettura_immagine": 0,
        "errore_riconoscimento": 0,
        "errore_copia": 0,
    }
    testo = _formatta_riepilogo_breve(riepilogo_sconosciuto_singolare)
    assert "1 sconosciuto" in testo

    riepilogo_errore_singolare = {
        "foto_totali": 1,
        "certo": 0,
        "ambiguo": 0,
        "sconosciuto": 0,
        "nessun_volto": 0,
        "scartati_piccoli_sfondo": 0,
        "errore_lettura_immagine": 1,
        "errore_riconoscimento": 0,
        "errore_copia": 0,
    }
    testo = _formatta_riepilogo_breve(riepilogo_errore_singolare)
    assert "1 errore (dettagli in terminale)" in testo


def test_output_per_foto_va_su_stderr_non_stdout(db_di_prova, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])
    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto_x.jpg")

    rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    catturato = capsys.readouterr()
    assert catturato.out == ""
    assert "foto_x_NESSUN_VOLTO.jpg" in catturato.err


def test_main_stampa_solo_riepilogo_breve_su_stdout(db_di_prova, tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rinomina_batch.PERCORSO_DB_DEFAULT", db_di_prova)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto_y.jpg")

    monkeypatch.setattr(
        sys, "argv", ["rinomina_batch.py", str(cartella_input), str(cartella_output)]
    )

    import io
    import contextlib

    buffer_out = io.StringIO()
    with contextlib.redirect_stdout(buffer_out):
        codice_uscita = main()

    assert codice_uscita == 0
    testo_stdout = buffer_out.getvalue()
    assert "1 foto" in testo_stdout
    assert "senza volto a fuoco" in testo_stdout
    assert "foto_y_NESSUN_VOLTO.jpg" not in testo_stdout
