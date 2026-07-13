"""Web UI Flask per la revisione dei volti e l'apprendimento incrementale."""

import json
import os
import webbrowser
from pathlib import Path

from flask import Flask, render_template

from config import CARTELLA_SESSIONI_DEFAULT, CARTELLE_ARCHIVIO_EXTRA, PERCORSO_DB_DEFAULT
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

    return app


if __name__ == "__main__":
    app = crea_app()
    if os.environ.get("VOLTI_NO_BROWSER") != "1":
        webbrowser.open("http://127.0.0.1:5000/")
    app.run(port=5000)
