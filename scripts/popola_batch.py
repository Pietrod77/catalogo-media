"""Popolamento iniziale del database volti a partire da un archivio di foto taggate.

Uso:
    python scripts/popola_batch.py <cartella_archivio>

Scansiona la cartella (e sottocartelle) alla ricerca di JPG, legge il nome
dal campo IPTC (XMP-getty:Personality) e il volto rilevato da InsightFace.
Salva nel DB solo i casi puliti (esattamente 1 volto e 1 nome); tutti gli
altri casi vengono registrati in log_scarti per revisione manuale.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.iptc import leggi_nomi
from core.volti import rileva_volti
from db.database import (
    connetti,
    foto_gia_processata,
    init_db,
    registra_scarto,
    salva_embedding,
    trova_o_crea_persona,
)

PERCORSO_DB_DEFAULT = Path(__file__).resolve().parent.parent / "db" / "volti.db"


def classifica_caso(nomi: list[str], volti: list) -> str | None:
    """Decide se una foto è un caso pulito da salvare o va scartata.

    Ritorna il motivo dello scarto, oppure None se il caso è pulito
    (esattamente 1 volto rilevato e esattamente 1 nome taggato).
    """
    if not nomi:
        return "iptc_mancante"
    if not volti:
        return "nessun_volto"
    if len(volti) != 1 or len(nomi) != 1:
        return "volti_multipli"
    return None


def popola_da_cartella(cartella: Path, percorso_db: Path) -> dict[str, int]:
    """Elabora tutte le foto JPG in cartella (ricorsivo) e popola il DB.

    Ritorna un riepilogo: {'salvate': N, 'iptc_mancante': N, 'nessun_volto': N,
    'volti_multipli': N, 'iptc_non_parsabile': N, 'errore_lettura_immagine': N,
    'gia_processata': N}.
    """
    init_db(percorso_db)
    conn = connetti(percorso_db)
    riepilogo = {
        "salvate": 0,
        "iptc_mancante": 0,
        "nessun_volto": 0,
        "volti_multipli": 0,
        "iptc_non_parsabile": 0,
        "errore_lettura_immagine": 0,
        "gia_processata": 0,
    }

    foto_trovate = sorted(
        [
            *cartella.rglob("*.jpg"),
            *cartella.rglob("*.JPG"),
            *cartella.rglob("*.jpeg"),
            *cartella.rglob("*.JPEG"),
            *cartella.rglob("*.png"),
            *cartella.rglob("*.PNG"),
        ]
    )

    for foto in foto_trovate:
        if foto_gia_processata(conn, str(foto)):
            riepilogo["gia_processata"] += 1
            print(f"[gia_processata] {foto.name}")
            continue

        try:
            nomi = leggi_nomi(foto)
        except Exception as errore:
            registra_scarto(conn, str(foto), "iptc_non_parsabile")
            riepilogo["iptc_non_parsabile"] += 1
            print(f"[iptc_non_parsabile] {foto.name}: {errore}")
            continue

        try:
            volti = rileva_volti(foto)
        except Exception as errore:
            registra_scarto(conn, str(foto), "errore_lettura_immagine")
            riepilogo["errore_lettura_immagine"] += 1
            print(f"[errore_lettura_immagine] {foto.name}: {errore}")
            continue

        motivo = classifica_caso(nomi, volti)

        if motivo is not None:
            registra_scarto(conn, str(foto), motivo)
            riepilogo[motivo] += 1
            print(f"[{motivo}] {foto.name}")
            continue

        person_id = trova_o_crea_persona(conn, nomi[0])
        salva_embedding(conn, person_id, volti[0].vettore, str(foto), "batch_iniziale")
        riepilogo["salvate"] += 1
        print(f"[salvata] {foto.name} -> {nomi[0]}")

    conn.close()
    return riepilogo


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python scripts/popola_batch.py <cartella_archivio>")
        return 1

    cartella = Path(sys.argv[1])
    if not cartella.is_dir():
        print(f"Cartella non trovata: {cartella}")
        return 1

    if shutil.which("exiftool") is None:
        print("exiftool non trovato. Installalo con: brew install exiftool")
        return 1

    riepilogo = popola_da_cartella(cartella, PERCORSO_DB_DEFAULT)

    print("\n--- Riepilogo popolamento ---")
    for chiave, valore in riepilogo.items():
        print(f"{chiave}: {valore}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
