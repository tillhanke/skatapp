// --- Globale Variablen (State) ---
let alleSpielerinnen = [];
let aktiveIDs = [];
let geberIndex = 0; // Wer in der Liste der Aktiven gibt gerade
let gezogenesReihenfolgeElement = null; // Für Drag & Drop der Sitzreihenfolge
let aktuellesSpielDraft = null; // Zwischenspeicher für die Bestätigungs-Übersicht

// --- Initialisierung ---
document.addEventListener('DOMContentLoaded', () => {
    ladeSpielerinnen();
    fuelleReizwerte();
    initialisiereSpielartUI();
    initialisiereExtraAbhaengigkeiten();
    initialisiereReihenfolgeDragDrop();

    const undoButton = document.getElementById('btn-undo-last');
    if (undoButton) {
        undoButton.addEventListener('click', undoLetztesSpiel);
    }

    // Event-Listener für den Start-Button
    document.getElementById('btn-start').addEventListener('click', startePartie);

    const btnDashboardOnly = document.getElementById('btn-dashboard-only');
    if (btnDashboardOnly) {
        btnDashboardOnly.addEventListener('click', zeigeNurDashboard);
    }

    const btnRefreshStand = document.getElementById('btn-refresh-stand');
    if (btnRefreshStand) {
        btnRefreshStand.addEventListener('click', () => ladeStand());
    }
    
    // Event-Listener für das Formular
    document.getElementById('form-spiel').addEventListener('submit', speichereSpiel);

    // Event-Listener für das Bestätigungs-Modal
    const previewCancel = document.getElementById('btn-preview-cancel');
    const previewConfirm = document.getElementById('btn-preview-confirm');
    if (previewCancel) {
        previewCancel.addEventListener('click', abbrecheSpielVorschau);
    }
    if (previewConfirm) {
        previewConfirm.addEventListener('click', bestaetigeUndSpeichereSpiel);
    }
});

// --- Funktionen ---

async function ladeSpielerinnen() {
    const res = await fetch('/api/spieler');
    alleSpielerinnen = await res.json();
    
    const container = document.getElementById('spieler-checkboxen');
    container.innerHTML = '';
    
    alleSpielerinnen.forEach(s => {
        const label = document.createElement('label');
        label.innerHTML = `<input type="checkbox" value="${s.id}" class="spieler-opt"> ${s.name} `;
        container.appendChild(label);
    });

    container.addEventListener('change', () => {
        const gewaehlt = document.querySelectorAll('.spieler-opt:checked').length;
        document.getElementById('btn-start').disabled = (gewaehlt < 3 || gewaehlt > 5);
        syncReihenfolgeListeMitAuswahl();
    });
}

function ermittleAktiveIDsAusStartAuswahl() {
    const gewaehlteCheckboxen = document.querySelectorAll('.spieler-opt:checked');
    const gewaehltIDs = Array.from(gewaehlteCheckboxen).map(cb => parseInt(cb.value));

    if (gewaehltIDs.length < 3 || gewaehltIDs.length > 5) {
        return null;
    }

    let idsAusListe = ermittleAktiveIDsAusReihenfolge();

    const setListe = new Set(idsAusListe);
    const istKonsistent =
        idsAusListe.length === gewaehltIDs.length &&
        gewaehltIDs.every(id => setListe.has(id));

    if (!istKonsistent) {
        const liste = document.getElementById('spieler-reihenfolge');
        if (liste) {
            liste.innerHTML = '';
            gewaehltIDs.forEach(id => {
                const li = document.createElement('li');
                const spielerin = alleSpielerinnen.find(p => p.id === id);
                li.textContent = spielerin ? spielerin.name : `Spielerin ${id}`;
                li.dataset.id = String(id);
                li.draggable = true;
                liste.appendChild(li);
            });
        }
        idsAusListe = gewaehltIDs.slice();
    }

    return idsAusListe;
}

function startePartie() {
    const ids = ermittleAktiveIDsAusStartAuswahl();
    if (!ids) {
        return;
    }

    aktiveIDs = ids;

    // UI umschalten
    document.getElementById('setup-bereich').style.display = 'none';
    document.getElementById('spiel-bereich').style.display = 'block';
    document.getElementById('dashboard-bereich').style.display = 'block';

    // Einzelspieler-Dropdown initial für die aktuellen aktiven Spielerinnen füllen
    aktualisiereEinzelspielerDropdown();

    aktualisiereAnzeige();
    ladeStand();
}

