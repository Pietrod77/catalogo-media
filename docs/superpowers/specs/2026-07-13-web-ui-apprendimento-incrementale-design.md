# Design: Web UI di revisione + apprendimento incrementale

Data: 2026-07-13

## Contesto e obiettivo

Design generale del progetto: `docs/superpowers/specs/2026-07-12-riconoscimento-volti-design.md`. Fasi 1-3 (setup, IPTC + popolamento batch, modulo di matching) sono complete: `db/volti.db` contiene 16 persone e 64 embedding, popolati da un batch iniziale su foto d'archivio taggate Getty. Il modulo `core/matching.py` (Fase 3) confronta un embedding contro il DB e classifica il risultato come `certo` (≥0.45), `ambiguo` (0.30-0.45) o `sconosciuto` (<0.30).

Questa fase costruisce l'interfaccia con cui Pietro usa concretamente lo strumento durante l'editing, e il meccanismo con cui il database cresce nel tempo. Le due cose coincidono: ogni conferma di un nome nella UI *è* l'atto di apprendimento incrementale (salva un nuovo embedding). Non ha senso costruire l'apprendimento incrementale come modulo isolato senza un'interfaccia che lo triggeri, quindi le fasi "apprendimento incrementale" e "web UI" del design originale vengono unite in un'unica fase.

**Flusso d'uso reale (chiarito in brainstorming, diverso dall'ipotesi iniziale del design originale):** Pietro non carica un'intera cartella/sessione di foto nella UI. Durante l'editing, quando incontra un volto che vuole identificare, fa uno screenshot del volto e lo trascina nella pagina web, uno alla volta. Non è quindi previsto un flusso "griglia di un'intera sessione" per questa fase — resta un'estensione futura possibile ma fuori scope qui.

**Il batch iniziale IPTC (Fase 2) resta il bootstrap del database, ma il meccanismo *principale* di crescita nel tempo è questo**: ogni volta che Pietro identifica un volto sconosciuto o corregge un match, il database si arricchisce senza bisogno di ri-lanciare un batch.

## Architettura

`app.py` (nuovo, root del progetto) avvia un server Flask locale (`localhost:5000`) e apre il browser automaticamente all'avvio (`python app.py`, coerente col README esistente). Una singola pagina HTML (`templates/index.html`) con una zona drag&drop, gestita da `static/app.js` (JS vanilla, nessun framework, nessun build step — coerente con la decisione già presa nel design originale). Due endpoint JSON principali più uno di supporto per le miniature:

- `POST /analizza` — riceve lo screenshot caricato, rileva i volti (`core/volti.py`, Fase 1, riuso diretto), per ciascun volto calcola i candidati (`core/matching.py`, Fase 3, riuso diretto). Ritorna JSON con la lista dei volti trovati (crop in base64 per l'anteprima, bounding box) e per ciascuno lo stato (`certo`/`ambiguo`/`sconosciuto`) con i relativi candidati.
- `POST /conferma` — riceve quale volto (se lo screenshot ne conteneva più di uno), il nome scelto (esistente o nuovo) e i dati dello screenshot. Salva lo screenshot su disco, crea/trova la persona (`db.database.trova_o_crea_persona`, già esistente da Fase 2), salva il nuovo embedding (`db.database.salva_embedding`, già esistente) con `fonte='conferma_editing'`.
- `GET /riferimento` — serve l'immagine di riferimento (`foto_riferimento` di un `Candidato`) per mostrare la miniatura nei casi ambigui, con validazione del path (vedi sezione sicurezza).

Nessun nuovo modulo di logica in `core/`: la logica di rilevamento volti e matching è già pronta e testata dalle fasi precedenti. Il lavoro di questa fase è tutto nell'orchestrazione HTTP (`app.py`) e nell'interfaccia (`templates/`, `static/`).

Scelta architetturale per la UI: **single-page con AJAX** (JS vanilla, `fetch` verso `/analizza` e `/conferma`, aggiornamento del DOM senza reload) invece di un'app Flask multi-pagina con redirect tra step. Motivazione: durante una sessione di editing Pietro processa molti screenshot in sequenza, uno alla volta — un reload di pagina ad ogni singolo screenshot rallenterebbe il flusso. Scartata anche l'opzione di introdurre htmx: il beneficio (meno JS scritto a mano) è marginale data la semplicità dell'interazione (drag&drop → 1-2 bottoni), e aggiungerebbe una dipendenza frontend non prevista nel design originale.

## Flusso dati

```
Browser (templates/index.html + static/app.js)
    │ drag&drop screenshot
    ▼
POST /analizza ──► core/volti.py: rileva_volti(img) ──► [0, 1, N volti]
    │                                                        │
    │                                          per ciascuno: core/matching.py
    │                                          calcola_candidati + classifica_match
    ▼
JSON: { volti: [ { crop_base64, bbox, stato, candidati: [{nome, punteggio, foto_riferimento}] } ] }
    │
    ▼
JS aggiorna il DOM:
  - 0 volti → messaggio errore, nessuna azione
  - >1 volto → mostra i crop dei volti trovati, Pietro clicca quale processare
              (poi si comporta come il caso "1 volto" sul volto scelto)
  - 1 volto, stato "certo" → nome proposto + bottone "Conferma"
              + link "non è lui, correggi" (apre lo stesso campo nome libero
              usato per ambiguo/sconosciuto)
  - 1 volto, stato "ambiguo" → 2-3 candidati cliccabili, ciascuno con
              miniatura (da GET /riferimento?path=<foto_riferimento>)
  - 1 volto, stato "sconosciuto" (o dopo "correggi") → campo testo con
              autocomplete sui nomi già presenti in DB (query semplice
              su persone.nome); se il testo scritto coincide con un
              suggerimento selezionato usa quel person_id, altrimenti
              alla conferma viene creata una persona nuova
    │
    ▼ Pietro conferma / sceglie un nome
POST /conferma { volto_scelto (bbox/indice), nome_scelto, screenshot }
    │
    ▼
app.py:
  1. salva lo screenshot in sessioni/conferme/<timestamp>_<hash>.jpg
  2. db.trova_o_crea_persona(nome_scelto) → person_id
  3. db.salva_embedding(person_id, vettore_del_volto_scelto,
     foto_origine=<path salvato>, fonte='conferma_editing')
    │
    ▼
JSON { ok: true } → JS resetta la UI, pronta per il prossimo screenshot
```

Il vettore dell'embedding (512 float32) calcolato in `/analizza` viene incluso nella risposta JSON per ciascun volto rilevato (es. lista di 512 numeri), tenuto lato client in memoria JS, e rispedito così com'è nel body di `/conferma` quando Pietro conferma quel volto. Nessuno stato server-side tra le due richieste (nessuna sessione, nessun file temporaneo): `/conferma` è autosufficiente, riceve tutto ciò che le serve nel payload. Vincolo: **l'embedding non viene mai ricalcolato una seconda volta** in `/conferma`, si riusa esattamente quello prodotto da `/analizza`.

## Sicurezza: path delle miniature di riferimento

`foto_riferimento` in `Candidato` (definito in Fase 3) è un path assoluto nel filesystem locale — può puntare a una foto d'archivio storica (Fase 2) o a uno screenshot salvato da questa fase. `GET /riferimento?path=...` è l'unico punto della UI che legge file potenzialmente fuori da `sessioni/`, quindi valida che il path richiesto sia contenuto in una lista di cartelle esplicitamente consentite (es. `sessioni/`, la cartella d'archivio nota usata in Fase 2) prima di servirlo; altrimenti ritorna 403. Nessun'altra route accetta path arbitrari da input utente.

## Gestione errori

- **0 volti rilevati**: `/analizza` ritorna `{ volti: [] }`, la UI mostra "nessun volto rilevato, ritaglia lo screenshot su un volto" — nessuna scrittura DB.
- **Formato immagine non valido / file corrotto**: `/analizza` cattura l'eccezione di decodifica, ritorna 400, la UI mostra "immagine non leggibile, riprova".
- **Nome vuoto in conferma**: `/conferma` valida server-side che il nome non sia una stringa vuota (oltre alla validazione HTML lato client) — altrimenti 400, evita di creare una persona senza nome.
- **Path traversal sulle miniature**: vedi sezione sicurezza sopra, 403 se il path non è in una cartella consentita.
- **Doppio click su "Conferma"**: non è un problema di correttezza del dato (crea solo un embedding aggiuntivo quasi identico per la stessa persona, coerente con la strategia "nessuna aggregazione a centroide" già decisa in Fase 3), ma la UI disabilita il bottone dopo il primo click per evitare submit accidentali ripetuti.
- **Server non raggiungibile / porta occupata**: fuori scope applicativo, comportamento standard di Flask all'avvio.

## Testing

- `core/volti.py` e `core/matching.py` restano invariati e già testati (Fase 1 e 3), riusati senza modifiche.
- Nuovi test in `tests/test_app.py` con `app.test_client()` di Flask, DB temporaneo (`tmp_path`, stesso pattern delle fasi precedenti), immagini sintetiche o reali già presenti nel repo di test:
  - `POST /analizza` con immagine senza volti → `volti: []`.
  - `POST /analizza` con immagine con un volto noto in DB → un volto, stato coerente con le soglie di Fase 3.
  - `POST /analizza` con immagine con più volti → lista con N volti.
  - `POST /conferma` con nome nuovo → crea persona + embedding, verificato leggendo il DB.
  - `POST /conferma` con nome esistente (via autocomplete) → riusa il `person_id` esistente, non duplica la persona.
  - `GET /riferimento` con path fuori dalle cartelle consentite → 403.
- Nessun test automatico del browser/JS: l'interazione client-side è minima (drag&drop, fetch, aggiornamento DOM) e viene verificata manualmente in un passaggio finale, come già fatto nelle fasi precedenti (es. verifica end-to-end di Fase 1).

## Struttura file (nuovi rispetto al design originale)

```
Volti_Riconoscimento/
├── app.py                         # NUOVO: avvio Flask, route /analizza /conferma /riferimento
├── templates/
│   └── index.html                 # NUOVO: pagina unica, zona drag&drop
├── static/
│   └── app.js                     # NUOVO: fetch verso gli endpoint, aggiornamento DOM
├── sessioni/
│   └── conferme/                  # NUOVO: screenshot confermati, esclusa da git (dentro sessioni/ già ignorata)
└── tests/
    └── test_app.py                # NUOVO: test degli endpoint Flask
```

Nessuna modifica agli schemi DB esistenti (Fase 1): `salva_embedding` e `trova_o_crea_persona` sono già generici rispetto alla `fonte`, non serve toccare `db/database.py`.

## Fuori scope per questa fase

- Griglia di revisione per un'intera sessione/cartella di foto (il flusso reale è uno screenshot alla volta).
- Autenticazione/protezione della web app: resta un tool locale a singolo utente, bind implicito su `localhost`.
- Editing/cancellazione di persone o embedding esistenti dalla UI (resta gestione diretta sul DB se mai necessaria).
- Aggregazione o pulizia degli embedding "quasi duplicati" da doppio click accidentale — non è un problema reale alla scala prevista (poche migliaia di embedding).
