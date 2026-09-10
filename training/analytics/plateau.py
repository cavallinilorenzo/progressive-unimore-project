"""Il rilevamento dello stallo — oggi una regola a soglia, domani un modello.

Questo file nasce **vuoto tranne un numero**, e nasce così apposta.

`docs/spec/05-coach-e-stallo.md` impone alla fase 4 un **termine di paragone
obbligatorio**: la regola a soglia «nessun record nelle ultime *N* sessioni
della finestra», contro cui il modello dovrà misurarsi. Il numero che va
all'orale non è l'F1 del modello, è la **differenza fra modello e baseline**.

Ma la spec non dà *N*. E un baseline il cui parametro si sceglie *dopo* aver
visto come si comporta il modello non è un termine di paragone: è un avversario
truccato. Basta provare 2, 3 e 4 e tenere quello che perde meglio, e nessuno,
all'orale, potrebbe distinguere quella scelta da questa.

Quindi *N* si sceglie **adesso**, prima che esista qualunque finestra,
qualunque modello e qualunque script di confronto, e in un **commit suo** — il
`git log` è l'unica prova dell'ordine che una dichiarazione a posteriori non
può dare. È il trucco di
[#102](https://github.com/cavallinilorenzo/progetto-django-uni/issues/102),
dove la soglia dei tempi di pagina fu committata prima di misurare un solo
millisecondo.
"""

#: Le sessioni senza record che fanno scattare il baseline a soglia.
#:
#: **Tre**, cioè **metà della finestra minima** da 6 allenamenti
#: (`docs/spec/05-coach-e-stallo.md`, §«Definizione operativa»). Il numero è
#: scelto alla cieca, e la ragione della scelta è tutta qui:
#:
#: - **1 o 2 sarebbero rumore.** Un massimale stimato oscilla di suo fra una
#:   sessione e l'altra; due sedute senza record sono una settimana storta, non
#:   uno stallo, e il baseline direbbe «stallo» quasi sempre.
#: - **5 o 6 sarebbero l'intera finestra.** «Nessun record in tutte e sei le
#:   sessioni» non è una soglia: è la definizione stessa di finestra piatta, e
#:   il baseline diventerebbe una tautologia con un recall vicino a zero.
#: - **Metà finestra è l'unico punto che non richiede di aver visto i dati.**
#:   Non c'è niente di magico nel 3: c'è che è il centro dell'unico intervallo
#:   che la spec fissa, e sceglierlo non richiede di sapere nulla su come si
#:   distribuiscono gli stalli.
#:
#: Se la fase 4 trovasse che un altro *N* rende il baseline più forte, quella è
#: **un'informazione, non una correzione**: si dichiara, e il confronto resta
#: quello contro questo numero qui.
SESSIONI_SENZA_RECORD_PER_STALLO = 3

from dataclasses import dataclass

from django.utils import timezone

from training.analytics import progressione as analytics_progressione

#: Quanti allenamenti di quell'esercizio deve contenere la finestra.
ALLENAMENTI_MINIMI = 6

#: E quanti giorni di calendario deve coprire, **insieme** al vincolo sopra.
#:
#: Doppio vincolo perché ciascuno da solo sbaglia in un verso diverso, e la
#: spec li nomina entrambi: quattro sedute in cinque giorni sono un microciclo,
#: non una storia; un mese senza panca è un'assenza, non uno stallo.
GIORNI_MINIMI = 21

#: Il buco che **spezza** la serie: oltre questo, si riparte a contare.
#:
#: Non è una terza condizione della finestra, è ciò che decide *dove* la
#: finestra può cominciare. Chi torna in palestra dopo due mesi non porta con
#: sé il proprio massimale di prima, e una finestra a cavallo dello stacco
#: misurerebbe la pausa invece dell'allenamento.
BUCO_MASSIMO_GIORNI = 28

#: La tolleranza con cui ADR-0004 chiama **piatta** una finestra: il massimale
#: non supera il massimo di finestra oltre il 2%.
#:
#: Qui non serve a etichettare — l'etichetta dal futuro è materia di fase 4 —
#: serve a non inventare un secondo numero: vedi `SOGLIA_REGRESSIONE`.
TOLLERANZA_PIATTA_PCT = 2.0

