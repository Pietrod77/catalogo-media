import pytest

from core.volti import rileva_volti


def test_rileva_volti_solleva_errore_se_file_non_esiste(tmp_path):
    percorso_inesistente = tmp_path / "non_esiste.jpg"

    with pytest.raises(FileNotFoundError):
        rileva_volti(percorso_inesistente)


def test_rileva_volti_solleva_errore_se_immagine_non_leggibile(tmp_path):
    percorso_non_immagine = tmp_path / "non_valida.jpg"
    percorso_non_immagine.write_bytes(b"non sono byte di una vera immagine")

    with pytest.raises(ValueError):
        rileva_volti(percorso_non_immagine)
