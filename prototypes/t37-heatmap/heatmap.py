"""PROTOTIPO — ticket #37: la heatmap muscolare.

Tre varianti sulla stessa rotta `/heatmap/`, commutabili con `?variant=`, nel
guscio della variante A vinta in #19.

La domanda del ticket e' un si'/no con ripiego gia' pronto, quindi le varianti
sono esattamente le tre risposte possibili:

  A  barre per gruppo          — il ripiego a costo zero, gia' in dashboard_a
  B  figura anatomica, 6 gruppi — poche regioni, tutte accendibili
  C  figura anatomica, 23 muscoli — precisa, ma il catalogo tagga solo il
                                    muscolo primario, quindi certe regioni
                                    restano spente per costruzione

Come funziona B/C senza una riga di JavaScript: `_corpo.svg` e' un partial
statico in cui ogni path porta gia' `class="g-<gruppo> m-<muscolo>"` (generato
da `build_body_svg.mjs`). La view non tocca l'SVG: emette solo un blocco
`<style>` con una regola di `fill` per classe. Il colore e' dato, il disegno e'
template. E' lo stesso principio di `json_script` scelto in #16 — i dati entrano
nella pagina come dati, non come DOM costruito a mano.
"""

import json

# I sei gruppi con i numeri finti gia' usati in #19 (317 serie in totale,
# il volume vero misurato in #13), disaggregati sui 23 muscoli del catalogo.
#
# La disaggregazione NON e' decorativa: e' il cuore della decisione fra B e C.
# Il catalogo di #27 tagga un solo muscolo primario per esercizio, quindi un
# muscolo che non e' primario di nessun esercizio svolto resta a zero. Qui
# quattro lo sono, e restano spenti apposta.
MUSCOLI = [
    # (codice, etichetta, gruppo, serie)
    ("chestUpper", "Petto alto", "chest", 22),
    ("chestMid", "Petto medio", "chest", 34),
    ("chestLower", "Petto basso", "chest", 6),
    ("lats", "Gran dorsale", "back", 30),
    ("traps", "Trapezio", "back", 12),
    ("upperBack", "Schiena alta", "back", 0),
    ("middleBack", "Schiena media", "back", 14),
    ("lowerBack", "Lombari", "back", 18),
    ("deltoidFront", "Deltoide anteriore", "shoulders", 18),
    ("deltoidLateral", "Deltoide laterale", "shoulders", 17),
    ("deltoidRear", "Deltoide posteriore", "shoulders", 6),
    ("biceps", "Bicipiti", "arms", 20),
    ("triceps", "Tricipiti", "arms", 22),
    ("forearms", "Avambracci", "arms", 6),
    ("quads", "Quadricipiti", "legs", 26),
    ("hamstrings", "Femorali", "legs", 16),
    ("glutes", "Glutei", "legs", 14),
    ("calves", "Polpacci", "legs", 12),
    ("adductors", "Adduttori", "legs", 0),
    ("abductors", "Abduttori", "legs", 0),
    ("rectusAbdominis", "Retto addominale", "core", 16),
    ("obliques", "Obliqui", "core", 8),
    ("transverse", "Trasverso", "core", 0),
]

GRUPPI_LABEL = {
    "chest": "Petto",
    "back": "Schiena",
    "shoulders": "Spalle",
    "arms": "Braccia",
    "legs": "Gambe",
    "core": "Core",
}

VARIANTI_HM = {
    "A": "Barre per gruppo — il ripiego",
    "B": "Figura anatomica — 6 gruppi",
    "C": "Figura anatomica — 23 muscoli",
}

# Scala: dal grigio della superficie al volt del brand. Il grigio non e' "nessun
# dato", e' "zero serie" — sono la stessa cosa qui, ed e' proprio il punto
# debole che la variante C deve mostrare invece di nascondere.
SPENTO = (0x2A, 0x2E, 0x36)
VOLT = (0xC9, 0xFF, 0x3D)