function zeigeNurDashboard() {
    document.getElementById('setup-bereich').style.display = 'none';
    document.getElementById('spiel-bereich').style.display = 'none';
    document.getElementById('dashboard-bereich').style.display = 'block';

    ladeStand();
}

function aktualisiereAnzeige() {
    // Wer gibt?
    const geberID = aktiveIDs[geberIndex];
    const geberName = alleSpielerinnen.find(p => p.id === geberID).name;
    document.getElementById('anzeige-geber').textContent = geberName;
}

function berechneAktiveSpielerinnen() {
    const anzahl = aktiveIDs.length;
    const geberId = aktiveIDs[geberIndex];

    if (anzahl === 3) {
        return {
            aktiveDreiIds: aktiveIDs.slice(),
            aussetzendeIds: [],
            geberId: geberId
        };
    }

    if (anzahl === 4) {
        const aktiveDreiIds = aktiveIDs.filter((id, index) => index !== geberIndex);
        const aussetzendeIds = [geberId];
        return { aktiveDreiIds, aussetzendeIds, geberId };
    }

    if (anzahl === 5) {
        const vorspielerinIndex = (geberIndex - 1 + anzahl) % anzahl;
        const aussetzendeIds = [];
        aussetzendeIds.push(geberId);
        aussetzendeIds.push(aktiveIDs[vorspielerinIndex]);

        const aussetzendeSet = new Set(aussetzendeIds);
        const aktiveDreiIds = aktiveIDs.filter(id => !aussetzendeSet.has(id));
        return { aktiveDreiIds, aussetzendeIds, geberId };
    }

    // Fallback: falls etwas inkonsistent ist, alle als aktiv betrachten
    return {
        aktiveDreiIds: aktiveIDs.slice(),
        aussetzendeIds: [],
        geberId: geberId
    };
}

function aktualisiereEinzelspielerDropdown() {
    const select = document.getElementById('einzelspieler');
    if (!select) return;

    const { aktiveDreiIds } = berechneAktiveSpielerinnen();

    select.innerHTML = '<option value="">-- Eingepasst --</option>';
    aktiveDreiIds.forEach(id => {
        const spielerin = alleSpielerinnen.find(p => p.id === id);
        if (spielerin) {
            select.innerHTML += `<option value="${id}">${spielerin.name}</option>`;
        }
    });

    // Standardmäßig auf Eingepasst zurücksetzen
    select.value = "";
}

