"""Rigenera le schede e lo storico allenamenti dell'utente della demo.

    python manage.py seed_demo_lorenzo --reset

A differenza di `seed_synthetic`, questo comando **non crea popolazione**: si
appoggia all'utente della demo che `seed_synthetic` ha già generato
(`DEMO_USERNAME_FINALE`, `cavallinilorenzo`) e gli sostituisce solo le schede e
gli allenamenti — mai gli altri 99 utenti sintetici, e mai i numeri su cui
`seed_synthetic` misura l'identità della popolazione (`make_users`,
`generate`): quelli restano il suo problema, non il nostro.

Nasce perché lo storico che l'utente della demo aveva finora — che fosse
l'assegnazione generica di `seed_synthetic` o un import a mano — non usava le
sue stesse schede: nomi di scheda a caso da una parte, allenamenti "Ppl —
giorno N" senza `routine` dall'altra. Una demo che mostra il legame fra scheda
e allenamento (ADR-0002) dovrebbe *usarlo*, non aggirarlo.

Qui si generano dieci schede con nomi ed esercizi reali del catalogo, e circa
un anno di storico — 2025-09-12 → 2026-09-11 — di allenamenti nati **da
quelle schede**, a rotazione, con una progressione di carico semplice ma non
piatta: le ripetizioni salgono verso l'alto del range, poi il carico sale di
un incremento dell'attrezzo e le ripetizioni ripartono — la stessa regola
della doppia progressione del coach, letta al contrario per generare dati
invece che per consigliarli.
"""

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from training.management.commands.seed_synthetic import DEMO_USERNAME_FINALE
from training.models import Exercise, Routine, RoutineExercise, User, Workout, WorkoutSet

SEED = 20260911
END_DATE = date(2026, 9, 11)
START_DATE = END_DATE - timedelta(days=364)

#: Giorni della settimana candidati per un allenamento: lun, mar, gio, ven, sab
#: (`date.weekday()`: 0 = lunedì). Non tutti si concretizzano — `ADERENZA`
#: sotto ne scarta una quota per somigliare a una vita vera.
GIORNI_CANDIDATI = {0, 1, 3, 4, 5}
ADERENZA = 0.88
QUOTA_SALTATE = 0.08

#: `{nome esercizio: (serie, ripetizioni minime, ripetizioni massime, carico
#: iniziale in kg)}`. I nomi sono quelli esatti di `data/catalog/exercises.csv`
#: — niente di nuovo entra nel catalogo (ADR-0001), si pesca da lì.
ESERCIZI = {
    "Panca piana con bilanciere": (4, 5, 8, Decimal("50")),
    "Panca inclinata con bilanciere": (3, 6, 10, Decimal("40")),
    "Military press con bilanciere": (4, 5, 8, Decimal("35")),
    "Alzate laterali con manubri": (3, 12, 15, Decimal("8")),
    "Push down ai cavi alla corda": (3, 10, 12, Decimal("20")),
    "Push down ai cavi con barra": (3, 10, 12, Decimal("25")),
    "Trazioni alla sbarra": (4, 6, 10, Decimal("0")),
    "Rematore con bilanciere": (4, 6, 10, Decimal("50")),
    "Pulldown a braccia tese ai cavi": (3, 10, 12, Decimal("45")),
    "Curl con bilanciere": (3, 8, 12, Decimal("25")),
    "Curl con manubri": (3, 10, 12, Decimal("12")),
    "Curl con bilanciere EZ": (3, 8, 12, Decimal("20")),
    "Curl a martello con manubri": (3, 10, 12, Decimal("12")),
    "Face pull ai cavi": (3, 12, 15, Decimal("15")),
    "Squat con bilanciere": (4, 5, 8, Decimal("60")),
    "Leg press": (4, 8, 12, Decimal("120")),
    "Stacco rumeno con bilanciere": (3, 8, 10, Decimal("60")),
    "Leg curl sdraiato": (3, 10, 12, Decimal("35")),
    "Leg curl seduto": (3, 10, 12, Decimal("35")),
    "Leg extension": (3, 10, 12, Decimal("40")),
    "Hip thrust con bilanciere": (4, 8, 10, Decimal("60")),
    "Calf raise in piedi alla macchina": (4, 12, 15, Decimal("60")),
    "Calf raise seduto alla macchina": (4, 12, 15, Decimal("40")),
    "Croci ai cavi": (3, 12, 15, Decimal("15")),
    "Dip alle parallele": (3, 8, 12, Decimal("0")),
    "French press con bilanciere EZ": (3, 10, 12, Decimal("20")),
    "Lat machine avanti": (3, 10, 12, Decimal("45")),
    "Alzate posteriori con manubri": (3, 12, 15, Decimal("8")),
    "Crunch a terra": (3, 15, 20, Decimal("0")),
    "Plank": (3, 1, 1, Decimal("0")),
    "Goblet squat con kettlebell": (3, 10, 12, Decimal("16")),
    "Affondi con manubri": (3, 10, 12, Decimal("14")),
    "Chest press alla macchina": (3, 10, 12, Decimal("40")),
    "Rematore alla macchina": (3, 10, 12, Decimal("45")),
}

