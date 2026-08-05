#!/bin/bash
# Avvia il tool di riconoscimento volti, profilo "personaggi" (porta 5002).
# Doppio click da Finder: apre il Terminal, avvia il server e il browser.
cd "$(dirname "$0")"
source venv/bin/activate
export VOLTI_NAS_URL="http://100.125.65.26:5002"
python app.py personaggi