def _colore(frazione):
    """Interpola spento -> volt. La radice schiarisce i valori bassi: senza,
    un muscolo con 6 serie su 34 e' visivamente indistinguibile da uno a zero,
    e la heatmap mentirebbe per arrotondamento."""
    t = frazione ** 0.65
    return "#%02X%02X%02X" % tuple(
        round(s + (v - s) * t) for s, v in zip(SPENTO, VOLT)
    )


def _scala(voci):
    """`voci` e' una lista di (chiave, serie). Ritorna le regole CSS e la
    legenda. Normalizza sul massimo, non sul totale: la domanda che la heatmap
    risponde e' «cosa alleni di piu' e cosa trascuri», che e' un confronto fra
    regioni, non una quota."""
    massimo = max(s for _, s in voci) or 1
    return {k: _colore(s / massimo) for k, s in voci}, massimo


def contesto_heatmap(variante):
    per_gruppo = {}
    for _codice, _label, gruppo, serie in MUSCOLI:
        per_gruppo[gruppo] = per_gruppo.get(gruppo, 0) + serie

    gruppi = [
        {
            "codice": g,
            "nome": GRUPPI_LABEL[g],
            "serie": per_gruppo[g],
            "pct": round(100 * per_gruppo[g] / sum(per_gruppo.values())),
        }
        for g in GRUPPI_LABEL
    ]
    muscoli = [
        {"codice": c, "nome": n, "gruppo": g, "serie": s} for c, n, g, s in MUSCOLI
    ]

    colori_gruppo, max_gruppo = _scala([(g["codice"], g["serie"]) for g in gruppi])
    colori_muscolo, max_muscolo = _scala([(m["codice"], m["serie"]) for m in muscoli])

    for g in gruppi:
        g["colore"] = colori_gruppo[g["codice"]]
    for m in muscoli:
        m["colore"] = colori_muscolo[m["codice"]]

    # Il blocco <style> e' tutta la logica di rendering della figura. Nella
    # variante B basta colorare i sei gruppi; nella C i 23 muscoli vincono sui
    # gruppi grazie all'ordine delle regole, che e' l'unica sottigliezza.
    if variante == "B":
        regole = "\n".join(
            f"  .corpo .g-{g['codice']} {{ fill: {g['colore']}; }}" for g in gruppi
        )
    else:
        regole = "\n".join(
            f"  .corpo .m-{m['codice']} {{ fill: {m['colore']}; }}" for m in muscoli
        )

    # I 23 muscoli annidati sotto i sei gruppi: e' la lista della variante C
    # dopo la revisione di Lorenzo. Ogni gruppo si apre e si legge per conto
    # suo, invece di scorrere 23 righe piatte.
    #
    # Il colore della riga di gruppo resta quello del gruppo (scala sui gruppi),
    # quello delle righe dentro resta quello del muscolo (scala sui muscoli):
    # sono due domande diverse — «quale gruppo peso di piu'» e «dentro questo
    # gruppo, cosa trascuro» — e mescolare le due scale renderebbe entrambe
    # illeggibili.
    annidati = [
        {
            **g,
            "muscoli": [m for m in muscoli if m["gruppo"] == g["codice"]],
            "spenti": len([m for m in muscoli if m["gruppo"] == g["codice"] and m["serie"] == 0]),
        }
        for g in gruppi
    ]

    return {
        "hm_annidati": annidati,
        "hm_variante": variante,
        "hm_variante_nome": VARIANTI_HM[variante],
        "hm_gruppi": gruppi,
        "hm_muscoli": muscoli,
        "hm_max_gruppo": max_gruppo,
        "hm_max_muscolo": max_muscolo,
        "hm_regole": regole,
        "hm_spenti": [m for m in muscoli if m["serie"] == 0],
        "hm_totale": sum(per_gruppo.values()),
        # La legenda della scala, sei gradini dal nulla al massimo.
        "hm_legenda": [
            {"colore": _colore(i / 5), "valore": round((i / 5) * (max_muscolo if variante == "C" else max_gruppo))}
            for i in range(6)
        ],
        "grafico_gruppi": json.dumps(
            {"labels": [g["nome"] for g in gruppi], "valori": [g["serie"] for g in gruppi]}
        ),
    }
