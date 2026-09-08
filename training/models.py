"""Modelli di Progressive — tutti in un file solo, come nell'esempio del prof.

Il file tiene tre strati:

1. l'utente (`User`), custom fin dalla primissima migrazione;
2. le tre anagrafiche (`MuscleGroup`, `Muscle`, `Equipment`), popolate da CSV e
   senza CRUD utente;
3. le sei entità di prima classe che la traccia conta come *related models* —
   `Exercise`, `Routine`, `RoutineExercise`, `Workout`, `WorkoutSet`, `Vote` —
   più `ExerciseAlias`, che è infrastruttura dell'import.

Il modello di dominio e le sue ragioni stanno in `docs/spec/01-modelli.md`;
i perché più costosi sono ADR in `docs/adr/`.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class User(AbstractUser):
    """L'utente di Progressive.

    È un `AbstractUser` esteso, non un `Profile` in OneToOne come nel progetto
    d'esempio del corso: è la raccomandazione della documentazione Django, costa
    zero solo se presa alla primissima migrazione, e va **dichiarata all'orale**
    come deviazione consapevole. Vedi ADR-0003.
    """

    body_mass_kg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="peso corporeo (kg)",
        help_text="Un solo valore corrente, non uno storico.",
    )
    is_synthetic = models.BooleanField(
        default=False,
        verbose_name="utente sintetico",
        help_text="Generato da seed_synthetic; va dichiarato in interfaccia.",
    )

    class Meta(AbstractUser.Meta):
        verbose_name = "utente"
        verbose_name_plural = "utenti"

    @property
    def has_body_mass(self):
        """Senza peso corporeo l'utente non compare in classifica e non riceve
        un percentile: meglio assente che sbagliato. Vedi ADR-0008."""
        return self.body_mass_kg is not None


class MuscleGroup(models.Model):
    """Uno dei 6 gruppi muscolari: petto, schiena, spalle, braccia, gambe, core."""

    code = models.CharField(max_length=32, unique=True)
    label_it = models.CharField(max_length=64)
    sort_order = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["sort_order"]
        verbose_name = "gruppo muscolare"
        verbose_name_plural = "gruppi muscolari"

    def __str__(self):
        return self.label_it


class Muscle(models.Model):
    """Uno dei 23 muscoli.

    I `code` sono tenuti identici a `reporting.muscle_taxonomy` di Overload
    (migrazione 0008): è quell'identità a rendere i dati di Progressive
    reimportabili nella dashboard personale. Le `label_it`, che sono solo
    testo d'interfaccia, sono libere di divergere.
    """

    code = models.CharField(max_length=32, unique=True)
    group = models.ForeignKey(
        MuscleGroup, on_delete=models.PROTECT, related_name="muscles"
    )
    label_it = models.CharField(max_length=64)
    sort_order = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["sort_order"]
        verbose_name = "muscolo"
        verbose_name_plural = "muscoli"

    def __str__(self):
        return self.label_it


class Equipment(models.Model):
    """L'attrezzo con cui si esegue un esercizio.

    Porta il peso a vuoto (`default_bar_weight_kg`): il peso del bilanciere è
    una proprietà dell'attrezzo, non del singolo esercizio.
    """

    code = models.CharField(max_length=32, unique=True)
    label_it = models.CharField(max_length=64)
    default_bar_weight_kg = models.DecimalField(
        max_digits=5, decimal_places=2, default=0
    )
    load_increment_kg = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=2.5,
        verbose_name="incremento minimo di carico (kg)",
        help_text=(
            "Il passo minimo con cui su questo attrezzo il carico può salire "
            "davvero. Zero sul corpo libero e sull'elastico: lì il coach "
            "consiglia ripetizioni, mai carico — è la regola, non un dato mancante."
        ),
    )
    sort_order = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["sort_order"]
        verbose_name = "attrezzo"
        verbose_name_plural = "attrezzi"

    def __str__(self):
        return self.label_it


class Exercise(models.Model):
    """Un movimento del catalogo globale.

    Ogni esercizio ha **un solo** muscolo primario: i muscoli secondari sono
    deliberatamente fuori dal modello, perché attribuire loro una quota di
    volume richiederebbe un coefficiente inventato e non misurato.
    """

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(
        max_length=140,
        unique=True,
        help_text="Generato da load_catalog, non a runtime: gli URL devono essere stabili.",
    )
    primary_muscle = models.ForeignKey(
        Muscle, on_delete=models.PROTECT, related_name="exercises"
    )
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="exercises"
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "esercizio"
        verbose_name_plural = "esercizi"
        constraints = [
            # `unique=True` su `name` è già lì, ma è case-sensitive: il catalogo
            # si carica da CSV e un duplicato di sola maiuscola passerebbe
            # silenziosamente.
            models.UniqueConstraint(Lower("name"), name="exercise_name_unique_ci"),
        ]

    def __str__(self):
        return self.name


class Routine(models.Model):
    """La scheda di allenamento: mutabile, e di proprietà di un utente."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="routines"
    )
    name = models.CharField(max_length=120, verbose_name="nome")
    notes = models.TextField(blank=True, verbose_name="note")
    is_public = models.BooleanField(
        default=False,
        verbose_name="pubblica",
        help_text="Solo una scheda pubblica è visibile e votabile dagli altri.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "scheda"
        verbose_name_plural = "schede"

    def __str__(self):
        return self.name


class RoutineExercise(models.Model):
    """Una voce della scheda: l'esercizio e il bersaglio da inseguire."""

    routine = models.ForeignKey(
        Routine, on_delete=models.CASCADE, related_name="exercises"
    )
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT)
    position = models.PositiveSmallIntegerField(verbose_name="posizione")
    target_sets = models.PositiveSmallIntegerField(verbose_name="serie previste")
    target_reps = models.PositiveSmallIntegerField(
        verbose_name="ripetizioni minime",
        help_text="Estremo basso del range.",
    )
    target_reps_max = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="ripetizioni massime",
        help_text="Estremo alto: è questo che la doppia progressione insegue.",
    )
    notes = models.CharField(max_length=200, blank=True, verbose_name="note")

    class Meta:
        ordering = ["position"]
        verbose_name = "esercizio della scheda"
        verbose_name_plural = "esercizi della scheda"
        constraints = [
            # Unicità su `(routine, exercise)` e **non** su `(routine, position)`:
            # riordinare due esercizi violerebbe un vincolo sulla posizione a
            # metà transazione, e SQLite non ha vincoli differibili usabili.
            # Che un esercizio compaia una volta sola per scheda è invece una
            # regola di dominio vera; l'ordine lo tiene `ordering`.
            models.UniqueConstraint(
                fields=["routine", "exercise"], name="routine_exercise_unique"
            ),
        ]

    def __str__(self):
        return f"{self.exercise} in {self.routine}"