async function speichereSpiel(e) {
    e.preventDefault();
    
    const spielerSelect = document.getElementById('einzelspieler');
    const spielerID = spielerSelect.value;
    const spielartSelect = document.getElementById('spielart');
    const aktuelleSpielart = spielerID === "" ? "Eingepasst" : spielartSelect.value;
    const mitOhneFaktor = parseInt(document.querySelector('input[name="mit_ohne"]:checked').value);
    const spitzenZahl = parseInt(document.getElementById('spitzen').value);
    const nullErgebnis = document.querySelector('input[name="null_gewonnen"]:checked');
    const schwarzAngesagtCheckbox = document.getElementById('extra-schwarz-angesagt');
    const schwarzAngesagtErgebnis = document.querySelector('input[name="schwarz_angesagt_gewonnen"]:checked');
    const schwarzGewonnenCheckbox = document.getElementById('schwarz-gewonnen-checkbox');

    const { aktiveDreiIds } = berechneAktiveSpielerinnen();

    // Sicherheitsnetz: Einzelspielerin darf nur eine der aktiven Drei sein
    let einzelspielerIdNum = null;
    if (spielerID !== "") {
        const parsed = parseInt(spielerID);
        if (!aktiveDreiIds.includes(parsed)) {
            // Ungültige Auswahl -> auf Eingepasst zurücksetzen
            spielerSelect.value = "";
        } else {
            einzelspielerIdNum = parsed;
        }
    }

    let augenWert;
    let schwarzErreichtWert = 0;

    if (aktuelleSpielart === "Null") {
        // Bei Nullspielen: 0 = gewonnen, 1 = verloren
        const hatGewonnen = !nullErgebnis || nullErgebnis.value === 'ja';
        augenWert = hatGewonnen ? 0 : 1;
        schwarzErreichtWert = 0;
    } else if (aktuelleSpielart === "Eingepasst") {
        // Eingepasste Spiele haben keine Augen und kein Schwarz
        augenWert = 0;
        schwarzErreichtWert = 0;
    } else if (schwarzAngesagtCheckbox && schwarzAngesagtCheckbox.checked) {
        // Schwarz angesagt: nur gewonnen/verloren auswählen, Augen automatisch setzen
        const hatSchwarzGewonnen =
            !schwarzAngesagtErgebnis || schwarzAngesagtErgebnis.value === 'ja';
        augenWert = hatSchwarzGewonnen ? 120 : 0;
        schwarzErreichtWert = hatSchwarzGewonnen ? 1 : 0;
    } else {
        // Normale Spiele ohne Schwarz-Ansage: Augen manuell, optional Schwarz gewonnen
        augenWert = spielerID === "" ? 0 : (parseInt(document.getElementById('augen').value) || 0);
        const hatSchwarzGewonnen =
            schwarzGewonnenCheckbox && schwarzGewonnenCheckbox.checked;
        schwarzErreichtWert = hatSchwarzGewonnen ? 1 : 0;
    }
    
    const daten = {
        aktive_spieler_ids: aktiveDreiIds.join(','),
        geber_id: aktiveIDs[geberIndex],
        einzelspieler_id: spielerSelect.value === "" ? null : (einzelspielerIdNum ?? parseInt(spielerSelect.value)),
        spielart: aktuelleSpielart,
        reizwert: parseInt(document.getElementById('reizwert').value),
        spitzen: spitzenZahl * mitOhneFaktor,
        hand: document.getElementById('extra-hand').checked ? 1 : 0,
        ouvert: document.getElementById('extra-ouvert').checked ? 1 : 0,
        schneider_angesagt: document.getElementById('extra-schneider-angesagt').checked ? 1 : 0,
        schwarz_angesagt: document.getElementById('extra-schwarz-angesagt').checked ? 1 : 0,
        schwarz_erreicht: schwarzErreichtWert,
        augen: augenWert
    };

    // Daten nur zwischenspeichern und Bestätigungs-Übersicht anzeigen
    aktuellesSpielDraft = daten;
    zeigeSpielVorschau(daten);
}

async function ladeStand() {
    const res = await fetch('/api/stand');
    const daten = await res.json();
    
    // Tabelle Punktestand
    const tbodyStand = document.querySelector('#tabelle-stand tbody');
    tbodyStand.innerHTML = daten.punktestand
        .map(s => `
            <tr>
                <td>${s.name}</td>
                <td>${s.gesamtpunkte}</td>
                <td>${s.gespielte_spiele}</td>
                <td>${s.gesamtspiele}</td>
            </tr>
        `)
        .join('');
        
    // Tabelle Historie
    const tbodyHist = document.querySelector('#tabelle-historie tbody');
    tbodyHist.innerHTML = daten.historie
        .map(h => `
            <tr>
                <td>${h.einzelspieler_name}</td>
                <td>${h.gegnerinnen || ''}</td>
                <td>${h.spielart}</td>
                <td>${h.spielwert}</td>
            </tr>
        `)
        .join('');

    // Undo-Button entsprechend Backend-Info aktivieren/deaktivieren
    const undoButton = document.getElementById('btn-undo-last');
    if (undoButton) {
        if (typeof daten.undo_moeglich === 'boolean') {
            undoButton.disabled = !daten.undo_moeglich;
        } else {
            // Fallback: erlaubt Undo, solange es mindestens ein Spiel in der Historie gibt
            undoButton.disabled = !(daten.historie && daten.historie.length > 0);
        }
    }
}

