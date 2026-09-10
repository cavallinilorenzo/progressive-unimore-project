"""Le due classifiche di Progressive, come query e non come pagine.

Il modulo **non conosce HTTP**: è la stessa scelta di `training/importer.py`,
e per la stessa ragione. Ciò che qui va provato riga per riga sono i *numeri* —
il punteggio bayesiano, la forza relativa, il pari merito — e provarli
attraverso il client di test vorrebbe dire leggerli dall'HTML, cioè testare il
template ogni volta che si vuole testare una divisione.

Le due classifiche sono di **natura diversa**, e non vanno chiamate entrambe
«classifica» senza aggettivo (`CONTEXT.md`, §Le due classifiche):

- la **classifica di forza** ordina gli *utenti* su **un singolo esercizio**
  per forza relativa, di sempre. È una classifica di **record**, non di
  attività;
- la **classifica sociale** ordina le *schede pubbliche* per punteggio
  bayesiano.

Nessuna delle due ordina per volume, e non è una dimenticanza: il volume di chi
si allena a corpo libero è strutturalmente più alto a parità di impegno, quindi
resta confrontabile nel tempo per lo stesso utente ma **mai fra utenti**
(ADR-0006). Nessuna delle due, inoltre, inventa un numero quando i dati non
bastano: sotto soglia non si mostra una classifica magra, si mostra il motivo.

Fonte: #33, `docs/spec/04-analisi.md` §«Le due classifiche».
"""

from django.db.models import (
    Avg,
    Count,
    ExpressionWrapper,
    F,
    FloatField,
    IntegerField,
    Max,
    Min,
    OuterRef,
    Subquery,
    Sum,
    Value,
    Window,
)
from django.db.models.functions import Cast, Rank

from training.models import Exercise, Routine, RoutineExercise, Vote, WorkoutSet
from training.querysets import EPLEY, MAX_REPS_FOR_1RM

#: Quanta gente serve su un esercizio perché confrontarsi abbia senso. È la
#: **stessa costante** che farà tacere il percentile di forza in fase 2, non una
#: seconda: una classifica su quattro persone ha lo stesso difetto informativo
#: di un percentile su tre, e due soglie diverse sarebbero due numeri da
#: giustificare all'orale invece di uno.
MIN_USERS_FOR_COMPARISON = 20

#: Quanti allenamenti *distinti* con quell'esercizio servono per entrare in
#: graduatoria. Non due serie: due serie nello stesso giorno sono lo stesso
#: dato. Esclude il valore singolo inserito male, che è il rumore realistico
#: misurato in #13.
MIN_WORKOUTS_FOR_RANKING = 2

#: L'anti-civetta della classifica sociale: una scheda con un esercizio solo
#: non è una scheda, è un'esca per voti. È l'unica difesa *strutturale* della
#: gamificabilità che questa pagina si prende; il resto si dichiara.
MIN_EXERCISES_FOR_RANKING = 3

#: I voti di prior della media bayesiana. Con `C = 3` una scheda ha bisogno di
#: qualche voto vero prima che il suo punteggio si stacchi dalla media globale.
C_PRIOR_VOTI = 3


def esercizi_con_classifica():
    """Gli esercizi la cui popolazione supera la soglia, i più praticati prima.

    È la lista che riempie il selettore: **non esiste una classifica di forza
    generale**, ne esiste una per ogni esercizio che abbia abbastanza gente
    sopra, e offrire nel menu un esercizio che poi dice «dati insufficienti»
    sarebbe un vicolo cieco messo in pagina apposta.

    La popolazione conta gli utenti **confrontabili**: chi ha almeno una serie
    utile e un peso corporeo dichiarato. La condizione dei due allenamenti
    distinti resta invece una condizione della *riga*, non della popolazione —
    è la lettura letterale delle tre condizioni di #33, ed è la ragione per cui
    una classifica può avere qualche riga in meno dei suoi utenti in soglia.
    """
    utenti_confrontabili = (
        WorkoutSet.objects.working()
        .filter(exercise=OuterRef("pk"), reps__lte=MAX_REPS_FOR_1RM)
        .exclude(workout__user__body_mass_kg__isnull=True)
        .values("exercise")
        .annotate(n=Count("workout__user_id", distinct=True))
        .values("n")
    )
    return (
        Exercise.objects.annotate(
            n_utenti=Subquery(utenti_confrontabili, output_field=IntegerField())
        )
        .filter(n_utenti__gte=MIN_USERS_FOR_COMPARISON)
        .select_related("primary_muscle__group", "equipment")
        .order_by("-n_utenti", "name")
    )


