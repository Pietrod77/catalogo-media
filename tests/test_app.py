import base64
import uuid
from pathlib import Path

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


def test_index_senza_profilo_mostra_titolo_generico(client):
    risposta = client.get("/")
    assert b"Riconoscimento volti</h1>" in risposta.data


def test_index_con_profilo_modelle_mostra_il_nome(tmp_path):
    app_modelle = crea_app(
        percorso_db=tmp_path / "volti_test.db",
        cartella_sessioni=tmp_path / "sessioni",
        nome_profilo="modelle",
    )
    client_modelle = app_modelle.test_client()

    risposta = client_modelle.get("/")

    assert b"Modelle" in risposta.data


def test_index_con_profilo_personaggi_mostra_il_nome(tmp_path):
    app_personaggi = crea_app(
        percorso_db=tmp_path / "volti_test.db",
        cartella_sessioni=tmp_path / "sessioni",
        nome_profilo="personaggi",
    )
    client_personaggi = app_personaggi.test_client()

    risposta = client_personaggi.get("/")

    assert b"Personaggi" in risposta.data


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


def test_analizza_include_score_nel_risultato(client, tmp_path, monkeypatch):
    vettore = _vettore_normalizzato(seed=20)
    volto_finto = VoltoRilevato(vettore=vettore, bbox=(10, 10, 50, 50), score=0.83)
    monkeypatch.setattr("app.rileva_volti", lambda percorso: [volto_finto])

    percorso_immagine = tmp_path / "screenshot.jpg"
    _crea_immagine_prova(percorso_immagine)

    with open(percorso_immagine, "rb") as f:
        risposta = client.post("/analizza", data={"immagine": (f, "screenshot.jpg")})

    dati = risposta.get_json()
    assert dati["volti"][0]["score"] == pytest.approx(0.83)


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


def test_conferma_nome_nuovo_crea_persona_ed_embedding(app, client):
    vettore = _vettore_normalizzato(seed=7).tolist()
    screenshot_b64 = base64.b64encode(b"contenuto finto jpg").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={
            "nome": "Nuova Persona",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )

    assert risposta.status_code == 200
    assert risposta.get_json()["ok"] is True

    conn = connetti(app.config["PERCORSO_DB"])
    riga_persona = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Nuova Persona",)
    ).fetchone()
    assert riga_persona is not None
    riga_embedding = conn.execute(
        "SELECT foto_origine, fonte FROM embedding WHERE person_id = ?",
        (riga_persona[0],),
    ).fetchone()
    conn.close()

    assert riga_embedding[1] == "conferma_editing"
    assert Path(riga_embedding[0]).exists()


def test_conferma_nome_esistente_non_duplica_persona(app, client):
    conn = connetti(app.config["PERCORSO_DB"])
    id_esistente = trova_o_crea_persona(conn, "Mario Rossi")
    conn.close()

    vettore = _vettore_normalizzato(seed=8).tolist()
    screenshot_b64 = base64.b64encode(b"contenuto finto jpg").decode("ascii")

    client.post(
        "/conferma",
        json={
            "nome": "Mario Rossi",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )

    conn = connetti(app.config["PERCORSO_DB"])
    persone = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Mario Rossi",)
    ).fetchall()
    embedding_rows = conn.execute(
        "SELECT id FROM embedding WHERE person_id = ?", (id_esistente,)
    ).fetchall()
    conn.close()

    assert len(persone) == 1
    assert len(embedding_rows) == 1


def test_conferma_nome_vuoto_ritorna_400(client):
    vettore = _vettore_normalizzato(seed=9).tolist()
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={"nome": "   ", "vettore": vettore, "screenshot_base64": screenshot_b64},
    )

    assert risposta.status_code == 400


def test_conferma_vettore_lunghezza_sbagliata_ritorna_400(app, client):
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={
            "nome": "Persona Vettore Corto",
            "vettore": [0.1, 0.2, 0.3],
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )

    assert risposta.status_code == 400
    conn = connetti(app.config["PERCORSO_DB"])
    riga = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Persona Vettore Corto",)
    ).fetchone()
    conn.close()
    assert riga is None


def test_conferma_vettore_con_valori_non_finiti_ritorna_400(client):
    vettore = _vettore_normalizzato(seed=10).tolist()
    vettore[0] = float("nan")
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={
            "nome": "Persona Vettore Nan",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )

    assert risposta.status_code == 400


def test_conferma_score_assente_ritorna_400(client):
    vettore = _vettore_normalizzato(seed=30).tolist()
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={
            "nome": "Persona Senza Score",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
        },
    )

    assert risposta.status_code == 400


def test_conferma_score_basso_ritorna_400(app, client):
    vettore = _vettore_normalizzato(seed=31).tolist()
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={
            "nome": "Persona Score Basso",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.3,
        },
    )

    assert risposta.status_code == 400
    conn = connetti(app.config["PERCORSO_DB"])
    riga = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Persona Score Basso",)
    ).fetchone()
    conn.close()
    assert riga is None


