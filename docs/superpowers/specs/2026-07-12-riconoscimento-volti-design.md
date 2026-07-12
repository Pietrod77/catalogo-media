# Design: Database locale volti↔nomi per identificazione soggetti fotografici

Data: 2026-07-12

## Contesto e obiettivo

Pietro è un fotografo professionista di moda ed eventi (fashion week, front row, backstage) che fotografa spesso le stesse persone ricorrenti senza sempre ricordarne il nome. L'obiettivo è un tool locale che, in fase di editing/nomina finale delle foto, suggerisca il nome della persona riconosciuta nel volto, basandosi su un database costruito da un archivio storico di foto già etichettate (nome nel campo IPTC).

Uso esclusivamente locale, nessun dato biometrico condiviso con servizi cloud esterni.

Scala prevista: da poche decine a 100-500 persone nel database, poche migliaia di embedding totali.

## Ambiente verificato

- macOS Tahoe 26.5.1, Apple Silicon (arm64)
- Xcode Command Line Tools presenti
- `exiftool` già installato (Homebrew)
- Python 3.13 disponibile via Homebrew (da usare in virtualenv dedicato; il Python 3.9 di sistema va evitato)
- `cmake` NON installato — rilevante per la scelta della libreria di face recognition (vedi sotto)

## Decisioni tecniche

### Libreria di riconoscimento facciale: InsightFace

Scelta **InsightFace** (rilevamento RetinaFace + embedding ArcFace, modello `buffalo_l`) invece di `face_recognition`/dlib.

Motivazione:
- **Installazione**: `face_recognition` richiede la compilazione di dlib da sorgente (serve cmake, non presente; build lenta 10-20 min, talvolta fragile con Xcode CLT recenti). InsightFace usa `onnxruntime`, con wheel precompilati per arm64 — installazione pulita.
- **Accuratezza**: ArcFace è più robusto di dlib su angolazioni difficili (profili, occhiali da sole, foto backstage non frontali), scenario tipico dell'archivio di Pietro.
- **Velocità**: onnxruntime più veloce di dlib CPU-only, con possibilità di sfruttare CoreML come execution provider su Apple Silicon.
- **Manutenzione**: InsightFace è attivamente mantenuto, dlib/face_recognition sostanzialmente fermo.

Contro accettato: modello da scaricare al primo avvio (~300MB), one-time, poi tutto locale.

### Lettura metadati IPTC: exiftool via subprocess

Già installato sul Mac di Pietro, standard più affidabile di `iptcinfo3` (poco mantenuto, gestisce peggio i casi limite).

**Campo confermato su campione reale (113 foto in `~/Desktop/_prova export per nomi/`, Milano/Parigi Fashion Week giugno-luglio 2026, credit Getty Images):** il nome pulito della persona è nel campo `XMP-getty:Personality` (namespace custom di Getty Images), non nei campi IPTC standard ipotizzati inizialmente (`Object Name`, `Caption-Abstract`). `Caption-Abstract` contiene solo la frase descrittiva completa (utile eventualmente come fallback/cross-check, non come fonte primaria).

Pattern osservato sul campione:
- 111/113 foto con `Personality` valorizzato.
- 2/113 con `Personality` vuoto → foto di un "guest" non identificato, da scartare (`iptc_mancante`).
- 20/113 (~18%) con più nomi separati da virgola nello stesso campo (es. `"Joseph Annunziata, Victoria Stella Doritou"`) per foto con più soggetti taggati.

Il caso "più nomi in Personality + più volti rilevati nella foto" non ha un abbinamento nome↔volto esplicito nell'IPTC: si applica comunque la regola conservativa già definita (skip se >1 volto rilevato, log in `log_scarti` con motivo `volti_multipli` per revisione manuale), sapendo ora che riguarda una quota non trascurabile delle foto (~18% nel campione). Possibile miglioramento futuro (non nello scope della Fase 2/3): un abbinamento assistito volto↔nome in fase di revisione manuale invece dello skip totale.

### Database: SQLite, nessun FAISS

Alla scala prevista (100-500 persone, poche migliaia di embedding a 512 dimensioni) un confronto diretto per similarità coseno via numpy è già nell'ordine dei millisecondi. FAISS sarebbe over-engineering ora; resta un'estensione futura se il DB crescesse a decine di migliaia di embedding, senza richiedere modifiche al resto dell'architettura.

Schema:

```sql
CREATE TABLE persone (
    id INTEGER PRIMARY KEY,
    nome TEXT UNIQUE NOT NULL,
    note TEXT,
    creato_il TIMESTAMP
);

CREATE TABLE embedding (
    id INTEGER PRIMARY KEY,
    person_id INTEGER REFERENCES persone(id),
    vettore BLOB,            -- embedding 512-dim, numpy float32 serializzato
    foto_origine TEXT,       -- path del file da cui è stato estratto
    fonte TEXT,               -- 'batch_iniziale' | 'conferma_editing' | 'manuale'
    creato_il TIMESTAMP
);

CREATE TABLE log_scarti (
    id INTEGER PRIMARY KEY,
    foto TEXT,
    motivo TEXT,              -- 'nessun_volto' | 'volti_multipli' | 'iptc_mancante' | 'iptc_non_parsabile'
    creato_il TIMESTAMP
);
```