#: Sotto quale pendenza (**% a settimana**) una finestra si dice *in regressione*.
#:
#: Non è un numero scelto: è `TOLLERANZA_PIATTA_PCT` distribuita sulla finestra
#: minima. Se ADR-0004 considera piatta una finestra che si muove entro il 2%,
#: allora una discesa è **netta** esattamente quando su 21 giorni supera quel
#: 2% — cioè quando esce dalla banda dentro cui il progetto ha già dichiarato
#: di non saper distinguere il movimento dal rumore.
#:
#: Scriverlo come divisione e non come `-0.67` è la parte che conta: un numero
#: letterale qui sarebbe la terza soglia inventata a mano del progetto, e
#: nessuno all'orale potrebbe dire da dove viene. Così, se la tolleranza o la
#: finestra minima cambiano, la regressione le segue senza che nessuno se ne
#: ricordi.
SOGLIA_REGRESSIONE = -TOLLERANZA_PIATTA_PCT / (GIORNI_MINIMI / 7)

#: I tre stati di progressione (`CONTEXT.md`). Costanti e non stringhe sparse:
#: la view e il template li confrontano, e `"non_stallo"` scritto a mano in un
#: `{% if %}` sbagliato sarebbe sempre falso senza segnalare niente — la
#: famiglia di guasto muto di `corpo_libero` al posto di `bodyweight` (#16).
STALLO = "stallo"
NON_STALLO = "non_stallo"
DATI_INSUFFICIENTI = "dati_insufficienti"


@dataclass(frozen=True)
class Sessione:
    """Un allenamento dentro la finestra, ridotto a ciò che il rilevamento vede.

    Tre campi e non la riga di A3 intera, perché questo è l'unico ingresso del
    rilevatore: tutto ciò che sta qui, un modello di fase 4 potrà guardarlo, e
    tutto ciò che non sta qui non potrà. Tenere il tipo stretto è il modo di
    non dover ricordare quel confine a mano.

    `giorno` è una **data locale**, non il `datetime` della riga di A3, e la
    conversione avviene qui una volta sola. La spec conta «21 giorni di
    **calendario**», e su datetime la sottrazione tronca le ore. Due sedute del 15 agosto alle 10 e
    del 5 settembre alle 8 distano 21 giorni sul calendario e 20 su
    `timedelta.days` — e la finestra della panca piana di `pk 64` prendeva
    davvero **sette** sedute dove sei bastavano, senza che niente lo
    segnalasse: sette sessioni sono una finestra legittima, solo non quella
    che la spec descrive. Il `datetime` non entra affatto: la finestra non ha
    niente da farci, e tenerlo accanto alla data sarebbe lasciare in giro
    l'unico oggetto con cui si può rifare lo stesso errore.

    `record` è il fatto che quella sessione abbia stabilito un **record
    personale**, e non si ricalcola: A3 annota già il massimo cumulativo
    (`record_a_quel_giorno`), e una sessione fa record esattamente quando quel
    massimo sale rispetto alla sessione prima. Costo: zero query, ed è la
    stessa lettura di #100 per il PR della pagina.
    """

    giorno: object
    massimale: float
    record: bool


