let sucheSpielerinnen = [];

document.addEventListener('DOMContentLoaded', async () => {
    const zurueckButton = document.getElementById('btn-zurueck-start');
    if (zurueckButton) {
        zurueckButton.addEventListener('click', () => {
            window.location.href = '/';
        });
    }

    const formSuche = document.getElementById('form-suche');
    if (formSuche) {
        formSuche.addEventListener('submit', async (event) => {
            event.preventDefault();
            await ladeSpieleFuerFilter();
        });
    }

    const resetButton = document.getElementById('btn-filter-reset');
    if (resetButton) {
        resetButton.addEventListener('click', async () => {
            if (formSuche) {
                formSuche.reset();
            }
            await ladeSpieleFuerFilter();
        });
    }

    await ladeSpielerinnenFuerFilter();
    await ladeSpieleFuerFilter();
});

async function ladeSpielerinnenFuerFilter() {
    const res = await fetch('/api/spieler');
    sucheSpielerinnen = await res.json();

    const select = document.getElementById('filter-spielerin');
    if (!select) {
        return;
    }

    select.innerHTML = '<option value="">Alle</option>';
    sucheSpielerinnen.forEach((spielerin) => {
        const option = document.createElement('option');
        option.value = String(spielerin.id);
        option.textContent = spielerin.name;
        select.appendChild(option);
    });
}

function baueSuchParameter() {
    const params = new URLSearchParams();

    const map = [
        ['einzelspieler_id', 'filter-spielerin'],
        ['ergebnis', 'filter-ergebnis'],
        ['spielart', 'filter-spielart'],
        ['schneider_angesagt', 'filter-schneider-angesagt'],
        ['schneider_erreicht', 'filter-schneider-erreicht'],
        ['schwarz_angesagt', 'filter-schwarz-angesagt'],
        ['schwarz_erreicht', 'filter-schwarz-erreicht'],
        ['datum_von', 'filter-datum-von'],
        ['datum_bis', 'filter-datum-bis']
    ];

    map.forEach(([apiName, elementId]) => {
        const element = document.getElementById(elementId);
        if (!element) {
            return;
        }
        const value = (element.value || '').trim();
        if (value !== '') {
            params.set(apiName, value);
        }
    });

    return params;
}

function formatiereZeitstempel(zeitstempel) {
    if (!zeitstempel) {
        return '-';
    }
    const zeit = new Date(String(zeitstempel).replace(' ', 'T'));
    if (Number.isNaN(zeit.getTime())) {
        return zeitstempel;
    }
    return zeit.toLocaleString('de-DE');
}

function renderSucheTabelle(spiele) {
    const tbody = document.querySelector('#tabelle-suche tbody');
    const leerText = document.getElementById('suche-leer');
    const trefferText = document.getElementById('suche-treffertext');

    if (!tbody || !leerText || !trefferText) {
        return;
    }

    const liste = Array.isArray(spiele) ? spiele : [];
    trefferText.textContent = `${liste.length} Spiele gefunden`;

    if (liste.length === 0) {
        tbody.innerHTML = '';
        leerText.style.display = 'block';
        return;
    }

    leerText.style.display = 'none';
    tbody.innerHTML = liste.map((spiel) => {
        const istEingepasst = spiel.spielart === 'Eingepasst';
        const istNull = spiel.spielart === 'Null';
        const schneiderText = (istEingepasst || istNull)
            ? '-'
            : (spiel.schneider_erreicht ? 'Erreicht' : 'Nicht erreicht');
        const schwarzText = (istEingepasst || istNull)
            ? '-'
            : (spiel.schwarz_angesagt
            ? (spiel.schwarz_erreicht ? 'Angesagt + erreicht' : 'Angesagt + nicht erreicht')
            : (spiel.schwarz_erreicht ? 'Erreicht' : 'Nicht erreicht'));
        const ergebnisText = istEingepasst
            ? 'Eingepasst'
            : (spiel.gewonnen ? 'Gewonnen' : 'Verloren');
        return `
            <tr>
                <td>${formatiereZeitstempel(spiel.zeitstempel)}</td>
                <td>${spiel.einzelspieler_name || 'Eingepasst'}</td>
                <td>${spiel.spielart || '-'}</td>
                <td>${spiel.spielwert ?? ''}</td>
                <td>${ergebnisText}</td>
                <td>${schneiderText}</td>
                <td>${schwarzText}</td>
            </tr>
        `;
    }).join('');
}

async function ladeSpieleFuerFilter() {
    const params = baueSuchParameter();
    const suffix = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`/api/spiele/suche${suffix}`);
    const spiele = await res.json();
    renderSucheTabelle(spiele);
}
