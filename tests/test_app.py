import pytest

from app import crea_app
from db.database import connetti, trova_o_crea_persona


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
