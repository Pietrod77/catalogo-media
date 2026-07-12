"""Lettura del nome della persona dal campo IPTC/XMP delle foto."""

import json
import subprocess
from pathlib import Path


def leggi_nomi(percorso_foto: str | Path) -> list[str]:
    """Legge il campo XMP-getty:Personality da una foto e ritorna i nomi taggati.

    Solleva FileNotFoundError se il file non esiste.
    Ritorna lista vuota se il campo è assente o vuoto (nessun nome taggato).
    Ritorna una lista di uno o più nomi se il campo è popolato (split su virgola).
    """
    percorso_foto = Path(percorso_foto)
    if not percorso_foto.exists():
        raise FileNotFoundError(f"File non trovato: {percorso_foto}")

    risultato = subprocess.run(
        ["exiftool", "-j", "-XMP-getty:Personality", str(percorso_foto)],
        capture_output=True,
        text=True,
        check=True,
    )
    dati = json.loads(risultato.stdout)[0]
    personality = dati.get("Personality", "")
    if not personality:
        return []
    return [nome.strip() for nome in personality.split(",") if nome.strip()]
