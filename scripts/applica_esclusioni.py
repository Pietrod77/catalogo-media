"""Applica le esclusioni marcate nel foglio di controllo di importa_facesheet.py.

Uso:
    python scripts/applica_esclusioni.py <cartella_output> <esclusioni.txt>

Sposta ogni foto elencata in esclusioni.txt (un nome file per riga, scaricato
dal pulsante "Scarica lista esclusioni" del foglio di controllo) fuori dalla
cartella, in una sottocartella "_esclusi" accanto ad essa: cosi' non verranno
piu' processate da scripts/popola_batch.py, ma restano recuperabili.
"""

import sys
from pathlib import Path


def applica_esclusioni(cartella_output: Path, percorso_lista: Path) -> tuple[int, int]:
    nomi_file = [
        riga.strip() for riga in percorso_lista.read_text(encoding="utf-8").splitlines() if riga.strip()
    ]
    cartella_esclusi = cartella_output.parent / f"{cartella_output.name}_esclusi"
    cartella_esclusi.mkdir(parents=True, exist_ok=True)

    spostate = 0
    non_trovate = 0
    for nome_file in nomi_file:
        origine = cartella_output / nome_file
        if not origine.is_file():
            print(f"[non_trovata] {nome_file}")
            non_trovate += 1
            continue
        origine.rename(cartella_esclusi / nome_file)
        spostate += 1

    return spostate, non_trovate


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: python scripts/applica_esclusioni.py <cartella_output> <esclusioni.txt>")
        return 1

    cartella_output = Path(sys.argv[1])
    percorso_lista = Path(sys.argv[2])
    if not cartella_output.is_dir():
        print(f"Cartella non trovata: {cartella_output}")
        return 1
    if not percorso_lista.is_file():
        print(f"File non trovato: {percorso_lista}")
        return 1

    spostate, non_trovate = applica_esclusioni(cartella_output, percorso_lista)
    print(f"\nSpostate {spostate} foto in {cartella_output.name}_esclusi (non trovate: {non_trovate}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
