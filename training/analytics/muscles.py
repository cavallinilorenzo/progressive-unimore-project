"""La heatmap muscolare — le serie per muscolo, e i colori con cui si accende.

La figura anatomica della dashboard, prototipata in #37 (variante C) e portata
qui, non riscritta: la scala, la doppia normalizzazione e l'annidamento sotto i
sei gruppi sono le decisioni di quel prototipo, e questo modulo le esegue sui
dati veri.

## Serie, non volume — e va detto in pagina

La domanda della heatmap è «cosa alleno di più e cosa trascuro», che è un
confronto **fra regioni del corpo**. Il volume non lo regge: una serie di squat
muove dieci volte i chili di una di alzate laterali, quindi una mappa
normalizzata sul volume avrebbe le gambe accese e le spalle spente per sempre,
e direbbe una cosa sull'anatomia invece che sull'allenamento. Le serie sono la
misura in cui i gruppi si confrontano davvero — è anche quella su cui parlerà
il coach quando arriverà lo squilibrio (fase 3).

È deliberatamente **una misura diversa** da quella di A2, che sui sei gruppi
mostra i kg (`analytics/volume.py`). Non è la divergenza di #75: quella era la
stessa grandezza calcolata in due modi, questa sono due grandezze diverse, con
due nomi diversi, e ognuna delle due pagine dichiara la propria. La divisione
del lavoro di #99 regge anche qui — la heatmap è il richiamo visivo, `/analisi/`
è dove si va a capire perché.

## La finestra: quattro settimane, sulla griglia dei lunedì

`04-analisi.md` dà 28 giorni come finestra dello squilibrio, e #99 ha dato 12
settimane a `/analisi/`. Qui vale la prima, ma **contata in settimane di
calendario** (`finestra_settimanale(4)`) e non in 28 giorni mobili: è la stessa
griglia su cui `/analisi/` raggruppa, e due griglie diverse per la stessa parola
«settimana» sono la premessa di una divergenza. L'ultima settimana è parziale,
come su `/analisi/`, e la pagina lo dichiara invece di nasconderlo.

## Il limite noto, e la sua misura corretta

Il catalogo (#27) tagga **un solo muscolo primario** per esercizio, quindi il
lavoro che un muscolo riceve da secondario non arriva sulla figura: uno spento
è un muscolo non allenato *direttamente*, non necessariamente un muscolo
trascurato. È il limite che la pagina dichiara invece di nasconderlo, e la
dichiarazione **non è condizionata a niente**, perché il limite è strutturale.

Su un punto, però, il prototipo #37 andava corretto, e l'ha detto il database:
i «4 muscoli su 23 sempre spenti» (schiena alta, adduttori, abduttori,
trasverso) erano misurati sui numeri finti del prototipo. Sul **catalogo vero**
tutti e 23 i muscoli hanno almeno un esercizio che li ha come primari — gli
adduttori dell'utente della demo contano 8 serie — e quei quattro erano zeri
*di quell'utente*, non del modello. `_muscoli_primari()` resta come guardia sul
caso opposto: un muscolo caricato senza esercizi resterebbe spento in silenzio,
e la pagina invece lo dice.
"""

from django.db.models import Count

from training.analytics.volume import finestra_settimanale, inizio_della_finestra
from training.models import Exercise, Muscle, MuscleGroup, WorkoutSet

#: La finestra della heatmap: 4 settimane, cioè i 28 giorni dello squilibrio.
SETTIMANE_HEATMAP = 4

#: La scala: dal grigio della superficie al volt del brand (prototipo #37).
#: Il grigio è «zero serie», che qui è anche «nessun dato» — sono la stessa
#: tinta, ed è il difetto che la variante C espone invece di nascondere.
SPENTO = (0x2A, 0x2E, 0x36)
VOLT = (0xC9, 0xFF, 0x3D)

#: L'esponente che schiarisce i valori bassi. Senza, un muscolo con 6 serie su
#: 34 è visivamente indistinguibile da uno a zero, e la mappa mentirebbe per
#: arrotondamento. Misurato sul prototipo, non scelto a tavolino.
GAMMA = 0.65


def colore(frazione):
    """Interpola spento → volt, con la radice di `GAMMA`."""
    t = frazione**GAMMA
    return "#%02X%02X%02X" % tuple(
        round(s + (v - s) * t) for s, v in zip(SPENTO, VOLT)
    )


def _scala(voci):
    """Da `{chiave: serie}` a `{chiave: colore}`, normalizzando sul **massimo**.

    Sul massimo e non sul totale, che è la decisione di #37: la domanda è un
    confronto fra regioni («cosa trascuro»), non una quota della torta. Su una
    scala del totale sei gruppi equilibrati sarebbero sei tinte identiche al
    16%, cioè un corpo uniformemente spento che non dice niente.
    """
    massimo = max(voci.values(), default=0) or 1
    return {chiave: colore(serie / massimo) for chiave, serie in voci.items()}, massimo


def _muscoli_primari():
    """I `pk` dei muscoli che **almeno un esercizio del catalogo** ha come primario.

    Ricavati, non elencati: la lista dei quattro spenti scritta a mano sarebbe
    vera oggi e falsa al primo esercizio caricato, e la pagina continuerebbe a
    scusarsi per un muscolo che nel frattempo si accende.
    """
    return set(Exercise.objects.values_list("primary_muscle_id", flat=True))