@dataclass(frozen=True)
class Finestra:
    """La finestra di progressione: **solo** le sue sessioni, e per un motivo.

    ADR-0004 regge su una condizione sola — il rilevatore vede la finestra, e
    l'etichetta viene da dati che non ha visto. Se questo oggetto portasse
    l'intera storia, o anche solo un puntatore all'utente, quella condizione
    diventerebbe una promessa da mantenere a mano in ogni funzione a valle, e
    la fase 4 la romperebbe una volta senza che nessun test lo dica: una
    feature che sbircia il futuro non fa fallire niente, fa salire i numeri.

    Portando **solo** le sessioni della finestra, la condizione smette di
    essere una promessa e diventa una proprietà del tipo. È anche la ragione
    per cui `rileva_stallo` prende una `Finestra` e non `(user, exercise)`.

    Le sei feature della spec si calcolano tutte di qui: pendenza e varianza
    dalle coppie (giorno, massimale), le sessioni dall'ultimo record da
    `record`, la frazione del massimo di finestra da `massimo`, la frequenza
    da `giorni` e dal numero di sessioni. Il volume no — è l'unica delle sei
    che chiederebbe un dato in più, e la aggiungerà la fase 4 allargando
    questo tipo, che è esattamente il punto in cui si vuole che la modifica
    cada.
    """

    sessioni: tuple

    @property
    def giorni(self):
        """I giorni di calendario coperti, dalla prima all'ultima sessione."""
        return (self.sessioni[-1].giorno - self.sessioni[0].giorno).days

    @property
    def massimo(self):
        """Il massimo massimale stimato **della finestra** — la base del deload."""
        return max(sessione.massimale for sessione in self.sessioni)

    @property
    def sessioni_senza_record(self):
        """Da quante sessioni non si fa un record, contando dall'ultima indietro.

        Zero quando l'ultima sessione è essa stessa un record. È il numero che
        la regola a soglia confronta, ed è anche la terza delle sei feature
        della spec, che è il motivo per cui sta sul tipo e non dentro la regola.
        """
        quante = 0
        for sessione in reversed(self.sessioni):
            if sessione.record:
                return quante
            quante += 1
        return quante

    @property
    def pendenza(self):
        """La pendenza relativa del massimale, in **% a settimana**.

        La prima delle sei feature, e quella che regge l'etichetta descrittiva
        «in regressione». Retta ai minimi quadrati sulle coppie (giorni
        dall'inizio, massimale), poi normalizzata sul massimale medio: senza
        normalizzare, mezzo chilo a settimana sarebbe una pendenza enorme sulle
        alzate laterali e invisibile sullo stacco, e le due non si potrebbero
        confrontare né mettere nella stessa feature.

        **Solo `Sum` e `Count`**, che è il vincolo che `04-analisi.md` impone
        alla pendenza perché SQLite non ha `stddev`. Qui gira in Python su
        righe già in mano — la pagina le ha materializzate per il grafico — e
        la formula è la stessa: tenerla in questa forma significa che la fase
        4, che dovrà calcolarla nell'ORM su 1904 finestre, riscrive una query
        e non una definizione.

        Il denominatore non può essere zero: `giorni >= GIORNI_MINIMI` per
        costruzione, quindi le sessioni non stanno tutte sullo stesso giorno.
        """
        n = len(self.sessioni)
        origine = self.sessioni[0].giorno
        x = [(sessione.giorno - origine).days for sessione in self.sessioni]
        y = [sessione.massimale for sessione in self.sessioni]

        somma_x, somma_y = sum(x), sum(y)
        somma_xy = sum(xi * yi for xi, yi in zip(x, y))
        somma_xx = sum(xi * xi for xi in x)

        kg_al_giorno = (n * somma_xy - somma_x * somma_y) / (
            n * somma_xx - somma_x * somma_x
        )
        return kg_al_giorno * 7 / (somma_y / n) * 100

    @property
    def discesa(self):
        """La pendenza col segno girato, per la frase «scende del 3,2%».

        Esiste solo perché il template non ha un valore assoluto, e «scende di
        -3,2% a settimana» è una doppia negazione: si legge una volta e si
        rilegge. Sta qui e non nella view perché è la stessa quantità, detta
        nel verso in cui la pagina la pronuncia — e ha senso solo dove
        `in_regressione` è vero, che è l'unico posto da cui si chiama.
        """
        return -self.pendenza

    @property
    def in_regressione(self):
        """La pendenza è nettamente in discesa — vedi `SOGLIA_REGRESSIONE`.

        **Convive con lo stallo, non lo sostituisce.** ADR-0004 tiene le classi
        binarie apposta: una terza classe «regressione» chiederebbe una seconda
        soglia appresa e renderebbe illeggibile la riga della matrice di
        confusione che interessa. Questa è un'osservazione **calcolata**, che
        si mostra in pagina e non entra mai in un training set.
        """
        return self.pendenza < SOGLIA_REGRESSIONE


