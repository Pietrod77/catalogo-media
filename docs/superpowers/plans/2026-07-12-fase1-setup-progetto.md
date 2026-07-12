# Fase 1: Setup Progetto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Predisporre l'ambiente di lavoro completo (struttura cartelle, virtualenv, dipendenze, schema DB, modulo di rilevamento volti) e verificare concretamente che InsightFace rilevi volti e calcoli embedding su questo Mac (Apple Silicon).

**Architecture:** Progetto Python in `~/Dropbox/Volti_Riconoscimento/`. `db/database.py` inizializza lo schema SQLite. `core/volti.py` incapsula rilevamento volto + embedding via InsightFace (modello `buffalo_l`, `onnxruntime` CPU). `scripts/verifica_setup.py` esegue una verifica end-to-end di tutti i componenti.

**Tech Stack:** Python 3.13 (Homebrew, venv dedicato), InsightFace + onnxruntime, OpenCV (headless), SQLite (libreria standard `sqlite3`), pytest, exiftool (già installato, invocato via subprocess in fasi successive).

## Global Constraints

- Python 3.13 via Homebrew, mai il Python 3.9 di sistema.
- Nessuna dipendenza da servizi cloud: tutto deve girare in locale.
- `venv/`, `db/*.db`, `logs/`, `sessioni/` restano esclusi da git (`.gitignore` già presente).
- Nomi di file, variabili, funzioni e commenti in italiano, coerente con il resto del progetto e del design doc (`docs/superpowers/specs/2026-07-12-riconoscimento-volti-design.md`).
- SQLite va usato in modalità journal di default (NON abilitare WAL), per compatibilità con la sync futura via Dropbox multi-computer.

---

### Task 1: Struttura cartelle e README

**Files:**
- Create: `core/__init__.py`
- Create: `db/__init__.py`
- Create: `scripts/__init__.py`
- Create: `templates/.gitkeep`
- Create: `static/.gitkeep`
- Create: `README.md`

**Interfaces:**
- Produces: struttura di cartelle su cui i Task successivi creeranno i moduli (`core/`, `db/`, `scripts/`, `templates/`, `static/`).

- [ ] **Step 1: Creare le cartelle mancanti**

Run:
```bash
cd ~/Dropbox/Volti_Riconoscimento
mkdir -p core db scripts templates static logs sessioni
touch core/__init__.py db/__init__.py scripts/__init__.py templates/.gitkeep static/.gitkeep
```

Expected: nessun output, le cartelle esistono (`ls` le mostra tutte).

- [ ] **Step 2: Scrivere il README.md**

Create `README.md`:

```markdown
# Volti_Riconoscimento

Database locale volti↔nomi per identificazione soggetti fotografici (fashion week, backstage, front row). Uso esclusivamente locale, nessun dato biometrico condiviso con servizi cloud.

Design completo: `docs/superpowers/specs/2026-07-12-riconoscimento-volti-design.md`.

## Setup su un nuovo computer

1. Assicurati che questa cartella sia già sincronizzata da Dropbox.
2. Installa Python 3.13 via Homebrew se non presente: `brew install python@3.13`
3. Crea il virtualenv locale (NON sincronizzato, va ricreato su ogni macchina):
   ```bash
   python3.13 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. Escludi `venv/` dalla sincronizzazione Dropbox (comando one-time per macchina):
   ```bash
   xattr -w com.dropbox.ignored 1 venv
   ```
5. Verifica che `exiftool` sia installato: `exiftool -ver` (su Mac: `brew install exiftool`).
6. Esegui la verifica end-to-end:
   ```bash
   python scripts/verifica_setup.py /percorso/a/una/foto/con/un/volto.jpg
   ```

## Regola d'oro multi-computer

