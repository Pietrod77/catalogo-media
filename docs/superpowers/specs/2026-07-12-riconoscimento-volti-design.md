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

Già installato sul Mac di Pietro, standard più affidabile di `iptcinfo3` (poco mantenuto, gestisce peggio i casi limite). Prima di scrivere il parser definitivo va ispezionato un campione reale dell'archivio per confermare quale campo IPTC è popolato (`Object Name`, `Caption/Abstract`, o altro).

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