#: Le dieci schede, nell'ordine in cui compaiono nella rotazione settimanale.
#: «Upper» e «Full Body» sono le due che l'utente della demo aveva già; le
#: altre otto completano un programma vero — push/pull/legs più una
#: suddivisione per gruppi, più una sessione leggera.
SCHEDE = {
    "Push": [
        "Panca piana con bilanciere",
        "Panca inclinata con bilanciere",
        "Military press con bilanciere",
        "Alzate laterali con manubri",
        "Push down ai cavi alla corda",
    ],
    "Pull": [
        "Trazioni alla sbarra",
        "Rematore con bilanciere",
        "Pulldown a braccia tese ai cavi",
        "Face pull ai cavi",
        "Curl con bilanciere",
    ],
    "Legs": [
        "Squat con bilanciere",
        "Leg press",
        "Stacco rumeno con bilanciere",
        "Leg curl sdraiato",
        "Calf raise in piedi alla macchina",
    ],
    "Upper": [
        "Panca piana con bilanciere",
        "Rematore con bilanciere",
        "Military press con bilanciere",
        "Curl con manubri",
        "Push down ai cavi con barra",
    ],
    "Lower": [
        "Squat con bilanciere",
        "Stacco rumeno con bilanciere",
        "Leg extension",
        "Leg curl seduto",
        "Hip thrust con bilanciere",
        "Calf raise seduto alla macchina",
    ],
    "Full Body": [
        "Squat con bilanciere",
        "Panca piana con bilanciere",
        "Rematore con bilanciere",
        "Military press con bilanciere",
        "Curl con bilanciere",
    ],
    "Petto e tricipiti": [
        "Panca piana con bilanciere",
        "Panca inclinata con bilanciere",
        "Croci ai cavi",
        "Dip alle parallele",
        "French press con bilanciere EZ",
    ],
    "Schiena e bicipiti": [
        "Trazioni alla sbarra",
        "Rematore con bilanciere",
        "Lat machine avanti",
        "Curl con bilanciere EZ",
        "Curl a martello con manubri",
    ],
    "Spalle e core": [
        "Military press con bilanciere",
        "Alzate laterali con manubri",
        "Alzate posteriori con manubri",
        "Crunch a terra",
        "Plank",
    ],
    "Total Body leggero": [
        "Goblet squat con kettlebell",
        "Affondi con manubri",
        "Chest press alla macchina",
        "Rematore alla macchina",
        "Plank",
    ],
}

ROTAZIONE = list(SCHEDE.keys())

#: Ogni quante volte che compare un esercizio il suo carico sale di un
#: incremento dell'attrezzo — la stessa cadenza con cui, nella doppia
#: progressione vera, le ripetizioni avrebbero già toccato l'estremo alto.
CADENZA_PROGRESSIONE = 4


