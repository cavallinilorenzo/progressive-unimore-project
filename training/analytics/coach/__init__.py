"""Il coach: **una** cosa da fare, scelta per priorità, e niente altro.

Il motore analitico mostra cosa è successo; il coach dice cosa fare. La riga
che separa le due cose è ADR-0007 e si legge così: un consiglio è **azionabile**
e ha dietro **una** query. «Stai trascurando le gambe» non è un consiglio, è
un'osservazione, e resta nella heatmap; «aggiungi un esercizio per le gambe al
prossimo allenamento» lo è. È la distinzione che impedisce al coach di
ridiventare un cruscotto.

## Un pacchetto, e `__init__.py` è l'unica superficie pubblica

`05-coach-e-stallo.md` diceva `training/analytics/coach.py`, modulo unico. La
mappa #111 l'ha corretto e la spec è aggiornata in #112: i quattro tipi di
consiglio condividono la **selezione per priorità**, che è il cuore di ADR-0007
e non può esistere in due copie. Un pacchetto dà a ogni ticket della fase 3 il
proprio file senza che la priorità si sdoppi.

Per non pagare quella scelta in cerimonia, la regola è stretta: **fuori di qui
si importano solo le due funzioni in fondo a questo file**, e un tipo di
consiglio guadagna un modulo suo **solo se ha una query propria**. I due tipi
di #112 non ce l'hanno — sono due letture di misure che il motore analitico già
calcola — e stanno qui, in due funzioni corte. Il **carico** invece la query ce
l'ha, e da #113 vive in `carico.py`: qui ne resta la riga che lo mette in coda
alla priorità. Lo stallo, quando arriverà, avrà il suo per la stessa ragione.

Il tipo `Consiglio` sta in `consiglio.py` e si riesporta di qui — il perché è
nel docstring di quel file, ed è l'unica eccezione alla regola dell'unica
superficie: è un tipo, non una risposta, e serve a entrambi i lati.

## La priorità è un intero cablato sul tipo

Mai un punteggio calcolato. Un punteggio sarebbe una terza cosa da giustificare
all'orale, e nessuno dei suoi pesi sarebbe misurato: la scala non uscirebbe da
nessun dato, solo da un pomeriggio di tentativi. L'ordine invece ha una ragione
in una riga — *se non ti alleni, nessun altro consiglio conta* — e quella riga
regge da sola tutta la gerarchia.

L'ordine sta in **un posto solo**, `REGOLE`, e il numero di priorità si ricava
da lì (`PRIORITA`). Scriverli separatamente vorrebbe dire poterli far divergere,
e il primo consiglio dato nell'ordine sbagliato sarebbe invisibile: la pagina
mostrerebbe *un* consiglio plausibile, semplicemente non quello giusto.

## Il coach non decide dove parla, ma sa che parla in due posti soli

- `consiglio_per_dashboard(user)` → **uno solo**, quello a priorità più alta
- `consigli_per_esercizio(user, exercise)` → il carico e, se rilevato, lo stallo

Non esiste una terza funzione, e soprattutto non esiste quella che li elenca
tutti: con quattro consigli calcolati mostrarne uno *sembra* uno spreco, ed è
invece la tesi del progetto (ADR-0007). La tentazione è reale e il posto in cui
si materializzerebbe è esattamente questo file.

## Nessuna persistenza, nessuna cache

Non è un modello Django e non salva niente: a ogni richiesta i consigli si
calcolano dalle serie già registrate. #102 ha **misurato** che a questa scala
non serve altro (ADR-0012), e un `PlateauAssessment` sarebbe una cache
travestita da modello.
"""

from dataclasses import dataclass

from training.analytics import costanza as analytics_costanza
from training.analytics import muscles as analytics_muscles
from training.analytics.coach import carico as coach_carico
from training.analytics.coach.consiglio import Consiglio

#: Quanti allenamenti deve contenere la finestra perché un gruppo a zero sia
#: uno **squilibrio** e non un'**assenza** (`05-coach-e-stallo.md`).
ALLENAMENTI_PER_LO_SQUILIBRIO = 8

