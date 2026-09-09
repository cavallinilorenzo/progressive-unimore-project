"""A1 e A2 — il volume nel tempo e la sua distribuzione sui sei gruppi.

Le due analisi che aprono `/analisi/`. Sono la **stessa somma** guardata da due
versi: `Sum(VOLUME)` sulle serie di lavoro eseguite dell'utente, nella stessa
finestra temporale, raggruppata una volta per settimana e una volta per gruppo
muscolare. Che la finestra sia la stessa non è un dettaglio di comodità: le due
figure stanno una accanto all'altra, e se rispondessero su periodi diversi la
seconda spiegherebbe una prima che non è quella disegnata sopra.

Il volume arriva da `training/querysets.py` per nome (`VOLUME`), mai riscritto
qui — vedi il docstring del pacchetto.

## I buchi, che sono il punto

`TruncWeek` restituisce **solo i periodi in cui esiste almeno una serie**. Una
settimana saltata non compare fra le righe, e un grafico che unisce i punti
così com'escono disegna due settimane adiacenti che in realtà distano un mese:
cioè **mente, e mente proprio sulla costanza**, che è la prima cosa che questa
pagina dovrebbe far vedere.

Gli zeri li aggiunge Python **dopo** la query, in `volume_per_settimana()`. È
presentazione, non calcolo: il database continua a fare l'aggregazione su
296.724 righe, e Python tocca dodici valori. La stessa struttura — una riga per
periodo, anche vuoto — è quella di cui la costanza (W1) avrà bisogno per
contare i giorni saltati, ed è la ragione per cui `finestra_settimanale()` è
una funzione a sé e non tre righe dentro la view.

## Perché anche i gruppi a zero

A2 riempie i buchi come A1, ma il buco qui è di un'altra natura: i gruppi
muscolari sono **sei**, un insieme chiuso, e un gruppo assente da una `values()`
è indistinguibile da un gruppo che la pagina si è dimenticata di disegnare. Un
petto a zero è un'informazione — è la stessa che ADR-0006 racconta al contrario,
quando la schiena spariva perché il volume del corpo libero valeva zero.
"""

from datetime import date, datetime, time, timedelta

from django.db.models import Sum
from django.db.models.functions import TruncWeek
from django.utils import timezone

from training.models import MuscleGroup, WorkoutSet
from training.querysets import VOLUME

#: La finestra di default di A1 e A2: **12 settimane**.
#:
#: `docs/spec/04-analisi.md` lascia la scelta fra 12 settimane e 12 mesi, con un
#: toggle che è fog dichiarata sulla mappa #96 e non si costruisce qui. Fra le
#: due, la settimana: la finestra lunga *nasconde* proprio il buco che questo
#: modulo si dà la pena di riempire — una settimana saltata dentro un punto
#: mensile è un punto un po' più basso, non un avvallamento — e su 12 mesi la
#: figura leviga esattamente la costanza, che è il primo consiglio del coach.
#:
#: Vale anche dal verso pratico: lo storico reale di Lorenzo è di 26 giorni, e
#: su una finestra annuale la propria demo sarebbe undici punti vuoti e uno pieno.
SETTIMANE_DI_DEFAULT = 12


def finestra_settimanale(settimane=SETTIMANE_DI_DEFAULT, oggi=None):
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


def inizio_della_finestra(settimane):
    """L'istante da cui filtrare, aware, dato l'elenco dei lunedì.

    Un `datetime` e non una `date`: `started_at` è un `DateTimeField`, e
    confrontarlo con una data pura lascerebbe fuori l'allenamento del lunedì
    mattina, perché Django promuoverebbe la data a mezzanotte **UTC** e non a
    mezzanotte di Roma.
    """
    return timezone.make_aware(datetime.combine(settimane[0], time.min))


def volume_per_settimana(user, settimane=None, oggi=None):
    """A1 — il volume settimanale, **coi buchi riempiti**.

    Restituisce una riga per ogni settimana della finestra, in ordine
    cronologico, anche per le settimane senza allenamenti. Il database
    raggruppa, Python completa.

    Le serie a corpo libero di un utente **senza peso corporeo dichiarato**
    hanno un carico effettivo nullo (ADR-0006), quindi la loro `Sum` è nulla e
    non entra: il volume di quell'utente è **incompleto, non zero**, ed è la
    pagina a doverlo dire — la stessa regola che #97 ha scritto sulla dashboard.
    """
    settimane = settimane or finestra_settimanale(oggi=oggi)

    # `.order_by("periodo")` in coda non è cosmesi: `WorkoutSet.Meta.ordering`
    # vale `["set_number"]`, e Django lo trascinerebbe nel `GROUP BY`,
    # spaccando ogni settimana in una riga per numero di serie. È lo stesso
    # inciampo silenzioso delle due trappole di `04-analisi.md`: il conto
    # sarebbe sbagliato e la pagina si disegnerebbe lo stesso.
    righe = (
        WorkoutSet.objects.working()
        .filter(
            workout__user=user,
            workout__started_at__gte=inizio_della_finestra(settimane),
        )
        .annotate(periodo=TruncWeek("workout__started_at"))
        .values("periodo")
        .annotate(volume=Sum(VOLUME))
        .order_by("periodo")
    )

    per_lunedi = {_a_data(riga["periodo"]): riga["volume"] or 0.0 for riga in righe}
    return [
        {"settimana": lunedi, "volume": round(per_lunedi.get(lunedi, 0.0), 1)}
        for lunedi in settimane
    ]


def volume_per_gruppo(user, settimane=None, oggi=None):
    """A2 — la distribuzione sui sei gruppi, nella **stessa** finestra di A1.

    Ordinata per volume decrescente: la domanda che la figura risponde è «cosa
    sto allenando di più», e l'ordine anatomico la renderebbe una tabella da
    leggere invece di una risposta da guardare. I gruppi a zero finiscono in
    coda da soli, e a parità restano nell'ordine del catalogo, o la pagina si
    riordinerebbe a ogni ricarica.

    Raggruppa per **id** del gruppo e non per `label_it`: l'etichetta è testo
    d'interfaccia e libera di cambiare, la chiave no.
    """
    settimane = settimane or finestra_settimanale(oggi=oggi)

    righe = (
        WorkoutSet.objects.working()
        .filter(
            workout__user=user,
            workout__started_at__gte=inizio_della_finestra(settimane),
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


def _a_data(periodo):
    """Il lunedì di `TruncWeek` come `date` locale.

    Con `USE_TZ = True` la troncatura restituisce un `datetime` **aware** a
    mezzanotte di Roma: confrontarlo con una `date` senza passare da
    `localtime()` sposterebbe di un giorno le settimane d'inverno, e il buco
    finirebbe nella casella sbagliata.
    """
    if isinstance(periodo, datetime):
        return timezone.localtime(periodo).date()
    return periodo if isinstance(periodo, date) else None
