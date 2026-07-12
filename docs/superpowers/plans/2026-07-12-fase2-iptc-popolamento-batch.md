# Fase 2: Modulo IPTC e Popolamento Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leggere il nome della persona dal campo IPTC delle foto (`XMP-getty:Personality`, confermato su campione reale), ed eseguire il primo popolamento reale del database volti↔nomi usando il campione di 113 foto già disponibile in `~/Desktop/_prova export per nomi/`.

**Architecture:** `core/iptc.py` legge il campo `XMP-getty:Personality` via `exiftool -j` (subprocess), ritorna la lista dei nomi taggati (uno o più, foto senza tag → lista vuota). `db/database.py` (già esistente dalla Fase 1) si estende con funzioni di scrittura: trova/crea persona, salva embedding, registra scarto. `scripts/popola_batch.py` orchestra tutto: per ogni foto in una cartella, legge nomi + rileva volti (riusando `core/volti.rileva_volti` dalla Fase 1), decide se il caso è "pulito" (esattamente 1 volto e 1 nome) o va scartato, e scrive nel DB o in `log_scarti`.

**Tech Stack:** Stesso della Fase 1 (Python 3.13 venv esistente, InsightFace, SQLite, exiftool via subprocess). Nessuna nuova dipendenza esterna.

## Global Constraints

