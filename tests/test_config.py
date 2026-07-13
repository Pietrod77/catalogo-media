import pytest
from pathlib import Path

from config import PROFILI, percorso_consentito, risolvi_profilo


def test_percorso_consentito_dentro_cartella_permessa(tmp_path):
    cartella = tmp_path / "sessioni"
    cartella.mkdir()
    file_dentro = cartella / "foto.jpg"
    file_dentro.write_bytes(b"x")

    assert percorso_consentito(file_dentro, [cartella]) is True


def test_percorso_consentito_fuori_cartella_permessa(tmp_path):
    cartella_permessa = tmp_path / "sessioni"
    cartella_permessa.mkdir()
    cartella_esterna = tmp_path / "altrove"
    cartella_esterna.mkdir()
    file_esterno = cartella_esterna / "foto.jpg"
    file_esterno.write_bytes(b"x")

    assert percorso_consentito(file_esterno, [cartella_permessa]) is False


def test_percorso_consentito_sottocartella_permessa(tmp_path):
    cartella_permessa = tmp_path / "sessioni"
    sottocartella = cartella_permessa / "conferme"
    sottocartella.mkdir(parents=True)
    file_dentro = sottocartella / "foto.jpg"
    file_dentro.write_bytes(b"x")

    assert percorso_consentito(file_dentro, [cartella_permessa]) is True


def test_profili_modelle_ha_i_campi_attesi():
    profilo = PROFILI["modelle"]
    assert isinstance(profilo["db"], Path)
    assert isinstance(profilo["sessioni"], Path)
    assert profilo["porta"] == 5001
    assert profilo["colore"] == "#ffe4e1"


def test_profili_personaggi_punta_al_db_esistente():
    from config import PERCORSO_DB_DEFAULT

    profilo = PROFILI["personaggi"]
    assert profilo["db"] == PERCORSO_DB_DEFAULT
    assert profilo["porta"] == 5002
    assert profilo["colore"] == "#b0e0e6"


def test_profili_modelle_e_personaggi_hanno_sessioni_diverse():
    assert PROFILI["modelle"]["sessioni"] != PROFILI["personaggi"]["sessioni"]


def test_risolvi_profilo_ritorna_il_profilo_richiesto():
    assert risolvi_profilo("modelle") == PROFILI["modelle"]
    assert risolvi_profilo("personaggi") == PROFILI["personaggi"]


def test_risolvi_profilo_nome_sconosciuto_solleva_valueerror():
    with pytest.raises(ValueError):
        risolvi_profilo("altro")
