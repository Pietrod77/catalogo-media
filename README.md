# Volti_Riconoscimento

Database locale volti↔nomi per identificazione soggetti fotografici (fashion week, backstage, front row). Uso esclusivamente locale, nessun dato biometrico condiviso con servizi cloud.

Design completo: `docs/superpowers/specs/2026-07-12-riconoscimento-volti-design.md`.

## Setup su un nuovo computer

1. Assicurati che questa cartella sia già sincronizzata da Dropbox.
2. Installa Python 3.13 via Homebrew se non presente: `brew install python@3.13`
3. Crea il virtualenv locale (NON sincronizzato, va ricreato su ogni macchina):
   ```bash
   python3.13 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. Escludi `venv/` dalla sincronizzazione Dropbox (comando one-time per macchina):
   ```bash
   xattr -w com.dropbox.ignored 1 venv
   ```
5. Verifica che `exiftool` sia installato: `exiftool -ver` (su Mac: `brew install exiftool`).
6. Esegui la verifica end-to-end:
   ```bash
   python scripts/verifica_setup.py /percorso/a/una/foto/con/un/volto.jpg
   ```

## Regola d'oro multi-computer

Non tenere l'app aperta su due computer contemporaneamente: il database SQLite condiviso via Dropbox non è pensato per scritture concorrenti da macchine diverse. Chiudi l'app e aspetta che Dropbox finisca di sincronizzare prima di passare a un altro computer.