class Command(BaseCommand):
    help = (
        "Sostituisce schede e allenamenti dell'utente della demo con dieci "
        "schede reali e un anno di storico coerente con esse."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Cancella prima le schede e gli allenamenti già presenti "
                "sull'utente della demo. Senza questo flag il comando si "
                "rifiuta di girare se ne trova già."
            ),
        )
        parser.add_argument("--seed", type=int, default=SEED)

    def handle(self, *args, **options):
        try:
            utente = User.objects.get(username=DEMO_USERNAME_FINALE)
        except User.DoesNotExist:
            raise CommandError(
                f"L'utente della demo «{DEMO_USERNAME_FINALE}» non esiste. "
                "Fai prima girare `python manage.py seed_synthetic`."
            )

        ha_dati = (
            Routine.objects.filter(user=utente).exists()
            or Workout.objects.filter(user=utente).exists()
        )
        if ha_dati:
            if not options["reset"]:
                raise CommandError(
                    f"{DEMO_USERNAME_FINALE} ha già schede o allenamenti. "
                    "Usa --reset per sostituirli."
                )
            self.stdout.write(
                f"Cancello schede e allenamenti precedenti di {DEMO_USERNAME_FINALE}…"
            )
            # Gli allenamenti prima: cancellare una scheda con `routine` ancora
            # puntata da un allenamento la mette a `NULL` (ADR-0002) invece di
            # bloccarsi, ma qui si vuole ripartire da zero su entrambi i lati.
            Workout.objects.filter(user=utente).delete()
            Routine.objects.filter(user=utente).delete()

        rng = random.Random(options["seed"])

        with transaction.atomic():
            schede = self.crea_schede(utente)
            n_allenamenti, n_serie = self.genera_storico(utente, schede, rng)

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(schede)} schede e {n_allenamenti} allenamenti "
                f"({n_serie} serie) per {DEMO_USERNAME_FINALE}, dal "
                f"{START_DATE:%d/%m/%Y} all'{END_DATE:%d/%m/%Y}."
            )
        )

    def crea_schede(self, utente):
        """Le dieci `Routine`, coi loro `RoutineExercise` da `ESERCIZI`."""
        schede = {}
        for nome, nomi_esercizi in SCHEDE.items():
            scheda = Routine.objects.create(user=utente, name=nome)
            for posizione, nome_esercizio in enumerate(nomi_esercizi, start=1):
                serie, reps_min, reps_max, _ = ESERCIZI[nome_esercizio]
                RoutineExercise.objects.create(
                    routine=scheda,
                    exercise=Exercise.objects.get(name=nome_esercizio),
                    position=posizione,
                    target_sets=serie,
                    target_reps=reps_min,
                    target_reps_max=reps_max if reps_max != reps_min else None,
                )
            schede[nome] = scheda
        return schede

    def genera_storico(self, utente, schede, rng):
        """Un anno di `Workout`, a rotazione sulle dieci schede."""
        giorni_allenamento = [
            START_DATE + timedelta(days=offset)
            for offset in range((END_DATE - START_DATE).days + 1)
            if (START_DATE + timedelta(days=offset)).weekday() in GIORNI_CANDIDATI
            and rng.random() < ADERENZA
        ]

        # Le occorrenze sono per esercizio e non per scheda: uno squat
        # progredisce allo stesso ritmo in "Legs" e in "Full Body", perché è
        # lo stesso corpo a farlo.
        occorrenze = {}
        tutte_le_serie = []
        n_allenamenti = 0

        for indice, giorno in enumerate(giorni_allenamento):
            nome_scheda = ROTAZIONE[indice % len(ROTAZIONE)]
            scheda = schede[nome_scheda]

            ora = rng.choice([7, 8, 18, 19, 20])
            minuto = rng.choice([0, 15, 30, 45])
            iniziato = timezone.make_aware(
                datetime.combine(giorno, time(ora, minuto))
            )
            durata = rng.randint(45, 80)

            workout = Workout.objects.create(
                user=utente,
                routine=scheda,
                title=scheda.name,
                started_at=iniziato,
                ended_at=iniziato + timedelta(minutes=durata),
            )
            n_allenamenti += 1

            for voce in scheda.exercises.select_related("exercise__equipment").all():
                _, reps_min, reps_max, peso_iniziale = ESERCIZI[voce.exercise.name]
                occ = occorrenze.get(voce.exercise_id, 0)
                occorrenze[voce.exercise_id] = occ + 1

                incremento = voce.exercise.equipment.load_increment_kg
                peso = peso_iniziale + incremento * (occ // CADENZA_PROGRESSIONE)
                reps_base = min(reps_min + (occ % CADENZA_PROGRESSIONE), reps_max)

                for numero in range(1, voce.target_sets + 1):
                    saltata = rng.random() < QUOTA_SALTATE
                    reps = None
                    peso_serie = None
                    if not saltata:
                        reps = max(
                            reps_min, min(reps_max, reps_base + rng.choice([-1, 0, 0, 0, 1]))
                        )
                        peso_serie = peso
                    tutte_le_serie.append(
                        WorkoutSet(
                            workout=workout,
                            exercise=voce.exercise,
                            set_number=numero,
                            reps=reps,
                            weight=peso_serie,
                            set_type=WorkoutSet.SetType.WORKING,
                            is_completed=not saltata,
                        )
                    )

        WorkoutSet.objects.bulk_create(tutte_le_serie)
        return n_allenamenti, len(tutte_le_serie)
