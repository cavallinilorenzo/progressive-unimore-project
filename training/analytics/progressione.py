"""A3, A4 e A5 — le tre analisi del dettaglio esercizio.

Le tre insieme rispondono a una domanda sola, che è quella per cui si apre la
pagina di un esercizio: **sto migliorando?** A3 la guarda nel tempo (la
progressione del massimale stimato), A4 nel proprio passato (il record), A5
rispetto agli altri (il percentile di forza relativa). Sono l'unico punto del
progetto in cui un utente si confronta con qualcuno che non è sé stesso di sei
mesi fa.

Le tre definizioni condivise arrivano da `training/querysets.py` per nome
(`EPLEY`, `MAX_REPS_FOR_1RM`), mai riscritte qui — vedi il docstring del
pacchetto.

## Il tetto a 12 ripetizioni vale su tutte e tre

Sopra le 12 ripetizioni Epley gonfia, quindi nessuna delle tre analisi di
questo file guarda quelle serie. Non è una regola di questo modulo: è la stessa
costante che il volume **non** applica e che userà il rilevamento dello stallo,
e le due parti del progetto devono usarla uguale (`MAX_REPS_FOR_1RM`).

Conseguenza da tenere a mente leggendo la pagina: lo storico grezzo in coda al
dettaglio può avere righe che qui non compaiono. Una serie da 15 ripetizioni è
allenamento — entra nel volume — ma non è un tentativo di record.

## A3 non è la query della spec, ed è documentato

`docs/spec/04-analisi.md` scriveva `Window(Max("best_1rm"))` sopra
`Max(EPLEY)`. Non gira: Django rifiuta un aggregato dentro un aggregato con un
`FieldError` in **costruzione**, prima ancora di toccare il database (#98).
La forma qui sotto è quella misurata dal prototipo `prototypes/t98-a3-window/`:
la `Subquery` sta **sotto** le due finestre, e le righe di base sono gli
allenamenti invece delle serie. Una sola query SQL, 5,9 ms sul caso peggiore
dell'intero database (146 allenamenti sulla panca piana).

Due trappole che il prototipo ha già pagato, e che questo file eredita risolte:

- **niente join a `sets`**: `Workout.objects.filter(sets__exercise=ex)` gira, non
  segnala niente e restituisce 281 righe invece di 146, perché le finestre
  vedono i duplicati del join **prima** del `DISTINCT`. Si passa da
  `pk__in=<subquery>`;
- **niente taglio temporale con `.filter()`**: finirebbe in `WHERE`, cioè prima
  della finestra, e il massimo cumulativo **ripartirebbe dal taglio** — sulla
  panca piana il taglio a 2026 mostra 108,5 al posto del record vero di 143,3.
  Questa pagina non taglia affatto (vedi `progressione`), e se un giorno
  tagliasse lo farebbe in Python, come i buchi di `TruncWeek` in `volume.py`.
"""

from django.db.models import (
    ExpressionWrapper,
    F,
    FloatField,
    Max,
    OuterRef,
    Subquery,
    Window,
)
from django.db.models.expressions import RowRange
from django.db.models.functions import Cast, Lag, PercentRank

from training.models import Workout, WorkoutSet
from training.querysets import EPLEY, MAX_REPS_FOR_1RM
from training.rankings import MIN_USERS_FOR_COMPARISON

#: Quante sessioni mostrare nella tabella dei salti. Il grafico porta tutta la
#: storia; la tabella serve a leggere **l'ultimo tratto**, dove sta la domanda
#: «l'ultima volta com'è andata». Oltre la decina si rilegge il grafico in
#: forma di numeri, che è la ridondanza che non serve a nessuno.
SESSIONI_CON_SALTO = 8


