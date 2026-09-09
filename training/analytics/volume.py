"""A1 e A2 — il volume nel tempo e la sua distribuzione sui sei gruppi.

Le due analisi che aprono `/analisi/`. Sono la **stessa somma** guardata da due
versi: `Sum(VOLUME)` sulle serie di lavoro eseguite dell'utente, nella stessa
finestra temporale, raggruppata una volta per periodo e una volta per gruppo
muscolare. Che la finestra sia la stessa non è un dettaglio di comodità: le due
figure stanno una accanto all'altra, e se rispondessero su periodi diversi la
seconda spiegherebbe una prima che non è quella disegnata sopra.

Il volume arriva da `training/querysets.py` per nome (`VOLUME`), mai riscritto
qui — vedi il docstring del pacchetto.

## Il taglio, che è il parametro di tutto il modulo

Le stesse due somme si guardano su **dodici settimane** o su **dodici mesi**
(#106). Non sono due analisi: sono la stessa analisi a due risoluzioni, e il
modulo la scrive una volta sola parametrizzandola su un `Taglio` — la funzione
che tronca, quella che genera la finestra, e le etichette. Due coppie di
funzioni parallele sarebbero due definizioni di volume, che è esattamente
l'errore che #97 ha appena finito di pagare sulla dashboard.

## I buchi, che sono il punto

`TruncWeek` e `TruncMonth` restituiscono **solo i periodi in cui esiste almeno
una serie**. Una settimana saltata non compare fra le righe, e un grafico che
unisce i punti così com'escono disegna due settimane adiacenti che in realtà
distano un mese: cioè **mente, e mente proprio sulla costanza**, che è la prima
cosa che questa pagina dovrebbe far vedere.

Gli zeri li aggiunge Python **dopo** la query, in `volume_nel_tempo()`. È
presentazione, non calcolo: il database continua a fare l'aggregazione su
296.724 righe, e Python tocca dodici valori. La stessa struttura — una riga per
periodo, anche vuoto — è quella di cui la costanza (W1) avrà bisogno per
contare i giorni saltati, ed è la ragione per cui la finestra è una funzione a
sé e non tre righe dentro la view.

Sul taglio mensile il riempimento non può iterare a passo fisso come fa quello
settimanale: **i mesi non hanno tutti la stessa lunghezza**, quindi la finestra
si costruisce contando i mesi in aritmetica di calendario e non i giorni.

## Perché anche i gruppi a zero

A2 riempie i buchi come A1, ma il buco qui è di un'altra natura: i gruppi
muscolari sono **sei**, un insieme chiuso, e un gruppo assente da una `values()`
è indistinguibile da un gruppo che la pagina si è dimenticata di disegnare. Un
petto a zero è un'informazione — è la stessa che ADR-0006 racconta al contrario,
quando la schiena spariva perché il volume del corpo libero valeva zero.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable

from django.db.models import Sum
from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone

from training.models import MuscleGroup, WorkoutSet
from training.querysets import VOLUME

#: Quanti punti disegna la finestra, in **entrambi** i tagli.
#:
#: Dodici e non un numero per taglio: il grafico ha la stessa forma, e sotto
#: cambia solo quanto sta dentro un punto. Dodici settimane sono un trimestre —
#: abbastanza perché un buco si veda — e dodici mesi sono l'anno, che è il
#: taglio su cui una stagione di allenamento si legge come una storia.
PUNTI_DELLA_FINESTRA = 12

#: Il numero di settimane del taglio di default, il nome con cui #99 l'ha
#: scritto e con cui `docs/spec/04-analisi.md` lo cita. Resta come alias di
#: `PUNTI_DELLA_FINESTRA` perché il default non è cambiato: il toggle aggiunge
#: una scelta, non ne ribalta una.
SETTIMANE_DI_DEFAULT = PUNTI_DELLA_FINESTRA


def finestra_settimanale(settimane=PUNTI_DELLA_FINESTRA, oggi=None):
    """I **lunedì** della finestra, dal più vecchio al più recente.

    L'ultimo è il lunedì della settimana in corso, che è quindi **parziale**:
    la pagina lo dichiara invece di nasconderlo, perché troncare la finestra
    all'ultima settimana chiusa farebbe sparire dal grafico l'allenamento di
    stamattina — cioè l'unico dato che l'utente sta cercando quando apre la
    pagina.

    Lunedì e non «sette giorni fa» perché è la stessa griglia che usa
    `TruncWeek`, e due griglie diverse non si allineerebbero mai.

    `oggi` è iniettabile per i test: i dati sintetici finiscono a una data
    fissa, e una finestra ancorata a `now()` li farebbe uscire dal grafico col
    passare delle settimane.
    """
    oggi = oggi or timezone.localdate()
    lunedi = oggi - timedelta(days=oggi.weekday())
    return [lunedi - timedelta(weeks=n) for n in reversed(range(settimane))]


def finestra_mensile(mesi=PUNTI_DELLA_FINESTRA, oggi=None):
    """I **primi del mese** della finestra, dal più vecchio al più recente.

    La sorella mensile della precedente, e non si scrive allo stesso modo: un
    mese non è un numero fisso di giorni, quindi indietreggiare a passo di
    `timedelta` sbaglierebbe — trenta giorni prima del 31 marzo è il 1° marzo,
    non febbraio. Si conta in **mesi**, su un indice `anno * 12 + mese`, che è
    l'unica aritmetica di calendario senza casi limite.

    Come per le settimane l'ultimo punto è il mese **in corso**, e la pagina
    dichiara quanto ne è trascorso: su un mese il punto parziale può valere un
    trentesimo del periodo, e accanto a undici mesi pieni sembrerebbe un crollo
    (#106).
    """
    oggi = oggi or timezone.localdate()
    primo = oggi.replace(day=1)
    indice = primo.year * 12 + (primo.month - 1)
    return [
        date((indice - n) // 12, (indice - n) % 12 + 1, 1)
        for n in reversed(range(mesi))
    ]


@dataclass(frozen=True)
class Taglio:
    """A che risoluzione si guardano A1 e A2: la settimana o il mese.

    Tiene insieme le tre cose che cambiano fra i due tagli e **niente altro**:
    come il database tronca (`trunc`), quali periodi la finestra deve contenere
    anche se vuoti (`finestra`), e come si scrive un periodo in pagina. Il
    calcolo non ne sa nulla — `volume_nel_tempo()` è una funzione sola per
    entrambi.

    `chiave` è il valore che compare in querystring (`?periodo=mese`), quindi è
    **testo d'interfaccia stabile**: cambiarlo romperebbe i preferiti di chi ha
    salvato la pagina, che è tutto il motivo per cui lo stato sta nell'URL.
    """

    chiave: str
    singolare: str
    plurale: str
    trunc: Callable
    formato: str
    finestra: Callable
    #: Quanti giorni dura un periodo, o `None` se dipende dal periodo stesso.
    #: È l'unica asimmetria vera fra i due tagli: sette giorni sono sempre
    #: sette, un mese no, e da lì discende tutto il resto di questo ticket.
    giorni_fissi: int | None

    def giorni_del_periodo(self, inizio):
        """Quanto dura il periodo che comincia a `inizio`, in giorni."""
        return self.giorni_fissi or monthrange(inizio.year, inizio.month)[1]


SETTIMANA = Taglio(
    chiave="settimana",
    singolare="settimana",
    plurale="settimane",
    trunc=TruncWeek,
    # `3 mar`: su dodici settimane l'anno non serve, e le etichette corte
    # stanno sull'asse senza ruotare.
    formato="j M",
    finestra=finestra_settimanale,
    giorni_fissi=7,
)

MESE = Taglio(
    chiave="mese",
    singolare="mese",
    plurale="mesi",
    trunc=TruncMonth,
    # `mar 26`: su dodici mesi l'anno cambia in mezzo alla finestra, e senza
    # ci si troverebbero due mesi di gennaio indistinguibili.
    formato="M y",
    finestra=finestra_mensile,
    giorni_fissi=None,
)

#: I due tagli in ordine di presentazione, che è anche l'ordine del toggle.
TAGLI = (SETTIMANA, MESE)

#: **Dodici settimane**, deciso in #99 con la sua ragione: la finestra lunga
#: *nasconde* proprio il buco che questo modulo si dà la pena di riempire — una
#: settimana saltata dentro un punto mensile è un punto un po' più basso, non un
#: avvallamento — e su dodici mesi la figura leviga esattamente la costanza, che
#: è il primo consiglio del coach.
#:
#: Il default è l'**assenza** del parametro, non `?periodo=settimana`: è la
#: regola già presa per i filtri del catalogo (#71) e per `?esercizio=` sulla
#: classifica di forza, e tiene `/analisi/` un indirizzo solo invece di due che
#: mostrano la stessa pagina.
TAGLIO_DI_DEFAULT = SETTIMANA


def taglio_richiesto(chiave):
    """Il taglio chiesto in querystring, col default per tutto il resto.

    Un `?periodo=` che non esiste **non è un 404**: è la stessa regola dello
    slug fuori soglia sulla classifica di forza — una domanda malposta ha una
    risposta legittima, che è la pagina di default, non una porta sbattuta.
    """
    for taglio in TAGLI:
        if taglio.chiave == chiave:
            return taglio
    return TAGLIO_DI_DEFAULT


def altro_taglio(taglio):
    """L'altro dei due. Serve al vuoto, che deve saper suggerire l'alternativa."""
    return MESE if taglio is SETTIMANA else SETTIMANA


def inizio_della_finestra(finestra):
    """L'istante da cui filtrare, aware, dato l'elenco dei periodi.

    Un `datetime` e non una `date`: `started_at` è un `DateTimeField`, e
    confrontarlo con una data pura lascerebbe fuori l'allenamento del lunedì
    mattina, perché Django promuoverebbe la data a mezzanotte **UTC** e non a
    mezzanotte di Roma.
    """
    return timezone.make_aware(datetime.combine(finestra[0], time.min))


def volume_nel_tempo(user, taglio=TAGLIO_DI_DEFAULT, finestra=None, oggi=None):
    """A1 — il volume per periodo, **coi buchi riempiti**.

    Restituisce una riga per ogni periodo della finestra, in ordine
    cronologico, anche per i periodi senza allenamenti. Il database raggruppa,
    Python completa.

    Una funzione sola per i due tagli, e la differenza è tutta in
    `taglio.trunc`: scriverne due significherebbe scrivere `Sum(VOLUME)` due
    volte, cioè riaprire la strada alla divergenza che #97 ha appena chiuso.

    Le serie a corpo libero di un utente **senza peso corporeo dichiarato**
    hanno un carico effettivo nullo (ADR-0006), quindi la loro `Sum` è nulla e
    non entra: il volume di quell'utente è **incompleto, non zero**, ed è la
    pagina a doverlo dire — la stessa regola che #97 ha scritto sulla dashboard.
    """
    finestra = finestra or taglio.finestra(oggi=oggi)

    # `.order_by("periodo")` in coda non è cosmesi: `WorkoutSet.Meta.ordering`
    # vale `["set_number"]`, e Django lo trascinerebbe nel `GROUP BY`,
    # spaccando ogni periodo in una riga per numero di serie. È lo stesso
    # inciampo silenzioso delle due trappole di `04-analisi.md`: il conto
    # sarebbe sbagliato e la pagina si disegnerebbe lo stesso.
    righe = (
        WorkoutSet.objects.working()
        .filter(
            workout__user=user,
            workout__started_at__gte=inizio_della_finestra(finestra),
        )
        .annotate(periodo=taglio.trunc("workout__started_at"))
        .values("periodo")
        .annotate(volume=Sum(VOLUME))
        .order_by("periodo")
    )

    per_periodo = {
        data_locale(riga["periodo"]): riga["volume"] or 0.0 for riga in righe
    }
    return [
        {"periodo": inizio, "volume": round(per_periodo.get(inizio, 0.0), 1)}
        for inizio in finestra
    ]


def volume_per_gruppo(user, taglio=TAGLIO_DI_DEFAULT, finestra=None, oggi=None):
    """A2 — la distribuzione sui sei gruppi, nella **stessa** finestra di A1.

    Ordinata per volume decrescente: la domanda che la figura risponde è «cosa
    sto allenando di più», e l'ordine anatomico la renderebbe una tabella da
    leggere invece di una risposta da guardare. I gruppi a zero finiscono in
    coda da soli, e a parità restano nell'ordine del catalogo, o la pagina si
    riordinerebbe a ogni ricarica.

    Il taglio non entra nel raggruppamento — qui non si tronca niente — ma
    entra nella **finestra**, ed è l'unico modo perché A2 continui a spiegare
    l'A1 disegnata sopra invece di un'altra.

    Raggruppa per **id** del gruppo e non per `label_it`: l'etichetta è testo
    d'interfaccia e libera di cambiare, la chiave no.
    """
    finestra = finestra or taglio.finestra(oggi=oggi)

    righe = (
        WorkoutSet.objects.working()
        .filter(
            workout__user=user,
            workout__started_at__gte=inizio_della_finestra(finestra),
        )
        .values("exercise__primary_muscle__group")
        .annotate(volume=Sum(VOLUME))
        .order_by()
    )
    per_gruppo = {
        riga["exercise__primary_muscle__group"]: riga["volume"] or 0.0
        for riga in righe
    }

    # Il `code` esce insieme all'etichetta perché la riga è anche un **varco**:
    # dal gruppo si va al catalogo filtrato (`/esercizi/?gruppo=<code>`), che è
    # la regola di navigazione di `02-pagine-e-template.md` — nessun link
    # orfano, e nessuna analisi che sia un vicolo cieco.
    gruppi = [
        {
            "gruppo": gruppo.label_it,
            "codice": gruppo.code,
            "volume": round(per_gruppo.get(gruppo.pk, 0.0), 1),
            "ordine": gruppo.sort_order,
        }
        for gruppo in MuscleGroup.objects.all()
    ]
    gruppi.sort(key=lambda riga: (-riga["volume"], riga["ordine"]))
    return gruppi


def quanto_e_trascorso(taglio, finestra, oggi=None):
    """Quanti giorni dell'**ultimo** periodo sono passati, e quanti ne conta.

    L'ultimo punto della finestra è sempre parziale, e su base mensile lo è
    molto più che su base settimanale: il 2 del mese quel punto vale un
    trentesimo del periodo, e disegnato accanto a undici mesi pieni si legge
    come un crollo dell'allenamento invece che come un mese appena cominciato.

    Restituire i due numeri invece di una frase serve a dichiararlo per quello
    che è — «9 giorni su 30» — invece di un generico «parziale» che su dodici
    mesi non basta a distinguere un punto basso da un punto giovane.

    Il taglio della finestra **non** si sposta al periodo chiuso, che pure
    toglierebbe il problema: farebbe sparire dal grafico l'allenamento di
    stamattina, cioè l'unico dato che l'utente sta cercando quando apre la
    pagina — la stessa ragione per cui `finestra_settimanale()` arriva alla
    settimana in corso.
    """
    oggi = oggi or timezone.localdate()
    inizio = finestra[-1]
    giorni = taglio.giorni_del_periodo(inizio)
    return {"trascorsi": min((oggi - inizio).days + 1, giorni), "totali": giorni}


def data_locale(periodo):
    """L'inizio del periodo troncato dal database, come `date` locale.

    Pubblica e non più `_a_data` da #101: la costanza (W1) raggruppa per
    settimana come A1 e ha bisogno della stessa conversione. Una seconda copia
    di questa funzione sarebbe una seconda regola di fuso orario, cioè la
    divergenza di #75 nel punto in cui non si vede — le due misure
    sbaglierebbero settimana in due modi diversi, e solo d'inverno.

    Con `USE_TZ = True` la troncatura restituisce un `datetime` **aware** a
    mezzanotte di Roma: confrontarlo con una `date` senza passare da
    `localtime()` sposterebbe di un giorno i periodi d'inverno, e il buco
    finirebbe nella casella sbagliata.
    """
    if isinstance(periodo, datetime):
        return timezone.localtime(periodo).date()
    return periodo if isinstance(periodo, date) else None
