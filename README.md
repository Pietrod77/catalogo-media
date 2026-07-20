# Catalogo Media

Strumento locale di catalogazione e indicizzazione per archivio fotografico. Uso esclusivamente locale, nessun dato condiviso con servizi cloud.

Design completo: `docs/superpowers/specs/2026-07-12-riconoscimento-volti-design.md`.

## Setup su un nuovo computer

1. Clona il repository:
   ```bash
   git clone https://github.com/Pietrod77/catalogo-media.git
   cd catalogo-media
   ```
2. Installa Python 3.13 via Homebrew se non presente: `brew install python@3.13`
3. Crea il virtualenv locale (va ricreato su ogni macchina):
   ```bash
   python3.13 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. Verifica che `exiftool` sia installato: `exiftool -ver` (su Mac: `brew install exiftool`).
5. Recupera le cartelle dati (`db/` e `sessioni/`, escluse dal repository) dal canale che ti è stato indicato e posizionale nella root del progetto.
6. Esegui la verifica end-to-end:
   ```bash
   python scripts/verifica_setup.py /percorso/a/una/foto/con/un/volto.jpg
   ```

## Regola d'oro multi-computer

Non tenere l'app aperta su due computer contemporaneamente: il database SQLite condiviso non è pensato per scritture concorrenti da macchine diverse. Chiudi l'app e aspetta il completamento della sincronizzazione prima di passare a un altro computer.