#: `Consiglio` vive in `consiglio.py` da #113 e si riesporta di qui: lo
#: costruiscono sia le regole corte di questo file sia `carico.py`, e un tipo
#: che serve alla superficie *e* ai suoi moduli non può stare nella superficie
#: senza che ogni modulo importi il proprio importatore. Fuori dal pacchetto
#: non cambia niente: `analytics_coach.Consiglio` è ancora questo.
__all__ = ["Consiglio", "consiglio_per_dashboard", "consigli_per_esercizio"]


@dataclass(frozen=True)
class Contesto:
    """Ciò che il coach ha già in mano quando chiede a una regola di parlare.

    Le regole di #112 prendevano `(conteggi, heatmap)`, cioè due misure già
    calcolate. Il carico però ha una **query propria** e gli serve l'utente,
    e lo stallo — priorità 3 — avrà lo stesso bisogno: passare un argomento in
    più significherebbe riscrivere la firma di tutte le regole a ogni ticket
    che ne aggiunge una. Un contesto solo lo evita, e dà un posto dichiarato a
    ciò che una regola può legittimamente guardare.

    `conteggi` e `heatmap` restano risposte **già ottenute** dal chiamante:
    non è una cache — non sopravvive alla richiesta — è il coach che non
    richiede al database quello che la dashboard ha appena chiesto.
    """

    user: object
    conteggi: dict
    heatmap: dict


def _costanza(contesto):
    """Meno di 2 allenamenti in 14 giorni, e solo per chi ne ha già almeno 4.

    Prima di tutti gli altri per la ragione che regge l'intera gerarchia: se
    non ci si allena, nessun altro consiglio conta. Un consiglio di carico dato
    a chi non entra in palestra da tre settimane è tecnicamente corretto e
    completamente inutile.

    La soglia dello storico non è una cortesia: a due allenamenti totali «ti
    stai allenando poco» è un rimprovero rivolto a chi ha appena cominciato, e
    per giunta calcolato su una finestra che contiene tutta la sua storia.

    **Nessuna query qui dentro.** I due numeri arrivano da
    `analytics/costanza.py`, che è l'unico modulo che sa contare gli
    allenamenti di un utente: una seconda misura di costanza sarebbe la
    divergenza di #75 un'altra volta, con l'aggravante che le due sarebbero
    entrambe giuste e discordi, a un palmo l'una dall'altra sulla stessa pagina.
    """
    conteggi = contesto.conteggi
    if conteggi["totali"] < analytics_costanza.STORICO_MINIMO:
        return None
    if conteggi["recenti"] >= analytics_costanza.ALLENAMENTI_DELLA_SOGLIA:
        return None

    quanti = conteggi["recenti"]
    return Consiglio(
        tipo="costanza",
        titolo="Rimettiti in moto",
        azione=(
            "Fissa la prossima seduta adesso, anche corta: la costanza viene "
            "prima di qualunque scelta di carico o di esercizio."
        ),
        misura=(
            f"{quanti} {'allenamento' if quanti == 1 else 'allenamenti'} "
            f"negli ultimi {analytics_costanza.GIORNI_DEL_CONSIGLIO} giorni"
        ),
    )


