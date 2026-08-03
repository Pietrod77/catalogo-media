import threading
import time

import numpy as np
import pytest
from werkzeug.serving import make_server

from app import crea_app
from core.sync import (
    esegui_ciclo_sync,
    invia_pendenti,
    nas_raggiungibile,
    scarica_incrementale,
)
from db.database import (
    connetti,
    embedding_da_sincronizzare,
    init_db,
    salva_embedding,
    trova_o_crea_persona,
)


class ServerNasDiProva:
    def __init__(self, app):
        self._server = make_server("127.0.0.1", 0, app)
        self.porta = self._server.server_port
        self.url_base = f"http://127.0.0.1:{self.porta}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def avvia(self):
        self._thread.start()

    def ferma(self):
        self._server.shutdown()
        self._thread.join(timeout=2)


@pytest.fixture
def nas_live(tmp_path):
    app_nas = crea_app(
        percorso_db=tmp_path / "nas" / "volti.db",
        cartella_sessioni=tmp_path / "nas" / "sessioni",
    )
    server = ServerNasDiProva(app_nas)
    server.avvia()
    for _ in range(50):
        if nas_raggiungibile(server.url_base):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Server NAS di prova non si e' avviato in tempo")
    yield server
    server.ferma()


def _vettore_normalizzato(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    return v / np.linalg.norm(v)


def test_nas_raggiungibile_true_quando_nas_attivo(nas_live):
    assert nas_raggiungibile(nas_live.url_base) is True


def test_nas_raggiungibile_false_per_indirizzo_inesistente():
    assert nas_raggiungibile("http://127.0.0.1:1") is False


def test_invia_pendenti_invia_e_marca_sincronizzata(nas_live, tmp_path):
    percorso_db_locale = tmp_path / "locale" / "volti.db"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)
    id_locale = trova_o_crea_persona(conn_locale, "Persona Offline")
    vettore = _vettore_normalizzato(seed=1)
    cartella_screenshot = tmp_path / "locale" / "sessioni" / "conferme"
    cartella_screenshot.mkdir(parents=True)
    file_screenshot = cartella_screenshot / "test.jpg"
    file_screenshot.write_bytes(b"contenuto finto jpg")
    salva_embedding(
        conn_locale,
        id_locale,
        vettore,
        str(file_screenshot),
        "conferma_editing",
        sincronizzato=False,
    )

    inviati = invia_pendenti(conn_locale, nas_live.url_base)

    assert inviati == 1
    assert embedding_da_sincronizzare(conn_locale) == []
    conn_locale.close()

    conn_nas = connetti(tmp_path / "nas" / "volti.db")
    riga_nas = conn_nas.execute(
        "SELECT nome FROM persone WHERE nome = ?", ("Persona Offline",)
    ).fetchone()
    conn_nas.close()
    assert riga_nas is not None


def test_invia_pendenti_salta_riga_senza_file_screenshot(nas_live, tmp_path):
    percorso_db_locale = tmp_path / "locale" / "volti.db"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)
    id_locale = trova_o_crea_persona(conn_locale, "Persona Senza File")
    vettore = _vettore_normalizzato(seed=2)
    salva_embedding(
        conn_locale,
        id_locale,
        vettore,
        str(tmp_path / "non_esiste.jpg"),
        "conferma_editing",
        sincronizzato=False,
    )

    inviati = invia_pendenti(conn_locale, nas_live.url_base)
    conn_locale.close()

    assert inviati == 0


def test_scarica_incrementale_pull_persone_ed_embedding(nas_live, tmp_path):
    conn_nas = connetti(tmp_path / "nas" / "volti.db")
    id_nas = trova_o_crea_persona(conn_nas, "Persona Sul Nas")
    vettore = _vettore_normalizzato(seed=3)
    cartella_nas_conferme = tmp_path / "nas" / "sessioni" / "conferme"
    cartella_nas_conferme.mkdir(parents=True, exist_ok=True)
    file_nas = cartella_nas_conferme / "originale.jpg"
    file_nas.write_bytes(b"contenuto reale nas")
    salva_embedding(conn_nas, id_nas, vettore, str(file_nas), "batch_iniziale")
    conn_nas.close()

    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)

    ricevuti = scarica_incrementale(conn_locale, nas_live.url_base, cartella_sessioni_locale)

    riga = conn_locale.execute(
        "SELECT p.nome FROM embedding e JOIN persone p ON p.id = e.person_id"
    ).fetchone()
    conn_locale.close()

    assert ricevuti == 1
    assert riga[0] == "Persona Sul Nas"
    assert (cartella_sessioni_locale / "conferme" / "originale.jpg").read_bytes() == (
        b"contenuto reale nas"
    )


def test_scarica_incrementale_non_duplica_se_richiamata_due_volte(nas_live, tmp_path):
    conn_nas = connetti(tmp_path / "nas" / "volti.db")
    id_nas = trova_o_crea_persona(conn_nas, "Persona Sul Nas")
    vettore = _vettore_normalizzato(seed=4)
    cartella_nas_conferme = tmp_path / "nas" / "sessioni" / "conferme"
    cartella_nas_conferme.mkdir(parents=True, exist_ok=True)
    file_nas = cartella_nas_conferme / "originale.jpg"
    file_nas.write_bytes(b"contenuto reale nas")
    salva_embedding(conn_nas, id_nas, vettore, str(file_nas), "batch_iniziale")
    conn_nas.close()

    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)

    scarica_incrementale(conn_locale, nas_live.url_base, cartella_sessioni_locale)
    scarica_incrementale(conn_locale, nas_live.url_base, cartella_sessioni_locale)

    conteggio = conn_locale.execute("SELECT COUNT(*) FROM embedding").fetchone()[0]
    conn_locale.close()

    assert conteggio == 1


def test_esegui_ciclo_sync_non_raggiungibile_non_solleva_errori(tmp_path):
    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)

    risultato = esegui_ciclo_sync(
        percorso_db_locale, cartella_sessioni_locale, "http://127.0.0.1:1"
    )

    assert risultato == {"raggiungibile": False, "inviati": 0, "ricevuti": 0}


def test_esegui_ciclo_sync_completo_invia_e_riceve(nas_live, tmp_path):
    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)
    id_locale = trova_o_crea_persona(conn_locale, "Persona Offline Due")
    vettore = _vettore_normalizzato(seed=5)
    cartella_screenshot = cartella_sessioni_locale / "conferme"
    cartella_screenshot.mkdir(parents=True)
    file_screenshot = cartella_screenshot / "offline.jpg"
    file_screenshot.write_bytes(b"contenuto offline")
    salva_embedding(
        conn_locale,
        id_locale,
        vettore,
        str(file_screenshot),
        "conferma_editing",
        sincronizzato=False,
    )
    conn_locale.close()

    risultato = esegui_ciclo_sync(percorso_db_locale, cartella_sessioni_locale, nas_live.url_base)

    assert risultato["raggiungibile"] is True
    assert risultato["inviati"] == 1
