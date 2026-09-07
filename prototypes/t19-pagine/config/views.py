"""PROTOTIPO — ticket #19.

Tre varianti della dashboard sulla stessa rotta, commutabili con `?variant=`.
Nessun database: i dati sono finti e vivono qui, ma sono modellati sulle sei
analisi ammesse in #16 e sui numeri veri dello storico misurato in #13
(15 sessioni, 317 serie, 24 esercizi in 26 giorni), perche' una dashboard
giudicata su dati inventati generosi mente sulla densita' che avra' davvero.
"""

import json

from django.http import HttpResponse
from django.shortcuts import render

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


def dashboard(request):
    contesto = _contesto(request)
    return render(
        request, f"prototype/dashboard_{contesto['variante'].lower()}.html", contesto
    )


def segnaposto(request, resto):
    """Qualsiasi altra rotta: esiste solo perche' i link della navigazione non muoiano."""
    return HttpResponse(
        f"<p style='font:16px/1.5 system-ui;padding:3rem'>"
        f"Prototipo #19 — la pagina <code>/{resto}</code> non e' prototipata. "
        f"<a href='/'>Torna alla dashboard</a></p>"
    )
