"""Rinomina in batch foto non taggate in base al riconoscimento volti.

Uso:
    python scripts/rinomina_batch.py <cartella_input> <cartella_output> [modelle|personaggi]

Scansiona <cartella_input> (e sottocartelle) alla ricerca di JPG/PNG, rileva
i volti con InsightFace, li confronta col database del profilo indicato
(default "personaggi" se omesso), e copia ogni foto in <cartella_output>
(stessa struttura di sottocartelle) col nome del file originale seguito da
un segmento per ogni volto trovato: nome e punteggio se il match è certo o
ambiguo, "sconosciuto" se nessun candidato valido, "NESSUN_VOLTO" se non è
stato rilevato alcun volto nella foto o se tutti i volti rilevati erano
troppo piccoli/sullo sfondo (vedi RAPPORTO_AREA_MINIMO). Per il profilo
"modelle" si usa una soglia minima piu' severa (SOGLIA_BASSA_MODELLE): non
c'e' una persona a disambiguare i match incerti come nella UI web, quindi
sotto quella soglia il volto resta "sconosciuto" invece di "ambiguo".

Sempre per il profilo "modelle" il nome file e' "pulito" (vedi
formato_modelle): i segmenti sono separati da spazi, i nomi hanno sempre
l'iniziale maiuscola ("Mila van Eeten" -> "Mila Van Eeten") e i volti
sconosciuti/assenti non aggiungono nulla, quindi una foto senza nessun nome
riconosciuto mantiene il nome originale.

Prima di elaborare le foto, si sincronizza col sito (NAS) per scaricare i
nomi confermati li' nel frattempo: cosi' il droplet riconosce anche le
persone aggiunte dal sito senza dover prima aprire "Avvia Modelle/
Personaggi.command" a mano. Se il sito non e' raggiungibile si procede
comunque con i dati locali piu' recenti disponibili.
"""

import contextlib
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PROFILI
from core.matching import SOGLIA_BASSA, calcola_candidati, classifica_match
from core.sync import esegui_ciclo_sync
from core.volti import rileva_volti
from db.database import connetti

PERCORSO_DB_DEFAULT = Path(__file__).resolve().parent.parent / "db" / "volti.db"

# Il profilo "modelle" non ha una persona che disambigua i match incerti come
# nella UI web: un match sotto questa soglia (piu' severa della SOGLIA_BASSA
# generale) resta "sconosciuto" invece di "ambiguo/DA_VERIFICARE".
SOGLIA_BASSA_MODELLE = 0.5

ESTENSIONI = ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.png", "*.PNG")

# Budget in byte (UTF-8) per il nome file generato, con margine sotto il limite
# di ~255 byte per componente di percorso del filesystem (macOS/APFS). Sopra
# questa soglia i segmenti in eccesso vengono troncati (vedi _tronca_nome_file).
LIMITE_BYTE_NOME_FILE = 200

# Rapporto minimo (area volto / area foto) sotto il quale un volto è considerato
# sullo sfondo/troppo piccolo per un riconoscimento affidabile. Calibrato su un
# campione reale di 62 volti in 20 foto: i volti "principali" occupavano tra lo
# 0,70% e il 3,25% dell'area della foto, tutti gli altri (sfondo/sfocati) tra lo
# 0,02% e lo 0,22% — soglia scelta nel mezzo di quel salto.
RAPPORTO_AREA_MINIMO = 0.004


def _sanitizza_nome(nome: str) -> str:
    """Sostituisce spazi con underscore e rimuove caratteri non validi in un nome file."""
    nome = nome.replace(" ", "_")
    for carattere in ("/", "\\", ":"):
        nome = nome.replace(carattere, "_")
    return nome


def _formatta_nome_modella(nome: str) -> str:
    """Normalizza un nome per il formato "modelle": parole separate da un solo
    spazio (trattini/underscore compresi) e sempre con iniziale maiuscola,
    anche dopo un apostrofo ("IDA HEINER" -> "Ida Heiner",
    "carmen dell'orefice" -> "Carmen Dell'Orefice"). Le parole tutte maiuscole
    vengono riportate in minuscolo, le altre mantengono le maiuscole interne
    ("McMenamy" resta "McMenamy")."""
    parole = [p for p in re.split(r"[\s_\-/\\:]+", nome) if p]
    return " ".join(
        re.sub(
            r"(^|')(\w)",
            lambda m: m.group(1) + m.group(2).upper(),
            parola.lower() if parola.isupper() else parola,
        )
        for parola in parole
    )


