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
    sincronizzato INTEGER NOT NULL DEFAULT 1,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS log_scarti (
    id INTEGER PRIMARY KEY,
    foto TEXT NOT NULL,
    motivo TEXT NOT NULL,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_stato (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ultimo_persona_id_nas INTEGER NOT NULL DEFAULT 0,
    ultimo_embedding_id_nas INTEGER NOT NULL DEFAULT 0
);
"""


def connetti(percorso_db: str | Path) -> sqlite3.Connection:
    """Apre una connessione al DB. Modalità journal di default (non WAL),
    per compatibilità con la sincronizzazione via Dropbox su più computer."""
    conn = sqlite3.connect(str(percorso_db))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migra_colonna_sincronizzato(conn: sqlite3.Connection) -> None:
    """Aggiunge embedding.sincronizzato ai DB creati prima di questa modifica
    (CREATE TABLE IF NOT EXISTS non altera tabelle gia' esistenti)."""
    colonne = [riga[1] for riga in conn.execute("PRAGMA table_info(embedding)").fetchall()]
    if "sincronizzato" not in colonne:
        conn.execute(
            "ALTER TABLE embedding ADD COLUMN sincronizzato INTEGER NOT NULL DEFAULT 1"
        )
        conn.commit()


def init_db(percorso_db: str | Path) -> None:
    """Crea le tabelle persone, embedding, log_scarti, sync_stato se non esistono già,
    e migra i DB pre-esistenti aggiungendo la colonna sincronizzato se assente."""
    conn = connetti(percorso_db)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migra_colonna_sincronizzato(conn)
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


def foto_gia_processata(conn: sqlite3.Connection, foto: str) -> bool:
    """Ritorna True se la foto è già stata salvata o scartata in un run precedente."""
    if (
        conn.execute(
            "SELECT 1 FROM embedding WHERE foto_origine = ? LIMIT 1", (foto,)
        ).fetchone()
        is not None
    ):
        return True
    if (
        conn.execute(
            "SELECT 1 FROM log_scarti WHERE foto = ? LIMIT 1", (foto,)
        ).fetchone()
        is not None
    ):
        return True
    return False


def registra_scarto(conn: sqlite3.Connection, foto: str, motivo: str) -> int:
    """Registra una foto scartata durante il popolamento. Ritorna l'id della riga creata."""
    cursor = conn.execute(
        "INSERT INTO log_scarti (foto, motivo) VALUES (?, ?)", (foto, motivo)
    )
    conn.commit()
    return cursor.lastrowid
