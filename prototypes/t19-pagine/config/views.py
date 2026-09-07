"""PROTOTIPO — ticket #19.

Tre varianti della dashboard sulla stessa rotta, commutabili con `?variant=`.
Nessun database: i dati sono finti e vivono qui, ma sono modellati sulle sei
analisi ammesse in #16 e sui numeri veri dello storico misurato in #13
(15 sessioni, 317 serie, 24 esercizi in 26 giorni), perche' una dashboard
giudicata su dati inventati generosi mente sulla densita' che avra' davvero.
"""

import json
import sys
from pathlib import Path

from django.http import HttpResponse
from django.shortcuts import render

# Il ticket #37 vive nella sua cartella, non qui: e' un prototipo distinto che
# prende in prestito questo guscio per essere giudicato in mezzo al resto.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "t37-heatmap"))
from heatmap import VARIANTI_HM, contesto_heatmap  # noqa: E402

VARIANTI = {
    "A": "Scoreboard — l'identita' di Overload",
    "B": "Coach — il verdetto per primo",
    "C": "Console — Bootstrap come il prof",
}

# --- dati finti, coerenti con lo storico reale di #13 ------------------------

DATI = {
    "utente": "Lorenzo",
    "settimane": ["14 lug", "21 lug", "28 lug", "4 ago", "11 ago", "18 ago", "25 ago", "1 set"],
    "volume_kg": [18400, 21050, 19800, 23100, 24600, 22900, 26350, 27800],
    "volume_settimana_kg": 27800,
    "volume_delta_pct": 5.5,
    "sessioni_settimana": 4,
    "sessioni_totali": 15,
    "serie_totali": 317,
    "esercizi_usati": 24,
    "costanza_pct": 86,
    "costanza_settimane": 6,
    "gruppi": [
        {"nome": "Petto", "serie": 62, "pct": 20, "delta": 3},
        {"nome": "Schiena", "serie": 74, "pct": 23, "delta": 6},
        {"nome": "Spalle", "serie": 41, "pct": 13, "delta": -2},
        {"nome": "Braccia", "serie": 48, "pct": 15, "delta": 1},
        {"nome": "Gambe", "serie": 68, "pct": 21, "delta": -4},
        {"nome": "Core", "serie": 24, "pct": 8, "delta": 0},
    ],
    "progressione_esercizio": "Panca piana con bilanciere",
    "progressione_date": ["10 ago", "14 ago", "17 ago", "21 ago", "24 ago", "28 ago", "31 ago", "4 set"],
    "progressione_1rm": [96.5, 98.2, 97.8, 100.4, 101.1, 100.9, 101.3, 101.0],
    "pr_recenti": [
        {"esercizio": "Stacco da terra", "valore": "140 kg × 5", "delta": "+5,0", "quando": "4 set"},
        {"esercizio": "Trazioni alla sbarra", "valore": "+20 kg × 6", "delta": "+2,5", "quando": "31 ago"},
        {"esercizio": "Military press", "valore": "62,5 kg × 4", "delta": "+2,5", "quando": "28 ago"},
    ],
    "percentili": [
        {"esercizio": "Stacco da terra", "percentile": 78, "rapporto": "1,84 × peso corporeo"},
        {"esercizio": "Panca piana", "percentile": 64, "rapporto": "1,33 × peso corporeo"},
        {"esercizio": "Squat", "percentile": 41, "rapporto": "1,42 × peso corporeo"},
    ],
    "coach": {
        "titolo": "Panca piana: sei in stallo",
        "dettaglio": (
            "Il massimale stimato non supera i 101,3 kg da 4 allenamenti "
            "(21 giorni). Prima di allora saliva di 1,2 kg a sessione."
        ),
        "azione": "Scarica il carico all'85% per una settimana, poi risali",
        "confidenza": 0.81,
        "secondari": [
            {"testo": "Gambe in calo: −4% di serie sulle ultime 3 settimane", "tono": "attenzione"},
            {"testo": "Core sotto la soglia consigliata: 8% del volume", "tono": "attenzione"},
            {"testo": "Costanza a 86%: 6 settimane senza saltare", "tono": "positivo"},
        ],
    },
    "prossimo": {
        "scheda": "Upper A — spinta",
        "esercizi": 6,
        "serie": 21,
        "ultimo_svolto": "3 giorni fa",
    },
    "ultime_sessioni": [
        {"data": "4 set", "scheda": "Lower B", "serie": 22, "volume": 8420, "durata": "1h 12m"},
        {"data": "31 ago", "scheda": "Upper A", "serie": 21, "volume": 6980, "durata": "58m"},
        {"data": "28 ago", "scheda": "Lower A", "serie": 19, "volume": 7310, "durata": "1h 04m"},
        {"data": "24 ago", "scheda": "Upper B", "serie": 20, "volume": 6150, "durata": "1h 01m"},
        {"data": "21 ago", "scheda": "Lower B", "serie": 22, "volume": 8090, "durata": "1h 09m"},
    ],
}