def rileva_stallo(finestra):
    """**La regola a soglia — ed è l'unica funzione che la fase 4 sostituisce.**

    «Nessun record nelle ultime `SESSIONI_SENZA_RECORD_PER_STALLO` sessioni
    della finestra». Una riga, e tutto il resto di questo file — la finestra,
    la serie spezzata dal buco, lo stato, l'avanzamento — resta in piedi
    identico quando al posto di questa riga ci sarà un prodotto scalare di
    coefficienti appresi (ADR-0005).

    **È qui che si taglia, e la firma è la parte importante.** Prende una
    `Finestra` e restituisce un `bool`:

    - **una `Finestra` e non `(user, exercise)`**, perché così non ha modo di
      guardare nulla che la finestra non contenga — la condizione di ADR-0004
      diventa una proprietà del tipo invece che una promessa;
    - **una `Finestra` e non le sei feature già estratte**, perché scegliere
      le feature è mestiere del rilevatore: la regola a soglia ne usa una sola,
      il modello ne userà sei, e una firma che le elencasse costringerebbe la
      fase 4 a cambiare *questa* riga oltre alla propria;
    - **un `bool` e non un punteggio**, perché ADR-0004 tiene le classi binarie
      e la pagina mostra uno stato, non una probabilità. Se la fase 4 volesse
      una confidenza, allargare il tipo di ritorno è un cambiamento che si
      vede; restituire un `float` da una funzione che si chiama `rileva_` non
      lo sarebbe.

    Il numero `N` sta in cima a questo file, scelto alla cieca e in un commit
    precedente a questo: la ragione è tutta lì.

    ### Quale «record», e perché quello di sempre

    Il record è il **massimo cumulativo di sempre** (A3, `#100`), non il
    massimo della finestra. Le due letture divergono su chi è tornato sotto un
    picco vecchio: col massimo di finestra costui rifà record appena risale un
    po', col massimo di sempre no.

    Vince quello di sempre per una ragione di pagina, non di teoria: è il
    numero che il dettaglio esercizio mostra due riquadri sopra, sotto la
    scritta «Il tuo record». Un baseline che dicesse «nessun record da 3
    sessioni» mentre la stessa pagina ne festeggia uno sarebbe una
    contraddizione visibile, e il progetto non ha un secondo posto in cui
    spiegare che «record» qui vuol dire un'altra cosa.

    L'etichetta di fase 4 userà invece il **massimo di finestra**, perché
    ADR-0004 la definisce così, e la differenza è dichiarata e non riconciliata
    — come le due finestre della costanza (#112). Sono due domande diverse:
    l'etichetta chiede se la finestra è piatta *rispetto a sé stessa*, il
    baseline chiede se l'utente sta ancora migliorando.
    """
    return finestra.sessioni_senza_record >= SESSIONI_SENZA_RECORD_PER_STALLO


def _sessioni(righe):
    """Le righe di A3 tradotte in `Sessione`, col record già segnato.

    Una passata sola su tutta la storia: `record_a_quel_giorno` è il massimo
    cumulativo, quindi una sessione ha fatto record esattamente quando quel
    massimo **sale** rispetto alla riga prima. La prima sessione in assoluto fa
    record per definizione — è il momento in cui il record nasce.

    Il confronto è `>` e non `>=` di proposito: ripetere il proprio massimale
    non è un record, ed è precisamente il caso che la regola a soglia deve
    saper vedere.
    """
    sessioni = []
    massimo_precedente = None
    for riga in righe:
        cumulativo = riga["record_a_quel_giorno"]
        sessioni.append(
            Sessione(
                giorno=timezone.localtime(riga["started_at"]).date(),
                massimale=riga["massimale"],
                record=massimo_precedente is None or cumulativo > massimo_precedente,
            )
        )
        massimo_precedente = cumulativo
    return sessioni


