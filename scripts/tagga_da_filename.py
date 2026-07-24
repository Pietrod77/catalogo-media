"""Tagga con IPTC (XMP-getty:Personality) le foto di un archivio dove il nome
della persona e' nel nome del file, non nei metadati.

Uso:
    python scripts/tagga_da_filename.py <cartella>

Cerca ricorsivamente file jpg/jpeg/png, deriva il nome dal filename
(rimuove l'estensione e un eventuale numero finale usato per distinguere
piu' foto della stessa persona, es. "Abby Champion 172.jpg" -> "Abby Champion")
e scrive il tag XMP-getty:Personality via exiftool — lo stesso campo letto da
core/iptc.py e usato da scripts/popola_batch.py. Salta i file che hanno gia'
il tag popolato (idempotente, si puo' rilanciare in sicurezza).
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.iptc import leggi_nomi

SUFFISSO_NUMERICO = re.compile(r"\s+\d+$")


def nome_da_filename(percorso: Path) -> str:
    """Deriva il nome persona dal filename, rimuovendo un numero finale."""
    stem = percorso.stem
    return SUFFISSO_NUMERICO.sub("", stem).strip()


def tagga_cartella(cartella: Path) -> dict[str, int]:
    riepilogo = {"taggate": 0, "gia_taggate": 0, "errore": 0}

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
        if leggi_nomi(foto):
            riepilogo["gia_taggate"] += 1
            continue

        nome = nome_da_filename(foto)
        if not nome:
            print(f"[nome_vuoto] {foto.name}")
            riepilogo["errore"] += 1
            continue

        try:
            subprocess.run(
                [
                    "exiftool",
                    "-overwrite_original",
                    f"-XMP-getty:Personality={nome}",
                    str(foto),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as errore:
            print(f"[errore] {foto.name}: {errore.stderr}")
            riepilogo["errore"] += 1
            continue

        print(f"[taggata] {foto.name} -> {nome}")
        riepilogo["taggate"] += 1

    return riepilogo


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python scripts/tagga_da_filename.py <cartella>")
        return 1

    cartella = Path(sys.argv[1])
    if not cartella.is_dir():
        print(f"Cartella non trovata: {cartella}")
        return 1

    riepilogo = tagga_cartella(cartella)

    print("\n--- Riepilogo tagging ---")
    for chiave, valore in riepilogo.items():
        print(f"{chiave}: {valore}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
