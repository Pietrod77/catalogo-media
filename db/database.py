"""Inizializzazione e connessione al database SQLite dei volti."""

import sqlite3
from pathlib import Path

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