def serie_per_muscolo(user, settimane=None, oggi=None):
    """La heatmap: i 23 muscoli e i sei gruppi, colorati, nella finestra.

    Restituisce **tutti** i muscoli del catalogo, anche quelli a zero: un
    muscolo assente dalla `values()` non si distingue da uno che la figura si è
    dimenticata di colorare, ed è la stessa ragione per cui A2 riempie i sei
    gruppi (#99).

    Quattro query e non di più, e **nessuna cresce con lo storico**: una aggrega
    le serie nel database, le altre tre leggono il catalogo — 23 muscoli, 6
    gruppi, e i muscoli primari degli esercizi. È la guardia di #86:
    l'invarianza, non il numero.

    I gruppi restano nell'**ordine del catalogo** e non ordinati per serie:
    accanto c'è una figura anatomica, e una lista che si riordina a ogni
    ricarica non si allinea più a un corpo che sta fermo.
    """
    settimane = settimane or finestra_settimanale(SETTIMANE_HEATMAP, oggi=oggi)

    # `.order_by()` in coda per la trappola di #99: `WorkoutSet.Meta.ordering`
    # vale `["set_number"]` e Django lo trascinerebbe nel `GROUP BY`, spaccando
    # ogni muscolo in una riga per numero di serie. Il conto sarebbe sbagliato e
    # la figura si colorerebbe lo stesso.
    righe = (
        WorkoutSet.objects.working()
        .filter(
            workout__user=user,
            workout__started_at__gte=inizio_della_finestra(settimane),
        )
        .values("exercise__primary_muscle")
        .annotate(serie=Count("id"))
        .order_by()
    )
    per_muscolo = {riga["exercise__primary_muscle"]: riga["serie"] for riga in righe}

    catalogo = list(
        Muscle.objects.select_related("group").order_by(
            "group__sort_order", "sort_order"
        )
    )
    # `misurabile` è il limite noto portato **dentro la riga**: un muscolo che
    # nessun esercizio ha come primario è spento per costruzione, e la pagina
    # deve poterlo distinguere da uno trascurato senza rifare il conto.
    primari = _muscoli_primari()
    muscoli = [
        {
            "codice": muscolo.code,
            "nome": muscolo.label_it,
            "gruppo": muscolo.group.code,
            "serie": per_muscolo.get(muscolo.pk, 0),
            "misurabile": muscolo.pk in primari,
        }
        for muscolo in catalogo
    ]

    # I sei gruppi arrivano dal **loro** catalogo e non da quelli che i muscoli
    # nominano: sono un insieme chiuso, come per A2 (#99), e un gruppo che
    # sparisse dalla lista sarebbe indistinguibile da uno che la pagina si è
    # dimenticata di disegnare. Vale già oggi come guardia sul futuro — un
    # gruppo nuovo caricato senza muscoli non deve far sparire una riga in
    # silenzio.
    etichette = {
        gruppo.code: gruppo.label_it for gruppo in MuscleGroup.objects.all()
    }
    per_gruppo = {codice: 0 for codice in etichette}
    for muscolo in muscoli:
        per_gruppo[muscolo["gruppo"]] = (
            per_gruppo.get(muscolo["gruppo"], 0) + muscolo["serie"]
        )
    totale = sum(per_gruppo.values())

    # **Due scale separate**, ed è la decisione di #37: il gruppo si colora
    # sulla scala dei gruppi, il muscolo su quella dei muscoli. Sono due
    # domande diverse — «quale gruppo peso di più» e «dentro questo gruppo cosa
    # trascuro» — e una scala sola le renderebbe illeggibili entrambe, perché
    # il massimo di gruppo è qualche volta quello di un singolo muscolo.
    colori_muscolo, max_muscolo = _scala({m["codice"]: m["serie"] for m in muscoli})
    colori_gruppo, max_gruppo = _scala(per_gruppo)
    for muscolo in muscoli:
        muscolo["colore"] = colori_muscolo[muscolo["codice"]]

    gruppi = [
        {
            "codice": codice,
            "nome": etichette[codice],
            "serie": serie,
            "pct": round(100 * serie / totale) if totale else 0,
            "colore": colori_gruppo[codice],
            "muscoli": [m for m in muscoli if m["gruppo"] == codice],
            "spenti": sum(
                1 for m in muscoli if m["gruppo"] == codice and m["serie"] == 0
            ),
        }
        for codice, serie in per_gruppo.items()
    ]

    return {
        "gruppi": gruppi,
        "muscoli": muscoli,
        "mai_misurabili": [m for m in muscoli if not m["misurabile"]],
        "totale": totale,
        "max_muscolo": max_muscolo,
        "max_gruppo": max_gruppo,
        "settimane": len(settimane),
        "da": settimane[0],
        # Sei gradini dal nulla al massimo: la legenda dice cosa vale una
        # tinta, altrimenti la figura è decorazione.
        "legenda": [
            {"colore": colore(passo / 5), "valore": round(passo / 5 * max_muscolo)}
            for passo in range(6)
        ],
    }
