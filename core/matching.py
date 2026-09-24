"""Confronto di un embedding facciale contro il database, per proporre un nome."""

import sqlite3
from dataclasses import dataclass, field

import numpy as np

SOGLIA_ALTA = 0.45
SOGLIA_BASSA = 0.30


@dataclass
class Candidato:
    nome: str
    punteggio: float
    foto_riferimento: str
    # tutte le foto di riferimento della persona, dalla piu' simile alla meno
    # simile al volto cercato (senza doppioni); la prima e' foto_riferimento
    foto_riferimenti: list[str] = field(default_factory=list)


def calcola_candidati(
    vettore: np.ndarray, conn: sqlite3.Connection, top_n: int = 3
) -> list[Candidato]:
    """Confronta vettore contro tutti gli embedding in DB, ritorna i migliori candidati.

    Per ogni persona il punteggio e' la media dei migliori 3 embedding di quella
    persona (o meno se ne ha meno di 3). Ritorna al massimo top_n candidati,
    ordinati per punteggio decrescente. Lista vuota se il DB non ha embedding.
    """
    righe = conn.execute(
        "SELECT p.nome, e.vettore, e.foto_origine "
        "FROM embedding e JOIN persone p ON p.id = e.person_id"
    ).fetchall()

    per_persona: dict[str, list[tuple[float, str]]] = {}
    for nome, blob, foto in righe:
        if len(blob) != 512 * 4:
            continue  # embedding corrotto/malformato in DB, salta invece di crashare
        vettore_db = np.frombuffer(blob, dtype=np.float32)
        similarita = float(np.dot(vettore, vettore_db))
        per_persona.setdefault(nome, []).append((similarita, foto))

    candidati = []
    for nome, coppie in per_persona.items():
        coppie.sort(key=lambda c: c[0], reverse=True)
        migliori = coppie[:3]
        punteggio = sum(s for s, _ in migliori) / len(migliori)
        foto_riferimenti = list(dict.fromkeys(foto for _, foto in coppie))
        candidati.append(
            Candidato(
                nome=nome,
                punteggio=punteggio,
                foto_riferimento=foto_riferimenti[0],
                foto_riferimenti=foto_riferimenti,
            )
        )

    candidati.sort(key=lambda c: c.punteggio, reverse=True)
    return candidati[:top_n]


def classifica_match(candidati: list[Candidato], soglia_bassa: float = SOGLIA_BASSA) -> str:
    """Ritorna 'certo', 'ambiguo' o 'sconosciuto' in base al punteggio del migliore.

    soglia_bassa e' personalizzabile per i chiamanti che vogliono un criterio
    piu' severo (es. la rinomina in batch, dove non c'e' una persona a
    disambiguare i match incerti come nella UI web)."""
    if not candidati or candidati[0].punteggio < soglia_bassa:
        return "sconosciuto"
    if candidati[0].punteggio >= SOGLIA_ALTA:
        return "certo"
    return "ambiguo"
