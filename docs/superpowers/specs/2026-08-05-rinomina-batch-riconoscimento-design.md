# Design: rinomina batch di foto tramite riconoscimento volti

Data: 2026-08-05

## Contesto e obiettivo

Pietro ha cartelle di foto JPG/PNG con volti **non ancora taggati** (l'inverso del caso già gestito da `scripts/popola_batch.py`, dove il nome è già noto — da IPTC o da facesheet — e si popola il DB). Qui invece si parte da foto senza nome e si vuole scoprire chi sono confrontandole col database **personaggi** già popolato, poi ottenere in output le stesse foto rinominate col nome trovato.

Caso d'uso concreto: Pietro riceve un archivio di foto da un evento senza indicazione di chi sia ritratto, e vuole capire velocemente chi sono le persone conosciute presenti, senza doverle riconoscere una per una a mano nell'interfaccia web.

## Cosa NON cambia

Nessuna modifica a `core/volti.py`, `core/matching.py`, `db/database.py`. Il nuovo script riusa `rileva_volti`, `calcola_candidati`, `classifica_match` così come sono — stesse soglie di match già in uso nell'app (`SOGLIA_ALTA=0.45`, `SOGLIA_BASSA=0.30`, `core/matching.py`). Confronta sempre contro il database **personaggi** (fisso, non parametrizzabile — stesso comportamento di `popola_batch.py` oggi), non richiede `exiftool` (a differenza di `popola_batch.py`, qui non si leggono tag IPTC).

## Formato del nome file in output

Per ogni volto rilevato in una foto, in base alla classificazione del match:

- **Match certo** (punteggio ≥ 0.45): aggiunge `_Nome_Cognome_XX` al nome file, dove `XX` è il punteggio × 100 arrotondato all'intero più vicino, e gli spazi nel nome della persona sono sostituiti da underscore.
- **Match ambiguo** (0.30 ≤ punteggio < 0.45): aggiunge `_Nome_Cognome_XX_DA_VERIFICARE` — il marcatore segue immediatamente quel nome specifico, non va accodato una sola volta alla fine di tutto il file. Questo per restare inequivocabile quando in una stessa foto convivono un volto certo e uno ambiguo: solo il segmento del volto incerto porta il marcatore.
- **Sconosciuto** (nessun candidato in DB, o punteggio sotto 0.30): aggiunge `_sconosciuto`, senza nome né percentuale (non c'è nulla di significativo da mostrare).
- **Nessun volto rilevato nella foto** (`rileva_volti` ritorna lista vuota — caso distinto da "sconosciuto": qui non è stato trovato proprio nessun volto, non un volto non riconosciuto): aggiunge `_NESSUN_VOLTO`.

Con più volti nella stessa foto, i segmenti si incatenano nell'ordine di rilevamento: `originale_Mario_Rossi_87_Anna_Bianchi_38_DA_VERIFICARE.jpg`. Il nome del file originale (senza estensione) resta sempre il prefisso, l'estensione originale viene preservata.

**Sanificazione**: prima di inserire il nome della persona nel filename, oltre a sostituire gli spazi con underscore, vengono rimossi/sostituiti eventuali caratteri non validi per un nome file (`/`, `\`, `:`) con un underscore — protezione minima, il caso reale nei nomi già in DB non ne contiene, ma evita un crash se mai capitasse.

## Architettura

**Script**: `scripts/rinomina_batch.py <cartella_input> <cartella_output>`

- Scansiona `<cartella_input>` ricorsivamente per `.jpg`/`.JPG`/`.jpeg`/`.JPEG`/`.png`/`.PNG` (stessi pattern già usati in `popola_batch.py::popola_da_cartella`).
- Per ogni sottocartella trovata nell'input, viene ricreata la stessa sottocartella dentro `<cartella_output>` — la struttura di cartelle dell'output rispecchia quella dell'input. Gli originali non vengono mai toccati (si legge soltanto dalla cartella di input).
- Per ogni foto: rileva i volti, per ciascuno calcola i candidati e classifica il match come da sezione precedente, costruisce il nuovo nome, **copia** (mai sposta) il file nella sottocartella di output corrispondente col nuovo nome.
- Riepilogo finale stampato a schermo (stesso stile di `popola_batch.py`): totale foto processate, quante con match certo/ambiguo/sconosciuto/nessun-volto (contate per volto, non per foto, dato che una foto può contribuire a più di una categoria se ha più volti), eventuali errori di lettura immagine.

**Codice**: funzione testabile `rinomina_da_cartella(cartella_input: Path, cartella_output: Path, percorso_db: Path) -> dict` che fa il lavoro vero, più un `main()` sottile che valida gli argomenti da riga di comando e la richiama — stesso pattern già usato in `popola_batch.py` (separazione tra logica testabile e wrapper CLI).

## Gestione errori

- **Immagine illeggibile/corrotta** (`rileva_volti` solleva `ValueError`): la foto viene saltata, contata in `errore_lettura_immagine` nel riepilogo, il batch continua con le foto successive — non deve interrompere l'intera elaborazione per un file problematico.
- **Cartella di output già esistente con un file dallo stesso nome**: sovrascritto silenziosamente (comportamento accettabile — permette di rilanciare lo script sulla stessa cartella di output senza errori, es. dopo aver aggiunto nuove persone al DB e voler ripetere il riconoscimento).
- **Collisioni di nome nell'output**: strutturalmente impossibili nella stessa sottocartella, perché il nome del file originale resta sempre il prefisso e due file non possono avere lo stesso nome nella stessa cartella di partenza.

## Testing

Nuovo file `tests/test_rinomina_batch.py`, stesso stile della suite esistente (`tmp_path`, `monkeypatch` di `rileva_volti` per simulare volti finti come già fatto in `tests/test_app.py`):

- Un volto con match certo → nome file con `_Nome_Cognome_XX` corretto
- Un volto con match ambiguo → `_Nome_Cognome_XX_DA_VERIFICARE`
- Un volto sconosciuto → `_sconosciuto`
- Nessun volto rilevato → `_NESSUN_VOLTO`
- Due volti nella stessa foto → segmenti incatenati nell'ordine giusto
- Struttura a sottocartelle nell'input → stessa struttura ricreata nell'output
- File originale non toccato/spostato (resta nella cartella di input dopo l'esecuzione)
- Immagine illeggibile → contata come errore, non blocca le foto successive

## Fuori scope

- Interfaccia web per questa funzionalità — resta uno script da terminale, come già deciso.
- Parametrizzazione del profilo (modelle vs personaggi) — fisso su personaggi, come `popola_batch.py`.
- Un modo per rifiutare/confermare via UI i match proposti prima della rinomina — lo script rinomina direttamente, la verifica dei casi "DA_VERIFICARE"/"sconosciuto" resta manuale (a occhio sui nomi file), non c'è un foglio di revisione HTML come per i facesheet.
