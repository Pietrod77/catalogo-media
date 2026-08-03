# Design: hosting su NAS con sync incrementale per il fallback locale

Data: 2026-08-03

## Contesto e obiettivo

Oggi l'app (design generale in `docs/superpowers/specs/2026-07-12-riconoscimento-volti-design.md`, profili in `docs/superpowers/specs/2026-07-13-profili-modelle-personaggi-design.md`) gira solo in locale su ogni Mac, con `db/` e `sessioni/` sincronizzati via Dropbox. Regola d'oro attuale: mai due computer aperti insieme, perché SQLite via Dropbox non gestisce scritture concorrenti.

Pietro vuole spostare l'app su un server sempre acceso per uso multi-utente simultaneo (lui, Francesca, Claudio), con due vincoli espliciti:

1. **Nessuna spesa aggiuntiva** — si usa l'hardware già posseduto (NAS Ugreen DXP4800 Plus, Docker via UGOS Pro), non un VPS a pagamento.
2. **Mantenere comunque una versione locale funzionante** per tutti e tre gli utenti, per i momenti in cui il NAS non è raggiungibile — non un'architettura a singolo punto di guasto senza percorso di recupero.

**Raggiungibilità remota già verificata e risolta**: il NAS è raggiunto tramite Tailscale (rete privata gratuita, già installata e autenticata sia sul Mac di Pietro che sul NAS — dispositivi `macbook-pro-di-pietro` e `ugreen-nas` nella stessa tailnet). Questo evita sia i costi di un VPS con IP pubblico sia la complessità del port forwarding. Francesca e Claudio si uniranno tramite invito Tailscale (funzione "Share" sul singolo nodo NAS, non sull'intera tailnet di Pietro).

## Cosa NON cambia

- Nessuna modifica allo schema SQLite esistente salvo un'aggiunta (vedi sotto). Route Flask esistenti (`GET /`, `POST /analizza`, `POST /conferma`, `GET /riferimento`) restano invariate nel comportamento per l'uso online diretto.
- Nessuna autenticazione applicativa: l'accesso è protetto solo a livello di rete (solo dispositivi nella tailnet, o quelli a cui viene condiviso il nodo, raggiungono le porte). Da verificare una tantum che il router di casa non abbia già una regola di port-forwarding che esponga quelle porte anche su internet pubblico.
- Il flusso di setup locale esistente (git clone, venv, symlink Dropbox per i dati — vedi `docs/superpowers/specs/` e memoria di distribuzione) resta necessario per chi vuole anche il fallback locale. Non cambia per chi userà solo il browser puntato al NAS.

## Architettura

### Due modalità d'uso, stesso codice

- **Modo normale** (NAS raggiungibile): nessuna app locale in esecuzione. Si apre il browser su `http://<ip-tailscale-nas>:<porta>/`. Tutti vedono sempre gli stessi dati in tempo reale, perché è lo stesso identico processo Flask sul NAS a servire tutti.
- **Modo fallback** (NAS irraggiungibile): l'utente lancia l'app in locale come oggi (`.command` → venv → `app.py <profilo>`), che lavora su un DB locale — una copia "specchio" del catalogo del NAS più le eventuali conferme fatte offline non ancora inviate.

### Sul NAS (Docker Compose, sempre acceso)

Due servizi dalla stessa immagine (profili `modelle` porta 5001, `personaggi` porta 5002), stesso schema di oggi in `config.py`. `db/` e `sessioni/` montati come volumi persistenti sullo storage del NAS. Volume aggiuntivo per la cache dei modelli InsightFace (`buffalo_l`, ~300MB) così non si riscarica a ogni riavvio del container.

### In locale (fallback, solo quando serve)

Stesso `app.py`, con un worker in background aggiuntivo (thread avviato da `crea_app()`) che si attiva **solo** se l'app conosce l'indirizzo del NAS tramite una variabile d'ambiente (es. `VOLTI_NAS_URL`, impostata nei `.command` locali). Sul container che gira sul NAS questa variabile non è impostata, quindi lì il worker non parte mai — il NAS non deve sincronizzarsi con se stesso.

## Sync incrementale (non un dump completo del database)

Verificato in `db/database.py`: lo schema (`persone`, `embedding`, `log_scarti`) è **append-only** in tutta la codebase — solo `INSERT`, mai `UPDATE`/`DELETE`. Questo permette un sync incrementale basato su id crescenti, invece di riscaricare l'intero database a ogni ciclo.

### Schema — una colonna nuova, una tabella nuova

- `embedding.sincronizzato BOOLEAN NOT NULL DEFAULT 1` — le righe arrivate dal NAS (specchio) o create mentre si è online sono già sincronizzate per definizione; solo le conferme fatte offline partono con `sincronizzato = 0` finché non vengono inviate con successo. Fa anche da coda: non serve una tabella separata per "cosa devo ancora inviare", basta filtrare su questa colonna.
- `sync_stato` (nuova tabella, una riga sola, solo lato locale) — tiene il segnalino di quanto già scaricato dal NAS: `ultimo_persona_id_nas`, `ultimo_embedding_id_nas`.

### Nuovo endpoint sul NAS

`GET /sync/esporta?dopo_persona=<id>&dopo_embedding=<id>` — ritorna solo persone/embedding con `id` maggiore di quelli passati, paginato (es. 200 righe per chiamata, per non generare risposte enormi se qualcuno resta offline a lungo), incluso lo screenshot in base64 di ogni embedding nuovo (serve per mostrare le miniature nei candidati anche offline).

### Worker in background (solo lato locale)

Ogni 30-60 secondi:

1. **Controllo raggiungibilità**: chiamata leggera con timeout breve al NAS. Se non risponde, non fa nulla e riprova al ciclo successivo — mai un blocco dell'interfaccia utente.
2. **Push**: per ogni riga locale con `sincronizzato = 0`, la reinvia all'endpoint `/conferma` già esistente sul NAS (stessa logica di dedup persona-per-nome già in uso oggi tramite `trova_o_crea_persona`), poi la marca `sincronizzato = 1`. Ogni riga viene inviata con una chiamata HTTP indipendente: se una fallisce, le altre già inviate restano comunque marcate, non si perde lavoro già fatto.
3. **Pull**: chiama `/sync/esporta` sul NAS con i segnalini di `sync_stato`, inserisce persone/embedding nuovi deduplicando per nome (persone) e per nome-file dello screenshot — già un uuid univoco generato al momento della conferma, quindi resistente a doppio invio accidentale — (embedding), salva le miniature ricevute in `sessioni/`, avanza i segnalini al massimo id visto.

### Caso due persone offline creano lo stesso nome

Se Francesca e Claudio, offline su Mac diversi, confermano entrambi un volto come "Mario Rossi": quando sincronizzano (in qualsiasi ordine), il NAS li fa confluire nella stessa persona — `trova_o_crea_persona` deduplica già per nome (vincolo `UNIQUE` sulla colonna). Nessun conflitto, si sommano solo gli embedding.

### Indicatore minimo nell'interfaccia

Riuso della barra colore/profilo già esistente: se ci sono conferme locali non ancora sincronizzate, una riga tipo "N conferme in attesa di sync". Utile per fiducia/debug, non blocca nessun flusso.

## Struttura file (indicativa, dettagli nel piano di esecuzione)

```
Volti_Riconoscimento/
├── Dockerfile                      # NUOVO, immagine unica per i servizi NAS
├── docker-compose.yml              # NUOVO, servizi modelle/personaggi sul NAS
├── db/database.py                  # + colonna sincronizzato, + tabella sync_stato
├── app.py                          # + endpoint GET /sync/esporta
├── core/
│   └── sync.py                     # NUOVO, worker background: push + pull incrementale
└── config.py                       # + lettura VOLTI_NAS_URL dall'ambiente
```

## Testing

- Endpoint `/sync/esporta`: formato risposta e paginazione corretta (righe oltre i segnalini, non prima).
- Worker di push: con un NAS finto/mock, verifica che solo le righe `sincronizzato = 0` vengano inviate e marcate dopo l'invio riuscito; che un fallimento su una riga non blocchi le altre.
- Worker di pull: dedup per nome persona e per nome-file screenshot già esistenti non creano duplicati; i segnalini avanzano correttamente.
- Nessuna modifica ai test esistenti delle route — restano validi.

## Fuori scope

- Autenticazione applicativa (login/password nell'app) — l'isolamento di rete via Tailscale è considerato sufficiente per ora; da rivalutare se cambiano gli utenti o il livello di fiducia richiesto.
- Sync in tempo reale/push notification quando qualcun altro è online — il modo normale (browser diretto al NAS) già risolve la coerenza in tempo reale; il sync incrementale serve solo al fallback offline.
- Interfaccia per risolvere conflitti manualmente — nel modello dati attuale (append-only, dedup per nome) i conflitti si risolvono già da soli per costruzione, non serve un'interfaccia dedicata.
- Migrazione automatica dei dati storici già in Dropbox verso i volumi del NAS — è un'operazione una tantum da fare a mano quando si passa alla nuova architettura, non fa parte di questo design.