def progressione(user, exercise):
    """A3 — una riga per **allenamento** in cui l'utente ha fatto l'esercizio.

    Ogni riga porta il massimale stimato di quella sessione (`massimale`), il
    massimo cumulativo fino a quel giorno compreso (`record_a_quel_giorno`) e
    il massimale della sessione precedente (`precedente`, nullo sulla prima).

    Le due finestre costano **1,5 ms** sopra l'aggregato che serve comunque:
    A3 non è un problema di prestazioni e la pagina non ha bisogno di
    guardarsi le spalle (#98).

    **Nessuna finestra temporale, di proposito.** `record_a_quel_giorno` è un
    massimo *di sempre*: mostrarne uno che riparte da una data sarebbe la
    risposta sbagliata alla domanda «qual è il mio record», e sui dati veri il
    caso peggiore è 146 righe — non c'è niente da tagliare per ragioni di costo.

    Restituisce un QuerySet: chi lo consuma lo materializza una volta e ci
    lavora in Python, perché `record_personale` legge le stesse righe e una
    seconda query per la stessa risposta sarebbe una definizione in più da
    tenere allineata.
    """
    # Il massimale della singola sessione, come **colonna** e non come
    # aggregato: è questo che permette alle due finestre di stare sopra senza
    # impilare un aggregato dentro un aggregato.
    massimale_sessione = (
        WorkoutSet.objects.working()
        .filter(workout=OuterRef("pk"), exercise=exercise, reps__lte=MAX_REPS_FOR_1RM)
        .values("workout")
        .annotate(m=Max(EPLEY))
        .values("m")
    )
    # Quali allenamenti contengono l'esercizio — come `pk__in` e **mai** come
    # join, o le finestre conterebbero ogni sessione una volta per serie.
    sessioni_con_esercizio = (
        WorkoutSet.objects.working()
        .filter(exercise=exercise, reps__lte=MAX_REPS_FOR_1RM)
        .values("workout_id")
    )
    return (
        Workout.objects.filter(user=user, pk__in=sessioni_con_esercizio)
        .annotate(
            massimale=Subquery(massimale_sessione, output_field=FloatField())
        )
        .annotate(
            # `RowRange(start=None, end=0)` è «da sempre a questa riga»: senza
            # frame esplicito il default di SQL sarebbe lo stesso, ma scritto
            # è una riga che all'orale si legge invece di ricordarsi.
            record_a_quel_giorno=Window(
                Max("massimale"), order_by="started_at",
                frame=RowRange(start=None, end=0),
            ),
            # `Lag` **non è un aggregato**, ed è la ragione per cui questa
            # finestra si costruisce mentre `Window(Max("massimale"))` sopra un
            # `Max` non si costruirebbe (#98).
            precedente=Window(Lag("massimale"), order_by="started_at"),
        )
        .values("id", "started_at", "massimale", "record_a_quel_giorno", "precedente")
        .order_by("started_at")
    )


def record_personale(righe):
    """A4 — il record, **derivato dalle righe di A3** e non da una seconda query.

    Restituisce `{"massimale", "quando", "sessioni"}`, o `None` se non c'è
    nessuna sessione utile.

    `docs/spec/04-analisi.md` scrive A4 come `Subquery` + `OuterRef` che annota
    `Exercise.objects`: è la forma giusta per una **lista** di esercizi, dove
    l'alternativa sarebbero cento query. Su un dettaglio, che è una riga sola,
    quella forma sarebbe ginnastica — e soprattutto A3 ha già in mano la
    risposta: il record *è* l'ultimo `record_a_quel_giorno`, e la sua data è il
    primo giorno in cui il massimale l'ha toccato. Costo: zero query.

    La correlata `Subquery` con `OuterRef` non sparisce dal progetto per
    questo, e non è una tecnica saltata: A3 stessa ne è costruita sopra
    (`massimale_sessione`), e la classifica di forza la usa per contare la
    popolazione di ogni esercizio.

    **La data sì, la serie no.** Dire *quando* è stato fatto il record cambia
    come lo si legge — un record di due anni fa e uno di martedì scorso sono
    due situazioni diverse — e qui costa zero. Dire *con quale serie* (quante
    ripetizioni, con che carico) richiederebbe una seconda `Subquery` correlata
    per un dato che lo storico in coda alla pagina già mostra.
    """
    righe = list(righe)
    if not righe:
        return None
    record = righe[-1]["record_a_quel_giorno"]
    quando = next(
        riga["started_at"] for riga in righe if riga["massimale"] == record
    )
    return {"massimale": record, "quando": quando, "sessioni": len(righe)}