Non tenere l'app aperta su due computer contemporaneamente: il database SQLite condiviso via Dropbox non è pensato per scritture concorrenti da macchine diverse. Chiudi l'app e aspetta che Dropbox finisca di sincronizzare prima di passare a un altro computer.
```

- [ ] **Step 3: Commit**

```bash
cd ~/Dropbox/Volti_Riconoscimento
git add core/__init__.py db/__init__.py scripts/__init__.py templates/.gitkeep static/.gitkeep README.md
git commit -m "Struttura cartelle progetto e README setup"
```

---

### Task 2: Virtualenv e dipendenze

**Files:**
- Create: `requirements.txt`

**Interfaces:**
- Produces: virtualenv `venv/` attivabile con `source venv/bin/activate`, con tutte le librerie installate e importabili, usato da tutti i task successivi.

- [ ] **Step 1: Scrivere requirements.txt**

Create `requirements.txt`:

```
insightface
onnxruntime
opencv-python-headless
numpy
flask
pillow
pytest
```

- [ ] **Step 2: Creare il virtualenv con Python 3.13**

Run:
```bash
cd ~/Dropbox/Volti_Riconoscimento
/opt/homebrew/bin/python3.13 -m venv venv
source venv/bin/activate
python --version
```

Expected: `Python 3.13.x`

- [ ] **Step 3: Installare le dipendenze**

Run (con venv attivo):
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Expected: installazione completata senza errori. Se `insightface` o `onnxruntime` falliscono con errori di compilazione, annotare l'errore esatto: è il segnale che va rivista la scelta della libreria (non atteso su arm64 con wheel precompilati, ma va verificato concretamente qui).

- [ ] **Step 4: Verificare che le librerie si importino correttamente**

Run (con venv attivo):
```bash
python -c "import insightface, onnxruntime, cv2, flask, numpy, PIL; print('OK: tutte le librerie importate correttamente')"
```

Expected: `OK: tutte le librerie importate correttamente`

- [ ] **Step 5: Escludere venv dalla sincronizzazione Dropbox**

Run:
```bash
cd ~/Dropbox/Volti_Riconoscimento
xattr -w com.dropbox.ignored 1 venv
xattr -p com.dropbox.ignored venv
```

Expected: il secondo comando stampa `1`, confermando l'esclusione.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt
git commit -m "Aggiunge requirements.txt e verifica installazione dipendenze"
```

---

### Task 3: Schema database (TDD)

**Files:**
- Create: `db/database.py`
- Test: `tests/test_database.py`

**Interfaces:**
- Produces: `init_db(percorso_db: str | pathlib.Path) -> None` in `db/database.py` — crea (se non esistono) le tabelle `persone`, `embedding`, `log_scarti` nel file SQLite indicato. `connetti(percorso_db: str | pathlib.Path) -> sqlite3.Connection` — apre una connessione con `journal_mode` di default (NON WAL).

- [ ] **Step 1: Scrivere il test che fallisce**

Create `tests/__init__.py` (vuoto) e `tests/test_database.py`:

```python
import sqlite3
from pathlib import Path

from db.database import init_db, connetti


def test_init_db_crea_le_tre_tabelle(tmp_path):
    percorso_db = tmp_path / "volti_test.db"

    init_db(percorso_db)

    conn = connetti(percorso_db)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tabelle = {riga[0] for riga in cursor.fetchall()}
    conn.close()

    assert {"persone", "embedding", "log_scarti"}.issubset(tabelle)


def test_init_db_e_idempotente(tmp_path):
    percorso_db = tmp_path / "volti_test.db"

    init_db(percorso_db)
    init_db(percorso_db)  # non deve sollevare errori se richiamata due volte

    conn = connetti(percorso_db)
    cursor = conn.execute("SELECT COUNT(*) FROM persone")
    assert cursor.fetchone()[0] == 0
    conn.close()


def test_connetti_usa_journal_mode_default_non_wal(tmp_path):
    percorso_db = tmp_path / "volti_test.db"

    init_db(percorso_db)
    conn = connetti(percorso_db)
    modalita = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()

    assert modalita.lower() != "wal"
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run (con venv attivo, dalla root del progetto):
```bash
pytest tests/test_database.py -v
```

Expected: FAIL con `ModuleNotFoundError: No module named 'db.database'` (o simile, perché `db/database.py` non esiste ancora).

- [ ] **Step 3: Implementare db/database.py**

Create `db/database.py`:

```python
"""Inizializzazione e connessione al database SQLite dei volti."""

