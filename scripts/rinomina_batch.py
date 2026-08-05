"""Rinomina in batch foto non taggate in base al riconoscimento volti.

Uso:
    python scripts/rinomina_batch.py <cartella_input> <cartella_output>

Scansiona <cartella_input> (e sottocartelle) alla ricerca di JPG/PNG, rileva
i volti con InsightFace, li confronta col database "personaggi", e copia
ogni foto in <cartella_output> (stessa struttura di sottocartelle) col nome
del file originale seguito da un segmento per ogni volto trovato: nome e
punteggio se il match è certo o ambiguo, "sconosciuto" se nessun candidato
valido, "NESSUN_VOLTO" se non è stato rilevato alcun volto nella foto.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.matching import calcola_candidati, classifica_match
from core.volti import SOGLIA_QUALITA_MINIMA, rileva_volti
from db.database import connetti

PERCORSO_DB_DEFAULT = Path(__file__).resolve().parent.parent / "db" / "volti.db"

ESTENSIONI = ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.png", "*.PNG")

# Budget in byte (UTF-8) per il nome file generato, con margine sotto il limite
# di ~255 byte per componente di percorso del filesystem (macOS/APFS). Sopra
# questa soglia i segmenti in eccesso vengono troncati (vedi _tronca_nome_file).
LIMITE_BYTE_NOME_FILE = 200


def _sanitizza_nome(nome: str) -> str:
    """Sostituisce spazi con underscore e rimuove caratteri non validi in un nome file."""
    nome = nome.replace(" ", "_")
    for carattere in ("/", "\\", ":"):
        nome = nome.replace(carattere, "_")
    return nome


def _segmento_per_volto(volto, conn) -> tuple[str, str]:
    """Calcola il segmento di nome file per un singolo volto rilevato.

    Ritorna (segmento, categoria) dove categoria è 'certo', 'ambiguo' o 'sconosciuto'."""
    candidati = calcola_candidati(volto.vettore, conn)
    stato = classifica_match(candidati)
    if stato == "sconosciuto":
        return "sconosciuto", "sconosciuto"
    nome_sanificato = _sanitizza_nome(candidati[0].nome)
    punteggio = round(candidati[0].punteggio * 100)
    if stato == "ambiguo":
        return f"{nome_sanificato}_{punteggio}_DA_VERIFICARE", "ambiguo"
    return f"{nome_sanificato}_{punteggio}", "certo"


def _tronca_nome_file(stem: str, segmenti: list[str], suffisso: str) -> str:
    """Costruisce il nome file tenendo solo i primi segmenti che stanno nel
    budget LIMITE_BYTE_NOME_FILE, aggiungendo un marcatore _ALTRI_<N> per i
    segmenti omessi. Usata quando il nome completo (foto con molti volti
    rilevati) supererebbe il limite di lunghezza del filesystem."""
    tenuti: list[str] = []
    for indice in range(len(segmenti)):
        candidati = segmenti[: indice + 1]
        omessi = len(segmenti) - len(candidati)
        pezzi = [stem] + candidati + ([f"ALTRI_{omessi}"] if omessi > 0 else [])
        nome_prova = "_".join(pezzi) + suffisso
        if len(nome_prova.encode("utf-8")) > LIMITE_BYTE_NOME_FILE:
            break
        tenuti = candidati

    omessi = len(segmenti) - len(tenuti)
    pezzi = [stem] + tenuti + ([f"ALTRI_{omessi}"] if omessi > 0 else [])
    return "_".join(pezzi) + suffisso


def _formatta_riepilogo_breve(riepilogo: dict[str, int]) -> str:
    """Costruisce la riga di riepilogo breve mostrata nel dialog del droplet
    (che cattura solo stdout) invece del dump completo del dizionario."""
    nomi_trovati = riepilogo["certo"] + riepilogo["ambiguo"]
    righe = [
        f"{riepilogo['foto_totali']} foto",
        f"{nomi_trovati} nomi trovati ({riepilogo['certo']} certi, {riepilogo['ambiguo']} da verificare)",
        f"{riepilogo['sconosciuto']} sconosciuti",
        f"{riepilogo['nessun_volto']} senza volto a fuoco",
    ]
    testo = " — ".join(righe)

    errori_totali = (
        riepilogo["errore_lettura_immagine"]
        + riepilogo["errore_riconoscimento"]
        + riepilogo["errore_copia"]
    )
    if errori_totali > 0:
        testo += f"\n{errori_totali} errori (dettagli in terminale)"
    return testo


def rinomina_da_cartella(
    cartella_input: Path, cartella_output: Path, percorso_db: Path
) -> dict[str, int]:
    """Elabora tutte le foto JPG/PNG in cartella_input (ricorsivo) e ne copia una
    versione rinominata in cartella_output, rispecchiando la struttura di
    sottocartelle dell'input. Gli originali non vengono mai modificati.

    Ritorna un riepilogo: {'foto_totali': N, 'certo': N, 'ambiguo': N,
    'sconosciuto': N, 'nessun_volto': N, 'errore_lettura_immagine': N,
    'errore_riconoscimento': N, 'errore_copia': N}.
    I conteggi certo/ambiguo/sconosciuto/nessun_volto sono per volto (una foto
    con più volti può contribuire a più categorie); foto_totali,
    errore_lettura_immagine (fallimento di rileva_volti), errore_riconoscimento
    (fallimento nel confronto col DB per uno dei volti) ed errore_copia
    (fallimento nella creazione della cartella o nella copia del file) sono
    per foto.
    """
    conn = connetti(percorso_db)
    riepilogo = {
        "foto_totali": 0,
        "certo": 0,
        "ambiguo": 0,
        "sconosciuto": 0,
        "nessun_volto": 0,
        "scartati_bassa_qualita": 0,
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
            for volto in volti:
                if volto.score < SOGLIA_QUALITA_MINIMA:
                    riepilogo["scartati_bassa_qualita"] += 1
                    print(
                        f"[scartato_bassa_qualita] {foto.name}: "
                        f"score {volto.score:.2f} sotto soglia {SOGLIA_QUALITA_MINIMA:.2f}",
                        file=sys.stderr,
                    )
                    continue
                volti_validi.append(volto)

            if not volti_validi:
                riepilogo["nessun_volto"] += 1
                nuovo_nome = f"{foto.stem}_NESSUN_VOLTO{foto.suffix}"
            else:
                try:
                    segmenti = []
                    for volto in volti_validi:
                        segmento, categoria = _segmento_per_volto(volto, conn)
                        segmenti.append(segmento)
                        riepilogo[categoria] += 1
                    nuovo_nome = f"{foto.stem}_{'_'.join(segmenti)}{foto.suffix}"
                    if len(nuovo_nome.encode("utf-8")) > LIMITE_BYTE_NOME_FILE:
                        nuovo_nome = _tronca_nome_file(foto.stem, segmenti, foto.suffix)
                except Exception as errore:
                    riepilogo["errore_riconoscimento"] += 1
                    print(f"[errore_riconoscimento] {foto.name}: {errore}", file=sys.stderr)
                    continue

            try:
                percorso_relativo = foto.relative_to(cartella_input).parent
                cartella_output_foto = cartella_output / percorso_relativo
                cartella_output_foto.mkdir(parents=True, exist_ok=True)
                percorso_destinazione = cartella_output_foto / nuovo_nome
                for vecchio in cartella_output_foto.glob(f"{foto.stem}_*{foto.suffix}"):
                    if vecchio == percorso_destinazione:
                        continue
                    altri_possibili_proprietari = any(
                        altro_stem != foto.stem and vecchio.name.startswith(f"{altro_stem}_")
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
    if len(sys.argv) != 3:
        print("Uso: python scripts/rinomina_batch.py <cartella_input> <cartella_output>")
        return 1

    cartella_input = Path(sys.argv[1])
    cartella_output = Path(sys.argv[2])

    if not cartella_input.is_dir():
        print(f"Cartella non trovata: {cartella_input}")
        return 1

    if not PERCORSO_DB_DEFAULT.is_file():
        print(f"Database non trovato: {PERCORSO_DB_DEFAULT}")
        return 1

    conn = connetti(PERCORSO_DB_DEFAULT)
    try:
        (numero_embedding,) = conn.execute("SELECT COUNT(*) FROM embedding").fetchone()
    finally:
        conn.close()
    if numero_embedding == 0:
        print(
            "Attenzione: il database non contiene ancora nessun volto — "
            "tutte le foto risulteranno sconosciute."
        )

    riepilogo = rinomina_da_cartella(cartella_input, cartella_output, PERCORSO_DB_DEFAULT)

    print(_formatta_riepilogo_breve(riepilogo))

    return 0


if __name__ == "__main__":
    sys.exit(main())