def test_conferma_score_sufficiente_salva_normalmente(app, client):
    vettore = _vettore_normalizzato(seed=32).tolist()
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={
            "nome": "Persona Score Alto",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )

    assert risposta.status_code == 200
    conn = connetti(app.config["PERCORSO_DB"])
    riga = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Persona Score Alto",)
    ).fetchone()
    conn.close()
    assert riga is not None


def test_riferimento_serve_file_in_cartella_consentita(app, client):
    cartella_conferme = app.config["CARTELLA_SESSIONI"] / "conferme"
    cartella_conferme.mkdir(parents=True)
    percorso_file = cartella_conferme / "riferimento.jpg"
    _crea_immagine_prova(percorso_file)

    risposta = client.get(f"/riferimento?path={percorso_file}")

    assert risposta.status_code == 200
    assert len(risposta.data) > 0


def test_riferimento_403_se_fuori_cartelle_consentite(client, tmp_path):
    cartella_esterna = tmp_path / "fuori"
    cartella_esterna.mkdir()
    percorso_file = cartella_esterna / "riferimento.jpg"
    _crea_immagine_prova(percorso_file)

    risposta = client.get(f"/riferimento?path={percorso_file}")

    assert risposta.status_code == 403


def test_riferimento_404_se_file_non_esiste(app, client):
    cartella_conferme = app.config["CARTELLA_SESSIONI"] / "conferme"
    cartella_conferme.mkdir(parents=True)
    percorso_inesistente = cartella_conferme / "non_esiste.jpg"

    risposta = client.get(f"/riferimento?path={percorso_inesistente}")

    assert risposta.status_code == 404


def test_riferimento_400_se_path_mancante(client):
    risposta = client.get("/riferimento")
    assert risposta.status_code == 400


def test_index_usa_colore_sfondo_di_default(client):
    risposta = client.get("/")
    assert b"#ffffff" in risposta.data


def test_index_usa_colore_sfondo_personalizzato(tmp_path):
    app_personalizzata = crea_app(
        percorso_db=tmp_path / "volti_test.db",
        cartella_sessioni=tmp_path / "sessioni",
        colore_sfondo="#ffe4e1",
    )
    client_personalizzato = app_personalizzata.test_client()

    risposta = client_personalizzato.get("/")

    assert b"#ffe4e1" in risposta.data


def test_index_mostra_conferme_in_sospeso(app, client):
    conn = connetti(app.config["PERCORSO_DB"])
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = _vettore_normalizzato(seed=41)
    salva_embedding(conn, id_mario, vettore, "foto.jpg", "conferma_editing", sincronizzato=False)
    conn.close()

    risposta = client.get("/")

    assert b"1 conferme in attesa di sync" in risposta.data


def test_index_non_mostra_indicatore_se_tutto_sincronizzato(client):
    risposta = client.get("/")
    assert b"conferme in attesa di sync" not in risposta.data


def test_conferma_con_nas_url_configurato_marca_non_sincronizzato(tmp_path):
    app_locale = crea_app(
        percorso_db=tmp_path / "volti_test.db",
        cartella_sessioni=tmp_path / "sessioni",
        nas_url="http://nas-di-prova.invalid:5002",
    )
    client_locale = app_locale.test_client()
    vettore = _vettore_normalizzato(seed=50).tolist()
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    client_locale.post(
        "/conferma",
        json={
            "nome": "Persona Offline",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )

    conn = connetti(app_locale.config["PERCORSO_DB"])
    riga = conn.execute(
        "SELECT sincronizzato FROM embedding e JOIN persone p ON p.id = e.person_id "
        "WHERE p.nome = ?",
        ("Persona Offline",),
    ).fetchone()
    conn.close()
    assert riga[0] == 0


def test_sync_esporta_ritorna_persone_ed_embedding_nuovi(app, client):
    conn = connetti(app.config["PERCORSO_DB"])
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = _vettore_normalizzato(seed=60)
    cartella_conferme = app.config["CARTELLA_SESSIONI"] / "conferme"
    cartella_conferme.mkdir(parents=True, exist_ok=True)
    file_foto = cartella_conferme / "test.jpg"
    file_foto.write_bytes(b"contenuto finto jpg")
    salva_embedding(conn, id_mario, vettore, str(file_foto), "conferma_editing")
    conn.close()

    risposta = client.get("/sync/esporta")
    dati = risposta.get_json()

    assert risposta.status_code == 200
    assert any(p["nome"] == "Mario Rossi" for p in dati["persone"])
    assert len(dati["embedding"]) == 1
    assert dati["embedding"][0]["nome"] == "Mario Rossi"
    assert dati["embedding"][0]["screenshot_base64"] is not None


def test_sync_esporta_rispetta_dopo_persona(app, client):
    conn = connetti(app.config["PERCORSO_DB"])
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    conn.close()

    risposta = client.get(f"/sync/esporta?dopo_persona={id_mario}")

    assert risposta.get_json()["persone"] == []
