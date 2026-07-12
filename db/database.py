"""Inizializzazione e connessione al database SQLite dei volti."""

import sqlite3
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS persone (
    id INTEGER PRIMARY KEY,
    nome TEXT UNIQUE NOT NULL,
    note TEXT,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS embedding (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES persone(id),
    vettore BLOB NOT NULL,
    foto_origine TEXT NOT NULL,
    fonte TEXT NOT NULL,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS log_scarti (
    id INTEGER PRIMARY KEY,
    foto TEXT NOT NULL,
    motivo TEXT NOT NULL,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def connetti(percorso_db: str | Path) -> sqlite3.Connection:
    """Apre una connessione al DB. Modalità journal di default (non WAL),
    per compatibilità con la sincronizzazione via Dropbox su più computer."""
    conn = sqlite3.connect(str(percorso_db))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(percorso_db: str | Path) -> None:
    """Crea le tabelle persone, embedding, log_scarti se non esistono già."""
    conn = connetti(percorso_db)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def trova_o_crea_persona(conn: sqlite3.Connection, nome: str) -> int:
    """Ritorna l'id della persona con quel nome, creandola se non esiste già."""
    riga = conn.execute("SELECT id FROM persone WHERE nome = ?", (nome,)).fetchone()
    if riga is not None:
        return riga[0]
    cursor = conn.execute("INSERT INTO persone (nome) VALUES (?)", (nome,))
    conn.commit()
    return cursor.lastrowid


def salva_embedding(
    conn: sqlite3.Connection,
    person_id: int,
    vettore: np.ndarray,
    foto_origine: str,
    fonte: str,
) -> int:
    """Inserisce un embedding legato a una persona. Ritorna l'id della riga creata."""
    cursor = conn.execute(
        "INSERT INTO embedding (person_id, vettore, foto_origine, fonte) "
        "VALUES (?, ?, ?, ?)",
        (person_id, vettore.astype(np.float32).tobytes(), foto_origine, fonte),
    )
    conn.commit()
    return cursor.lastrowid


def registra_scarto(conn: sqlite3.Connection, foto: str, motivo: str) -> int:
    """Registra una foto scartata durante il popolamento. Ritorna l'id della riga creata."""
    cursor = conn.execute(
        "INSERT INTO log_scarti (foto, motivo) VALUES (?, ?)", (foto, motivo)
    )
    conn.commit()
    return cursor.lastrowid
