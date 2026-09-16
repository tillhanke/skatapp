// --- Remote-Play: Lobby, Tisch und Live-Aktualisierung ---------------------
//
// Der Server ist die einzige Wahrheit. Dieses Skript schickt Aktionen hin und
// zeichnet, was zurueckkommt - es kennt bewusst keine Spielregeln und keine
// fremden Karten.

let tischCode = null;
let eigenesToken = null;
let ereignisStrom = null;
let letzterZustand = null;
let gewaehlteDruckKarten = new Set();

const FARB_NAME = { E: 'Eichel', B: 'Blatt', H: 'Herz', S: 'Schell' };
const FARB_KLASSE = { E: 'eichel', B: 'blatt', H: 'herz', S: 'schell' };
const RANG_NAME = {
    A: 'Ass', '10': 'Zehn', K: 'König', O: 'Ober', U: 'Unter',
    '9': 'Neun', '8': 'Acht', '7': 'Sieben',
};

// Deutsches Blatt. Für Eichel und Schell gibt es keine Unicode-Zeichen
// (die bekannten Symbole gehören zum französischen Blatt), deshalb kleine
// eigene SVG-Symbole. Gefüllt wird über currentColor; die Farbe kommt aus
// der jeweiligen Kartenklasse im Stylesheet.
const FARB_SVG = {
    E: '<rect x="15" y="1.5" width="2" height="4.5" rx="1"/>'
        + '<path d="M6 12.5a10 6.5 0 0 1 20 0z"/>'
        + '<path d="M8 13.5h16c0 8-3.3 15.5-8 15.5S8 21.5 8 13.5z"/>',
    B: '<path d="M16 2C10 7.5 5 12 5 17.6c0 5 4.6 8.6 11 8.6s11-3.6 11-8.6C27 12 22 7.5 16 2z"/>'
        + '<rect x="15.1" y="24" width="1.8" height="6.5" rx="0.9"/>'
        + '<path d="M16 24.5V7.5M16 14.5l5-4M16 19l5-4M16 14.5l-5-4M16 19l-5-4"'
        + ' stroke="#fff" stroke-width="1.15" stroke-linecap="round" fill="none" opacity="0.5"/>',
    H: '<path d="M16 29S3 20 3 11.5C3 7 6.3 4 10.2 4c2.6 0 4.7 1.4 5.8 3.4'
        + 'C17.1 5.4 19.2 4 21.8 4 25.7 4 29 7 29 11.5 29 20 16 29 16 29z"/>',
    S: '<path d="M16 1a2.9 2.9 0 0 1 2.9 2.9V6h-5.8V3.9A2.9 2.9 0 0 1 16 1z"/>'
        + '<path fill-rule="evenodd" d="M16 5.6a12.2 12.2 0 1 1 0 24.4 12.2 12.2 0 0 1 0-24.4z'
        + 'm-4.6 11.1h9.2v2.4h-9.2z"/>',
};

function farbSymbol(farbe) {
    return '<svg class="farb-symbol" viewBox="0 0 32 32" aria-hidden="true">'
        + FARB_SVG[farbe] + '</svg>';
}

// --- Hilfen ----------------------------------------------------------------

function el(id) {
    return document.getElementById(id);
}

function zeige(id, sichtbar) {
    const knoten = el(id);
    if (knoten) knoten.style.display = sichtbar ? '' : 'none';
}

function tokenSchluessel(code) {
    return `skat_token_${code}`;
}

function tokenLaden(code) {
    try {
        return window.localStorage.getItem(tokenSchluessel(code));
    } catch {
        return null;
    }
}

function tokenSpeichern(code, token) {
    try {
        window.localStorage.setItem(tokenSchluessel(code), token);
    } catch {
        // Privater Modus o.Ä.: das Cookie vom Server reicht für diese Sitzung.
    }
}

function zeigeFehler(text) {
    const knoten = el('beitritt-fehler');
    if (!knoten) return;
    knoten.textContent = text || '';
    knoten.style.display = text ? 'block' : 'none';
}

function status(text) {
    const knoten = el('verbindung-status');
    if (knoten) knoten.textContent = text || '';
}

async function hole(pfad, optionen = {}) {
    const kopf = Object.assign({ 'Content-Type': 'application/json' }, optionen.headers || {});
    if (eigenesToken) kopf['X-Skat-Token'] = eigenesToken;

    const antwort = await fetch(pfad, Object.assign({}, optionen, { headers: kopf }));
    let daten = null;
    try {
        daten = await antwort.json();
    } catch {
        daten = null;
    }
    if (!antwort.ok) {
        throw new Error((daten && daten.error) || `Fehler ${antwort.status}`);
    }
    return daten;
}

