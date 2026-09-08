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
passano entrambe. Qui c'è **solo** ciò che le classifiche consumano; le altre
analisi aggiungeranno i propri metodi a questa stessa classe.

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

    def with_estimated_1rm(self):
        """Annota `massimale_stimato`, **senza** applicare il tetto a 12.

        Il tetto è un filtro sulle righe, non una proprietà dell'espressione:
        chi calcola un massimale filtra `reps__lte=MAX_REPS_FOR_1RM`, chi
        calcola il volume no. Tenerli separati è ciò che permette alla stessa
        serie da 15 ripetizioni di restare nel volume e di non concorrere al
        record.
        """
        return self.annotate(massimale_stimato=EPLEY)
