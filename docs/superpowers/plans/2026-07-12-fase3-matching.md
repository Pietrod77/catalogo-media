# Fase 3: Modulo di Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dato l'embedding di un volto nuovo, confrontarlo contro tutti gli embedding nel database e proporre il nome più probabile (o "sconosciuto", o 2-3 candidati se ambiguo), usando le soglie calibrate sui dati reali (0.45 / 0.30, vedi design doc).

**Architecture:** `core/matching.py` contiene funzioni pure (nessun I/O oltre alla query DB): `calcola_candidati` confronta un embedding contro tutti quelli in DB e ritorna i migliori candidati per persona (media dei migliori 3 embedding a persona, coerente con la strategia "nessuna aggregazione a centroide" del design), `classifica_match` decide se il risultato è "certo", "ambiguo" o "sconosciuto" in base alle soglie.

**Tech Stack:** Stesso delle Fasi precedenti (venv esistente, numpy, SQLite). Nessuna nuova dipendenza.

## Global Constraints

- Nomi di file, variabili, funzioni e commenti in italiano.
- Soglie: `SOGLIA_ALTA = 0.45`, `SOGLIA_BASSA = 0.30` (calibrate empiricamente, vedi design doc sezione "Soglie di matching, calibrate sui dati reali").
- Similarità = prodotto scalare (dot product) tra vettori, dato che gli embedding di InsightFace (`VoltoRilevato.vettore`) sono già normalizzati L2 — NON serve dividere per le norme.
- Per ogni persona, il punteggio è la media dei migliori 3 embedding di quella persona (o meno se ne ha meno di 3) — mai un centroide calcolato in anticipo, il confronto è sempre contro gli embedding grezzi.
- I test automatici usano vettori sintetici (no dipendenza da InsightFace/exiftool/foto reali) — questo modulo è pura logica su numpy array e query SQLite, testabile in isolamento.
- venv/, db/*.db restano esclusi da git.

---

### Task 1: Modulo di matching (core/matching.py)

**Files:**
- Create: `core/matching.py`
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: nessuna funzione da moduli precedenti — riceve `vettore: numpy.ndarray` (shape `(512,)`, come prodotto da `VoltoRilevato.vettore` in `core/volti.py`) e `conn: sqlite3.Connection` (come da `db/database.connetti`), letti direttamente con query SQL sulle tabelle `persone`/`embedding` esistenti dalla Fase 1/2.
- Produces:
  - `Candidato` (dataclass): `nome: str`, `punteggio: float`, `foto_riferimento: str` (path della foto da cui proviene l'embedding migliore di quella persona, utile in futuro per mostrare una miniatura di riferimento).
  - `calcola_candidati(vettore: numpy.ndarray, conn: sqlite3.Connection, top_n: int = 3) -> list[Candidato]` — ritorna al massimo `top_n` candidati ordinati per punteggio decrescente. Lista vuota se il DB non ha embedding.
  - `classifica_match(candidati: list[Candidato]) -> str` — ritorna `"certo"` (miglior candidato ≥ SOGLIA_ALTA), `"ambiguo"` (miglior candidato tra SOGLIA_BASSA e SOGLIA_ALTA), o `"sconosciuto"` (lista vuota o miglior candidato < SOGLIA_BASSA).

- [ ] **Step 1: Scrivere il test che fallisce**

Create `tests/test_matching.py`:

```python
import numpy as np
import pytest

from core.matching import calcola_candidati, classifica_match, Candidato
from db.database import connetti, init_db, trova_o_crea_persona, salva_embedding


def _vettore_normalizzato(seed: int) -> np.ndarray:
    """Genera un vettore casuale riproducibile e normalizzato L2 (come un vero embedding)."""
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    return v / np.linalg.norm(v)


def _vettore_simile(base: np.ndarray, rumore: float, seed: int) -> np.ndarray:
    """Genera un vettore vicino a 'base' (simula la stessa persona in un'altra foto)."""
    rng = np.random.default_rng(seed)
    perturbazione = rng.normal(0, rumore, 512).astype(np.float32)
    v = base + perturbazione
    return v / np.linalg.norm(v)


@pytest.fixture
def db_con_due_persone(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    vettore_mario = _vettore_normalizzato(seed=1)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    for i in range(3):
        v = _vettore_simile(vettore_mario, rumore=0.02, seed=100 + i)
        salva_embedding(conn, id_mario, v, f"mario_{i}.jpg", "batch_iniziale")

    vettore_anna = _vettore_normalizzato(seed=2)
    id_anna = trova_o_crea_persona(conn, "Anna Bianchi")
    salva_embedding(conn, id_anna, vettore_anna, "anna_0.jpg", "batch_iniziale")

    yield conn, vettore_mario, vettore_anna
    conn.close()


def test_calcola_candidati_trova_la_persona_giusta_al_primo_posto(db_con_due_persone):
    conn, vettore_mario, _ = db_con_due_persone
    nuovo_volto = _vettore_simile(vettore_mario, rumore=0.02, seed=999)

    candidati = calcola_candidati(nuovo_volto, conn)

    assert candidati[0].nome == "Mario Rossi"
    assert candidati[0].punteggio > 0.9


def test_calcola_candidati_usa_media_dei_migliori_3_embedding(db_con_due_persone):
    conn, vettore_mario, _ = db_con_due_persone
    id_mario_query = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Mario Rossi",)
    ).fetchone()[0]
    # Aggiunge un quarto embedding molto diverso per Mario: la media dei migliori 3
    # deve restare alta (il 4o embedding, peggiore, va escluso dalla media).
    vettore_outlier = _vettore_normalizzato(seed=12345)
    salva_embedding(conn, id_mario_query, vettore_outlier, "mario_outlier.jpg", "manuale")

    nuovo_volto = _vettore_simile(vettore_mario, rumore=0.02, seed=999)
    candidati = calcola_candidati(nuovo_volto, conn)

    mario = next(c for c in candidati if c.nome == "Mario Rossi")
    assert mario.punteggio > 0.8  # la media dei 3 migliori resta alta nonostante l'outlier


def test_calcola_candidati_ritorna_lista_vuota_se_db_vuoto(tmp_path):
    percorso_db = tmp_path / "volti_vuoto.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    candidati = calcola_candidati(_vettore_normalizzato(seed=1), conn)

    conn.close()
    assert candidati == []


def test_classifica_match_certo_sopra_soglia_alta():
    candidati = [Candidato(nome="Mario Rossi", punteggio=0.9, foto_riferimento="x.jpg")]
    assert classifica_match(candidati) == "certo"


def test_classifica_match_ambiguo_tra_le_soglie():
    candidati = [Candidato(nome="Mario Rossi", punteggio=0.35, foto_riferimento="x.jpg")]
    assert classifica_match(candidati) == "ambiguo"


def test_classifica_match_sconosciuto_sotto_soglia_bassa():
    candidati = [Candidato(nome="Mario Rossi", punteggio=0.1, foto_riferimento="x.jpg")]
    assert classifica_match(candidati) == "sconosciuto"


def test_classifica_match_sconosciuto_se_nessun_candidato():
    assert classifica_match([]) == "sconosciuto"
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run (con venv attivo, dalla root del progetto):
```bash
source venv/bin/activate
pytest tests/test_matching.py -v
```

Expected: FAIL con `ModuleNotFoundError: No module named 'core.matching'`.

- [ ] **Step 3: Implementare core/matching.py**

Create `core/matching.py`:

```python
"""Confronto di un embedding facciale contro il database, per proporre un nome."""

import sqlite3
from dataclasses import dataclass

import numpy as np

SOGLIA_ALTA = 0.45
SOGLIA_BASSA = 0.30


@dataclass
class Candidato:
    nome: str
    punteggio: float
    foto_riferimento: str


def calcola_candidati(
    vettore: np.ndarray, conn: sqlite3.Connection, top_n: int = 3
) -> list[Candidato]:
    """Confronta vettore contro tutti gli embedding in DB, ritorna i migliori candidati.

    Per ogni persona il punteggio e' la media dei migliori 3 embedding di quella
    persona (o meno se ne ha meno di 3). Ritorna al massimo top_n candidati,
    ordinati per punteggio decrescente. Lista vuota se il DB non ha embedding.
    """
    righe = conn.execute(
        "SELECT p.nome, e.vettore, e.foto_origine "
        "FROM embedding e JOIN persone p ON p.id = e.person_id"
    ).fetchall()

    per_persona: dict[str, list[tuple[float, str]]] = {}
    for nome, blob, foto in righe:
        vettore_db = np.frombuffer(blob, dtype=np.float32)
        similarita = float(np.dot(vettore, vettore_db))
        per_persona.setdefault(nome, []).append((similarita, foto))

    candidati = []
    for nome, coppie in per_persona.items():
        coppie.sort(key=lambda c: c[0], reverse=True)
        migliori = coppie[:3]
        punteggio = sum(s for s, _ in migliori) / len(migliori)
        foto_riferimento = migliori[0][1]
        candidati.append(Candidato(nome=nome, punteggio=punteggio, foto_riferimento=foto_riferimento))

    candidati.sort(key=lambda c: c.punteggio, reverse=True)
    return candidati[:top_n]


def classifica_match(candidati: list[Candidato]) -> str:
    """Ritorna 'certo', 'ambiguo' o 'sconosciuto' in base al punteggio del migliore."""
    if not candidati or candidati[0].punteggio < SOGLIA_BASSA:
        return "sconosciuto"
    if candidati[0].punteggio >= SOGLIA_ALTA:
        return "certo"
    return "ambiguo"
```

- [ ] **Step 4: Eseguire il test e verificare che passi**

Run:
```bash
pytest tests/test_matching.py -v
```

Expected: `7 passed`.

- [ ] **Step 5: Eseguire l'intera suite di test del progetto**

Run:
```bash
pytest tests/ -v
```

Expected: tutti i test passano (nessuna regressione sulle Fasi precedenti — 24 pre-esistenti + 7 nuovi = 31 totali).

- [ ] **Step 6: Commit**

```bash
git add core/matching.py tests/test_matching.py
git commit -m "Aggiunge modulo di matching con soglie calibrate (certo/ambiguo/sconosciuto)"
```

---

### Task 2: Verifica su dati reali

**Files:**
- Nessun file di codice nuovo. Verifica il modulo del Task 1 contro il database reale già popolato in Fase 2.

**Interfaces:**
- Consumes: `calcola_candidati`/`classifica_match` da `core/matching.py` (Task 1), `rileva_volti` da `core/volti.py` (Fase 1), `connetti` da `db/database.py`.

- [ ] **Step 1: Verificare il riconoscimento su una foto già nel DB (deve dare "certo")**

Run (con venv attivo, dalla root del progetto — sostituendo il percorso con una foto reale già presente come embedding in `db/volti.db`, es. una delle foto di una persona con più embedding salvati):

```bash
python3 -c "
from core.volti import rileva_volti
from core.matching import calcola_candidati, classifica_match
from db.database import connetti

volti = rileva_volti('/Users/pietrodaprano/Desktop/_prova export per nomi/PI2_3003_WzqHBTgl.jpg')
conn = connetti('db/volti.db')
candidati = calcola_candidati(volti[0].vettore, conn)
for c in candidati:
    print(f'{c.nome}: {c.punteggio:.3f}')
print('classificazione:', classifica_match(candidati))
conn.close()
"
```

Expected: il primo candidato è il nome corretto per quella foto (per `PI2_3003_WzqHBTgl.jpg` ci si aspetta "Nicky Passarella", il nome letto in IPTC durante la Fase 1/2 per questa foto), con punteggio molto alto (vicino a 1.0, dato che è la stessa identica foto/embedding già nel DB) e classificazione `"certo"`.

- [ ] **Step 2: Verificare il comportamento su un volto sconosciuto**

Trovare o creare una foto con un volto di una persona NON presente nel DB (es. una foto personale qualunque con un volto, non da fashion week), ed eseguire lo stesso script sostituendo il percorso. Se non si trova facilmente una foto adatta, generare un embedding sintetico casuale (normalizzato) come sostituto:

```bash
python3 -c "
import numpy as np
from core.matching import calcola_candidati, classifica_match
from db.database import connetti

rng = np.random.default_rng(42)
volto_sconosciuto = rng.random(512).astype(np.float32)
volto_sconosciuto /= np.linalg.norm(volto_sconosciuto)

conn = connetti('db/volti.db')
candidati = calcola_candidati(volto_sconosciuto, conn)
for c in candidati:
    print(f'{c.nome}: {c.punteggio:.3f}')
print('classificazione:', classifica_match(candidati))
conn.close()
"
```

Expected: `classificazione: sconosciuto` (un vettore casuale non deve avvicinarsi a nessuna persona reale nel DB, coerente con la distribuzione inter-persona osservata: max 0.238, ben sotto la soglia bassa di 0.30).

- [ ] **Step 3: Scrivere un breve riepilogo nel report**

Scrivi i risultati reali (nomi, punteggi, classificazioni ottenute) in `.superpowers/sdd/task-2-fase3-report.md` (nuovo file, scratch, già escluso da git). Non serve commit di codice per questo task.

## Definizione di "Fase 3 completata"

`pytest tests/ -v` passa tutti i test (31 totali). La verifica su una foto reale già nel DB ritorna il nome corretto con classificazione "certo". La verifica su un volto/vettore non presente nel DB ritorna "sconosciuto". Il modulo di matching è pronto per essere usato dalla Fase successiva (interfaccia web di revisione).