- Python 3.13 via Homebrew, venv esistente in `venv/` (già configurato, non ricrearlo).
- Nessuna dipendenza da servizi cloud: tutto in locale.
- Nomi di file, variabili, funzioni e commenti in italiano.
- `db/*.db`, `logs/`, `sessioni/` restano esclusi da git (`.gitignore` già presente, non modificarlo).
- Il campo IPTC del nome è `XMP-getty:Personality` (namespace Getty), letto con `exiftool -j -XMP-getty:Personality <file>` (output JSON). Se il campo è assente, la chiave `"Personality"` non compare nel JSON — non è un errore, va trattato come "nessun nome".
- Caso ambiguo (numero di volti rilevati diverso dal numero di nomi letti, in una direzione o nell'altra) → NON tentare abbinamenti automatici: scartare e loggare in `log_scarti` con motivo `volti_multipli`. Procedere al salvataggio automatico SOLO quando c'è esattamente 1 volto rilevato E esattamente 1 nome letto.
- I test automatici NON devono dipendere da `~/Desktop/_prova export per nomi/` (cartella privata dell'utente, foto di persone reali, non deve essere referenziata in codice o test committati). I test usano fixture sintetiche create al volo con PIL + exiftool. La cartella reale si usa SOLO nel Task 4 (verifica manuale/esecuzione reale), passata come argomento a runtime, mai hardcoded.

---

### Task 1: Modulo lettura IPTC (core/iptc.py)

**Files:**
- Create: `core/iptc.py`
- Test: `tests/test_iptc.py`

**Interfaces:**
- Produces: `leggi_nomi(percorso_foto: str | pathlib.Path) -> list[str]` in `core/iptc.py`. Solleva `FileNotFoundError` se il file non esiste. Ritorna lista vuota se il campo `Personality` è assente o vuoto. Ritorna una lista di uno o più nomi (stringhe, senza spazi ai bordi) se il campo è popolato, splittando su virgola.

- [ ] **Step 1: Scrivere il test che fallisce**

Create `tests/test_iptc.py`:

```python
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from core.iptc import leggi_nomi


def _crea_foto_di_prova(percorso: Path, personality: str | None) -> None:
    """Crea una foto JPG minima e, se richiesto, scrive il tag XMP-getty:Personality."""
    Image.new("RGB", (10, 10), color="red").save(percorso)
    if personality is not None:
        subprocess.run(
            [
                "exiftool",
                "-overwrite_original",
                f"-XMP-getty:Personality={personality}",
                str(percorso),
            ],
            check=True,
            capture_output=True,
        )


def test_leggi_nomi_solleva_errore_se_file_non_esiste(tmp_path):
    percorso_inesistente = tmp_path / "non_esiste.jpg"

    with pytest.raises(FileNotFoundError):
        leggi_nomi(percorso_inesistente)


def test_leggi_nomi_singolo_nome(tmp_path):
    percorso = tmp_path / "foto_singola.jpg"
    _crea_foto_di_prova(percorso, "Mario Rossi")

    assert leggi_nomi(percorso) == ["Mario Rossi"]


def test_leggi_nomi_piu_nomi(tmp_path):
    percorso = tmp_path / "foto_multipla.jpg"
    _crea_foto_di_prova(percorso, "Mario Rossi, Anna Bianchi")

    assert leggi_nomi(percorso) == ["Mario Rossi", "Anna Bianchi"]


def test_leggi_nomi_ritorna_lista_vuota_se_personality_assente(tmp_path):
    percorso = tmp_path / "foto_senza_tag.jpg"
    _crea_foto_di_prova(percorso, None)

    assert leggi_nomi(percorso) == []
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run (con venv attivo, dalla root del progetto):
```bash
source venv/bin/activate
pytest tests/test_iptc.py -v
```

Expected: FAIL con `ModuleNotFoundError: No module named 'core.iptc'`.

- [ ] **Step 3: Implementare core/iptc.py**

Create `core/iptc.py`:

```python
"""Lettura del nome della persona dal campo IPTC/XMP delle foto."""

import json
import subprocess
from pathlib import Path


def leggi_nomi(percorso_foto: str | Path) -> list[str]:
    """Legge il campo XMP-getty:Personality da una foto e ritorna i nomi taggati.

    Solleva FileNotFoundError se il file non esiste.
    Ritorna lista vuota se il campo è assente o vuoto (nessun nome taggato).
    Ritorna una lista di uno o più nomi se il campo è popolato (split su virgola).
    """
    percorso_foto = Path(percorso_foto)
    if not percorso_foto.exists():
        raise FileNotFoundError(f"File non trovato: {percorso_foto}")

    risultato = subprocess.run(
        ["exiftool", "-j", "-XMP-getty:Personality", str(percorso_foto)],
        capture_output=True,
        text=True,
        check=True,
    )
    dati = json.loads(risultato.stdout)[0]
    personality = dati.get("Personality", "")
    if not personality:
        return []
    return [nome.strip() for nome in personality.split(",") if nome.strip()]
```

- [ ] **Step 4: Eseguire il test e verificare che passi**

Run:
```bash
pytest tests/test_iptc.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add core/iptc.py tests/test_iptc.py
git commit -m "Aggiunge modulo lettura nome da IPTC (XMP-getty:Personality)"
```

---

### Task 2: Estensioni database per il popolamento (db/database.py)

**Files:**
- Modify: `db/database.py`
- Test: `tests/test_database.py` (aggiungere test, non toccare quelli esistenti)

**Interfaces:**
- Consumes: `connetti`, `init_db` già esistenti in `db/database.py` (Fase 1). `VoltoRilevato.vettore` da `core/volti.py` è un `numpy.ndarray` shape `(512,)` dtype `float32` — la funzione di salvataggio embedding deve accettare esattamente questo tipo.
- Produces (nuove funzioni in `db/database.py`):
  - `trova_o_crea_persona(conn: sqlite3.Connection, nome: str) -> int` — ritorna l'id della persona con quel nome, creandola se non esiste.
  - `salva_embedding(conn: sqlite3.Connection, person_id: int, vettore: numpy.ndarray, foto_origine: str, fonte: str) -> int` — inserisce una riga in `embedding`, ritorna l'id creato.
  - `registra_scarto(conn: sqlite3.Connection, foto: str, motivo: str) -> int` — inserisce una riga in `log_scarti`, ritorna l'id creato.

  Queste funzioni NON aprono/chiudono la connessione (a differenza di `init_db`) — ricevono una connessione già aperta e fanno `commit()` internamente dopo ogni scrittura, così lo script di popolamento (Task 3) può salvare foto per foto senza perdere progresso in caso di interruzione a metà batch.

- [ ] **Step 1: Scrivere i test che falliscono**

Add to `tests/test_database.py` (in fondo al file, dopo i test esistenti):

```python
import numpy as np

from db.database import trova_o_crea_persona, salva_embedding, registra_scarto


def test_trova_o_crea_persona_crea_nuova_persona(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    person_id = trova_o_crea_persona(conn, "Mario Rossi")

    riga = conn.execute(
        "SELECT nome FROM persone WHERE id = ?", (person_id,)
    ).fetchone()
    conn.close()
    assert riga[0] == "Mario Rossi"


def test_trova_o_crea_persona_riusa_persona_esistente(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    primo_id = trova_o_crea_persona(conn, "Mario Rossi")
    secondo_id = trova_o_crea_persona(conn, "Mario Rossi")

    conteggio = conn.execute("SELECT COUNT(*) FROM persone").fetchone()[0]
    conn.close()
    assert primo_id == secondo_id
    assert conteggio == 1


def test_salva_embedding_inserisce_e_recupera_vettore(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)
    person_id = trova_o_crea_persona(conn, "Mario Rossi")
    vettore_originale = np.random.rand(512).astype(np.float32)

    embedding_id = salva_embedding(
        conn, person_id, vettore_originale, "foto.jpg", "batch_iniziale"
    )

    riga = conn.execute(
        "SELECT vettore, person_id, foto_origine, fonte FROM embedding WHERE id = ?",
        (embedding_id,),
    ).fetchone()
    conn.close()
    vettore_recuperato = np.frombuffer(riga[0], dtype=np.float32)
    assert np.array_equal(vettore_recuperato, vettore_originale)
    assert riga[1] == person_id
    assert riga[2] == "foto.jpg"
    assert riga[3] == "batch_iniziale"


def test_registra_scarto_inserisce_riga(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    conn = connetti(percorso_db)

    scarto_id = registra_scarto(conn, "foto_scartata.jpg", "nessun_volto")

    riga = conn.execute(
        "SELECT foto, motivo FROM log_scarti WHERE id = ?", (scarto_id,)
    ).fetchone()
    conn.close()
    assert riga[0] == "foto_scartata.jpg"
    assert riga[1] == "nessun_volto"
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run:
```bash
pytest tests/test_database.py -v
```

Expected: FAIL con `ImportError: cannot import name 'trova_o_crea_persona' from 'db.database'` (i 4 test nuovi falliscono, i test esistenti di Fase 1 continuano a passare una volta risolto l'import — per ora falliscono tutti per lo stesso ImportError a livello di modulo).

- [ ] **Step 3: Implementare le funzioni in db/database.py**

Add to `db/database.py` (in fondo al file, dopo `init_db`):

```python
import numpy as np


def trova_o_crea_persona(conn: sqlite3.Connection, nome: str) -> int:
    """Ritorna l'id della persona con quel nome, creandola se non esiste già."""
    riga = conn.execute("SELECT id FROM persone WHERE nome = ?", (nome,)).fetchone()
    if riga is not None:
        return riga[0]
    cursor = conn.execute("INSERT INTO persone (nome) VALUES (?)", (nome,))
    conn.commit()
    return cursor.lastrowid


def salva_embedding(
    conn: sqlite3.Connection,
    person_id: int,
    vettore: np.ndarray,
    foto_origine: str,
    fonte: str,
) -> int:
    """Inserisce un embedding legato a una persona. Ritorna l'id della riga creata."""
    cursor = conn.execute(
        "INSERT INTO embedding (person_id, vettore, foto_origine, fonte) "
        "VALUES (?, ?, ?, ?)",
        (person_id, vettore.astype(np.float32).tobytes(), foto_origine, fonte),
    )
    conn.commit()
    return cursor.lastrowid


def registra_scarto(conn: sqlite3.Connection, foto: str, motivo: str) -> int:
    """Registra una foto scartata durante il popolamento. Ritorna l'id della riga creata."""
    cursor = conn.execute(
        "INSERT INTO log_scarti (foto, motivo) VALUES (?, ?)", (foto, motivo)
    )
    conn.commit()
    return cursor.lastrowid
```

Note: sposta `import numpy as np` in cima al file insieme agli altri import (non lasciarlo in mezzo al file) — nel blocco `import sqlite3` / `from pathlib import Path` già esistente in testa a `db/database.py`.

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run:
```bash
pytest tests/test_database.py -v
```

Expected: tutti i test passano (i 5 originali della Fase 1 + i 4 nuovi = 9 totali).

- [ ] **Step 5: Commit**

```bash
git add db/database.py tests/test_database.py
git commit -m "Aggiunge funzioni di scrittura DB per il popolamento (persona, embedding, scarto)"
```

---

### Task 3: Script di popolamento batch (scripts/popola_batch.py)

**Files:**
- Create: `scripts/popola_batch.py`
- Test: `tests/test_popola_batch.py`

**Interfaces:**
- Consumes: `leggi_nomi` da `core.iptc` (Task 1), `rileva_volti`/`VoltoRilevato` da `core.volti` (Fase 1), `connetti`/`init_db`/`trova_o_crea_persona`/`salva_embedding`/`registra_scarto` da `db.database` (Task 2).
- Produces: `classifica_caso(nomi: list[str], volti: list) -> str | None` in `scripts/popola_batch.py` — pura logica di decisione, senza I/O, testabile in isolamento. Ritorna il `motivo` di scarto (`"iptc_mancante"`, `"nessun_volto"`, `"volti_multipli"`) oppure `None` se il caso è pulito (esattamente 1 volto e 1 nome, si può procedere al salvataggio).

- [ ] **Step 1: Scrivere il test che fallisce**

Create `tests/test_popola_batch.py`:

```python
import pytest

from scripts.popola_batch import classifica_caso


def test_classifica_caso_nessun_nome():
    assert classifica_caso([], ["volto_finto"]) == "iptc_mancante"


def test_classifica_caso_nessun_volto():
    assert classifica_caso(["Mario Rossi"], []) == "nessun_volto"


def test_classifica_caso_piu_volti_un_nome():
    assert classifica_caso(["Mario Rossi"], ["volto1", "volto2"]) == "volti_multipli"


def test_classifica_caso_un_volto_piu_nomi():
    assert (
        classifica_caso(["Mario Rossi", "Anna Bianchi"], ["volto1"]) == "volti_multipli"
    )


def test_classifica_caso_pulito_un_volto_un_nome():
    assert classifica_caso(["Mario Rossi"], ["volto1"]) is None
```

Note: i test passano liste di stringhe finte al posto di `VoltoRilevato` reali per il parametro `volti` — `classifica_caso` deve usare solo `len()`, non deve ispezionare il contenuto degli elementi, quindi va bene testarla con qualunque lista della lunghezza giusta.

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run:
```bash
pytest tests/test_popola_batch.py -v
```

Expected: FAIL con `ModuleNotFoundError: No module named 'scripts.popola_batch'`.

- [ ] **Step 3: Implementare scripts/popola_batch.py**

Create `scripts/popola_batch.py`:

```python
"""Popolamento iniziale del database volti a partire da un archivio di foto taggate.

Uso:
    python scripts/popola_batch.py <cartella_archivio>

Scansiona la cartella (e sottocartelle) alla ricerca di JPG, legge il nome
dal campo IPTC (XMP-getty:Personality) e il volto rilevato da InsightFace.
Salva nel DB solo i casi puliti (esattamente 1 volto e 1 nome); tutti gli
altri casi vengono registrati in log_scarti per revisione manuale.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.iptc import leggi_nomi
from core.volti import rileva_volti
from db.database import (
    connetti,
    init_db,
    registra_scarto,
    salva_embedding,
    trova_o_crea_persona,
)

PERCORSO_DB_DEFAULT = Path(__file__).resolve().parent.parent / "db" / "volti.db"


def classifica_caso(nomi: list[str], volti: list) -> str | None:
    """Decide se una foto è un caso pulito da salvare o va scartata.

    Ritorna il motivo dello scarto, oppure None se il caso è pulito
    (esattamente 1 volto rilevato e esattamente 1 nome taggato).
    """
    if not nomi:
        return "iptc_mancante"
    if not volti:
        return "nessun_volto"
    if len(volti) != 1 or len(nomi) != 1:
        return "volti_multipli"
    return None


def popola_da_cartella(cartella: Path, percorso_db: Path) -> dict[str, int]:
    """Elabora tutte le foto JPG in cartella (ricorsivo) e popola il DB.

    Ritorna un riepilogo: {'salvate': N, 'iptc_mancante': N, 'nessun_volto': N,
    'volti_multipli': N, 'iptc_non_parsabile': N}.
    """
    init_db(percorso_db)
    conn = connetti(percorso_db)
    riepilogo = {
        "salvate": 0,
        "iptc_mancante": 0,
        "nessun_volto": 0,
        "volti_multipli": 0,
        "iptc_non_parsabile": 0,
    }

    foto_trovate = sorted(
        [
            *cartella.rglob("*.jpg"),
            *cartella.rglob("*.JPG"),
            *cartella.rglob("*.jpeg"),
            *cartella.rglob("*.JPEG"),
        ]
    )

    for foto in foto_trovate:
        try:
            nomi = leggi_nomi(foto)
        except Exception as errore:
            registra_scarto(conn, str(foto), "iptc_non_parsabile")
            riepilogo["iptc_non_parsabile"] += 1
            print(f"[iptc_non_parsabile] {foto.name}: {errore}")
            continue

        volti = rileva_volti(foto)
        motivo = classifica_caso(nomi, volti)

        if motivo is not None:
            registra_scarto(conn, str(foto), motivo)
            riepilogo[motivo] += 1
            print(f"[{motivo}] {foto.name}")
            continue

        person_id = trova_o_crea_persona(conn, nomi[0])
        salva_embedding(conn, person_id, volti[0].vettore, str(foto), "batch_iniziale")
        riepilogo["salvate"] += 1
        print(f"[salvata] {foto.name} -> {nomi[0]}")

    conn.close()
    return riepilogo


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python scripts/popola_batch.py <cartella_archivio>")
        return 1

    cartella = Path(sys.argv[1])
    if not cartella.is_dir():
        print(f"Cartella non trovata: {cartella}")
        return 1

    riepilogo = popola_da_cartella(cartella, PERCORSO_DB_DEFAULT)

    print("\n--- Riepilogo popolamento ---")
    for chiave, valore in riepilogo.items():
        print(f"{chiave}: {valore}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Eseguire il test e verificare che passi**

Run:
```bash
pytest tests/test_popola_batch.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Eseguire l'intera suite di test del progetto**

Run:
```bash
pytest tests/ -v
```

Expected: tutti i test passano (nessuna regressione sulle Fasi precedenti).

- [ ] **Step 6: Commit**

```bash
git add scripts/popola_batch.py tests/test_popola_batch.py
git commit -m "Aggiunge script di popolamento batch con classificazione casi puliti/scarti"
```

---

### Task 4: Esecuzione reale del popolamento sul campione disponibile

**Files:**
- Nessun file di codice nuovo. Questo task esegue lo script del Task 3 contro dati reali e verifica il risultato nel DB.

**Interfaces:**
- Consumes: `popola_da_cartella`/`main` da `scripts/popola_batch.py` (Task 3).

- [ ] **Step 1: Eseguire il popolamento sul campione reale**

Run (con venv attivo, dalla root del progetto):
```bash
source venv/bin/activate
python scripts/popola_batch.py "/Users/pietrodaprano/Desktop/_prova export per nomi"
```

Expected: lo script processa le 113 foto della cartella campione, stampa una riga per foto (`[salvata] ...` o `[motivo] ...`), e termina con un riepilogo. In base all'ispezione fatta durante il design (111/113 foto con Personality valorizzato, 2/113 vuote, ~20/113 con più nomi), attendersi approssimativamente: `iptc_mancante` intorno a 2, `volti_multipli` intorno a 20 (i casi con più nomi — a meno che InsightFace rilevi anche più di un volto in quelle foto, nel qual caso il numero potrebbe variare), il resto (`salvate` + eventuali `nessun_volto` se qualche foto ha il volto non rilevabile) a coprire i restanti ~91 file. Non serve che i numeri combacino esattamente: l'obiettivo è che lo script giri senza errori Python non gestiti (crash) su tutte le 113 foto.

- [ ] **Step 2: Verificare il contenuto del DB popolato**

Run:
```bash
sqlite3 db/volti.db "SELECT COUNT(*) FROM persone;"
sqlite3 db/volti.db "SELECT COUNT(*) FROM embedding;"
sqlite3 db/volti.db "SELECT COUNT(*) FROM log_scarti;"
sqlite3 db/volti.db "SELECT nome, COUNT(*) FROM persone p JOIN embedding e ON e.person_id = p.id GROUP BY p.nome ORDER BY COUNT(*) DESC;"
sqlite3 db/volti.db "SELECT motivo, COUNT(*) FROM log_scarti GROUP BY motivo;"
```

Expected: il numero di persone create corrisponde ai nomi distinti visti nei casi "puliti" (es. "Nicky Passarella", "Jaren Jackson Jr", "Diego Della Valle", "Suzi de Givenchy", ecc. — ognuno con più embedding se compare in più foto). Il totale `persone + embedding + log_scarti` per riga processata deve tornare coerente con le 113 foto (ogni foto o produce un embedding salvato, o produce esattamente una riga di scarto).

- [ ] **Step 3: Scrivere un breve riepilogo dei risultati nel report**

Scrivi il riepilogo effettivo (numeri reali ottenuti dai comandi sopra) in un file di report: `.superpowers/sdd/task-4-fase2-report.md` (nuovo file), includendo: numero di persone create, numero di embedding salvati, conteggio scarti per motivo, ed eventuali anomalie osservate (es. foto con più volti rilevati che avevano un solo nome, o viceversa — utile per la Fase 4/matching futura).

Non serve commit di codice per questo task (nessun file sotto controllo versione viene modificato — `db/volti.db` è gitignored). Il file di report in `.superpowers/sdd/` è scratch, già escluso da git dal Task 1 della Fase 1.

## Definizione di "Fase 2 completata"

`pytest tests/ -v` passa tutti i test (Fase 1 + Fase 2). `python scripts/popola_batch.py "/Users/pietrodaprano/Desktop/_prova export per nomi"` gira senza crash su tutte le 113 foto del campione, popolando `db/volti.db` con persone ed embedding reali, e classificando correttamente i casi ambigui in `log_scarti`. Questo è il primo popolamento reale del database — da qui in poi il DB contiene dati veri, pronti per la Fase 4 (matching).
