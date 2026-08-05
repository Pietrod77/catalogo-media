"""Rinomina in batch foto non taggate in base al riconoscimento volti.

Uso:
    python scripts/rinomina_batch.py <cartella_input> <cartella_output>

Scansiona <cartella_input> (e sottocartelle) alla ricerca di JPG/PNG, rileva
i volti con InsightFace, li confronta col database "personaggi", e copia
ogni foto in <cartella_output> (stessa struttura di sottocartelle) col nome
del file originale seguito da un segmento per ogni volto trovato: nome e
punteggio se il match è certo o ambiguo, "sconosciuto" se nessun candidato
valido, "NESSUN_VOLTO" se non è stato rilevato alcun volto nella foto.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.matching import calcola_candidati, classifica_match
from core.volti import rileva_volti
from db.database import connetti

PERCORSO_DB_DEFAULT = Path(__file__).resolve().parent.parent / "db" / "volti.db"

ESTENSIONI = ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.png", "*.PNG")


def _sanitizza_nome(nome: str) -> str:
    """Sostituisce spazi con underscore e rimuove caratteri non validi in un nome file."""
    nome = nome.replace(" ", "_")
    for carattere in ("/", "\\", ":"):
        nome = nome.replace(carattere, "_")
    return nome


def _segmento_per_volto(volto, conn) -> tuple[str, str]:
    """Calcola il segmento di nome file per un singolo volto rilevato.

    Ritorna (segmento, categoria) dove categoria è 'certo', 'ambiguo' o 'sconosciuto'."""
    candidati = calcola_candidati(volto.vettore, conn)
    stato = classifica_match(candidati)
    if stato == "sconosciuto":
        return "sconosciuto", "sconosciuto"
    nome_sanificato = _sanitizza_nome(candidati[0].nome)
    punteggio = round(candidati[0].punteggio * 100)
    if stato == "ambiguo":
        return f"{nome_sanificato}_{punteggio}_DA_VERIFICARE", "ambiguo"
    return f"{nome_sanificato}_{punteggio}", "certo"


def rinomina_da_cartella(
    cartella_input: Path, cartella_output: Path, percorso_db: Path
) -> dict[str, int]:
    """Elabora tutte le foto JPG/PNG in cartella_input (ricorsivo) e ne copia una
    versione rinominata in cartella_output, rispecchiando la struttura di
    sottocartelle dell'input. Gli originali non vengono mai modificati.

    Ritorna un riepilogo: {'foto_totali': N, 'certo': N, 'ambiguo': N,
    'sconosciuto': N, 'nessun_volto': N, 'errore_lettura_immagine': N}.
    I conteggi certo/ambiguo/sconosciuto/nessun_volto sono per volto (una foto
    con più volti può contribuire a più categorie); foto_totali e
    errore_lettura_immagine sono per foto.
    """
    conn = connetti(percorso_db)
    riepilogo = {
        "foto_totali": 0,
        "certo": 0,
        "ambiguo": 0,
        "sconosciuto": 0,
        "nessun_volto": 0,
        "errore_lettura_immagine": 0,
    }

    foto_trovate = sorted(
        {percorso for pattern in ESTENSIONI for percorso in cartella_input.rglob(pattern)}
    )

    try:
        for foto in foto_trovate:
            riepilogo["foto_totali"] += 1
            try:
                volti = rileva_volti(foto)
            except ValueError as errore:
                riepilogo["errore_lettura_immagine"] += 1
                print(f"[errore_lettura_immagine] {foto.name}: {errore}")
                continue
            except Exception as errore:
                riepilogo["errore_lettura_immagine"] += 1
                print(f"[errore_lettura_immagine] {foto.name}: {errore}")
                continue

            if not volti:
                riepilogo["nessun_volto"] += 1
                nuovo_nome = f"{foto.stem}_NESSUN_VOLTO{foto.suffix}"
            else:
                segmenti = []
                for volto in volti:
                    segmento, categoria = _segmento_per_volto(volto, conn)
                    segmenti.append(segmento)
                    riepilogo[categoria] += 1
                nuovo_nome = f"{foto.stem}_{'_'.join(segmenti)}{foto.suffix}"

            try:
                percorso_relativo = foto.relative_to(cartella_input).parent
                cartella_output_foto = cartella_output / percorso_relativo
                cartella_output_foto.mkdir(parents=True, exist_ok=True)
                shutil.copy2(foto, cartella_output_foto / nuovo_nome)
                print(f"[{nuovo_nome}] <- {foto.name}")
            except Exception as errore:
                riepilogo["errore_lettura_immagine"] += 1
                print(f"[errore_lettura_immagine] {foto.name}: {errore}")
    finally:
        conn.close()
    return riepilogo


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: python scripts/rinomina_batch.py <cartella_input> <cartella_output>")
        return 1

    cartella_input = Path(sys.argv[1])
    cartella_output = Path(sys.argv[2])

    if not cartella_input.is_dir():
        print(f"Cartella non trovata: {cartella_input}")
        return 1

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, PERCORSO_DB_DEFAULT)

    print("\n--- Riepilogo rinomina ---")
    for chiave, valore in riepilogo.items():
        print(f"{chiave}: {valore}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
