"""Estrazione di coppie foto+nome da un facesheet PDF (facce+didascalie).

Uso:
    python scripts/importa_facesheet.py <file.pdf> <cartella_output>

Estrae ogni foto persona incorporata nel PDF e abbina la didascalia con il nome
piu' vicina, in qualunque posizione rispetto alla foto (sopra, sotto, a lato o
sovrapposta) per adattarsi ai diversi layout usati da agenzie e maison. Salva
ogni foto come JPG con il nome scritto nel tag IPTC/XMP-getty:Personality (lo
stesso campo letto da core/iptc.py) e genera un foglio di controllo HTML per
la revisione manuale prima di lanciare scripts/popola_batch.py sulla cartella
di output.
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # pymupdf
from PIL import Image

MIN_AREA_PT = 3000  # scarta immagini molto piccole (loghi/icone)
RELATIVE_AREA_RATIO = 0.2  # scarta immagini con area < 20% della piu' grande nella pagina
MAX_GAP = 40  # pt di spazio massimo tra il bordo della foto e la didascalia (sopra/sotto/lati)
TOLLERANZA_SOVRAPPOSIZIONE = 15  # pt di leggera sovrapposizione ammessa (didascalia a ridosso del bordo)
OVERLAY_FRACTION = 0.4  # la didascalia puo' sovrapporsi fino al 40% dell'area della foto
LUNGHEZZA_MASSIMA_NOME = 60  # oltre questa lunghezza il testo e' quasi certo un paragrafo, non un nome
RAPPORTO_ALTEZZA_ANOMALA = 1.5  # immagini piu' alte di questo multiplo della mediana di pagina hanno bbox inaffidabile
FRAZIONE_PAGINE_BOILERPLATE = 0.3  # testo ripetuto identico su piu' di questa frazione di pagine = intestazione/piede pagina, non un nome

# Intestazioni di sezione ricorrenti in questo tipo di documento: non sono mai nomi di persone.
PAROLE_NON_NOME = {
    "top", "talent", "talents", "vip", "vips", "kol", "kols", "ambassador",
    "ambassadors", "press", "guest", "guests", "celeb", "celebs", "celebrity",
    "celebrities", "influencer", "influencers", "confirmed", "tbc", "executive",
    "executives", "execs", "global", "suggestions", "suggestion", "attendance",
    "red", "carpet", "countries", "sports", "team", "demographic",
    "demographics", "millennial", "gen",
}

# Descrizioni di professione/ruolo: mai il nome di una persona, ma spesso vicine
# alla foto quanto (o piu' di) il nome vero.
PAROLE_RUOLO = {
    "actor", "actress", "actors", "actresses", "musician", "musicians",
    "singer", "singers", "model", "models", "athlete", "athletes",
    "footballer", "footballers", "rapper", "rappers", "dj", "djs",
    "influencer", "influencers", "creator", "creators", "author", "authors",
    "artist", "artists", "designer", "designers", "presenter", "presenters",
    "host", "hosts", "attended", "award", "winning", "multi",
    "dancer", "dancers", "journalist", "journalists", "personality",
}


def estrai_pagina(page: "fitz.Page") -> tuple[list[tuple[tuple, int]], list[tuple[tuple, str]]]:
    """Ritorna (immagini, testi) della pagina: immagini come (bbox, xref),
    testi come (bbox, testo), una riga per elemento."""
    immagini = [
        (im["bbox"], im["xref"]) for im in page.get_image_info(xrefs=True) if im.get("xref")
    ]
    testi = []
    for blocco in page.get_text("dict")["blocks"]:
        if blocco["type"] != 0:
            continue
        for linea in blocco["lines"]:
            testo = "".join(s["text"] for s in linea["spans"]).strip()
            if testo:
                testi.append((linea["bbox"], testo))
    return immagini, testi


def filtra_loghi(immagini: list[tuple[tuple, int]]) -> list[tuple[tuple, int]]:
    """Scarta immagini troppo piccole rispetto alle altre nella stessa pagina
    (tipicamente loghi o icone decorative, non foto di persone)."""
    if not immagini:
        return immagini
    aree = [(x1 - x0) * (y1 - y0) for (x0, y0, x1, y1), _ in immagini]
    area_max = max(aree)
    return [
        img
        for img, area in zip(immagini, aree)
        if area >= MIN_AREA_PT and area >= area_max * RELATIVE_AREA_RATIO
    ]


RE_NUMERO_PAGINA = re.compile(r"^\W*page\W*\d+\W*$", re.IGNORECASE)
# Codice di look/outfit ("AA15", "AA2"): sigla breve senza spazi, mai un nome.
RE_CODICE_LOOK = re.compile(r"^[A-Z]{1,4}\d{1,4}[A-Z]?$")
# Descrizione tra parentesi in coda al nome ("Lulu Wang (Chinese-American director)").
RE_PARENTESI_FINALE = re.compile(r"\s*\([^()]*\)\s*$")
# Statistiche follower ("301K FOLLOWERS, ER 6%") o deliverable social ("1 IG REEL + 3 STORIES").
RE_STATISTICHE_SOCIAL = re.compile(
    r"\d+\s*(%|k\b|m\b|million|reach)|followers|\ber\s*\d", re.IGNORECASE
)
RE_DELIVERABLE_SOCIAL = re.compile(
    r"^\d+\s*(ig|ig\s*post|ig\s*reel|ig\s*carousel|ig\s*stor|tiktok|reel|story|stories|carousel)\b",
    re.IGNORECASE,
)
PAROLE_DI_PROSA = {
    "and", "the", "with", "for", "in", "an", "his", "her", "of", "its", "is",
    "he", "she", "also", "a", "to", "at", "on", "as", "known", "who",
    "attending", "will", "be",
}
# Nomi di piattaforme social usati come etichetta invece che come nome di persona.
PIATTAFORME_SOCIAL = {"ig", "tiktok", "tik", "tok", "youtube", "weibo", "facebook", "instagram", "content"}
# Suffissi di nome che finiscono in punto ("Kelvin Harrison Jr.") ma non sono
# fine di una frase come i frammenti di prosa che la regola sul punto finale
# vuole scartare.
SUFFISSI_NOME = {"jr", "sr", "ii", "iii", "iv"}


def pulisci_nome(testo: str) -> str:
    """Rimuove un'eventuale descrizione tra parentesi in coda al nome
    (es. "Lulu Wang (Chinese-American director)" -> "Lulu Wang")."""
    return RE_PARENTESI_FINALE.sub("", testo).strip()


def sembra_nome(testo: str) -> bool:
    """Esclude testo che non puo' essere un nome: campi etichettati (contengono ':'),
    paragrafi/frammenti di prosa troppo lunghi o con parole di collegamento tipiche
    di una frase, numeri di pagina, sigle di look/outfit, o intestazioni di sezione
    ricorrenti in questi documenti (TOP, VIP, KOL, TBC, ...). I nomi in questi
    documenti sono sempre scritti come didascalie (maiuscolo/titolo, mai punto
    finale), eventualmente seguiti da una descrizione tra parentesi che viene
    ignorata ai fini del controllo."""
    testo_pulito = pulisci_nome(testo)
    if ":" in testo_pulito:
        return False
    if len(testo_pulito) > LUNGHEZZA_MASSIMA_NOME:
        return False
    parole = re.findall(r"[^\W\d_]+", testo_pulito.lower())
    if not parole:
        return False
    if testo_pulito.endswith(".") and parole[-1] not in SUFFISSI_NOME:
        return False
    if RE_NUMERO_PAGINA.match(testo_pulito):
        return False
    if RE_CODICE_LOOK.match(testo_pulito):
        return False
    if RE_STATISTICHE_SOCIAL.search(testo_pulito):
        return False
    if RE_DELIVERABLE_SOCIAL.match(testo_pulito):
        return False
    if all(p in PAROLE_NON_NOME for p in parole):
        return False
    if any(p in PAROLE_DI_PROSA for p in parole):
        return False
    if any(p in PAROLE_RUOLO for p in parole):
        return False
    if all(p in PIATTAFORME_SOCIAL for p in parole):
        return False
    return True


def _sovrapposizione(a0: float, a1: float, b0: float, b1: float) -> float:
    """Lunghezza della sovrapposizione tra due intervalli [a0,a1] e [b0,b1] (0 se nessuna)."""
    return max(0.0, min(a1, b1) - max(a0, b0))


def distanza_candidato(
    bbox_img: tuple, bbox_testo: tuple, bbox_affidabile: bool = True, gap_massimo: float = MAX_GAP
) -> float | None:
    """Ritorna un punteggio di distanza (piu' basso = abbinamento piu' probabile)
    se il testo puo' essere la didascalia di questa foto (sopra, sotto, a lato o
    sovrapposta in basso), altrimenti None. Se bbox_affidabile e' False (immagine
    con bounding box anomalo rispetto alle altre della pagina) si considera solo
    il caso di sovrapposizione, non la ricerca direzionale sopra/sotto/lato."""
    ix0, iy0, ix1, iy1 = bbox_img
    tx0, ty0, tx1, ty1 = bbox_testo

    # Sovrapposta alla foto, in basso o in alto (didascalia disegnata dentro la foto)
    altezza_img = iy1 - iy0
    zona_overlay_alta = iy1 - altezza_img * OVERLAY_FRACTION
    zona_overlay_bassa = iy0 + altezza_img * OVERLAY_FRACTION
    centro_testo_y = (ty0 + ty1) / 2
    if _sovrapposizione(tx0, tx1, ix0, ix1) > 0:
        if zona_overlay_alta <= centro_testo_y <= iy1:
            return abs(iy1 - centro_testo_y)
        if iy0 <= centro_testo_y <= zona_overlay_bassa:
            return abs(centro_testo_y - iy0)

    if not bbox_affidabile:
        return None

    # Sotto o sopra la foto, con sovrapposizione orizzontale
    if _sovrapposizione(tx0, tx1, ix0, ix1) > 0:
        if -TOLLERANZA_SOVRAPPOSIZIONE <= ty0 - iy1 <= gap_massimo:  # sotto
            return abs(ty0 - iy1)
        if -TOLLERANZA_SOVRAPPOSIZIONE <= iy0 - ty1 <= gap_massimo:  # sopra
            return abs(iy0 - ty1)

    # A destra o a sinistra della foto, con sovrapposizione verticale. Quando la
    # foto e' alta quanto l'intera scheda (caso tipico bio-card), piu' testi
    # nella stessa colonna si sovrappongono tutti verticalmente alla foto: si
    # preferisce quello piu' vicino alla parte alta della foto, dove di norma
    # sta il nome, non semplicemente il piu' vicino in orizzontale.
    if _sovrapposizione(ty0, ty1, iy0, iy1) > 0:
        scarto_dall_alto = abs(centro_testo_y - iy0)
        if -TOLLERANZA_SOVRAPPOSIZIONE <= tx0 - ix1 <= gap_massimo:  # a destra
            return abs(tx0 - ix1) + scarto_dall_alto
        if -TOLLERANZA_SOVRAPPOSIZIONE <= ix0 - tx1 <= gap_massimo:  # a sinistra
            return abs(ix0 - tx1) + scarto_dall_alto

    return None


def abbina_foto_nomi(
    immagini: list[tuple[tuple, int]],
    testi: list[tuple[tuple, str]],
    boilerplate: set[str] = frozenset(),
) -> list[tuple[int, str | None]]:
    """Abbina ogni foto alla didascalia piu' vicina (assegnazione greedy per
    distanza crescente). Ogni foto riceve al massimo un nome, ma lo stesso nome
    puo' essere riutilizzato per piu' foto vicine (caso comune: piu' foto della
    stessa persona sulla stessa pagina). Le foto senza didascalia trovata
    restano con nome None. `boilerplate` e' un insieme di testi da ignorare
    (intestazioni/piedi pagina ripetuti su piu' pagine)."""
    altezze = sorted((y1 - y0) for (_, y0, _, y1), _ in immagini)
    mediana_altezza = altezze[len(altezze) // 2] if altezze else 0
    # Se in pagina c'e' un solo nome candidato (indipendentemente da quante
    # foto), non c'e' ambiguita' possibile su chi sia: si allarga la tolleranza
    # di distanza per catturare layout con didascalia lontana dalla foto (es.
    # nome in cima alla pagina, una o piu' foto della stessa persona piu' in
    # basso, come nelle schede "un vip per pagina" di alcune maison).
    numero_nomi_candidati = sum(
        1 for _, testo in testi if sembra_nome(testo) and testo not in boilerplate
    )
    gap_massimo = MAX_GAP if numero_nomi_candidati != 1 else 1000.0

    candidati = []
    for i_idx, (bbox_img, _) in enumerate(immagini):
        altezza_img = bbox_img[3] - bbox_img[1]
        bbox_affidabile = (
            mediana_altezza == 0 or altezza_img <= mediana_altezza * RAPPORTO_ALTEZZA_ANOMALA
        )
        for t_idx, (bbox_testo, testo) in enumerate(testi):
            if not sembra_nome(testo) or testo in boilerplate:
                continue
            d = distanza_candidato(bbox_img, bbox_testo, bbox_affidabile, gap_massimo)
            if d is not None:
                e_handle = testo.strip().startswith("@")
                candidati.append((e_handle, d, i_idx, t_idx))
    # Un nome vero (non-handle) vince sempre su un handle Instagram/TikTok
    # anche se geometricamente un po' piu' lontano: l'handle e' un ripiego,
    # usato solo se per quella foto non si trova nessun nome vero vicino.
    candidati.sort(key=lambda c: (c[0], c[1]))

    immagini_usate: set[int] = set()
    abbinamenti: dict[int, str] = {}
    for _, _, i_idx, t_idx in candidati:
        if i_idx in immagini_usate:
            continue
        immagini_usate.add(i_idx)
        abbinamenti[i_idx] = pulisci_nome(testi[t_idx][1])

    return [(xref, abbinamenti.get(i_idx)) for i_idx, (_, xref) in enumerate(immagini)]


def sanitizza_nome_file(nome: str) -> str:
    pulito = re.sub(r"[^A-Za-z0-9]+", "_", nome).strip("_")
    return pulito or "senza_nome"


def scrivi_tag_personality(percorso_foto: Path, nome: str) -> None:
    subprocess.run(
        ["exiftool", "-overwrite_original", f"-XMP-getty:Personality={nome}", str(percorso_foto)],
        capture_output=True,
        check=True,
    )


def salva_come_jpeg(dati: bytes, percorso_foto: Path) -> None:
    """Salva i byte immagine estratti dal PDF come JPEG in percorso_foto,
    indipendentemente dal formato originale (alcuni PDF incorporano PNG)."""
    import io

    with Image.open(io.BytesIO(dati)) as img:
        img.convert("RGB").save(percorso_foto, "JPEG", quality=92)


def applica_ripiego_pagina_singola(
    abbinamenti: list[tuple[int, str | None]],
) -> list[tuple[int, str | None]]:
    """Se in una pagina e' stato trovato un solo nome distinto (caso tipico:
    una scheda con piu' foto della stessa persona, dove il nome e' vicino solo
    alla prima foto), lo applica anche alle foto della stessa pagina rimaste
    senza abbinamento geometrico."""
    nomi_trovati = {nome for _, nome in abbinamenti if nome}
    if len(nomi_trovati) != 1:
        return abbinamenti
    unico_nome = next(iter(nomi_trovati))
    return [(xref, nome or unico_nome) for xref, nome in abbinamenti]


def trova_boilerplate(
    pagine: list[tuple[list[tuple[tuple, int]], list[tuple[tuple, str]]]],
) -> set[str]:
    """Individua testi identici ripetuti su piu' pagine (intestazioni, piedi
    pagina, numeri di pagina): non possono essere nomi di persone."""
    if not pagine:
        return set()
    conteggio: dict[str, int] = {}
    for _, testi in pagine:
        for _, testo in set((bbox, t) for bbox, t in testi):
            conteggio[testo] = conteggio.get(testo, 0) + 1
    soglia = max(2, int(len(pagine) * FRAZIONE_PAGINE_BOILERPLATE))
    return {testo for testo, n in conteggio.items() if n >= soglia}


def trova_immagini_boilerplate(
    pagine: list[tuple[list[tuple[tuple, int]], list[tuple[tuple, str]]]],
) -> set[int]:
    """Individua xref di immagini che si ripetono identiche su piu' pagine:
    tipicamente un logo o watermark fisso di pagina, mai una foto di persona."""
    if not pagine:
        return set()
    conteggio: dict[int, int] = {}
    for immagini, _ in pagine:
        for xref in {xref for _, xref in immagini}:
            conteggio[xref] = conteggio.get(xref, 0) + 1
    soglia = max(2, int(len(pagine) * FRAZIONE_PAGINE_BOILERPLATE))
    return {xref for xref, n in conteggio.items() if n >= soglia}


def estrai_facesheet(percorso_pdf: Path, cartella_output: Path) -> list[dict]:
    """Estrae tutte le foto dal PDF, le abbina a un nome quando possibile,
    le salva come JPG taggati in cartella_output e ritorna i risultati
    (uno per foto) per il foglio di controllo."""
    cartella_output.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(percorso_pdf)
    risultati = []
    contatore = 0

    pagine = [estrai_pagina(page) for page in doc]
    boilerplate = trova_boilerplate(pagine)
    immagini_boilerplate = trova_immagini_boilerplate(pagine)

    for num_pagina, (immagini, testi) in enumerate(pagine, start=1):
        immagini = [(bbox, xref) for bbox, xref in immagini if xref not in immagini_boilerplate]
        immagini = filtra_loghi(immagini)
        if not immagini:
            continue

        abbinamenti = abbina_foto_nomi(immagini, testi, boilerplate)
        abbinamenti = applica_ripiego_pagina_singola(abbinamenti)

        for xref, nome in abbinamenti:
            contatore += 1
            base = sanitizza_nome_file(nome) if nome else f"pagina{num_pagina}_{contatore}"
            nome_file = f"{contatore:03d}_{base}.jpg"
            percorso_foto = cartella_output / nome_file

            try:
                dati_immagine = doc.extract_image(xref)
                salva_come_jpeg(dati_immagine["image"], percorso_foto)
            except Exception as errore:
                print(f"[errore_estrazione] pagina {num_pagina}, xref {xref}: {errore}")
                continue

            if nome:
                try:
                    scrivi_tag_personality(percorso_foto, nome)
                except Exception as errore:
                    print(f"[errore_tag] {nome_file}: {errore}")

            risultati.append({"file": nome_file, "nome": nome, "pagina": num_pagina})

    return risultati


def scrivi_foglio_controllo(risultati: list[dict], cartella_output: Path, nome_pdf: str) -> Path:
    righe = []
    for r in risultati:
        nome = r["nome"] or "⚠️ NESSUN NOME TROVATO"
        classe = "senza-nome" if not r["nome"] else ""
        righe.append(
            f'<div class="scheda {classe}" data-file="{r["file"]}" onclick="toggleEsclusa(this)">'
            f'<img src="{r["file"]}" loading="lazy">'
            f'<div class="didascalia">{nome}<br><small>pag. {r["pagina"]} — {r["file"]}</small></div>'
            f"</div>"
        )

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Revisione {nome_pdf}</title>
<style>
body {{ font-family: -apple-system, sans-serif; background: #111; color: #eee; margin: 0; padding: 20px; }}
h1 {{ font-size: 16px; font-weight: normal; color: #999; }}
.barra {{ position: sticky; top: 0; background: #111; padding: 10px 0; display: flex; align-items: center; gap: 12px; z-index: 10; }}
.barra button {{ background: #d33; color: #fff; border: none; border-radius: 6px; padding: 8px 14px; font-size: 13px; cursor: pointer; }}
.barra button:hover {{ background: #f44; }}
.barra span {{ color: #999; font-size: 13px; }}
.griglia {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }}
.scheda {{ background: #222; border-radius: 8px; overflow: hidden; cursor: pointer; border: 3px solid transparent; user-select: none; }}
.scheda.senza-nome {{ border-color: #a33; }}
.scheda.esclusa {{ border-color: #f44; opacity: 0.35; }}
.scheda.esclusa .didascalia::before {{ content: "❌ ESCLUSA — "; color: #f66; }}
.scheda img {{ width: 100%; aspect-ratio: 3/4; object-fit: cover; display: block; }}
.didascalia {{ padding: 8px; font-size: 13px; }}
.didascalia small {{ color: #888; }}
</style></head>
<body>
<div class="barra">
  <button onclick="scaricaEsclusioni()">Scarica lista esclusioni</button>
  <span id="contatore">0 foto marcate come sbagliate</span>
</div>
<h1>{nome_pdf} — {len(risultati)} foto estratte. Clicca una foto per marcarla come sbagliata.</h1>
<div class="griglia">
{''.join(righe)}
</div>
<script>
function toggleEsclusa(el) {{
  el.classList.toggle('esclusa');
  const n = document.querySelectorAll('.scheda.esclusa').length;
  document.getElementById('contatore').textContent = n + ' foto marcate come sbagliate';
}}
function scaricaEsclusioni() {{
  const file = [...document.querySelectorAll('.scheda.esclusa')].map(el => el.dataset.file);
  const blob = new Blob([file.join('\\n')], {{type: 'text/plain'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'esclusioni.txt';
  a.click();
}}
</script>
</body></html>
"""
    percorso_html = cartella_output / "_revisione.html"
    percorso_html.write_text(html, encoding="utf-8")
    return percorso_html


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: python scripts/importa_facesheet.py <file.pdf> <cartella_output>")
        return 1

    percorso_pdf = Path(sys.argv[1])
    cartella_output = Path(sys.argv[2])
    if not percorso_pdf.is_file():
        print(f"File non trovato: {percorso_pdf}")
        return 1

    risultati = estrai_facesheet(percorso_pdf, cartella_output)
    percorso_html = scrivi_foglio_controllo(risultati, cartella_output, percorso_pdf.name)

    con_nome = sum(1 for r in risultati if r["nome"])
    senza_nome = len(risultati) - con_nome
    print(f"\nEstratte {len(risultati)} foto ({con_nome} con nome, {senza_nome} senza nome).")
    print(f"Foglio di controllo: {percorso_html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
