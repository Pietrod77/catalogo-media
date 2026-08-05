# Riepilogo breve e filtro nitidezza per rinomina_batch.py Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `scripts/rinomina_batch.py` scarta i volti sotto la soglia di qualità già usata dall'app web, e stampa su stdout (quindi nel dialog del droplet) solo un riepilogo breve invece del log completo per-foto.

**Architecture:** Due modifiche isolate all'interno della stessa funzione `rinomina_da_cartella` e di `main()` in `scripts/rinomina_batch.py`: (1) un filtro sui volti rilevati basato su `VoltoRilevato.score`, con un nuovo contatore diagnostico; (2) una nuova funzione pura `_formatta_riepilogo_breve` che sostituisce la stampa grezza del dizionario di riepilogo, più lo spostamento di tutte le stampe per-foto/per-errore da stdout a stderr (il droplet AppleScript cattura solo stdout).

**Tech Stack:** Python 3, pytest, nessuna nuova dipendenza.

## Global Constraints

- Nessuna modifica a `core/volti.py`, `core/matching.py`, `db/database.py`, `app.py` o al droplet `Rinomina Volti.app`.
- La soglia di qualità è `SOGLIA_QUALITA_MINIMA` importata da `core.volti` (valore attuale 0.5, stesso significato già in uso in `app.py`) — non ridefinita, non parametrizzabile da riga di comando.
- Una foto con tutti i volti scartati dal filtro è trattata esattamente come il caso esistente "nessun volto rilevato" (marcatore `_NESSUN_VOLTO`, contatore `nessun_volto`) — nessun marcatore distinto.
- Il riepilogo finale su stdout ha il formato: `N foto — N nomi trovati (N certi, N da verificare), N sconosciuti, N senza volto a fuoco`, con una riga aggiuntiva `N errori (dettagli in terminale)` solo se la somma degli errori è > 0.

---

### Task 1: Filtro volti sotto soglia di qualità

**Files:**
- Modify: `scripts/rinomina_batch.py:20-22` (import), `scripts/rinomina_batch.py:95-104` (dizionario riepilogo), `scripts/rinomina_batch.py:125-141` (blocco di classificazione dei volti dentro `rinomina_da_cartella`)
- Test: `tests/test_rinomina_batch.py`

**Interfaces:**
- Consumes: `SOGLIA_QUALITA_MINIMA: float` da `core.volti` (già esiste, stesso import pattern di `app.py:27`); `VoltoRilevato.score: float` (già esiste).
- Produces: `rinomina_da_cartella(...)` ritorna il dizionario di riepilogo con una nuova chiave `"scartati_bassa_qualita": int` (conteggio per volto, non per foto). Nessun'altra funzione pubblica cambia firma.

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi in `tests/test_rinomina_batch.py`, dopo `test_nessun_volto_rilevato` (circa riga 133):