// --- Karten zeichnen -------------------------------------------------------

function karteZerlegen(code) {
    return { farbe: code[0], rang: code.slice(1) };
}

function karteKnoten(code, { anklickbar = false, gewaehlt = false, gedimmt = false } = {}) {
    const { farbe, rang } = karteZerlegen(code);
    const knoten = document.createElement(anklickbar ? 'button' : 'span');
    if (anklickbar) knoten.type = 'button';

    knoten.className = `karte karte-${FARB_KLASSE[farbe]}`
        + (gewaehlt ? ' karte-gewaehlt' : '')
        + (gedimmt ? ' karte-gedimmt' : '');
    knoten.dataset.code = code;
    knoten.title = `${FARB_NAME[farbe]} ${RANG_NAME[rang] || rang}`;
    knoten.innerHTML = `<span class="karte-rang">${rang}</span>` + farbSymbol(farbe);
    return knoten;
}

function kartenIn(container, codes, optionen = {}) {
    container.innerHTML = '';
    (codes || []).forEach(code => container.appendChild(karteKnoten(code, optionen)));
}

// --- Beitritt --------------------------------------------------------------

async function tischAnlegen() {
    zeigeFehler('');
    try {
        const daten = await hole('/api/tisch', { method: 'POST' });
        window.location.search = `?code=${daten.code}`;
    } catch (fehler) {
        zeigeFehler(fehler.message);
    }
}

async function tischOeffnen(code) {
    zeigeFehler('');
    code = (code || '').trim().toUpperCase();
    if (code.length !== 6) {
        zeigeFehler('Ein Raumcode besteht aus sechs Zeichen.');
        return;
    }
    tischCode = code;
    eigenesToken = tokenLaden(code);

    let uebersicht;
    try {
        uebersicht = await hole(`/api/tisch/${code}`);
    } catch (fehler) {
        zeigeFehler(fehler.message);
        return;
    }

    // Schon einen Platz an diesem Tisch? Dann direkt verbinden.
    if (eigenesToken && uebersicht.ich) {
        verbinde();
        return;
    }

    eigenesToken = null;
    el('anzeige-beitritt-code').textContent = code;
    zeige('beitritt-code-block', false);
    zeige('beitritt-namen-block', true);

    const container = el('beitritt-namen');
    container.innerHTML = '';

    if (uebersicht.sitzend.length) {
        const sitzen = document.createElement('p');
        sitzen.className = 'hinweis';
        sitzen.textContent = 'Schon am Tisch: '
            + uebersicht.sitzend.map(s => s.name).join(', ');
        container.appendChild(sitzen);
    }

    if (uebersicht.zuschauer && uebersicht.zuschauer.length) {
        const wartend = document.createElement('p');
        wartend.className = 'hinweis';
        wartend.textContent = 'Schaut gerade zu: '
            + uebersicht.zuschauer.map(z => z.name).join(', ');
        container.appendChild(wartend);
    }

    // Abgewiesen wird niemand – aber man soll vorher wissen, worauf man sich
    // einlässt.
    const rollenhinweis = el('beitritt-rollenhinweis');
    const texte = {
        zuschauer_partie_laeuft:
            'Die Partie läuft bereits. Du kommst als Zuschauerin rein und '
            + 'spielst ab dem nächsten Spiel mit.',
        zuschauer_voll:
            'Der Tisch ist mit fünf Spielerinnen voll. Du kannst zuschauen und '
            + 'rückst nach, sobald jemand geht.',
    };
    const text = texte[uebersicht.beitritt_als];
    rollenhinweis.textContent = text || '';
    rollenhinweis.style.display = text ? 'block' : 'none';

    const reihe = document.createElement('div');
    reihe.className = 'knopfreihe';
    uebersicht.frei.forEach(spielerin => {
        const knopf = document.createElement('button');
        knopf.type = 'button';
        knopf.textContent = spielerin.name;
        knopf.addEventListener('click', () => beitreten(spielerin.id));
        reihe.appendChild(knopf);
    });
    container.appendChild(reihe);
}