function zeigeSpielVorschau(daten) {
    const overlay = document.getElementById('spiel-preview-overlay');
    const body = document.getElementById('spiel-preview-body');
    if (!overlay || !body) {
        return;
    }

    const einzelName = daten.einzelspieler_id === null
        ? 'Eingepasst'
        : (alleSpielerinnen.find(p => p.id === daten.einzelspieler_id)?.name || `Spielerin ${daten.einzelspieler_id}`);

    const spitzenAnzahl = Math.abs(daten.spitzen || 0);
    const mitOhneText = (daten.spitzen || 0) >= 0 ? 'mit' : 'ohne';

    const extras = [];
    if (daten.hand) extras.push('Hand');
    if (daten.ouvert) extras.push('Ouvert');
    if (daten.schneider_angesagt) extras.push('Schneider angesagt');
    if (daten.schwarz_angesagt) extras.push('Schwarz angesagt');
    if (daten.schwarz_erreicht) extras.push('Schwarz erreicht');

    let augenText = '-';
    if (daten.spielart === 'Null') {
        augenText = daten.augen === 0 ? 'Null gewonnen' : 'Null verloren';
    } else if (daten.spielart === 'Eingepasst') {
        augenText = 'Keine Augen (eingepasst)';
    } else if (daten.schwarz_angesagt) {
        augenText = daten.schwarz_erreicht ? 'Schwarz gewonnen' : 'Schwarz nicht erreicht';
    } else {
        augenText = `${daten.augen} Augen`;
    }

    const geberID = daten.geber_id;
    const geberName = alleSpielerinnen.find(p => p.id === geberID)?.name || `Spielerin ${geberID}`;

    body.innerHTML = `
        <dl>
            <dt>Geberin</dt>
            <dd>${geberName}</dd>
            <dt>Einzelspielerin</dt>
            <dd>${einzelName}</dd>
            <dt>Spielart</dt>
            <dd>${daten.spielart}</dd>
            <dt>Reizwert</dt>
            <dd>${daten.reizwert}</dd>
            <dt>Spitzen</dt>
            <dd>${mitOhneText} ${spitzenAnzahl}</dd>
            <dt>Extras</dt>
            <dd>${extras.length ? extras.join(', ') : 'Keine'}</dd>
            <dt>Ergebnis / Augen</dt>
            <dd>${augenText}</dd>
        </dl>
        <p style="margin-top: 10px;">
            Die genaue Punktewertung siehst du nach dem Speichern im Dashboard.
        </p>
    `;

    overlay.style.display = 'flex';
}

function abbrecheSpielVorschau() {
    const overlay = document.getElementById('spiel-preview-overlay');
    if (overlay) {
        overlay.style.display = 'none';
    }
}

async function bestaetigeUndSpeichereSpiel() {
    if (!aktuellesSpielDraft) {
        abbrecheSpielVorschau();
        return;
    }

    const overlay = document.getElementById('spiel-preview-overlay');
    if (overlay) {
        overlay.style.display = 'none';
    }

    const res = await fetch('/api/spiel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(aktuellesSpielDraft)
    });

    if (res.ok) {
        // Geber weiterrücken
        geberIndex = (geberIndex + 1) % aktiveIDs.length;
        document.getElementById('form-spiel').reset();
        aktuellesSpielDraft = null;
        aktualisiereAnzeige();
        aktualisiereEinzelspielerDropdown();
        ladeStand();
    } else {
        window.alert('Fehler beim Speichern des Spiels.');
    }
}

