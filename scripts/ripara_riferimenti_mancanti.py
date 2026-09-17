"""Ripara i riferimenti foto_origine che puntano a percorsi non piu' validi
(es. dopo una riorganizzazione di cartelle), cercando un file con lo stesso
nome dentro cartella_ricerca e ricopiandolo dentro cartella_destinazione.

Da eseguire sulla macchina dove risiedono sia il database sia (dopo averli
eventualmente ricopiati li') i file immagine mancanti — tipicamente sul NAS,
dopo aver scp-ato i file recuperati localmente nella cartella sessioni
corretta.

Non tocca le righe il cui file esiste gia' (nessuna azione), ne' quelle per
cui non si trova un file con lo stesso nome in cartella_ricerca (restano
segnalate come non trovate, senza sollevare errori).

Uso:
    python scripts/ripara_riferimenti_mancanti.py <percorso_db> <cartella_ricerca> <cartella_destinazione>
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import connetti


def ripara(conn, cartella_ricerca: Path, cartella_destinazione: Path) -> dict[str, int]:
    """Per ogni embedding con foto_origine non esistente, cerca un file con lo
    stesso nome in cartella_ricerca (ricorsivamente) e lo ricopia dentro
    cartella_destinazione, aggiornando foto_origine al nuovo percorso.

    Ritorna {'riparati': N, 'non_trovati': N, 'gia_ok': N}."""
    indice: dict[str, Path] = {}
    for percorso in cartella_ricerca.rglob("*"):
        if percorso.is_file():
            indice.setdefault(percorso.name, percorso)

    righe = conn.execute("SELECT id, foto_origine FROM embedding").fetchall()

    risultato = {"riparati": 0, "non_trovati": 0, "gia_ok": 0}
    for id_, foto_origine in righe:
        if Path(foto_origine).is_file():
            risultato["gia_ok"] += 1
            continue

        nome = Path(foto_origine).name
        sorgente = indice.get(nome)
        if sorgente is None:
            risultato["non_trovati"] += 1
            continue

        cartella_destinazione.mkdir(parents=True, exist_ok=True)
        destinazione = cartella_destinazione / nome
        if not destinazione.exists():
            shutil.copy2(sorgente, destinazione)

        conn.execute(
            "UPDATE embedding SET foto_origine = ? WHERE id = ?", (str(destinazione), id_)
        )
        risultato["riparati"] += 1

    conn.commit()
    return risultato


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Uso: python scripts/ripara_riferimenti_mancanti.py "
            "<percorso_db> <cartella_ricerca> <cartella_destinazione>"
        )
        return 1

    percorso_db = Path(sys.argv[1])
    cartella_ricerca = Path(sys.argv[2])
    cartella_destinazione = Path(sys.argv[3])

    if not percorso_db.is_file():
        print(f"Database non trovato: {percorso_db}")
        return 1
    if not cartella_ricerca.is_dir():
        print(f"Cartella di ricerca non trovata: {cartella_ricerca}")
        return 1

    conn = connetti(percorso_db)
    try:
        risultato = ripara(conn, cartella_ricerca, cartella_destinazione)
    finally:
        conn.close()

    print(
        f"Riparati {risultato['riparati']}, "
        f"non trovati {risultato['non_trovati']}, "
        f"gia' a posto {risultato['gia_ok']}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