async function beitreten(spielerId) {
    zeigeFehler('');
    try {
        const daten = await hole(`/api/tisch/${tischCode}/beitreten`, {
            method: 'POST',
            body: JSON.stringify({ spieler_id: spielerId }),
        });
        eigenesToken = daten.token;
        tokenSpeichern(tischCode, daten.token);
        if (daten.rolle === 'zuschauer') {
            status(daten.grund === 'voll'
                ? 'Tisch voll – du schaust zu und rückst nach, sobald jemand geht.'
                : 'Partie läuft – du schaust zu und bist ab dem nächsten Spiel dabei.');
        }
        verbinde();
    } catch (fehler) {
        zeigeFehler(fehler.message);
    }
}

// --- Live-Verbindung -------------------------------------------------------

function verbinde() {
    zeige('beitritt-bereich', false);
    if (ereignisStrom) ereignisStrom.close();

    const aufdecken = el('schalter-aufdecken') && el('schalter-aufdecken').checked;
    const pfad = `/api/tisch/${tischCode}/ereignisse`
        + `?token=${encodeURIComponent(eigenesToken)}`
        + (aufdecken ? '&aufdecken=1' : '');

    status('Verbinde …');
    ereignisStrom = new EventSource(pfad);

    ereignisStrom.addEventListener('zustand', ereignis => {
        status('');
        zeichneZustand(JSON.parse(ereignis.data));
    });
    ereignisStrom.addEventListener('ende', () => {
        status('Der Tisch wurde geschlossen.');
        ereignisStrom.close();
    });
    ereignisStrom.onerror = () => {
        // EventSource verbindet selbstständig neu.
        status('Verbindung unterbrochen – versuche erneut …');
    };
}

async function sendeAktion(name, daten) {
    try {
        await hole(`/api/tisch/${tischCode}/aktion`, {
            method: 'POST',
            body: JSON.stringify({ aktion: name, daten: daten || {} }),
        });
    } catch (fehler) {
        window.alert(fehler.message);
    }
}

// --- Zeichnen --------------------------------------------------------------

function zeichneZustand(zustand) {
    letzterZustand = zustand;

    if (zustand.phase === 'lobby') {
        zeige('lobby-bereich', true);
        zeige('tisch-bereich', false);
        zeichneLobby(zustand);
        return;
    }

    zeige('lobby-bereich', false);
    zeige('tisch-bereich', true);
    zeichneTisch(zustand);
}

function zeichneLobby(zustand) {
    el('einladung-link').value =
        `${window.location.origin}/spielen?code=${zustand.code}`;

    const liste = el('lobby-reihenfolge');
    liste.innerHTML = '';
    zustand.spieler.forEach(spielerin => {
        const eintrag = document.createElement('li');
        eintrag.textContent = spielerin.name
            + (spielerin.id === zustand.ich.id ? ' (du)' : '');
        eintrag.dataset.id = String(spielerin.id);
        eintrag.draggable = true;
        liste.appendChild(eintrag);
    });

    const anzahl = zustand.spieler.length;
    el('btn-partie-starten').disabled = anzahl < 3 || anzahl > 5;
    el('lobby-hinweis').textContent = anzahl < 3
        ? `Noch ${3 - anzahl} Spielerin(nen) nötig.`
        : `${anzahl} Spielerinnen am Tisch – es kann losgehen.`;
}

function zeichneTisch(zustand) {
    const spiel = zustand.spiel;
    const binAmZug = spiel && spiel.am_zug_id === zustand.ich.id;

    zeichneSpielerleiste(zustand);
    zeichneZuschauerleiste(zustand);

    // Statuszeile
    if (!spiel) {
        el('tisch-status').textContent = 'Warte auf das nächste Geben …';
    } else if (zustand.phase === 'pause') {
        el('tisch-status').textContent = 'Spiel beendet.';
    } else {
        const amZug = (zustand.spieler.find(s => s.id === spiel.am_zug_id) || {}).name;
        el('tisch-status').textContent = binAmZug
            ? 'Du bist am Zug.'
            : `${amZug || '–'} ist am Zug.`;
    }

    zeichneReizen(zustand, binAmZug);
    zeichneSkatUndAnsage(zustand, binAmZug);
    zeichneStich(zustand);
    zeichneBlatt(zustand, binAmZug);
    zeichneZuschauer(zustand);
    zeichneErgebnis(zustand);
    zeichneRundenTabelle(zustand);
}

