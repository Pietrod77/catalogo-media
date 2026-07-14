# Filtro qualità sugli embedding salvati — Design

## Contesto

Oggi, quando l'utente conferma un nome tramite l'interfaccia web (`POST /conferma`), il vettore embedding calcolato durante `/analizza` viene salvato come riferimento per quella persona, indipendentemente da quanto il volto rilevato fosse nitido, grande o ben illuminato nello screenshot originale. Un embedding calcolato da un rilevamento scadente (volto piccolo, sfocato, di profilo, in ombra) può degradare la qualità del matching futuro per quella persona.

InsightFace calcola già, per ogni volto rilevato, uno `score` di confidenza (`det_score`, campo `VoltoRilevato.score` in `core/volti.py`) — ma questo valore non viene mai passato al frontend né usato per decidere se salvare l'embedding.

## Vincolo esplicito dell'utente

Il filtro deve applicarsi **solo ai nuovi salvataggi**, da quando viene implementato in poi. Non deve in alcun modo toccare, invalidare, ricalcolare o rimuovere embedding già presenti nel database (in particolare le modelle inserite a mano nel profilo "modelle"). Nessuna migrazione, nessuna colonna nuova nel DB, nessuna riscrittura di dati esistenti.

## Calibrazione della soglia (dati reali)

Poiché lo score non è mai stato salvato nel DB, per calibrare la soglia si è rieseguito il rilevamento (operazione di sola lettura, nessuna modifica al DB) sulle foto di riferimento (`foto_origine`) dei 115 embedding già presenti:

- **modelle** (45 embedding, inseriti a mano): score min 0.64, mediana 0.82, max 0.89. 2 casi sotto 0.70, 0 sotto 0.5.
- **personaggi** (70 embedding, da import batch IPTC): score min 0.57, mediana 0.86, max 0.92. 1 caso sotto 0.70, 0 sotto 0.5.

Una soglia di **0.5** non avrebbe bloccato nessuno dei 115 embedding già accettati manualmente in passato, pur essendo abbastanza permissiva da lasciar passare la maggior parte dei rilevamenti normali. È un punto di partenza prudente, nello stesso spirito delle soglie di matching (`SOGLIA_ALTA`/`SOGLIA_BASSA` in `core/matching.py`), regolabile in futuro quando si avrà più esperienza reale con il filtro attivo.

## Comportamento

Quando un tentativo di salvataggio (`/conferma`) riguarda un volto con score sotto soglia, il salvataggio viene **bloccato completamente**: nessun embedding scadente entra mai nel database. L'utente vede un messaggio di errore e deve riprovare con uno screenshot più nitido/ravvicinato del volto.

Il blocco avviene solo sull'azione di salvataggio, non sull'analisi/matching: `/analizza` continua a mostrare candidati e stato (certo/ambiguo/sconosciuto) anche per volti di bassa qualità, perché l'informazione resta utile per capire chi potrebbe essere. Solo il tentativo di scriverlo come nuovo riferimento nel DB viene rifiutato.

## Architettura

**Nuova costante** in `core/volti.py`, accanto a `VoltoRilevato`:
```python
SOGLIA_QUALITA_MINIMA = 0.5
```
Vive qui (non in `core/matching.py`) perché è una proprietà della qualità del rilevamento del volto, non del matching contro persone esistenti.

**Flusso dati — `score` deve attraversare tre punti:**

1. `POST /analizza` (`app.py`): ogni elemento di `risultato_volti` guadagna la chiave `"score": volto.score` (il valore è già calcolato da `rileva_volti`, va solo esposto nella risposta JSON).

2. `static/app.js`: l'oggetto `volto` ricevuto da `/analizza` include già `.score` grazie al punto 1. La funzione `confermaNome(volto, nome)` include `score: volto.score` nel body JSON inviato a `/conferma`, accanto a `nome`, `vettore`, `screenshot_base64`.

3. `POST /conferma` (`app.py`): legge `dati.get("score")`.
   - Se assente (`None`): 400 `{"errore": "dati mancanti"}` — stesso trattamento già riservato a `vettore`/`screenshot_base64` mancanti.
   - Se presente e `score < SOGLIA_QUALITA_MINIMA`: 400 `{"errore": "qualità troppo bassa (score {score:.2f}), usa uno screenshot più nitido o ravvicinato"}`.
   - Se `score >= SOGLIA_QUALITA_MINIMA`: procede come oggi (crea/trova persona, salva embedding).

Il controllo si inserisce nella validazione già esistente in `/conferma` (accanto al controllo su `nome` e sulla shape del vettore), stesso stile e stessa posizione nel codice.

## Gestione errori lato frontend

Nessun nuovo codice UI necessario: `confermaNome()` in `app.js` già gestisce risposte `/conferma` non-ok mostrando `dati.errore` in `#risultato` (vedi gestione esistente per l'errore "vettore non valido"). Il messaggio di qualità bassa passa dallo stesso percorso.

## Testing

Seguendo lo stile TDD già presente in `tests/test_app.py`:

- `test_analizza_include_score_nel_risultato`: verifica che la risposta di `/analizza` contenga `score` per ogni volto rilevato.
- `test_conferma_score_basso_ritorna_400`: invia un `/conferma` con `score` sotto `SOGLIA_QUALITA_MINIMA`, verifica 400 e che non venga creata alcuna persona/embedding nel DB (stesso pattern del test già esistente per vettore di lunghezza sbagliata).
- `test_conferma_score_assente_ritorna_400`: invia un `/conferma` senza campo `score`, verifica 400 "dati mancanti".
- `test_conferma_score_sufficiente_salva_normalmente`: verifica che con score sopra soglia il salvataggio avvenga come oggi.
- I test esistenti che chiamano `/conferma` (es. `test_conferma_nome_nuovo_crea_persona_ed_embedding`) vanno aggiornati per includere un campo `score` valido nel payload, altrimenti falliranno con "dati mancanti" dopo questa modifica.

## Fuori scope

- Nessun controllo aggiuntivo sulla dimensione in pixel del volto: si usa solo `det_score`, già disponibile.
- Nessuna modifica retroattiva ai dati esistenti.
- Nessuna soglia diversa per profilo (modelle/personaggi): un'unica costante condivisa, coerente con l'approccio attuale delle soglie di matching.
- Nessun'opzione per l'utente di forzare il salvataggio nonostante la bassa qualità (scelta esplicita: blocco totale, non un avviso aggirabile).