def classifica_forza(exercise):
    """La graduatoria di forza relativa su **un** esercizio, di sempre.

    Una riga per utente ammesso, ordinata per massimale stimato diviso peso
    corporeo. Le tre condizioni d'ammissione (#33):

    1. la **popolazione** dell'esercizio è sopra soglia — ma quella si chiede a
       `esercizi_con_classifica()`, perché è una proprietà dell'esercizio e non
       della riga: qui la classifica si costruisce comunque, ed è la view a
       decidere se mostrarla;
    2. **almeno due allenamenti distinti** dell'utente con quell'esercizio;
    3. **peso corporeo dichiarato** — senza, non esiste forza relativa, e
       l'utente non compare *affatto* invece di comparire con un numero
       sbagliato (ADR-0008).

    Nessuna finestra temporale, e per due ragioni che vanno insieme: è una
    classifica di record, e qualsiasi finestra più corta di 12 settimane
    espellerebbe lo storico reale di 26 giorni dalla propria demo.

    Il **pari merito** si rompe sul primo allenamento con quell'esercizio: è il
    ripiego dichiarato in anticipo da #33, e la ragione per cui è stato preso
    sta nel commento dentro la query — misurata, non temuta.
    """
    return (
        WorkoutSet.objects.working()
        .filter(exercise=exercise, reps__lte=MAX_REPS_FOR_1RM)
        .exclude(workout__user__body_mass_kg__isnull=True)
        # I quattro campi dell'utente escono **rinominati**, e non è cosmesi:
        # `workout__user__is_synthetic` in un template è una chiave e non un
        # attributo, quindi il partial dell'«utente dimostrativo» (ADR-0009),
        # che legge `utente.is_synthetic`, non riuscirebbe a leggerlo. Con
        # questi nomi la riga della classifica si passa al partial così com'è,
        # e la formula dell'etichetta resta scritta in un posto solo.
        .values(
            utente_id=F("workout__user_id"),
            username=F("workout__user__username"),
            is_synthetic=F("workout__user__is_synthetic"),
            body_mass_kg=F("workout__user__body_mass_kg"),
        )
        .annotate(
            massimale=Max(EPLEY),
            allenamenti=Count("workout_id", distinct=True),
            # Il pari merito si rompe su **da quanto tempo** si pratica
            # l'esercizio, non su quando si è segnato il record: è il ripiego
            # che #33 aveva dichiarato *in anticipo* per il caso in cui la data
            # del massimale non avesse retto, ed è quello che è successo.
            #
            # La versione con la data del record era una `Subquery` correlata
            # che ordina su un'espressione (`order_by(EPLEY.desc())`), e SQLite
            # la rivaluta **riga per riga** invece che per gruppo: misurata sui
            # dati veri, la stessa pagina passa da **0,01 s a 31 s**. Questa è
            # un aggregato nella stessa passata, non cambia nessuna delle altre
            # regole, e resta spiegabile: a parità di forza relativa sta sopra
            # chi quell'esercizio lo pratica da più tempo.
            primo_allenamento=Min("workout__started_at"),
        )
        .filter(allenamenti__gte=MIN_WORKOUTS_FOR_RANKING)
        # `Cast` sul peso corporeo, che è un `DecimalField`: senza, la
        # divisione mescola due tipi e Django si rifiuta di indovinare. È la
        # seconda trappola di `04-analisi.md`, e l'`output_field` va
        # sull'**espressione** — passato come argomento di `annotate()` sarebbe
        # una seconda annotazione di nome `output_field`, cioè niente.
        .annotate(
            relativa=ExpressionWrapper(
                F("massimale") / Cast(F("body_mass_kg"), FloatField()),
                output_field=FloatField(),
            )
        )
        # `Rank()` e non `RowNumber()`: due primi a pari merito sono entrambi
        # «1°» e il successivo è «3°». È il significato letterale di pari
        # merito, e costa zero.
        .annotate(posizione=Window(Rank(), order_by=F("relativa").desc()))
        # L'ordine *dentro* il pari merito è deterministico, o la pagina si
        # riordina a ogni ricarica e il paginatore mostra due volte la stessa
        # persona.
        .order_by("-relativa", "primo_allenamento", "utente_id")
    )


def media_globale_dei_voti():
    """La media di **tutti** i `Vote.score` del database: un solo `aggregate`.

    Non è la media delle medie, e la differenza non è teorica: la media delle
    medie peserebbe uguale una scheda con un voto e una con cinquanta, che è
    esattamente ciò che la media bayesiana esiste per non fare.
    """
    return Vote.objects.aggregate(m=Avg("score"))["m"] or 0


