"""Allinea il segnalino di sync locale allo stato attuale del NAS, per non
ri-scaricare tutta la storia gia' presente in locale al primo avvio del sync.

Uso: python scripts/allinea_sync_stato.py <percorso_db_locale> <url_nas>
Esempio: python scripts/allinea_sync_stato.py db/volti.db http://100.125.65.26:5002
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import aggiorna_sync_stato, connetti, init_db, leggi_sync_stato


def main() -> None:
    if len(sys.argv) != 3:
        print("Uso: python scripts/allinea_sync_stato.py <percorso_db_locale> <url_nas>")
        sys.exit(1)

    percorso_db = Path(sys.argv[1])
    url_nas = sys.argv[2]

    init_db(percorso_db)
    conn = connetti(percorso_db)
    precedente = leggi_sync_stato(conn)

    risposta = requests.get(f"{url_nas}/sync/stato", timeout=10)
    risposta.raise_for_status()
    dati = risposta.json()

    aggiorna_sync_stato(conn, dati["ultimo_persona_id"], dati["ultimo_embedding_id"])
    conn.close()

    print(
        f"sync_stato allineato: era {precedente}, ora "
        f"({dati['ultimo_persona_id']}, {dati['ultimo_embedding_id']})"
    )


if __name__ == "__main__":
    main()