```python
def test_volto_sotto_soglia_qualita_trattato_come_nessun_volto(db_di_prova, tmp_path, monkeypatch):
    vettore = _vettore_normalizzato(seed=50)
    conn = connetti(db_di_prova)
    id_persona = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(conn, id_persona, vettore, "mario_0.jpg", "batch_iniziale")
    conn.close()

    volto_sfocato = VoltoRilevato(vettore=vettore, bbox=(10, 10, 50, 50), score=0.2)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_sfocato])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto_sfocata.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto_sfocata_NESSUN_VOLTO.jpg"
    assert riepilogo["nessun_volto"] == 1
    assert riepilogo["certo"] == 0
    assert riepilogo["scartati_bassa_qualita"] == 1


def test_volto_valido_e_volto_scartato_stessa_foto(db_di_prova, tmp_path, monkeypatch):
    v1 = _vettore_normalizzato(seed=60)
    v2 = _vettore_normalizzato(seed=61)
    conn = connetti(db_di_prova)
    id_mario = trova_o_crea_persona(conn, "Mario Rossi")
    salva_embedding(conn, id_mario, v1, "mario_0.jpg", "batch_iniziale")
    id_anna = trova_o_crea_persona(conn, "Anna Bianchi")
    salva_embedding(conn, id_anna, v2, "anna_0.jpg", "batch_iniziale")
    conn.close()

    volto_valido = VoltoRilevato(vettore=v1, bbox=(0, 0, 40, 40), score=0.9)
    volto_scartato = VoltoRilevato(vettore=v2, bbox=(50, 50, 90, 90), score=0.3)
    monkeypatch.setattr(
        "scripts.rinomina_batch.rileva_volti", lambda percorso: [volto_valido, volto_scartato]
    )

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto_mista.jpg")

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    file_output = list(cartella_output.glob("*.jpg"))
    assert len(file_output) == 1
    assert file_output[0].name == "foto_mista_Mario_Rossi_100.jpg"
    assert riepilogo["certo"] == 1
    assert riepilogo["scartati_bassa_qualita"] == 1
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `venv/bin/pytest tests/test_rinomina_batch.py::test_volto_sotto_soglia_qualita_trattato_come_nessun_volto tests/test_rinomina_batch.py::test_volto_valido_e_volto_scartato_stessa_foto -v`
Expected: FAIL — `KeyError: 'scartati_bassa_qualita'` (la chiave non esiste ancora nel dizionario ritornato), oppure il primo assert su `file_output[0].name` fallisce perché oggi il volto sfocato viene comunque classificato normalmente (nessun filtro).

- [ ] **Step 3: Implementa il filtro**

In `scripts/rinomina_batch.py`, cambia la riga di import (riga 21):

```python
from core.volti import SOGLIA_QUALITA_MINIMA, rileva_volti
```

Nel dizionario di riepilogo dentro `rinomina_da_cartella` (righe 95-104), aggiungi la nuova chiave subito dopo `"nessun_volto": 0,`:

```python
    riepilogo = {
        "foto_totali": 0,
        "certo": 0,
        "ambiguo": 0,
        "sconosciuto": 0,
        "nessun_volto": 0,
        "scartati_bassa_qualita": 0,
        "errore_lettura_immagine": 0,
        "errore_riconoscimento": 0,
        "errore_copia": 0,
    }
```

Sostituisci il blocco di classificazione (righe 125-141, dentro il `for foto in foto_trovate:`) con:

```python
            volti_validi = []
            for volto in volti:
                if volto.score < SOGLIA_QUALITA_MINIMA:
                    riepilogo["scartati_bassa_qualita"] += 1
                    print(
                        f"[scartato_bassa_qualita] {foto.name}: "
                        f"score {volto.score:.2f} sotto soglia {SOGLIA_QUALITA_MINIMA:.2f}",
                        file=sys.stderr,
                    )
                    continue
                volti_validi.append(volto)

            if not volti_validi:
                riepilogo["nessun_volto"] += 1
                nuovo_nome = f"{foto.stem}_NESSUN_VOLTO{foto.suffix}"
            else:
                try:
                    segmenti = []
                    for volto in volti_validi:
                        segmento, categoria = _segmento_per_volto(volto, conn)
                        segmenti.append(segmento)
                        riepilogo[categoria] += 1
                    nuovo_nome = f"{foto.stem}_{'_'.join(segmenti)}{foto.suffix}"
                    if len(nuovo_nome.encode("utf-8")) > LIMITE_BYTE_NOME_FILE:
                        nuovo_nome = _tronca_nome_file(foto.stem, segmenti, foto.suffix)
                except Exception as errore:
                    riepilogo["errore_riconoscimento"] += 1
                    print(f"[errore_riconoscimento] {foto.name}: {errore}")
                    continue