def serie_corrente(sessioni):
    """L'ultimo tratto ininterrotto: da dove la finestra può cominciare.

    Si scorre all'indietro dall'ultima sessione e ci si ferma al primo buco
    oltre `BUCO_MASSIMO_GIORNI`. Quello che sta prima del buco non è storia
    vecchia da pesare meno: è storia di **un altro** tratto di allenamento, e
    farla entrare significherebbe misurare la pausa.

    Lista vuota in ingresso, lista vuota in uscita: è la coppia (utente,
    esercizio) mai registrata, che non è un caso d'errore.
    """
    if not sessioni:
        return []
    inizio = 0
    for i in range(len(sessioni) - 1, 0, -1):
        buco = (sessioni[i].giorno - sessioni[i - 1].giorno).days
        if buco > BUCO_MASSIMO_GIORNI:
            inizio = i
            break
    return sessioni[inizio:]


def finestra_di_progressione(serie):
    """La finestra: il **suffisso più corto** che soddisfa entrambi i vincoli.

    Si cresce all'indietro dall'ultima sessione finché non si hanno almeno
    `ALLENAMENTI_MINIMI` allenamenti **e** almeno `GIORNI_MINIMI` giorni.
    `None` quando la serie corrente non basta a soddisfarli.

    ### Perché il suffisso minimo e non le ultime sei, misurato

    «≥ 6 allenamenti **e** ≥ 21 giorni» si può leggere in due modi: sei
    sessioni fisse da validare sul calendario, oppure quante ne servono per
    coprire entrambi i minimi. La spec elenca i due vincoli in tabella e non
    dice quale.

    La differenza non è teorica, e sull'utente della demo si vede: `pk 64` si
    allena quattro volte a settimana, e sulle 28 coppie (utente, esercizio) del
    suo storico le ultime **sei** sedute stanno in **meno di 21 giorni** in due
    casi — pulley basso (19 giorni) e stacco da terra (18). Con la finestra
    fissa a sei, quei due esercizi mostrerebbero «dati insufficienti» per
    sempre, e — questa è la parte che decide — **allenandosi di più
    peggiorerebbero**: sei sedute più ravvicinate coprono meno giorni, quindi
    la barra di avanzamento andrebbe all'indietro proprio mentre l'utente fa
    la cosa giusta. Col suffisso minimo quei due prendono sette sessioni e
    rispondono.

    Il costo è che la finestra non ha più larghezza costante fra un esercizio e
    l'altro. Va bene qui, dove la domanda è *questo utente su questo esercizio
    adesso*, e la pagina dichiara quante sessioni ha guardato. La fase 4, che
    etichetta finestre a scorrimento e ha bisogno che siano confrontabili fra
    loro, userà la sua — «finestre consecutive condividono cinque punti su
    sei» è una frase su quelle, non su questa.
    """
    for quante in range(ALLENAMENTI_MINIMI, len(serie) + 1):
        candidata = serie[-quante:]
        if (candidata[-1].giorno - candidata[0].giorno).days >= GIORNI_MINIMI:
            return Finestra(sessioni=tuple(candidata))
    return None


