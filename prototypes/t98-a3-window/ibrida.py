"""Prototipo #98, terza sonda: la forma ibrida corretta, e la semantica dei filtri."""
import os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django; django.setup()

from django.db.models import Count, FloatField, Max, OuterRef, Subquery, Window
from django.db.models.expressions import RowRange
from django.db.models.functions import Lag
from training.models import Exercise, User, Workout, WorkoutSet
from training.querysets import EPLEY, MAX_REPS_FOR_1RM

utente = User.objects.get(username="cavallinilorenzo")
ex = Exercise.objects.get(name="Panca piana con bilanciere")

def progressione(user, exercise):
    """A3, forma ibrida. Una riga per allenamento, nessun join che moltiplica."""
    massimale_sessione = (
        WorkoutSet.objects.working()
        .filter(workout=OuterRef("pk"), exercise=exercise, reps__lte=MAX_REPS_FOR_1RM)
        .values("workout").annotate(m=Max(EPLEY)).values("m"))
    sessioni_con_esercizio = (
        WorkoutSet.objects.working()
        .filter(exercise=exercise, reps__lte=MAX_REPS_FOR_1RM)
        .values("workout_id"))
    return (Workout.objects.filter(user=user, pk__in=sessioni_con_esercizio)
            .annotate(best_1rm=Subquery(massimale_sessione, output_field=FloatField()))
            .annotate(
                running_max=Window(Max("best_1rm"), order_by="started_at",
                                   frame=RowRange(start=None, end=0)),
                previous=Window(Lag("best_1rm"), order_by="started_at"))
            .values("id", "started_at", "best_1rm", "running_max", "previous")
            .order_by("started_at"))

def prova(etichetta, fn):
    try:
        r = list(fn()); print(f"  REGGE   {etichetta}  ({len(r)} righe)"); return r
    except Exception as e:
        print(f"  ROMPE   {etichetta}\n          {type(e).__name__}: {e}"); return None

print("--- 1. il conteggio torna? ---")
atteso = (WorkoutSet.objects.working()
          .filter(exercise=ex, workout__user=utente, reps__lte=MAX_REPS_FOR_1RM)
          .values("workout_id").distinct().count())
righe = prova("progressione ibrida", lambda: progressione(utente, ex))
print(f"          allenamenti distinti attesi: {atteso}")
print(f"          combacia: {len(righe) == atteso}")
for r in righe[:3]: print(f"          {r}")
print(f"          ultima: {righe[-1]}")
print(f"          running_max monotono: "
      f"{all(righe[i]['running_max'] <= righe[i+1]['running_max'] for i in range(len(righe)-1))}")
print(f"          previous[i] == best_1rm[i-1]: "
      f"{all(righe[i]['previous'] == righe[i-1]['best_1rm'] for i in range(1, len(righe)))}")

print("\n--- 2. cosa regge sopra, e con che semantica ---")
prova(".filter(started_at__gte=2026)", lambda: progressione(utente, ex).filter(started_at__year__gte=2026))
r = progressione(utente, ex).filter(started_at__year__gte=2026)
print(f"          prima riga del taglio: {list(r)[0] if r else None}")
print("          ^ running_max riparte dal taglio: il filtro finisce in WHERE,")
print("            cioe' PRIMA della finestra. Per un massimo cumulativo e' sbagliato.")
r2 = prova(".filter(running_max__gt=120)", lambda: progressione(utente, ex).filter(running_max__gt=120))
if r2: print(f"          prima riga: {r2[0]}")
prova(".order_by('-running_max')", lambda: progressione(utente, ex).order_by("-running_max"))
prova("slice [-12:] equivalente: list(...)[-12:]", lambda: list(progressione(utente, ex))[-12:])
prova("slice [:12]", lambda: progressione(utente, ex)[:12])
try: print(f"  REGGE   .count() -> {progressione(utente, ex).count()}")
except Exception as e: print(f"  ROMPE   .count(): {e}")

print("\n--- 3. quante query SQL, e quanto costa ---")
from django.db import connection
from django.test.utils import CaptureQueriesContext
with CaptureQueriesContext(connection) as ctx: list(progressione(utente, ex))
print(f"  query SQL emesse: {len(ctx.captured_queries)}")

def crono(fn, giri=7):
    t=[]
    for _ in range(giri):
        a=time.perf_counter(); r=list(fn()); t.append(time.perf_counter()-a)
    return min(t), len(r)
ms, n = crono(lambda: progressione(utente, ex))
print(f"  ibrida su {ex.name} ({n} allenamenti): {ms*1000:.1f} ms")

print("\n--- 4. il caso peggiore del database ---")
peggiore = (WorkoutSet.objects.working().filter(reps__lte=MAX_REPS_FOR_1RM)
            .values("workout__user_id", "exercise_id")
            .annotate(n=Count("workout_id", distinct=True))
            .order_by("-n").first())
u2 = User.objects.get(pk=peggiore["workout__user_id"])
e2 = Exercise.objects.get(pk=peggiore["exercise_id"])
print(f"  {u2.username} / {e2.name}: {peggiore['n']} allenamenti")
ms2, n2 = crono(lambda: progressione(u2, e2))
print(f"  ibrida: {ms2*1000:.1f} ms ({n2} righe)")

print("\n--- 5. e se l'esercizio non ha storico? ---")
vuoto = Exercise.objects.exclude(
    pk__in=WorkoutSet.objects.filter(workout__user=utente).values("exercise_id")).first()
print(f"  {vuoto.name}: {len(list(progressione(utente, vuoto)))} righe")
