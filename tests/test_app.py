import numpy as np
import pytest
from PIL import Image

from app import crea_app
from core.volti import VoltoRilevato
from db.database import connetti, trova_o_crea_persona, salva_embedding


@pytest.fixture
def app(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    cartella_sessioni = tmp_path / "sessioni"
    return crea_app(percorso_db=percorso_db, cartella_sessioni=cartella_sessioni)


@pytest.fixture
def client(app):
    return app.test_client()


def test_index_restituisce_200(client):
    risposta = client.get("/")
    assert risposta.status_code == 200


def test_index_include_zona_drop(client):
    risposta = client.get("/")
    assert b'id="zona-drop"' in risposta.data


def test_index_include_nomi_esistenti(app, client):
    conn = connetti(app.config["PERCORSO_DB"])
    trova_o_crea_persona(conn, "Mario Rossi")
    conn.close()

    risposta = client.get("/")

    assert b"Mario Rossi" in risposta.data


def _vettore_normalizzato(seed: int) -> np.ndarray:
    """Genera un vettore casuale riproducibile e normalizzato L2 (come un vero embedding)."""
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    return v / np.linalg.norm(v)


def _crea_immagine_prova(percorso, dimensione=(100, 100)):
    Image.new("RGB", dimensione, color="blue").save(percorso)


def test_analizza_nessun_volto(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.rileva_volti", lambda percorso: [])
    percorso_immagine = tmp_path / "screenshot.jpg"
    _crea_immagine_prova(percorso_immagine)

    with open(percorso_immagine, "rb") as f:
        risposta = client.post("/analizza", data={"immagine": (f, "screenshot.jpg")})

    assert risposta.status_code == 200
    assert risposta.get_json()["volti"] == []


def test_analizza_un_volto_certo(app, client, tmp_path, monkeypatch):
    conn = connetti(app.config["PERCORSO_DB"])
    vettore = _vettore_normalizzato(seed=1)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    for i in range(3):
        salva_embedding(conn, id_mario, vettore, f"mario_{i}.jpg", "batch_iniziale")
    conn.close()

    volto_finto = VoltoRilevato(vettore=vettore, bbox=(10, 10, 50, 50), score=0.9)
    monkeypatch.setattr("app.rileva_volti", lambda percorso: [volto_finto])

    percorso_immagine = tmp_path / "screenshot.jpg"
    _crea_immagine_prova(percorso_immagine)

    with open(percorso_immagine, "rb") as f:
        risposta = client.post("/analizza", data={"immagine": (f, "screenshot.jpg")})

    dati = risposta.get_json()
    assert len(dati["volti"]) == 1
    volto = dati["volti"][0]
    assert volto["stato"] == "certo"
    assert volto["candidati"][0]["nome"] == "Mario Rossi"
    assert len(volto["vettore"]) == 512


def test_analizza_piu_volti(client, tmp_path, monkeypatch):
    v1 = _vettore_normalizzato(seed=1)
    v2 = _vettore_normalizzato(seed=2)
    monkeypatch.setattr(
        "app.rileva_volti",
        lambda percorso: [
            VoltoRilevato(vettore=v1, bbox=(0, 0, 40, 40), score=0.9),
            VoltoRilevato(vettore=v2, bbox=(50, 50, 90, 90), score=0.9),
        ],
    )
    percorso_immagine = tmp_path / "screenshot.jpg"
    _crea_immagine_prova(percorso_immagine)

    with open(percorso_immagine, "rb") as f:
        risposta = client.post("/analizza", data={"immagine": (f, "screenshot.jpg")})

    assert len(risposta.get_json()["volti"]) == 2


def test_analizza_immagine_non_leggibile(client, tmp_path, monkeypatch):
    def _solleva_valueerror(percorso):
        raise ValueError("immagine non leggibile")

    monkeypatch.setattr("app.rileva_volti", _solleva_valueerror)
    percorso_immagine = tmp_path / "screenshot.jpg"
    _crea_immagine_prova(percorso_immagine)

    with open(percorso_immagine, "rb") as f:
        risposta = client.post("/analizza", data={"immagine": (f, "screenshot.jpg")})

    assert risposta.status_code == 400


def test_analizza_nessun_file_inviato(client):
    risposta = client.post("/analizza", data={})
    assert risposta.status_code == 400
