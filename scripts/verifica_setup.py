"""Verifica end-to-end del setup della Fase 1: DB, exiftool, InsightFace.

Uso:
    python scripts/verifica_setup.py [percorso_foto_con_volto.jpg]

Se il percorso della foto non viene passato, salta solo il controllo
del rilevamento volti (utile finché non si ha ancora una foto di prova).
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import init_db, connetti
from core.volti import rileva_volti


def verifica_database() -> bool:
    percorso_db = Path(__file__).resolve().parent.parent / "db" / "volti_verifica.db"
    try:
        init_db(percorso_db)
        conn = connetti(percorso_db)
        tabelle = {
            riga[0]
            for riga in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        percorso_db.unlink()
        ok = {"persone", "embedding", "log_scarti"}.issubset(tabelle)
        print(f"[{'OK' if ok else 'FAIL'}] Database: schema creato correttamente")
        return ok
    except Exception as errore:
        print(f"[FAIL] Database: {errore}")
        return False


def verifica_exiftool() -> bool:
    try:
        risultato = subprocess.run(
            ["exiftool", "-ver"], capture_output=True, text=True, check=True
        )
        print(f"[OK] exiftool: versione {risultato.stdout.strip()}")
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as errore:
        print(f"[FAIL] exiftool non trovato o non funzionante: {errore}")
        return False


def verifica_insightface(percorso_foto: str | None) -> bool:
    if percorso_foto is None:
        print("[SKIP] InsightFace: nessuna foto di prova passata come argomento")
        return True
    try:
        risultati = rileva_volti(percorso_foto)
        if not risultati:
            print(f"[FAIL] InsightFace: nessun volto rilevato in {percorso_foto}")
            return False
        volto = risultati[0]
        ok = volto.vettore.shape == (512,)
        print(
            f"[{'OK' if ok else 'FAIL'}] InsightFace: {len(risultati)} volto/i rilevato/i, "
            f"embedding shape={volto.vettore.shape}"
        )
        return ok
    except Exception as errore:
        print(f"[FAIL] InsightFace: {errore}")
        return False


def main() -> int:
    percorso_foto = sys.argv[1] if len(sys.argv) > 1 else None

    risultati = [
        verifica_database(),
        verifica_exiftool(),
        verifica_insightface(percorso_foto),
    ]

    if all(risultati):
        print("\nFase 1 completata: tutti i componenti funzionano correttamente.")
        return 0
    else:
        print("\nAlcuni controlli sono falliti, vedi sopra.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