class Workout(models.Model):
    """L'allenamento eseguito: un log immutabile.

    `routine` in `SET_NULL` e `title` come istantanea del nome sono la stessa
    decisione (ADR-0002): modificare o cancellare la scheda non riscrive mai
    il passato.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workouts"
    )
    routine = models.ForeignKey(
        Routine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workouts",
    )
    title = models.CharField(
        max_length=120,
        verbose_name="titolo",
        help_text="Istantanea del nome della scheda al momento dell'esecuzione.",
    )
    started_at = models.DateTimeField(verbose_name="iniziato il")
    ended_at = models.DateTimeField(null=True, blank=True, verbose_name="finito il")
    notes = models.TextField(blank=True, verbose_name="note")
    external_id = models.UUIDField(
        null=True,
        blank=True,
        unique=True,
        help_text="Idempotenza dell'import. Nullo per gli allenamenti nati in-app.",
    )

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "allenamento"
        verbose_name_plural = "allenamenti"
        constraints = [
            # L'unico bloccante sulle durate: lo storico reale contiene sessioni
            # da 0 minuti e da 25 ore, e restano ammesse — assurde ma non
            # impossibili. Una fine *prima* dell'inizio invece lo è.
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True)
                | models.Q(ended_at__gte=models.F("started_at")),
                name="workout_ended_after_started",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "-started_at"], name="workout_user_recent_idx"
            ),
        ]

    def __str__(self):
        return f"{self.title} — {self.started_at:%d/%m/%Y}"


class WorkoutSet(models.Model):
    """Una serie dentro un allenamento.

    `weight` è **sempre già comprensivo del bilanciere**: `default_bar_weight_kg`
    serve solo a precompilare il form e non entra in nessuna analisi. Sommarlo a
    valle significherebbe non sapere più se un numero l'ha scritto l'utente o
    inventato la query.
    """

    class SetType(models.TextChoices):
        WORKING = "working", "Efficace"
        WARMUP = "warmup", "Riscaldamento"
        RAMP_UP = "rampUp", "Avvicinamento"

    workout = models.ForeignKey(Workout, on_delete=models.CASCADE, related_name="sets")
    # Punta a `Exercise`, mai a `RoutineExercise`: la serie sopravvive alla
    # scheda che l'ha suggerita.
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT)
    set_number = models.PositiveSmallIntegerField(verbose_name="numero di serie")
    reps = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="ripetizioni",
        help_text="Nullo se la serie è stata saltata.",
    )
    weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="carico (kg)",
        help_text="Nullo se saltata. Zero è legittimo sul corpo libero.",
    )
    set_type = models.CharField(
        max_length=16,
        choices=SetType.choices,
        default=SetType.WORKING,
        verbose_name="tipo di serie",
    )
    is_completed = models.BooleanField(default=True, verbose_name="eseguita")
    external_id = models.UUIDField(
        null=True,
        blank=True,
        unique=True,
        help_text="Idempotenza dell'import.",
    )

    class Meta:
        ordering = ["set_number"]
        verbose_name = "serie"
        verbose_name_plural = "serie"
        constraints = [
            models.UniqueConstraint(
                fields=["workout", "exercise", "set_number"],
                name="workout_set_unique",
            ),
            # Non si può pretendere `reps` su una serie saltata, e non si può
            # accettare una serie eseguita a zero ripetizioni.
            models.CheckConstraint(
                condition=models.Q(is_completed=False) | models.Q(reps__gt=0),
                name="workout_set_completed_has_reps",
            ),
            # Zero è valido (corpo libero), negativo no.
            models.CheckConstraint(
                condition=models.Q(weight__isnull=True) | models.Q(weight__gte=0),
                name="workout_set_weight_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["exercise"], name="workout_set_exercise_idx"),
        ]

    def __str__(self):
        return f"{self.exercise} — serie {self.set_number}"


class Vote(models.Model):
    """Il voto di un utente su una scheda pubblica.

    Scala 1–5 e non pollice su/giù, perché serve una media da ordinare.
    Il divieto di autovoto **non è esprimibile come vincolo di database** —
    attraversa una relazione: vive nel form e nella vista, e va testato lì.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="votes"
    )
    routine = models.ForeignKey(Routine, on_delete=models.CASCADE, related_name="votes")
    score = models.PositiveSmallIntegerField(verbose_name="voto")
    comment = models.TextField(blank=True, verbose_name="commento")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "voto"
        verbose_name_plural = "voti"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "routine"], name="vote_unique_per_user_routine"
            ),
            models.CheckConstraint(
                condition=models.Q(score__gte=1) & models.Q(score__lte=5),
                name="vote_score_between_1_and_5",
            ),
        ]

    def __str__(self):
        return f"{self.score}/5 su {self.routine}"


class ExerciseAlias(models.Model):
    """Il nome grezzo di un CSV estraneo, legato a un esercizio del catalogo.

    È infrastruttura dell'import, non un'entità del dominio: non compare in
    nessuna analisi e non allarga il catalogo. È il modo in cui un nome estraneo
    entra nel dominio senza sporcarlo. Vedi ADR-0010.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="exercise_aliases",
    )
    raw_name = models.CharField(max_length=160, verbose_name="nome grezzo")
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)

    class Meta:
        ordering = ["raw_name"]
        verbose_name = "alias di esercizio"
        verbose_name_plural = "alias di esercizio"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "raw_name"], name="exercise_alias_unique_per_user"
            ),
        ]

    def __str__(self):
        return f"{self.raw_name} → {self.exercise}"