```

Nota: la riga `print(f"[errore_riconoscimento] {foto.name}: {errore}")` resta invariata (stdout) in questo task — verrà spostata su stderr nel Task 2, insieme alle altre stampe per-foto.

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `venv/bin/pytest tests/test_rinomina_batch.py -v`
Expected: PASS — tutti i test, inclusi i due nuovi e l'intera suite esistente (nessuna regressione: i volti con `score >= 0.5`, valore già usato in tutti i test esistenti che impostano `score=0.9`, non vengono filtrati).

- [ ] **Step 5: Commit**

```bash
git add scripts/rinomina_batch.py tests/test_rinomina_batch.py
git commit -m "Filtra i volti sotto soglia di qualità in rinomina_batch"
```

---

### Task 2: Riepilogo breve e routing stdout/stderr

**Files:**
- Modify: `scripts/rinomina_batch.py` (nuova funzione `_formatta_riepilogo_breve`, chiamata in `main()`, routing delle stampe per-foto/per-errore su stderr)
- Test: `tests/test_rinomina_batch.py`

**Interfaces:**
- Consumes: il dizionario di riepilogo con la chiave `"scartati_bassa_qualita"` prodotta dal Task 1 (non usata nella formattazione breve, ma presente nel dict).
- Produces: `_formatta_riepilogo_breve(riepilogo: dict[str, int]) -> str`, funzione pura senza side-effect, importabile da `scripts.rinomina_batch`.

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi in `tests/test_rinomina_batch.py`, in cima al file cambia l'import (riga 11) per includere la nuova funzione:

```python
from scripts.rinomina_batch import _formatta_riepilogo_breve, _sanitizza_nome, main, rinomina_da_cartella
```

Poi aggiungi questi test (in fondo al file):

```python
def test_formatta_riepilogo_breve_conteggi_base():
    riepilogo = {
        "foto_totali": 150,
        "certo": 78,
        "ambiguo": 14,
        "sconosciuto": 40,
        "nessun_volto": 18,
        "scartati_bassa_qualita": 5,
        "errore_lettura_immagine": 0,
        "errore_riconoscimento": 0,
        "errore_copia": 0,
    }
    testo = _formatta_riepilogo_breve(riepilogo)
    assert "150 foto" in testo
    assert "92 nomi trovati (78 certi, 14 da verificare)" in testo
    assert "40 sconosciuti" in testo
    assert "18 senza volto a fuoco" in testo
    assert "errori" not in testo


def test_formatta_riepilogo_breve_include_riga_errori_se_presenti():
    riepilogo = {
        "foto_totali": 10,
        "certo": 5,
        "ambiguo": 0,
        "sconosciuto": 3,
        "nessun_volto": 1,
        "scartati_bassa_qualita": 0,
        "errore_lettura_immagine": 1,
        "errore_riconoscimento": 0,
        "errore_copia": 0,
    }
    testo = _formatta_riepilogo_breve(riepilogo)
    assert "1 errori (dettagli in terminale)" in testo


def test_output_per_foto_va_su_stderr_non_stdout(db_di_prova, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])
    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto_x.jpg")

    rinomina_da_cartella(cartella_input, cartella_output, db_di_prova)

    catturato = capsys.readouterr()
    assert catturato.out == ""
    assert "foto_x_NESSUN_VOLTO.jpg" in catturato.err