async function undoLetztesSpiel() {
    const bestaetigt = window.confirm('Letztes Spiel wirklich löschen?');
    if (!bestaetigt) {
        return;
    }

    const res = await fetch('/api/spiel/undo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    });

    const undoButton = document.getElementById('btn-undo-last');

    if (res.ok) {
        const daten = await res.json();

        const geberId = daten && typeof daten.geber_id === 'number' ? daten.geber_id : null;

        if (geberId !== null && Array.isArray(aktiveIDs) && aktiveIDs.length > 0) {
            const index = aktiveIDs.indexOf(geberId);
            if (index !== -1) {
                geberIndex = index;
            } else {
                geberIndex = (geberIndex - 1 + aktiveIDs.length) % aktiveIDs.length;
            }
        } else if (Array.isArray(aktiveIDs) && aktiveIDs.length > 0) {
            geberIndex = (geberIndex - 1 + aktiveIDs.length) % aktiveIDs.length;
        }

        aktualisiereAnzeige();
        await ladeStand();

        if (undoButton) {
            undoButton.disabled = true;
        }
    } else {
        let fehlerNachricht = 'Fehler beim Zurücknehmen des letzten Spiels.';
        if (res.status === 400 || res.status === 409) {
            try {
                const daten = await res.json();
                if (daten && daten.error) {
                    fehlerNachricht = daten.error;
                }
            } catch {
                // Ignorieren, Standardmeldung verwenden
            }
        }

        if (undoButton) {
            undoButton.disabled = true;
        }

        window.alert(fehlerNachricht);
    }
}

function ermittleAktiveIDsAusReihenfolge() {
    const liste = document.getElementById('spieler-reihenfolge');
    if (!liste) return [];
    const lis = Array.from(liste.querySelectorAll('li'));
    return lis.map(li => parseInt(li.dataset.id));
}

function syncReihenfolgeListeMitAuswahl() {
    const liste = document.getElementById('spieler-reihenfolge');
    if (!liste) return;

    const gewaehltIDs = Array.from(document.querySelectorAll('.spieler-opt:checked'))
        .map(cb => parseInt(cb.value));

    const vorhandeneLis = Array.from(liste.querySelectorAll('li'));

    // Einträge entfernen, die nicht mehr ausgewählt sind
    vorhandeneLis.forEach(li => {
        const id = parseInt(li.dataset.id);
        if (!gewaehltIDs.includes(id)) {
            li.remove();
        }
    });

    const aktuelleIDs = new Set(
        Array.from(liste.querySelectorAll('li')).map(li => parseInt(li.dataset.id))
    );

    // Neu ausgewählte Spielerinnen am Ende hinzufügen, bestehende Reihenfolge beibehalten
    gewaehltIDs.forEach(id => {
        if (!aktuelleIDs.has(id)) {
            const li = document.createElement('li');
            const spielerin = alleSpielerinnen.find(p => p.id === id);
            li.textContent = spielerin ? spielerin.name : `Spielerin ${id}`;
            li.dataset.id = String(id);
            li.draggable = true;
            liste.appendChild(li);
        }
    });
}

function initialisiereReihenfolgeDragDrop() {
    const liste = document.getElementById('spieler-reihenfolge');
    if (!liste) return;

    // --- Maus / Desktop Drag & Drop ---
    liste.addEventListener('dragstart', (event) => {
        const li = event.target && event.target.closest('li');
        if (!li) return;
        gezogenesReihenfolgeElement = li;
        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
        }
    });

    liste.addEventListener('dragover', (event) => {
        event.preventDefault();
        const li = event.target && event.target.closest('li');
        if (!li || li === gezogenesReihenfolgeElement) return;

        const bounding = li.getBoundingClientRect();
        const offset = event.clientY - bounding.top;

        if (offset > bounding.height / 2) {
            li.after(gezogenesReihenfolgeElement);
        } else {
            li.before(gezogenesReihenfolgeElement);
        }
    });

    ['drop', 'dragend'].forEach(eventName => {
        liste.addEventListener(eventName, (event) => {
            event.preventDefault();
            gezogenesReihenfolgeElement = null;
        });
    });

    // --- Touch-Unterstützung für Mobilgeräte ---
    // Viele Mobile-Browser unterstützen das native HTML5-Drag-&-Drop nicht.
    // Daher simulieren wir das Verschieben über Touch-Events.
    let touchAktiv = false;

    liste.addEventListener('touchstart', (event) => {
        const touch = event.touches[0];
        if (!touch) return;

        const li = event.target && event.target.closest('li');
        if (!li) return;

        gezogenesReihenfolgeElement = li;
        touchAktiv = true;

        // Verhindert, dass der Browser scrollt statt zu „ziehen“
        event.preventDefault();
    }, { passive: false });

    liste.addEventListener('touchmove', (event) => {
        if (!touchAktiv || !gezogenesReihenfolgeElement) return;

        const touch = event.touches[0];
        if (!touch) return;

        // Element unter dem Finger ermitteln
        const zielElement = document.elementFromPoint(touch.clientX, touch.clientY);
        if (!zielElement) return;

        const li = zielElement.closest('#spieler-reihenfolge li');
        if (!li || li === gezogenesReihenfolgeElement) return;

        const bounding = li.getBoundingClientRect();
        const offset = touch.clientY - bounding.top;

        if (offset > bounding.height / 2) {
            li.after(gezogenesReihenfolgeElement);
        } else {
            li.before(gezogenesReihenfolgeElement);
        }

        event.preventDefault();
    }, { passive: false });

    const touchEndHandler = (event) => {
        if (event) {
            event.preventDefault();
        }
        touchAktiv = false;
        gezogenesReihenfolgeElement = null;
    };

    liste.addEventListener('touchend', touchEndHandler, { passive: false });
    liste.addEventListener('touchcancel', touchEndHandler, { passive: false });
}