def _segmento_per_volto(
    volto, conn, soglia_bassa: float = SOGLIA_BASSA, formato_modelle: bool = False
) -> tuple[str | None, str]:
    """Calcola il segmento di nome file per un singolo volto rilevato.

    Ritorna (segmento, categoria) dove categoria è 'certo', 'ambiguo' o 'sconosciuto'.
    Con formato_modelle un volto sconosciuto non produce alcun segmento (None)."""
    candidati = calcola_candidati(volto.vettore, conn)
    stato = classifica_match(candidati, soglia_bassa=soglia_bassa)
    if stato == "sconosciuto":
        return (None if formato_modelle else "sconosciuto"), "sconosciuto"
    punteggio = round(candidati[0].punteggio * 100)
    if formato_modelle:
        nome = _formatta_nome_modella(candidati[0].nome)
        if stato == "ambiguo":
            return f"{nome} {punteggio} DA VERIFICARE", "ambiguo"
        return f"{nome} {punteggio}", "certo"
    nome_sanificato = _sanitizza_nome(candidati[0].nome)
    if stato == "ambiguo":
        return f"{nome_sanificato}_{punteggio}_DA_VERIFICARE", "ambiguo"
    return f"{nome_sanificato}_{punteggio}", "certo"


def _tronca_nome_file(
    stem: str, segmenti: list[str], suffisso: str, separatore: str = "_"
) -> str:
    """Costruisce il nome file tenendo solo i primi segmenti che stanno nel
    budget LIMITE_BYTE_NOME_FILE, aggiungendo un marcatore ALTRI<sep><N> per i
    segmenti omessi. Usata quando il nome completo (foto con molti volti
    rilevati) supererebbe il limite di lunghezza del filesystem."""
    tenuti: list[str] = []
    for indice in range(len(segmenti)):
        candidati = segmenti[: indice + 1]
        omessi = len(segmenti) - len(candidati)
        pezzi = [stem] + candidati + ([f"ALTRI{separatore}{omessi}"] if omessi > 0 else [])
        nome_prova = separatore.join(pezzi) + suffisso
        if len(nome_prova.encode("utf-8")) > LIMITE_BYTE_NOME_FILE:
            break
        tenuti = candidati

    omessi = len(segmenti) - len(tenuti)
    pezzi = [stem] + tenuti + ([f"ALTRI{separatore}{omessi}"] if omessi > 0 else [])
    return separatore.join(pezzi) + suffisso


def _puo_appartenere_a(nome_file: Path, stem: str) -> bool:
    """True se nome_file puo' essere l'output di una foto sorgente con questo
    stem: copia col nome originale, oppure stem seguito da "_" (formato
    personaggi) o da " " (formato modelle)."""
    return (
        nome_file.stem == stem
        or nome_file.name.startswith(f"{stem}_")
        or nome_file.name.startswith(f"{stem} ")
    )


def _pluralizza(numero: int, singolare: str, plurale: str) -> str:
    return singolare if numero == 1 else plurale


def _formatta_riepilogo_breve(riepilogo: dict[str, int]) -> str:
    """Costruisce la riga di riepilogo breve mostrata nel dialog del droplet
    (che cattura solo stdout) invece del dump completo del dizionario."""
    nomi_trovati = riepilogo["certo"] + riepilogo["ambiguo"]
    parola_nomi = _pluralizza(nomi_trovati, "nome trovato", "nomi trovati")
    parola_certi = _pluralizza(riepilogo["certo"], "certo", "certi")
    parola_sconosciuti = _pluralizza(riepilogo["sconosciuto"], "sconosciuto", "sconosciuti")
    righe = [
        f"{riepilogo['foto_totali']} foto",
        f"{nomi_trovati} {parola_nomi} ({riepilogo['certo']} {parola_certi}, {riepilogo['ambiguo']} da verificare)",
        f"{riepilogo['sconosciuto']} {parola_sconosciuti}",
        f"{riepilogo['nessun_volto']} senza volto a fuoco",
    ]
    testo = righe[0] + " — " + ", ".join(righe[1:])

    errori_totali = (
        riepilogo["errore_lettura_immagine"]
        + riepilogo["errore_riconoscimento"]
        + riepilogo["errore_copia"]
    )
    if errori_totali > 0:
        parola_errori = _pluralizza(errori_totali, "errore", "errori")
        testo += f"\n{errori_totali} {parola_errori} (dettagli in terminale)"
    return testo