@dataclass(frozen=True)
class StatoProgressione:
    """Cosa Progressive dice di una coppia (utente, esercizio), oggi.

    `stato` è uno dei tre di `CONTEXT.md`, e il terzo — `DATI_INSUFFICIENTI` —
    **non è un modo educato di dire «non stallo»**: è l'ammissione che la
    domanda non ha ancora risposta. La differenza si vede in pagina: `stallo` e
    `non_stallo` sono verdetti, `dati_insufficienti` è una barra di
    avanzamento, e i campi `allenamenti` e `giorni` esistono per disegnarla.

    `finestra` è nulla esattamente quando lo stato è `DATI_INSUFFICIENTI`: non
    c'è verdetto perché non c'è la finestra su cui darlo. È anche il campo che
    #115 legge per il deload — ma **non** attraverso `Finestra.massimo`, come
    questa riga si aspettava: quello è il massimo *massimale stimato*, e il 90%
    di un massimale supera il carico che l'ha prodotto per ogni serie da quattro
    ripetizioni in su. Il deload legge i **giorni** della finestra e ci chiede
    sopra i carichi di lavoro. Le due letture di «massimo di finestra» restano
    diverse e dichiarate.

    `in_regressione` è un'etichetta descrittiva e vive accanto allo stato, mai
    dentro: si può essere in stallo e in regressione, in regressione senza
    stallo (si scende, ma un record recente c'è stato), o in stallo senza
    regressione, che è il caso tipico — piatto.
    """

    stato: str
    allenamenti: int
    giorni: int
    finestra: object = None
    in_regressione: bool = False

    @property
    def deciso(self):
        """Vero quando c'è un verdetto — cioè quando la finestra esiste."""
        return self.stato != DATI_INSUFFICIENTI

    @property
    def e_stallo(self):
        """Vero solo sul verdetto di stallo — la forma che un template sa leggere.

        Il template non può importare `STALLO`, e `{% if stato.stato == "stallo" %}`
        sarebbe la costante riscritta a mano in un posto dove uno scarto di
        battitura non fallisce: sarebbe solo sempre falso. Due proprietà
        (`deciso`, `e_stallo`) coprono i tre stati senza che la stringa esca
        mai da questo file.
        """
        return self.stato == STALLO

    @property
    def avanzamento(self):
        """*«4 allenamenti su 6 — 12 giorni su 21»*, la frase della spec.

        Si costruisce anche a finestra piena, e non è sprecato: quando lo stato
        è deciso diventa la dichiarazione di **quanto** il verdetto ha
        guardato, che è il numero senza cui un verdetto non si distingue da uno
        inventato — la stessa ragione per cui un `Consiglio` porta la sua
        `misura`.
        """
        allenamento = "allenamento" if self.allenamenti == 1 else "allenamenti"
        giorno = "giorno" if self.giorni == 1 else "giorni"
        if self.deciso:
            return (
                f"{self.allenamenti} {allenamento} in {self.giorni} {giorno}"
            )
        return (
            f"{self.allenamenti} {allenamento} su {ALLENAMENTI_MINIMI} — "
            f"{self.giorni} {giorno} su {GIORNI_MINIMI}"
        )


def stato_progressione(user, exercise, righe=None):
    """Lo stato di progressione di una coppia (utente, esercizio).

    `righe` sono le righe di A3 (`analytics/progressione.progressione`) quando
    il chiamante le ha già: il dettaglio esercizio le materializza comunque per
    il grafico, e questa funzione gli costa allora **zero query**. È lo stesso
    patto di `consiglio_per_dashboard(user, heatmap=...)` in #112, e per la
    stessa ragione: non è una cache — non sopravvive alla richiesta — è il
    chiamante che passa una risposta che ha già in mano.

    Senza `righe` la query la fa lei, ed è il ramo che serve al coach (#115),
    che parla anche dove A3 non è stata calcolata. `user` e `exercise` restano
    in firma proprio per quel ramo: sono gli unici due argomenti con cui A3 si
    interroga.

    **Il rilevamento vero non è qui**, è in `rileva_stallo`. Questa funzione
    decide *se* c'è una finestra e traduce il verdetto in qualcosa che una
    pagina sa disegnare; la fase 4 non la tocca.
    """
    if righe is None:
        righe = analytics_progressione.progressione(user, exercise)

    serie = serie_corrente(_sessioni(list(righe)))
    if not serie:
        return StatoProgressione(stato=DATI_INSUFFICIENTI, allenamenti=0, giorni=0)

    finestra = finestra_di_progressione(serie)
    if finestra is None:
        # L'avanzamento si misura sulla **serie corrente**, non su tutta la
        # storia: dopo un buco di due mesi il conto riparte, e mostrarlo è
        # l'unico modo perché la barra corrisponda a ciò che la regola guarda.
        return StatoProgressione(
            stato=DATI_INSUFFICIENTI,
            allenamenti=len(serie),
            giorni=(serie[-1].giorno - serie[0].giorno).days,
        )

    return StatoProgressione(
        stato=STALLO if rileva_stallo(finestra) else NON_STALLO,
        allenamenti=len(finestra.sessioni),
        giorni=finestra.giorni,
        finestra=finestra,
        in_regressione=finestra.in_regressione,
    )
