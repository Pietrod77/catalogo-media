# Web UI di revisione + apprendimento incrementale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Costruire la web app Flask locale con cui Pietro trascina uno screenshot di un volto, riceve un nome proposto (certo/ambiguo/sconosciuto), e la sua conferma salva un nuovo embedding nel DB — è il meccanismo di apprendimento incrementale.

**Architecture:** Flask single-page con AJAX (JS vanilla, nessun framework). Tre route: `GET /` (pagina), `POST /analizza` (rileva volti + calcola candidati, ritorna JSON), `POST /conferma` (salva screenshot + persona + embedding), `GET /riferimento` (serve le miniature dei volti di riferimento con validazione path). Riusa senza modifiche `core/volti.py` (Fase 1) e `core/matching.py` (Fase 3).

**Tech Stack:** Flask, Pillow, numpy, opencv-python (già in `requirements.txt`, nessuna nuova dipendenza). pytest + `Flask.test_client()` per i test.

## Global Constraints

- Nomi di file, variabili, funzioni e commenti in italiano (convenzione del progetto).
- Nessuna nuova dipendenza: `flask` e `pillow` sono già in `requirements.txt`.
- Nessuna modifica a `core/volti.py` o `core/matching.py` — riuso diretto delle interfacce esistenti (`rileva_volti`, `VoltoRilevato`, `calcola_candidati`, `classifica_match`, `Candidato`).
- Soglie di matching invariate: `SOGLIA_ALTA = 0.45`, `SOGLIA_BASSA = 0.30` (definite in `core/matching.py`, Fase 3).
- L'embedding di un volto non va **mai** ricalcolato in `/conferma`: si riusa esattamente quello prodotto da `/analizza` e rispedito dal client nel payload.
- `sessioni/` è già esclusa da git (`.gitignore` esistente); `sessioni/conferme/` (nuova sottocartella per gli screenshot confermati) va creata a runtime con `mkdir(parents=True, exist_ok=True)`, non pre-esistente nel repo.
- `db/database.py` non va modificato: `trova_o_crea_persona` e `salva_embedding` sono già generici rispetto al parametro `fonte` (questa fase userà `fonte='conferma_editing'`).
- Design di riferimento: `docs/superpowers/specs/2026-07-13-web-ui-apprendimento-incrementale-design.md`.

---

### Task 1: Configurazione percorsi (`config.py`)

**Files:**
- Create: `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nessuna funzione da moduli precedenti.
- Produces:
  - `PERCORSO_DB_DEFAULT: Path` — path di default del DB (`db/volti.db`).
  - `CARTELLA_SESSIONI_DEFAULT: Path` — path di default della cartella sessioni (`sessioni/`).
  - `CARTELLE_ARCHIVIO_EXTRA: list[Path]` — cartelle aggiuntive consentite per le miniature di riferimento, lette dalla variabile d'ambiente opzionale `VOLTI_ARCHIVIO_STORICO` (lista vuota se non impostata).
  - `percorso_consentito(percorso: Path, cartelle_consentite: list[Path]) -> bool` — True se `percorso` è contenuto (anche in una sottocartella) in una delle `cartelle_consentite`.

- [ ] **Step 1: Scrivere il test che fallisce**

Create `tests/test_config.py`:

```python
from pathlib import Path

from config import percorso_consentito


def test_percorso_consentito_dentro_cartella_permessa(tmp_path):
    cartella = tmp_path / "sessioni"
    cartella.mkdir()
    file_dentro = cartella / "foto.jpg"
    file_dentro.write_bytes(b"x")

    assert percorso_consentito(file_dentro, [cartella]) is True


def test_percorso_consentito_fuori_cartella_permessa(tmp_path):
    cartella_permessa = tmp_path / "sessioni"
    cartella_permessa.mkdir()
    cartella_esterna = tmp_path / "altrove"
    cartella_esterna.mkdir()
    file_esterno = cartella_esterna / "foto.jpg"
    file_esterno.write_bytes(b"x")

    assert percorso_consentito(file_esterno, [cartella_permessa]) is False


def test_percorso_consentito_sottocartella_permessa(tmp_path):
    cartella_permessa = tmp_path / "sessioni"
    sottocartella = cartella_permessa / "conferme"
    sottocartella.mkdir(parents=True)
    file_dentro = sottocartella / "foto.jpg"
    file_dentro.write_bytes(b"x")

    assert percorso_consentito(file_dentro, [cartella_permessa]) is True
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run (con venv attivo, dalla root del progetto):
```bash
source venv/bin/activate
pytest tests/test_config.py -v
```

