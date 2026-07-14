# Filtro qualità sugli embedding salvati Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Impedire che volti rilevati con bassa confidenza (`det_score`) vengano salvati come nuovi embedding di riferimento tramite `POST /conferma`, senza toccare in alcun modo gli embedding già presenti nel database.

**Architecture:** Lo `score` già calcolato da InsightFace in `rileva_volti` viene esposto nella risposta di `/analizza`, propagato dal frontend (`static/app.js`) fino alla chiamata `/conferma`, e lì confrontato con una soglia minima costante prima di permettere il salvataggio.

**Tech Stack:** Flask (Python), pytest, JavaScript vanilla (nessun framework/test runner JS nel progetto).

## Global Constraints

- Soglia minima: `SOGLIA_QUALITA_MINIMA = 0.5`, definita in `core/volti.py`.
- Il filtro si applica solo ai nuovi salvataggi da questo momento in poi. Nessuna modifica al database esistente, nessuna colonna nuova, nessuna migrazione, nessun ricalcolo retroattivo.
- `/conferma` con `score` assente → 400 `{"errore": "dati mancanti"}` (stesso trattamento di `vettore`/`screenshot_base64` mancanti).
- `/conferma` con `score < SOGLIA_QUALITA_MINIMA` → 400 con messaggio `f"qualità troppo bassa (score {score:.2f}), usa uno screenshot più nitido o ravvicinato"`.
- `/analizza` (matching/candidati) resta invariato: il blocco riguarda solo l'azione di salvataggio, non l'analisi.
- Nessun controllo sulla dimensione in pixel del volto: si usa solo `det_score`.
- Nessuna soglia diversa per profilo (modelle/personaggi): un'unica costante condivisa.
- Nessuna opzione per l'utente di forzare comunque il salvataggio: il blocco è totale.

---

### Task 1: Esporre lo score nella risposta di `/analizza`

**Files:**
- Modify: `core/volti.py`
- Modify: `app.py` (route `/analizza`)
- Test: `tests/test_app.py`

**Interfaces:**
- Produces: costante `SOGLIA_QUALITA_MINIMA: float = 0.5` in `core/volti.py`, importabile con `from core.volti import SOGLIA_QUALITA_MINIMA`.
- Produces: la risposta JSON di `POST /analizza` include, per ogni volto, la chiave `"score": float` accanto a `"vettore"`, `"crop_base64"`, `"stato"`, `"candidati"`.

- [ ] **Step 1: Scrivi il test che deve fallire**

Apri `tests/test_app.py` e aggiungi questo test subito dopo `test_analizza_piu_volti` (circa riga 141-142, prima di `test_analizza_immagine_non_leggibile`):

```python
def test_analizza_include_score_nel_risultato(client, tmp_path, monkeypatch):
    vettore = _vettore_normalizzato(seed=20)
    volto_finto = VoltoRilevato(vettore=vettore, bbox=(10, 10, 50, 50), score=0.83)
    monkeypatch.setattr("app.rileva_volti", lambda percorso: [volto_finto])

    percorso_immagine = tmp_path / "screenshot.jpg"
    _crea_immagine_prova(percorso_immagine)

    with open(percorso_immagine, "rb") as f:
        risposta = client.post("/analizza", data={"immagine": (f, "screenshot.jpg")})

    dati = risposta.get_json()
    assert dati["volti"][0]["score"] == pytest.approx(0.83)
```

`VoltoRilevato` è già importato in cima al file (`from core.volti import VoltoRilevato`), non serve aggiungere nulla.

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `source venv/bin/activate && pytest tests/test_app.py::test_analizza_include_score_nel_risultato -v`
Expected: FAIL con `KeyError: 'score'`

- [ ] **Step 3: Aggiungi la costante in `core/volti.py`**

In `core/volti.py`, subito dopo la definizione della dataclass `VoltoRilevato` (dopo la riga `score: float`, prima di `def carica_modello`), aggiungi:

```python
@dataclass
class VoltoRilevato:
    vettore: np.ndarray  # embedding, shape (512,), dtype float32
    bbox: tuple[int, int, int, int]
    score: float


SOGLIA_QUALITA_MINIMA = 0.5


def carica_modello() -> FaceAnalysis:
```

- [ ] **Step 4: Esponi `score` nella risposta di `/analizza`**

