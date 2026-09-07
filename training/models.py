"""Modelli del catalogo esercizi di Progressive.

Qui vivono solo le tre anagrafiche (`MuscleGroup`, `Muscle`, `Equipment`) e il
catalogo `Exercise`: sono i modelli che il ticket #27 doveva rendere caricabili.
`Routine`, `RoutineExercise`, `Workout`, `WorkoutSet` e `Vote` — gli altri
modelli decisi in #14 — arrivano con la sessione di costruzione.

Il catalogo è globale e scritto a mano: nessun utente crea esercizi propri,
perché un esercizio custom sarebbe invisibile a percentili e classifiche.
Vedi ADR-0001.
"""

from django.db import models


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

    def __str__(self):
        return self.name
