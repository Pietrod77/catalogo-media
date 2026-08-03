# Hosting NAS con sync incrementale — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare l'app Flask di riconoscimento volti sul NAS (Docker, sempre acceso, raggiungibile via Tailscale) mantenendo un fallback locale che sincronizza in background le conferme fatte offline, senza mai scaricare l'intero database.

**Architecture:** Stesso `app.py` in due contesti — container Docker sul NAS (sorgente di verità, sempre online) e installazione locale di fallback (stesso codice, con un worker in background opzionale attivato solo se sa dove si trova il NAS). Lo schema SQLite esistente è append-only: una colonna `sincronizzato` su `embedding` e un endpoint di export incrementale bastano per evitare un dump completo del database a ogni sync.

**Tech Stack:** Python 3.13, Flask, SQLite (libreria standard `sqlite3`), `requests` (nuova dipendenza, per le chiamate HTTP del worker di sync), Docker + Docker Compose (deploy NAS), pytest (test, incluso un server Flask live via `werkzeug.serving.make_server` per i test di integrazione del sync).

## Global Constraints

- Design approvato in `docs/superpowers/specs/2026-08-03-hosting-nas-sync-design.md` — ogni scelta sotto discende da lì, non reintrodurre alternative già scartate (autenticazione applicativa, sync in tempo reale, risoluzione conflitti manuale, VPS a pagamento sono esplicitamente fuori scope).
- Schema `persone`/`embedding`/`log_scarti` in `db/database.py` è append-only in tutta la codebase (solo `INSERT`, mai `UPDATE`/`DELETE` salvo la nuova `segna_sincronizzato`) — non introdurre `UPDATE`/`DELETE` aggiuntivi senza necessità.
- Nessuna modifica al comportamento delle route esistenti per l'uso online diretto (online-oggi resta identico): le modifiche devono essere additive (nuovi parametri opzionali con default che preservano il comportamento attuale).
- Segui lo stile di test già in uso in `tests/` (fixture `tmp_path`, nomi test descrittivi in italiano, niente mock pesanti — si preferisce comportamento reale, es. un vero server Flask live per i test di sync).
- **Ordine di esecuzione**: i task sono numerati nell'ordine in cui vanno eseguiti (1→5). Task 4 (`app.py`) importa `core.sync` (Task 3): rispettare l'ordine evita import rotti.

---

### Task 1: Estendere `db/database.py` per il sync incrementale

**Files:**
- Modify: `db/database.py`
- Test: `tests/test_database.py`

**Interfaces:**
- Consumes: `SCHEMA`, `connetti()`, `init_db()`, `salva_embedding()`, `trova_o_crea_persona()` esistenti (invariati nelle firme salvo `salva_embedding`, vedi sotto).
- Produces (usati da Task 3 e Task 4):
  - `salva_embedding(conn, person_id, vettore, foto_origine, fonte, sincronizzato: bool = True) -> int`
  - `embedding_da_sincronizzare(conn) -> list[dict]` — ogni dict: `{"id": int, "nome": str, "vettore": list[float] (512), "foto_origine": str, "fonte": str}`
  - `segna_sincronizzato(conn, embedding_id: int) -> None`
  - `leggi_sync_stato(conn) -> tuple[int, int]` — `(ultimo_persona_id_nas, ultimo_embedding_id_nas)`
  - `aggiorna_sync_stato(conn, ultimo_persona_id_nas: int, ultimo_embedding_id_nas: int) -> None`
  - `esporta_persone_dopo(conn, dopo_id: int, limite: int = 200) -> list[dict]` — ogni dict: `{"id": int, "nome": str}`
  - `esporta_embedding_dopo(conn, dopo_id: int, limite: int = 200) -> list[dict]` — stesso formato di `embedding_da_sincronizzare` più `"id"`

- [ ] **Step 1: Scrivere i test per lo schema esteso e la migrazione**

Aggiungi in fondo a `tests/test_database.py`:

```python
def test_init_db_su_db_vecchio_aggiunge_colonna_sincronizzato(tmp_path):
    percorso_db = tmp_path / "vecchio.db"
    conn = sqlite3.connect(str(percorso_db))
    conn.executescript(
        """
        CREATE TABLE persone (id INTEGER PRIMARY KEY, nome TEXT UNIQUE NOT NULL, note TEXT,
            creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE embedding (id INTEGER PRIMARY KEY, person_id INTEGER NOT NULL REFERENCES persone(id),
            vettore BLOB NOT NULL, foto_origine TEXT NOT NULL, fonte TEXT NOT NULL,
            creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        """
    )
    conn.commit()
    conn.close()

    init_db(percorso_db)

    conn = connetti(percorso_db)
    colonne = [riga[1] for riga in conn.execute("PRAGMA table_info(embedding)").fetchall()]
    conn.close()
    assert "sincronizzato" in colonne


def test_init_db_migrazione_colonna_e_idempotente(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    init_db(percorso_db)  # seconda chiamata non deve sollevare errori

    conn = connetti(percorso_db)
    colonne = [riga[1] for riga in conn.execute("PRAGMA table_info(embedding)").fetchall()]
    conn.close()
    assert colonne.count("sincronizzato") == 1


def test_init_db_crea_tabella_sync_stato(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)

    conn = connetti(percorso_db)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tabelle = {riga[0] for riga in cursor.fetchall()}
    conn.close()
    assert "sync_stato" in tabelle
```

