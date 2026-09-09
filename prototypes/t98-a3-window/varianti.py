"""Prototipo #98, seconda sonda: le varianti del ripiego."""
import os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django; django.setup()

from django.db.models import F, FloatField, Max, OuterRef, Subquery, Window
from django.db.models.expressions import RowRange
from django.db.models.functions import Lag
from training.models import Exercise, User, Workout, WorkoutSet
from training.querysets import EPLEY, MAX_REPS_FOR_1RM

utente = User.objects.get(username="cavallinilorenzo")
ex = Exercise.objects.get(name="Panca piana con bilanciere")

def prova(etichetta, fn, mostra_sql=False):
    try:
        qs = fn()
        righe = list(qs)
        print(f"  REGGE   {etichetta}  ({len(righe)} righe)")
        if righe: print(f"          prima riga: {righe[0]}")
        if mostra_sql: print("          SQL: " + str(qs.query))
        return qs
    except Exception as e:
        print(f"  ROMPE   {etichetta}\n          {type(e).__name__}: {e}")
        return None

BASE = dict(exercise=ex, workout__user=utente, reps__lte=MAX_REPS_FOR_1RM)

def per_workout():
    return (WorkoutSet.objects.working().filter(**BASE)
            .values("workout_id", "workout__started_at")
            .annotate(best_1rm=Max(EPLEY)))

print("\n--- A. le due Window, separate, sopra l'aggregato ---")
prova("Window(Max(best_1rm)) da sola", lambda: per_workout().annotate(
    running_max=Window(Max("best_1rm"), order_by="workout__started_at",
                       frame=RowRange(start=None, end=0))))
prova("Window(Lag(best_1rm)) da sola", lambda: per_workout().annotate(
    previous=Window(Lag("best_1rm"), order_by="workout__started_at")))
prova("Window(Max(EPLEY)) inline, senza il passaggio aggregato",
      lambda: WorkoutSet.objects.working().filter(**BASE)
      .values("workout_id", "workout__started_at")
      .annotate(running_max=Window(Max(EPLEY), order_by="workout__started_at",
                                   frame=RowRange(start=None, end=0))))

print("\n--- B. l'aggregato diventa una Subquery, poi la Window ci sta sopra ---")
def best_per_workout_subquery():
    """`Workout` come riga di base: il massimale della sessione arriva da una
    `Subquery` correlata, che **non e' un aggregato** agli occhi della query
    esterna, quindi la `Window` ci si impila sopra."""
    inner = (WorkoutSet.objects.working()
             .filter(workout=OuterRef("pk"), exercise=ex, reps__lte=MAX_REPS_FOR_1RM)
             .values("workout").annotate(m=Max(EPLEY)).values("m"))
    return (Workout.objects.filter(user=utente, sets__exercise=ex).distinct()
            .annotate(best_1rm=Subquery(inner, output_field=FloatField())))

ibrida = prova("Workout + Subquery(Max) + Window(Max) + Window(Lag)",
    lambda: best_per_workout_subquery().annotate(
        running_max=Window(Max("best_1rm"), order_by="started_at",
                           frame=RowRange(start=None, end=0)),
        previous=Window(Lag("best_1rm"), order_by="started_at"),
    ).values("id", "started_at", "best_1rm", "running_max", "previous")
      .order_by("started_at"))

if ibrida is not None:
    print("\n--- C. cosa regge SOPRA la forma ibrida ---")
    def ib():
        return best_per_workout_subquery().annotate(
            running_max=Window(Max("best_1rm"), order_by="started_at",
                               frame=RowRange(start=None, end=0)),
            previous=Window(Lag("best_1rm"), order_by="started_at"),
        ).values("id","started_at","best_1rm","running_max","previous").order_by("started_at")
    prova(".filter() su campo normale (taglio temporale)",
          lambda: ib().filter(started_at__year__gte=2025))
    prova(".filter() sull'annotazione di finestra", lambda: ib().filter(running_max__gt=0))
    prova(".order_by('-running_max')", lambda: ib().order_by("-running_max"))
    prova("slice [:12]", lambda: ib()[:12])
    try: print(f"  REGGE   .count() -> {ib().count()}")
    except Exception as e: print(f"  ROMPE   .count()\n          {type(e).__name__}: {e}")
    print("\n  SQL della forma ibrida:\n  " + str(ib().query))

print("\n--- D. il ripiego puro: due Subquery correlate, nessuna Window ---")
def subquery_pura():
    fino_a_qui = (WorkoutSet.objects.working()
        .filter(exercise=ex, workout__user=utente, reps__lte=MAX_REPS_FOR_1RM,
                workout__started_at__lte=OuterRef("workout__started_at"))
        .values("exercise").annotate(m=Max(EPLEY)).values("m"))
    return (per_workout()
            .annotate(running_max=Subquery(fino_a_qui, output_field=FloatField()))
            .order_by("workout__started_at"))
prova("Subquery correlata su per_workout()", subquery_pura)

print("\n--- E. tempi (min di 5 giri) ---")
def crono(fn, giri=5):
    t=[]
    for _ in range(giri):
        a=time.perf_counter(); r=list(fn()); t.append(time.perf_counter()-a)
    return min(t), len(r)
for nome, fn in [
    ("ibrida  Subquery(Max) + Window", (lambda: best_per_workout_subquery().annotate(
        running_max=Window(Max("best_1rm"), order_by="started_at", frame=RowRange(start=None,end=0)),
        previous=Window(Lag("best_1rm"), order_by="started_at"),
    ).values("id","started_at","best_1rm","running_max","previous").order_by("started_at"))),
    ("ripiego Subquery correlata   ", subquery_pura),
    ("solo l'aggregato per sessione", per_workout),
]:
    try:
        ms, n = crono(fn); print(f"  {nome}: {ms*1000:8.1f} ms  ({n} righe)")
    except Exception as e:
        print(f"  {nome}: ROMPE ({type(e).__name__})")
