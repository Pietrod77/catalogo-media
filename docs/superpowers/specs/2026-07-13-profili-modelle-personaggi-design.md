# Design: profili separati modelle/personaggi

Data: 2026-07-13

## Contesto e obiettivo

Il tool (design generale in `docs/superpowers/specs/2026-07-12-riconoscimento-volti-design.md`, web UI in `docs/superpowers/specs/2026-07-13-web-ui-apprendimento-incrementale-design.md`) oggi lavora su un unico database (`db/volti.db`, 22 persone). Pietro fotografa due popolazioni di soggetti molto diverse tra loro:

- **Modelle** — in passerella, non ancora presenti nel DB attuale.
- **Personaggi** — persone non-modelle negli stessi eventi (PR, editor, celebrità in front row, staff backstage). Il DB attuale, popolato dall'archivio Fashion Week Getty (nomi come "Lee Pace", "Christian Louboutin"), è in realtà interamente composto da questa categoria, non da modelle.

**Perché separare invece di aggiungere un campo categoria:** un tag testuale non ridurrebbe i falsi positivi nel matching (che dipende dalla vicinanza degli embedding, non da un'etichetta). Il beneficio reale di due database distinti è duplice:

1. **Scala**: le soglie di matching (0.45/0.30) sono state calibrate nel range 100-500 persone per singolo DB. Con centinaia di modelle *più* 500+ personaggi attesi nel giro di qualche anno, un unico DB combinato supererebbe presto quel range. Separati, ciascun DB resta singolarmente dentro (o vicino) alla scala su cui il sistema è stato validato.
2. **Qualità del match**: le modelle professioniste tendono ad assomigliarsi tra loro (età, tipo fisico) molto più di un gruppo eterogeneo di personaggi. Pool separati evitano di confrontare una modella con un personaggio irrilevante, riducendo il rumore nel matching.

Le prestazioni non sono un vincolo: `calcola_candidati` misura ~10ms su 500 persone/4000 embedding (verificato in una review indipendente), ampio margine anche per un solo DB a piena scala.

## Cosa NON cambia

Nessuna modifica alle route Flask (`GET /`, `POST /analizza`, `POST /conferma`, `GET /riferimento`), a `core/volti.py`, `core/matching.py`, o allo schema SQLite. Sono già completamente parametriche rispetto a `percorso_db` e `cartella_sessioni` (decisione presa in Fase 4): la separazione è un cambio di configurazione/avvio, non di logica applicativa.

## Architettura

### Registro profili in `config.py`

```python
PROFILI = {
    "modelle": {
        "db": RADICE_PROGETTO / "db" / "volti_modelle.db",
        "sessioni": RADICE_PROGETTO / "sessioni" / "modelle",
        "porta": 5001,
        "colore": "#ffe4e1",  # rosso molto chiaro
    },
    "personaggi": {
        "db": PERCORSO_DB_DEFAULT,  # db/volti.db esistente, 22 persone reali
        "sessioni": RADICE_PROGETTO / "sessioni" / "personaggi",
        "porta": 5002,
        "colore": "#b0e0e6",  # azzurro carta da zucchero
    },
}
```

**Il DB esistente (`db/volti.db`) non viene rinominato o spostato** — resta il file fisico del profilo `personaggi`, zero rischio sui dati reali già sincronizzati via Dropbox. Il profilo `modelle` punta a un nuovo file, creato vuoto al primo avvio dallo stesso `init_db` già usato oggi.

Le porte (5001/5002) evitano deliberatamente la 5000 di default, che su macOS confligge con AirPlay Receiver (problema segnalato in una review indipendente sul codice attuale — occasione per sistemarlo insieme a questo cambio).

I colori sono scelte di partenza facilmente modificabili (un valore esadecimale ciascuno in un punto solo).

### Selezione del profilo all'avvio

`app.py` legge `sys.argv[1]`: deve essere esattamente `modelle` o `personaggi`, altrimenti l'app stampa l'uso corretto ed esce (nessun default silenzioso — un avvio senza argomento chiaro rischierebbe di popolare il profilo sbagliato per errore). Esempio:

```bash
python app.py personaggi   # http://127.0.0.1:5002/, i 22 esistenti
python app.py modelle      # http://127.0.0.1:5001/, parte vuoto
```

Entrambi possono restare aperti contemporaneamente in due tab del browser, dato che girano su porte diverse.

### Colore per riconoscimento visivo

`crea_app()` guadagna un terzo parametro opzionale `colore_sfondo` (default `"#ffffff"`, bianco neutro — usato se l'app viene avviata senza passare da un profilo, es. nei test), passato al template `index.html` e applicato come colore di sfondo della pagina. Serve a distinguere a colpo d'occhio in quale profilo ci si trova quando si passa da un tab all'altro — utile soprattutto nei primi tempi, prima che le due UI si differenzino anche nei dati mostrati.

## Struttura file

```
Volti_Riconoscimento/
├── config.py                      # + dizionario PROFILI, funzione di risoluzione profilo
├── app.py                         # blocco __main__ modificato: legge argv, risolve profilo
├── templates/index.html           # + applica colore_sfondo passato dal backend
├── db/
│   ├── volti.db                   # invariato, ora e' il DB "personaggi"
│   └── volti_modelle.db           # NUOVO, creato vuoto al primo avvio, escluso da git (db/*.db)
└── sessioni/
    ├── modelle/conferme/          # NUOVO, dentro sessioni/ gia' esclusa da git
    └── personaggi/conferme/       # NUOVO
```

## Testing

- Funzione pura di risoluzione profilo (nome stringa → dict con db/sessioni/porta/colore, o errore se il nome non è valido) testabile senza Flask, in `tests/test_config.py`.
- `crea_app()` esteso con `colore_sfondo`: un test in `tests/test_app.py` verifica che `GET /` includa il colore passato nell'HTML renderizzato (stesso pattern già usato per verificare `nomi_esistenti_json`).
- Nessuna modifica ai test esistenti delle route — restano validi, i parametri nuovi hanno default neutri.

## Fuori scope

- Filtro di qualità sugli embedding salvati (score minimo di detection) — richiesto da Pietro ma trattato come sotto-progetto separato.
- Import bulk da pagina web — sotto-progetto separato, non ancora disegnato.
- Migrazione/smistamento manuale di persone tra i due DB — non necessario, il DB esistente è già interamente "personaggi".
- Un terzo profilo o un sistema generico a N profili — Pietro ha chiesto esplicitamente due categorie; generalizzare ora sarebbe over-engineering senza un bisogno concreto.