def classifica_sociale():
    """Le schede pubbliche, ordinate per **media bayesiana**.

    ``punteggio = (C · m + Σ voti) / (C + n)`` — la media della scheda smorzata
    verso la media globale, tanto più quanto meno voti ha.

    `Avg("votes__score")` nudo metterebbe una scheda con un solo 5 sopra una
    con cinquanta voti a 4,8. Anche la sola **soglia minima di voti** è
    scartata: è arbitraria, e una scheda con esattamente tre cinque resterebbe
    comunque in cima. La bayesiana è **una riga di ORM in più che elimina una
    soglia invece di aggiungerla**.

    Media grezza e numero di voti restano annotati e vanno mostrati accanto:
    il punteggio che ordina dev'essere ispezionabile.
    """
    media_globale = float(media_globale_dei_voti())

    # L'anti-civetta passa da una **sottoquery separata**, e qui sta la prima
    # trappola silenziosa di `04-analisi.md`: contare gli esercizi nello stesso
    # `annotate()` dei voti significa due join a molti nella stessa query, che
    # moltiplicano le righe. `Count(distinct=True)` salverebbe i conteggi, ma
    # `Sum("votes__score")` verrebbe moltiplicato per il numero di esercizi e
    # il punteggio sarebbe sbagliato **senza che niente segnali errore**.
    votabili = (
        RoutineExercise.objects.values("routine")
        .annotate(n=Count("pk"))
        .filter(n__gte=MIN_EXERCISES_FOR_RANKING)
        .values("routine")
    )

    return (
        Routine.objects.filter(is_public=True, pk__in=votabili)
        .select_related("user")
        .annotate(
            n_voti=Count("votes"),
            somma_voti=Sum("votes__score"),
            media=Avg("votes__score"),
        )
        .filter(n_voti__gte=1)
        # `somma_voti` e `n_voti` sono interi: senza il `Cast` la divisione
        # tronca, e un punteggio di 4,7 diventerebbe 4 — la seconda trappola,
        # nella sua forma peggiore, perché **ordina lo stesso** e la pagina
        # sembra funzionare.
        .annotate(
            punteggio=ExpressionWrapper(
                (
                    Value(float(C_PRIOR_VOTI)) * Value(media_globale)
                    + Cast(F("somma_voti"), FloatField())
                )
                / (Value(float(C_PRIOR_VOTI)) + Cast(F("n_voti"), FloatField())),
                output_field=FloatField(),
            )
        )
        .annotate(posizione=Window(Rank(), order_by=F("punteggio").desc()))
        .order_by("-punteggio", "-n_voti", "pk")
    )


def schede_pubbliche_di(user):
    """Le schede pubbliche di `user`, con la posizione se sono in classifica.

    `classifica_sociale()` va **valutata per intero e filtrata qui in
    Python**, non con un `.filter(user=user)` in coda alla query: quel filtro
    finirebbe nel `WHERE`, cioè prima del `GROUP BY` e della `Window(Rank())`,
    e la posizione risultante sarebbe relativa alle sole schede dell'utente
    invece che alla classifica vera — lo stesso errore silenzioso descritto
    sopra, in una forma nuova.

    Per le schede *non* in classifica il motivo si distingue in due: pochi
    esercizi o zero voti, perché sono due difetti diversi e chi legge deve
    sapere quale correggere.
    """
    classificate = {r.pk: r for r in classifica_sociale() if r.user_id == user.pk}

    righe = []
    for scheda in (
        Routine.objects.filter(user=user, is_public=True)
        .annotate(
            n_esercizi=Count("exercises", distinct=True),
            n_voti=Count("votes", distinct=True),
            media=Avg("votes__score"),
        )
        .order_by("-created_at")
    ):
        classificata = classificate.get(scheda.pk)
        if classificata is not None:
            righe.append(
                {
                    "routine": scheda,
                    "in_classifica": True,
                    "posizione": classificata.posizione,
                    "punteggio": classificata.punteggio,
                    "media": classificata.media,
                    "n_voti": classificata.n_voti,
                }
            )
        else:
            righe.append(
                {
                    "routine": scheda,
                    "in_classifica": False,
                    "motivo": (
                        "esercizi"
                        if scheda.n_esercizi < MIN_EXERCISES_FOR_RANKING
                        else "voti"
                    ),
                    "n_esercizi": scheda.n_esercizi,
                    "n_voti": scheda.n_voti,
                    "media": scheda.media,
                }
            )
    return righe