def test_main_stampa_solo_riepilogo_breve_su_stdout(db_di_prova, tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rinomina_batch.PERCORSO_DB_DEFAULT", db_di_prova)
    monkeypatch.setattr("scripts.rinomina_batch.rileva_volti", lambda percorso: [])

    cartella_input = tmp_path / "input"
    cartella_output = tmp_path / "output"
    _crea_immagine_prova(cartella_input / "foto_y.jpg")

    monkeypatch.setattr(
        sys, "argv", ["rinomina_batch.py", str(cartella_input), str(cartella_output)]
    )

    import io
    import contextlib

    buffer_out = io.StringIO()
    with contextlib.redirect_stdout(buffer_out):
        codice_uscita = main()

    assert codice_uscita == 0
    testo_stdout = buffer_out.getvalue()
    assert "1 foto" in testo_stdout
    assert "senza volto a fuoco" in testo_stdout
    assert "foto_y_NESSUN_VOLTO.jpg" not in testo_stdout
```

Nota: il `db_di_prova` in `test_main_stampa_solo_riepilogo_breve_su_stdout` ha 0 embedding, quindi `main()` stampa anche l'avviso "Attenzione: il database..." su stdout prima del riepilogo — gli assert sopra verificano solo che il riepilogo breve sia presente, non l'esclusività del contenuto di stdout.

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `venv/bin/pytest tests/test_rinomina_batch.py -v -k "formatta_riepilogo or output_per_foto_va_su_stderr or main_stampa_solo_riepilogo"`
Expected: FAIL — `ImportError` su `_formatta_riepilogo_breve` (non esiste ancora), oppure `AssertionError` sul contenuto di stdout/stderr (oggi tutto va su stdout).

- [ ] **Step 3: Implementa la funzione di formattazione e sposta le stampe su stderr**

In `scripts/rinomina_batch.py`, aggiungi questa funzione subito dopo `_tronca_nome_file` (dopo la riga che oggi è `return "_".join(pezzi) + suffisso`, prima di `def rinomina_da_cartella`):

```python
def _formatta_riepilogo_breve(riepilogo: dict[str, int]) -> str:
    """Costruisce la riga di riepilogo breve mostrata nel dialog del droplet
    (che cattura solo stdout) invece del dump completo del dizionario."""
    nomi_trovati = riepilogo["certo"] + riepilogo["ambiguo"]
    righe = [
        f"{riepilogo['foto_totali']} foto",
        f"{nomi_trovati} nomi trovati ({riepilogo['certo']} certi, {riepilogo['ambiguo']} da verificare)",
        f"{riepilogo['sconosciuto']} sconosciuti",
        f"{riepilogo['nessun_volto']} senza volto a fuoco",
    ]
    testo = " — ".join(righe)

    errori_totali = (
        riepilogo["errore_lettura_immagine"]
        + riepilogo["errore_riconoscimento"]
        + riepilogo["errore_copia"]
    )
    if errori_totali > 0:
        testo += f"\n{errori_totali} errori (dettagli in terminale)"
    return testo
```

Poi, nella stessa funzione `rinomina_da_cartella`, sposta su stderr le tre stampe per-foto rimaste su stdout (cerca ciascuna stringa esatta nel file e aggiungi `, file=sys.stderr` alla chiamata `print`):

1. `print(f"[errore_lettura_immagine] {foto.name}: {errore}")` (compare due volte, nei due blocchi `except ValueError` ed `except Exception` dopo la chiamata a `rileva_volti`) → entrambe diventano `print(f"[errore_lettura_immagine] {foto.name}: {errore}", file=sys.stderr)`
2. `print(f"[errore_riconoscimento] {foto.name}: {errore}")` (introdotta invariata nel Task 1) → `print(f"[errore_riconoscimento] {foto.name}: {errore}", file=sys.stderr)`
3. `print(f"[{nuovo_nome}] <- {foto.name}")` (stampa di successo dopo `shutil.copy2`) → `print(f"[{nuovo_nome}] <- {foto.name}", file=sys.stderr)`
4. `print(f"[errore_copia] {foto.name}: {errore}")` → `print(f"[errore_copia] {foto.name}: {errore}", file=sys.stderr)`

Infine, in `main()`, sostituisci il blocco:

```python
    print("\n--- Riepilogo rinomina ---")
    for chiave, valore in riepilogo.items():
        print(f"{chiave}: {valore}")
```

con:

```python
    print(_formatta_riepilogo_breve(riepilogo))
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `venv/bin/pytest tests/test_rinomina_batch.py -v`
Expected: PASS — tutta la suite, inclusi i quattro nuovi test. In particolare `test_main_avvisa_se_db_vuoto_ma_procede` deve continuare a passare (l'avviso "Attenzione" resta su stdout, invariato).

- [ ] **Step 5: Commit**

```bash
git add scripts/rinomina_batch.py tests/test_rinomina_batch.py
git commit -m "Sostituisce il log per-foto con un riepilogo breve su stdout"
```

---

## Note finali (nessuna azione richiesta)

Il comando lanciato da `Rinomina Volti.app` (`venv/bin/python scripts/rinomina_batch.py <input> <output>`) non cambia: l'AppleScript cattura di default solo stdout del comando, quindi dopo questo piano il dialog mostrerà automaticamente solo la riga di riepilogo breve, senza bisogno di toccare il droplet stesso.
