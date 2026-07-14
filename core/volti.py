"""Rilevamento volti e calcolo embedding facciali tramite InsightFace."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis

_modello: FaceAnalysis | None = None


@dataclass
class VoltoRilevato:
    vettore: np.ndarray  # embedding, shape (512,), dtype float32
    bbox: tuple[int, int, int, int]
    score: float


SOGLIA_QUALITA_MINIMA = 0.5


def carica_modello() -> FaceAnalysis:
    """Carica il modello InsightFace (buffalo_l) una sola volta per processo."""
    global _modello
    if _modello is None:
        _modello = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _modello.prepare(ctx_id=-1, det_size=(640, 640))
    return _modello


def rileva_volti(percorso_foto: str | Path) -> list[VoltoRilevato]:
    """Rileva tutti i volti in una foto e ne calcola l'embedding.

    Solleva FileNotFoundError se il file non esiste.
    Ritorna lista vuota se il file esiste ma non contiene volti rilevabili.
    """
    percorso_foto = Path(percorso_foto)
    if not percorso_foto.exists():
        raise FileNotFoundError(f"File non trovato: {percorso_foto}")

    immagine = cv2.imread(str(percorso_foto))
    if immagine is None:
        raise ValueError(f"Impossibile leggere l'immagine: {percorso_foto}")

    modello = carica_modello()
    volti = modello.get(immagine)

    risultati = []
    for volto in volti:
        bbox = tuple(int(v) for v in volto.bbox)
        risultati.append(
            VoltoRilevato(
                vettore=volto.normed_embedding.astype(np.float32),
                bbox=bbox,
                score=float(volto.det_score),
            )
        )
    return risultati
