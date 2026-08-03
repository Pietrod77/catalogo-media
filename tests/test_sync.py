import logging
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
    leggi_sync_stato,
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


def test_round_trip_push_poi_pull_non_duplica(nas_live, tmp_path):
    """Bug C1: una conferma fatta offline, inviata al NAS e poi riscaricata,
    non deve tornare indietro come riga nuova. L'uid viaggia con la riga nel
    push, quindi al pull viene riconosciuta come gia' presente anche se il NAS
    ha salvato lo screenshot con un nome file uuid completamente diverso."""
    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)
    id_locale = trova_o_crea_persona(conn_locale, "Persona Round Trip")
    vettore = _vettore_normalizzato(seed=10)
    cartella_screenshot = cartella_sessioni_locale / "conferme"
    cartella_screenshot.mkdir(parents=True)
    file_screenshot = cartella_screenshot / "offline_round_trip.jpg"
    file_screenshot.write_bytes(b"contenuto offline round trip")
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

    scarica_incrementale(conn_locale, nas_live.url_base, cartella_sessioni_locale)

    conteggio = conn_locale.execute("SELECT COUNT(*) FROM embedding").fetchone()[0]
    conn_locale.close()

    assert conteggio == 1


def test_scarica_incrementale_salta_riga_con_uid_gia_presente(nas_live, tmp_path):
    """Il dedup del pull si basa sull'uid, non sul nome del file: una riga gia'
    presente in locale con lo stesso uid non viene reinserita nemmeno se sul NAS
    il suo foto_origine ha un basename diverso."""
    uid_condiviso = "stesso-uid-di-prova"
    vettore = _vettore_normalizzato(seed=11)

    conn_nas = connetti(tmp_path / "nas" / "volti.db")
    id_nas = trova_o_crea_persona(conn_nas, "Persona Condivisa")
    cartella_nas_conferme = tmp_path / "nas" / "sessioni" / "conferme"
    cartella_nas_conferme.mkdir(parents=True, exist_ok=True)
    file_nas = cartella_nas_conferme / "nome_diverso_sul_nas.jpg"
    file_nas.write_bytes(b"contenuto sul nas")
    salva_embedding(
        conn_nas, id_nas, vettore, str(file_nas), "batch_iniziale", uid=uid_condiviso
    )
    conn_nas.close()

    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)
    id_locale = trova_o_crea_persona(conn_locale, "Persona Condivisa")
    salva_embedding(
        conn_locale, id_locale, vettore, "gia_presente.jpg", "batch_iniziale", uid=uid_condiviso
    )

    ricevuti = scarica_incrementale(conn_locale, nas_live.url_base, cartella_sessioni_locale)

    conteggio = conn_locale.execute("SELECT COUNT(*) FROM embedding").fetchone()[0]
    conn_locale.close()

    assert ricevuti == 0
    assert conteggio == 1


def test_scarica_incrementale_conserva_foto_origine_se_manca_screenshot(nas_live, tmp_path):
    """Bug I2: se il NAS non ha i byte della foto (righe storiche con percorsi
    che esistono solo sul Mac di origine), il pull deve conservare il
    foto_origine originale, non inventarne uno locale che non esistera' mai."""
    conn_nas = connetti(tmp_path / "nas" / "volti.db")
    id_nas = trova_o_crea_persona(conn_nas, "Persona Storica")
    vettore = _vettore_normalizzato(seed=12)
    percorso_inesistente = "/Users/altro/Desktop/archivio/foto_storica.jpg"
    salva_embedding(conn_nas, id_nas, vettore, percorso_inesistente, "batch_iniziale")
    conn_nas.close()

    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)

    scarica_incrementale(conn_locale, nas_live.url_base, cartella_sessioni_locale)

    foto_origine = conn_locale.execute("SELECT foto_origine FROM embedding").fetchone()[0]
    conn_locale.close()

    assert foto_origine == percorso_inesistente


def test_scarica_incrementale_riga_malformata_non_blocca_le_altre(tmp_path, monkeypatch, caplog):
    """Bug I5: una riga malformata veniva propagata come eccezione, il segnalino
    non avanzava mai e lo stesso identico blocco veniva ritentato all'infinito.
    Ora la riga viene saltata con log, le altre passano e il segnalino avanza."""

    class RispostaFinta:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "persone": [{"id": 1, "nome": "Persona Buona"}],
                "embedding": [
                    {"id": 1, "nome": "Persona Rotta", "vettore": "non-un-vettore",
                     "foto_origine": "/rotta.jpg", "fonte": "batch_iniziale",
                     "uid": "uid-rotto", "screenshot_base64": None},
                    {"id": 2, "nome": "Persona Buona",
                     "vettore": _vettore_normalizzato(seed=20).tolist(),
                     "foto_origine": "/buona.jpg", "fonte": "batch_iniziale",
                     "uid": "uid-buono", "screenshot_base64": None},
                ],
            }

    monkeypatch.setattr("core.sync.requests.get", lambda *a, **k: RispostaFinta())

    percorso_db_locale = tmp_path / "locale" / "volti.db"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)

    with caplog.at_level(logging.ERROR):
        ricevuti = scarica_incrementale(
            conn_locale, "http://irrilevante", tmp_path / "locale" / "sessioni"
        )

    uid_salvati = [r[0] for r in conn_locale.execute("SELECT uid FROM embedding")]
    stato = leggi_sync_stato(conn_locale)
    conn_locale.close()

    assert ricevuti == 1
    assert uid_salvati == ["uid-buono"]
    # il segnalino ha superato ANCHE la riga rotta: non verra' ritentata all'infinito
    assert stato == (1, 2)
    assert "riga saltata" in caplog.text


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