Expected: FAIL con `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 3: Implementare config.py**

Create `config.py`:

```python
"""Percorsi e configurazione del progetto (DB, cartella sessioni, cartelle
consentite per le miniature di riferimento servite da /riferimento)."""

import os
from pathlib import Path

RADICE_PROGETTO = Path(__file__).resolve().parent
PERCORSO_DB_DEFAULT = RADICE_PROGETTO / "db" / "volti.db"
CARTELLA_SESSIONI_DEFAULT = RADICE_PROGETTO / "sessioni"

_archivio_storico = os.environ.get("VOLTI_ARCHIVIO_STORICO")
CARTELLE_ARCHIVIO_EXTRA: list[Path] = (
    [Path(_archivio_storico).resolve()] if _archivio_storico else []
)


def percorso_consentito(percorso: Path, cartelle_consentite: list[Path]) -> bool:
    """Ritorna True se percorso e' contenuto (anche in una sottocartella)
    in una delle cartelle_consentite."""
    percorso = Path(percorso).resolve()
    return any(
        percorso.is_relative_to(Path(cartella).resolve())
        for cartella in cartelle_consentite
    )
```

- [ ] **Step 4: Eseguire il test e verificare che passi**

Run:
```bash
pytest tests/test_config.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "Aggiunge config.py con percorsi e validazione cartelle consentite"
```

---

### Task 2: App Flask skeleton + `GET /`

**Files:**
- Create: `app.py`
- Create: `templates/index.html`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `PERCORSO_DB_DEFAULT`, `CARTELLA_SESSIONI_DEFAULT`, `CARTELLE_ARCHIVIO_EXTRA` da `config.py` (Task 1); `connetti`, `init_db` da `db/database.py` (Fase 1).
- Produces:
  - `crea_app(percorso_db: Path = PERCORSO_DB_DEFAULT, cartella_sessioni: Path = CARTELLA_SESSIONI_DEFAULT) -> Flask` — factory che crea e configura l'app. Imposta `app.config["PERCORSO_DB"]`, `app.config["CARTELLA_SESSIONI"]`, `app.config["CARTELLE_CONSENTITE_RIFERIMENTI"]` (= `[CARTELLA_SESSIONI, *CARTELLE_ARCHIVIO_EXTRA]`). Chiama `init_db` sul percorso DB. Route `GET /` che renderizza `templates/index.html` passando la lista dei nomi già presenti in DB (per l'autocomplete lato client).
  - Route successive (`/analizza`, `/conferma`, `/riferimento`) verranno aggiunte nei Task 3-5, tutte nested dentro `crea_app`.

- [ ] **Step 1: Scrivere il test che fallisce**

Create `tests/test_app.py`:

```python
import pytest

from app import crea_app
from db.database import connetti, trova_o_crea_persona