def _contesto(request):
    variante = request.GET.get("variant", "A").upper()
    if variante not in VARIANTI:
        variante = "A"
    chiavi = list(VARIANTI)
    i = chiavi.index(variante)
    return {
        **DATI,
        "variante": variante,
        "variante_nome": VARIANTI[variante],
        "variante_prec": chiavi[i - 1],
        "variante_succ": chiavi[(i + 1) % len(chiavi)],
        # I grafici arrivano al template come JSON da `json_script`, mai da un
        # endpoint: e' il pattern deciso in #16.
        "grafico_volume": json.dumps(
            {"labels": DATI["settimane"], "valori": DATI["volume_kg"]}
        ),
        "grafico_gruppi": json.dumps(
            {
                "labels": [g["nome"] for g in DATI["gruppi"]],
                "valori": [g["serie"] for g in DATI["gruppi"]],
            }
        ),
        "grafico_progressione": json.dumps(
            {"labels": DATI["progressione_date"], "valori": DATI["progressione_1rm"]}
        ),
    }


# --- la sitemap, dopo la scelta della variante A ----------------------------
#
# A tiene cinque voci nell'header, contro le undici in sidebar di B. Le voci
# che B mostrava per esteso non spariscono: si annidano. Questa struttura e'
# la risposta all'obiezione di Lorenzo — «schede della community o gli stalli
# devono comunque esistere, magari se entro in esercizi vedro' lo stallo».

