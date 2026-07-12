"""Lettura del nome della persona dal campo IPTC/XMP delle foto."""

import json
import subprocess
from pathlib import Path


def leggi_nomi(percorso_foto: str | Path) -> list[str]:
    """Legge il campo XMP-getty:Personality da una foto e ritorna i nomi taggati.

    Solleva FileNotFoundError se il file non esiste.
    Ritorna lista vuota se il campo è assente o vuoto (nessun nome taggato).
    Ritorna una lista di uno o più nomi se il campo è popolato.

    Il campo XMP-getty:Personality può essere memorizzato in due modi diversi
    a seconda del workflow con cui è stato scritto:
    - come lista XMP vera e propria (caso reale con Capture One / Getty):
      exiftool -j lo restituisce come array JSON, es. ["Mario Rossi", "Anna Bianchi"];
    - come stringa singola con nomi separati da virgola (usato in alcuni file
      dell'archivio storico): exiftool -j lo restituisce come stringa,
      es. "Mario Rossi, Anna Bianchi".
    Entrambi i casi vanno gestiti per non scartare erroneamente foto reali
    con più persone taggate come "non parsabili".
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
    if isinstance(personality, list):
        return [nome.strip() for nome in personality if nome.strip()]
    return [nome.strip() for nome in personality.split(",") if nome.strip()]