function zeichneZuschauerleiste(zustand) {
    const zeile = el('tisch-zuschauer');
    const wartende = zustand.zuschauer || [];
    if (wartende.length) {
        zeile.textContent = 'Schaut zu: ' + wartende
            .map(z => z.name + (z.wartet_auf_platz ? ' (wartet auf einen Platz)' : ''))
            .join(', ');
        zeile.style.display = 'block';
    } else {
        zeile.style.display = 'none';
    }

    // Eigener Status, falls man selbst nur zuschaut.
    const eigener = el('zuschauer-eigener-status');
    if (zustand.ich.zuschauer) {
        eigener.textContent = zustand.ich.wartet_auf_platz
            ? 'Du schaust zu. Der Tisch ist voll – du rückst nach, sobald jemand geht.'
            : 'Du schaust zu und bist ab dem nächsten Spiel dabei.';
        eigener.style.display = 'block';
    } else {
        eigener.style.display = 'none';
    }
}

function zeichneSpielerleiste(zustand) {
    const container = el('tisch-spieler');
    container.innerHTML = '';
    const spiel = zustand.spiel;

    zustand.spieler.forEach(spielerin => {
        const knoten = document.createElement('div');
        const merkmale = ['spieler-chip'];
        if (spiel && spiel.am_zug_id === spielerin.id) merkmale.push('ist-am-zug');
        if (spielerin.setzt_aus) merkmale.push('setzt-aus');
        if (!spielerin.verbunden) merkmale.push('nicht-verbunden');
        knoten.className = merkmale.join(' ');

        const zusatz = [];
        if (spielerin.ist_geber) zusatz.push('gibt');
        if (spielerin.setzt_aus) zusatz.push('setzt aus');
        if (spiel && spiel.alleinspieler_id === spielerin.id) zusatz.push('allein');
        if (!spielerin.verbunden) zusatz.push('offline');

        knoten.innerHTML = `<strong>${spielerin.name}</strong>`
            + (zusatz.length ? `<span class="chip-zusatz">${zusatz.join(' · ')}</span>` : '')
            + (spiel && spiel.kartenzahl && spiel.kartenzahl[spielerin.id] !== undefined
                ? `<span class="chip-karten">${spiel.kartenzahl[spielerin.id]} Karten</span>`
                : '');

        // Nur bei tatsächlich abgerissener Verbindung und nie bei sich selbst.
        if (!spielerin.verbunden && spielerin.id !== zustand.ich.id) {
            const weg = document.createElement('button');
            weg.type = 'button';
            weg.className = 'chip-entfernen';
            weg.textContent = '\u00d7';
            weg.title = `${spielerin.name} vom Tisch nehmen`;
            weg.setAttribute('aria-label', `${spielerin.name} vom Tisch nehmen`);
            weg.addEventListener('click', () => spielerinEntfernen(spielerin));
            knoten.appendChild(weg);
        }

        container.appendChild(knoten);
    });
}

async function spielerinEntfernen(spielerin) {
    const frage = `${spielerin.name} ist offline. Vom Tisch nehmen?\n\n`
        + 'Das laufende Spiel wird verworfen und nicht gewertet. '
        + 'Danach wird sofort neu gegeben – oder es geht zurück in die Lobby, '
        + 'wenn dann weniger als drei Leute sitzen.';
    if (!window.confirm(frage)) return;
    try {
        await hole(`/api/tisch/${tischCode}/entfernen`, {
            method: 'POST',
            body: JSON.stringify({ spieler_id: spielerin.id }),
        });
    } catch (fehler) {
        window.alert(fehler.message);
    }
}

function zeichneReizen(zustand, binAmZug) {
    const spiel = zustand.spiel;
    const aktiv = spiel && spiel.phase === 'reizen';
    zeige('reiz-bereich', aktiv);
    if (!aktiv) return;

    const verlauf = el('reiz-verlauf');
    verlauf.innerHTML = (spiel.reiz_verlauf || [])
        .map(eintrag => {
            const name = (zustand.spieler.find(s => s.id === eintrag.spieler_id) || {}).name;
            const wort = { reizt: 'reizt', hoert: 'hört', passt: 'passt' }[eintrag.aktion];
            return `<span>${name} ${wort}${eintrag.aktion === 'passt' ? '' : ' ' + eintrag.wert}</span>`;
        })
        .join('');

    el('reiz-lage').textContent = spiel.reiz_gebot
        ? `Aktuelles Gebot: ${spiel.reiz_gebot}`
        : 'Noch kein Gebot.';

    const knoepfe = el('reiz-knoepfe');
    knoepfe.innerHTML = '';
    if (!binAmZug) {
        knoepfe.innerHTML = '<p class="hinweis">Warte, bis du an der Reihe bist.</p>';
        return;
    }

    if (spiel.reiz_erwartet === 'antwort') {
        knoepfe.appendChild(knopf(`Ja (${spiel.reiz_gebot})`, () => sendeAktion('hoeren')));
    } else {
        // Die nächsten sechs möglichen Reizwerte anbieten.
        (zustand.reizwerte || [])
            .filter(wert => wert > spiel.reiz_gebot)
            .slice(0, 6)
            .forEach(wert => knoepfe.appendChild(
                knopf(String(wert), () => sendeAktion('reizen', { wert }))
            ));
    }
    knoepfe.appendChild(knopf('Passe', () => sendeAktion('passen'), 'knopf-zurueckhaltend'));
}