def _squilibrio(contesto):
    """Un gruppo muscolare a zero serie di lavoro nella finestra della heatmap.

    La soglia è di **assenza**, non di proporzione, ed è la decisione che rende
    la regola difendibile: «non hai allenato le gambe in un mese» è un fatto che
    esce da un `Count` uguale a zero, mentre «le tue spalle sono al 9% invece
    che al 15%» richiederebbe una ripartizione ideale che nessuno ha misurato e
    che il progetto non ha nessun titolo per inventare.

    La seconda metà della condizione — almeno 8 allenamenti nella finestra — è
    ciò che distingue uno squilibrio da un'assenza: chi si è allenato due volte
    in un mese ha cinque gruppi a zero, e il suo problema è la costanza, che
    infatti ha la priorità sopra.

    **Il limite del muscolo secondario si dichiara sempre, e non è cosmetico.**
    Il catalogo tagga un solo muscolo primario per esercizio (ADR-0001, per non
    inventare coefficienti di volume), quindi «zero serie» significa *zero serie
    dirette*. Misurato sul database della demo il 2026-09-09: la regola scatta
    per **33 utenti su 55** con almeno 8 allenamenti nella finestra, e in **32
    casi su 33** il gruppo mancante è **braccia** — cioè proprio il gruppo che
    riceve più lavoro da secondario, da ogni trazione e da ogni spinta. Il
    consiglio resta vero (l'utente della demo non ha mai registrato una serie
    con primario braccia in 443 allenamenti su 24 mesi) e resta azionabile
    (aggiungi lavoro diretto), ma senza la parola «direttamente» in pagina
    direbbe una cosa più grande di quella che sa.

    Come per la costanza, **nessuna query qui dentro**: i conteggi per gruppo
    sono quelli della heatmap, cioè la stessa misura in serie che la pagina
    mostra a mezzo schermo di distanza.
    """
    conteggi, heatmap = contesto.conteggi, contesto.heatmap
    if conteggi["nella_finestra"] < ALLENAMENTI_PER_LO_SQUILIBRIO:
        return None

    # I gruppi restano nell'**ordine del catalogo** — quello in cui la heatmap
    # li elenca — e il primo a zero vince. Serve un ordine qualunque, purché
    # stabile e uguale a quello della figura accanto: con due gruppi a zero un
    # criterio che si riordinasse a ogni ricarica mostrerebbe due consigli
    # diversi a due aggiornamenti di distanza, sugli stessi identici dati.
    spenti = [gruppo for gruppo in heatmap["gruppi"] if gruppo["serie"] == 0]
    if not spenti:
        return None

    # Le frasi nominano il gruppo **senza articolo** (`del gruppo Braccia`, non
    # `per le braccia`). Non è goffaggine: l'articolo cambia con l'etichetta —
    # *il* petto, *la* schiena, *le* gambe — e una tabella di articoli sarebbe
    # una settima cosa da tenere allineata al catalogo, sbagliata in silenzio
    # al primo gruppo caricato. I gruppi qui restano un insieme aperto letto
    # dal database, come in `muscles.py`.
    gruppo = spenti[0]
    return Consiglio(
        tipo="squilibrio",
        titolo=f"{gruppo['nome']}: nessun lavoro diretto",
        azione=(
            f"Aggiungi un esercizio del gruppo {gruppo['nome']} al prossimo "
            "allenamento: una voce in scheda basta a rimetterlo in moto."
        ),
        misura=(
            f"0 serie con muscolo primario nel gruppo {gruppo['nome']}, in "
            f"{heatmap['settimane']} settimane su "
            f"{conteggi['nella_finestra']} allenamenti"
        ),
        limite=(
            "Il conto guarda il muscolo primario dell'esercizio: il lavoro che "
            "questo gruppo riceve da secondario — dalle trazioni, dalle "
            "spinte — non ci entra."
        ),
    )


def _carico(contesto):
    """La doppia progressione sull'esercizio allenato per ultimo (#113).

    **È l'unica regola che apre query per conto suo**, e per questo è anche
    l'unica che le apre *tardi*: la selezione scorre `REGOLE` in ordine e si
    ferma al primo consiglio, quindi queste tre query non partono affatto
    quando la costanza o lo squilibrio hanno già parlato. Il costo si paga solo
    quando serve, che è la ragione per cui una regola con una query dietro può
    stare in fondo senza appesantire il caso peggiore.

    La scelta dell'esercizio sta in `carico.esercizio_piu_recente` e non qui:
    sul dettaglio esercizio la pagina lo sa già, e questa funzione è solo il
    ramo della dashboard, dove nessuno l'ha detto.

    `None` quando l'utente non ha mai registrato una serie di lavoro — cioè
    l'utente appena registrato, e sostanzialmente nessun altro: è questa regola
    a restringere il silenzio del riquadro a quel caso solo.
    """
    esercizio = coach_carico.esercizio_piu_recente(contesto.user)
    if esercizio is None:
        return None
    return coach_carico.consiglio_di_carico(contesto.user, esercizio)