In `app.py`, nel blocco `risultato_volti.append(...)` dentro la route `/analizza` (circa righe 99-113), aggiungi la chiave `"score"`:

```python
                risultato_volti.append(
                    {
                        "vettore": volto.vettore.tolist(),
                        "crop_base64": crop_base64,
                        "score": volto.score,
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
```

- [ ] **Step 5: Esegui il test e verifica che passi**

Run: `pytest tests/test_app.py::test_analizza_include_score_nel_risultato -v`
Expected: PASS

- [ ] **Step 6: Esegui l'intera suite per verificare nessuna regressione**

Run: `pytest -v`
Expected: tutti i test passano (nessuna modifica a `/conferma` in questo task, quindi nessun test esistente dovrebbe rompersi)

- [ ] **Step 7: Commit**

```bash
git add core/volti.py app.py tests/test_app.py
git commit -m "$(cat <<'EOF'
Espone lo score di rilevamento nella risposta di /analizza

Primo passo verso il filtro qualità sugli embedding salvati: il
det_score calcolato da InsightFace ora raggiunge il frontend.
EOF
)"
```

---

### Task 2: Validare lo score in `/conferma` e propagarlo da `app.js`

**Files:**
- Modify: `app.py` (route `/conferma`)
- Modify: `static/app.js` (funzione `confermaNome`)
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `SOGLIA_QUALITA_MINIMA` da `core.volti` (Task 1); campo `"score"` presente nell'oggetto `volto` ricevuto da `/analizza` (Task 1).
- Produces: `POST /conferma` richiede ora un campo `"score": float` nel body JSON, oltre a `nome`, `vettore`, `screenshot_base64`.

- [ ] **Step 1: Scrivi i test che devono fallire**

Apri `tests/test_app.py` e aggiungi questi test subito dopo `test_conferma_vettore_con_valori_non_finiti_ritorna_400` (circa riga 271-272, prima di `test_riferimento_serve_file_in_cartella_consentita`):

```python
def test_conferma_score_assente_ritorna_400(client):
    vettore = _vettore_normalizzato(seed=30).tolist()
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={
            "nome": "Persona Senza Score",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
        },
    )

    assert risposta.status_code == 400


def test_conferma_score_basso_ritorna_400(app, client):
    vettore = _vettore_normalizzato(seed=31).tolist()
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={
            "nome": "Persona Score Basso",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.3,
        },
    )

    assert risposta.status_code == 400
    conn = connetti(app.config["PERCORSO_DB"])
    riga = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Persona Score Basso",)
    ).fetchone()
    conn.close()
    assert riga is None


def test_conferma_score_sufficiente_salva_normalmente(app, client):
    vettore = _vettore_normalizzato(seed=32).tolist()
    screenshot_b64 = base64.b64encode(b"x").decode("ascii")

    risposta = client.post(
        "/conferma",
        json={
            "nome": "Persona Score Alto",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )

    assert risposta.status_code == 200
    conn = connetti(app.config["PERCORSO_DB"])
    riga = conn.execute(
        "SELECT id FROM persone WHERE nome = ?", ("Persona Score Alto",)
    ).fetchone()
    conn.close()
    assert riga is not None
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest tests/test_app.py::test_conferma_score_assente_ritorna_400 tests/test_app.py::test_conferma_score_basso_ritorna_400 tests/test_app.py::test_conferma_score_sufficiente_salva_normalmente -v`
Expected: `test_conferma_score_assente_ritorna_400` FAIL (oggi torna 200, non 400); `test_conferma_score_basso_ritorna_400` FAIL (oggi salva comunque); `test_conferma_score_sufficiente_salva_normalmente` PASS già oggi (va bene, lo teniamo come rete di sicurezza per il prossimo step)

- [ ] **Step 3: Aggiorna la route `/conferma` in `app.py`**

Sostituisci l'intero corpo della funzione `conferma()` (circa righe 120-147) con:

```python
    @app.post("/conferma")
    def conferma():
        dati = request.get_json(silent=True) or {}
        nome = (dati.get("nome") or "").strip()
        vettore_lista = dati.get("vettore")
        screenshot_base64 = dati.get("screenshot_base64")
        score = dati.get("score")

        if not nome:
            return jsonify(errore="nome mancante"), 400
        if not vettore_lista or not screenshot_base64 or score is None:
            return jsonify(errore="dati mancanti"), 400

        vettore = np.array(vettore_lista, dtype=np.float32)
        if vettore.shape != (512,) or not np.all(np.isfinite(vettore)):
            return jsonify(errore="vettore non valido"), 400

        if score < SOGLIA_QUALITA_MINIMA:
            return (
                jsonify(
                    errore=(
                        f"qualità troppo bassa (score {score:.2f}), "
                        "usa uno screenshot più nitido o ravvicinato"
                    )
                ),
                400,
            )

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

Aggiungi anche `SOGLIA_QUALITA_MINIMA` all'import da `core.volti` in cima al file:

```python
from core.volti import SOGLIA_QUALITA_MINIMA, rileva_volti
```

- [ ] **Step 4: Aggiorna i test esistenti che chiamano `/conferma` senza `score`**

Nello stesso file `tests/test_app.py`, aggiungi `"score": 0.9,` ai body JSON dei seguenti quattro test già esistenti (senza cambiare nient'altro):

1. `test_conferma_nome_nuovo_crea_persona_ed_embedding` (circa riga 167-174):
```python
    risposta = client.post(
        "/conferma",
        json={
            "nome": "Nuova Persona",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )
```

2. `test_conferma_nome_esistente_non_duplica_persona` (circa riga 202-209):
```python
    client.post(
        "/conferma",
        json={
            "nome": "Mario Rossi",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )
```

3. `test_conferma_vettore_lunghezza_sbagliata_ritorna_400` (circa riga 239-246), per continuare a testare specificamente la validazione del vettore (senza questo, il test passerebbe comunque ma per il motivo sbagliato, "dati mancanti" invece di "vettore non valido"):
```python
    risposta = client.post(
        "/conferma",
        json={
            "nome": "Persona Vettore Corto",
            "vettore": [0.1, 0.2, 0.3],
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )
```

4. `test_conferma_vettore_con_valori_non_finiti_ritorna_400` (circa riga 262-269), stesso motivo:
```python
    risposta = client.post(
        "/conferma",
        json={
            "nome": "Persona Vettore Nan",
            "vettore": vettore,
            "screenshot_base64": screenshot_b64,
            "score": 0.9,
        },
    )
```

Non serve modificare `test_conferma_nome_vuoto_ritorna_400`: il controllo su `nome` avviene prima del controllo su `score`, quindi quel test resta corretto così com'è.

- [ ] **Step 5: Esegui l'intera suite e verifica che tutto passi**

Run: `pytest -v`
Expected: tutti i test passano, incluso il nuovo terzetto del Task 2 e i quattro test aggiornati.

- [ ] **Step 6: Propaga lo score da `static/app.js`**

In `static/app.js`, nella funzione `confermaNome` (circa righe 188-196), aggiungi `score: volto.score,` al body JSON:

```javascript
function confermaNome(volto, nome) {
    fetch("/conferma", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            nome: nome,
            vettore: volto.vettore,
            screenshot_base64: screenshotBase64,
            score: volto.score,
        }),
    })
```

- [ ] **Step 7: Verifica manuale della modifica JS**

Il progetto non ha un test runner JavaScript: la correttezza del contratto è già garantita dai test Python del Task 2 (che validano cosa deve ricevere `/conferma`), qui verifichiamo solo che la riga sia stata scritta correttamente:

Run: `grep -n "score: volto.score" static/app.js`
Expected: una riga di output che mostra `score: volto.score,` dentro `confermaNome`

- [ ] **Step 8: Commit**

```bash
git add app.py static/app.js tests/test_app.py
git commit -m "$(cat <<'EOF'
Blocca il salvataggio di embedding con score sotto 0.5

/conferma rifiuta ora i volti a bassa confidenza di rilevamento
(qualità dell'immagine insufficiente) prima che diventino embedding
di riferimento. Il filtro riguarda solo i nuovi salvataggi: nessun
embedding già presente nel database viene toccato.
EOF
)"
```

---

## Verifica finale end-to-end (manuale, dopo il Task 2)

Dopo l'implementazione, riavvia il server (`python app.py modelle` o `python app.py personaggi`, ricordando che il dev server Flask non fa hot-reload) e trascina uno screenshot con un volto ben visibile: il salvataggio deve funzionare come prima. Non esiste un modo semplice per forzare uno score basso dalla UI reale (dipenderebbe da uno screenshot davvero degradato), quindi la garanzia principale sul comportamento di blocco resta la suite di test automatici del Task 2.