function fuelleReizwerte() {
    // Alle gültigen Skat-Reizwerte (inkl. Nullspiele 23, 35, 46, 59)
    const moeglicheWerte = [
        18, 20, 22, 23, 24, 27, 30, 33, 35, 36, 40, 44, 45, 46, 48, 50, 
        54, 55, 59, 60, 63, 66, 70, 72, 77, 80, 81, 84, 88, 90, 96, 99, 
        100, 108, 110, 120, 132, 144, 156, 168, 192, 216, 240, 264
    ];
    
    const select = document.getElementById('reizwert');
    moeglicheWerte.forEach(wert => {
        select.innerHTML += `<option value="${wert}">${wert}</option>`;
    });
}

function initialisiereSpielartUI() {
    const spielartSelect = document.getElementById('spielart');
    if (!spielartSelect) return;

    function aktualisiereExtrasFuerSpielart() {
        const istNullSpiel = spielartSelect.value === 'Null';
        const istGrandSpiel = spielartSelect.value === 'Grand';

        const spitzenContainer = document.getElementById('spitzen-container');
        const spitzenSelect = document.getElementById('spitzen');
        const schneiderCheckbox = document.getElementById('extra-schneider-angesagt');
        const schwarzCheckbox = document.getElementById('extra-schwarz-angesagt');
        const ouvertCheckbox = document.getElementById('extra-ouvert');
        const augenContainer = document.getElementById('augen-container');
        const nullErgebnisContainer = document.getElementById('null-ergebnis-container');
        const schwarzCheckboxContainer = document.getElementById('schwarz-checkbox-container');
        const schwarzErgebnisContainer = document.getElementById('schwarz-ergebnis-container');

        const schneiderLabel = schneiderCheckbox ? schneiderCheckbox.parentElement : null;
        const schwarzLabel = schwarzCheckbox ? schwarzCheckbox.parentElement : null;

        if (istNullSpiel) {
            // Bei Nullspielen dürfen Schneider/Schwarz nicht aktiv sein,
            // insbesondere nicht, wenn Ouvert gewählt wurde.
            if (schneiderCheckbox) schneiderCheckbox.checked = false;
            if (schwarzCheckbox) schwarzCheckbox.checked = false;

            if (spitzenContainer) spitzenContainer.style.display = 'none';
            if (schneiderLabel) schneiderLabel.style.display = 'none';
            if (schwarzLabel) schwarzLabel.style.display = 'none';

            if (augenContainer) augenContainer.style.display = 'none';
            if (nullErgebnisContainer) nullErgebnisContainer.style.display = 'block';
            if (schwarzCheckboxContainer) schwarzCheckboxContainer.style.display = 'none';
            if (schwarzErgebnisContainer) schwarzErgebnisContainer.style.display = 'none';
        } else {
            if (spitzenContainer) spitzenContainer.style.display = '';
            if (spitzenSelect) {
                // Optionen je nach Spielart einschränken:
                // - Grand: nur 1–4 Spitzen
                // - andere Farbspiele: 1–11 Spitzen
                const maxSpitzen = istGrandSpiel ? 4 : 11;
                const aktuelleWahl = parseInt(spitzenSelect.value) || 1;

                // Dropdown-Inhalt neu aufbauen
                spitzenSelect.innerHTML = '';
                for (let i = 1; i <= maxSpitzen; i++) {
                    const opt = document.createElement('option');
                    opt.value = String(i);
                    opt.textContent = String(i);
                    spitzenSelect.appendChild(opt);
                }

                // Vorherige Auswahl beibehalten, wenn noch gültig, sonst auf 1 setzen
                if (aktuelleWahl >= 1 && aktuelleWahl <= maxSpitzen) {
                    spitzenSelect.value = String(aktuelleWahl);
                } else {
                    spitzenSelect.value = '1';
                }
            }
            if (schneiderLabel) schneiderLabel.style.display = '';
            if (schwarzLabel) schwarzLabel.style.display = '';

            // Standard: Augenfeld sichtbar
            if (augenContainer) augenContainer.style.display = 'block';
            if (nullErgebnisContainer) nullErgebnisContainer.style.display = 'none';

            // Bei Nicht-Null-Spielen:
            // - ohne Schwarz-Ansage: Augen + Checkbox „Schwarz gewonnen“
            // - mit Schwarz-Ansage: nur Ergebnis-Block für Schwarz-angesagtes Spiel
            if (schwarzCheckbox && schwarzCheckbox.checked) {
                if (augenContainer) augenContainer.style.display = 'none';
                if (schwarzCheckboxContainer) schwarzCheckboxContainer.style.display = 'none';
                if (schwarzErgebnisContainer) schwarzErgebnisContainer.style.display = 'block';
            } else {
                if (augenContainer) augenContainer.style.display = 'block';
                if (schwarzCheckboxContainer) schwarzCheckboxContainer.style.display = 'block';
                if (schwarzErgebnisContainer) schwarzErgebnisContainer.style.display = 'none';
            }
        }
    }

    spielartSelect.addEventListener('change', aktualisiereExtrasFuerSpielart);
    // Initialer Zustand beim Laden
    aktualisiereExtrasFuerSpielart();
}

