"""Sincronizzazione incrementale tra un'installazione locale di fallback e il NAS."""

import base64
import logging
import threading
import time
from pathlib import Path

import numpy as np
import requests

from db.database import (
    aggiorna_sync_stato,
    connetti,
    embedding_da_sincronizzare,
    embedding_uid_esiste,
    leggi_sync_stato,
    salva_embedding,
    segna_sincronizzato,
    trova_o_crea_persona,
)

logger = logging.getLogger(__name__)

INTERVALLO_SECONDI = 60
TIMEOUT_RAGGIUNGIBILITA = 2.0
TIMEOUT_RICHIESTA = 10.0

# Le conferme offline hanno gia' superato la soglia di qualita' localmente al
# momento del salvataggio: il punteggio originale non viene pero' conservato in
# DB, quindi nel reinvio al NAS si usa un valore fittizio che supera comunque
# la soglia di controllo di /conferma.
SCORE_REINVIO = 1.0


def nas_raggiungibile(url_base: str) -> bool:
    """Controlla se il NAS risponde, con timeout breve per non bloccare il worker."""
    try:
        risposta = requests.get(f"{url_base}/", timeout=TIMEOUT_RAGGIUNGIBILITA)
        return risposta.status_code == 200
    except requests.exceptions.RequestException:
        return False


def invia_pendenti(conn, url_base: str) -> int:
    """Reinvia al NAS ogni conferma locale non ancora sincronizzata. Ritorna
    il numero di righe inviate con successo."""
    inviati = 0
    for riga in embedding_da_sincronizzare(conn):
        try:
            percorso_foto = Path(riga["foto_origine"])
            if not percorso_foto.is_file():
                continue
            screenshot_base64 = base64.b64encode(percorso_foto.read_bytes()).decode("ascii")
            try:
                risposta = requests.post(
                    f"{url_base}/conferma",
                    json={
                        "nome": riga["nome"],
                        "vettore": riga["vettore"],
                        "screenshot_base64": screenshot_base64,
                        "score": SCORE_REINVIO,
                        # L'uid della riga viaggia con essa: il NAS deve salvare
                        # la stessa identita', non generarne una nuova, altrimenti
                        # al pull successivo la conferma tornerebbe come duplicato.
                        "uid": riga["uid"],
                    },
                    timeout=TIMEOUT_RICHIESTA,
                )
            except requests.exceptions.RequestException:
                continue
            if risposta.status_code == 200:
                segna_sincronizzato(conn, riga["id"])
                inviati += 1
        except Exception:
            # Un errore inatteso su una riga non deve fermare l'invio delle altre.
            logger.exception("Errore nell'invio dell'embedding id=%s, riga saltata", riga.get("id"))
            continue
    return inviati


def scarica_incrementale(conn, url_base: str, cartella_sessioni: Path) -> int:
    """Scarica dal NAS le persone/embedding creati dopo l'ultimo pull. Ritorna
    il numero di embedding nuovi effettivamente inseriti (esclusi i duplicati)."""
    ultimo_persona, ultimo_embedding = leggi_sync_stato(conn)
    risposta = requests.get(
        f"{url_base}/sync/esporta",
        params={"dopo_persona": ultimo_persona, "dopo_embedding": ultimo_embedding},
        timeout=TIMEOUT_RICHIESTA,
    )
    risposta.raise_for_status()
    dati = risposta.json()

    for persona in dati["persone"]:
        trova_o_crea_persona(conn, persona["nome"])
        ultimo_persona = max(ultimo_persona, persona["id"])

    cartella_conferme = cartella_sessioni / "conferme"
    cartella_conferme.mkdir(parents=True, exist_ok=True)

    def salva_riga_remota(riga: dict) -> bool:
        """Inserisce in locale una riga scaricata. Ritorna True se e' stata
        davvero inserita, False se era gia' presente (stesso uid)."""
        if embedding_uid_esiste(conn, riga["uid"]):
            return False
        if riga["screenshot_base64"] is not None:
            percorso_locale = cartella_conferme / Path(riga["foto_origine"]).name
            percorso_locale.write_bytes(base64.b64decode(riga["screenshot_base64"]))
            foto_origine_locale = str(percorso_locale)
        else:
            # Nessun byte ricevuto: il file non esiste sul NAS (tipico delle righe
            # storiche batch_iniziale). Meglio conservare il percorso originale
            # che scriverne uno locale che non esistera' mai.
            foto_origine_locale = riga["foto_origine"]
        person_id = trova_o_crea_persona(conn, riga["nome"])
        vettore = np.array(riga["vettore"], dtype=np.float32)
        salva_embedding(
            conn, person_id, vettore, foto_origine_locale, riga["fonte"],
            sincronizzato=True, uid=riga["uid"],
        )
        return True

    ricevuti = 0
    for riga in dati["embedding"]:
        try:
            if salva_riga_remota(riga):
                ricevuti += 1
        except Exception:
            # Una riga malformata non deve bloccare per sempre il pull: la si
            # salta rumorosamente e si avanza comunque il segnalino oltre di essa.
            logger.exception(
                "Errore nel salvataggio dell'embedding remoto id=%s, riga saltata",
                riga.get("id"),
            )
        id_riga = riga.get("id")
        if id_riga is not None:
            ultimo_embedding = max(ultimo_embedding, id_riga)

    aggiorna_sync_stato(conn, ultimo_persona, ultimo_embedding)
    return ricevuti


def esegui_ciclo_sync(percorso_db: Path, cartella_sessioni: Path, url_base: str) -> dict:
    """Un ciclo completo di sync: se il NAS e' raggiungibile, invia le conferme
    pendenti e scarica le novita'. Non solleva mai eccezioni verso il chiamante."""
    if not nas_raggiungibile(url_base):
        return {"raggiungibile": False, "inviati": 0, "ricevuti": 0}
    conn = connetti(percorso_db)
    try:
        inviati = invia_pendenti(conn, url_base)
        ricevuti = scarica_incrementale(conn, url_base, cartella_sessioni)
    finally:
        conn.close()
    return {"raggiungibile": True, "inviati": inviati, "ricevuti": ricevuti}


def avvia_worker_sync(percorso_db: Path, cartella_sessioni: Path, url_base: str) -> threading.Thread:
    """Avvia un thread daemon che esegue un ciclo di sync ogni INTERVALLO_SECONDI,
    ignorando qualunque errore (ritenta al ciclo successivo)."""

    def ciclo():
        while True:
            try:
                esegui_ciclo_sync(percorso_db, cartella_sessioni, url_base)
            except Exception:
                pass
            time.sleep(INTERVALLO_SECONDI)

    thread = threading.Thread(target=ciclo, daemon=True)
    thread.start()
    return thread