- [ ] **Step 2: Eseguire i test, verificare che falliscano**

Run: `venv/bin/pytest tests/test_database.py -k migrazione_colonna or test_init_db_su_db_vecchio or sync_stato -v`
Expected: FAIL — colonna/tabella non esistono ancora.

- [ ] **Step 3: Estendere `SCHEMA` e aggiungere la migrazione in `init_db`**

In `db/database.py`, modifica `SCHEMA` (aggiungi `sincronizzato` alla tabella `embedding` e la nuova tabella `sync_stato`):

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS persone (
    id INTEGER PRIMARY KEY,
    nome TEXT UNIQUE NOT NULL,
    note TEXT,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS embedding (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES persone(id),
    vettore BLOB NOT NULL,
    foto_origine TEXT NOT NULL,
    fonte TEXT NOT NULL,
    sincronizzato INTEGER NOT NULL DEFAULT 1,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS log_scarti (
    id INTEGER PRIMARY KEY,
    foto TEXT NOT NULL,
    motivo TEXT NOT NULL,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_stato (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ultimo_persona_id_nas INTEGER NOT NULL DEFAULT 0,
    ultimo_embedding_id_nas INTEGER NOT NULL DEFAULT 0
);
"""


def _migra_colonna_sincronizzato(conn: sqlite3.Connection) -> None:
    """Aggiunge embedding.sincronizzato ai DB creati prima di questa modifica
    (CREATE TABLE IF NOT EXISTS non altera tabelle gia' esistenti)."""
    colonne = [riga[1] for riga in conn.execute("PRAGMA table_info(embedding)").fetchall()]
    if "sincronizzato" not in colonne:
        conn.execute(
            "ALTER TABLE embedding ADD COLUMN sincronizzato INTEGER NOT NULL DEFAULT 1"
        )
        conn.commit()


def init_db(percorso_db: str | Path) -> None:
    """Crea le tabelle persone, embedding, log_scarti, sync_stato se non esistono già,
    e migra i DB pre-esistenti aggiungendo la colonna sincronizzato se assente."""
    conn = connetti(percorso_db)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migra_colonna_sincronizzato(conn)
    finally:
        conn.close()
```

- [ ] **Step 4: Eseguire i test, verificare che passino**

Run: `venv/bin/pytest tests/test_database.py -v`
Expected: PASS (inclusi tutti i test esistenti, invariati).

- [ ] **Step 5: Commit**

```bash
git add db/database.py tests/test_database.py
git commit -m "Aggiunge colonna sincronizzato e tabella sync_stato con migrazione idempotente"
```

- [ ] **Step 6: Scrivere i test per `salva_embedding` con il nuovo parametro e le funzioni di coda/export**

Aggiungi in fondo a `tests/test_database.py`:

```python
def test_salva_embedding_default_sincronizzato_true(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    person_id = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = np.random.rand(512).astype(np.float32)

    embedding_id = salva_embedding(conn, person_id, vettore, "foto.jpg", "batch_iniziale")

    riga = conn.execute(
        "SELECT sincronizzato FROM embedding WHERE id = ?", (embedding_id,)
    ).fetchone()
    conn.close()
    assert riga[0] == 1


def test_salva_embedding_sincronizzato_false(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    person_id = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = np.random.rand(512).astype(np.float32)

    embedding_id = salva_embedding(
        conn, person_id, vettore, "foto.jpg", "conferma_editing", sincronizzato=False
    )

    riga = conn.execute(
        "SELECT sincronizzato FROM embedding WHERE id = ?", (embedding_id,)
    ).fetchone()
    conn.close()
    assert riga[0] == 0


def test_embedding_da_sincronizzare_ritorna_solo_le_pendenti(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = np.random.rand(512).astype(np.float32)
    salva_embedding(conn, id_mario, vettore, "sincronizzata.jpg", "batch_iniziale")
    embedding_id_pendente = salva_embedding(
        conn, id_mario, vettore, "pendente.jpg", "conferma_editing", sincronizzato=False
    )

    pendenti = embedding_da_sincronizzare(conn)
    conn.close()

    assert len(pendenti) == 1
    assert pendenti[0]["id"] == embedding_id_pendente
    assert pendenti[0]["nome"] == "Mario Rossi"
    assert pendenti[0]["foto_origine"] == "pendente.jpg"
    assert pendenti[0]["fonte"] == "conferma_editing"
    assert len(pendenti[0]["vettore"]) == 512


def test_segna_sincronizzato_aggiorna_la_riga(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = np.random.rand(512).astype(np.float32)
    embedding_id = salva_embedding(
        conn, id_mario, vettore, "pendente.jpg", "conferma_editing", sincronizzato=False
    )

    segna_sincronizzato(conn, embedding_id)

    riga = conn.execute(
        "SELECT sincronizzato FROM embedding WHERE id = ?", (embedding_id,)
    ).fetchone()
    conn.close()
    assert riga[0] == 1


def test_leggi_sync_stato_crea_riga_singleton_se_assente(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    stato = leggi_sync_stato(conn)
    conn.close()

    assert stato == (0, 0)


def test_aggiorna_sync_stato_persiste_valori(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    aggiorna_sync_stato(conn, 5, 10)
    stato = leggi_sync_stato(conn)
    conn.close()

    assert stato == (5, 10)


def test_esporta_persone_dopo_filtra_per_id(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    id_prima = trova_o_crea_persona(conn, "Prima Persona")
    trova_o_crea_persona(conn, "Seconda Persona")

    risultato = esporta_persone_dopo(conn, id_prima)
    conn.close()

    assert [p["nome"] for p in risultato] == ["Seconda Persona"]


def test_esporta_embedding_dopo_include_vettore_come_lista(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    vettore_originale = np.random.rand(512).astype(np.float32)
    salva_embedding(conn, id_mario, vettore_originale, "foto.jpg", "batch_iniziale")

    risultato = esporta_embedding_dopo(conn, 0)
    conn.close()

    assert len(risultato) == 1
    riga = risultato[0]
    assert riga["nome"] == "Mario Rossi"
    assert riga["foto_origine"] == "foto.jpg"
    assert riga["fonte"] == "batch_iniziale"
    assert np.allclose(riga["vettore"], vettore_originale.tolist())
```

- [ ] **Step 7: Eseguire i test, verificare che falliscano**

Run: `venv/bin/pytest tests/test_database.py -v`
Expected: FAIL con `ImportError`/`NameError` — le funzioni non esistono ancora.

- [ ] **Step 8: Implementare `salva_embedding` esteso e le nuove funzioni**

In `db/database.py`, modifica `salva_embedding` esistente e aggiungi le nuove funzioni (dopo `salva_embedding`, prima di `foto_gia_processata`):

```python
def salva_embedding(
    conn: sqlite3.Connection,
    person_id: int,
    vettore: np.ndarray,
    foto_origine: str,
    fonte: str,
    sincronizzato: bool = True,
) -> int:
    """Inserisce un embedding legato a una persona. Ritorna l'id della riga creata.

    sincronizzato=False marca la riga come non ancora inviata al NAS (usato solo
    dalle conferme fatte in modalita' fallback locale)."""
    cursor = conn.execute(
        "INSERT INTO embedding (person_id, vettore, foto_origine, fonte, sincronizzato) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            person_id,
            vettore.astype(np.float32).tobytes(),
            foto_origine,
            fonte,
            int(sincronizzato),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def embedding_da_sincronizzare(conn: sqlite3.Connection) -> list[dict]:
    """Ritorna le righe embedding non ancora inviate al NAS (sincronizzato = 0)."""
    righe = conn.execute(
        "SELECT e.id, p.nome, e.vettore, e.foto_origine, e.fonte "
        "FROM embedding e JOIN persone p ON p.id = e.person_id "
        "WHERE e.sincronizzato = 0 ORDER BY e.id"
    ).fetchall()
    return [
        {
            "id": id_,
            "nome": nome,
            "vettore": np.frombuffer(blob, dtype=np.float32).tolist(),
            "foto_origine": foto_origine,
            "fonte": fonte,
        }
        for id_, nome, blob, foto_origine, fonte in righe
    ]


def segna_sincronizzato(conn: sqlite3.Connection, embedding_id: int) -> None:
    """Marca una riga embedding come inviata con successo al NAS."""
    conn.execute("UPDATE embedding SET sincronizzato = 1 WHERE id = ?", (embedding_id,))
    conn.commit()


def leggi_sync_stato(conn: sqlite3.Connection) -> tuple[int, int]:
    """Ritorna (ultimo_persona_id_nas, ultimo_embedding_id_nas), creando la riga
    singleton con valori (0, 0) se non esiste ancora."""
    riga = conn.execute(
        "SELECT ultimo_persona_id_nas, ultimo_embedding_id_nas FROM sync_stato WHERE id = 1"
    ).fetchone()
    if riga is not None:
        return riga
    conn.execute(
        "INSERT INTO sync_stato (id, ultimo_persona_id_nas, ultimo_embedding_id_nas) "
        "VALUES (1, 0, 0)"
    )
    conn.commit()
    return (0, 0)


def aggiorna_sync_stato(
    conn: sqlite3.Connection, ultimo_persona_id_nas: int, ultimo_embedding_id_nas: int
) -> None:
    """Aggiorna i segnalini di avanzamento del pull incrementale dal NAS."""
    leggi_sync_stato(conn)  # assicura che la riga singleton esista prima dell'UPDATE
    conn.execute(
        "UPDATE sync_stato SET ultimo_persona_id_nas = ?, ultimo_embedding_id_nas = ? "
        "WHERE id = 1",
        (ultimo_persona_id_nas, ultimo_embedding_id_nas),
    )
    conn.commit()


def esporta_persone_dopo(conn: sqlite3.Connection, dopo_id: int, limite: int = 200) -> list[dict]:
    """Ritorna le persone con id > dopo_id, per l'export incrementale verso i client locali."""
    righe = conn.execute(
        "SELECT id, nome FROM persone WHERE id > ? ORDER BY id LIMIT ?",
        (dopo_id, limite),
    ).fetchall()
    return [{"id": id_, "nome": nome} for id_, nome in righe]


def esporta_embedding_dopo(conn: sqlite3.Connection, dopo_id: int, limite: int = 200) -> list[dict]:
    """Ritorna gli embedding con id > dopo_id, per l'export incrementale verso i client locali."""
    righe = conn.execute(
        "SELECT e.id, p.nome, e.vettore, e.foto_origine, e.fonte "
        "FROM embedding e JOIN persone p ON p.id = e.person_id "
        "WHERE e.id > ? ORDER BY e.id LIMIT ?",
        (dopo_id, limite),
    ).fetchall()
    return [
        {
            "id": id_,
            "nome": nome,
            "vettore": np.frombuffer(blob, dtype=np.float32).tolist(),
            "foto_origine": foto_origine,
            "fonte": fonte,
        }
        for id_, nome, blob, foto_origine, fonte in righe
    ]
```

Aggiungi anche gli import necessari in cima a `tests/test_database.py` (se non già presenti dal file esistente, che importa già `numpy as np` più sotto — spostali in cima per chiarezza):

```python
from db.database import (
    init_db,
    connetti,
    trova_o_crea_persona,
    salva_embedding,
    registra_scarto,
    foto_gia_processata,
    embedding_da_sincronizzare,
    segna_sincronizzato,
    leggi_sync_stato,
    aggiorna_sync_stato,
    esporta_persone_dopo,
    esporta_embedding_dopo,
)
```

- [ ] **Step 9: Eseguire tutti i test, verificare che passino**

Run: `venv/bin/pytest tests/test_database.py -v`
Expected: PASS, tutti i test (esistenti + nuovi).

- [ ] **Step 10: Commit**

```bash
git add db/database.py tests/test_database.py
git commit -m "Aggiunge funzioni di coda e export incrementale per il sync NAS"
```

---

### Task 2: `config.py` — variabili d'ambiente per NAS e host di ascolto

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces (usati da Task 4): `NAS_URL: str | None`, `HOST: str`

- [ ] **Step 1: Scrivere i test**

Aggiungi in fondo a `tests/test_config.py`:

```python
def test_nas_url_none_se_variabile_ambiente_assente(monkeypatch):
    monkeypatch.delenv("VOLTI_NAS_URL", raising=False)
    import importlib
    import config as config_module

    importlib.reload(config_module)
    assert config_module.NAS_URL is None


def test_nas_url_legge_variabile_ambiente(monkeypatch):
    monkeypatch.setenv("VOLTI_NAS_URL", "http://100.125.65.26:5002")
    import importlib
    import config as config_module

    importlib.reload(config_module)
    assert config_module.NAS_URL == "http://100.125.65.26:5002"


def test_host_default_localhost(monkeypatch):
    monkeypatch.delenv("VOLTI_HOST", raising=False)
    import importlib
    import config as config_module

    importlib.reload(config_module)
    assert config_module.HOST == "127.0.0.1"


def test_host_legge_variabile_ambiente(monkeypatch):
    monkeypatch.setenv("VOLTI_HOST", "0.0.0.0")
    import importlib
    import config as config_module

    importlib.reload(config_module)
    assert config_module.HOST == "0.0.0.0"
```

- [ ] **Step 2: Eseguire i test, verificare che falliscano**

Run: `venv/bin/pytest tests/test_config.py -k nas_url or host -v`
Expected: FAIL — `AttributeError: module 'config' has no attribute 'NAS_URL'`.

- [ ] **Step 3: Aggiungere le due costanti in `config.py`**

Dopo la riga `_archivio_storico = os.environ.get("VOLTI_ARCHIVIO_STORICO")` e prima di `CARTELLE_ARCHIVIO_EXTRA`, aggiungi:

```python
NAS_URL = os.environ.get("VOLTI_NAS_URL") or None
HOST = os.environ.get("VOLTI_HOST", "127.0.0.1")
```

- [ ] **Step 4: Eseguire i test, verificare che passino**

Run: `venv/bin/pytest tests/test_config.py -v`
Expected: PASS, tutti i test (esistenti + nuovi).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "Aggiunge NAS_URL e HOST come variabili d'ambiente configurabili"
```

---

### Task 3: `core/sync.py` — worker di sync incrementale (push + pull)

**Files:**
- Create: `core/sync.py`
- Modify: `requirements.txt`
- Test: `tests/test_sync.py` (nuovo file)

**Interfaces:**
- Consumes: `connetti`, `embedding_da_sincronizzare`, `segna_sincronizzato`, `leggi_sync_stato`, `aggiorna_sync_stato`, `trova_o_crea_persona`, `salva_embedding`, `foto_gia_processata` (Task 1); `crea_app` da `app.py` (già esistente, non ancora modificato dal Task 4 — i test qui usano solo la firma odierna, senza il parametro `nas_url` introdotto più avanti).
- Produces (usato da Task 4): `avvia_worker_sync(percorso_db: Path, cartella_sessioni: Path, url_base: str) -> threading.Thread`; anche `nas_raggiungibile`, `invia_pendenti`, `scarica_incrementale`, `esegui_ciclo_sync` (usate direttamente nei test, non da altri moduli applicativi)

- [ ] **Step 1: Aggiungere `requests` alle dipendenze**

In `requirements.txt`, aggiungi una riga:

```
requests==2.32.3
```

Poi installa nel venv:

Run: `venv/bin/pip install requests==2.32.3`

- [ ] **Step 2: Scrivere `tests/test_sync.py` (server NAS di prova + test)**

Crea `tests/test_sync.py`:

```python
import threading
import time

import numpy as np
import pytest
from werkzeug.serving import make_server

from app import crea_app
from core.sync import (
    esegui_ciclo_sync,
    invia_pendenti,
    nas_raggiungibile,
    scarica_incrementale,
)
from db.database import (
    connetti,
    embedding_da_sincronizzare,
    init_db,
    salva_embedding,
    trova_o_crea_persona,
)


class ServerNasDiProva:
    def __init__(self, app):
        self._server = make_server("127.0.0.1", 0, app)
        self.porta = self._server.server_port
        self.url_base = f"http://127.0.0.1:{self.porta}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def avvia(self):
        self._thread.start()

    def ferma(self):
        self._server.shutdown()
        self._thread.join(timeout=2)


@pytest.fixture
def nas_live(tmp_path):
    app_nas = crea_app(
        percorso_db=tmp_path / "nas" / "volti.db",
        cartella_sessioni=tmp_path / "nas" / "sessioni",
    )
    server = ServerNasDiProva(app_nas)
    server.avvia()
    for _ in range(50):
        if nas_raggiungibile(server.url_base):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Server NAS di prova non si e' avviato in tempo")
    yield server
    server.ferma()


def _vettore_normalizzato(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    return v / np.linalg.norm(v)


def test_nas_raggiungibile_true_quando_nas_attivo(nas_live):
    assert nas_raggiungibile(nas_live.url_base) is True


def test_nas_raggiungibile_false_per_indirizzo_inesistente():
    assert nas_raggiungibile("http://127.0.0.1:1") is False


def test_invia_pendenti_invia_e_marca_sincronizzata(nas_live, tmp_path):
    percorso_db_locale = tmp_path / "locale" / "volti.db"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)
    id_locale = trova_o_crea_persona(conn_locale, "Persona Offline")
    vettore = _vettore_normalizzato(seed=1)
    cartella_screenshot = tmp_path / "locale" / "sessioni" / "conferme"
    cartella_screenshot.mkdir(parents=True)
    file_screenshot = cartella_screenshot / "test.jpg"
    file_screenshot.write_bytes(b"contenuto finto jpg")
    salva_embedding(
        conn_locale,
        id_locale,
        vettore,
        str(file_screenshot),
        "conferma_editing",
        sincronizzato=False,
    )

    inviati = invia_pendenti(conn_locale, nas_live.url_base)

    assert inviati == 1
    assert embedding_da_sincronizzare(conn_locale) == []
    conn_locale.close()

    conn_nas = connetti(tmp_path / "nas" / "volti.db")
    riga_nas = conn_nas.execute(
        "SELECT nome FROM persone WHERE nome = ?", ("Persona Offline",)
    ).fetchone()
    conn_nas.close()
    assert riga_nas is not None


def test_invia_pendenti_salta_riga_senza_file_screenshot(nas_live, tmp_path):
    percorso_db_locale = tmp_path / "locale" / "volti.db"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)
    id_locale = trova_o_crea_persona(conn_locale, "Persona Senza File")
    vettore = _vettore_normalizzato(seed=2)
    salva_embedding(
        conn_locale,
        id_locale,
        vettore,
        str(tmp_path / "non_esiste.jpg"),
        "conferma_editing",
        sincronizzato=False,
    )

    inviati = invia_pendenti(conn_locale, nas_live.url_base)
    conn_locale.close()

    assert inviati == 0


def test_scarica_incrementale_pull_persone_ed_embedding(nas_live, tmp_path):
    conn_nas = connetti(tmp_path / "nas" / "volti.db")
    id_nas = trova_o_crea_persona(conn_nas, "Persona Sul Nas")
    vettore = _vettore_normalizzato(seed=3)
    cartella_nas_conferme = tmp_path / "nas" / "sessioni" / "conferme"
    cartella_nas_conferme.mkdir(parents=True, exist_ok=True)
    file_nas = cartella_nas_conferme / "originale.jpg"
    file_nas.write_bytes(b"contenuto reale nas")
    salva_embedding(conn_nas, id_nas, vettore, str(file_nas), "batch_iniziale")
    conn_nas.close()

    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)

    ricevuti = scarica_incrementale(conn_locale, nas_live.url_base, cartella_sessioni_locale)

    riga = conn_locale.execute(
        "SELECT p.nome FROM embedding e JOIN persone p ON p.id = e.person_id"
    ).fetchone()
    conn_locale.close()

    assert ricevuti == 1
    assert riga[0] == "Persona Sul Nas"
    assert (cartella_sessioni_locale / "conferme" / "originale.jpg").read_bytes() == (
        b"contenuto reale nas"
    )


def test_scarica_incrementale_non_duplica_se_richiamata_due_volte(nas_live, tmp_path):
    conn_nas = connetti(tmp_path / "nas" / "volti.db")
    id_nas = trova_o_crea_persona(conn_nas, "Persona Sul Nas")
    vettore = _vettore_normalizzato(seed=4)
    cartella_nas_conferme = tmp_path / "nas" / "sessioni" / "conferme"
    cartella_nas_conferme.mkdir(parents=True, exist_ok=True)
    file_nas = cartella_nas_conferme / "originale.jpg"
    file_nas.write_bytes(b"contenuto reale nas")
    salva_embedding(conn_nas, id_nas, vettore, str(file_nas), "batch_iniziale")
    conn_nas.close()

    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)

    scarica_incrementale(conn_locale, nas_live.url_base, cartella_sessioni_locale)
    scarica_incrementale(conn_locale, nas_live.url_base, cartella_sessioni_locale)

    conteggio = conn_locale.execute("SELECT COUNT(*) FROM embedding").fetchone()[0]
    conn_locale.close()

    assert conteggio == 1


def test_esegui_ciclo_sync_non_raggiungibile_non_solleva_errori(tmp_path):
    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)

    risultato = esegui_ciclo_sync(
        percorso_db_locale, cartella_sessioni_locale, "http://127.0.0.1:1"
    )

    assert risultato == {"raggiungibile": False, "inviati": 0, "ricevuti": 0}


def test_esegui_ciclo_sync_completo_invia_e_riceve(nas_live, tmp_path):
    percorso_db_locale = tmp_path / "locale" / "volti.db"
    cartella_sessioni_locale = tmp_path / "locale" / "sessioni"
    init_db(percorso_db_locale)
    conn_locale = connetti(percorso_db_locale)
    id_locale = trova_o_crea_persona(conn_locale, "Persona Offline Due")
    vettore = _vettore_normalizzato(seed=5)
    cartella_screenshot = cartella_sessioni_locale / "conferme"
    cartella_screenshot.mkdir(parents=True)
    file_screenshot = cartella_screenshot / "offline.jpg"
    file_screenshot.write_bytes(b"contenuto offline")
    salva_embedding(
        conn_locale,
        id_locale,
        vettore,
        str(file_screenshot),
        "conferma_editing",
        sincronizzato=False,
    )
    conn_locale.close()

    risultato = esegui_ciclo_sync(percorso_db_locale, cartella_sessioni_locale, nas_live.url_base)

    assert risultato["raggiungibile"] is True
    assert risultato["inviati"] == 1
```

- [ ] **Step 3: Eseguire i test, verificare che falliscano**

Run: `venv/bin/pytest tests/test_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.sync'`.

- [ ] **Step 4: Implementare `core/sync.py`**

Crea `core/sync.py`:

```python
"""Sincronizzazione incrementale tra un'installazione locale di fallback e il NAS."""

import base64
import threading
import time
from pathlib import Path

import numpy as np
import requests

from db.database import (
    aggiorna_sync_stato,
    connetti,
    embedding_da_sincronizzare,
    foto_gia_processata,
    leggi_sync_stato,
    salva_embedding,
    segna_sincronizzato,
    trova_o_crea_persona,
)

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
                },
                timeout=TIMEOUT_RICHIESTA,
            )
        except requests.exceptions.RequestException:
            continue
        if risposta.status_code == 200:
            segna_sincronizzato(conn, riga["id"])
            inviati += 1
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
    ricevuti = 0
    for riga in dati["embedding"]:
        nome_file = Path(riga["foto_origine"]).name
        percorso_locale = cartella_conferme / nome_file
        if foto_gia_processata(conn, str(percorso_locale)):
            ultimo_embedding = max(ultimo_embedding, riga["id"])
            continue
        if riga["screenshot_base64"] is not None:
            percorso_locale.write_bytes(base64.b64decode(riga["screenshot_base64"]))
        person_id = trova_o_crea_persona(conn, riga["nome"])
        vettore = np.array(riga["vettore"], dtype=np.float32)
        salva_embedding(
            conn, person_id, vettore, str(percorso_locale), riga["fonte"], sincronizzato=True
        )
        ultimo_embedding = max(ultimo_embedding, riga["id"])
        ricevuti += 1

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
```

- [ ] **Step 5: Eseguire tutti i test di `test_sync.py`, verificare che passino**

Run: `venv/bin/pytest tests/test_sync.py -v`
Expected: PASS, tutti i test.

- [ ] **Step 6: Commit**

```bash
git add core/sync.py requirements.txt tests/test_sync.py
git commit -m "Aggiunge il worker di sync incrementale push+pull verso il NAS"
```

---

### Task 4: `app.py` — endpoint di export, flag di sincronizzazione, indicatore in UI

**Files:**
- Modify: `app.py`
- Modify: `templates/index.html:25`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `esporta_persone_dopo`, `esporta_embedding_dopo` (Task 1); `NAS_URL`, `HOST` (Task 2); `avvia_worker_sync` (Task 3)
- Produces: `crea_app(percorso_db, cartella_sessioni, colore_sfondo="#ffffff", nome_profilo="", nas_url: str | None = None) -> Flask` — nuovo parametro opzionale `nas_url`, che se impostato marca come `sincronizzato=False` le nuove conferme fatte tramite questa app; endpoint `GET /sync/esporta?dopo_persona=&dopo_embedding=` che ritorna `{"persone": [...], "embedding": [...]}` col campo aggiuntivo `screenshot_base64` per ogni embedding.

- [ ] **Step 1: Scrivere i test per l'indicatore "conferme in attesa", il flag nas_url e l'endpoint di export**

Aggiungi in fondo a `tests/test_app.py`:

```python
def test_index_mostra_conferme_in_sospeso(app, client):
    conn = connetti(app.config["PERCORSO_DB"])
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = _vettore_normalizzato(seed=41)
    salva_embedding(conn, id_mario, vettore, "foto.jpg", "conferma_editing", sincronizzato=False)
    conn.close()

    risposta = client.get("/")

    assert b"1 conferme in attesa di sync" in risposta.data


def test_index_non_mostra_indicatore_se_tutto_sincronizzato(client):
    risposta = client.get("/")
    assert b"conferme in attesa di sync" not in risposta.data


def test_conferma_con_nas_url_configurato_marca_non_sincronizzato(tmp_path):
    app_locale = crea_app(
        percorso_db=tmp_path / "volti_test.db",
        cartella_sessioni=tmp_path / "sessioni",
        nas_url="http://nas-di-prova.invalid:5002",
    )
    client_locale = app_locale.test_client()
    vettore = _vettore_normalizzato(seed=50).tolist()
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    client_locale.post(
        "/conferma",
        json={
            "nome": "Persona Offline",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )

    conn = connetti(app_locale.config["PERCORSO_DB"])
    riga = conn.execute(
        "SELECT sincronizzato FROM embedding e JOIN persone p ON p.id = e.person_id "
        "WHERE p.nome = ?",
        ("Persona Offline",),
    ).fetchone()
    conn.close()
    assert riga[0] == 0


def test_sync_esporta_ritorna_persone_ed_embedding_nuovi(app, client):
    conn = connetti(app.config["PERCORSO_DB"])
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    vettore = _vettore_normalizzato(seed=60)
    cartella_conferme = app.config["CARTELLA_SESSIONI"] / "conferme"
    cartella_conferme.mkdir(parents=True, exist_ok=True)
    file_foto = cartella_conferme / "test.jpg"
    file_foto.write_bytes(b"contenuto finto jpg")
    salva_embedding(conn, id_mario, vettore, str(file_foto), "conferma_editing")
    conn.close()

    risposta = client.get("/sync/esporta")
    dati = risposta.get_json()

    assert risposta.status_code == 200
    assert any(p["nome"] == "Mario Rossi" for p in dati["persone"])
    assert len(dati["embedding"]) == 1
    assert dati["embedding"][0]["nome"] == "Mario Rossi"
    assert dati["embedding"][0]["screenshot_base64"] is not None


def test_sync_esporta_rispetta_dopo_persona(app, client):
    conn = connetti(app.config["PERCORSO_DB"])
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    conn.close()

    risposta = client.get(f"/sync/esporta?dopo_persona={id_mario}")

    assert risposta.get_json()["persone"] == []
```

- [ ] **Step 2: Eseguire i test, verificare che falliscano**

Run: `venv/bin/pytest tests/test_app.py -k sincronizzato or sync_esporta or in_sospeso -v`
Expected: FAIL — endpoint/parametro/indicatore non esistono ancora.

- [ ] **Step 3: Modificare `crea_app`, `/conferma`, `index()` e aggiungere `/sync/esporta` in `app.py`**

Aggiorna gli import in cima ad `app.py`:

```python
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
```

Modifica la firma di `crea_app` e il body di `index()`:

```python
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
```

(le route `/analizza` e `/riferimento` restano invariate — non toccarle)

Modifica solo la riga di `salva_embedding` dentro `/conferma`:

```python
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
```

Aggiungi il nuovo endpoint subito dopo `riferimento()`, prima di `return app`:

```python
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
```

Aggiorna il blocco `__main__` per usare `HOST`, `NAS_URL` e avviare il worker:

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
        nome_profilo=sys.argv[1],
        nas_url=NAS_URL,
    )
    if NAS_URL:
        avvia_worker_sync(profilo["db"], profilo["sessioni"], NAS_URL)
    if os.environ.get("VOLTI_NO_BROWSER") != "1":
        webbrowser.open(f"http://127.0.0.1:{profilo['porta']}/")
    app.run(host=HOST, port=profilo["porta"])
```

In `templates/index.html`, subito dopo la riga 25 (`<p style="color: #666;">Siamo a {{ numero_persone }} volti in database</p>`), aggiungi:

```html
    {% if conteggio_in_sospeso > 0 %}
    <p style="color: #a00;">{{ conteggio_in_sospeso }} conferme in attesa di sync</p>
    {% endif %}
```

- [ ] **Step 4: Eseguire tutta la suite, verificare che passi**

Run: `venv/bin/pytest tests/ -v`
Expected: PASS, tutti i test del progetto (esistenti + tutti quelli aggiunti nei Task 1-4).

- [ ] **Step 5: Commit**

```bash
git add app.py templates/index.html tests/test_app.py
git commit -m "Aggiunge endpoint /sync/esporta, flag sincronizzato su /conferma e indicatore in UI"
```

---

### Task 5: Containerizzazione per il NAS (Dockerfile + Docker Compose)

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `requirements.txt` (Task 3), `HOST`/`NAS_URL` da `config.py` (Task 2), `app.py` invariato nell'interfaccia CLI (`python app.py modelle|personaggi`)
- Produces: immagine Docker `volti-riconoscimento` avviabile sul NAS via `docker compose up -d`

- [ ] **Step 1: Creare `.dockerignore`**

```
venv/
__pycache__/
*.pyc
.pytest_cache/
.git/
tests/
docs/
```

- [ ] **Step 2: Creare `Dockerfile`**

```dockerfile
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV VOLTI_NO_BROWSER=1
ENV VOLTI_HOST=0.0.0.0
```

Nota: nessun `CMD`/`ENTRYPOINT` qui — lo specifica `docker-compose.yml` per ciascun servizio, perché la stessa immagine serve sia per `modelle` che per `personaggi`.

- [ ] **Step 3: Creare `docker-compose.yml`**

```yaml
services:
  volti-modelle:
    build: .
    image: volti-riconoscimento:latest
    command: ["python", "app.py", "modelle"]
    ports:
      - "5001:5001"
    volumes:
      - ./db:/app/db
      - ./sessioni:/app/sessioni
      - insightface-cache:/root/.insightface
    restart: unless-stopped

  volti-personaggi:
    build: .
    image: volti-riconoscimento:latest
    command: ["python", "app.py", "personaggi"]
    ports:
      - "5002:5002"
    volumes:
      - ./db:/app/db
      - ./sessioni:/app/sessioni
      - insightface-cache:/root/.insightface
    restart: unless-stopped

volumes:
  insightface-cache:
```

- [ ] **Step 4: Validare la sintassi del Compose file (non richiede il NAS)**

Run: `docker compose config`
Expected: stampa la configurazione risolta senza errori di parsing.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "Aggiunge Dockerfile e docker-compose per il deploy sul NAS"
```

- [ ] **Step 6: Verifica manuale sul NAS (fuori dall'automazione, da fare a mano da Pietro)**

Non automatizzabile in questo piano (richiede accesso al NAS via Tailscale/SSH e copiare la repo lì). Checklist per quando si esegue:

1. Copiare la repo (o clonarla da GitHub) in una cartella del NAS, verificando che `db/` e `sessioni/` puntino ai dati reali (non cartelle vuote) prima di avviare.
2. `docker compose build` — verifica che l'immagine si costruisca senza errori (il download dei pacchetti InsightFace/onnxruntime può richiedere qualche minuto la prima volta).
3. `docker compose up -d` — avvia entrambi i servizi.
4. Da un altro dispositivo nella tailnet (es. il Mac di Pietro), aprire `http://<ip-tailscale-nas>:5001/` e `:5002/` nel browser e verificare che le pagine rispondano con i dati attesi (numero di persone in DB coerente con quanto già presente).
5. Verificare che il volume `insightface-cache` sopravviva a un `docker compose restart` (il modello non deve riscaricarsi).

---

## Note per l'esecuzione

Ogni task ha una suite di test eseguibile in isolamento; a piano completato, eseguire l'intera suite (`venv/bin/pytest -v`) come verifica finale prima di considerare il lavoro concluso.
