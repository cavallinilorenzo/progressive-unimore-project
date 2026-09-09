"""Prototipo #98 — A3: una `Window` sopra un aggregato, e cosa Django accetta.

Codice usa e getta. Si lancia dalla radice del repo:

    uv run python prototypes/t98-a3-window/probe.py

Risponde alle quattro domande del ticket, una sonda per domanda, e stampa il
SQL generato dove il SQL e' la risposta. Non importa niente di applicativo
oltre ai modelli e a `training/querysets.py`.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.db import connection
from django.db.models import F, FloatField, Max, OuterRef, Subquery, Window
from django.db.models.expressions import RowRange
from django.db.models.functions import Lag

from training.models import Exercise, User, WorkoutSet
from training.querysets import EPLEY, MAX_REPS_FOR_1RM


def rule(titolo):
    print("\n" + "=" * 72)
    print(titolo)
    print("=" * 72)


def esito(etichetta, fn):
    """Esegue `fn`, stampa se ha retto e cosa ha detto Django quando no."""
    try:
        valore = fn()
        print(f"  REGGE   {etichetta}")
        return valore
    except Exception as exc:
        print(f"  ROMPE   {etichetta}")
        print(f"          {type(exc).__name__}: {exc}")
        return None


def cronometra(fn, giri=3):
    tempi = []
    for _ in range(giri):
        t = time.perf_counter()
        risultato = fn()
        tempi.append(time.perf_counter() - t)
    return min(tempi), risultato


# --------------------------------------------------------------------------
# Il soggetto: l'utente della demo e l'esercizio con lo storico piu' lungo.
#
# `seed_synthetic.DEMO_USERNAME` vale ancora `demo064`, ma quello e' il nome
# **prima** che `assegna_username` lo sostituisca col nome della persona: nel
# database seedato l'utente della demo e' `cavallinilorenzo`. La mappa #96 lo
# chiama «Martina Longo»: e' un residuo, il nome e' cambiato con #95.
# --------------------------------------------------------------------------

utente = User.objects.get(username="cavallinilorenzo")

conteggi = (
    WorkoutSet.objects.working()
    .filter(workout__user=utente, reps__lte=MAX_REPS_FOR_1RM)
    .values("exercise_id", "exercise__name")
    .annotate(allenamenti=Max("workout_id"))
    .order_by()
)
per_esercizio = sorted(
    (
        (
            e["exercise_id"],
            e["exercise__name"],
            WorkoutSet.objects.working()
            .filter(
                workout__user=utente,
                exercise_id=e["exercise_id"],
                reps__lte=MAX_REPS_FOR_1RM,
            )
            .values("workout_id")
            .distinct()
            .count(),
        )
        for e in conteggi
    ),
    key=lambda r: -r[2],
)

rule("Il soggetto")
print(f"  utente: {utente.username} ({utente.get_full_name() or '—'}), "
      f"peso corporeo {utente.body_mass_kg}")
print(f"  serie totali nel DB: {WorkoutSet.objects.count():,}")
print(f"  esercizi con storico: {len(per_esercizio)}")
for eid, nome, n in per_esercizio[:5]:
    print(f"    - {nome}: {n} allenamenti distinti")

ex_id, ex_nome, ex_n = per_esercizio[0]
ex = Exercise.objects.get(pk=ex_id)
print(f"\n  esercizio scelto: {ex_nome} ({ex_n} allenamenti)")


# --------------------------------------------------------------------------
# 1. La query della spec gira?
# --------------------------------------------------------------------------

def per_workout():
    return (
        WorkoutSet.objects.working()
        .filter(exercise=ex, workout__user=utente, reps__lte=MAX_REPS_FOR_1RM)
        .values("workout_id", "workout__started_at")
        .annotate(best_1rm=Max(EPLEY))
    )


def progressione():
    return per_workout().annotate(
        running_max=Window(
            Max("best_1rm"),
            order_by="workout__started_at",
            frame=RowRange(start=None, end=0),
        ),
        previous=Window(Lag("best_1rm"), order_by="workout__started_at"),
    )


rule("1. La query della spec, cosi' com'e' scritta in 04-analisi.md")

righe = esito("costruzione + valutazione", lambda: list(progressione()))
if righe is not None:
    print(f"          {len(righe)} righe")
    for r in righe[:4]:
        print(f"          {r}")
    print("\n  SQL generato:")
    print("  " + str(progressione().query).replace("\n", "\n  "))


# --------------------------------------------------------------------------
# 2. Cosa si rompe quando ci si filtra / ordina / affetta sopra.
# --------------------------------------------------------------------------

rule("2. Cosa regge dopo l'annotazione di finestra")

esito(
    ".filter() su un campo normale (taglio temporale)",
    lambda: list(progressione().filter(workout__started_at__gte="2025-01-01")),
)
esito(
    ".filter() sull'annotazione di finestra stessa",
    lambda: list(progressione().filter(running_max__gt=0)),
)
esito(
    ".filter() sull'aggregato sottostante (best_1rm)",
    lambda: list(progressione().filter(best_1rm__gt=0)),
)
esito(
    ".order_by() su un campo normale",
    lambda: list(progressione().order_by("workout__started_at")),
)
esito(
    ".order_by() sull'annotazione di finestra",
    lambda: list(progressione().order_by("-running_max")),
)
esito("slice [:12]", lambda: list(progressione()[:12]))
esito(
    "taglio temporale PRIMA della finestra (filtro sul queryset aggregato)",
    lambda: list(
        per_workout()
        .filter(workout__started_at__gte="2025-01-01")
        .annotate(
            running_max=Window(
                Max("best_1rm"),
                order_by="workout__started_at",
                frame=RowRange(start=None, end=0),
            ),
            previous=Window(Lag("best_1rm"), order_by="workout__started_at"),
        )
    ),
)
esito(".count()", lambda: progressione().count())


# --------------------------------------------------------------------------
# 3. Il ripiego: `Subquery` correlata, mai SQL grezzo.

rule("Esito")
print("""
  La query della spec non gira: e' un FieldError in COSTRUZIONE, non un
  errore di SQL. `Window(Max("best_1rm"))` dove `best_1rm` e' gia' un
  aggregato: Django rifiuta prima ancora di parlare col database, quindi
  nessuna delle prove del punto 2 dice niente sulla finestra — dicono tutte
  lo stesso errore, perche' nessuna arriva a costruirsi.

  Le varianti stanno in `varianti.py`, la forma che vince in `ibrida.py`.
""")