SITEMAP = [
    {
        "voce": "Dashboard",
        "url": "/",
        "nota": "Le sei analisi di #16 come widget; ognuna e' un varco verso la pagina che la approfondisce.",
        "figlie": [
            {"url": "/", "cosa": "Volume, gruppi, costanza, PR, percentile, avviso di stallo", "crud": ""},
        ],
    },
    {
        "voce": "Schede",
        "url": "/schede/",
        "nota": "Ospita il CRUD completo su Routine, e la parte sociale.",
        "figlie": [
            {"url": "/schede/", "cosa": "Le mie schede", "crud": "R"},
            {"url": "/schede/nuova/", "cosa": "Crea scheda", "crud": "C"},
            {"url": "/schede/&lt;id&gt;/", "cosa": "Dettaglio, esercizi ordinati", "crud": "R"},
            {"url": "/schede/&lt;id&gt;/modifica/", "cosa": "Modifica scheda ed esercizi", "crud": "U"},
            {"url": "/schede/&lt;id&gt;/elimina/", "cosa": "Elimina scheda", "crud": "D"},
            {"url": "/schede/&lt;id&gt;/pubblica/", "cosa": "Pubblica o ritira dalla community", "crud": "U"},
            {"url": "/schede/pubbliche/", "cosa": "<b>Schede della community</b> &mdash; la voce di B", "crud": "R"},
            {"url": "/schede/pubbliche/&lt;id&gt;/", "cosa": "Dettaglio pubblico, voto e commento", "crud": "CUD su Vote"},
        ],
    },
    {
        "voce": "Storico",
        "url": "/allenamenti/",
        "nota": "CRUD completo su Workout e sulle sue serie. E' qui che si registra un allenamento.",
        "figlie": [
            {"url": "/allenamenti/", "cosa": "Elenco allenamenti, con filtri", "crud": "R"},
            {"url": "/allenamenti/nuovo/", "cosa": "Registra allenamento (anche <code>?scheda=</code>, che precompila)", "crud": "C"},
            {"url": "/allenamenti/&lt;id&gt;/", "cosa": "Dettaglio, tutte le serie", "crud": "R"},
            {"url": "/allenamenti/&lt;id&gt;/modifica/", "cosa": "Correggi allenamento", "crud": "U"},
            {"url": "/allenamenti/&lt;id&gt;/elimina/", "cosa": "Elimina allenamento", "crud": "D"},
            {"url": "/allenamenti/&lt;id&gt;/serie/nuova/", "cosa": "Aggiungi una serie", "crud": "C su WorkoutSet"},
        ],
    },
    {
        "voce": "Esercizi",
        "url": "/esercizi/",
        "nota": "Catalogo globale, in sola lettura (ADR-0001). <b>E' qui che vive lo stallo</b>: la pagina di un esercizio e' la sua storia.",
        "figlie": [
            {"url": "/esercizi/", "cosa": "Catalogo, filtri per muscolo e attrezzo", "crud": "R"},
            {"url": "/esercizi/&lt;slug&gt;/", "cosa": "<b>Progressione del massimale, stato di stallo, PR, percentile</b>", "crud": "R"},
        ],
    },
    {
        "voce": "Classifiche",
        "url": "/classifiche/",
        "nota": "Le due classifiche di natura diversa decise nella mappa. Il taglio esatto e' il ticket #33.",
        "figlie": [
            {"url": "/classifiche/forza/", "cosa": "Percentile di forza relativa sulla popolazione", "crud": "R"},
            {"url": "/classifiche/schede/", "cosa": "Schede pubbliche piu' votate", "crud": "R"},
        ],
    },
    {
        "voce": "Account (menu utente)",
        "url": "/profilo/",
        "nota": "Le voci che in B stavano in fondo alla sidebar: scendono nel menu, non nell'header.",
        "figlie": [
            {"url": "/profilo/", "cosa": "Profilo, peso corporeo, preferenze", "crud": "RU"},
            {"url": "/importa/", "cosa": "Import CSV, passo 1: carica i due file", "crud": "C"},
            {"url": "/importa/anteprima/", "cosa": "Passo 2: anteprima, abbinamento esercizi, errori", "crud": ""},
            {"url": "/importa/conferma/", "cosa": "Passo 3: conferma atomica", "crud": "C"},
            {"url": "/accounts/login/", "cosa": "Accesso", "crud": ""},
            {"url": "/registrazione/", "cosa": "Registrazione", "crud": "C su User"},
            {"url": "/accounts/logout/", "cosa": "Uscita", "crud": ""},
        ],
    },
]


def mappa(request):
    """PROTOTIPO — la sitemap completa nel guscio della variante A."""
    contesto = _contesto(request)
    contesto["variante"] = "A"
    contesto["sitemap"] = SITEMAP
    return render(request, "prototype/mappa.html", contesto)


def dashboard(request):
    contesto = _contesto(request)
    return render(
        request, f"prototype/dashboard_{contesto['variante'].lower()}.html", contesto
    )


def heatmap(request):
    """PROTOTIPO — ticket #37: le tre risposte al si'/no sulla figura anatomica,
    nel guscio della variante A vinta in #19. `?variant=` qui sceglie la
    heatmap, non la dashboard."""
    variante = request.GET.get("variant", "A").upper()
    if variante not in VARIANTI_HM:
        variante = "A"
    chiavi = list(VARIANTI_HM)
    i = chiavi.index(variante)

    contesto = _contesto(request)
    contesto.update(contesto_heatmap(variante))
    contesto.update({
        # Il guscio e' sempre quello di A (lo dice `{% extends %}` nel template);
        # qui `variante` serve solo alla barra flottante, che commuta la heatmap.
        "variante": variante,
        "variante_nome": VARIANTI_HM[variante],
        "variante_prec": chiavi[i - 1],
        "variante_succ": chiavi[(i + 1) % len(chiavi)],
    })
    return render(request, "prototype/heatmap.html", contesto)


def segnaposto(request, resto):
    """Qualsiasi altra rotta: esiste solo perche' i link della navigazione non muoiano."""
    return HttpResponse(
        f"<p style='font:16px/1.5 system-ui;padding:3rem'>"
        f"Prototipo #19 — la pagina <code>/{resto}</code> non e' prototipata. "
        f"<a href='/'>Torna alla dashboard</a></p>"
    )
