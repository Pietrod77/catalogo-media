const zonaDrop = document.getElementById("zona-drop");
const risultatoDiv = document.getElementById("risultato");

let screenshotBase64 = null;

zonaDrop.addEventListener("dragover", (evento) => {
    evento.preventDefault();
    zonaDrop.classList.add("drag-over");
});

zonaDrop.addEventListener("dragleave", () => {
    zonaDrop.classList.remove("drag-over");
});

zonaDrop.addEventListener("drop", (evento) => {
    evento.preventDefault();
    zonaDrop.classList.remove("drag-over");
    const file = evento.dataTransfer.files[0];
    if (file) {
        gestisciFile(file);
    }
});

zonaDrop.addEventListener("click", () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = () => {
        if (input.files[0]) {
            gestisciFile(input.files[0]);
        }
    };
    input.click();
});

function gestisciFile(file) {
    const lettore = new FileReader();
    lettore.onload = () => {
        screenshotBase64 = lettore.result.split(",")[1];
    };
    lettore.readAsDataURL(file);

    const formData = new FormData();
    formData.append("immagine", file);

    risultatoDiv.innerHTML = "<p>Analisi in corso...</p>";

    fetch("/analizza", { method: "POST", body: formData })
        .then((risposta) => risposta.json().then((dati) => ({ ok: risposta.ok, dati })))
        .then(({ ok, dati }) => {
            if (!ok) {
                risultatoDiv.innerHTML = `<p class="errore">${dati.errore}</p>`;
                return;
            }
            mostraVolti(dati.volti);
        })
        .catch((errore) => {
            risultatoDiv.innerHTML = '<p class="errore">Errore di rete, riprova.</p>';
        });
}

function mostraVolti(volti) {
    if (volti.length === 0) {
        risultatoDiv.innerHTML =
            '<p class="errore">Nessun volto rilevato. Ritaglia lo screenshot su un volto.</p>';
        return;
    }
    if (volti.length === 1) {
        mostraRisultatoVolto(volti[0]);
        return;
    }
    risultatoDiv.innerHTML = "<p>Piu' volti rilevati, scegli quale identificare:</p>";
    const contenitore = document.createElement("div");
    contenitore.id = "scelta-volti";
    volti.forEach((volto) => {
        const img = document.createElement("img");
        img.src = "data:image/jpeg;base64," + volto.crop_base64;
        img.className = "crop-volto";
        img.addEventListener("click", () => mostraRisultatoVolto(volto));
        contenitore.appendChild(img);
    });
    risultatoDiv.appendChild(contenitore);
}

function mostraRisultatoVolto(volto) {
    risultatoDiv.innerHTML = "";

    const anteprima = document.createElement("img");
    anteprima.src = "data:image/jpeg;base64," + volto.crop_base64;
    anteprima.className = "crop-volto";
    risultatoDiv.appendChild(anteprima);

    if (volto.stato === "certo") {
        mostraCerto(volto);
    } else if (volto.stato === "ambiguo") {
        mostraAmbiguo(volto);
    } else {
        mostraNomeLibero(volto);
    }
}

function mostraCerto(volto) {
    const candidato = volto.candidati[0];
    const blocco = document.createElement("div");
    blocco.innerHTML = `
        <p>${candidato.nome} (${candidato.punteggio.toFixed(3)})</p>
        <button id="btn-conferma">Conferma</button>
        <a href="#" id="link-correggi">non e' lui, correggi</a>
    `;
    risultatoDiv.appendChild(blocco);

    document.getElementById("btn-conferma").addEventListener("click", (evento) => {
        evento.target.disabled = true;
        confermaNome(volto, candidato.nome);
    });
    document.getElementById("link-correggi").addEventListener("click", (evento) => {
        evento.preventDefault();
        mostraNomeLibero(volto);
    });
}

function mostraAmbiguo(volto) {
    const intestazione = document.createElement("p");
    intestazione.textContent = "Match ambiguo, scegli il candidato giusto:";
    risultatoDiv.appendChild(intestazione);

    const lista = document.createElement("div");
    lista.id = "lista-candidati";
    volto.candidati.forEach((candidato) => {
        const voce = document.createElement("div");
        voce.className = "candidato";
        voce.innerHTML = `
            <img src="/riferimento?path=${encodeURIComponent(candidato.foto_riferimento)}" class="miniatura-riferimento">
            <span>${candidato.nome} (${candidato.punteggio.toFixed(3)})</span>
        `;
        voce.addEventListener("click", () => {
            // Guard against double-click: disable all candidati
            const tuttiCandidati = lista.querySelectorAll(".candidato");
            tuttiCandidati.forEach((cd) => {
                cd.style.pointerEvents = "none";
            });
            confermaNome(volto, candidato.nome);
        });
        lista.appendChild(voce);
    });
    risultatoDiv.appendChild(lista);

    const linkAltro = document.createElement("a");
    linkAltro.href = "#";
    linkAltro.textContent = "nessuno di questi, altro nome";
    linkAltro.addEventListener("click", (evento) => {
        evento.preventDefault();
        mostraNomeLibero(volto);
    });
    risultatoDiv.appendChild(linkAltro);
}

function mostraNomeLibero(volto) {
    // Remove all children except the crop preview image
    const figli = Array.from(risultatoDiv.children);
    figli.forEach((figlio) => {
        if (!figlio.classList.contains("crop-volto")) {
            figlio.remove();
        }
    });

    const form = document.createElement("div");
    form.id = "form-nome-libero";
    form.innerHTML = `
        <input type="text" id="input-nome" list="lista-nomi-esistenti" placeholder="Nome persona">
        <datalist id="lista-nomi-esistenti">
            ${NOMI_ESISTENTI.map((nome) => `<option value="${nome}"></option>`).join("")}
        </datalist>
        <button id="btn-salva-nome">Salva nome</button>
    `;
    risultatoDiv.appendChild(form);

    document.getElementById("btn-salva-nome").addEventListener("click", (evento) => {
        const nome = document.getElementById("input-nome").value.trim();
        if (!nome) {
            return;
        }
        evento.target.disabled = true;
        confermaNome(volto, nome);
    });
}

function confermaNome(volto, nome) {
    fetch("/conferma", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            nome: nome,
            vettore: volto.vettore,
            screenshot_base64: screenshotBase64,
        }),
    })
        .then((risposta) => risposta.json())
        .then((dati) => {
            if (dati.ok) {
                if (!NOMI_ESISTENTI.includes(nome)) {
                    NOMI_ESISTENTI.push(nome);
                }
                risultatoDiv.innerHTML = `<p class="successo">Salvato: ${nome}</p>`;
                setTimeout(() => {
                    risultatoDiv.innerHTML = "";
                }, 1500);
            } else {
                risultatoDiv.innerHTML = `<p class="errore">${dati.errore}</p>`;
            }
        })
        .catch((errore) => {
            risultatoDiv.innerHTML = '<p class="errore">Errore di rete, riprova.</p>';
            // Re-enable buttons for retry
            const pulsanti = risultatoDiv.querySelectorAll("button");
            pulsanti.forEach((pulsante) => {
                pulsante.disabled = false;
            });
            // Remove pointer-events guard from candidati
            const candidati = risultatoDiv.querySelectorAll(".candidato");
            candidati.forEach((candidato) => {
                candidato.style.pointerEvents = "";
            });
        });
}