function knopf(beschriftung, beiKlick, zusatzKlasse) {
    const knoten = document.createElement('button');
    knoten.type = 'button';
    knoten.textContent = beschriftung;
    if (zusatzKlasse) knoten.className = zusatzKlasse;
    knoten.addEventListener('click', beiKlick);
    return knoten;
}

function zeichneSkatUndAnsage(zustand, binAmZug) {
    const spiel = zustand.spiel;
    const phase = spiel && spiel.phase;

    zeige('skat-bereich', binAmZug && phase === 'skat_entscheidung');
    zeige('druecken-bereich', binAmZug && phase === 'druecken');
    zeige('ansage-bereich', binAmZug && phase === 'ansage');

    if (binAmZug && phase === 'skat_entscheidung') {
        el('anzeige-reizwert').textContent = spiel.reizwert;
    }

    if (binAmZug && phase === 'druecken') {
        kartenIn(el('anzeige-skat'), (spiel.skat || []));
        el('btn-druecken').disabled = gewaehlteDruckKarten.size !== 2;
    } else {
        gewaehlteDruckKarten.clear();
    }

    if (binAmZug && phase === 'ansage') {
        // Nach dem Aufnehmen des Skats sind Schneider, Schwarz und Ouvert
        // ausgeschlossen - beim Null bleibt Ouvert erlaubt.
        const istHand = !spiel.skat_aufgenommen;
        const istNull = el('ansage-spielart').value === 'Null';
        el('ansage-schneider').disabled = !istHand || istNull;
        el('ansage-schwarz').disabled = !istHand || istNull;
        el('ansage-ouvert').disabled = !istHand && !istNull;
        [el('ansage-schneider'), el('ansage-schwarz'), el('ansage-ouvert')]
            .forEach(feld => { if (feld.disabled) feld.checked = false; });

        el('ansage-hinweis').textContent = istHand
            ? 'Handspiel – Ansagen sind möglich. Ouvert schließt Schwarz und Schneider ein.'
            : 'Skat aufgenommen – damit ist es kein Handspiel, Ansagen entfallen.';
    }
}

function zeichneStich(zustand) {
    const spiel = zustand.spiel;
    const flaeche = el('stich-karten');
    if (!spiel) {
        flaeche.innerHTML = '';
        el('stich-info').textContent = '';
        return;
    }

    flaeche.innerHTML = '';
    (spiel.aktueller_stich || []).forEach(eintrag => {
        const name = (zustand.spieler.find(s => s.id === eintrag.spieler_id) || {}).name;
        const platz = document.createElement('div');
        platz.className = 'stich-platz';
        platz.appendChild(karteKnoten(eintrag.karte));
        const beschriftung = document.createElement('span');
        beschriftung.className = 'stich-name';
        beschriftung.textContent = name || '';
        platz.appendChild(beschriftung);
        flaeche.appendChild(platz);
    });

    const teile = [`Stich ${Math.min(spiel.stiche_anzahl + 1, 10)} von 10`];
    if (spiel.ansage) {
        const a = spiel.ansage;
        const zusatz = [
            a.hand ? 'Hand' : null,
            a.ouvert ? 'Ouvert' : null,
            a.schwarz_angesagt ? 'Schwarz angesagt' : (a.schneider_angesagt ? 'Schneider angesagt' : null),
        ].filter(Boolean);
        teile.push(`${a.spielart}${zusatz.length ? ' (' + zusatz.join(', ') + ')' : ''}`);
        teile.push(`Reizwert ${spiel.reizwert}`);
    }
    el('stich-info').textContent = teile.join(' · ');
}

