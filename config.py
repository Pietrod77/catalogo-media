"""Percorsi e configurazione del progetto (DB, cartella sessioni, cartelle
consentite per le miniature di riferimento servite da /riferimento)."""

import os
from pathlib import Path

RADICE_PROGETTO = Path(__file__).resolve().parent
PERCORSO_DB_DEFAULT = RADICE_PROGETTO / "db" / "volti.db"
CARTELLA_SESSIONI_DEFAULT = RADICE_PROGETTO / "sessioni"

_archivio_storico = os.environ.get("VOLTI_ARCHIVIO_STORICO")
NAS_URL = os.environ.get("VOLTI_NAS_URL") or None
HOST = os.environ.get("VOLTI_HOST", "127.0.0.1")
CARTELLE_ARCHIVIO_EXTRA: list[Path] = (
    [Path(_archivio_storico).resolve()] if _archivio_storico else []
)


def percorso_consentito(percorso: Path, cartelle_consentite: list[Path]) -> bool:
    """Ritorna True se percorso e' contenuto (anche in una sottocartella)
    in una delle cartelle_consentite."""
    percorso = Path(percorso).resolve()
    return any(
        percorso.is_relative_to(Path(cartella).resolve())
        for cartella in cartelle_consentite
    )


PROFILI: dict[str, dict] = {
    "modelle": {
        "db": RADICE_PROGETTO / "db" / "volti_modelle.db",
        "sessioni": RADICE_PROGETTO / "sessioni" / "modelle",
        "porta": 5001,
        "colore": "#ffe4e1",
    },
    "personaggi": {
        "db": PERCORSO_DB_DEFAULT,
        "sessioni": CARTELLA_SESSIONI_DEFAULT,
        "porta": 5002,
        "colore": "#b0e0e6",
    },
}


def risolvi_profilo(nome: str) -> dict:
    """Ritorna la configurazione (db, sessioni, porta, colore) del profilo richiesto.

    Solleva ValueError se nome non e' un profilo valido."""
    if nome not in PROFILI:
        raise ValueError(
            f"Profilo sconosciuto: {nome!r}. Usa 'modelle' o 'personaggi'."
        )
    return PROFILI[nome]