#: Le regole **in ordine di priorità**, ed è questa lista l'ordine: non c'è un
#: secondo posto in cui sia scritto. Il coach di #112 ne aveva due; #113 ci ha
#: infilato il carico in fondo, e lo stallo entrerà in mezzo — fra lo
#: squilibrio e il carico — senza toccare la selezione.
REGOLE = [
    ("costanza", _costanza),
    ("squilibrio", _squilibrio),
    ("carico", _carico),
]

#: La priorità come **intero cablato sul tipo**, ricavata dall'ordine di
#: `REGOLE` e mai scritta a mano: due elenchi da tenere allineati sono due
#: elenchi che prima o poi non lo sono più.
PRIORITA = {tipo: numero for numero, (tipo, _) in enumerate(REGOLE, start=1)}


def consiglio_per_dashboard(user, heatmap=None, oggi=None):
    """**Un** consiglio, quello a priorità più alta, o `None`.

    `None` non è un caso d'errore: è la risposta corretta quando nessuna regola
    scatta, e in #112 capita spesso, perché due dei quattro tipi non esistono
    ancora. La dashboard, in quel caso, **non mostra il riquadro** — la ragione
    sta nella view. Con il carico (priorità 4, che scatta per chiunque abbia
    registrato una serie) il silenzio si restringerà quasi al solo utente nuovo.

    `heatmap` è il risultato di `analytics/muscles.py` quando il chiamante ce
    l'ha già: la dashboard lo calcola comunque per disegnare la figura, e
    rifarlo qui vorrebbe dire ripetere le stesse quattro query per ottenere lo
    stesso oggetto. Non è una cache — non sopravvive alla richiesta — è il
    chiamante che passa una risposta che ha già in mano.

    Il costo in query di questa funzione, quando la heatmap arriva da fuori, è
    **uno**: l'aggregato dei tre conteggi. E non cresce con lo storico, che è la
    guardia di #86 sulla dashboard.

    `oggi` è iniettabile come in tutto `analytics/` e per la stessa ragione: i
    dati sintetici finiscono a una data fissa e un test ancorato a `now()`
    scadrebbe da solo. Se si passano **entrambi**, `heatmap` e `oggi`, la
    heatmap dev'essere costruita sullo stesso `oggi`: il coach non ha modo di
    accorgersi che guardano due finestre diverse.
    """
    heatmap = heatmap or analytics_muscles.serie_per_muscolo(user, oggi=oggi)
    conteggi = analytics_costanza.allenamenti_per_il_coach(user, oggi=oggi)
    contesto = Contesto(user=user, conteggi=conteggi, heatmap=heatmap)

    for _, regola in REGOLE:
        consiglio = regola(contesto)
        if consiglio is not None:
            return consiglio
    return None


def consigli_per_esercizio(user, exercise):
    """Il carico e, se rilevato, lo stallo — sulla pagina di dettaglio esercizio.

    Vuota in #112, e deliberatamente presente: è l'altra metà della superficie
    pubblica di ADR-0007, e i due ticket che la riempiono (stallo e carico) si
    innestano qui senza aprire un terzo punto d'ingresso.

    Restituisce una **lista** e non un consiglio solo, al contrario della
    dashboard: sul dettaglio i due tipi ammessi non si escludono — lo stallo
    dice di scaricare, il carico dice da dove ripartire — e sono comunque due e
    non «tutti», che è ciò che ADR-0007 vieta.

    Da #113 ne contiene **uno**, il carico. Resta una lista e non diventa un
    consiglio solo: lo stallo si aggiunge qui, e una funzione che oggi
    restituisse un oggetto e domani due sarebbe una firma da cambiare in un
    ticket che ha già il suo lavoro da fare.

    La lista è vuota quando l'esercizio non è mai stato registrato con una
    serie di lavoro — un esercizio del catalogo aperto per curiosità — e la
    pagina in quel caso non disegna il riquadro, come la dashboard.

    **Nessuna selezione per priorità qui.** Sul dettaglio i consigli ammessi
    non si escludono, quindi l'ordine di `REGOLE` non serve: serve a scegliere
    *uno*, e qui non si sceglie.
    """
    consiglio = coach_carico.consiglio_di_carico(user, exercise)
    return [consiglio] if consiglio is not None else []
