"""La doppia progressione — l'unica regola di carico del progetto.

Prima salgono le **ripetizioni**, poi il **carico**. È la regola di
`docs/spec/05-coach-e-stallo.md`, ed è l'ultima delle quattro per priorità
perché è quella che scatta per quasi tutti: chi ha registrato una serie di
lavoro ha un consiglio di carico, sempre.

Ha un modulo suo — e non due funzioni in `__init__.py` come la costanza e lo
squilibrio — per la regola del pacchetto: **un tipo di consiglio guadagna un
modulo solo se ha una query propria**. Questa ce l'ha, ed è l'unica cosa che
sa chiedere al database che nessun'altra analisi chiede: non «quanto sei
forte», ma «cosa hai fatto **l'ultima volta**».

## Il numero che esce di qui è quello che l'utente riscrive nel form

Non passa da `EFFECTIVE_LOAD`. Il carico effettivo somma il peso corporeo sul
corpo libero (ADR-0006) ed è la definizione giusta per il volume e per il
massimale, dove la domanda è *quanto hai spostato*; qui la domanda è *cosa
scrivo la prossima volta*, e la risposta deve stare nella stessa unità della
casella: `weight`, bilanciere compreso (`WorkoutSet.weight`). Un consiglio che
dicesse «sali a 106,5 kg» a chi ha fatto trazioni con 10,5 kg di zavorra
sarebbe aritmeticamente ineccepibile e inservibile.

Per la stessa ragione **non si arrotonda niente**: il carico proposto è un
carico che l'utente ha davvero sollevato più un `Equipment.load_increment_kg`,
quindi resta sulla griglia dei dischi per costruzione. L'arrotondamento serve
al deload, che parte da un massimo *calcolato* — ed è materia sua.

## Il target viene dalla scheda dell'ultimo allenamento, e sui dati veri non c'è

L'allenamento è un log immutabile e conserva la scheda da cui è nato
(ADR-0002), quindi con lo stesso esercizio in più schede **non serve nessuna
regola di precedenza**: si guarda la scheda di *quell'*allenamento lì. ADR-0002
avverte che «pianificato vs eseguito» non è affidabile sul passato, ma qui non
si giudica il passato: si propone la prossima sessione (ADR-0007).

**Misurato il 2026-09-09 sul database della demo: 0 allenamenti su 11.855 hanno
una scheda collegata.** Il generatore sintetico (#18) crea schede e allenamenti
senza legarli, e l'import da Overload non ha una scheda da portarsi dietro. La
conseguenza è che il ramo «target dalla scheda» esiste, è testato, ed è
**invisibile alla demo**: la pagina che si guarda all'orale gira sul ramo
dell'allenamento libero. Il consiglio lo dichiara in `limite`, invece di far
finta di aver letto un target che non c'era.

## Il carico della sessione è il **massimo** fra le serie di lavoro completate

Con serie a carichi diversi — una discesa, un back-off — «tutte le serie hanno
raggiunto il target» sarebbe falso per sempre, e il coach direbbe «una
ripetizione in più» a vita senza che niente lo segnali. La sessione è quindi
riassunta dalla sua **serie di punta**: il carico è il massimo fra le serie
completate, e le ripetizioni che contano sono quelle eseguite a quel carico.

Il massimo si prende **fra le completate** e non fra tutte, o una serie di
punta saltata sposterebbe il carico di riferimento su un numero che l'utente
non ha sollevato, lasciando la sessione senza nemmeno una ripetizione da
leggere.

Misurato il 2026-09-09: sulle **82.180** coppie (allenamento, esercizio) del
database, le serie di lavoro completate stanno **tutte** a un carico solo.
Questa regola quindi oggi non cambia un singolo consiglio — è una guardia, non
un comportamento, e va detto: il generatore sintetico non produce discese, ma
un log vero importato da Overload può, e senza la riga il coach direbbe «una
ripetizione in più» per sempre alla prima serie discendente che incontra.

## Le serie non eseguite

Non entrano nel conto — è il filtro universale di #13 — e quando **nessuna** è
stata completata diventano il quarto caso: la scorsa volta il piano non ha
retto, e il coach non fa salire niente. È l'unico punto del progetto in cui
l'aderenza al piano è un dato e non uno scarto.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import OuterRef, Subquery

from training.analytics.coach.consiglio import Consiglio
from training.models import RoutineExercise, Workout, WorkoutSet

#: Quante sessioni servono: la scorsa e quella prima. La seconda la usa solo il
#: ramo dell'allenamento libero, che confronta due sessioni consecutive, e per
#: leggerle non serve una finestra — `Lag` risponderebbe alla stessa domanda su
#: tutta la storia, che è la domanda di A3, non questa. Due righe si leggono in
#: Python, e sono le stesse due righe che gli altri tre casi materializzano
#: comunque.
SESSIONI_LETTE = 2

#: Il tipo di serie su cui la regola lavora. **Non** `working()`: quel metodo
#: filtra anche `is_completed=True`, e una sessione in cui non è stato
#: completato niente è esattamente il quarto caso — sparirebbe proprio la
#: sessione a cui il coach deve rispondere.
SERIE_DI_LAVORO = WorkoutSet.SetType.WORKING


@dataclass(frozen=True)
class Sessione:
    """Una sessione di quell'esercizio, ridotta a ciò che la regola guarda.

    `ripetizioni` è vuota **se e solo se** `nessuna_completata` è vera: i due
    campi escono dalla stessa lista in `_riassumi`, e tenerli coerenti è ciò
    che permette agli altri tre casi di chiamare `min()` senza guardarsi le
    spalle.
    """

    quando: object
    carico: Decimal
    #: Le ripetizioni delle serie di lavoro **completate** al carico di punta,
    #: nell'ordine in cui sono state fatte.
    ripetizioni: tuple
    #: Gli estremi del range della scheda di *quell'*allenamento, nulli quando
    #: l'allenamento era libero — che sui dati veri è sempre.
    target_reps: int = None
    target_reps_max: int = None
    #: Nessuna serie di lavoro completata: il quarto caso.
    nessuna_completata: bool = False
    #: Quante serie di lavoro c'erano in tutto, completate o no.
    serie_totali: int = 0


def _kg(valore):
    """`Decimal("57.50")` → `«57,5»`.

    Un carico scritto `57.50 kg` dentro una frase italiana si legge come un
    prezzo, e i decimali finti sono rumore in un numero che va riscritto a mano
    sul telefono in palestra.
    """
    return f"{Decimal(valore).normalize():f}".replace(".", ",")


def _carico_in_frase(carico):
    """Zero non è un carico mancante, è il corpo libero (#13): scriverlo
    «0 kg» sarebbe l'unico posto della pagina in cui un dato vero sembra un
    buco."""
    return "a corpo libero" if Decimal(carico) == 0 else f"{_kg(carico)} kg"


def sessioni_recenti(user, exercise, quante=SESSIONI_LETTE):
    """Le ultime `quante` sessioni di quell'esercizio, la più recente per prima.

    **Due query, e non crescono con lo storico.** La prima sceglie gli
    allenamenti — `pk__in` su una subquery e mai un join a `sets`, che è la
    trappola già pagata da A3 (#98): il join duplica l'allenamento una volta
    per serie, e qui il duplicato non si vedrebbe nemmeno, perché uno `[:2]`
    su righe doppie restituisce **una** sessione sola credendo di averne due.

    La seconda legge le serie di quegli allenamenti e si porta dietro il target
    della scheda con due `Subquery` correlate su `workout__routine`, invece di
    una terza query: la scheda dell'allenamento è nulla nella stragrande
    maggioranza dei casi, e chiedere una riga che di solito non c'è vale meno
    di una colonna che di solito è nulla.
    """
    allenamenti = list(
        Workout.objects.filter(
            user=user,
            pk__in=WorkoutSet.objects.filter(
                exercise=exercise, set_type=SERIE_DI_LAVORO
            ).values("workout_id"),
        ).order_by("-started_at")[:quante]
    )
    if not allenamenti:
        return []

    voce_di_scheda = RoutineExercise.objects.filter(
        routine=OuterRef("workout__routine"), exercise=exercise
    )
    serie = (
        WorkoutSet.objects.filter(
            workout__in=allenamenti, exercise=exercise, set_type=SERIE_DI_LAVORO
        )
        .annotate(
            reps_minime=Subquery(voce_di_scheda.values("target_reps")[:1]),
            reps_massime=Subquery(voce_di_scheda.values("target_reps_max")[:1]),
        )
        .order_by("set_number")
    )

    per_allenamento = {}
    for riga in serie:
        per_allenamento.setdefault(riga.workout_id, []).append(riga)

    return [
        _riassumi(allenamento, per_allenamento[allenamento.pk])
        for allenamento in allenamenti
        if allenamento.pk in per_allenamento
    ]


def _riassumi(allenamento, righe):
    """Una sessione: il carico di punta, e le ripetizioni fatte a quel carico."""
    completate = [
        riga
        for riga in righe
        if riga.is_completed and riga.reps is not None and riga.weight is not None
    ]
    if completate:
        carico = max(riga.weight for riga in completate)
        ripetizioni = tuple(
            riga.reps for riga in completate if riga.weight == carico
        )
    else:
        # Il quarto caso: il carico serve solo per dire «riprova questo», e
        # l'unico disponibile è quello che era scritto sulle serie saltate.
        carichi = [riga.weight for riga in righe if riga.weight is not None]
        carico = max(carichi) if carichi else Decimal(0)
        ripetizioni = ()

    return Sessione(
        quando=allenamento.started_at,
        carico=carico,
        ripetizioni=ripetizioni,
        target_reps=righe[0].reps_minime,
        target_reps_max=righe[0].reps_massime,
        nessuna_completata=not completate,
        serie_totali=len(righe),
    )


def esercizio_piu_recente(user):
    """L'esercizio che l'utente ha allenato per ultimo, o `None`.

    È la scelta di **quale** esercizio porta il consiglio di carico in
    dashboard, dove non c'è una pagina a dirlo. «Il più recentemente allenato»
    ha una query dietro e una definizione sola; «l'esercizio principale» ne
    avrebbe tre — più serie, più volume, più recente — di cui nessuna misurata,
    e sceglierne una sarebbe inventare una gerarchia.

    Il pari dentro l'allenamento lo scioglie **l'ordine di registrazione**
    (`-id`): dentro un allenamento non esiste un campo che ordini gli esercizi
    — `set_number` riparte da 1 per ognuno — e l'ordine in cui le serie sono
    state scritte è l'unica traccia di quale sia venuto per ultimo. È una
    definizione debole, e sta qui in una riga invece che sparsa in una view.

    Come in `sessioni_recenti`, **non** `working()`: la sessione in cui non è
    stato completato niente è quella a cui il quarto caso risponde, e filtrarla
    via qui zittirebbe il consiglio proprio quando ha più da dire.
    """
    ultima = (
        WorkoutSet.objects.filter(workout__user=user, set_type=SERIE_DI_LAVORO)
        .select_related("exercise__equipment")
        .order_by("-workout__started_at", "-id")
        .first()
    )
    return ultima.exercise if ultima is not None else None


def consiglio_di_carico(user, exercise):
    """La doppia progressione su una coppia (utente, esercizio), o `None`.

    `None` solo quando l'esercizio non è mai stato registrato con una serie di
    lavoro: lì non c'è un ultimo carico, e inventare un punto di partenza
    sarebbe l'unico modo in cui questo consiglio può essere *falso* invece che
    prudente.

    I quattro casi, nell'ordine in cui si escludono:

    1. **Nessuna serie completata** la scorsa volta → si riprova lo stesso
       carico. Viene per primo perché le ripetizioni di quella sessione non
       esistono: non c'è niente da confrontare, e qualunque altro ramo
       leggerebbe una lista vuota.
    2. **Attrezzo a incremento zero** → il consiglio resta sulle ripetizioni,
       sempre, e il limite si dichiara. Viene prima del confronto perché
       nessun esito del confronto può farlo cambiare: su `band` e `bodyweight`
       il carico non ha un passo con cui salire.
    3. **Le ripetizioni sono arrivate** — al `target_reps_max` della scheda o,
       senza scheda, allo stesso carico di una sessione fa senza calare — → il
       carico sale di un incremento.
    4. **Altrimenti**: stesso carico, una ripetizione in più.
    """
    sessioni = sessioni_recenti(user, exercise)
    if not sessioni:
        return None

    ultima = sessioni[0]
    precedente = sessioni[1] if len(sessioni) > 1 else None
    incremento = exercise.equipment.load_increment_kg
    quando = f"il {ultima.quando:%d/%m/%Y}"

    if ultima.nessuna_completata:
        return Consiglio(
            tipo="carico",
            titolo="Riprova lo stesso carico",
            azione=(
                f"Ripeti {_carico_in_frase(ultima.carico)} su {exercise.name}: "
                "la scorsa volta nessuna serie di lavoro è arrivata in fondo, "
                "e il carico non sale su una sessione che non ha retto."
            ),
            misura=f"0 serie di lavoro completate su {ultima.serie_totali}, {quando}",
            esercizio=exercise,
        )

    sale, misura, limite = _valuta(ultima, precedente, quando)

    if incremento == 0:
        return Consiglio(
            tipo="carico",
            titolo="Aggiungi una ripetizione",
            azione=(
                f"Continua {_carico_in_frase(ultima.carico)} su "
                f"{exercise.name} e aggiungi una ripetizione: su "
                f"{exercise.equipment.label_it} il carico non ha un passo con "
                "cui salire."
            ),
            misura=misura,
            limite=_limite_incremento_zero(exercise, limite),
            esercizio=exercise,
        )

    if sale:
        riparti = (
            f" e riparti da {ultima.target_reps} ripetizioni."
            if ultima.target_reps
            else ": che le ripetizioni calino è previsto, ed è il segno che il "
            "carico è salito davvero."
        )
        return Consiglio(
            tipo="carico",
            titolo="Sali di carico",
            azione=(
                f"Passa a {_kg(ultima.carico + incremento)} kg su "
                f"{exercise.name} ({_kg(ultima.carico)} + {_kg(incremento)}, "
                f"l'incremento di {exercise.equipment.label_it}){riparti}"
            ),
            misura=misura,
            limite=limite,
            esercizio=exercise,
        )

    return Consiglio(
        tipo="carico",
        titolo="Stesso carico, una ripetizione in più",
        azione=(
            f"Ripeti {_carico_in_frase(ultima.carico)} su {exercise.name} e "
            f"punta a {_traguardo(ultima, precedente)} ripetizioni su tutte le "
            "serie di lavoro: il carico sale quando ci arrivi."
        ),
        misura=misura,
        limite=limite,
        esercizio=exercise,
    )


def _traguardo(ultima, precedente):
    """Le ripetizioni a cui puntare quando il carico non sale.

    Con la scheda è il `target_reps_max`, che è il numero scritto. Senza, è la
    **serie migliore già fatta a quel carico** — nelle due sessioni lette — e
    non un numero inventato: il coach chiede di portare tutte le serie dove una
    è già arrivata, che è esattamente la doppia progressione detta senza scheda.

    Il `+1` sulla serie più debole è il pavimento del caso in cui la migliore
    coincide con la peggiore: senza, il consiglio direbbe «punta a 8» a chi ha
    appena fatto 8/8/8, cioè «rifai identico».
    """
    if ultima.target_reps_max:
        return ultima.target_reps_max

    fatte = ultima.ripetizioni
    if precedente is not None and precedente.carico == ultima.carico:
        fatte = fatte + precedente.ripetizioni
    return max(max(fatte), min(ultima.ripetizioni) + 1)


def _valuta(ultima, precedente, quando):
    """Il cuore: le ripetizioni sono arrivate, sì o no — e con quale misura.

    Due rami, e la differenza non è il criterio ma **cosa c'è da leggere**: con
    una scheda il traguardo è scritto (`target_reps_max`), senza scheda il
    traguardo è la sessione precedente. In entrambi i casi la sessione è
    giudicata dalla sua **serie più debole**: la doppia progressione chiede il
    target *su tutte le serie di lavoro*, e prendere la serie migliore farebbe
    salire il carico a chi ha fatto un set buono e poi è crollato.
    """
    ripetizioni = ultima.ripetizioni
    conteggio = "/".join(str(n) for n in ripetizioni)

    if ultima.target_reps_max:
        misura = (
            f"{_kg(ultima.carico)} kg × {conteggio} ripetizioni, "
            f"target {ultima.target_reps_max}, {quando}"
        )
        return all(n >= ultima.target_reps_max for n in ripetizioni), misura, ""

    limite = (
        "L'ultimo allenamento non era su scheda: senza un target di "
        "ripetizioni il coach confronta le ultime due sessioni allo stesso "
        "carico, che è una regola più prudente."
    )

    if precedente is None:
        misura = (
            f"{_kg(ultima.carico)} kg × {conteggio} ripetizioni, {quando} — "
            "prima sessione registrata su questo esercizio"
        )
        return False, misura, limite

    if precedente.carico != ultima.carico:
        # **Non** «primo passaggio a questo carico»: sarebbe falso e
        # invisibile. La regola guarda due sessioni, non tutta la storia, e un
        # carico può essere già stato usato dieci volte più indietro — dirlo
        # «primo» sarebbe un consiglio giusto con sotto un numero sbagliato,
        # cioè il guasto contro cui esiste il campo `misura`.
        misura = (
            f"{_kg(ultima.carico)} kg × {conteggio} ripetizioni {quando}, "
            f"ma la sessione prima era {_carico_in_frase(precedente.carico)}: "
            "lo stesso carico non è ancora stato ripetuto due volte di fila"
        )
        return False, misura, limite

    if not precedente.ripetizioni:
        misura = (
            f"{_kg(ultima.carico)} kg × {conteggio} ripetizioni, {quando} — "
            "la sessione prima non ha completato nessuna serie"
        )
        return False, misura, limite

    misura = (
        f"{_kg(ultima.carico)} kg due volte di fila: "
        f"{'/'.join(str(n) for n in precedente.ripetizioni)} ripetizioni il "
        f"{precedente.quando:%d/%m/%Y}, {conteggio} {quando}"
    )
    return min(ripetizioni) >= min(precedente.ripetizioni), misura, limite


def _limite_incremento_zero(exercise, limite):
    """Il limite che questo ticket esiste per non lasciare muto.

    `data/catalog/equipment.csv` ha **due** attrezzi a incremento zero, non uno:
    il corpo libero **e l'elastico**. La spec parlava solo del corpo libero, e
    la differenza non è cosmetica — sul corpo libero il carico si muove
    comunque, perché la zavorra si scrive in `weight` e `EFFECTIVE_LOAD` somma
    il peso corporeo (ADR-0006); sull'**elastico** no, e senza questa riga il
    coach direbbe «una ripetizione in più» per sempre, per sempre corretto e
    per sempre inutile, senza che niente lo segnali. È la stessa famiglia di
    guasto muto di `corpo_libero` scritto al posto di `bodyweight` (#16).
    """
    proprio = (
        f"Su {exercise.equipment.label_it} l'incremento di carico è zero, "
        "quindi il coach può consigliare solo ripetizioni: quando diventano "
        "troppe, il passo dopo — una variante più difficile, o della zavorra — "
        "è una scelta che il coach non misura."
    )
    return f"{proprio} {limite}".strip()
