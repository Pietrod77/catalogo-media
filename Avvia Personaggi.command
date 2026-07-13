#!/bin/bash
# Avvia il tool di riconoscimento volti, profilo "personaggi" (porta 5002).
# Doppio click da Finder: apre il Terminal, avvia il server e il browser.
cd "$(dirname "$0")"
source venv/bin/activate
python app.py personaggi