import sqlite3
from pathlib import Path

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
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS log_scarti (
    id INTEGER PRIMARY KEY,
    foto TEXT NOT NULL,
    motivo TEXT NOT NULL,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def connetti(percorso_db: str | Path) -> sqlite3.Connection:
    """Apre una connessione al DB. Modalità journal di default (non WAL),
    per compatibilità con la sincronizzazione via Dropbox su più computer."""
    conn = sqlite3.connect(str(percorso_db))
    return conn


def init_db(percorso_db: str | Path) -> None:
    """Crea le tabelle persone, embedding, log_scarti se non esistono già."""
    conn = connetti(percorso_db)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Eseguire il test e verificare che passi**

Run:
```bash
pytest tests/test_database.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add db/database.py tests/__init__.py tests/test_database.py
git commit -m "Aggiunge schema database SQLite (persone, embedding, log_scarti)"
```

---

### Task 4: Modulo di rilevamento volti ed embedding (InsightFace)

**Files:**
- Create: `core/volti.py`
- Test: `tests/test_volti.py`

**Interfaces:**
- Consumes: nessuna dipendenza dai task precedenti oltre alle librerie installate in Task 2.
- Produces: `VoltoRilevato` (dataclass con campi `vettore: numpy.ndarray` shape `(512,)` dtype `float32`, `bbox: tuple[int, int, int, int]`, `score: float`) e `rileva_volti(percorso_foto: str | pathlib.Path) -> list[VoltoRilevato]` in `core/volti.py`. Questi sono i tipi/firme che i moduli di matching (Fase 4 del design) e di popolamento batch (Fase 3) useranno.

- [ ] **Step 1: Scrivere il test che fallisce (caso file inesistente, non richiede modello)**

Create `tests/test_volti.py`:

```python
from pathlib import Path

import pytest

from core.volti import rileva_volti


def test_rileva_volti_solleva_errore_se_file_non_esiste(tmp_path):
    percorso_inesistente = tmp_path / "non_esiste.jpg"

    with pytest.raises(FileNotFoundError):
        rileva_volti(percorso_inesistente)
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run:
```bash
pytest tests/test_volti.py -v
```

Expected: FAIL con `ModuleNotFoundError: No module named 'core.volti'`.

- [ ] **Step 3: Implementare core/volti.py**

Create `core/volti.py`:

```python
"""Rilevamento volti e calcolo embedding facciali tramite InsightFace."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis

_modello: FaceAnalysis | None = None


@dataclass
class VoltoRilevato:
    vettore: np.ndarray  # embedding, shape (512,), dtype float32
    bbox: tuple[int, int, int, int]
    score: float


def carica_modello() -> FaceAnalysis:
    """Carica il modello InsightFace (buffalo_l) una sola volta per processo."""
    global _modello
    if _modello is None:
        _modello = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _modello.prepare(ctx_id=-1, det_size=(640, 640))
    return _modello


def rileva_volti(percorso_foto: str | Path) -> list[VoltoRilevato]:
    """Rileva tutti i volti in una foto e ne calcola l'embedding.

    Solleva FileNotFoundError se il file non esiste.
    Ritorna lista vuota se il file esiste ma non contiene volti rilevabili.
    """
    percorso_foto = Path(percorso_foto)
    if not percorso_foto.exists():
        raise FileNotFoundError(f"File non trovato: {percorso_foto}")

    immagine = cv2.imread(str(percorso_foto))
    if immagine is None:
        raise ValueError(f"Impossibile leggere l'immagine: {percorso_foto}")

    modello = carica_modello()
    volti = modello.get(immagine)

    risultati = []
    for volto in volti:
        bbox = tuple(int(v) for v in volto.bbox)
        risultati.append(
            VoltoRilevato(
                vettore=volto.normed_embedding.astype(np.float32),
                bbox=bbox,
                score=float(volto.det_score),
            )
        )
    return risultati
```

- [ ] **Step 4: Eseguire il test e verificare che passi**

Run:
```bash
pytest tests/test_volti.py -v
```

Expected: `1 passed`. Al primo avvio InsightFace scarica il modello `buffalo_l` (~300MB) in `~/.insightface/models/` — è normale che questo step richieda qualche minuto la prima volta.

- [ ] **Step 5: Individuare una foto reale con un volto per la verifica manuale**

Run:
```bash
find ~/Pictures ~/Desktop ~/Downloads -maxdepth 3 \( -iname "*.jpg" -o -iname "*.jpeg" \) 2>/dev/null | head -10
```

Se il comando restituisce almeno un percorso, sceglierne uno che sappiamo contenere un volto (es. un ritratto, un selfie, una foto di un evento) e procedere con lo Step 6 usando quel percorso.

Se non restituisce nulla (come verificato nell'esplorazione fatta durante il brainstorming: le cartelle `~/Pictures/Tony Ward fw26` e `~/Pictures/milano uomo` contengono solo cataloghi Lightroom/Capture One senza JPG esportati localmente), chiedere a Pietro il percorso di una singola foto JPG con un volto da usare solo per questo smoke test — non serve che sia dall'archivio taggato, serve solo a confermare che InsightFace rileva volti su questo Mac.

- [ ] **Step 6: Verificare manualmente il rilevamento su una foto reale**

Run (sostituendo il percorso con quello trovato/fornito allo Step 5):
```bash
python -c "
from core.volti import rileva_volti
risultati = rileva_volti('/percorso/alla/foto.jpg')
print(f'Volti rilevati: {len(risultati)}')
for i, volto in enumerate(risultati):
    print(f'  Volto {i}: shape embedding={volto.vettore.shape}, dtype={volto.vettore.dtype}, score={volto.score:.3f}, bbox={volto.bbox}')
"
```

Expected: `Volti rilevati: 1` (o più, se la foto ne contiene più di uno), con `shape embedding=(512,)` e `dtype=float32` per ciascun volto. Questo conferma che InsightFace funziona correttamente su questo Mac (Apple Silicon) end-to-end.

- [ ] **Step 7: Commit**

```bash
git add core/volti.py tests/test_volti.py
git commit -m "Aggiunge modulo rilevamento volti ed embedding con InsightFace"
```

---

### Task 5: Script di verifica end-to-end della Fase 1

**Files:**
- Create: `scripts/verifica_setup.py`

**Interfaces:**
- Consumes: `init_db` e `connetti` da `db.database`, `rileva_volti` da `core.volti`.
- Produces: script CLI eseguibile che conferma in un colpo d'occhio che tutti i componenti della Fase 1 funzionano.

- [ ] **Step 1: Scrivere scripts/verifica_setup.py**

Create `scripts/verifica_setup.py`:

```python
"""Verifica end-to-end del setup della Fase 1: DB, exiftool, InsightFace.

Uso:
    python scripts/verifica_setup.py [percorso_foto_con_volto.jpg]

Se il percorso della foto non viene passato, salta solo il controllo
del rilevamento volti (utile finché non si ha ancora una foto di prova).
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import init_db, connetti
from core.volti import rileva_volti


def verifica_database() -> bool:
    percorso_db = Path(__file__).resolve().parent.parent / "db" / "volti_verifica.db"
    try:
        init_db(percorso_db)
        conn = connetti(percorso_db)
        tabelle = {
            riga[0]
            for riga in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        percorso_db.unlink()
        ok = {"persone", "embedding", "log_scarti"}.issubset(tabelle)
        print(f"[{'OK' if ok else 'FAIL'}] Database: schema creato correttamente")
        return ok
    except Exception as errore:
        print(f"[FAIL] Database: {errore}")
        return False


def verifica_exiftool() -> bool:
    try:
        risultato = subprocess.run(
            ["exiftool", "-ver"], capture_output=True, text=True, check=True
        )
        print(f"[OK] exiftool: versione {risultato.stdout.strip()}")
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as errore:
        print(f"[FAIL] exiftool non trovato o non funzionante: {errore}")
        return False


def verifica_insightface(percorso_foto: str | None) -> bool:
    if percorso_foto is None:
        print("[SKIP] InsightFace: nessuna foto di prova passata come argomento")
        return True
    try:
        risultati = rileva_volti(percorso_foto)
        if not risultati:
            print(f"[FAIL] InsightFace: nessun volto rilevato in {percorso_foto}")
            return False
        volto = risultati[0]
        ok = volto.vettore.shape == (512,)
        print(
            f"[{'OK' if ok else 'FAIL'}] InsightFace: {len(risultati)} volto/i rilevato/i, "
            f"embedding shape={volto.vettore.shape}"
        )
        return ok
    except Exception as errore:
        print(f"[FAIL] InsightFace: {errore}")
        return False


def main() -> int:
    percorso_foto = sys.argv[1] if len(sys.argv) > 1 else None

    risultati = [
        verifica_database(),
        verifica_exiftool(),
        verifica_insightface(percorso_foto),
    ]

    if all(risultati):
        print("\nFase 1 completata: tutti i componenti funzionano correttamente.")
        return 0
    else:
        print("\nAlcuni controlli sono falliti, vedi sopra.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Eseguire lo script senza foto di prova**

Run:
```bash
cd ~/Dropbox/Volti_Riconoscimento
source venv/bin/activate
python scripts/verifica_setup.py
```

Expected:
```
[OK] Database: schema creato correttamente
[OK] exiftool: versione X.XX
[SKIP] InsightFace: nessuna foto di prova passata come argomento

Fase 1 completata: tutti i componenti funzionano correttamente.
```

- [ ] **Step 3: Eseguire lo script con la foto di prova individuata nel Task 4**

Run (sostituendo il percorso con quello usato nel Task 4, Step 6):
```bash
python scripts/verifica_setup.py /percorso/alla/foto.jpg
```

Expected:
```
[OK] Database: schema creato correttamente
[OK] exiftool: versione X.XX
[OK] InsightFace: 1 volto/i rilevato/i, embedding shape=(512,)

Fase 1 completata: tutti i componenti funzionano correttamente.
```

- [ ] **Step 4: Commit**

```bash
git add scripts/verifica_setup.py
git commit -m "Aggiunge script di verifica end-to-end Fase 1"
```

---

## Definizione di "Fase 1 completata"

`python scripts/verifica_setup.py <percorso_foto_con_volto>` stampa `[OK]` su tutti e tre i controlli (database, exiftool, InsightFace) e termina con "Fase 1 completata". A questo punto l'ambiente è pronto per la Fase 2 (ispezione del campo IPTC sull'archivio reale, non appena Pietro ne individua la posizione).
