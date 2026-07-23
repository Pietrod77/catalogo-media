"""Estrazione OCR di coppie foto+nome da facesheet PDF senza testo nativo:
pagine "flattenate" in poche immagini composite (una colonna di piu' persone
impaginata come un unico raster), dove i nomi sono disegnati dentro
l'immagine invece che come testo PDF vero (caso: MOSCHINO FACE SHEET.pdf).

A differenza di scripts/importa_facesheet.py (che legge il testo nativo del
PDF), qui si usa il rilevamento volti dell'app stessa per trovare ogni
persona nella composite, l'OCR (tesseract) per leggere le didascalie vicine,
e si abbinano per posizione verticale. Ogni composite viene poi tagliata in
una fascia per persona (bordi a meta' strada tra un volto e il successivo).

Richiede tesseract installato (`brew install tesseract`) e il pacchetto
pytesseract (`pip install pytesseract`).

Uso:
    python scripts/importa_facesheet_ocr.py <file.pdf> <cartella_output>
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # pymupdf
import pytesseract
from PIL import Image

from core.volti import rileva_volti
from scripts.importa_facesheet import (
    filtra_loghi,
    sanitizza_nome_file,
    scrivi_foglio_controllo,
    scrivi_tag_personality,
    sembra_nome,
)

CONFIDENZA_OCR_MINIMA = 40
DISTANZA_MASSIMA_NOME = 400  # px: oltre questa distanza verticale un nome non e' plausibile per quel volto


def estrai_righe_ocr(immagine: Image.Image) -> list[tuple[tuple, str]]:
    """OCR sull'immagine con page-segmentation "sparse text" (adatta a
    didascalie isolate su sfondo bianco). Ritorna (bbox_pixel, testo) per riga,
    scartando parole a bassa confidenza o fatte di sola punteggiatura (rumore
    letto dentro le foto)."""
    dati = pytesseract.image_to_data(immagine, output_type=pytesseract.Output.DICT, config="--psm 11")
    righe: dict[tuple, dict] = {}
    for i in range(len(dati["text"])):
        parola = dati["text"][i].strip()
        conf = int(dati["conf"][i])
        if not parola or conf < CONFIDENZA_OCR_MINIMA or not any(c.isalnum() for c in parola):
            continue
        chiave = (dati["block_num"][i], dati["par_num"][i], dati["line_num"][i])
        x, y, w, h = dati["left"][i], dati["top"][i], dati["width"][i], dati["height"][i]
        r = righe.setdefault(chiave, {"parole": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h})
        r["parole"].append(parola)
        r["x0"] = min(r["x0"], x)
        r["y0"] = min(r["y0"], y)
        r["x1"] = max(r["x1"], x + w)
        r["y1"] = max(r["y1"], y + h)
    return [((r["x0"], r["y0"], r["x1"], r["y1"]), " ".join(r["parole"])) for r in righe.values()]


def abbina_volti_nomi_ocr(
    volti: list, righe: list[tuple[tuple, str]]
) -> list[tuple[tuple, str | None]]:
    """Abbina ogni volto rilevato alla riga OCR piu' vicina verticalmente
    (didascalie in questi documenti sono sempre allineate vicino al bordo
    inferiore della foto della persona, a sinistra o sotto). Assegnazione
    greedy per distanza crescente, un nome usato al massimo una volta."""
    candidati = []
    for v_idx, volto in enumerate(volti):
        _, _, _, fy1 = volto.bbox
        for r_idx, (bbox_testo, testo) in enumerate(righe):
            if not sembra_nome(testo):
                continue
            ty0, ty1 = bbox_testo[1], bbox_testo[3]
            centro_testo_y = (ty0 + ty1) / 2
            d = abs(centro_testo_y - fy1)
            if d <= DISTANZA_MASSIMA_NOME:
                candidati.append((d, v_idx, r_idx))
    candidati.sort(key=lambda c: c[0])

    volti_usati: set[int] = set()
    righe_usate: set[int] = set()
    abbinamenti: dict[int, str] = {}
    for _, v_idx, r_idx in candidati:
        if v_idx in volti_usati or r_idx in righe_usate:
            continue
        volti_usati.add(v_idx)
        righe_usate.add(r_idx)
        abbinamenti[v_idx] = righe[r_idx][1]

    return [(volto.bbox, abbinamenti.get(v_idx)) for v_idx, volto in enumerate(volti)]


MARGINE_ORIZZONTALE_VOLTO = 1.5  # multiplo della larghezza del volto da includere ai lati (spalle/capelli)


def ritaglia_fasce(volti: list, larghezza: int, altezza: int) -> list[tuple[int, int, int, int]]:
    """Ritaglia una foto per persona attorno al suo volto: verticalmente una
    fascia a meta' strada tra i centri di volti consecutivi (cosi' ogni fascia
    contiene esattamente un volto, senza sconfinare nel vicino), orizzontalmente
    centrata sul volto invece che sulla larghezza intera della composite (che
    include anche lo spazio bianco della didascalia e mostrerebbe il volto
    fuori inquadratura nel foglio di controllo)."""
    centri_y = [(v.bbox[1] + v.bbox[3]) / 2 for v in volti]
    ordine = sorted(range(len(volti)), key=lambda i: centri_y[i])
    confini_y = [0]
    for a, b in zip(ordine, ordine[1:]):
        confini_y.append(int((centri_y[a] + centri_y[b]) / 2))
    confini_y.append(altezza)

    fasce = [None] * len(volti)
    for posizione, indice in enumerate(ordine):
        fx0, _, fx1, _ = volti[indice].bbox
        centro_x = (fx0 + fx1) / 2
        largh_volto = fx1 - fx0
        x0 = max(0, int(centro_x - largh_volto * MARGINE_ORIZZONTALE_VOLTO))
        x1 = min(larghezza, int(centro_x + largh_volto * MARGINE_ORIZZONTALE_VOLTO))
        fasce[indice] = (x0, confini_y[posizione], x1, confini_y[posizione + 1])
    return fasce


def estrai_facesheet_ocr(percorso_pdf: Path, cartella_output: Path) -> list[dict]:
    cartella_output.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(percorso_pdf)
    risultati = []
    contatore = 0

    for num_pagina, page in enumerate(doc, start=1):
        immagini = [
            (im["bbox"], im["xref"]) for im in page.get_image_info(xrefs=True) if im.get("xref")
        ]
        immagini = filtra_loghi(immagini)

        for _, xref in immagini:
            try:
                dati_immagine = doc.extract_image(xref)
                composite = Image.open(io.BytesIO(dati_immagine["image"])).convert("RGB")
            except Exception as errore:
                print(f"[errore_estrazione] pagina {num_pagina}, xref {xref}: {errore}")
                continue

            percorso_temp = cartella_output / f"_composite_{xref}.jpg"
            composite.save(percorso_temp, "JPEG", quality=95)
            try:
                volti = rileva_volti(percorso_temp)
            finally:
                percorso_temp.unlink(missing_ok=True)
            if not volti:
                continue

            righe = estrai_righe_ocr(composite)
            abbinamenti = abbina_volti_nomi_ocr(volti, righe)
            fasce = ritaglia_fasce(volti, composite.width, composite.height)

            for (bbox_volto, nome), fascia in zip(abbinamenti, fasce):
                contatore += 1
                base = sanitizza_nome_file(nome) if nome else f"pagina{num_pagina}_{contatore}"
                nome_file = f"{contatore:03d}_{base}.jpg"
                percorso_foto = cartella_output / nome_file
                composite.crop(fascia).save(percorso_foto, "JPEG", quality=92)

                if nome:
                    try:
                        scrivi_tag_personality(percorso_foto, nome)
                    except Exception as errore:
                        print(f"[errore_tag] {nome_file}: {errore}")

                risultati.append({"file": nome_file, "nome": nome, "pagina": num_pagina})

    return risultati


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: python scripts/importa_facesheet_ocr.py <file.pdf> <cartella_output>")
        return 1

    percorso_pdf = Path(sys.argv[1])
    cartella_output = Path(sys.argv[2])
    if not percorso_pdf.is_file():
        print(f"File non trovato: {percorso_pdf}")
        return 1

    risultati = estrai_facesheet_ocr(percorso_pdf, cartella_output)
    percorso_html = scrivi_foglio_controllo(risultati, cartella_output, percorso_pdf.name)

    con_nome = sum(1 for r in risultati if r["nome"])
    senza_nome = len(risultati) - con_nome
    print(f"\nEstratte {len(risultati)} foto ({con_nome} con nome, {senza_nome} senza nome).")
    print(f"Foglio di controllo: {percorso_html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