function zeichneBlatt(zustand, binAmZug) {
    const spiel = zustand.spiel;
    const container = el('blatt-karten');
    // Zuschauende haben kein eigenes Blatt - der Server schickt keins.
    const eigenes = spiel && spiel.ich;

    if (!eigenes) {
        zeige('blatt-bereich', false);
        return;
    }
    zeige('blatt-bereich', true);

    const phase = spiel.phase;
    const imDruecken = binAmZug && phase === 'druecken';
    const imSpielen = binAmZug && phase === 'spielen';
    const erlaubt = new Set(eigenes.erlaubte_karten || []);

    // Beim Ansagen die Reihenfolge zur gerade gewählten Spielart zeigen,
    // damit man seinen Trumpf sieht, bevor man sich festlegt.
    let blatt = eigenes.blatt || [];
    if (phase === 'ansage' && eigenes.blatt_je_spielart) {
        blatt = eigenes.blatt_je_spielart[el('ansage-spielart').value] || blatt;
    }

    el('blatt-ueberschrift').textContent = imDruecken
        ? 'Dein Blatt – zwei Karten zum Drücken wählen'
        : 'Dein Blatt';

    container.innerHTML = '';
    blatt.forEach(code => {
        const anklickbar = imDruecken || (imSpielen && erlaubt.has(code));
        const knoten = karteKnoten(code, {
            anklickbar,
            gewaehlt: gewaehlteDruckKarten.has(code),
            gedimmt: imSpielen && !erlaubt.has(code),
        });
        if (imDruecken) {
            knoten.addEventListener('click', () => {
                if (gewaehlteDruckKarten.has(code)) {
                    gewaehlteDruckKarten.delete(code);
                } else if (gewaehlteDruckKarten.size < 2) {
                    gewaehlteDruckKarten.add(code);
                }
                zeichneZustand(letzterZustand);
            });
        } else if (imSpielen && erlaubt.has(code)) {
            knoten.addEventListener('click', () => sendeAktion('karte_spielen', { karte: code }));
        }
        container.appendChild(knoten);
    });
}

function zeichneZuschauer(zustand) {
    const darf = Boolean(zustand.darf_aufdecken);
    zeige('zuschauer-bereich', darf);
    if (!darf) return;

    const ueberschrift = el('zuschauer-bereich').querySelector('h3');
    if (ueberschrift) {
        ueberschrift.textContent = zustand.ich.zuschauer ? 'Du schaust zu' : 'Du setzt aus';
    }

    const inhalt = el('zuschauer-inhalt');
    const spiel = zustand.spiel;

    if (!zustand.aufgedeckt) {
        inhalt.innerHTML = '<p class="hinweis">Karten sind verdeckt. '
            + 'Mit dem Schalter oben siehst du alle Blätter.</p>';
        return;
    }

    inhalt.innerHTML = '';
    Object.entries(spiel.alle_blaetter || {}).forEach(([spielerId, karten]) => {
        const name = (zustand.spieler.find(s => String(s.id) === String(spielerId)) || {}).name;
        const block = document.createElement('div');
        block.className = 'zuschauer-block';
        block.innerHTML = `<h4>${name || spielerId}</h4>`;
        const reihe = document.createElement('div');
        reihe.className = 'kartenhand';
        kartenIn(reihe, karten);
        block.appendChild(reihe);
        inhalt.appendChild(block);
    });

    if (spiel.skat && spiel.skat.length) {
        const block = document.createElement('div');
        block.className = 'zuschauer-block';
        block.innerHTML = '<h4>Skat</h4>';
        const reihe = document.createElement('div');
        reihe.className = 'kartenhand';
        kartenIn(reihe, spiel.skat);
        block.appendChild(reihe);
        inhalt.appendChild(block);
    }

    if (spiel.alle_stiche && spiel.alle_stiche.length) {
        const block = document.createElement('div');
        block.className = 'zuschauer-block';
        block.innerHTML = '<h4>Gespielte Stiche</h4>';
        spiel.alle_stiche.forEach((stich, nummer) => {
            const name = (zustand.spieler.find(s => s.id === stich.gewinner_id) || {}).name;
            const zeile = document.createElement('div');
            zeile.className = 'zuschauer-stich';
            zeile.innerHTML = `<span class="stich-nummer">${nummer + 1}.</span>`;
            const reihe = document.createElement('span');
            reihe.className = 'kartenzeile';
            kartenIn(reihe, stich.karten);
            zeile.appendChild(reihe);
            const wer = document.createElement('span');
            wer.className = 'stich-name';
            wer.textContent = `→ ${name || ''}`;
            zeile.appendChild(wer);
            block.appendChild(zeile);
        });
        inhalt.appendChild(block);
    }
}

