"""Percorsi e configurazione del progetto (DB, cartella sessioni, cartelle
consentite per le miniature di riferimento servite da /riferimento)."""

import os
from pathlib import Path

RADICE_PROGETTO = Path(__file__).resolve().parent
PERCORSO_DB_DEFAULT = RADICE_PROGETTO / "db" / "volti.db"
CARTELLA_SESSIONI_DEFAULT = RADICE_PROGETTO / "sessioni"

_archivio_storico = os.environ.get("VOLTI_ARCHIVIO_STORICO")
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
