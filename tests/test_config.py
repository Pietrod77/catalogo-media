from pathlib import Path

from config import percorso_consentito


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
