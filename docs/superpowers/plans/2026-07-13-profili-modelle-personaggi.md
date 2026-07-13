# Profili separati modelle/personaggi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Selezionare il profilo (modelle/personaggi) all'avvio con `python app.py modelle|personaggi`, ciascuno con il proprio DB, cartella sessioni, porta e colore di sfondo, riusando l'architettura già parametrica di `crea_app()`.

**Architecture:** Un dizionario `PROFILI` in `config.py` mappa il nome del profilo ai suoi parametri (db, sessioni, porta, colore). `crea_app()` guadagna un parametro `colore_sfondo` opzionale, propagato al template. Il blocco `__main__` di `app.py` legge `sys.argv[1]`, risolve il profilo, e lancia l'app coi parametri giusti. Nessuna modifica alle route esistenti o alla logica di matching/detection.

**Tech Stack:** Stesso delle fasi precedenti (Flask, SQLite). Nessuna nuova dipendenza.

## Global Constraints

- Nomi di file, variabili, funzioni e commenti in italiano.
- Nessuna nuova dipendenza esterna.
- Non modificare `core/volti.py`, `core/matching.py`, `db/database.py`, né la logica delle route `/analizza`, `/conferma`, `/riferimento` (solo `crea_app()` e `index()` cambiano, per il parametro colore).
- `db/volti.db` esistente (22 persone reali) **non va rinominato né spostato** — resta il file del profilo `personaggi`.
- Porte: `modelle` → 5001, `personaggi` → 5002 (evitano la 5000, che confligge con AirPlay Receiver su macOS).
- Colori esatti: `modelle` → `"#ffe4e1"` (rosso molto chiaro), `personaggi` → `"#b0e0e6"` (azzurro carta da zucchero).
- Design di riferimento: `docs/superpowers/specs/2026-07-13-profili-modelle-personaggi-design.md`.

---

### Task 1: Registro profili (`config.py`)

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `RADICE_PROGETTO`, `PERCORSO_DB_DEFAULT`, `CARTELLA_SESSIONI_DEFAULT` (già presenti in `config.py`).
- Produces:
  - `PROFILI: dict[str, dict]` — chiavi `"modelle"` e `"personaggi"`, ciascuna con `"db": Path`, `"sessioni": Path`, `"porta": int`, `"colore": str`.
  - `risolvi_profilo(nome: str) -> dict` — ritorna `PROFILI[nome]`; solleva `ValueError` con messaggio leggibile se `nome` non è `"modelle"` o `"personaggi"`.

- [ ] **Step 1: Scrivere il test che fallisce**

