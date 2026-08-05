# Design: riepilogo breve e filtro volti sfocati/sfondo per rinomina_batch.py

Data: 2026-08-05

## Contesto e obiettivo

`scripts/rinomina_batch.py` (già in produzione, usato tramite il droplet macOS "Rinomina Volti.app") funziona ma Pietro ha segnalato due problemi dopo l'uso reale:

1. Il dialog di riepilogo finale mostra l'intero output stampato dallo script (una riga per ogni foto processata), che diventa lunghissimo e poco leggibile su cartelle numerose.
2. Lo script rileva e cerca di riconoscere anche i volti piccoli/sfocati sullo sfondo delle foto (es. persone lontane, fuori fuoco), producendo segmenti di nome file poco utili o fuorvianti per volti che non sono il soggetto reale della foto.

## Cosa NON cambia

Nessuna modifica a `core/volti.py`, `core/matching.py`, `db/database.py`, `app.py` o alla web app. Il filtro di nitidezza riusa la costante `SOGLIA_QUALITA_MINIMA` già esportata da `core/volti.py` e già usata da `app.py` (endpoint `/conferma`) con lo stesso significato: sotto soglia, il volto è considerato di qualità/nitidezza insufficiente per un riconoscimento affidabile.

## 1. Filtro volti sotto soglia di qualità

In `rinomina_da_cartella`, subito dopo la chiamata a `rileva_volti(foto)`, i volti rilevati vengono filtrati scartando quelli con `volto.score < SOGLIA_QUALITA_MINIMA` (stessa soglia 0.5 già in uso in `app.py`). Solo i volti rimanenti vengono passati a `_segmento_per_volto` per il matching e la costruzione del nome file.

Se **tutti** i volti rilevati in una foto vengono scartati dal filtro (incluso il caso limite in cui non ne era stato rilevato nessuno), la foto è trattata esattamente come il caso già esistente "nessun volto rilevato": marcatore `_NESSUN_VOLTO` nel nome file, incremento del contatore esistente `nessun_volto`. Non viene introdotto un marcatore distinto per "volti scartati per qualità" — dal punto di vista dell'utente il risultato pratico è lo stesso: "nessuno da riconoscere qui".

Viene aggiunto un nuovo contatore nel dizionario di riepilogo, `scartati_bassa_qualita` (per volto, non per foto), che conta quanti volti sono stati esclusi dal filtro — usato solo per diagnostica via terminale (vedi sezione 3), non mostrato nel dialog breve.

## 2. Riepilogo breve

`main()` non stampa più il dizionario di riepilogo grezzo chiave per chiave. Costruisce invece una singola riga di sintesi, ad esempio:

```
150 foto — 92 nomi trovati (78 certi, 14 da verificare), 40 sconosciuti, 18 senza volto a fuoco
```

dove "nomi trovati" = `certo + ambiguo` (con il dettaglio dei due tra parentesi), "sconosciuti" = `sconosciuto`, "senza volto a fuoco" = `nessun_volto` (il contatore unificato descritto sopra).

Se la somma di `errore_lettura_immagine + errore_riconoscimento + errore_copia` è maggiore di zero, viene aggiunta una riga ulteriore:

```
3 errori (dettagli in terminale)
```

Questa è l'unica cosa stampata su stdout da `main()` a fine elaborazione (oltre all'eventuale avviso "database vuoto" già esistente, stampato prima di iniziare).

## 3. Stdout vs stderr

Il droplet AppleScript lancia lo script con `do shell script` e cattura solo lo **stdout** del comando nella variabile mostrata nel dialog finale — non stderr. Per accorciare il dialog senza perdere visibilità durante il debug da terminale (dove stdout e stderr appaiono comunque intrecciati sullo stesso schermo):

- La riga di successo per-foto (`[nuovo_nome] <- foto.name`) passa da stdout a stderr.
- Le righe di errore per-foto (`[errore_lettura_immagine]`, `[errore_riconoscimento]`, `[errore_copia]`) passano da stdout a stderr.
- Viene aggiunta una riga diagnostica su stderr per ogni volto scartato dal filtro qualità, ad esempio `[scartato_bassa_qualita] foto.name: score 0.31 sotto soglia 0.50` — utile se in futuro serve ritarare la soglia osservando quanti/quali volti vengono esclusi.
- Il riepilogo finale breve (sezione 2) resta l'unica cosa su stdout, quindi l'unica cosa che finisce nel dialog del droplet.

Nessuna modifica al file `Rinomina Volti.app` stesso (il comando lanciato resta identico) — il cambiamento è interamente nello script Python.

## Testing

Aggiornamenti a `tests/test_rinomina_batch.py`:

- Volto con `score` sotto `SOGLIA_QUALITA_MINIMA` → trattato come nessun volto valido (marcatore `_NESSUN_VOLTO`, contatore `nessun_volto` incrementato, `scartati_bassa_qualita` incrementato).
- Volto con `score` sopra soglia → comportamento invariato rispetto a oggi (nessuna regressione).
- Foto con due volti, uno sopra e uno sotto soglia → solo il volto valido contribuisce al nome file e ai contatori certo/ambiguo/sconosciuto; il contatore `scartati_bassa_qualita` riflette il volto escluso.
- `rinomina_da_cartella` continua a ritornare il dizionario di riepilogo completo (compreso il nuovo campo `scartati_bassa_qualita`) — i test sul formato breve stampato da `main()` si limitano a verificare che la funzione di formattazione produca la riga attesa dati input di esempio, senza dover catturare stdout/stderr dell'intero processo.

## Fuori scope

- Rendere la soglia configurabile da riga di comando o da UI — resta fissa, la stessa costante condivisa con l'app web.
- Un criterio alternativo basato sulla dimensione del bounding box — scartato in fase di brainstorming a favore del riuso dello score già esistente.
- Modifiche al droplet AppleScript — il cambiamento è trasparente al chiamante.
