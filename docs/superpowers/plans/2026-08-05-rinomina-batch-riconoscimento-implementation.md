# Rinomina batch tramite riconoscimento volti — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nuovo script `scripts/rinomina_batch.py` che rileva i volti in una cartella di foto non taggate, li confronta col database "personaggi" già popolato, e produce copie delle foto rinominate col nome della persona riconosciuta (o un marcatore per i casi incerti/sconosciuti/senza volto).

**Architecture:** Script standalone che riusa `core.volti.rileva_volti`, `core.matching.calcola_candidati`/`classifica_match` e `db.database.connetti` così come sono — nessuna modifica al codice esistente. Una funzione testabile `rinomina_da_cartella()` fa il lavoro, un `main()` sottile fa da wrapper CLI — stesso pattern già usato in `scripts/popola_batch.py`.

**Tech Stack:** Python 3.13, stessa suite (numpy, Pillow per i test, pytest), nessuna nuova dipendenza.

## Global Constraints

- Design approvato in `docs/superpowers/specs/2026-08-05-rinomina-batch-riconoscimento-design.md` — nessuna modifica a `core/volti.py`, `core/matching.py`, `db/database.py`.
- Confronto sempre contro il database **personaggi** (fisso, non parametrizzabile).
- Soglie di match invariate: certo ≥ 0.45, ambiguo 0.30–0.45, sconosciuto < 0.30 (`core/matching.py`, non toccarle).
- Copia i file, non li sposta mai — gli originali nella cartella di input restano intatti.
- Formato nome file esatto: `<nomeoriginale>_<segmenti>.<ext>` dove ogni segmento è, per volto, uno tra `Nome_Cognome_XX` (certo), `Nome_Cognome_XX_DA_VERIFICARE` (ambiguo), `sconosciuto` (nessun match valido); una foto senza volti rilevati produce `<nomeoriginale>_NESSUN_VOLTO.<ext>` (nessun segmento per volto, marcatore unico). `XX` è il punteggio del miglior candidato moltiplicato per 100 e arrotondato all'intero.

---

### Task 1: `scripts/rinomina_batch.py` con test

**Files:**
- Create: `scripts/rinomina_batch.py`
- Test: `tests/test_rinomina_batch.py`

**Interfaces:**
- Consumes: `rileva_volti(percorso_foto) -> list[VoltoRilevato]` (da `core.volti`, solleva `ValueError` se immagine illeggibile), `calcola_candidati(vettore, conn, top_n=3) -> list[Candidato]` e `classifica_match(candidati) -> str` (`"certo"|"ambiguo"|"sconosciuto"`, da `core.matching`), `connetti(percorso_db) -> sqlite3.Connection` (da `db.database`).
- Produces: `rinomina_da_cartella(cartella_input: Path, cartella_output: Path, percorso_db: Path) -> dict[str, int]` — chiavi del dict: `foto_totali`, `certo`, `ambiguo`, `sconosciuto`, `nessun_volto`, `errore_lettura_immagine` (conteggi per volto, tranne `foto_totali` e `errore_lettura_immagine` che sono per foto). Anche `_sanitizza_nome(nome: str) -> str` (helper interno, testato direttamente).

- [ ] **Step 1: Scrivere i test**

Crea `tests/test_rinomina_batch.py`:

```python
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core.volti import VoltoRilevato
from db.database import connetti, init_db, salva_embedding, trova_o_crea_persona
from scripts.rinomina_batch import _sanitizza_nome, rinomina_da_cartella


def _vettore_normalizzato(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    return v / np.linalg.norm(v)


def _vettore_con_similarita(base: np.ndarray, similarita: float, seed: int) -> np.ndarray:
    """Costruisce un vettore normalizzato con cosine similarity esatta rispetto a base
    (per testare in modo deterministico i confini certo/ambiguo/sconosciuto)."""
    rng = np.random.default_rng(seed)
    casuale = rng.random(512).astype(np.float32)
    ortogonale = casuale - np.dot(casuale, base) * base
    ortogonale = ortogonale / np.linalg.norm(ortogonale)
    vettore = similarita * base + np.sqrt(1 - similarita**2) * ortogonale
    return vettore.astype(np.float32)


def _crea_immagine_prova(percorso: Path, dimensione=(100, 100)) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", dimensione, color="blue").save(percorso)


@pytest.fixture
def db_di_prova(tmp_path):
    percorso_db = tmp_path / "volti_test.db"
    init_db(percorso_db)
    return percorso_db


def test_sanitizza_nome_sostituisce_spazi():
    assert _sanitizza_nome("Mario Rossi") == "Mario_Rossi"


def test_sanitizza_nome_rimuove_caratteri_non_validi():
    assert _sanitizza_nome("Mario/Rossi:Test") == "Mario_Rossi_Test"


def test_volto_con_match_certo(db_di_prova, tmp_path, monkeypatch):
    vettore = _vettore_normalizzato(seed=1)
    conn = connetti(db_di_prova)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(conn, id_mario, vettore, "mario_0.jpg", "batch_iniziale")
    conn.close()

    volto_finto = VoltoRilevato(vettore=vettore, bbox=(10, 10, 50, 50), score=0.9)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_finto])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto1.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto1_Mario_Rossi_100.jpg"
    assert riepilogo["certo"] == 1
    assert riepilogo["foto_totali"] == 1


def test_volto_con_match_ambiguo(db_di_prova, tmp_path, monkeypatch):
    base = _vettore_normalizzato(seed=2)
    vettore_query = _vettore_con_similarita(base, 0.38, seed=3)
    conn = connetti(db_di_prova)
    id_anna = trova_o_crea_persona(conn, "Anna Bianchi")
    salva_embedding(conn, id_anna, base, "anna_0.jpg", "batch_iniziale")
    conn.close()

    volto_finto = VoltoRilevato(vettore=vettore_query, bbox=(10, 10, 50, 50), score=0.9)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_finto])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto2.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto2_Anna_Bianchi_38_DA_VERIFICARE.jpg"
    assert riepilogo["ambiguo"] == 1


def test_volto_sconosciuto(db_di_prova, tmp_path, monkeypatch):
    base = _vettore_normalizzato(seed=4)
    vettore_query = _vettore_con_similarita(base, 0.10, seed=5)
    conn = connetti(db_di_prova)
    id_persona = trova_o_crea_persona(conn, "Qualcun Altro")
    salva_embedding(conn, id_persona, base, "altro_0.jpg", "batch_iniziale")
    conn.close()

    volto_finto = VoltoRilevato(vettore=vettore_query, bbox=(10, 10, 50, 50), score=0.9)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_finto])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto3.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto3_sconosciuto.jpg"
    assert riepilogo["sconosciuto"] == 1


def test_nessun_volto_rilevato(db_di_prova, tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto4.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto4_NESSUN_VOLTO.jpg"
    assert riepilogo["nessun_volto"] == 1


def test_due_volti_stessa_foto_segmenti_incatenati(db_di_prova, tmp_path, monkeypatch):
    v1 = _vettore_normalizzato(seed=6)
    v2 = _vettore_normalizzato(seed=7)
    conn = connetti(db_di_prova)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(conn, id_mario, v1, "mario_0.jpg", "batch_iniziale")
    id_anna = trova_o_crea_persona(conn, "Anna Bianchi")
    salva_embedding(conn, id_anna, v2, "anna_0.jpg", "batch_iniziale")
    conn.close()

    volto1 = VoltoRilevato(vettore=v1, bbox=(0, 0, 40, 40), score=0.9)
    volto2 = VoltoRilevato(vettore=v2, bbox=(50, 50, 90, 90), score=0.9)
    monkeypatch.setattr(
        "scripts.rinomina_batch.rileva_volti", lambda percorso: [volto1, volto2]
    )

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto5.jpg")

    rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto5_Mario_Rossi_100_Anna_Bianchi_100.jpg"


def test_struttura_sottocartelle_rispecchiata(db_di_prova, tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "evento1" / "foto6.jpg")

    rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    percorso_atteso = cartella_output / "evento1" / "foto6_NESSUN_VOLTO.jpg"
    assert percorso_atteso.exists()


def test_file_originale_non_toccato(db_di_prova, tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    percorso_originale = cartella_input / "foto7.jpg"
    _crea_immagine_prova(percorso_originale)

    rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    assert percorso_originale.exists()
    assert list(cartella_input.glob("*.jpg")) == [percorso_originale]


def test_immagine_illeggibile_non_blocca_le_altre(db_di_prova, tmp_path, monkeypatch):
    def _rileva_volti_finto(percorso):
        if "corrotta" in str(percorso):
            raise ValueError("immagine non leggibile")
        return []

    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", _rileva_volti_finto)

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "corrotta.jpg")
    _crea_immagine_prova(cartella_input / "normale.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    assert riepilogo["errore_lettura_immagine"] == 1
    assert riepilogo["foto_totali"] == 2
    assert (cartella_output / "normale_NESSUN_VOLTO.jpg").exists()
    assert not list(cartella_output.glob("corrotta*"))
```

- [ ] **Step 2: Eseguire i test, verificare che falliscano**

Run: `venv/bin/pytest tests/test_rinomina_batch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.rinomina_batch'`.

- [ ] **Step 3: Implementare `scripts/rinomina_batch.py`**

Crea `scripts/rinomina_batch.py`:

```python
"""Rinomina in batch foto non taggate in base al riconoscimento volti.

Uso:
    python scripts/rinomina_batch.py <cartella_input> <cartella_output>

Scansiona <cartella_input> (e sottocartelle) alla ricerca di JPG/PNG, rileva
i volti con InsightFace, li confronta col database "personaggi", e copia
ogni foto in <cartella_output> (stessa struttura di sottocartelle) col nome
del file originale seguito da un segmento per ogni volto trovato: nome e
punteggio se il match è certo o ambiguo, "sconosciuto" se nessun candidato
valido, "NESSUN_VOLTO" se non è stato rilevato alcun volto nella foto.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.matching import calcola_candidati, classifica_match
from core.volti import rileva_volti
from db.database import connetti

PERCORSO_DB_DEFAULT = Path(__file__).resolve().parent.parent / "db" / "volti.db"

ESTENSIONI = ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.png", "*.PNG")


def _sanitizza_nome(nome: str) -> str:
    """Sostituisce spazi con underscore e rimuove caratteri non validi in un nome file."""
    nome = nome.replace(" ", "_")
    for carattere in ("/", "\\", ":"):
        nome = nome.replace(carattere, "_")
    return nome


def _segmento_per_volto(volto, conn) -> tuple[str, str]:
    """Calcola il segmento di nome file per un singolo volto rilevato.

    Ritorna (segmento, categoria) dove categoria è 'certo', 'ambiguo' o 'sconosciuto'."""
    candidati = calcola_candidati(volto.vettore, conn)
    stato = classifica_match(candidati)
    if stato == "sconosciuto":
        return "sconosciuto", "sconosciuto"
    nome_sanificato = _sanitizza_nome(candidati[0].nome)
    punteggio = round(candidati[0].punteggio * 100)
    if stato == "ambiguo":
        return f"{nome_sanificato}_{punteggio}_DA_VERIFICARE", "ambiguo"
    return f"{nome_sanificato}_{punteggio}", "certo"


def rinomina_da_cartella(
    cartella_input: Path, cartella_output: Path, percorso_db: Path
) -> dict[str, int]:
    """Elabora tutte le foto JPG/PNG in cartella_input (ricorsivo) e ne copia una
    versione rinominata in cartella_output, rispecchiando la struttura di
    sottocartelle dell'input. Gli originali non vengono mai modificati.

    Ritorna un riepilogo: {'foto_totali': N, 'certo': N, 'ambiguo': N,
    'sconosciuto': N, 'nessun_volto': N, 'errore_lettura_immagine': N}.
    I conteggi certo/ambiguo/sconosciuto/nessun_volto sono per volto (una foto
    con più volti può contribuire a più categorie); foto_totali e
    errore_lettura_immagine sono per foto.
    """
    conn = connetti(percorso_db)
    riepilogo = {
        "foto_totali": 0,
        "certo": 0,
        "ambiguo": 0,
        "sconosciuto": 0,
        "nessun_volto": 0,
        "errore_lettura_immagine": 0,
    }

    foto_trovate = sorted(
        {percorso for pattern in ESTENSIONI for percorso in cartella_input.rglob(pattern)}
    )

    for foto in foto_trovate:
        riepilogo["foto_totali"] += 1
        try:
            volti = rileva_volti(foto)
        except ValueError as errore:
            riepilogo["errore_lettura_immagine"] += 1
            print(f"[errore_lettura_immagine] {foto.name}: {errore}")
            continue

        if not volti:
            riepilogo["nessun_volto"] += 1
            nuovo_nome = f"{foto.stem}_NESSUN_VOLTO{foto.suffix}"
        else:
            segmenti = []
            for volto in volti:
                segmento, categoria = _segmento_per_volto(volto, conn)
                segmenti.append(segmento)
                riepilogo[categoria] += 1
            nuovo_nome = f"{foto.stem}_{'_'.join(segmenti)}{foto.suffix}"

        percorso_relativo = foto.relative_to(cartella_input).parent
        cartella_output_foto = cartella_output / percorso_relativo
        cartella_output_foto.mkdir(parents=True, exist_ok=True)
        shutil.copy2(foto, cartella_output_foto / nuovo_nome)
        print(f"[{nuovo_nome}] <- {foto.name}")

    conn.close()
    return riepilogo


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: python scripts/rinomina_batch.py <cartella_input> <cartella_output>")
        return 1

    cartella_input = Path(sys.argv[1])
    cartella_output = Path(sys.argv[2])

    if not cartella_input.is_dir():
        print(f"Cartella non trovata: {cartella_input}")
        return 1

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, PERCORSO_DB_DEFAULT)

    print("\n--- Riepilogo rinomina ---")
    for chiave, valore in riepilogo.items():
        print(f"{chiave}: {valore}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Eseguire i test, verificare che passino**

Run: `venv/bin/pytest tests/test_rinomina_batch.py -v`
Expected: PASS, tutti i test.

- [ ] **Step 5: Eseguire l'intera suite per assicurarsi che nulla si sia rotto**

Run: `venv/bin/pytest tests/ -v`
Expected: PASS, tutti i test del progetto (esistenti + i nuovi).

- [ ] **Step 6: Commit**

```bash
git add scripts/rinomina_batch.py tests/test_rinomina_batch.py
git commit -m "Aggiunge script di rinomina batch foto tramite riconoscimento volti"
```

---

## Note per l'esecuzione

Task unico: lo script è abbastanza piccolo e coeso da non richiedere una scomposizione ulteriore. A completamento, eseguire `venv/bin/pytest tests/ -v` come verifica finale.