Add to `tests/test_config.py` (in cima al file, aggiungere l'import):

```python
from config import PROFILI, percorso_consentito, risolvi_profilo
```

(sostituire la riga `from config import percorso_consentito` esistente con quella sopra).

Add at the end of `tests/test_config.py`:

```python
def test_profili_modelle_ha_i_campi_attesi():
    profilo = PROFILI["modelle"]
    assert isinstance(profilo["db"], Path)
    assert isinstance(profilo["sessioni"], Path)
    assert profilo["porta"] == 5001
    assert profilo["colore"] == "#ffe4e1"


def test_profili_personaggi_punta_al_db_esistente():
    from config import PERCORSO_DB_DEFAULT

    profilo = PROFILI["personaggi"]
    assert profilo["db"] == PERCORSO_DB_DEFAULT
    assert profilo["porta"] == 5002
    assert profilo["colore"] == "#b0e0e6"


def test_profili_modelle_e_personaggi_hanno_sessioni_diverse():
    assert PROFILI["modelle"]["sessioni"] != PROFILI["personaggi"]["sessioni"]


def test_risolvi_profilo_ritorna_il_profilo_richiesto():
    assert risolvi_profilo("modelle") == PROFILI["modelle"]
    assert risolvi_profilo("personaggi") == PROFILI["personaggi"]


def test_risolvi_profilo_nome_sconosciuto_solleva_valueerror():
    with pytest.raises(ValueError):
        risolvi_profilo("altro")
```

Add `import pytest` at the top of `tests/test_config.py` if not already present (check the current imports first — the file currently only imports `from pathlib import Path` and `from config import percorso_consentito`; add `import pytest` as a new line before those).

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run (con venv attivo, dalla root del progetto):
```bash
source venv/bin/activate
pytest tests/test_config.py -v
```

Expected: FAIL con `ImportError: cannot import name 'PROFILI' from 'config'`.

- [ ] **Step 3: Implementare PROFILI e risolvi_profilo in config.py**

Modify `config.py`. Aggiungere alla fine del file (dopo la funzione `percorso_consentito` esistente):

```python
PROFILI: dict[str, dict] = {
    "modelle": {
        "db": RADICE_PROGETTO / "db" / "volti_modelle.db",
        "sessioni": RADICE_PROGETTO / "sessioni" / "modelle",
        "porta": 5001,
        "colore": "#ffe4e1",
    },
    "personaggi": {
        "db": PERCORSO_DB_DEFAULT,
        "sessioni": RADICE_PROGETTO / "sessioni" / "personaggi",
        "porta": 5002,
        "colore": "#b0e0e6",
    },
}


def risolvi_profilo(nome: str) -> dict:
    """Ritorna la configurazione (db, sessioni, porta, colore) del profilo richiesto.

    Solleva ValueError se nome non e' un profilo valido."""
    if nome not in PROFILI:
        raise ValueError(
            f"Profilo sconosciuto: {nome!r}. Usa 'modelle' o 'personaggi'."
        )
    return PROFILI[nome]
```

- [ ] **Step 4: Eseguire il test e verificare che passi**

Run:
```bash
pytest tests/test_config.py -v
```

Expected: `8 passed` (3 test pre-esistenti da Fase 4 + 5 nuovi).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "Aggiunge registro profili modelle/personaggi in config.py"
```

---

### Task 2: Colore parametrico + selezione profilo all'avvio (`app.py`, `templates/index.html`)

**Files:**
- Modify: `app.py`
- Modify: `templates/index.html`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `PROFILI`, `risolvi_profilo` da `config.py` (Task 1).
- Produces:
  - `crea_app(percorso_db=..., cartella_sessioni=..., colore_sfondo: str = "#ffffff") -> Flask` — nuovo parametro opzionale, propagato a `app.config["COLORE_SFONDO"]` e da lì al template `index.html` in fase di render.
  - Blocco `if __name__ == "__main__":` aggiornato: richiede `sys.argv[1]` in `{"modelle", "personaggi"}`, altrimenti stampa l'uso corretto ed esce con `sys.exit(1)`; poi lancia l'app sui parametri del profilo risolto (porta inclusa).

- [ ] **Step 1: Scrivere il test che fallisce**

Add to `tests/test_app.py`, alla fine del file:

```python
def test_index_usa_colore_sfondo_di_default(client):
    risposta = client.get("/")
    assert b"#ffffff" in risposta.data


def test_index_usa_colore_sfondo_personalizzato(tmp_path):
    app_personalizzata = crea_app(
        percorso_db=tmp_path / "volti_test.db",
        cartella_sessioni=tmp_path / "sessioni",
        colore_sfondo="#ffe4e1",
    )
    client_personalizzato = app_personalizzata.test_client()

    risposta = client_personalizzato.get("/")

    assert b"#ffe4e1" in risposta.data
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run:
```bash
pytest tests/test_app.py -v -k colore_sfondo
```

Expected: FAIL — `test_index_usa_colore_sfondo_di_default` fallisce perché `#ffffff` non compare ancora nell'HTML (il parametro non esiste), `test_index_usa_colore_sfondo_personalizzato` fallisce con `TypeError: crea_app() got an unexpected keyword argument 'colore_sfondo'`.

- [ ] **Step 3: Aggiungere colore_sfondo a crea_app()**

Modify `app.py`. Nella firma di `crea_app`, aggiungere il nuovo parametro:

```python
def crea_app(
    percorso_db: Path = PERCORSO_DB_DEFAULT,
    cartella_sessioni: Path = CARTELLA_SESSIONI_DEFAULT,
    colore_sfondo: str = "#ffffff",
) -> Flask:
```

Subito dopo `app.config["CARTELLE_CONSENTITE_RIFERIMENTI"] = [...]` (già presente), aggiungere:

```python
    app.config["COLORE_SFONDO"] = colore_sfondo
```

Nella route `index()`, modificare la chiamata a `render_template` per includere il nuovo parametro:

```python
        return render_template(
            "index.html",
            nomi_esistenti_json=json.dumps(nomi_esistenti),
            colore_sfondo=app.config["COLORE_SFONDO"],
        )
```

- [ ] **Step 4: Applicare il colore nel template**

Modify `templates/index.html`. Sostituire:

```html
<body>
```

con:

```html
<body style="background-color: {{ colore_sfondo }};">
```

- [ ] **Step 5: Eseguire il test e verificare che passi**

Run:
```bash
pytest tests/test_app.py -v -k colore_sfondo
```

Expected: `2 passed`.

- [ ] **Step 6: Aggiornare il blocco __main__ per la selezione del profilo**

Modify `app.py`. Aggiungere `import sys` in cima al file, tra gli import esistenti (ordine alfabetico con gli altri import stdlib: `os`, `sys`, `tempfile`, `uuid`, `webbrowser`).

Sostituire l'import da `config` esistente:

```python
from config import (
    CARTELLA_SESSIONI_DEFAULT,
    CARTELLE_ARCHIVIO_EXTRA,
    PERCORSO_DB_DEFAULT,
    percorso_consentito,
)
```

con:

```python
from config import (
    CARTELLA_SESSIONI_DEFAULT,
    CARTELLE_ARCHIVIO_EXTRA,
    PERCORSO_DB_DEFAULT,
    percorso_consentito,
    risolvi_profilo,
)
```

Sostituire il blocco finale:

```python
if __name__ == "__main__":
    app = crea_app()
    if os.environ.get("VOLTI_NO_BROWSER") != "1":
        webbrowser.open("http://127.0.0.1:5000/")
    app.run(port=5000)
```

con:

```python
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
    )
    if os.environ.get("VOLTI_NO_BROWSER") != "1":
        webbrowser.open(f"http://127.0.0.1:{profilo['porta']}/")
    app.run(port=profilo["porta"])
```

Non c'è un test automatico per questo blocco (come per il blocco `__main__` già esistente prima di questo piano, non testato direttamente) — la verifica è manuale, nel Task 3.

- [ ] **Step 7: Eseguire l'intera suite di test del progetto**

Run:
```bash
pytest tests/ -v
```

Expected: tutti i test passano (52 pre-esistenti + 5 di Task 1 + 2 di questo task = 59 totali), 0 failed.

- [ ] **Step 8: Commit**

```bash
git add app.py templates/index.html tests/test_app.py
git commit -m "Aggiunge selezione profilo all'avvio e colore di sfondo per distinguerli"
```

---

### Task 3: Verifica end-to-end

**Files:**
- Nessun file di codice nuovo. Verifica manuale dei due profili avviati realmente.

**Interfaces:**
- Consumes: `crea_app`, blocco `__main__` da `app.py` (Task 2).

- [ ] **Step 1: Eseguire l'intera suite di test**

Run:
```bash
source venv/bin/activate
pytest tests/ -v
```

Expected: tutti i test passano, 0 failed.

- [ ] **Step 2: Verificare il messaggio d'errore per argomento mancante o non valido**

Run:
```bash
python app.py
```
Expected: stampa `Uso: python app.py modelle|personaggi` ed esce (codice di uscita 1), nessun server avviato.

```bash
python app.py qualcosa
```
Expected: stampa `Profilo sconosciuto: 'qualcosa'. Usa 'modelle' o 'personaggi'.` ed esce, nessun server avviato.

- [ ] **Step 3: Avviare il profilo "personaggi" e verificare che sia il DB reale esistente**

Run:
```bash
VOLTI_NO_BROWSER=1 python app.py personaggi
```

Expected: il server si avvia su `http://127.0.0.1:5002/` senza errori.

In un altro terminale (stesso venv attivo):
```bash
curl -s http://127.0.0.1:5002/ | grep -o '#b0e0e6'
curl -s http://127.0.0.1:5002/ | grep -o 'Nicky Passarella'
```

Expected: entrambi i comandi trovano una corrispondenza — il colore azzurro carta da zucchero è nella pagina, e "Nicky Passarella" (una delle 22 persone reali già in `db/volti.db`) compare nella lista nomi esistenti embedded nella pagina.

Ferma il server (`Ctrl+C`).

- [ ] **Step 4: Avviare il profilo "modelle" e verificare che sia vuoto**

Run:
```bash
VOLTI_NO_BROWSER=1 python app.py modelle
```

Expected: il server si avvia su `http://127.0.0.1:5001/` senza errori. Viene creato `db/volti_modelle.db` (verificare con `ls db/`).

In un altro terminale:
```bash
curl -s http://127.0.0.1:5001/ | grep -o '#ffe4e1'
curl -s http://127.0.0.1:5001/ | grep -o 'const NOMI_ESISTENTI = \[\]'
```

Expected: il colore rosso molto chiaro è presente, e la lista nomi esistenti è vuota (`[]`, nessuna persona nel nuovo DB).

Ferma il server (`Ctrl+C`).

- [ ] **Step 5: Verificare che i due profili possano girare contemporaneamente**

Run in due terminali separati (stesso venv attivo in entrambi):
```bash
# terminale 1
VOLTI_NO_BROWSER=1 python app.py personaggi
```
```bash
# terminale 2
VOLTI_NO_BROWSER=1 python app.py modelle
```

Expected: entrambi restano in esecuzione senza errori di porta occupata (5001 e 5002 sono distinte). Verificare con:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5002/
```
Expected: `200` per entrambi.

Fermare entrambi i server (`Ctrl+C` in ciascun terminale).

- [ ] **Step 6: Scrivere un breve riepilogo nel report**

Scrivi i risultati reali (output dei comandi sopra) in `.superpowers/sdd/task-3-profili-report.md` (nuovo file, scratch, già escluso da git). Non serve commit di codice per questo task.

## Definizione di "Profili modelle/personaggi completati"

`pytest tests/ -v` passa tutti i test (59 totali). `python app.py` senza argomenti o con un argomento non valido stampa l'uso corretto ed esce senza avviare nulla. `python app.py personaggi` serve il DB reale esistente (22 persone) su porta 5002 con sfondo azzurro. `python app.py modelle` crea e serve un DB vuoto su porta 5001 con sfondo rosso chiaro. Entrambi possono girare contemporaneamente senza conflitti di porta.
