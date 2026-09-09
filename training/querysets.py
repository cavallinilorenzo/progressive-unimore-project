"""Le definizioni condivise che ogni analisi di Progressive usa.

Sono **espressioni**, non servizi: qui non si risponde a una domanda, si dà un
nome una volta sola a ciò che comparirebbe copiato in ogni query
(`docs/spec/04-analisi.md`, §«Le tre definizioni che tengono insieme tutto»).

Il file nasce con le classifiche (#76) e non col motore analitico, che è fase
2, perché la classifica di forza ha bisogno di **due** di quelle tre
definizioni — il filtro universale e Epley — e scriverle dentro la view
significherebbe tenerne una seconda copia proprio nel punto in cui la fase 2
scriverà la prima. È la lezione di #75: una regola scritta due volte diverge al
primo ripensamento, e nessun test lo segnala perché due copie identiche
passano entrambe. Le altre analisi aggiungono i propri metodi a questa stessa
classe: la fase 2 ci ha portato `VOLUME` e `with_volume()` (#97), insieme alla
riconciliazione della dashboard, che il volume se lo era riscritto a mano.

Cosa entra qui e quando: **solo ciò che ha almeno due consumatori previsti**,
il resto lo aggiunge il ticket che lo consuma. Un metodo che nessuno chiama è
codice da spiegare all'orale che non serve a niente.

`models.py` importa questo file, non il contrario: le espressioni parlano di
colonne per nome (`F("weight")`) e non hanno bisogno di conoscere i modelli.
"""

from django.db import models
from django.db.models import Case, ExpressionWrapper, F, FloatField, Value, When
from django.db.models.functions import Cast

#: Il `code` dell'attrezzo «corpo libero» nel catalogo (`data/catalog/equipment.csv`).
#: Sta qui come costante e non come stringa in mezzo a un `When`: #16 l'aveva
#: scritto `corpo_libero`, che è italiano ma non è il dato, e la query sarebbe
#: stata sempre falsa **senza segnalare niente** (`docs/spec/04-analisi.md`).
CORPO_LIBERO = "bodyweight"

#: Sopra le 12 ripetizioni la stima di Epley gonfia: quelle serie non
#: concorrono al massimale, ma restano nel volume. Stesso numero del
#: rilevamento dello stallo (#17): le due parti del progetto devono usarlo uguale.
MAX_REPS_FOR_1RM = 12

#: Il carico effettivo — ADR-0006.
#:
#: `Sum(F("reps") * F("weight"))` dà **zero** per ogni trazione e ogni
#: piegamento, e #13 ha misurato che sul corpo libero i pesi nulli sono
#: legittimi, non sporcizia: senza questo `Case` la schiena sparirebbe dalle
#: analisi e nessuno se ne accorgerebbe. Il `+` gestisce gratis anche le
#: trazioni zavorrate.
#:
#: `weight` è **sempre già comprensivo del bilanciere**:
#: `Equipment.default_bar_weight_kg` precompila il form e non entra qui.
EFFECTIVE_LOAD = Case(
    When(
        exercise__equipment__code=CORPO_LIBERO,
        then=F("weight") + F("workout__user__body_mass_kg"),
    ),
    default=F("weight"),
    output_field=FloatField(),
)

#: Il massimale stimato con Epley: `carico effettivo × (1 + reps / 30)`.
#:
#: Epley e non Brzycki perché è una **moltiplicazione**, quindi si legge in una
#: riga di `F()`, mentre Brzycki ha un denominatore che esplode vicino alle 37
#: ripetizioni.
#:
#: Il `Cast` su `reps` non è cerimonia: `reps` è un intero e `30.0` un float,
#: e Django rifiuta di indovinare il tipo di un'espressione mista. Senza, la
#: divisione sarebbe intera e **una serie da 8 ripetizioni varrebbe come una da
#: 0** — è la stessa trappola della media bayesiana, un piano più sotto.
EPLEY = ExpressionWrapper(
    EFFECTIVE_LOAD * (Value(1.0) + Cast(F("reps"), FloatField()) / Value(30.0)),
    output_field=FloatField(),
)

#: Il volume di **una serie**: carico effettivo × ripetizioni.
#:
#: È l'espressione che A1 e A2 sommano (`docs/spec/04-analisi.md`) e che la
#: dashboard aggrega sulla finestra mobile. Vive qui e non dentro le `Sum` che
#: la consumano perché scritta due volte diverge: la dashboard di #95 la
#: calcolava come `Sum(F("reps") * F("weight"))`, cioè **senza carico
#: effettivo**, e su corpo libero quel volume è zero — nessun test lo
#: segnalava, perché due definizioni identiche nella forma passano entrambe
#: (#75).
#:
#: Il `Cast` su `reps` per la ragione di sempre: `reps` è un intero e
#: `EFFECTIVE_LOAD` un float, e un'espressione mista Django non la indovina.
VOLUME = ExpressionWrapper(
    EFFECTIVE_LOAD * Cast(F("reps"), FloatField()),
    output_field=FloatField(),
)


class WorkoutSetQuerySet(models.QuerySet):
    """Il custom QuerySet di `WorkoutSet`, concatenabile.

    Esiste per una ragione sola, ed è quella da dire all'orale: tre definizioni
    comparivano in quasi ogni query, e o si ripetono o si nominano una volta.
    """

    def working(self):
        """Il **filtro universale**: solo le serie efficaci ed eseguite.

        I due filtri vanno sempre insieme, e nessuna analisi ne usa uno solo.
        #13 ha misurato **19% di serie non completate**: farle entrare
        significherebbe contare allenamento che non è avvenuto. Le serie
        saltate non spariscono — diventano il dato dell'aderenza al piano, che
        è materia del coach.
        """
        return self.filter(set_type="working", is_completed=True)

    def with_effective_load(self):
        """Annota `carico_effettivo` — vedi `EFFECTIVE_LOAD`."""
        return self.annotate(carico_effettivo=EFFECTIVE_LOAD)

    def with_volume(self):
        """Annota `volume` **per serie** — vedi `VOLUME`.

        Il nome resta al valore di riga, non all'aggregato, e la scelta è
        quella che tiene il file coerente con sé stesso: qui stanno
        **espressioni**, non risposte, e un metodo che restituisse già una
        somma non sarebbe più concatenabile — nessuno potrebbe metterci un
        `.filter()` dopo, né raggrupparlo per settimana come fa A1.

        «Volume» di una singola serie non è un abuso del termine: il volume è
        additivo per costruzione, e la somma di un gruppo di righe è la
        domanda, che sta in chi la pone. Chi aggrega ha due strade, entrambe
        con la stessa definizione sotto: `Sum(VOLUME)` direttamente, o
        `.with_volume()` seguito da `Sum("volume")` quando la riga serve anche
        da sola.
        """
        return self.annotate(volume=VOLUME)

    def with_estimated_1rm(self):
        """Annota `massimale_stimato`, **senza** applicare il tetto a 12.

        Il tetto è un filtro sulle righe, non una proprietà dell'espressione:
        chi calcola un massimale filtra `reps__lte=MAX_REPS_FOR_1RM`, chi
        calcola il volume no. Tenerli separati è ciò che permette alla stessa
        serie da 15 ripetizioni di restare nel volume e di non concorrere al
        record.
        """
        return self.annotate(massimale_stimato=EPLEY)
