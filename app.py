"""Web UI Flask per la revisione dei volti e l'apprendimento incrementale."""

import base64
import json
import os
import sys
import tempfile
import uuid
import webbrowser
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request, send_file

from config import (
    CARTELLA_SESSIONI_DEFAULT,
    CARTELLE_ARCHIVIO_EXTRA,
    HOST,
    NAS_URL,
    PERCORSO_DB_DEFAULT,
    percorso_consentito,
    risolvi_profilo,
)
from core.matching import calcola_candidati, classifica_match
from core.sync import avvia_worker_sync
from core.volti import SOGLIA_QUALITA_MINIMA, rileva_volti
from db.database import (
    connetti,
    esporta_embedding_dopo,
    esporta_persone_dopo,
    init_db,
    salva_embedding,
    trova_o_crea_persona,
)


def crea_app(
    percorso_db: Path = PERCORSO_DB_DEFAULT,
    cartella_sessioni: Path = CARTELLA_SESSIONI_DEFAULT,
    colore_sfondo: str = "#ffffff",
    nome_profilo: str = "",
    nas_url: str | None = None,
) -> Flask:
    """Crea e configura l'app Flask. percorso_db e cartella_sessioni sono
    parametrizzabili per permettere ai test di usare un DB e una cartella
    temporanei, isolati dai dati reali. nas_url, se impostato, indica che
    questa istanza e' un fallback locale: le conferme fatte qui partono
    come non sincronizzate, in attesa che il worker le invii al NAS."""
    app = Flask(__name__)
    app.config["PERCORSO_DB"] = Path(percorso_db)
    app.config["CARTELLA_SESSIONI"] = Path(cartella_sessioni)
    app.config["CARTELLE_CONSENTITE_RIFERIMENTI"] = [
        app.config["CARTELLA_SESSIONI"],
        *CARTELLE_ARCHIVIO_EXTRA,
    ]
    app.config["COLORE_SFONDO"] = colore_sfondo
    app.config["NOME_PROFILO"] = nome_profilo
    app.config["NAS_URL"] = nas_url
    init_db(app.config["PERCORSO_DB"])

    @app.get("/")
    def index():
        conn = connetti(app.config["PERCORSO_DB"])
        righe = conn.execute("SELECT nome FROM persone ORDER BY nome").fetchall()
        conteggio_in_sospeso = conn.execute(
            "SELECT COUNT(*) FROM embedding WHERE sincronizzato = 0"
        ).fetchone()[0]
        conn.close()
        nomi_esistenti = [riga[0] for riga in righe]
        return render_template(
            "index.html",
            nomi_esistenti_json=json.dumps(nomi_esistenti),
            colore_sfondo=app.config["COLORE_SFONDO"],
            nome_profilo=app.config["NOME_PROFILO"],
            numero_persone=len(nomi_esistenti),
            conteggio_in_sospeso=conteggio_in_sospeso,
        )

    @app.post("/analizza")
    def analizza():
        file = request.files.get("immagine")
        if file is None or file.filename == "":
            return jsonify(errore="nessuna immagine inviata"), 400

        fd, percorso_temp_str = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        percorso_temp = Path(percorso_temp_str)
        file.save(percorso_temp)

        try:
            try:
                volti = rileva_volti(percorso_temp)
            except ValueError:
                return jsonify(errore="immagine non leggibile"), 400

            immagine = cv2.imread(str(percorso_temp))
            altezza, larghezza = immagine.shape[:2]

            conn = connetti(app.config["PERCORSO_DB"])
            risultato_volti = []
            for volto in volti:
                x1, y1, x2, y2 = volto.bbox
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(larghezza, x2), min(altezza, y2)
                crop = immagine[y1:y2, x1:x2]
                _, buffer = cv2.imencode(".jpg", crop)
                crop_base64 = base64.b64encode(buffer).decode("ascii")

                candidati = calcola_candidati(volto.vettore, conn)
                stato = classifica_match(candidati)

                risultato_volti.append(
                    {
                        "vettore": volto.vettore.tolist(),
                        "crop_base64": crop_base64,
                        "score": volto.score,
                        "stato": stato,
                        "candidati": [
                            {
                                "nome": c.nome,
                                "punteggio": c.punteggio,
                                "foto_riferimento": c.foto_riferimento,
                            }
                            for c in candidati
                        ],
                    }
                )
            conn.close()
            return jsonify(volti=risultato_volti)
        finally:
            percorso_temp.unlink(missing_ok=True)

    @app.post("/conferma")
    def conferma():
        dati = request.get_json(silent=True) or {}
        nome = (dati.get("nome") or "").strip()
        vettore_lista = dati.get("vettore")
        screenshot_base64 = dati.get("screenshot_base64")
        score = dati.get("score")

        if not nome:
            return jsonify(errore="nome mancante"), 400
        if not vettore_lista or not screenshot_base64 or score is None:
            return jsonify(errore="dati mancanti"), 400

        vettore = np.array(vettore_lista, dtype=np.float32)
        if vettore.shape != (512,) or not np.all(np.isfinite(vettore)):
            return jsonify(errore="vettore non valido"), 400

        if score < SOGLIA_QUALITA_MINIMA:
            return (
                jsonify(
                    errore=(
                        f"qualità troppo bassa (score {score:.2f}), "
                        "usa uno screenshot più nitido o ravvicinato"
                    )
                ),
                400,
            )

        cartella_conferme = app.config["CARTELLA_SESSIONI"] / "conferme"
        cartella_conferme.mkdir(parents=True, exist_ok=True)
        percorso_screenshot = cartella_conferme / f"{uuid.uuid4().hex}.jpg"
        percorso_screenshot.write_bytes(base64.b64decode(screenshot_base64))

        conn = connetti(app.config["PERCORSO_DB"])
        person_id = trova_o_crea_persona(conn, nome)
        salva_embedding(
            conn,
            person_id,
            vettore,
            str(percorso_screenshot),
            "conferma_editing",
            sincronizzato=app.config["NAS_URL"] is None,
        )
        conn.close()

        return jsonify(ok=True)

    @app.get("/riferimento")
    def riferimento():
        percorso_str = request.args.get("path", "")
        if not percorso_str:
            return jsonify(errore="path mancante"), 400

        percorso = Path(percorso_str)
        if not percorso_consentito(
            percorso, app.config["CARTELLE_CONSENTITE_RIFERIMENTI"]
        ):
            return jsonify(errore="path non consentito"), 403
        if not percorso.is_file():
            return jsonify(errore="file non trovato"), 404

        return send_file(percorso)

    @app.get("/sync/esporta")
    def sync_esporta():
        dopo_persona = int(request.args.get("dopo_persona", 0))
        dopo_embedding = int(request.args.get("dopo_embedding", 0))
        conn = connetti(app.config["PERCORSO_DB"])
        persone = esporta_persone_dopo(conn, dopo_persona)
        righe_embedding = esporta_embedding_dopo(conn, dopo_embedding)
        conn.close()

        embedding = []
        for riga in righe_embedding:
            percorso_foto = Path(riga["foto_origine"])
            screenshot_base64 = (
                base64.b64encode(percorso_foto.read_bytes()).decode("ascii")
                if percorso_foto.is_file()
                else None
            )
            embedding.append({**riga, "screenshot_base64": screenshot_base64})

        return jsonify(persone=persone, embedding=embedding)

    return app


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python app.py modelle|personaggi")
        sys.exit(1)

    try:
        profilo = risolvi_profilo(sys.argv[1])
    except ValueError as errore:
        print(errore)
        sys.exit(1)

    app = crea_app(
        percorso_db=profilo["db"],
        cartella_sessioni=profilo["sessioni"],
        colore_sfondo=profilo["colore"],
        nome_profilo=sys.argv[1],
        nas_url=NAS_URL,
    )
    if NAS_URL:
        avvia_worker_sync(profilo["db"], profilo["sessioni"], NAS_URL)
    if os.environ.get("VOLTI_NO_BROWSER") != "1":
        webbrowser.open(f"http://127.0.0.1:{profilo['porta']}/")
    app.run(host=HOST, port=profilo["porta"])
