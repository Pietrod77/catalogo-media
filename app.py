"""Web UI Flask per la revisione dei volti e l'apprendimento incrementale."""

import base64
import json
import os
import tempfile
import webbrowser
from pathlib import Path

import cv2
from flask import Flask, jsonify, render_template, request

from config import CARTELLA_SESSIONI_DEFAULT, CARTELLE_ARCHIVIO_EXTRA, PERCORSO_DB_DEFAULT
from core.matching import calcola_candidati, classifica_match
from core.volti import rileva_volti
from db.database import connetti, init_db


def crea_app(
    percorso_db: Path = PERCORSO_DB_DEFAULT,
    cartella_sessioni: Path = CARTELLA_SESSIONI_DEFAULT,
) -> Flask:
    """Crea e configura l'app Flask. percorso_db e cartella_sessioni sono
    parametrizzabili per permettere ai test di usare un DB e una cartella
    temporanei, isolati dai dati reali."""
    app = Flask(__name__)
    app.config["PERCORSO_DB"] = Path(percorso_db)
    app.config["CARTELLA_SESSIONI"] = Path(cartella_sessioni)
    app.config["CARTELLE_CONSENTITE_RIFERIMENTI"] = [
        app.config["CARTELLA_SESSIONI"],
        *CARTELLE_ARCHIVIO_EXTRA,
    ]
    init_db(app.config["PERCORSO_DB"])

    @app.get("/")
    def index():
        conn = connetti(app.config["PERCORSO_DB"])
        righe = conn.execute("SELECT nome FROM persone ORDER BY nome").fetchall()
        conn.close()
        nomi_esistenti = [riga[0] for riga in righe]
        return render_template(
            "index.html", nomi_esistenti_json=json.dumps(nomi_esistenti)
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

    return app


if __name__ == "__main__":
    app = crea_app()
    if os.environ.get("VOLTI_NO_BROWSER") != "1":
        webbrowser.open("http://127.0.0.1:5000/")
    app.run(port=5000)