### Strategia embedding multipli per persona: nessuna aggregazione a centroide

Ogni embedding viene salvato singolarmente, legato a un `person_id`, invece di essere fuso in un centroide medio per persona.

Motivazione: se una persona ha foto molto diverse tra loro (scatto professionale frontale ben illuminato vs foto backstage sfocata di profilo), la media dei vettori può cadere in una "terra di mezzo" che non assomiglia bene a nessuna delle due condizioni, peggiorando il matching. Alla scala prevista, confrontare un volto nuovo contro tutti gli embedding esistenti in DB è comunque questione di millisecondi con numpy vettorizzato — non serve ottimizzare aggregando.

### Soglie di matching, calibrate sui dati reali

Con il DB popolato dalla Fase 2 (64 embedding, 16 persone, alcune con più foto), è stata calcolata empiricamente la distribuzione delle similarità coseno (dot product, essendo gli embedding di InsightFace già normalizzati L2):

- Similarità intra-persona (stessa persona, foto diverse): min 0.470, media 0.825, max 0.967 (146 coppie).
- Similarità inter-persona (persone diverse): min -0.165, media 0.013, max 0.238 (1870 coppie).

Nessuna sovrapposizione tra le due distribuzioni in questo campione: separazione netta tra 0.238 (massimo inter-persona) e 0.470 (minimo intra-persona). Soglie scelte con margine:

- **Soglia alta (match certo): 0.45** — sopra questo valore, oltre il massimo osservato tra persone diverse con ampio margine.
- **Soglia bassa (sconosciuto sotto questa soglia): 0.30** — margine di sicurezza sotto la soglia alta per la fascia "ambiguo".
- Tra 0.30 e 0.45: match ambiguo, da mostrare come candidato ma non confermare automaticamente.

Queste soglie andranno ricalibrate quando il DB crescerà (più persone → più probabilità di falsi positivi vicino alla soglia), ma sono un punto di partenza solido basato su dati reali invece che su valori di letteratura generici.

In fase di matching: calcolo la similarità coseno del volto nuovo contro tutti gli embedding in DB, poi aggrego per persona prendendo **la media dei migliori 3 match** per quella persona (non il singolo migliore, per evitare falsi positivi isolati da un embedding anomalo). Se una persona ha meno di 3 embedding, si usa la media di quelli disponibili.

Conseguenza positiva: ogni conferma nella web UI aggiunge un nuovo embedding "sul campo" (luce, angolo, evento reali) per quella persona, migliorando naturalmente il matching nel tempo — è il meccanismo di apprendimento incrementale.

### Interfaccia: web app locale Flask, non CLI

Motivazione: la revisione di una sessione di editing richiede vedere una griglia di foto reali con nome proposto sotto ciascuna, editabile e confermabile in batch — non ottenibile in modo pratico da un terminale. Flask + template HTML/JS vanilla (niente framework frontend, niente build step) è il minimo indispensabile: un comando (`python app.py`) apre il browser sulla griglia della sessione corrente. Priorità a "meno manutenzione" più che a eleganza dell'interfaccia, come richiesto.

Per i casi ambigui (2-3 nomi candidati vicini alla soglia), l'interfaccia mostra **la miniatura del volto di riferimento in DB accanto a ciascun nome candidato**, non solo testo — il confronto visivo è più veloce e affidabile per un fotografo che leggere un punteggio numerico.

## Flusso utente end-to-end

1. Pietro carica una foto o un'intera cartella di sessione di editing nella web UI (o via script batch).
2. Per ogni volto rilevato nella/e foto:
   - Match con alta confidenza sopra soglia → nome proposto con punteggio, un click per confermare.
   - Match ambiguo (più nomi vicini alla soglia) → 2-3 nomi candidati, ciascuno con miniatura del volto di riferimento in DB, Pietro clicca quello giusto.
   - Nessun match sopra soglia → "sconosciuto", campo di testo libero per inserire il nome.
3. Ogni conferma/correzione/nuovo nome salva immediatamente il nuovo embedding nel DB legato al `person_id` corretto (apprendimento incrementale, nessun batch da rilanciare).
4. Bottone "Conferma tutto" per applicare in blocco le scelte fatte sull'intera griglia della sessione.

## Uso da più computer

Requisito emerso: Pietro potrebbe dover usare lo strumento da computer diversi in futuro (non ancora certo se tutti Mac o anche altri sistemi). Lo stack scelto (Python, onnxruntime/InsightFace, Flask, SQLite, exiftool) è già cross-platform, quindi non serve cambiare le decisioni tecniche — bastano alcune accortezze:

**Cosa deve sincronizzarsi tra i computer (via Dropbox, dato che il progetto vive già in `~/Dropbox/Volti_Riconoscimento/`):**
- Il codice (già gestito da git, e comunque dentro Dropbox).
- `db/volti.db` — è il dato di valore (embedding + nomi), deve essere lo stesso su tutti i computer.