def rinomina_da_cartella(
    cartella_input: Path,
    cartella_output: Path,
    percorso_db: Path,
    soglia_bassa: float = SOGLIA_BASSA,
    formato_modelle: bool = False,
) -> dict[str, int]:
    """Elabora tutte le foto JPG/PNG in cartella_input (ricorsivo) e ne copia una
    versione rinominata in cartella_output, rispecchiando la struttura di
    sottocartelle dell'input. Gli originali non vengono mai modificati.

    Con formato_modelle i nomi trovati sono separati da spazi e i volti
    sconosciuti/assenti non aggiungono nulla al nome file.

    Ritorna un riepilogo: {'foto_totali': N, 'certo': N, 'ambiguo': N,
    'sconosciuto': N, 'nessun_volto': N, 'scartati_piccoli_sfondo': N,
    'errore_lettura_immagine': N, 'errore_riconoscimento': N,
    'errore_copia': N}.
    I conteggi certo/ambiguo/sconosciuto/nessun_volto/scartati_piccoli_sfondo
    sono per volto (una foto con più volti può contribuire a più categorie);
    foto_totali, errore_lettura_immagine (fallimento di rileva_volti),
    errore_riconoscimento (fallimento nel confronto col DB per uno dei volti)
    ed errore_copia (fallimento nella creazione della cartella o nella copia
    del file) sono per foto.
    """
    conn = connetti(percorso_db)
    riepilogo = {
        "foto_totali": 0,
        "certo": 0,
        "ambiguo": 0,
        "sconosciuto": 0,
        "nessun_volto": 0,
        "scartati_piccoli_sfondo": 0,
        "errore_lettura_immagine": 0,
        "errore_riconoscimento": 0,
        "errore_copia": 0,
    }

    foto_trovate = sorted(
        {percorso for pattern in ESTENSIONI for percorso in cartella_input.rglob(pattern)}
    )
    tutti_gli_stem = {f.stem for f in foto_trovate}

    try:
        for foto in foto_trovate:
            riepilogo["foto_totali"] += 1
            try:
                # InsightFace stampa log di caricamento modello ("find model:",
                # "Applied providers:", ecc.) direttamente su stdout con print()
                # — qui li reindirizziamo su stderr per non farli finire nel
                # dialog del droplet, che cattura solo lo stdout del comando.
                with contextlib.redirect_stdout(sys.stderr):
                    volti = rileva_volti(foto)
            except ValueError as errore:
                riepilogo["errore_lettura_immagine"] += 1
                print(f"[errore_lettura_immagine] {foto.name}: {errore}", file=sys.stderr)
                continue
            except Exception as errore:
                riepilogo["errore_lettura_immagine"] += 1
                print(f"[errore_lettura_immagine] {foto.name}: {errore}", file=sys.stderr)
                continue

            volti_validi = []
            if volti:
                larghezza_immagine, altezza_immagine = Image.open(foto).size
                area_immagine = larghezza_immagine * altezza_immagine
                for volto in volti:
                    x1, y1, x2, y2 = volto.bbox
                    area_volto = max(0, x2 - x1) * max(0, y2 - y1)
                    rapporto = area_volto / area_immagine if area_immagine else 0
                    if rapporto < RAPPORTO_AREA_MINIMO:
                        riepilogo["scartati_piccoli_sfondo"] += 1
                        print(
                            f"[scartato_piccolo_sfondo] {foto.name}: "
                            f"area {rapporto*100:.2f}% sotto soglia {RAPPORTO_AREA_MINIMO*100:.2f}%",
                            file=sys.stderr,
                        )
                        continue
                    volti_validi.append(volto)

            separatore = " " if formato_modelle else "_"
            if not volti_validi:
                riepilogo["nessun_volto"] += 1
                if formato_modelle:
                    nuovo_nome = foto.name
                else:
                    nuovo_nome = f"{foto.stem}_NESSUN_VOLTO{foto.suffix}"
            else:
                try:
                    segmenti = []
                    for volto in volti_validi:
                        segmento, categoria = _segmento_per_volto(
                            volto, conn, soglia_bassa, formato_modelle
                        )
                        if segmento is not None:
                            segmenti.append(segmento)
                        riepilogo[categoria] += 1
                    nuovo_nome = separatore.join([foto.stem] + segmenti) + foto.suffix
                    if len(nuovo_nome.encode("utf-8")) > LIMITE_BYTE_NOME_FILE:
                        nuovo_nome = _tronca_nome_file(
                            foto.stem, segmenti, foto.suffix, separatore
                        )
                except Exception as errore:
                    riepilogo["errore_riconoscimento"] += 1
                    print(f"[errore_riconoscimento] {foto.name}: {errore}", file=sys.stderr)
                    continue

            try:
                percorso_relativo = foto.relative_to(cartella_input).parent
                cartella_output_foto = cartella_output / percorso_relativo
                cartella_output_foto.mkdir(parents=True, exist_ok=True)
                percorso_destinazione = cartella_output_foto / nuovo_nome
                # pulisce gli output precedenti della stessa foto in entrambi i
                # formati (personaggi "stem_..." e modelle "stem ..."/"stem.ext")
                vecchi = set(cartella_output_foto.glob(f"{foto.stem}_*{foto.suffix}"))
                vecchi |= set(cartella_output_foto.glob(f"{foto.stem} *{foto.suffix}"))
                vecchi |= set(cartella_output_foto.glob(f"{foto.stem}{foto.suffix}"))
                for vecchio in sorted(vecchi):
                    if vecchio == percorso_destinazione:
                        continue
                    altri_possibili_proprietari = any(
                        altro_stem != foto.stem and _puo_appartenere_a(vecchio, altro_stem)
                        for altro_stem in tutti_gli_stem
                    )
                    if altri_possibili_proprietari:
                        continue
                    vecchio.unlink()
                shutil.copy2(foto, percorso_destinazione)
                print(f"[{nuovo_nome}] <- {foto.name}", file=sys.stderr)
            except Exception as errore:
                riepilogo["errore_copia"] += 1
                print(f"[errore_copia] {foto.name}: {errore}", file=sys.stderr)
    finally:
        conn.close()
    return riepilogo


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print(
            "Uso: python scripts/rinomina_batch.py <cartella_input> <cartella_output> "
            "[modelle|personaggi]"
        )
        return 1

    cartella_input = Path(sys.argv[1])
    cartella_output = Path(sys.argv[2])

    if not cartella_input.is_dir():
        print(f"Cartella non trovata: {cartella_input}")
        return 1

    if len(sys.argv) == 4:
        nome_profilo = sys.argv[3]
        if nome_profilo not in PROFILI:
            print(f"Profilo sconosciuto: {nome_profilo!r}. Usa 'modelle' o 'personaggi'.")
            return 1
        percorso_db = PROFILI[nome_profilo]["db"]
    else:
        nome_profilo = "personaggi"
        percorso_db = PERCORSO_DB_DEFAULT

    soglia_bassa = SOGLIA_BASSA_MODELLE if nome_profilo == "modelle" else SOGLIA_BASSA

    if not percorso_db.is_file():
        print(f"Database non trovato: {percorso_db}")
        return 1

    esito_sync = esegui_ciclo_sync(
        percorso_db, PROFILI[nome_profilo]["sessioni"], PROFILI[nome_profilo]["nas_url"]
    )
    if esito_sync["raggiungibile"]:
        print(f"Sincronizzato con il sito: {esito_sync['ricevuti']} nomi nuovi scaricati.")
    else:
        print("Sito non raggiungibile: uso i dati locali piu' recenti disponibili.")

    conn = connetti(percorso_db)
    try:
        (numero_embedding,) = conn.execute("SELECT COUNT(*) FROM embedding").fetchone()
    finally:
        conn.close()
    if numero_embedding == 0:
        print(
            "Attenzione: il database non contiene ancora nessun volto — "
            "tutte le foto risulteranno sconosciute."
        )

    riepilogo = rinomina_da_cartella(
        cartella_input,
        cartella_output,
        percorso_db,
        soglia_bassa,
        formato_modelle=nome_profilo == "modelle",
    )

    print(_formatta_riepilogo_breve(riepilogo))

    return 0


if __name__ == "__main__":
    sys.exit(main())