def percentile_forza(user, exercise):
    """A5 — dove sta l'utente nella popolazione, in forza relativa.

    Restituisce sempre un dizionario con uno `stato`, e il punto della funzione
    è che gli stati diversi da `"ok"` **non sono errori**: sono la risposta.

    - `"senza_peso"` — l'utente non ha dichiarato il peso corporeo. Non esiste
      una forza relativa senza denominatore (ADR-0008), e la pagina lo dice con
      l'invito al profilo invece di tacere.
    - `"popolazione_insufficiente"` — meno di `MIN_USERS_FOR_COMPARISON` utenti
      confrontabili su questo esercizio. «Sei nel 67° percentile» su tre
      persone è formalmente corretto e informativamente falso.
    - `"senza_serie"` — la popolazione c'è, ma l'utente non ha ancora una serie
      utile (sotto le 12 ripetizioni) su questo esercizio.
    - `"ok"` — `percentile` è la percentuale di utenti **sotto** di lui.

    La popolazione è definita esattamente come quella di
    `rankings.esercizi_con_classifica()`: chi ha almeno una serie utile e un
    peso corporeo dichiarato. Stessa soglia e stessa popolazione, o l'esercizio
    che offre una classifica potrebbe negare un percentile e viceversa.

    Le **due condizioni della classifica** che qui non valgono sono i due
    allenamenti distinti — che #33 dichiara condizione della *riga* di
    graduatoria, non del confronto — e nulla di più: chi ha una sola sessione
    ha comunque un massimale, e il percentile non è una graduatoria pubblica.

    La riga dell'utente si cerca **in Python**, non con un `.filter()` dopo la
    finestra: un filtro sull'utente cadrebbe nell'`HAVING`, cioè prima che
    `PERCENT_RANK` sia calcolato, e resterebbe una riga sola — percentile zero,
    senza un errore. È la stessa famiglia della trappola del taglio temporale
    di A3. La popolazione è di cento righe: leggerle tutte costa niente.
    """
    if not user.has_body_mass:
        return {"stato": "senza_peso", "soglia": MIN_USERS_FOR_COMPARISON}

    righe = list(_forza_relativa_della_popolazione(exercise))
    if len(righe) < MIN_USERS_FOR_COMPARISON:
        return {
            "stato": "popolazione_insufficiente",
            "n_utenti": len(righe),
            "soglia": MIN_USERS_FOR_COMPARISON,
        }

    mia = next(
        (riga for riga in righe if riga["workout__user_id"] == user.pk), None
    )
    if mia is None:
        return {
            "stato": "senza_serie",
            "n_utenti": len(righe),
            "soglia": MIN_USERS_FOR_COMPARISON,
        }
    return {
        "stato": "ok",
        # `PERCENT_RANK` ascendente è la frazione di popolazione
        # **strettamente sotto**: la pagina la racconta così («più forte del
        # 70%») e non come «settantesimo percentile», che è la stessa cosa
        # detta in un modo che si legge male.
        "percentile": round(mia["pct"] * 100),
        "relativa": round(mia["relativa"], 2),
        "n_utenti": len(righe),
        "soglia": MIN_USERS_FOR_COMPARISON,
    }


def _forza_relativa_della_popolazione(exercise):
    """Una riga per utente confrontabile, col suo `PERCENT_RANK`.

    `PercentRank` e non un aggregato di percentile: SQLite non ha
    `percentile_cont` né `median`, ma ha le funzioni di finestra
    (`docs/spec/04-analisi.md`, §SQLite). La finestra si costruisce sopra
    l'aggregato per la stessa ragione per cui `Lag` ci si costruisce in A3 —
    `PercentRank` non è un aggregato — ed è già il pattern della classifica di
    forza.
    """
    return (
        WorkoutSet.objects.working()
        .filter(exercise=exercise, reps__lte=MAX_REPS_FOR_1RM)
        # Senza peso corporeo la forza relativa dividerebbe per null. La riga
        # non era nel ticket originale di A5: arriva da #33 come terza
        # condizione d'ammissione, ed è il tipo di riga che si perde
        # ricopiando la query.
        .exclude(workout__user__body_mass_kg__isnull=True)
        .values("workout__user_id", "workout__user__body_mass_kg")
        .annotate(massimale=Max(EPLEY))
        .annotate(
            # `Cast` sul peso corporeo, che è un `DecimalField`: senza, la
            # divisione mescola due tipi e Django si rifiuta di indovinare.
            relativa=ExpressionWrapper(
                F("massimale")
                / Cast(F("workout__user__body_mass_kg"), FloatField()),
                output_field=FloatField(),
            )
        )
        .annotate(pct=Window(PercentRank(), order_by=F("relativa").asc()))
        # `order_by()` vuoto per la ragione misurata in `volume.py`:
        # `WorkoutSet.Meta.ordering` vale `["set_number"]` e Django lo
        # trascinerebbe nel `GROUP BY`, spaccando ogni utente in una riga per
        # numero di serie. Il percentile si calcolerebbe lo stesso, su una
        # popolazione gonfiata di cloni.
        .order_by()
    )


def salti(righe):
    """Le ultime sessioni con il **salto** rispetto alla precedente.

    È il consumo di `Lag`: senza questa lettura la seconda finestra di A3
    sarebbe una tecnica calcolata e mai mostrata, cioè codice da giustificare
    all'orale che non serve a niente.

    Più recenti in cima, come lo storico grezzo poco sotto nella stessa pagina:
    due tabelle adiacenti con l'ordine opposto si leggono come un errore.
    `nuovo_record` marca le sessioni in cui il massimale ha toccato il massimo
    cumulativo **battendo** la precedente — la prima sessione in assoluto è un
    record per definizione e marcarla non direbbe niente.
    """
    return [
        {
            "quando": riga["started_at"],
            "massimale": riga["massimale"],
            "salto": (
                None
                if riga["precedente"] is None
                else riga["massimale"] - riga["precedente"]
            ),
            "nuovo_record": (
                riga["precedente"] is not None
                and riga["massimale"] == riga["record_a_quel_giorno"]
                and riga["massimale"] > riga["precedente"]
            ),
        }
        for riga in reversed(righe[-SESSIONI_CON_SALTO:])
    ]