function initialisiereExtraAbhaengigkeiten() {
    const schneiderCheckbox = document.getElementById('extra-schneider-angesagt');
    const schwarzCheckbox = document.getElementById('extra-schwarz-angesagt');
    const ouvertCheckbox = document.getElementById('extra-ouvert');
    const spielartSelect = document.getElementById('spielart');
    const handCheckbox = document.getElementById('extra-hand');
    const augenContainer = document.getElementById('augen-container');
    const nullErgebnisContainer = document.getElementById('null-ergebnis-container');
    const schwarzCheckboxContainer = document.getElementById('schwarz-checkbox-container');
    const schwarzErgebnisContainer = document.getElementById('schwarz-ergebnis-container');

    if (!schneiderCheckbox || !schwarzCheckbox || !ouvertCheckbox || !handCheckbox || !spielartSelect) return;

    function istNullSpielAktuell() {
        return spielartSelect.value === 'Null';
    }

    // Wenn Schneider angesagt wird, muss Hand automatisch aktiv sein
    schneiderCheckbox.addEventListener('change', () => {
        if (schneiderCheckbox.checked) {
            handCheckbox.checked = true;
        }
    });

    // Wenn Schwarz angesagt wird, muss Schneider automatisch auch aktiv sein
    schwarzCheckbox.addEventListener('change', () => {
        if (istNullSpielAktuell()) {
            // Bei Null-Spielen gibt es kein Schneider/Schwarz
            schwarzCheckbox.checked = false;
            schneiderCheckbox.checked = false;
            return;
        }

        if (schwarzCheckbox.checked) {
            schneiderCheckbox.checked = true;
            handCheckbox.checked = true;

            // Bei Schwarz-Ansage: nur Schwarz-Ergebnis anzeigen, Augenfeld/Checkbox ausblenden
            if (augenContainer) augenContainer.style.display = 'none';
            if (nullErgebnisContainer) nullErgebnisContainer.style.display = 'none';
            if (schwarzCheckboxContainer) schwarzCheckboxContainer.style.display = 'none';
            if (schwarzErgebnisContainer) schwarzErgebnisContainer.style.display = 'block';
        }
        else {
            // Ohne Schwarz-Ansage: Augenfeld + Checkbox „Schwarz gewonnen“, kein Schwarz-Ansage-Ergebnisblock
            if (!istNullSpielAktuell()) {
                if (augenContainer) augenContainer.style.display = 'block';
                if (schwarzCheckboxContainer) schwarzCheckboxContainer.style.display = 'block';
                if (schwarzErgebnisContainer) schwarzErgebnisContainer.style.display = 'none';
            }
        }
    });

    // Wenn Ouvert gesetzt wird, müssen Schwarz + Schneider automatisch aktiv sein
    ouvertCheckbox.addEventListener('change', () => {
        if (istNullSpielAktuell()) {
            // Null Ouvert hat feste Wertung ohne Schneider/Schwarz
            schwarzCheckbox.checked = false;
            schneiderCheckbox.checked = false;
            return;
        }

        if (ouvertCheckbox.checked) {
            schwarzCheckbox.checked = true;
            schneiderCheckbox.checked = true;
            handCheckbox.checked = true;

            // Darstellung für Schwarz-Ansage aktualisieren,
            // damit der Gewonnen/Verloren-Container sofort erscheint
            const event = new Event('change');
            schwarzCheckbox.dispatchEvent(event);
        }
    });
}