@pytest.fixture
def app(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    cartella_sessioni = tmp_path / "sessioni"
    return crea_app(percorso_db=percorso_db, cartella_sessioni=cartella_sessioni)


@pytest.fixture
def client(app):
    return app.test_client()


def test_index_restituisce_200(client):
    risposta = client.get("/")
    assert risposta.status_code == 200


def test_index_include_zona_drop(client):
    risposta = client.get("/")
    assert b'id="zona-drop"' in risposta.data


def test_index_include_nomi_esistenti(app, client):
    conn = connetti(app.config["PERCORSO_DB"])
    trova_o_crea_persona(conn, "Mario Rossi")
    conn.close()

    risposta = client.get("/")

    assert b"Mario Rossi" in risposta.data
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run:
```bash
pytest tests/test_app.py -v
```

Expected: FAIL con `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Creare templates/index.html**

Create `templates/index.html`:

```html
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>Volti - Revisione</title>
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: 40px auto; }
        #zona-drop {
            border: 2px dashed #888;
            border-radius: 8px;
            padding: 40px;
            text-align: center;
            cursor: pointer;
        }
        #zona-drop.drag-over { border-color: #333; background: #f0f0f0; }
        .crop-volto { max-width: 150px; margin: 8px; border-radius: 4px; }
        .miniatura-riferimento { max-width: 80px; vertical-align: middle; margin-right: 8px; }
        .candidato { cursor: pointer; padding: 8px; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 8px; }
        .errore { color: #c00; }
        .successo { color: #080; }
    </style>
</head>
<body>
    <h1>Riconoscimento volti</h1>
    <div id="zona-drop">Trascina qui uno screenshot del volto da identificare, o clicca per selezionarlo</div>
    <div id="risultato"></div>
    <script>
        const NOMI_ESISTENTI = {{ nomi_esistenti_json | safe }};
    </script>
    <script src="{{ url_for('static', filename='app.js') }}"></script>
</body>
</html>
```

- [ ] **Step 4: Implementare app.py**

Create `app.py`:

```python
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
```

- [ ] **Step 5: Eseguire il test e verificare che passi**

Run:
```bash
pytest tests/test_app.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add app.py templates/index.html tests/test_app.py
git commit -m "Aggiunge scheletro app Flask con route GET / e pagina base"
```

---

### Task 3: `POST /analizza`

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `rileva_volti`, `VoltoRilevato` da `core/volti.py` (Fase 1); `calcola_candidati`, `classifica_match`, `Candidato` da `core/matching.py` (Fase 3); `connetti` da `db/database.py`.
- Produces: route `POST /analizza` che riceve un file multipart (`request.files["immagine"]`) e ritorna JSON:
  ```json
  {
    "volti": [
      {
        "vettore": [0.1, 0.2, ...],      // 512 float, embedding del volto
        "crop_base64": "...",             // JPEG del volto ritagliato, base64
        "stato": "certo" | "ambiguo" | "sconosciuto",
        "candidati": [
          {"nome": "...", "punteggio": 0.9, "foto_riferimento": "..."}
        ]
      }
    ]
  }
  ```
  400 con `{"errore": "..."}` se manca il file o l'immagine non è leggibile.

- [ ] **Step 1: Scrivere i test che falliscono**

Add to `tests/test_app.py` (in cima al file, aggiungere gli import necessari):

```python
import numpy as np
from PIL import Image

from core.volti import VoltoRilevato
from db.database import salva_embedding
```

Add at the end of `tests/test_app.py`:

```python
def _vettore_normalizzato(seed: int) -> np.ndarray:
    """Genera un vettore casuale riproducibile e normalizzato L2 (come un vero embedding)."""
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    return v / np.linalg.norm(v)


def _crea_immagine_prova(percorso, dimensione=(100, 100)):
    Image.new("RGB", dimensione, color="blue").save(percorso)


def test_analizza_nessun_volto(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.rileva_volti", lambda percorso: [])
    percorso_immagine = tmp_path / "screenshot.jpg"
    _crea_immagine_prova(percorso_immagine)

    with open(percorso_immagine, "rb") as f:
        risposta = client.post("/analizza", data={"immagine": (f, "screenshot.jpg")})

    assert risposta.status_code == 200
    assert risposta.get_json()["volti"] == []


def test_analizza_un_volto_certo(app, client, tmp_path, monkeypatch):
    conn = connetti(app.config["PERCORSO_DB"])
    vettore = _vettore_normalizzato(seed=1)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    for i in range(3):
        salva_embedding(conn, id_mario, vettore, f"mario_{i}.jpg", "batch_iniziale")
    conn.close()

    volto_finto = VoltoRilevato(vettore=vettore, bbox=(10, 10, 50, 50), score=0.9)
    monkeypatch.setattr("app.rileva_volti", lambda percorso: [volto_finto])

    percorso_immagine = tmp_path / "screenshot.jpg"
    _crea_immagine_prova(percorso_immagine)

    with open(percorso_immagine, "rb") as f:
        risposta = client.post("/analizza", data={"immagine": (f, "screenshot.jpg")})

    dati = risposta.get_json()
    assert len(dati["volti"]) == 1
    volto = dati["volti"][0]
    assert volto["stato"] == "certo"
    assert volto["candidati"][0]["nome"] == "Mario Rossi"
    assert len(volto["vettore"]) == 512


def test_analizza_piu_volti(client, tmp_path, monkeypatch):
    v1 = _vettore_normalizzato(seed=1)
    v2 = _vettore_normalizzato(seed=2)
    monkeypatch.setattr(
        "app.rileva_volti",
        lambda percorso: [
            VoltoRilevato(vettore=v1, bbox=(0, 0, 40, 40), score=0.9),
            VoltoRilevato(vettore=v2, bbox=(50, 50, 90, 90), score=0.9),
        ],
    )
    percorso_immagine = tmp_path / "screenshot.jpg"
    _crea_immagine_prova(percorso_immagine)

    with open(percorso_immagine, "rb") as f:
        risposta = client.post("/analizza", data={"immagine": (f, "screenshot.jpg")})

    assert len(risposta.get_json()["volti"]) == 2


def test_analizza_immagine_non_leggibile(client, tmp_path, monkeypatch):
    def _solleva_valueerror(percorso):
        raise ValueError("immagine non leggibile")

    monkeypatch.setattr("app.rileva_volti", _solleva_valueerror)
    percorso_immagine = tmp_path / "screenshot.jpg"
    _crea_immagine_prova(percorso_immagine)

    with open(percorso_immagine, "rb") as f:
        risposta = client.post("/analizza", data={"immagine": (f, "screenshot.jpg")})

    assert risposta.status_code == 400


def test_analizza_nessun_file_inviato(client):
    risposta = client.post("/analizza", data={})
    assert risposta.status_code == 400
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run:
```bash
pytest tests/test_app.py -v -k analizza
```

Expected: FAIL con `404 NOT FOUND` (la route non esiste ancora) o `AttributeError`.

- [ ] **Step 3: Implementare la route /analizza**

Modify `app.py`. Aggiungere questi import in cima al file:

```python
import base64
import os
import tempfile

import cv2
```

(mantenere gli import già presenti da Task 2, aggiungendo questi). Sostituire la riga di import esistente `from flask import Flask, render_template` con:

```python
from flask import Flask, jsonify, render_template, request
```

E aggiungere:

```python
from core.matching import calcola_candidati, classifica_match
from core.volti import rileva_volti
```

Dentro `crea_app`, subito dopo la route `index()`, aggiungere:

```python
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
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run:
```bash
pytest tests/test_app.py -v
```

Expected: tutti i test passano (8 totali: 3 di Task 2 + 5 di questo task).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "Aggiunge route POST /analizza: rilevamento volti + candidati"
```

---

### Task 4: `POST /conferma`

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `trova_o_crea_persona`, `salva_embedding` da `db/database.py` (Fase 1/2).
- Produces: route `POST /conferma` che riceve JSON `{"nome": str, "vettore": list[float], "screenshot_base64": str}` e ritorna `{"ok": true}` (200) o `{"errore": "..."}` (400). Salva lo screenshot in `<cartella_sessioni>/conferme/<uuid>.jpg`, crea/trova la persona, salva l'embedding con `fonte='conferma_editing'` e `foto_origine` = path dello screenshot salvato.

- [ ] **Step 1: Scrivere i test che falliscono**

Add to `tests/test_app.py` (aggiungere import in cima):

```python
import base64
import uuid
from pathlib import Path
```

Add at the end of `tests/test_app.py`:

```python
def test_conferma_nome_nuovo_crea_persona_ed_embedding(app, client):
    vettore = _vettore_normalizzato(seed=7).tolist()
    screenshot_b64 = base64.b64encode(b"contenuto finto jpg").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={
            "nome": "Nuova Persona",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
        },
    )

    assert risposta.status_code == 200
    assert risposta.get_json()["ok"] is True

    conn = connetti(app.config["PERCORSO_DB"])
    riga_persona = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Nuova Persona",)
    ).fetchone()
    assert riga_persona is not None
    riga_embedding = conn.execute(
        "SELECT foto_origine, fonte FROM embedding WHERE person_id = ?",
        (riga_persona[0],),
    ).fetchone()
    conn.close()

    assert riga_embedding[1] == "conferma_editing"
    assert Path(riga_embedding[0]).exists()


def test_conferma_nome_esistente_non_duplica_persona(app, client):
    conn = connetti(app.config["PERCORSO_DB"])
    id_esistente = trova_o_crea_persona(conn, "Mario Rossi")
    conn.close()

    vettore = _vettore_normalizzato(seed=8).tolist()
    screenshot_b64 = base64.b64encode(b"contenuto finto jpg").decode("ascii")

    client.post(
        "/conferma",
        json={
            "nome": "Mario Rossi",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
        },
    )

    conn = connetti(app.config["PERCORSO_DB"])
    persone = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Mario Rossi",)
    ).fetchall()
    embedding_rows = conn.execute(
        "SELECT id FROM embedding WHERE person_id = ?", (id_esistente,)
    ).fetchall()
    conn.close()

    assert len(persone) == 1
    assert len(embedding_rows) == 1


def test_conferma_nome_vuoto_ritorna_400(client):
    vettore = _vettore_normalizzato(seed=9).tolist()
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={"nome": "   ", "vettore": vettore, "screenshot_base64": screenshot_b64},
    )

    assert risposta.status_code == 400
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run:
```bash
pytest tests/test_app.py -v -k conferma
```

Expected: FAIL con `404 NOT FOUND`.

- [ ] **Step 3: Implementare la route /conferma**

Modify `app.py`. Aggiungere import in cima al file:

```python
import uuid

import numpy as np

from db.database import connetti, init_db, salva_embedding, trova_o_crea_persona
```

(sostituire l'import esistente `from db.database import connetti, init_db` con quello sopra, che include anche `salva_embedding` e `trova_o_crea_persona`).

Dentro `crea_app`, subito dopo la route `analizza()`, aggiungere:

```python
    @app.post("/conferma")
    def conferma():
        dati = request.get_json(silent=True) or {}
        nome = (dati.get("nome") or "").strip()
        vettore_lista = dati.get("vettore")
        screenshot_base64 = dati.get("screenshot_base64")

        if not nome:
            return jsonify(errore="nome mancante"), 400
        if not vettore_lista or not screenshot_base64:
            return jsonify(errore="dati mancanti"), 400

        vettore = np.array(vettore_lista, dtype=np.float32)

        cartella_conferme = app.config["CARTELLA_SESSIONI"] / "conferme"
        cartella_conferme.mkdir(parents=True, exist_ok=True)
        percorso_screenshot = cartella_conferme / f"{uuid.uuid4().hex}.jpg"
        percorso_screenshot.write_bytes(base64.b64decode(screenshot_base64))

        conn = connetti(app.config["PERCORSO_DB"])
        person_id = trova_o_crea_persona(conn, nome)
        salva_embedding(
            conn, person_id, vettore, str(percorso_screenshot), "conferma_editing"
        )
        conn.close()

        return jsonify(ok=True)
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run:
```bash
pytest tests/test_app.py -v
```

Expected: tutti i test passano (11 totali: 8 precedenti + 3 di questo task).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "Aggiunge route POST /conferma: salva screenshot, persona ed embedding"
```

---

### Task 5: `GET /riferimento`

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `percorso_consentito` da `config.py` (Task 1).
- Produces: route `GET /riferimento?path=<percorso>` che serve il file immagine se `path` è contenuto in una delle cartelle in `app.config["CARTELLE_CONSENTITE_RIFERIMENTI"]`. Ritorna 400 se manca `path`, 403 se il path non è consentito, 404 se il file non esiste, altrimenti 200 con il contenuto del file.

- [ ] **Step 1: Scrivere i test che falliscono**

Add at the end of `tests/test_app.py`:

```python
def test_riferimento_serve_file_in_cartella_consentita(app, client):
    cartella_conferme = app.config["CARTELLA_SESSIONI"] / "conferme"
    cartella_conferme.mkdir(parents=True)
    percorso_file = cartella_conferme / "riferimento.jpg"
    _crea_immagine_prova(percorso_file)

    risposta = client.get(f"/riferimento?path={percorso_file}")

    assert risposta.status_code == 200
    assert len(risposta.data) > 0


def test_riferimento_403_se_fuori_cartelle_consentite(client, tmp_path):
    cartella_esterna = tmp_path / "fuori"
    cartella_esterna.mkdir()
    percorso_file = cartella_esterna / "riferimento.jpg"
    _crea_immagine_prova(percorso_file)

    risposta = client.get(f"/riferimento?path={percorso_file}")

    assert risposta.status_code == 403


def test_riferimento_404_se_file_non_esiste(app, client):
    cartella_conferme = app.config["CARTELLA_SESSIONI"] / "conferme"
    cartella_conferme.mkdir(parents=True)
    percorso_inesistente = cartella_conferme / "non_esiste.jpg"

    risposta = client.get(f"/riferimento?path={percorso_inesistente}")

    assert risposta.status_code == 404


def test_riferimento_400_se_path_mancante(client):
    risposta = client.get("/riferimento")
    assert risposta.status_code == 400
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run:
```bash
pytest tests/test_app.py -v -k riferimento
```

Expected: FAIL con `404 NOT FOUND` (route non ancora definita) per i primi tre test (comportamento coincidentalmente simile ma per motivo sbagliato: la route non esiste), e il quarto fallisce allo stesso modo.

- [ ] **Step 3: Implementare la route /riferimento**

Modify `app.py`. Aggiungere import in cima al file:

```python
from flask import Flask, jsonify, render_template, request, send_file

from config import (
    CARTELLA_SESSIONI_DEFAULT,
    CARTELLE_ARCHIVIO_EXTRA,
    PERCORSO_DB_DEFAULT,
    percorso_consentito,
)
```

(sostituire l'import esistente da `config` con quello sopra, che include anche `percorso_consentito`).

Dentro `crea_app`, subito dopo la route `conferma()`, aggiungere:

```python
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
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run:
```bash
pytest tests/test_app.py -v
```

Expected: tutti i test passano (15 totali: 11 precedenti + 4 di questo task).

- [ ] **Step 5: Eseguire l'intera suite di test del progetto**

Run:
```bash
pytest tests/ -v
```

Expected: tutti i test passano (49 totali: 31 pre-esistenti da Fasi 1-3 + 3 in `test_config.py` + 15 in `test_app.py` [3 index + 5 analizza + 3 conferma + 4 riferimento]), 0 failed.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "Aggiunge route GET /riferimento con validazione path"
```

---

### Task 6: Interfaccia client (`static/app.js`)

**Files:**
- Create: `static/app.js`

**Interfaces:**
- Consumes: endpoint `/analizza`, `/conferma`, `/riferimento` (Task 3-5); variabile globale `NOMI_ESISTENTI` (array di stringhe) definita inline in `templates/index.html` (Task 2); elementi DOM `#zona-drop` e `#risultato` (Task 2).
- Produces: comportamento client-side completo del flusso drag&drop → analisi → conferma. Nessuna interfaccia consumata da altri task (foglia dell'albero delle dipendenze).

Non essendoci un framework di test per JS in questo progetto (deciso nel design, coerente con "niente framework frontend, niente build step"), questo task si verifica manualmente in un browser reale nel Task 7, non con pytest.

- [ ] **Step 1: Creare static/app.js**

Create `static/app.js`:

```javascript
const zonaDrop = document.getElementById("zona-drop");
const risultatoDiv = document.getElementById("risultato");

let screenshotBase64 = null;

zonaDrop.addEventListener("dragover", (evento) => {
    evento.preventDefault();
    zonaDrop.classList.add("drag-over");
});

zonaDrop.addEventListener("dragleave", () => {
    zonaDrop.classList.remove("drag-over");
});

zonaDrop.addEventListener("drop", (evento) => {
    evento.preventDefault();
    zonaDrop.classList.remove("drag-over");
    const file = evento.dataTransfer.files[0];
    if (file) {
        gestisciFile(file);
    }
});

zonaDrop.addEventListener("click", () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = () => {
        if (input.files[0]) {
            gestisciFile(input.files[0]);
        }
    };
    input.click();
});

function gestisciFile(file) {
    const lettore = new FileReader();
    lettore.onload = () => {
        screenshotBase64 = lettore.result.split(",")[1];
    };
    lettore.readAsDataURL(file);

    const formData = new FormData();
    formData.append("immagine", file);

    risultatoDiv.innerHTML = "<p>Analisi in corso...</p>";

    fetch("/analizza", { method: "POST", body: formData })
        .then((risposta) => risposta.json().then((dati) => ({ ok: risposta.ok, dati })))
        .then(({ ok, dati }) => {
            if (!ok) {
                risultatoDiv.innerHTML = `<p class="errore">${dati.errore}</p>`;
                return;
            }
            mostraVolti(dati.volti);
        });
}

function mostraVolti(volti) {
    if (volti.length === 0) {
        risultatoDiv.innerHTML =
            '<p class="errore">Nessun volto rilevato. Ritaglia lo screenshot su un volto.</p>';
        return;
    }
    if (volti.length === 1) {
        mostraRisultatoVolto(volti[0]);
        return;
    }
    risultatoDiv.innerHTML = "<p>Piu' volti rilevati, scegli quale identificare:</p>";
    const contenitore = document.createElement("div");
    contenitore.id = "scelta-volti";
    volti.forEach((volto) => {
        const img = document.createElement("img");
        img.src = "data:image/jpeg;base64," + volto.crop_base64;
        img.className = "crop-volto";
        img.addEventListener("click", () => mostraRisultatoVolto(volto));
        contenitore.appendChild(img);
    });
    risultatoDiv.appendChild(contenitore);
}

function mostraRisultatoVolto(volto) {
    risultatoDiv.innerHTML = "";

    const anteprima = document.createElement("img");
    anteprima.src = "data:image/jpeg;base64," + volto.crop_base64;
    anteprima.className = "crop-volto";
    risultatoDiv.appendChild(anteprima);

    if (volto.stato === "certo") {
        mostraCerto(volto);
    } else if (volto.stato === "ambiguo") {
        mostraAmbiguo(volto);
    } else {
        mostraNomeLibero(volto);
    }
}

function mostraCerto(volto) {
    const candidato = volto.candidati[0];
    const blocco = document.createElement("div");
    blocco.innerHTML = `
        <p>${candidato.nome} (${candidato.punteggio.toFixed(3)})</p>
        <button id="btn-conferma">Conferma</button>
        <a href="#" id="link-correggi">non e' lui, correggi</a>
    `;
    risultatoDiv.appendChild(blocco);

    document.getElementById("btn-conferma").addEventListener("click", (evento) => {
        evento.target.disabled = true;
        confermaNome(volto, candidato.nome);
    });
    document.getElementById("link-correggi").addEventListener("click", (evento) => {
        evento.preventDefault();
        mostraNomeLibero(volto);
    });
}

function mostraAmbiguo(volto) {
    const intestazione = document.createElement("p");
    intestazione.textContent = "Match ambiguo, scegli il candidato giusto:";
    risultatoDiv.appendChild(intestazione);

    const lista = document.createElement("div");
    lista.id = "lista-candidati";
    volto.candidati.forEach((candidato) => {
        const voce = document.createElement("div");
        voce.className = "candidato";
        voce.innerHTML = `
            <img src="/riferimento?path=${encodeURIComponent(candidato.foto_riferimento)}" class="miniatura-riferimento">
            <span>${candidato.nome} (${candidato.punteggio.toFixed(3)})</span>
        `;
        voce.addEventListener("click", () => confermaNome(volto, candidato.nome));
        lista.appendChild(voce);
    });
    risultatoDiv.appendChild(lista);

    const linkAltro = document.createElement("a");
    linkAltro.href = "#";
    linkAltro.textContent = "nessuno di questi, altro nome";
    linkAltro.addEventListener("click", (evento) => {
        evento.preventDefault();
        mostraNomeLibero(volto);
    });
    risultatoDiv.appendChild(linkAltro);
}

function mostraNomeLibero(volto) {
    const esistente = document.getElementById("form-nome-libero");
    if (esistente) {
        esistente.remove();
    }

    const form = document.createElement("div");
    form.id = "form-nome-libero";
    form.innerHTML = `
        <input type="text" id="input-nome" list="lista-nomi-esistenti" placeholder="Nome persona">
        <datalist id="lista-nomi-esistenti">
            ${NOMI_ESISTENTI.map((nome) => `<option value="${nome}"></option>`).join("")}
        </datalist>
        <button id="btn-salva-nome">Salva nome</button>
    `;
    risultatoDiv.appendChild(form);

    document.getElementById("btn-salva-nome").addEventListener("click", (evento) => {
        const nome = document.getElementById("input-nome").value.trim();
        if (!nome) {
            return;
        }
        evento.target.disabled = true;
        confermaNome(volto, nome);
    });
}

function confermaNome(volto, nome) {
    fetch("/conferma", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            nome: nome,
            vettore: volto.vettore,
            screenshot_base64: screenshotBase64,
        }),
    })
        .then((risposta) => risposta.json())
        .then((dati) => {
            if (dati.ok) {
                if (!NOMI_ESISTENTI.includes(nome)) {
                    NOMI_ESISTENTI.push(nome);
                }
                risultatoDiv.innerHTML = `<p class="successo">Salvato: ${nome}</p>`;
                setTimeout(() => {
                    risultatoDiv.innerHTML = "";
                }, 1500);
            } else {
                risultatoDiv.innerHTML = `<p class="errore">${dati.errore}</p>`;
            }
        });
}
```

- [ ] **Step 2: Commit**

```bash
git add static/app.js
git commit -m "Aggiunge interfaccia client: drag&drop, stati certo/ambiguo/sconosciuto"
```

---

### Task 7: Verifica end-to-end

**Files:**
- Nessun file di codice nuovo. Verifica l'intera fase (Task 1-6) contro il database reale già popolato in Fase 2/3.

**Interfaces:**
- Consumes: `crea_app` da `app.py` (Task 2-5).

- [ ] **Step 1: Eseguire l'intera suite di test**

Run (con venv attivo, dalla root del progetto):
```bash
source venv/bin/activate
pytest tests/ -v
```

Expected: tutti i test passano, 0 failed.

- [ ] **Step 2: Avviare il server contro il DB reale**

Run in un terminale separato (o in background):
```bash
VOLTI_NO_BROWSER=1 python app.py
```

Expected: il server si avvia su `http://127.0.0.1:5000/` senza errori (nessun tentativo di aprire un browser, dato `VOLTI_NO_BROWSER=1`).

- [ ] **Step 3: Verificare /analizza via script su un volto reale già noto in DB (atteso: "certo")**

In un altro terminale, con lo stesso venv attivo:
```bash
python3 -c "
import requests

with open('/Users/pietrodaprano/Desktop/_prova export per nomi/PI2_3003_WzqHBTgl.jpg', 'rb') as f:
    risposta = requests.post('http://127.0.0.1:5000/analizza', files={'immagine': f})

dati = risposta.json()
volto = dati['volti'][0]
print('stato:', volto['stato'])
print('primo candidato:', volto['candidati'][0]['nome'], volto['candidati'][0]['punteggio'])
"
```

Expected: `stato: certo`, primo candidato `Nicky Passarella` con punteggio vicino a 1.0 (stessa foto già nel DB, coerente con la verifica manuale di Fase 3 Task 2).

- [ ] **Step 4: Verificare /conferma con un nome nuovo, poi controllare il DB**

```bash
python3 -c "
import base64
import requests

with open('/Users/pietrodaprano/Desktop/_prova export per nomi/PI2_3003_WzqHBTgl.jpg', 'rb') as f:
    contenuto = f.read()

risposta_analizza = requests.post(
    'http://127.0.0.1:5000/analizza',
    files={'immagine': ('screenshot.jpg', contenuto)},
)
volto = risposta_analizza.json()['volti'][0]

risposta_conferma = requests.post(
    'http://127.0.0.1:5000/conferma',
    json={
        'nome': 'Persona Di Verifica E2E',
        'vettore': volto['vettore'],
        'screenshot_base64': base64.b64encode(contenuto).decode('ascii'),
    },
)
print(risposta_conferma.json())
"
```

Expected: `{'ok': True}`.

Poi verificare che sia stato salvato:
```bash
python3 -c "
from db.database import connetti

conn = connetti('db/volti.db')
riga = conn.execute(
    \"SELECT p.nome, e.fonte, e.foto_origine FROM embedding e \"
    \"JOIN persone p ON p.id = e.person_id WHERE p.nome = ?\",
    ('Persona Di Verifica E2E',),
).fetchone()
conn.close()
print(riga)
"
```

Expected: una riga con `fonte='conferma_editing'` e `foto_origine` che punta a un file esistente sotto `sessioni/conferme/`.

**Nota:** questo passaggio crea una persona di test reale nel DB di produzione (`db/volti.db`). Va rimossa manualmente a fine verifica (vedi Step 6).

- [ ] **Step 5: Verifica manuale in browser (richiede intervento umano — non automatizzabile)**

Con il server ancora avviato, apri `http://127.0.0.1:5000/` in un browser. Fai uno screenshot reale di un volto (noto o sconosciuto) e trascinalo nella zona di drop. Verifica che:
- la zona mostri "Analisi in corso..." e poi il risultato;
- se il volto è noto (score alto): appaia il nome proposto con bottone "Conferma" e link "non è lui, correggi";
- se ambiguo: appaiano 2-3 candidati con miniatura cliccabile;
- se sconosciuto: appaia il campo testo con autocomplete (digita una lettera di un nome già in DB e verifica che compaia il suggerimento);
- dopo la conferma, la UI mostri "Salvato: ..." e si resetti dopo ~1.5s pronta per il prossimo screenshot.

- [ ] **Step 6: Pulizia dati di verifica**

Rimuovi la persona di test creata allo Step 4:
```bash
python3 -c "
from db.database import connetti

conn = connetti('db/volti.db')
conn.execute(\"DELETE FROM embedding WHERE person_id IN (SELECT id FROM persone WHERE nome = 'Persona Di Verifica E2E')\")
conn.execute(\"DELETE FROM persone WHERE nome = 'Persona Di Verifica E2E'\")
conn.commit()
conn.close()
print('pulizia completata')
"
```

Rimuovi anche eventuali file creati in `sessioni/conferme/` durante la verifica (cartella già esclusa da git, nessun rischio di commit accidentale).

Ferma il server (`Ctrl+C` nel terminale dove è in esecuzione).

- [ ] **Step 7: Scrivere un breve riepilogo nel report**

Scrivi i risultati reali (stato, nomi, punteggi ottenuti, esito della verifica manuale in browser) in `.superpowers/sdd/task-7-fase4-report.md` (nuovo file, scratch, già escluso da git). Non serve commit di codice per questo task.

## Definizione di "Fase 4 completata"

`pytest tests/ -v` passa tutti i test. Il server Flask si avvia con `python app.py`. Una foto reale già nel DB, inviata a `/analizza`, ritorna il nome corretto con stato "certo". Una conferma via `/conferma` crea correttamente persona + embedding con `fonte='conferma_editing'` e salva lo screenshot su disco. La verifica manuale in browser conferma che drag&drop, i tre stati (certo/ambiguo/sconosciuto), il caso multi-volto e l'autocomplete funzionano come da design.