function zeichneErgebnis(zustand) {
    const fertig = zustand.phase === 'pause';
    zeige('ergebnis-bereich', fertig);
    if (!fertig) return;

    const zurueck = el('btn-spiel-zuruecknehmen');
    if (zurueck) zurueck.disabled = !zustand.undo_moeglich;

    const letztes = (zustand.ergebnisse || [])[zustand.ergebnisse.length - 1];
    if (!letztes) return;

    const zeile = letztes.zeile;
    const name = (zustand.spieler.find(s => s.id === letztes.alleinspieler_id) || {}).name;

    if (zeile.spielart === 'Eingepasst') {
        el('ergebnis-inhalt').innerHTML =
            '<p>Es wurde eingepasst – null Punkte für alle.</p>';
        return;
    }

    const mitOhne = zeile.spitzen >= 0 ? 'mit' : 'ohne';
    const teile = [
        `<p><strong>${name}</strong> hat ${zeile.spielart} `
        + `${mitOhne} ${Math.abs(zeile.spitzen)} gespielt `
        + `und <strong>${letztes.gewonnen ? 'gewonnen' : 'verloren'}</strong>.</p>`,
        `<p class="hinweis">Reizwert ${zeile.reizwert} · `
        + (zeile.spielart === 'Null'
            ? `${letztes.stiche_alleinspieler} Stiche`
            : `${letztes.augen_alleinspieler} Augen · ${letztes.stiche_alleinspieler} Stiche`)
        + `${letztes.ueberreizt ? ' · <strong>überreizt</strong>' : ''}</p>`,
        `<p class="ergebnis-punkte">${zeile.spielwert > 0 ? '+' : ''}${zeile.spielwert} Punkte</p>`,
    ];
    el('ergebnis-inhalt').innerHTML = teile.join('');
}

function zeichneRundenTabelle(zustand) {
    const koerper = el('tabelle-runde').querySelector('tbody');
    koerper.innerHTML = (zustand.ergebnisse || [])
        .slice()
        .reverse()
        .map(eintrag => {
            const zeile = eintrag.zeile;
            const name = (zustand.spieler.find(s => s.id === eintrag.alleinspieler_id) || {}).name;
            return `<tr>
                <td>${zeile.spielart === 'Eingepasst' ? '–' : (name || '')}</td>
                <td>${zeile.spielart}</td>
                <td>${zeile.spielart === 'Null' || zeile.spielart === 'Eingepasst'
                    ? '–' : eintrag.augen_alleinspieler}</td>
                <td>${zeile.spielwert}</td>
            </tr>`;
        })
        .join('');
}

