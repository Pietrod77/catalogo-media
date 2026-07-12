import subprocess
from pathlib import Path

import pytest
from PIL import Image

from core.iptc import leggi_nomi


def _crea_foto_di_prova(percorso: Path, personality: str | None) -> None:
    """Crea una foto JPG minima e, se richiesto, scrive il tag XMP-getty:Personality."""
    Image.new("RGB", (10, 10), color="red").save(percorso)
    if personality is not None:
        subprocess.run(
            [
                "exiftool",
                "-overwrite_original",
                f"-XMP-getty:Personality={personality}",
                str(percorso),
            ],
            check=True,
            capture_output=True,
        )


def test_leggi_nomi_solleva_errore_se_file_non_esiste(tmp_path):
    percorso_inesistente = tmp_path / "non_esiste.jpg"

    with pytest.raises(FileNotFoundError):
        leggi_nomi(percorso_inesistente)


def test_leggi_nomi_singolo_nome(tmp_path):
    percorso = tmp_path / "foto_singola.jpg"
    _crea_foto_di_prova(percorso, "Mario Rossi")

    assert leggi_nomi(percorso) == ["Mario Rossi"]


def test_leggi_nomi_piu_nomi(tmp_path):
    percorso = tmp_path / "foto_multipla.jpg"
    _crea_foto_di_prova(percorso, "Mario Rossi, Anna Bianchi")

    assert leggi_nomi(percorso) == ["Mario Rossi", "Anna Bianchi"]


def test_leggi_nomi_ritorna_lista_vuota_se_personality_assente(tmp_path):
    percorso = tmp_path / "foto_senza_tag.jpg"
    _crea_foto_di_prova(percorso, None)

    assert leggi_nomi(percorso) == []


def _crea_foto_di_prova_lista_xmp(percorso: Path, nomi: list[str]) -> None:
    """Crea una foto JPG minima e scrive Personality come vera lista XMP
    (non come stringa unica con virgole), replicando il formato con cui
    l'archivio reale (Capture One / Getty) salva più nomi taggati.
    """
    Image.new("RGB", (10, 10), color="red").save(percorso)
    comando = ["exiftool", "-overwrite_original"]
    for indice, nome in enumerate(nomi):
        operatore = "=" if indice == 0 else "+="
        comando.append(f"-XMP-getty:Personality{operatore}{nome}")
    comando.append(str(percorso))
    subprocess.run(comando, check=True, capture_output=True)


def test_leggi_nomi_gestisce_personality_come_lista_xmp(tmp_path):
    """Riproduce il bug reale: exiftool -j ritorna Personality come array JSON
    quando il tag è stato scritto come lista XMP a valori multipli (workflow
    Capture One / Getty), non come stringa unica separata da virgole.
    """
    percorso = tmp_path / "foto_lista_xmp.jpg"
    _crea_foto_di_prova_lista_xmp(percorso, ["Mario Rossi", "Anna Bianchi"])

    assert leggi_nomi(percorso) == ["Mario Rossi", "Anna Bianchi"]
