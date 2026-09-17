"""Copia una tantum tutte le persone/embedding del database Modelle dentro il
database Personaggi (mai il contrario).

Da eseguire una sola volta per allineare lo storico dopo aver attivato la
propagazione automatica delle nuove conferme (vedi app.py, crea_app,
percorso_db_propagazione): da quel momento ogni nuova conferma fatta su
Modelle finisce gia' in automatico anche su Personaggi, ma le conferme fatte
*prima* di attivarla vanno riportate a mano con questo script.

Idempotente: salta gli embedding gia' presenti in Personaggi (stesso
foto_origine), quindi si puo' rilanciare piu' volte senza creare duplicati.

Uso:
    python scripts/propaga_modelle_in_personaggi.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PROFILI
from db.database import connetti, init_db, salva_embedding, trova_o_crea_persona


def propaga(percorso_db_modelle: Path, percorso_db_personaggi: Path) -> dict[str, int]:
    """Copia in percorso_db_personaggi ogni embedding di percorso_db_modelle
    non ancora presente (per foto_origine). Ritorna {'copiati': N, 'saltati': N}."""
    init_db(percorso_db_modelle)
    init_db(percorso_db_personaggi)

    conn_modelle = connetti(percorso_db_modelle)
    conn_personaggi = connetti(percorso_db_personaggi)
    try:
        righe = conn_modelle.execute(
            "SELECT p.nome, e.vettore, e.foto_origine, e.fonte "
            "FROM embedding e JOIN persone p ON p.id = e.person_id"
        ).fetchall()

        risultato = {"copiati": 0, "saltati": 0}
        for nome, vettore_blob, foto_origine, fonte in righe:
            gia_presente = conn_personaggi.execute(
                "SELECT 1 FROM embedding WHERE foto_origine = ?", (foto_origine,)
            ).fetchone()
            if gia_presente:
                risultato["saltati"] += 1
                continue

            vettore = np.frombuffer(vettore_blob, dtype=np.float32)
            person_id = trova_o_crea_persona(conn_personaggi, nome)
            salva_embedding(conn_personaggi, person_id, vettore, foto_origine, fonte)
            risultato["copiati"] += 1

        return risultato
    finally:
        conn_modelle.close()
        conn_personaggi.close()


def main() -> int:
    risultato = propaga(PROFILI["modelle"]["db"], PROFILI["personaggi"]["db"])
    print(
        f"Copiati {risultato['copiati']} embedding in Personaggi, "
        f"{risultato['saltati']} gia' presenti (saltati)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