// --- Start -----------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    el('btn-zurueck-start').addEventListener('click', () => {
        // Der Platz am Tisch bleibt bestehen - über den Einladungslink
        // kommt man zurück. Trotzdem nachfragen, wenn gerade gespielt wird:
        // die anderen warten dann womöglich auf einen Zug.
        const imSpiel = letzterZustand && letzterZustand.phase === 'spiel';
        if (imSpiel) {
            const frage = 'Zurück zur Startseite?\n\n'
                + 'Du bleibst am Tisch sitzen und kannst über den Einladungslink '
                + 'zurückkommen – die anderen warten so lange auf dich.';
            if (!window.confirm(frage)) return;
        }
        window.location.href = '/';
    });

    el('btn-tisch-anlegen').addEventListener('click', tischAnlegen);
    el('btn-code-oeffnen').addEventListener('click', () => tischOeffnen(el('eingabe-code').value));
    el('eingabe-code').addEventListener('keydown', ereignis => {
        if (ereignis.key === 'Enter') tischOeffnen(el('eingabe-code').value);
    });

    el('btn-link-kopieren').addEventListener('click', async () => {
        const feld = el('einladung-link');
        try {
            await navigator.clipboard.writeText(feld.value);
            el('btn-link-kopieren').textContent = 'Kopiert';
            window.setTimeout(() => { el('btn-link-kopieren').textContent = 'Kopieren'; }, 1500);
        } catch {
            feld.select();   // Fallback: markieren, damit von Hand kopiert werden kann
        }
    });

    el('btn-partie-starten').addEventListener('click', async () => {
        const reihenfolge = Array.from(el('lobby-reihenfolge').querySelectorAll('li'))
            .map(eintrag => parseInt(eintrag.dataset.id, 10));
        try {
            await hole(`/api/tisch/${tischCode}/reihenfolge`, {
                method: 'POST',
                body: JSON.stringify({ reihenfolge }),
            });
            await hole(`/api/tisch/${tischCode}/starten`, { method: 'POST' });
        } catch (fehler) {
            window.alert(fehler.message);
        }
    });

    el('btn-skat-aufnehmen').addEventListener('click', () => sendeAktion('skat_aufnehmen'));
    el('btn-hand-spielen').addEventListener('click', () => sendeAktion('hand_spielen'));
    el('btn-druecken').addEventListener('click', () => {
        if (gewaehlteDruckKarten.size !== 2) return;
        const karten = Array.from(gewaehlteDruckKarten);
        gewaehlteDruckKarten.clear();
        sendeAktion('druecken', { karten });
    });

    el('ansage-spielart').addEventListener('change', () => {
        if (letzterZustand) zeichneZustand(letzterZustand);
    });
    el('btn-ansagen').addEventListener('click', () => sendeAktion('ansagen', {
        spielart: el('ansage-spielart').value,
        hand: letzterZustand && letzterZustand.spiel
            ? !letzterZustand.spiel.skat_aufgenommen : false,
        schneider_angesagt: el('ansage-schneider').checked,
        schwarz_angesagt: el('ansage-schwarz').checked,
        ouvert: el('ansage-ouvert').checked,
    }));

    el('btn-naechstes-spiel').addEventListener('click', async () => {
        try {
            await hole(`/api/tisch/${tischCode}/naechstes`, { method: 'POST' });
        } catch (fehler) {
            window.alert(fehler.message);
        }
    });

    el('btn-tisch-verlassen').addEventListener('click', async () => {
        const frage = 'Die Runde zurück in die Lobby holen?\n\n'
            + 'Dort können Spielerinnen gehen, dazukommen und die Sitzordnung '
            + 'neu gelegt werden. Die bisherigen Ergebnisse bleiben erhalten.';
        if (!window.confirm(frage)) return;
        try {
            await hole(`/api/tisch/${tischCode}/lobby`, { method: 'POST' });
        } catch (fehler) {
            window.alert(fehler.message);
        }
    });

    el('btn-platz-freigeben').addEventListener('click', async () => {
        if (!window.confirm('Deinen Platz an diesem Tisch freigeben?')) return;
        try {
            await hole(`/api/tisch/${tischCode}/verlassen`, { method: 'POST' });
            window.location.search = `?code=${tischCode}`;
        } catch (fehler) {
            window.alert(fehler.message);
        }
    });

    el('btn-spiel-zuruecknehmen').addEventListener('click', async () => {
        if (!window.confirm('Das letzte Spiel wirklich zurücknehmen?')) return;
        try {
            await hole(`/api/tisch/${tischCode}/undo`, { method: 'POST' });
        } catch (fehler) {
            window.alert(fehler.message);
        }
    });

    // Aufdecken ändert den Strom, deshalb neu verbinden.
    el('schalter-aufdecken').addEventListener('change', () => verbinde());

    initialisiereReihenfolgeZiehen();

    const ausUrl = new URLSearchParams(window.location.search).get('code');
    if (ausUrl) {
        el('eingabe-code').value = ausUrl.toUpperCase();
        tischOeffnen(ausUrl);
    }
});

// --- Sitzordnung per Drag & Drop (nur Lobby) -------------------------------

function initialisiereReihenfolgeZiehen() {
    const liste = el('lobby-reihenfolge');
    let gezogen = null;

    liste.addEventListener('dragstart', ereignis => {
        gezogen = ereignis.target.closest('li');
        if (gezogen) gezogen.classList.add('wird-gezogen');
    });

    liste.addEventListener('dragover', ereignis => {
        ereignis.preventDefault();
        const ziel = ereignis.target.closest('li');
        if (!ziel || !gezogen || ziel === gezogen) return;
        const kasten = ziel.getBoundingClientRect();
        const nachUnten = (ereignis.clientY - kasten.top) > kasten.height / 2;
        liste.insertBefore(gezogen, nachUnten ? ziel.nextSibling : ziel);
    });

    ['drop', 'dragend'].forEach(name => {
        liste.addEventListener(name, ereignis => {
            ereignis.preventDefault();
            if (gezogen) gezogen.classList.remove('wird-gezogen');
            gezogen = null;
        });
    });
}