**Cosa NON deve sincronizzarsi:**
- `venv/` — un virtualenv compilato è specifico di macchina/architettura; va ricreato localmente su ogni computer da `requirements.txt`, non sincronizzato. Su Mac si esclude dalla sync di Dropbox con un comando one-time: `xattr -w com.dropbox.ignored 1 venv` (va rilanciato su ogni singolo computer, è un'impostazione locale).
- La cache del modello InsightFace (scaricata di default fuori dal progetto, in `~/.insightface`) — resta naturalmente locale a ogni macchina, nessuna azione necessaria.

**Regola d'oro per evitare corruzione del DB condiviso via Dropbox:** non tenere l'app aperta su due computer contemporaneamente. SQLite non è pensato per essere scritto da due processi su file sincronizzati via cloud in parallelo — si rischiano conflitti o "file in conflitto" generati da Dropbox. In pratica: chiudere l'app prima di passare a un altro computer, e aspettare che Dropbox abbia finito di sincronizzare (icona di stato) prima di riaprirla altrove. Per lo stesso motivo, il DB va tenuto in modalità journal SQLite di default (non WAL): la modalità WAL crea file `.db-wal`/`.db-shm` separati dal `.db` principale, che se sincronizzati in momenti diversi da Dropbox possono lasciare una copia inconsistente sull'altro computer.

**Setup su un nuovo computer:** aprire la cartella già sincronizzata da Dropbox, creare un virtualenv locale (`python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`), verificare che `exiftool` sia installato localmente (via Homebrew su Mac, o l'equivalente sul sistema in uso), poi lanciare `app.py` — il DB è già lì, sincronizzato.

## Struttura del progetto

Percorso: `~/Dropbox/Volti_Riconoscimento/`

```
Volti_Riconoscimento/
├── venv/                          # virtualenv Python 3.13, escluso da git
├── app.py                         # avvio web UI per revisione batch
├── requirements.txt
├── config.py                      # soglie di confidenza, path DB, ecc.
├── db/
│   ├── database.py                # inizializzazione schema, connessione SQLite
│   └── volti.db                   # il database (embedding + nomi), escluso da git
├── core/
│   ├── iptc.py                    # lettura nome da IPTC via exiftool
│   ├── volti.py                   # rilevamento volto + calcolo embedding (InsightFace)
│   └── matching.py                # confronto embedding, soglie, aggregazione top-3
├── scripts/
│   ├── popola_batch.py            # Fase 3: popolamento iniziale da archivio taggato
│   └── aggiungi_manuale.py        # Fase 5: aggiunta singola foto+nome da CLI
├── templates/                     # HTML per la web UI di revisione
├── static/
├── logs/                          # log_scarti.csv, riepiloghi batch, esclusi da git
└── sessioni/                      # cartelle di foto da rivedere in editing, escluse da git
```

`db/`, `logs/`, `sessioni/` e `venv/` sono esclusi da git per evitare di versionare dati biometrici, foto e file pesanti nel repo locale.

## Casi limite gestiti nel popolamento batch (Fase 3)

- Nessun volto rilevato nella foto → skip, log in `log_scarti`.
- Più volti rilevati con un solo nome IPTC → skip di default (non si può sapere quale volto corrisponde al nome), segnalato in un file separato per revisione manuale futura.
- IPTC vuoto o non parsabile → skip, log in `log_scarti`.
- A fine batch: file di riepilogo con conteggi (foto processate, embedding salvati, scarti per categoria).

## Stato bloccante noto

**La posizione dell'archivio JPG già taggato non è ancora nota** (da localizzare — potrebbe essere su uno dei volumi esterni tracciati in `~/archivio-foto/inventory.db`, sistema di inventario file separato non collegato a questo progetto). Questo blocca la Fase 2 (ispezione campione IPTC reale) e la Fase 3 (popolamento batch), ma non impedisce di procedere con Fase 1 (setup progetto, virtualenv, verifica installazione InsightFace) fin da subito.

## Fasi di sviluppo

1. Setup progetto: struttura cartelle, virtualenv Python 3.13, dipendenze, verifica funzionamento InsightFace su questo Mac.
2. Ispezione archivio reale: individuare la posizione dell'archivio, ispezionare un campione per confermare il campo IPTC popolato.
3. Modulo di estrazione/popolamento batch con logging dei casi scartati.
4. Modulo di matching con soglie configurabili, testato su un piccolo set noto.
5. Modulo di apprendimento incrementale.
6. Web UI di revisione batch per la fase di editing.
7. Test end-to-end su un sottoinsieme reale dell'archivio, prima del popolamento completo.

## Nota legale

Il database tratta dati biometrici di persone identificate nell'ambito dell'attività professionale di Pietro. Resta locale e non condiviso, ma la base giuridica corretta (informativa minima, finalità, conservazione, diritto di cancellazione) va verificata con il commercialista/legale in parallelo allo sviluppo — fuori dallo scope tecnico di questo progetto.
