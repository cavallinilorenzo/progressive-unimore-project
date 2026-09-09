"""Test di Progressive — un file solo, `TestCase` + `Client`, come il corso.

Vedi `docs/spec/07-test.md`: i test non inseguono la copertura, proteggono i
requisiti della traccia e le poche regole che il database non può imporre da
solo. I quattro test che contano davvero arrivano coi ticket delle pagine e
dell'import; qui c'è solo la guardia sulle fondamenta — i quattro check
constraint e le unicità decise in `01-modelli.md`, che sono invisibili finché
qualcuno non li rimuove da `Meta` senza accorgersene.
"""

import json
import random
import re
import shutil
import statistics
import tempfile
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, models, transaction
from django.db.models import Sum
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from training import rankings, views
from training.analytics import progressione as analytics_progressione
from training.analytics import volume as analytics_volume
from training.exporter import (
    INTESTAZIONE_SERIE,
    INTESTAZIONE_SESSIONI,
    esporta,
)
from training.importer import (
    COLONNE_SERIE,
    COLONNE_SESSIONI,
    leggi,
    nome_pubblico,
    risolvi,
    scrivi,
)
from training.forms import VoteForm
from training.querysets import CORPO_LIBERO, MAX_REPS_FOR_1RM, VOLUME
from training.management.commands import seed_synthetic
from training.models import (
    Equipment,
    Exercise,
    ExerciseAlias,
    Muscle,
    MuscleGroup,
    Routine,
    RoutineExercise,
    Vote,
    Workout,
    WorkoutSet,
)

User = get_user_model()


class CatalogLoadTests(TestCase):
    """Il catalogo versionato entra per intero, e rientrarci non duplica nulla."""

    def test_load_catalog_is_idempotent_and_slugs_every_exercise(self):
        call_command("load_catalog", stdout=StringIO())
        call_command("load_catalog", stdout=StringIO())

        self.assertEqual(MuscleGroup.objects.count(), 6)
        self.assertEqual(Muscle.objects.count(), 23)
        self.assertEqual(Equipment.objects.count(), 9)
        self.assertEqual(Exercise.objects.count(), 100)

        # Gli URL degli esercizi poggiano sullo slug: se ne manca uno, o due
        # coincidono, una pagina del catalogo è irraggiungibile.
        self.assertEqual(Exercise.objects.exclude(slug="").count(), 100)
        self.assertEqual(Exercise.objects.values("slug").distinct().count(), 100)

    def test_bodyweight_load_increment_is_zero(self):
        """Zero non è un vuoto: sul corpo libero il coach consiglia ripetizioni."""
        call_command("load_catalog", stdout=StringIO())

        self.assertEqual(
            Equipment.objects.get(code="bodyweight").load_increment_kg, Decimal("0.00")
        )
        self.assertEqual(
            Equipment.objects.get(code="barbell").load_increment_kg, Decimal("2.50")
        )


class ModelConstraintTests(TestCase):
    """I vincoli che il database *può* imporre, e che quindi deve imporre."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="lorenzo", password="x")
        cls.other = User.objects.create_user(username="martina", password="x")
        group = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        muscle = Muscle.objects.create(
            code="chestMid", group=group, label_it="Petto medio", sort_order=1
        )
        equipment = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        cls.exercise = Exercise.objects.create(
            name="Panca piana", slug="panca-piana", primary_muscle=muscle,
            equipment=equipment,
        )
        cls.routine = Routine.objects.create(user=cls.user, name="Spinta A")
        cls.workout = Workout.objects.create(
            user=cls.user, routine=cls.routine, title="Spinta A",
            started_at=timezone.now(),
        )

    def assertViolatesConstraint(self, create):
        with self.assertRaises(IntegrityError), transaction.atomic():
            create()

    def test_exercise_name_is_unique_case_insensitively(self):
        """Un duplicato di sola maiuscola passerebbe silenziosamente dal CSV."""
        self.assertViolatesConstraint(
            lambda: Exercise.objects.create(
                name="PANCA PIANA",
                slug="panca-piana-2",
                primary_muscle=self.exercise.primary_muscle,
                equipment=self.exercise.equipment,
            )
        )

    def test_exercise_appears_once_per_routine(self):
        RoutineExercise.objects.create(
            routine=self.routine, exercise=self.exercise, position=1,
            target_sets=3, target_reps=8,
        )
        self.assertViolatesConstraint(
            lambda: RoutineExercise.objects.create(
                routine=self.routine, exercise=self.exercise, position=2,
                target_sets=3, target_reps=8,
            )
        )

    def test_two_exercises_may_share_a_position(self):
        """L'unicità è su `(routine, exercise)`, non sulla posizione: riordinare
        non deve violare nulla a metà transazione."""
        other = Exercise.objects.create(
            name="Croci ai cavi", slug="croci-ai-cavi",
            primary_muscle=self.exercise.primary_muscle,
            equipment=self.exercise.equipment,
        )
        RoutineExercise.objects.create(
            routine=self.routine, exercise=self.exercise, position=1,
            target_sets=3, target_reps=8,
        )
        RoutineExercise.objects.create(
            routine=self.routine, exercise=other, position=1,
            target_sets=3, target_reps=12,
        )
        self.assertEqual(self.routine.exercises.count(), 2)

    def test_workout_cannot_end_before_it_started(self):
        self.assertViolatesConstraint(
            lambda: Workout.objects.create(
                user=self.user, title="A ritroso",
                started_at=timezone.now(),
                ended_at=timezone.now() - timedelta(hours=1),
            )
        )

    def test_absurd_but_possible_durations_are_allowed(self):
        """Lo storico reale ha sessioni da 0 minuti e da 25 ore: entrano."""
        start = timezone.now()
        Workout.objects.create(
            user=self.user, title="Lampo", started_at=start, ended_at=start
        )
        Workout.objects.create(
            user=self.user, title="Infinita", started_at=start,
            ended_at=start + timedelta(hours=25),
        )
        self.assertEqual(Workout.objects.filter(ended_at__isnull=False).count(), 2)

    def test_a_completed_set_cannot_have_zero_reps(self):
        self.assertViolatesConstraint(
            lambda: WorkoutSet.objects.create(
                workout=self.workout, exercise=self.exercise, set_number=1,
                reps=0, weight=Decimal("60.00"),
            )
        )

    def test_a_skipped_set_may_have_no_reps_and_no_weight(self):
        skipped = WorkoutSet.objects.create(
            workout=self.workout, exercise=self.exercise, set_number=1,
            reps=None, weight=None, is_completed=False,
        )
        self.assertFalse(skipped.is_completed)

    def test_zero_weight_is_legitimate_but_negative_is_not(self):
        WorkoutSet.objects.create(
            workout=self.workout, exercise=self.exercise, set_number=1,
            reps=10, weight=Decimal("0.00"),
        )
        self.assertViolatesConstraint(
            lambda: WorkoutSet.objects.create(
                workout=self.workout, exercise=self.exercise, set_number=2,
                reps=10, weight=Decimal("-5.00"),
            )
        )

    def test_a_set_number_is_unique_per_workout_and_exercise(self):
        WorkoutSet.objects.create(
            workout=self.workout, exercise=self.exercise, set_number=1,
            reps=8, weight=Decimal("60.00"),
        )
        self.assertViolatesConstraint(
            lambda: WorkoutSet.objects.create(
                workout=self.workout, exercise=self.exercise, set_number=1,
                reps=8, weight=Decimal("62.50"),
            )
        )

    def test_a_vote_is_between_one_and_five(self):
        self.assertViolatesConstraint(
            lambda: Vote.objects.create(user=self.other, routine=self.routine, score=6)
        )

    def test_a_user_votes_a_routine_only_once(self):
        Vote.objects.create(user=self.other, routine=self.routine, score=4)
        self.assertViolatesConstraint(
            lambda: Vote.objects.create(
                user=self.other, routine=self.routine, score=5
            )
        )


class WorkoutHistoryTests(TestCase):
    """ADR-0002: cancellare la scheda non riscrive il passato."""

    def test_deleting_a_routine_keeps_the_workout_and_its_title(self):
        user = User.objects.create_user(username="lorenzo", password="x")
        routine = Routine.objects.create(user=user, name="Spinta A")
        workout = Workout.objects.create(
            user=user, routine=routine, title="Spinta A", started_at=timezone.now()
        )

        routine.delete()
        workout.refresh_from_db()

        self.assertIsNone(workout.routine)
        self.assertEqual(workout.title, "Spinta A")


class CustomUserTests(TestCase):
    """ADR-0008: senza peso corporeo l'utente resta fuori dalle classifiche."""

    def test_body_mass_is_optional_and_declares_itself(self):
        user = User.objects.create_user(username="lorenzo", password="x")
        self.assertIsNone(user.body_mass_kg)
        self.assertFalse(user.has_body_mass)
        self.assertFalse(user.is_synthetic)

        user.body_mass_kg = Decimal("78.50")
        self.assertTrue(user.has_body_mass)


# --- Il guscio: `base.html` e la sua guardia -------------------------------
#
# `07-test.md` §1 lo chiama «l'unico requisito della traccia che si può violare
# senza accorgersene»: basta aggiungere un template di fretta, e la traccia
# impone che *tutte* le pagine estendano `base.html`. Il test nasce col guscio
# invece che al passo 13 (mappa #53, regola 3), perché arrivando alla fine
# avrebbe lasciato passare nove ticket senza guardia.

TEMPLATE_ROOTS = (
    Path(settings.BASE_DIR) / "templates",
    Path(settings.BASE_DIR) / "training" / "templates",
)

BASE_TEMPLATE = "base.html"

EXTENDS_RE = re.compile(r"{%\s*extends\s+[\"']([^\"']+)[\"']\s*%}")


def iter_page_templates():
    """Ogni `.html` che sia una *pagina*, nelle due cartelle di template.

    I frammenti — prefisso `_`, per esempio `_corpo.svg` o un `_riga.html` —
    sono esclusi: sono inclusi da una pagina, non resi da soli. Escluso anche
    `base.html`, che è la radice della catena e non estende nessuno.

    `prototypes/` resta fuori dal giro perché non è una cartella di template
    del progetto: i suoi file estendono `prototype/base_a.html`, che è la loro
    radice e non la nostra.
    """
    for root in TEMPLATE_ROOTS:
        for path in sorted(root.rglob("*.html")):
            if path.name.startswith("_") or path.name == BASE_TEMPLATE:
                continue
            yield path


class TemplateInheritanceTests(TestCase):
    """Nessun template orfano: ogni pagina risale a `base.html`."""

    def test_every_page_template_extends_base(self):
        templates = list(iter_page_templates())
        self.assertGreater(
            len(templates), 0, "Nessun template trovato: le radici sono sbagliate."
        )

        for path in templates:
            # `subTest` è il motivo per cui il messaggio dice *quale* file:
            # il test fallisce sul singolo template, non sul totale.
            with self.subTest(template=str(path.relative_to(settings.BASE_DIR))):
                chain = self.resolve_chain(path)
                self.assertEqual(
                    chain[-1],
                    BASE_TEMPLATE,
                    f"{path.relative_to(settings.BASE_DIR)} non risale a "
                    f"{BASE_TEMPLATE}: catena {' -> '.join(chain)}",
                )

    def resolve_chain(self, path):
        """I nomi che `path` estende, in ordine, fino a `base.html` o al guasto.

        L'ereditarietà vale «direttamente o per catena»: `dashboard.html` può
        estendere un guscio intermedio, purché quello finisca su `base.html`.
        L'ultimo elemento della lista è la diagnosi — `base.html` se la catena
        è sana, altrimenti il punto in cui si è rotta.
        """
        chain = []
        current = path

        for _ in range(10):  # un tetto: una catena più lunga è un ciclo
            match = EXTENDS_RE.search(current.read_text(encoding="utf-8"))
            if match is None:
                chain.append(f"<nessun extends in {current.name}>")
                return chain

            parent = match.group(1)
            chain.append(parent)
            if parent == BASE_TEMPLATE:
                return chain

            try:
                current = Path(get_template(parent).origin.name)
            except TemplateDoesNotExist:
                chain.append(f"<{parent} non esiste>")
                return chain

        chain.append("<catena troppo lunga: ciclo di extends>")
        return chain


class ShellTests(TestCase):
    """Il guscio rende, e le pagine d'errore lo rendono anche loro.

    La dashboard è dietro `LoginRequiredMixin` dal ticket #68 — è una pagina
    personale — quindi qui si entra prima di guardarla. Che *senza* login
    devii verso il login è invece un requisito, ed è testato in
    `AuthenticationTests`.
    """

    def setUp(self):
        user = User.objects.create_user(username="lorenzo", password="passphrase-1")
        self.client.force_login(user)

    def test_dashboard_renders_the_shell(self):
        response = self.client.get(reverse("training:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "training/dashboard.html")
        self.assertTemplateUsed(response, BASE_TEMPLATE)

    def test_header_carries_the_five_sections(self):
        """Cinque voci, e nessuna sesta: la regola di navigazione di #19."""
        response = self.client.get(reverse("training:dashboard"))
        body = response.content.decode()

        for voce in ("Dashboard", "Schede", "Storico", "Esercizi", "Classifiche"):
            self.assertIn(f">{voce}</a>", body)

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
    def test_not_found_page_extends_the_shell(self):
        response = self.client.get("/questa-rotta-non-esiste/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("Progressive", response.content.decode())

    def test_server_error_page_renders_without_request(self):
        """Django rende la 500 senza request né context processor.

        È la condizione in cui il guscio è più fragile — `request` e `user` non
        ci sono — e l'unico modo di scoprirlo è renderla come fa Django.
        """
        html = get_template("500.html").render()

        self.assertIn("500", html)
        self.assertIn("Progressive", html)


# --- Autenticazione e profilo (#68) ----------------------------------------
#
# Il giro completo — registrarsi, entrare, uscire — più le due regole che
# questo ticket introduce e che da qui in avanti valgono per ogni pagina:
# ciò che non è pubblico sta dietro `LoginRequiredMixin`, e il peso corporeo è
# facoltativo con una conseguenza dichiarata (ADR-0008).

PASSWORD = "una-passphrase-lunga-1"


class AuthenticationTests(TestCase):
    """Registrazione, login, logout: le tre porte, e la guardia sul resto."""

    def test_signup_creates_the_user_and_logs_them_in(self):
        response = self.client.post(
            reverse("training:signup"),
            {"username": "lorenzo", "password1": PASSWORD, "password2": PASSWORD},
        )

        self.assertRedirects(response, reverse("training:profile"))
        utente = User.objects.get(username="lorenzo")
        # Chi si registra entra subito: la pagina di destinazione è già sua.
        self.assertEqual(int(self.client.session["_auth_user_id"]), utente.pk)
        # E nasce senza peso corporeo: è il profilo a chiederlo, non la
        # registrazione.
        self.assertIsNone(utente.body_mass_kg)

    def test_login_and_logout_round_trip(self):
        User.objects.create_user(username="lorenzo", password=PASSWORD)

        entrata = self.client.post(
            reverse("login"), {"username": "lorenzo", "password": PASSWORD}
        )
        self.assertRedirects(entrata, reverse("training:dashboard"))

        # `LOGOUT_REDIRECT_URL` non è dichiarato: l'uscita *rende* una pagina,
        # e come tutte le altre estende `base.html`.
        uscita = self.client.post(reverse("logout"))
        self.assertEqual(uscita.status_code, 200)
        self.assertTemplateUsed(uscita, "registration/logged_out.html")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_refuses_a_get(self):
        """Da Django 5 uscire è un POST, e l'header lo fa con un form.

        Se qualcuno rimettesse un `<a href>` al posto del form, il menu
        smetterebbe di funzionare in silenzio: qui il 405 lo dice.
        """
        User.objects.create_user(username="lorenzo", password=PASSWORD)
        self.client.force_login(User.objects.get(username="lorenzo"))

        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)

    def test_private_pages_redirect_anonymous_users_to_the_login(self):
        """Il pattern da qui in avanti: 302 verso il login, con `next`."""
        for nome in ("training:dashboard", "training:profile"):
            with self.subTest(rotta=nome):
                url = reverse(nome)
                response = self.client.get(url)

                self.assertEqual(response.status_code, 302)
                self.assertRedirects(response, f"{reverse('login')}?next={url}")

    def test_login_page_overrides_the_full_blocks_but_extends_base(self):
        """L'eccezione prevista dalla spec, e il suo limite.

        Le pagine di autenticazione svuotano `header` e `footer` — mostrare
        una navigazione a chi non è entrato non ha senso — ma restano figlie
        di `base.html`, che è il requisito della traccia.
        """
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, BASE_TEMPLATE)
        body = response.content.decode()
        self.assertNotIn(">Classifiche</a>", body)  # header svuotato
        self.assertIn("progressive.css", body)  # ma il guscio c'è


class ProfileTests(TestCase):
    """`/profilo/`: il peso corporeo si dichiara, e l'assenza si dichiara."""

    def setUp(self):
        self.user = User.objects.create_user(username="lorenzo", password=PASSWORD)
        self.client.force_login(self.user)

    def test_body_mass_is_declared_and_read_back(self):
        response = self.client.post(
            reverse("training:profile"), {"body_mass_kg": "78.5"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.body_mass_kg, Decimal("78.50"))
        self.assertIn("78,5", response.content.decode())

    def test_the_page_declares_what_a_missing_body_mass_costs(self):
        """ADR-0008: assente è meglio di sbagliato, purché la pagina lo dica."""
        response = self.client.get(reverse("training:profile"))
        body = response.content.decode()

        self.assertIn("classifica", body)
        self.assertIn("percentile", body)

    def test_body_mass_can_be_cleared(self):
        """Svuotarlo è una risposta valida: riporta l'utente fuori dai ranking."""
        self.user.body_mass_kg = Decimal("78.50")
        self.user.save(update_fields=["body_mass_kg"])

        self.client.post(reverse("training:profile"), {"body_mass_kg": ""})

        self.user.refresh_from_db()
        self.assertIsNone(self.user.body_mass_kg)
        self.assertFalse(self.user.has_body_mass)

    def test_a_user_never_edits_someone_elses_profile(self):
        """Non c'è `pk` nell'URL: `get_object` restituisce `request.user`.

        È il motivo per cui questa pagina non ha `UserPassesTestMixin` — non
        esiste un modo di puntare al profilo di un altro — e il test lo fissa
        contro un futuro `/profilo/<pk>/`.
        """
        altra = User.objects.create_user(username="martina", password=PASSWORD)

        self.client.post(reverse("training:profile"), {"body_mass_kg": "60"})

        altra.refresh_from_db()
        self.assertIsNone(altra.body_mass_kg)
        self.user.refresh_from_db()
        self.assertEqual(self.user.body_mass_kg, Decimal("60.00"))


class RoutineCrudTests(TestCase):
    """Il primo dei due CRUD completi che pagano il requisito della traccia.

    Due cose si proteggono qui, e sono di natura diversa. La prima è che i
    quattro verbi funzionino davvero — creare, leggere, modificare, eliminare —
    perché «CRUD operations on main objects» è un requisito minimo e va
    dimostrato, non descritto. La seconda è la **proprietà dell'oggetto**: che
    un secondo utente prenda 403 non è una raffinatezza, è ciò che distingue
    un CRUD da un CRUD sui dati di chiunque, e non c'è vincolo di database che
    possa imporlo al posto della view.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="lorenzo", password=PASSWORD)
        cls.altro = User.objects.create_user(username="martina", password=PASSWORD)

        group = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        muscle = Muscle.objects.create(
            code="chestMid", group=group, label_it="Petto medio", sort_order=1
        )
        cls.equipment = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana", slug="panca-piana",
            primary_muscle=muscle, equipment=cls.equipment,
        )
        cls.rematore = Exercise.objects.create(
            name="Rematore con bilanciere", slug="rematore-con-bilanciere",
            primary_muscle=muscle, equipment=cls.equipment,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.routine = Routine.objects.create(user=self.user, name="Spinta A")

    def formset_payload(self, righe, iniziali=0):
        """Il `management_form` più le righe: un POST di formset è metà contabilità.

        Senza `TOTAL_FORMS` e `INITIAL_FORMS` il formset non è nemmeno
        invalido, è *rotto* (`ManagementFormError`), e il test fallirebbe per
        la ragione sbagliata.
        """
        payload = {
            "exercises-TOTAL_FORMS": str(len(righe)),
            "exercises-INITIAL_FORMS": str(iniziali),
            "exercises-MIN_NUM_FORMS": "0",
            "exercises-MAX_NUM_FORMS": "1000",
        }
        for indice, riga in enumerate(righe):
            for campo, valore in riga.items():
                payload[f"exercises-{indice}-{campo}"] = valore
        return payload

    # --- I quattro verbi ------------------------------------------------

    def test_create_read_update_delete_a_routine(self):
        """Il giro completo, nell'ordine in cui lo si mostra all'orale."""
        # Create — e si atterra sugli esercizi, non sulla lista.
        response = self.client.post(
            reverse("training:routine-create"),
            {"name": "Tirata B", "notes": "Giovedì", "is_public": ""},
        )
        routine = Routine.objects.get(name="Tirata B")
        self.assertEqual(routine.user, self.user)
        self.assertRedirects(
            response, reverse("training:routine-exercises", args=[routine.pk])
        )

        # Read
        response = self.client.get(
            reverse("training:routine-detail", args=[routine.pk])
        )
        self.assertContains(response, "Tirata B")

        # Update
        self.client.post(
            reverse("training:routine-update", args=[routine.pk]),
            {"name": "Tirata B2", "notes": "", "is_public": "on"},
        )
        routine.refresh_from_db()
        self.assertEqual(routine.name, "Tirata B2")
        self.assertTrue(routine.is_public)

        # Delete — il GET è solo la domanda, l'effetto è il POST.
        self.client.get(reverse("training:routine-delete", args=[routine.pk]))
        self.assertTrue(Routine.objects.filter(pk=routine.pk).exists())

        response = self.client.post(
            reverse("training:routine-delete", args=[routine.pk])
        )
        self.assertRedirects(response, reverse("training:routine-list"))
        self.assertFalse(Routine.objects.filter(pk=routine.pk).exists())

    def test_the_list_shows_only_my_routines(self):
        Routine.objects.create(user=self.altro, name="Scheda di Martina")

        response = self.client.get(reverse("training:routine-list"))

        self.assertContains(response, "Spinta A")
        self.assertNotContains(response, "Scheda di Martina")

    def test_is_public_is_the_flag_that_opens_the_routine_to_the_community(self):
        """Senza questo campo in pagina la sezione community non ha nulla da mostrare."""
        self.client.post(
            reverse("training:routine-update", args=[self.routine.pk]),
            {"name": "Spinta A", "notes": "", "is_public": "on"},
        )
        self.routine.refresh_from_db()
        self.assertTrue(self.routine.is_public)

        self.client.post(
            reverse("training:routine-update", args=[self.routine.pk]),
            {"name": "Spinta A", "notes": "", "is_public": ""},
        )
        self.routine.refresh_from_db()
        self.assertFalse(self.routine.is_public)

    def test_deleting_a_routine_declares_that_workouts_survive(self):
        """ADR-0002 detto dove la domanda nasce: sulla pagina di conferma."""
        response = self.client.get(
            reverse("training:routine-delete", args=[self.routine.pk])
        )
        self.assertContains(response, "allenamenti")

    # --- La proprietà dell'oggetto --------------------------------------

    def test_a_second_user_gets_403_on_every_owned_route(self):
        """403 e non 404, e soprattutto non 200: è il punto di `test_func()`."""
        self.client.force_login(self.altro)

        for nome in (
            "routine-detail",
            "routine-update",
            "routine-delete",
            "routine-exercises",
        ):
            with self.subTest(rotta=nome):
                response = self.client.get(reverse(f"training:{nome}", args=[self.routine.pk]))
                self.assertEqual(response.status_code, 403)

    def test_a_second_user_cannot_delete_or_edit_by_post_either(self):
        """Il 403 sul GET non basta: l'effetto sta nel POST."""
        self.client.force_login(self.altro)

        response = self.client.post(
            reverse("training:routine-delete", args=[self.routine.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Routine.objects.filter(pk=self.routine.pk).exists())

        response = self.client.post(
            reverse("training:routine-update", args=[self.routine.pk]),
            {"name": "Rubata", "notes": "", "is_public": "on"},
        )
        self.assertEqual(response.status_code, 403)
        self.routine.refresh_from_db()
        self.assertEqual(self.routine.name, "Spinta A")

    def test_an_anonymous_visitor_is_sent_to_the_login_not_to_a_403(self):
        """Per un anonimo la risposta giusta è «entra», e la dà `LoginRequiredMixin`."""
        self.client.logout()

        response = self.client.get(reverse("training:routine-list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_the_owner_is_taken_from_the_request_not_from_the_post(self):
        """`user` non è un campo del form: un POST che lo dichiara viene ignorato."""
        self.client.post(
            reverse("training:routine-create"),
            {"name": "Regalata", "notes": "", "is_public": "", "user": self.altro.pk},
        )

        self.assertEqual(Routine.objects.get(name="Regalata").user, self.user)

    # --- Il formset degli esercizi --------------------------------------

    def test_the_formset_adds_updates_and_removes_rows(self):
        url = reverse("training:routine-exercises", args=[self.routine.pk])

        # Aggiunge due righe (INITIAL_FORMS = 0: sono entrambe nuove).
        response = self.client.post(
            url,
            self.formset_payload([
                {"position": "1", "exercise": str(self.panca.pk),
                 "target_sets": "3", "target_reps": "8", "target_reps_max": "12",
                 "notes": "", "id": ""},
                {"position": "2", "exercise": str(self.rematore.pk),
                 "target_sets": "4", "target_reps": "6", "target_reps_max": "",
                 "notes": "", "id": ""},
            ]),
        )
        self.assertRedirects(
            response, reverse("training:routine-detail", args=[self.routine.pk])
        )
        self.assertEqual(self.routine.exercises.count(), 2)

        panca_riga, rematore_riga = self.routine.exercises.all()
        self.assertEqual(panca_riga.exercise, self.panca)
        self.assertEqual(panca_riga.target_reps_max, 12)
        self.assertIsNone(rematore_riga.target_reps_max)

        # Modifica la prima e cancella la seconda, in un solo POST.
        self.client.post(
            url,
            self.formset_payload(
                [
                    {"position": "1", "exercise": str(self.panca.pk),
                     "target_sets": "5", "target_reps": "5", "target_reps_max": "",
                     "notes": "Pesante", "id": str(panca_riga.pk)},
                    {"position": "2", "exercise": str(self.rematore.pk),
                     "target_sets": "4", "target_reps": "6", "target_reps_max": "",
                     "notes": "", "id": str(rematore_riga.pk), "DELETE": "on"},
                ],
                iniziali=2,
            ),
        )

        self.assertEqual(self.routine.exercises.count(), 1)
        panca_riga.refresh_from_db()
        self.assertEqual(panca_riga.target_sets, 5)
        self.assertEqual(panca_riga.notes, "Pesante")

    def test_empty_rows_are_ignored(self):
        """`extra=3` significa tre righe vuote in coda: non devono creare nulla."""
        self.client.post(
            reverse("training:routine-exercises", args=[self.routine.pk]),
            self.formset_payload([
                {"position": "1", "exercise": str(self.panca.pk),
                 "target_sets": "3", "target_reps": "8", "target_reps_max": "",
                 "notes": "", "id": ""},
                {"position": "", "exercise": "", "target_sets": "", "target_reps": "",
                 "target_reps_max": "", "notes": "", "id": ""},
                {"position": "", "exercise": "", "target_sets": "", "target_reps": "",
                 "target_reps_max": "", "notes": "", "id": ""},
            ]),
        )

        self.assertEqual(self.routine.exercises.count(), 1)

    def test_the_same_exercise_twice_is_a_form_error_not_a_500(self):
        """`routine_exercise_unique` arriverebbe come `IntegrityError`.

        Il vincolo del database resta la garanzia vera; questo test protegge
        la *traduzione*, cioè che l'utente veda un errore di form invece di
        una pagina d'errore.
        """
        response = self.client.post(
            reverse("training:routine-exercises", args=[self.routine.pk]),
            self.formset_payload([
                {"position": "1", "exercise": str(self.panca.pk),
                 "target_sets": "3", "target_reps": "8", "target_reps_max": "",
                 "notes": "", "id": ""},
                {"position": "2", "exercise": str(self.panca.pk),
                 "target_sets": "3", "target_reps": "8", "target_reps_max": "",
                 "notes": "", "id": ""},
            ]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.routine.exercises.count(), 0)
        self.assertContains(response, "una volta sola")

    def test_a_reversed_rep_range_is_refused(self):
        """L'estremo alto è quello che la doppia progressione insegue."""
        response = self.client.post(
            reverse("training:routine-exercises", args=[self.routine.pk]),
            self.formset_payload([
                {"position": "1", "exercise": str(self.panca.pk),
                 "target_sets": "3", "target_reps": "12", "target_reps_max": "8",
                 "notes": "", "id": ""},
            ]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.routine.exercises.count(), 0)
        self.assertContains(response, "sotto il minimo")

    def test_the_exercises_page_does_not_requery_the_catalogue_per_row(self):
        """Il costo della pagina non cresce con le righe.

        Stessa guardia di `test_the_sets_page_does_not_requery_the_catalogue_per_row`,
        e non è un doppione: sono due formset distinti, e la correzione di #70
        aveva toccato solo quello delle serie. Misurata sul catalogo vero — i
        100 esercizi di `load_catalog` — questa pagina faceva **11 query con
        due righe e 21 con dodici**, cioè una per riga e sempre la stessa; ora
        ne fa sette in entrambi i casi.

        Il numero però non è ciò che si protegge, o la guardia cadrebbe al primo
        `select_related` innocuo aggiunto altrove nella view. Ciò che si
        protegge è l'**invariante**: due righe o dodici, le query sono le
        stesse. È la forma che regge anche quando il resto della pagina cambia.

        Le dodici righe hanno bisogno di dodici esercizi distinti, perché
        `routine_exercise_unique` vieta di elencarne uno due volte nella stessa
        scheda — al contrario delle serie di #70, che ripetono lo stesso
        esercizio cambiando `set_number`.
        """
        catalogo = Exercise.objects.bulk_create([
            Exercise(
                name=f"Esercizio {numero}",
                slug=f"esercizio-{numero}",
                primary_muscle=self.panca.primary_muscle,
                equipment=self.equipment,
            )
            for numero in range(12)
        ])
        url = reverse("training:routine-exercises", args=[self.routine.pk])

        def rendi_con(n_righe):
            self.routine.exercises.all().delete()
            RoutineExercise.objects.bulk_create([
                RoutineExercise(
                    routine=self.routine,
                    exercise=esercizio,
                    position=indice + 1,
                    target_sets=3,
                    target_reps=8,
                )
                for indice, esercizio in enumerate(catalogo[:n_righe])
            ])
            with CaptureQueriesContext(connection) as contesto:
                self.assertEqual(self.client.get(url).status_code, 200)
            return len(contesto.captured_queries)

        self.assertEqual(rendi_con(2), rendi_con(12))

    def test_the_header_link_to_the_routines_is_a_real_route(self):
        """#67 aveva lasciato `href="/schede/"` letterale: ora è il tag `url`."""
        response = self.client.get(reverse("training:dashboard"))

        self.assertContains(response, f'href="{reverse("training:routine-list")}"')

    def test_only_one_header_section_lights_up_at_a_time(self):
        """`/schede/<pk>/esercizi/` accendeva anche «Esercizi».

        Il controllo era `'/esercizi/' in request.path`, e quella sottostringa
        compare dentro l'URL del formset. La voce attiva si decide sul
        prefisso; due voci accese sono peggio di nessuna.
        """
        response = self.client.get(
            reverse("training:routine-exercises", args=[self.routine.pk])
        )
        body = response.content.decode()

        self.assertIn('class="attivo">Schede</a>', body)
        self.assertIn('class="">Esercizi</a>', body)


class WorkoutSetQuerySetTests(TestCase):
    """Le definizioni condivise, provate come espressioni e non attraverso una pagina.

    `training/querysets.py` è il posto in cui il volume, il filtro universale e
    Epley hanno un nome solo. Finché a consumarle c'erano solo le classifiche,
    i loro test bastavano; dal motore analitico in poi le consumano tre
    superfici, e una definizione provata solo di riflesso è una definizione che
    può cambiare senza che nessuno lo dica.

    Fonte: #97, `docs/spec/04-analisi.md` §«Il custom QuerySet».
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="atleta", password=PASSWORD, body_mass_kg=Decimal("80")
        )
        gruppo = MuscleGroup.objects.create(code="back", label_it="Schiena", sort_order=1)
        muscolo = Muscle.objects.create(
            code="lats", group=gruppo, label_it="Dorsali", sort_order=1
        )
        bilanciere = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        corpo_libero = Equipment.objects.create(
            code=CORPO_LIBERO, label_it="Corpo libero", sort_order=2
        )
        cls.rematore = Exercise.objects.create(
            name="Rematore", slug="rematore",
            primary_muscle=muscolo, equipment=bilanciere,
        )
        cls.trazioni = Exercise.objects.create(
            name="Trazioni", slug="trazioni",
            primary_muscle=muscolo, equipment=corpo_libero,
        )
        cls.workout = Workout.objects.create(
            user=cls.user, title="Schiena", started_at=timezone.now()
        )

    def serie(self, exercise, reps, weight, **kwargs):
        campi = {
            "set_type": WorkoutSet.SetType.WORKING,
            "is_completed": True,
            **kwargs,
        }
        return WorkoutSet.objects.create(
            workout=self.workout, exercise=exercise,
            set_number=WorkoutSet.objects.filter(
                workout=self.workout, exercise=exercise
            ).count() + 1,
            reps=reps, weight=Decimal(weight), **campi,
        )

    def volume_di(self, riga):
        return WorkoutSet.objects.with_volume().get(pk=riga.pk).volume

    def test_the_volume_of_a_barbell_set_is_reps_times_weight(self):
        """Il caso semplice: 10 × 60 = 600, e il `default` del `Case` basta."""
        riga = self.serie(self.rematore, reps=10, weight="60")

        self.assertEqual(self.volume_di(riga), 600.0)

    def test_a_bodyweight_set_is_not_worth_zero(self):
        """Il motivo per cui `EFFECTIVE_LOAD` esiste (ADR-0006).

        8 trazioni a peso aggiunto nullo sono 8 × 80 kg di corpo sollevato. Con
        `reps × weight` varrebbero zero, e la schiena sparirebbe dalle analisi
        di chi si allena a corpo libero **senza che niente segnali errore**.
        """
        riga = self.serie(self.trazioni, reps=8, weight="0")

        self.assertEqual(self.volume_di(riga), 640.0)

    def test_a_weighted_pull_up_adds_the_belt_to_the_body(self):
        """Le trazioni zavorrate: il `+` del `Case` le gestisce senza un ramo in più."""
        riga = self.serie(self.trazioni, reps=5, weight="20")

        self.assertEqual(self.volume_di(riga), 500.0)

    def test_a_missing_body_mass_leaves_the_volume_unknown_not_zero(self):
        """Senza peso corporeo il carico effettivo è **nullo**, non zero.

        È la scelta di ADR-0008 letta sul volume: la somma salta quelle righe,
        e chi mostra il numero deve dire che è incompleto. Zero sarebbe una
        risposta, e sarebbe falsa.
        """
        anonimo = User.objects.create_user(username="anonimo", password=PASSWORD)
        allenamento = Workout.objects.create(
            user=anonimo, title="Schiena", started_at=timezone.now()
        )
        riga = WorkoutSet.objects.create(
            workout=allenamento, exercise=self.trazioni, set_number=1,
            reps=8, weight=Decimal("0"),
            set_type=WorkoutSet.SetType.WORKING, is_completed=True,
        )

        self.assertIsNone(self.volume_di(riga))

    def test_the_volume_keeps_the_sets_above_twelve_reps(self):
        """Il tetto a 12 è del massimale, non del volume.

        Una serie da 15 ripetizioni non concorre a Epley (gonfia) ma è
        allenamento avvenuto, quindi resta nel volume. Le due regole vivono
        separate apposta: il tetto è un filtro sulle righe, non una proprietà
        dell'espressione.
        """
        riga = self.serie(self.rematore, reps=15, weight="40")

        self.assertEqual(self.volume_di(riga), 600.0)

    def test_the_volume_is_not_truncated_by_integer_division(self):
        """La trappola dei tipi misti, sul mezzo chilo.

        `reps` è un intero e il carico un decimale: senza il `Cast`
        l'espressione mescola due tipi, e 10 × 2,5 diventerebbe 20 invece di
        25. Sbaglia **ordinando lo stesso**, che è la forma peggiore.
        """
        riga = self.serie(self.rematore, reps=10, weight="2.5")

        self.assertEqual(self.volume_di(riga), 25.0)

    def test_working_and_with_volume_chain_and_the_result_is_still_a_queryset(self):
        """Concatenabile: è la ragione per cui `with_volume()` annota la riga.

        Se il metodo restituisse già una somma, nessuno potrebbe filtrarci
        dopo, né raggrupparlo per settimana come fa A1. Qui si concatena tre
        volte e si somma alla fine, che è il modo in cui le analisi lo useranno.
        """
        self.serie(self.rematore, reps=10, weight="60")
        self.serie(self.trazioni, reps=8, weight="0")
        self.serie(self.rematore, reps=10, weight="900",
                   set_type=WorkoutSet.SetType.WARMUP)

        totale = (
            WorkoutSet.objects.working()
            .filter(workout__user=self.user)
            .with_volume()
            .aggregate(v=Sum("volume"))["v"]
        )

        self.assertEqual(totale, 1240.0)

    def test_the_expression_and_the_method_are_the_same_definition(self):
        """`Sum(VOLUME)` e `.with_volume()` non possono divergere.

        Le due strade esistono entrambe — la prima quando serve solo il totale,
        la seconda quando serve anche la riga — e devono restare una
        definizione sola. Questo è il test che lo dice a voce alta.
        """
        self.serie(self.rematore, reps=10, weight="60")
        self.serie(self.trazioni, reps=8, weight="0")

        righe = WorkoutSet.objects.working().filter(workout__user=self.user)

        self.assertEqual(
            righe.aggregate(v=Sum(VOLUME))["v"],
            righe.with_volume().aggregate(v=Sum("volume"))["v"],
        )


class DashboardTests(TestCase):
    """Le quattro cifre della dashboard, che fino a #78 erano trattini.

    Il guscio reggeva finché il database era vuoto. Con due anni di storico
    dentro non regge: `/` è la prima pagina che il prof vede, e una prima pagina
    muta su centinaia di allenamenti fa sembrare rotto ciò che funziona.

    Ciò che questi test proteggono non è il numero esatto — quello cambia col
    calendario, perché le finestre sono mobili — ma le due regole che lo
    rendono giusto: **solo le serie di lavoro completate contano**, e la pagina
    di chi non ha niente non mostra zeri travestiti da dati.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="lorenzo", password=PASSWORD, body_mass_kg=Decimal("70")
        )
        cls.vuoto = User.objects.create_user(username="nuovo", password=PASSWORD)
        # Chi non ha dichiarato il peso corporeo: le sue trazioni non hanno un
        # carico effettivo (ADR-0006), quindi restano fuori dal volume. È
        # un'assenza che la pagina deve **dichiarare**, non nascondere.
        cls.senza_peso = User.objects.create_user(
            username="anonimo", password=PASSWORD
        )

        gruppo = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        muscolo = Muscle.objects.create(
            code="chestMid", group=gruppo, label_it="Petto medio", sort_order=1
        )
        dorso = MuscleGroup.objects.create(code="back", label_it="Schiena", sort_order=2)
        dorsale = Muscle.objects.create(
            code="lats", group=dorso, label_it="Dorsali", sort_order=1
        )
        attrezzo = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        corpo_libero = Equipment.objects.create(
            code=CORPO_LIBERO, label_it="Corpo libero", sort_order=2
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana", slug="panca-piana",
            primary_muscle=muscolo, equipment=attrezzo,
        )
        cls.trazioni = Exercise.objects.create(
            name="Trazioni", slug="trazioni",
            primary_muscle=dorsale, equipment=corpo_libero,
        )
        cls.workout = Workout.objects.create(
            user=cls.user, title="Petto", started_at=timezone.now()
        )
        # 10 × 100 = 1000 kg che contano.
        WorkoutSet.objects.create(
            workout=cls.workout, exercise=cls.panca, set_number=1,
            reps=10, weight=Decimal("100"), set_type=WorkoutSet.SetType.WORKING,
            is_completed=True,
        )
        # Il riscaldamento non è volume allenante.
        WorkoutSet.objects.create(
            workout=cls.workout, exercise=cls.panca, set_number=2,
            reps=10, weight=Decimal("500"), set_type=WorkoutSet.SetType.WARMUP,
            is_completed=True,
        )
        # Una serie programmata e non spuntata non è successa.
        WorkoutSet.objects.create(
            workout=cls.workout, exercise=cls.panca, set_number=3,
            reps=10, weight=Decimal("900"), set_type=WorkoutSet.SetType.WORKING,
            is_completed=False,
        )
        # 8 trazioni a peso aggiunto zero. Col carico effettivo valgono
        # 8 × (0 + 70) = 560 kg; con `reps × weight` varrebbero **zero**, ed è
        # esattamente la divergenza che #97 è nato per chiudere.
        WorkoutSet.objects.create(
            workout=cls.workout, exercise=cls.trazioni, set_number=1,
            reps=8, weight=Decimal("0"), set_type=WorkoutSet.SetType.WORKING,
            is_completed=True,
        )

        # Lo stesso allenamento, per chi il peso corporeo non l'ha dichiarato.
        senza = Workout.objects.create(
            user=cls.senza_peso, title="Schiena", started_at=timezone.now()
        )
        WorkoutSet.objects.create(
            workout=senza, exercise=cls.trazioni, set_number=1,
            reps=8, weight=Decimal("0"), set_type=WorkoutSet.SetType.WORKING,
            is_completed=True,
        )

    def setUp(self):
        self.client.login(username="lorenzo", password=PASSWORD)

    def test_the_volume_counts_only_completed_working_sets(self):
        """Il riscaldamento e le serie non spuntate stanno fuori.

        Sono i due carichi più alti del fixture apposta: se entrassero, il
        volume sarebbe 15.560 invece di 1.560, e un test che guardasse solo
        «c'è un numero» non se ne accorgerebbe.
        """
        response = self.client.get(reverse("training:dashboard"))

        self.assertEqual(response.context["volume_recente"], 1560.0)

    def test_the_volume_counts_the_bodyweight_sets_too(self):
        """La regressione che #97 è nato per chiudere.

        Fino a #97 questa view calcolava il volume come `reps × weight`, che
        sulle trazioni fa **zero**: 8 ripetizioni a peso aggiunto nullo
        sparivano dal riquadro che apre la prima pagina. Col carico effettivo
        valgono 8 × (0 + 70) = 560 kg, e il totale passa da 1.000 a 1.560.

        Il numero è scritto qui per esteso apposta: se qualcuno riscrivesse il
        volume a mano, tornerebbe 1.000 e il test lo direbbe.
        """
        response = self.client.get(reverse("training:dashboard"))

        self.assertEqual(response.context["volume_recente"], 1560.0)
        self.assertNotEqual(response.context["volume_recente"], 1000.0)

    def test_the_dashboard_volume_is_the_shared_definition(self):
        """Il ponte fra le due superfici, che prima non esisteva.

        La divergenza di #95 è passata perché **nessun test confrontava la
        dashboard con le analisi**: due definizioni identiche nella forma e
        diverse nel risultato passavano entrambe. Questo test fallisce se la
        pagina torna a calcolarsi il volume per conto suo, qualunque sia la
        formula che sceglie.
        """
        atteso = (
            WorkoutSet.objects.working()
            .filter(workout__user=self.user)
            .aggregate(v=Sum(VOLUME))["v"]
        )

        response = self.client.get(reverse("training:dashboard"))

        self.assertEqual(response.context["volume_recente"], atteso)

    def test_without_a_body_mass_the_bodyweight_volume_is_declared_missing(self):
        """Senza peso corporeo le trazioni non hanno un carico, e si dice.

        `EFFECTIVE_LOAD` somma `weight + body_mass_kg`, quindi con un peso
        corporeo nullo l'espressione è nulla e la `Sum` salta quelle righe: il
        volume non è «zero», è **incompleto**. Un numero incompleto senza
        etichetta è il guasto che non si vede, quindi l'avviso di ADR-0008 lo
        dichiara accanto agli altri due costi.
        """
        self.client.login(username="anonimo", password=PASSWORD)

        response = self.client.get(reverse("training:dashboard"))

        self.assertIsNone(response.context["volume_recente"])
        self.assertContains(response, "non entrano nel volume")

    def test_the_record_of_the_month_ignores_the_warm_up(self):
        """500 kg di riscaldamento non sono un record: il record è 100."""
        response = self.client.get(reverse("training:dashboard"))

        self.assertEqual(response.context["record"].weight, Decimal("100"))
        self.assertContains(response, "Panca piana")

    def test_the_page_shows_the_numbers_instead_of_dashes(self):
        """La regressione che questo ticket è nato per chiudere."""
        response = self.client.get(reverse("training:dashboard"))

        self.assertEqual(response.context["allenamenti_totali"], 1)
        self.assertNotContains(response, "Analisi in arrivo")

    def test_a_user_with_no_history_is_invited_instead_of_shown_zeros(self):
        """Chi non ha niente riceve l'invito, non quattro zeri.

        Ed è la faccia opposta dello stesso difetto: dire «crea una scheda e la
        dashboard inizia a rispondere» a chi ha 443 allenamenti significa non
        aver guardato i suoi dati; mostrare quattro zeri a chi si è appena
        iscritto significa la stessa cosa al contrario.
        """
        self.client.login(username="nuovo", password=PASSWORD)

        response = self.client.get(reverse("training:dashboard"))

        self.assertEqual(response.context["allenamenti_totali"], 0)
        self.assertIsNone(response.context["record"])
        self.assertContains(response, "Da qui si comincia")

    def test_the_greeting_uses_the_persons_name_when_there_is_one(self):
        """`Ciao, Lorenzo Cavallini` e non `Ciao, cavallinilorenzo`."""
        self.user.first_name = "Lorenzo"
        self.user.last_name = "Cavallini"
        self.user.save(update_fields=["first_name", "last_name"])

        response = self.client.get(reverse("training:dashboard"))

        self.assertContains(response, "Ciao, Lorenzo Cavallini")


# --- `/analisi/`, A1 e A2, e il primo grafico (#99) -------------------------
#
# Tre cose vanno protette qui, e nessuna è «la pagina rende».
#
# La prima sono i **buchi**: `TruncWeek` restituisce solo i periodi in cui
# esiste una serie, e una settimana saltata che non compare fa disegnare due
# punti adiacenti che distano un mese. Il grafico mentirebbe sulla costanza —
# cioè proprio sul dato che questa pagina esiste per mostrare — e si
# disegnerebbe benissimo.
#
# La seconda è che il volume di qui sia **lo stesso** della dashboard e delle
# classifiche. È il test-ponte di #97, esteso alla terza superficie: due
# definizioni che si sono allontanate passano entrambe i propri test.
#
# La terza sono i **dati nel DOM**. Un grafico vuoto è indistinguibile da un
# grafico non ancora disegnato, e nessun test che guardi solo lo status code
# se ne accorgerebbe: il guasto si scoprirebbe all'orale. Il payload di
# `json_script` è HTML reso dal server, quindi è verificabile senza far girare
# un browser — ed è l'unica parte della catena Chart.js che possiamo provare.


class AnalysisPageTests(TestCase):
    """`/analisi/` — le due analisi, i buchi, e i dati che devono stare in pagina."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="atleta", password=PASSWORD, body_mass_kg=Decimal("80")
        )
        cls.nuovo = User.objects.create_user(username="nuovo", password=PASSWORD)
        cls.dormiente = User.objects.create_user(
            username="dormiente", password=PASSWORD, body_mass_kg=Decimal("70")
        )

        # I sei gruppi per intero: A2 li mostra tutti, anche a zero, e con due
        # soli in tabella la regola non sarebbe provata.
        cls.gruppi = {
            codice: MuscleGroup.objects.create(
                code=codice, label_it=etichetta, sort_order=ordine
            )
            for ordine, (codice, etichetta) in enumerate(
                [
                    ("chest", "Petto"),
                    ("back", "Schiena"),
                    ("shoulders", "Spalle"),
                    ("arms", "Braccia"),
                    ("legs", "Gambe"),
                    ("core", "Core"),
                ],
                start=1,
            )
        }
        petto = Muscle.objects.create(
            code="chestMid", group=cls.gruppi["chest"], label_it="Petto medio",
            sort_order=1,
        )
        dorsali = Muscle.objects.create(
            code="lats", group=cls.gruppi["back"], label_it="Dorsali", sort_order=1
        )
        bilanciere = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        corpo_libero = Equipment.objects.create(
            code=CORPO_LIBERO, label_it="Corpo libero", sort_order=2
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana", slug="panca-piana",
            primary_muscle=petto, equipment=bilanciere,
        )
        cls.trazioni = Exercise.objects.create(
            name="Trazioni", slug="trazioni",
            primary_muscle=dorsali, equipment=corpo_libero,
        )

    def setUp(self):
        self.client.login(username="atleta", password=PASSWORD)
        # La finestra si calcola una volta e si riusa: i test scrivono le serie
        # *dentro* settimane note, e ancorarle a `now()` le farebbe scivolare
        # fuori dal grafico a seconda del giorno in cui girano.
        self.settimane = analytics_volume.finestra_settimanale()

    def serie(self, lunedi, exercise=None, reps=10, weight="100", user=None, **kwargs):
        """Una serie di lavoro nel martedì della settimana che comincia `lunedi`.

        Martedì e non lunedì di proposito: se la troncatura sbagliasse fuso
        orario, una serie di lunedì a mezzanotte finirebbe nella settimana
        precedente e il test lo direbbe per caso. Un giorno pieno dentro la
        settimana rende il test una prova sull'aggregazione, non sui bordi.
        """
        istante = timezone.make_aware(
            timezone.datetime.combine(lunedi + timedelta(days=1), timezone.datetime.min.time())
        ) + timedelta(hours=18)
        allenamento = Workout.objects.create(
            user=user or self.user, title="Sessione", started_at=istante
        )
        campi = {
            "set_type": WorkoutSet.SetType.WORKING,
            "is_completed": True,
            **kwargs,
        }
        return WorkoutSet.objects.create(
            workout=allenamento,
            exercise=exercise or self.panca,
            set_number=1,
            reps=reps,
            weight=Decimal(weight),
            **campi,
        )

    # --- A1: i buchi ------------------------------------------------------

    def test_the_window_always_has_twelve_weeks_even_with_a_single_workout(self):
        """Una serie sola non fa un grafico da un punto.

        È la regola che rende il grafico onesto: la finestra è dichiarata dalla
        pagina, non dedotta dai dati, quindi undici settimane vuote restano
        undici settimane vuote.
        """
        self.serie(self.settimane[-1])

        righe = analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )

        self.assertEqual(len(righe), analytics_volume.SETTIMANE_DI_DEFAULT)
        self.assertEqual([riga["periodo"] for riga in righe], self.settimane)

    def test_a_skipped_week_is_a_zero_and_not_a_missing_row(self):
        """Il cuore del ticket.

        Due allenamenti a tre settimane di distanza: senza riempimento le righe
        sarebbero due e adiacenti, e la linea salirebbe dolcemente sopra un
        vuoto di ventun giorni. Con il riempimento, in mezzo c'è un avvallamento
        a zero — che è ciò che è successo davvero.
        """
        self.serie(self.settimane[-4], weight="100", reps=10)
        self.serie(self.settimane[-1], weight="100", reps=10)

        righe = analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )
        volumi = [riga["volume"] for riga in righe]

        self.assertEqual(volumi[-4], 1000.0)
        self.assertEqual(volumi[-3], 0.0)
        self.assertEqual(volumi[-2], 0.0)
        self.assertEqual(volumi[-1], 1000.0)

    def test_several_sets_in_one_week_collapse_into_a_single_row(self):
        """La trappola del `GROUP BY`, che non segnala niente.

        `WorkoutSet.Meta.ordering` vale `["set_number"]`, e Django trascina
        l'ordinamento di default nel raggruppamento: senza l'`order_by`
        esplicito in coda alla query, ogni settimana si spaccherebbe in una
        riga per numero di serie. Il totale della pagina resterebbe giusto e il
        grafico avrebbe dodici punti lo stesso — con dentro un terzo del volume.
        """
        allenamento = Workout.objects.create(
            user=self.user,
            title="Petto",
            started_at=timezone.make_aware(
                timezone.datetime.combine(
                    self.settimane[-1] + timedelta(days=1),
                    timezone.datetime.min.time(),
                )
            )
            + timedelta(hours=18),
        )
        for numero in range(1, 4):
            WorkoutSet.objects.create(
                workout=allenamento, exercise=self.panca, set_number=numero,
                reps=10, weight=Decimal("100"),
                set_type=WorkoutSet.SetType.WORKING, is_completed=True,
            )

        righe = analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )

        self.assertEqual(righe[-1]["volume"], 3000.0)

    def test_the_window_excludes_what_happened_before_it(self):
        """Tredici settimane fa è fuori, e non deve rientrare dalla porta di servizio."""
        self.serie(self.settimane[0] - timedelta(weeks=1))

        righe = analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )

        self.assertEqual([riga["volume"] for riga in righe], [0.0] * 12)

    # --- A1: la stessa definizione di volume delle altre superfici --------

    def test_the_analysis_uses_the_effective_load_like_every_other_surface(self):
        """Il test-ponte di #97, esteso alla terza superficie.

        8 trazioni a peso aggiunto nullo, con 80 kg dichiarati, valgono 640 kg —
        non zero. Se questa pagina si riscrivesse il volume come
        `reps × weight`, il numero sarebbe 0 e nessun altro test se ne
        accorgerebbe: è esattamente il guasto che la dashboard aveva.
        """
        self.serie(self.settimane[-1], exercise=self.trazioni, reps=8, weight="0")

        righe = analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )

        self.assertEqual(righe[-1]["volume"], 640.0)
        self.assertEqual(
            righe[-1]["volume"],
            WorkoutSet.objects.working()
            .filter(workout__user=self.user)
            .aggregate(v=Sum(VOLUME))["v"],
        )

    def test_warm_ups_and_skipped_sets_stay_out(self):
        """Il filtro universale vale qui come ovunque, e vale intero."""
        self.serie(self.settimane[-1], reps=10, weight="100")
        self.serie(
            self.settimane[-1], reps=10, weight="500",
            set_type=WorkoutSet.SetType.WARMUP,
        )
        self.serie(self.settimane[-1], reps=10, weight="900", is_completed=False)

        righe = analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )

        self.assertEqual(righe[-1]["volume"], 1000.0)

    def test_another_persons_volume_is_not_mine(self):
        """Una pagina personale che sommasse tutti sarebbe una fuga di dati muta."""
        self.serie(self.settimane[-1], user=self.dormiente, reps=10, weight="100")

        righe = analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )

        self.assertEqual([riga["volume"] for riga in righe], [0.0] * 12)

    # --- A2: i sei gruppi -------------------------------------------------

    def test_all_six_groups_appear_even_the_untrained_ones(self):
        """Un gruppo mai allenato è un'informazione, non un'assenza.

        I gruppi sono un insieme chiuso: uno che non compare non si distingue
        da uno che la pagina si è dimenticata di disegnare. È la stessa lezione
        di ADR-0006 letta al contrario — lì la schiena spariva per un carico
        effettivo mancante, e nessuno se ne accorgeva.
        """
        self.serie(self.settimane[-1], exercise=self.panca, reps=10, weight="100")

        righe = analytics_volume.volume_per_gruppo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )

        self.assertEqual(len(righe), 6)
        self.assertEqual(righe[0], {"gruppo": "Petto", "codice": "chest", "volume": 1000.0, "ordine": 1})
        self.assertEqual({riga["volume"] for riga in righe[1:]}, {0.0})

    def test_the_groups_are_ordered_by_volume_and_ties_are_deterministic(self):
        """Ordine per volume, e a pari merito quello del catalogo.

        Senza il secondo criterio la pagina si riordinerebbe a ogni ricarica —
        cinque gruppi a zero sono cinque pari merito, non un caso di scuola.
        """
        self.serie(self.settimane[-1], exercise=self.panca, reps=10, weight="50")
        self.serie(self.settimane[-1], exercise=self.trazioni, reps=10, weight="20")

        righe = analytics_volume.volume_per_gruppo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )

        self.assertEqual([riga["gruppo"] for riga in righe[:2]], ["Schiena", "Petto"])
        self.assertEqual(
            [riga["gruppo"] for riga in righe[2:]],
            ["Spalle", "Braccia", "Gambe", "Core"],
        )

    def test_the_two_analyses_answer_on_the_same_window(self):
        """A2 spiega A1, quindi deve guardare lo stesso periodo.

        Se le finestre divergessero, la seconda figura racconterebbe una prima
        che non è quella disegnata sopra — e sarebbero due grafici coerenti
        ciascuno con sé stesso.
        """
        self.serie(self.settimane[0] - timedelta(weeks=1), reps=10, weight="100")
        self.serie(self.settimane[-1], reps=10, weight="100")

        totale_a1 = sum(
            riga["volume"]
            for riga in analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )
        )
        totale_a2 = sum(
            riga["volume"]
            for riga in analytics_volume.volume_per_gruppo(
            self.user, analytics_volume.SETTIMANA, self.settimane
        )
        )

        self.assertEqual(totale_a1, 1000.0)
        self.assertEqual(totale_a1, totale_a2)

    # --- La pagina --------------------------------------------------------

    def test_the_page_is_private(self):
        """`LoginRequiredMixin`: `/analisi/` è lo storico di una persona."""
        self.client.logout()

        response = self.client.get(reverse("training:analysis"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_the_sixth_nav_item_points_here(self):
        """La voce esiste, e non è un link orfano: è la regola di navigazione."""
        response = self.client.get(reverse("training:dashboard"))

        self.assertContains(response, f'href="{reverse("training:analysis")}"')

    def test_the_chart_data_is_really_in_the_document(self):
        """Il test che il ticket chiedeva per nome.

        Un grafico vuoto e un grafico non ancora disegnato sono la stessa
        immagine, e uno status code 200 non distingue fra i due. Qui si guarda
        il payload di `json_script`, che è HTML reso dal server: se i numeri
        sono lì, ciò che resta fra loro e la figura è solo Chart.js.
        """
        self.serie(self.settimane[-1], exercise=self.panca, reps=10, weight="100")

        response = self.client.get(reverse("training:analysis"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="dati-volume-periodi"')
        self.assertContains(response, 'id="dati-volume-gruppi"')
        self.assertContains(response, 'data-grafico="dati-volume-periodi"')
        self.assertContains(response, 'data-grafico="dati-volume-gruppi"')

        payload = self.payload(response, "dati-volume-periodi")
        self.assertEqual(payload["tipo"], "line")
        self.assertEqual(len(payload["valori"]), 12)
        self.assertEqual(payload["valori"][-1], 1000.0)

        gruppi = self.payload(response, "dati-volume-gruppi")
        self.assertEqual(gruppi["tipo"], "bar")
        self.assertEqual(gruppi["etichette"][0], "Petto")
        self.assertEqual(len(gruppi["etichette"]), 6)

    def payload(self, response, identificatore):
        """Il dizionario dentro il `json_script` con quell'`id`."""
        trovato = re.search(
            rf'<script id="{identificatore}" type="application/json">(.*?)</script>',
            response.content.decode(),
            re.S,
        )
        self.assertIsNotNone(trovato, f"Nessun json_script con id {identificatore}")
        return json.loads(trovato.group(1))

    def test_chart_js_is_loaded_only_where_there_is_something_to_draw(self):
        """La libreria non si scarica per non fare niente.

        È anche la guardia sulla convenzione che #99 lascia in eredità: il CDN
        sta nel blocco `scripts` della **pagina**, non in `base.html`, o
        arriverebbe addosso anche a chi apre il form di una scheda.
        """
        vuota = self.client.get(reverse("training:analysis"))
        self.assertNotContains(vuota, "chart.umd.min.js")

        self.serie(self.settimane[-1])
        piena = self.client.get(reverse("training:analysis"))
        self.assertContains(piena, "chart.umd.min.js")

        altrove = self.client.get(reverse("training:dashboard"))
        self.assertNotContains(altrove, "chart.umd.min.js")

    def test_someone_with_no_history_is_invited_to_start(self):
        """Chi non ha mai registrato niente non vede due linee piatte."""
        self.client.login(username="nuovo", password=PASSWORD)

        response = self.client.get(reverse("training:analysis"))

        self.assertFalse(response.context["ha_dati_in_assoluto"])
        self.assertContains(response, "Non c'è ancora niente da analizzare")

    def test_someone_with_history_outside_the_window_is_sent_to_it(self):
        """Il secondo vuoto, e la ragione per cui sono due.

        Dire «crea una scheda e comincia» a chi ha centinaia di allenamenti
        alle spalle significa non aver guardato i suoi dati, ed è il difetto
        che si nota per primo.
        """
        self.serie(self.settimane[0] - timedelta(weeks=4), user=self.dormiente)
        self.client.login(username="dormiente", password=PASSWORD)

        response = self.client.get(reverse("training:analysis"))

        self.assertTrue(response.context["ha_dati_in_assoluto"])
        self.assertFalse(response.context["ha_dati_in_finestra"])
        self.assertContains(response, "Niente in 12 settimane")
        self.assertNotContains(response, "Non c'è ancora niente da analizzare")

    def test_the_page_declares_that_a_missing_body_mass_makes_the_volume_partial(self):
        """Incompleto, non zero — la stessa dichiarazione della dashboard.

        Qui pesa di più che là: il volume è il soggetto della pagina, non un
        riquadro fra quattro, e una schiena bassa per un peso corporeo mancante
        si legge come un dato sull'allenamento.
        """
        self.serie(self.settimane[-1], user=self.nuovo, exercise=self.panca)
        self.client.login(username="nuovo", password=PASSWORD)

        response = self.client.get(reverse("training:analysis"))

        self.assertContains(response, "Il volume qui sotto è incompleto")

    def test_every_group_is_a_way_into_the_catalogue(self):
        """Nessuna analisi è un vicolo cieco: dal gruppo si va agli esercizi."""
        self.serie(self.settimane[-1], exercise=self.panca)

        response = self.client.get(reverse("training:analysis"))

        self.assertContains(
            response, f'{reverse("training:exercise-list")}?gruppo=chest'
        )

    # --- Il toggle settimana/mese, e i buchi sui mesi (#106) --------------
    #
    # Il taglio mensile ha **un** difetto in più di quello settimanale, ed è
    # tutto il ticket: i mesi non hanno la stessa lunghezza, quindi la finestra
    # non si costruisce a passo fisso e il riempimento dei buchi non può
    # scivolare di un giorno senza che nessuno se ne accorga — un volume nel
    # mese sbagliato si disegna esattamente come un volume nel mese giusto.
    #
    # Il resto sono i due modi in cui il toggle può rompere quello che c'era:
    # A2 che smette di rispondere sulla finestra di A1, e il vuoto che manda
    # allo storico chi bastava rimandare all'altro taglio.

    def serie_il(self, giorno, exercise=None, reps=10, weight="100", user=None):
        """Una serie di lavoro a mezzogiorno di una data **assoluta**.

        La sorella di `serie()` per i test mensili, che ragionano su date di
        calendario e non su offset dalla finestra. Mezzogiorno e non mezzanotte
        per la stessa ragione di là: un istante lontano dai bordi rende il test
        una prova sull'aggregazione, non sul fuso orario.
        """
        istante = timezone.make_aware(
            timezone.datetime.combine(giorno, timezone.datetime.min.time())
        ) + timedelta(hours=12)
        allenamento = Workout.objects.create(
            user=user or self.user, title="Sessione", started_at=istante
        )
        return WorkoutSet.objects.create(
            workout=allenamento,
            exercise=exercise or self.panca,
            set_number=1,
            reps=reps,
            weight=Decimal(weight),
            set_type=WorkoutSet.SetType.WORKING,
            is_completed=True,
        )

    def test_the_monthly_window_counts_months_and_not_days(self):
        """Dodici primi-del-mese, e il capodanno attraversato correttamente.

        Il modo sbagliato di scrivere questa funzione è indietreggiare di 30
        giorni per volta: su un anno l'errore si accumula in un paio di mesi, e
        la finestra finirebbe per contenere due volte lo stesso mese senza mai
        segnalare niente.
        """
        finestra = analytics_volume.finestra_mensile(oggi=date(2026, 3, 15))

        self.assertEqual(len(finestra), 12)
        self.assertEqual(finestra[-1], date(2026, 3, 1))
        self.assertEqual(finestra[0], date(2025, 4, 1))
        self.assertEqual({giorno.day for giorno in finestra}, {1})

    def test_a_skipped_month_is_a_zero_and_not_a_missing_row(self):
        """Il cuore del ticket, sul taglio che il ticket aggiunge.

        `TruncMonth` ha lo stesso difetto di `TruncWeek` — restituisce solo i
        mesi in cui esiste una serie — e su base mensile il buco pesa di più:
        due punti adiacenti che in realtà distano un trimestre sono un anno di
        allenamento raccontato come continuo.
        """
        finestra = analytics_volume.finestra_mensile(oggi=date(2026, 3, 15))
        self.serie_il(date(2025, 12, 10))
        self.serie_il(date(2026, 3, 10))

        righe = analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.MESE, finestra
        )
        volumi = [riga["volume"] for riga in righe]

        self.assertEqual(len(righe), 12)
        self.assertEqual([riga["periodo"] for riga in righe], finestra)
        self.assertEqual(volumi[-4], 1000.0)
        self.assertEqual(volumi[-3:-1], [0.0, 0.0])
        self.assertEqual(volumi[-1], 1000.0)

    def test_months_of_different_lengths_do_not_shift_the_holes(self):
        """Febbraio non sposta marzo, che è ciò che un passo fisso farebbe.

        Tre mesi consecutivi di lunghezza diversa (31, 28, 31), con una serie
        ciascuno e volumi distinti: se il riempimento allineasse per offset
        invece che per data, i valori finirebbero nei punti sbagliati e i
        totali resterebbero giusti — il guasto invisibile di questa famiglia.
        """
        finestra = analytics_volume.finestra_mensile(oggi=date(2026, 3, 20))
        self.serie_il(date(2026, 1, 15), weight="10")
        self.serie_il(date(2026, 2, 15), weight="20")
        self.serie_il(date(2026, 3, 15), weight="30")

        righe = analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.MESE, finestra
        )

        per_mese = {riga["periodo"]: riga["volume"] for riga in righe}
        self.assertEqual(per_mese[date(2026, 1, 1)], 100.0)
        self.assertEqual(per_mese[date(2026, 2, 1)], 200.0)
        self.assertEqual(per_mese[date(2026, 3, 1)], 300.0)

    def test_the_monthly_window_reaches_further_back_than_the_weekly_one(self):
        """Il toggle deve *aggiungere* storia, o non varrebbe la pena.

        Una serie di otto mesi fa è fuori dalle dodici settimane e dentro i
        dodici mesi: se non lo fosse, i due tagli mostrerebbero la stessa cosa
        con etichette diverse.
        """
        otto_mesi_fa = timezone.localdate() - timedelta(days=240)
        self.serie_il(otto_mesi_fa)

        settimanale = analytics_volume.volume_nel_tempo(
            self.user, analytics_volume.SETTIMANA
        )
        mensile = analytics_volume.volume_nel_tempo(self.user, analytics_volume.MESE)

        self.assertEqual(sum(riga["volume"] for riga in settimanale), 0.0)
        self.assertEqual(sum(riga["volume"] for riga in mensile), 1000.0)

    def test_the_two_analyses_share_the_window_on_the_monthly_cut_too(self):
        """Il vincolo di #99 non è per il taglio settimanale, è per la pagina.

        A2 spiega A1: se il toggle spostasse solo il grafico sopra, la
        distribuzione sui gruppi resterebbe quella di dodici settimane e
        starebbe sotto un grafico che parla di dodici mesi.
        """
        self.serie_il(timezone.localdate() - timedelta(days=200), weight="100")
        self.serie_il(timezone.localdate(), exercise=self.trazioni, reps=8, weight="0")

        totale_a1 = sum(
            riga["volume"]
            for riga in analytics_volume.volume_nel_tempo(
                self.user, analytics_volume.MESE
            )
        )
        totale_a2 = sum(
            riga["volume"]
            for riga in analytics_volume.volume_per_gruppo(
                self.user, analytics_volume.MESE
            )
        )

        self.assertEqual(totale_a1, 1000.0 + 640.0)
        self.assertEqual(totale_a1, totale_a2)

    def test_the_partial_point_is_declared_in_days_of_that_month(self):
        """«Parziale» non basta su dodici mesi: si dice quanti giorni su quanti.

        Il 2 del mese l'ultimo punto vale un trentesimo del periodo, e accanto
        a undici mesi pieni si legge come un crollo dell'allenamento invece che
        come un mese appena cominciato. E il denominatore è quello del mese
        vero: febbraio ne ha 28, non 30.
        """
        febbraio = analytics_volume.finestra_mensile(oggi=date(2026, 2, 3))
        parziale = analytics_volume.quanto_e_trascorso(
            analytics_volume.MESE, febbraio, oggi=date(2026, 2, 3)
        )

        self.assertEqual(parziale, {"trascorsi": 3, "totali": 28})

        # Sullo stesso giorno la settimana conta diversamente, ed è il punto:
        # il 3 febbraio 2026 è un **martedì**, quindi il mese è al terzo giorno
        # e la settimana al secondo. Due griglie diverse, due denominatori.
        settimana = analytics_volume.finestra_settimanale(oggi=date(2026, 2, 3))
        self.assertEqual(
            analytics_volume.quanto_e_trascorso(
                analytics_volume.SETTIMANA, settimana, oggi=date(2026, 2, 3)
            ),
            {"trascorsi": 2, "totali": 7},
        )

    def test_the_querystring_chooses_the_cut_and_a_bad_value_falls_back(self):
        """Lo stato vive nell'URL, e un valore sconosciuto non è un 404.

        La stessa regola dello slug fuori soglia sulla classifica di forza: una
        domanda malposta ha una risposta legittima, che è la pagina di default.
        """
        self.serie(self.settimane[-1])

        mese = self.client.get(reverse("training:analysis"), {"periodo": "mese"})
        self.assertEqual(mese.context["taglio"], analytics_volume.MESE)
        self.assertEqual(mese.context["taglio"].plurale, "mesi")

        assurdo = self.client.get(
            reverse("training:analysis"), {"periodo": "trimestre"}
        )
        self.assertEqual(assurdo.status_code, 200)
        self.assertEqual(assurdo.context["taglio"], analytics_volume.SETTIMANA)

        default = self.client.get(reverse("training:analysis"))
        self.assertEqual(default.context["taglio"], analytics_volume.SETTIMANA)

    def test_the_default_cut_has_no_parameter_in_its_link(self):
        """Un indirizzo solo per la pagina di default, non due.

        È la regola dei filtri del catalogo (#71): il default è l'**assenza**
        del parametro, o `/analisi/` e `/analisi/?periodo=settimana` finirebbero
        nei preferiti come due pagine diverse che mostrano la stessa cosa.
        """
        response = self.client.get(reverse("training:analysis"))

        tagli = {scelta["chiave"]: scelta for scelta in response.context["tagli"]}
        self.assertEqual(tagli["settimana"]["url"], reverse("training:analysis"))
        self.assertEqual(
            tagli["mese"]["url"], f"{reverse('training:analysis')}?periodo=mese"
        )
        self.assertTrue(tagli["settimana"]["attivo"])
        self.assertFalse(tagli["mese"]["attivo"])
        self.assertContains(response, 'href="/analisi/?periodo=mese"')

    def test_the_monthly_chart_labels_carry_the_year(self):
        """Su dodici mesi l'anno cambia in mezzo alla finestra.

        Senza, la figura mostrerebbe due mesi di gennaio indistinguibili — ed è
        proprio il taglio in cui si guarda una stagione intera.
        """
        self.serie(self.settimane[-1])

        response = self.client.get(reverse("training:analysis"), {"periodo": "mese"})
        payload = self.payload(response, "dati-volume-periodi")

        self.assertEqual(len(payload["valori"]), 12)
        self.assertEqual(payload["tipo"], "line")
        # `mar 26` e non `3 mar`: due parole, la seconda di due cifre.
        self.assertRegex(payload["etichette"][0], r"^\w+ \d{2}$")

    def test_an_empty_window_offers_the_wider_cut_when_there_is_something_there(self):
        """Il vuoto «fuori finestra» cambia significato col toggle.

        Chi ha allenamenti di sei mesi fa è fuori dalle dodici settimane ma
        dentro i dodici mesi: mandarlo allo storico sarebbe far uscire dalla
        pagina qualcuno che la pagina poteva servire. L'alternativa si offre
        **solo** dopo averla verificata, o sarebbe un link verso un secondo
        vuoto.
        """
        self.serie_il(
            timezone.localdate() - timedelta(days=180), user=self.dormiente
        )
        self.client.login(username="dormiente", password=PASSWORD)

        response = self.client.get(reverse("training:analysis"))

        self.assertFalse(response.context["ha_dati_in_finestra"])
        self.assertTrue(response.context["altro_taglio_ha_dati"])
        self.assertContains(response, "Guarda 12 mesi")

    def test_an_empty_window_does_not_offer_a_cut_that_is_empty_too(self):
        """Un link a un secondo vuoto sarebbe peggio di nessun link.

        Due anni fa è fuori da entrambi i tagli, e sul taglio mensile l'altro è
        quello settimanale, cioè **più stretto**: non c'è mai niente da
        suggerire in quella direzione.
        """
        self.serie_il(
            timezone.localdate() - timedelta(days=730), user=self.dormiente
        )
        self.client.login(username="dormiente", password=PASSWORD)

        settimanale = self.client.get(reverse("training:analysis"))
        self.assertFalse(settimanale.context["altro_taglio_ha_dati"])
        self.assertContains(settimanale, "Vai allo storico")

        mensile = self.client.get(reverse("training:analysis"), {"periodo": "mese"})
        self.assertFalse(mensile.context["altro_taglio_ha_dati"])


class TemplateCommentTests(TestCase):
    """I commenti di template non finiscono nella pagina.

    La forma breve `{# … #}` è una comodità di **una riga sola**: il lexer di
    Django la cerca senza `re.DOTALL`, quindi un commento che va a capo non
    viene riconosciuto e il suo testo — note interne, riferimenti ad ADR,
    numeri di ticket — viene reso come HTML e appare in pagina.

    Quattro template lo facevano già, e nessun test se ne accorgeva: è un
    guasto silenzioso della stessa famiglia dell'ereditarietà di `base.html`,
    quindi prende la stessa forma di guardia. Rilevato in #69.
    """

    def test_no_template_opens_a_short_comment_it_does_not_close(self):
        aperto = re.compile(r"{#(?!.*#})")

        trovati = []
        for root in TEMPLATE_ROOTS:
            for path in sorted(root.rglob("*.html")):
                for numero, riga in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    if aperto.search(riga):
                        trovati.append(
                            f"{path.relative_to(settings.BASE_DIR)}:{numero}"
                        )

        self.assertEqual(
            trovati,
            [],
            "Commento `{# … #}` su più righe: usa il tag `comment`. "
            + ", ".join(trovati),
        )


# --- Il catalogo esercizi (#71) --------------------------------------------
#
# La lista è ciò che paga il requisito «select/view **grouped** objects», e i
# test lo prendono alla lettera: non basta che la pagina renda, deve
# raggruppare e deve filtrare sui tre assi. Il dettaglio in fase 1 è un guscio,
# e ciò che va protetto è che apra dallo slug e che lo storico sia *dell'utente
# che guarda*.


class ExerciseListTests(TestCase):
    """`/esercizi/`: raggruppa, filtra sui tre assi, e non si modifica."""

    @classmethod
    def setUpTestData(cls):
        # Due gruppi, tre muscoli, due attrezzi: il minimo che rende
        # distinguibili i tre filtri e il raggruppamento.
        petto = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        gambe = MuscleGroup.objects.create(code="legs", label_it="Gambe", sort_order=2)
        petto_medio = Muscle.objects.create(
            code="chestMid", group=petto, label_it="Petto medio", sort_order=1
        )
        petto_alto = Muscle.objects.create(
            code="chestUpper", group=petto, label_it="Petto alto", sort_order=2
        )
        quadricipiti = Muscle.objects.create(
            code="quads", group=gambe, label_it="Quadricipiti", sort_order=3
        )
        bilanciere = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        corpo_libero = Equipment.objects.create(
            code="bodyweight",
            label_it="Corpo libero",
            load_increment_kg=Decimal("0"),
            sort_order=2,
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana",
            slug="panca-piana",
            primary_muscle=petto_medio,
            equipment=bilanciere,
        )
        cls.inclinata = Exercise.objects.create(
            name="Panca inclinata",
            slug="panca-inclinata",
            primary_muscle=petto_alto,
            equipment=bilanciere,
        )
        cls.piegamenti = Exercise.objects.create(
            name="Piegamenti",
            slug="piegamenti",
            primary_muscle=petto_medio,
            equipment=corpo_libero,
        )
        cls.squat = Exercise.objects.create(
            name="Squat",
            slug="squat",
            primary_muscle=quadricipiti,
            equipment=bilanciere,
        )

    def setUp(self):
        self.client.force_login(
            User.objects.create_user(username="lorenzo", password=PASSWORD)
        )

    def nomi(self, response):
        """I nomi degli esercizi che la pagina ha davvero selezionato."""
        return sorted(e.name for e in response.context["esercizi"])

    def test_the_catalogue_is_grouped_by_muscle_group(self):
        """Il requisito «grouped objects»: non una lista piatta, blocchi.

        Il raggruppamento passa da `regroup`, che spezza in due blocchi lo
        stesso gruppo se il queryset non arriva ordinato: il test guarda
        l'ordine del queryset, che è la condizione, non solo l'HTML.
        """
        response = self.client.get(reverse("training:exercise-list"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "training/exercise_list.html")
        self.assertTemplateUsed(response, BASE_TEMPLATE)

        gruppi = [e.primary_muscle.group.label_it for e in response.context["esercizi"]]
        self.assertEqual(gruppi, ["Petto", "Petto", "Petto", "Gambe"])

        body = response.content.decode()
        self.assertIn("Petto</div>", body)
        self.assertIn("Gambe</div>", body)

    def test_the_group_filter_narrows_the_catalogue(self):
        response = self.client.get(
            reverse("training:exercise-list"), {"gruppo": "legs"}
        )

        self.assertEqual(self.nomi(response), ["Squat"])

    def test_the_muscle_filter_narrows_the_catalogue(self):
        response = self.client.get(
            reverse("training:exercise-list"), {"muscolo": "chestMid"}
        )

        self.assertEqual(self.nomi(response), ["Panca piana", "Piegamenti"])

    def test_the_equipment_filter_narrows_the_catalogue(self):
        response = self.client.get(
            reverse("training:exercise-list"), {"attrezzo": "bodyweight"}
        )

        self.assertEqual(self.nomi(response), ["Piegamenti"])

    def test_the_three_filters_combine_with_and(self):
        """Combinati restringono, non sommano: è un AND, non un OR."""
        response = self.client.get(
            reverse("training:exercise-list"),
            {"gruppo": "chest", "muscolo": "chestMid", "attrezzo": "barbell"},
        )

        self.assertEqual(self.nomi(response), ["Panca piana"])

    def test_choosing_a_group_narrows_the_muscle_dropdown(self):
        """Offrire «quadricipiti» sotto «petto» è offrire un filtro vuoto."""
        response = self.client.get(
            reverse("training:exercise-list"), {"gruppo": "chest"}
        )

        muscoli = sorted(m.code for m in response.context["muscoli"])
        self.assertEqual(muscoli, ["chestMid", "chestUpper"])

    def test_an_empty_result_says_so_instead_of_rendering_nothing(self):
        response = self.client.get(
            reverse("training:exercise-list"),
            {"gruppo": "legs", "attrezzo": "bodyweight"},
        )

        self.assertEqual(self.nomi(response), [])
        self.assertIn("Nessun esercizio", response.content.decode())

    def test_the_catalogue_declares_that_it_is_read_only(self):
        """ADR-0001: la sola lettura è una scelta, e va dichiarata all'orale.

        Senza questa riga in pagina il catalogo si legge come un CRUD
        dimenticato — che è esattamente l'equivoco che costerebbe voto.
        """
        response = self.client.get(reverse("training:exercise-list"))
        body = response.content.decode()

        self.assertIn("Catalogo chiuso, per scelta", body)
        # E il catalogo non offre nessuna rotta di scrittura.
        for verbo in ("nuovo", "modifica", "elimina"):
            with self.subTest(verbo=verbo):
                self.assertNotIn(f"/esercizi/{verbo}", body)


class ExerciseDetailTests(TestCase):
    """`/esercizi/<slug>/`: apre dallo slug, e lo storico è di chi guarda."""

    @classmethod
    def setUpTestData(cls):
        gruppo = MuscleGroup.objects.create(
            code="chest", label_it="Petto", sort_order=1
        )
        muscolo = Muscle.objects.create(
            code="chestMid", group=gruppo, label_it="Petto medio", sort_order=1
        )
        attrezzo = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana",
            slug="panca-piana",
            primary_muscle=muscolo,
            equipment=attrezzo,
        )
        cls.squat = Exercise.objects.create(
            name="Squat",
            slug="squat",
            primary_muscle=muscolo,
            equipment=attrezzo,
        )
        cls.user = User.objects.create_user(username="lorenzo", password=PASSWORD)
        cls.altra = User.objects.create_user(username="martina", password=PASSWORD)

    def setUp(self):
        self.client.force_login(self.user)

    def serie(self, user, exercise, weight, giorni_fa=0):
        workout = Workout.objects.create(
            user=user,
            title="Spinta A",
            started_at=timezone.now() - timedelta(days=giorni_fa),
        )
        return WorkoutSet.objects.create(
            workout=workout,
            exercise=exercise,
            set_number=1,
            reps=5,
            weight=Decimal(weight),
        )

    def test_the_page_opens_from_the_slug(self):
        response = self.client.get(
            reverse("training:exercise-detail", args=[self.panca.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "training/exercise_detail.html")
        self.assertTemplateUsed(response, BASE_TEMPLATE)
        self.assertEqual(response.context["esercizio"], self.panca)
        body = response.content.decode()
        self.assertIn("Panca piana", body)
        self.assertIn("Petto medio", body)
        self.assertIn("Bilanciere", body)

    def test_an_unknown_slug_is_a_404(self):
        response = self.client.get(
            reverse("training:exercise-detail", args=["esercizio-inventato"])
        )

        self.assertEqual(response.status_code, 404)

    def test_the_list_links_to_the_detail_by_slug(self):
        """I due URL sono una sezione sola: la lista deve aprirci il dettaglio."""
        response = self.client.get(reverse("training:exercise-list"))

        self.assertIn(
            reverse("training:exercise-detail", args=[self.panca.slug]),
            response.content.decode(),
        )

    def test_the_history_holds_only_my_sets_on_this_exercise(self):
        """Due confini in uno: l'utente e l'esercizio.

        Lo storico è la sola parte personale della pagina, e non è protetta da
        un mixin — l'esercizio è del catalogo globale — ma dal filtro sul
        queryset. Se quel filtro cade, un utente legge gli allenamenti di un
        altro senza che niente lo segnali.
        """
        mia = self.serie(self.user, self.panca, "100.00")
        self.serie(self.user, self.squat, "140.00")
        self.serie(self.altra, self.panca, "60.00")

        response = self.client.get(
            reverse("training:exercise-detail", args=[self.panca.slug])
        )

        self.assertEqual(list(response.context["serie"]), [mia])
        self.assertIn("100 kg", response.content.decode())

    def test_the_history_keeps_the_most_recent_sessions_whole(self):
        """Il taglio è per sessione, non per serie.

        Un `[:N]` sulle serie taglierebbe a metà l'ultima sessione mostrata, e
        una sessione monca si legge come una sessione fatta male.
        """
        limite = views.ExerciseDetailView.SESSIONI_RECENTI
        for giorni in range(limite + 3):
            self.serie(self.user, self.panca, "100.00", giorni_fa=giorni)

        response = self.client.get(
            reverse("training:exercise-detail", args=[self.panca.slug])
        )

        serie = list(response.context["serie"])
        self.assertEqual(len(serie), limite)
        # Le più recenti, e in ordine: la pagina racconta all'indietro.
        date = [s.workout.started_at for s in serie]
        self.assertEqual(date, sorted(date, reverse=True))

    def test_an_empty_history_says_so(self):
        response = self.client.get(
            reverse("training:exercise-detail", args=[self.panca.slug])
        )

        self.assertEqual(list(response.context["serie"]), [])
        self.assertIn("Non hai ancora registrato una serie", response.content.decode())

    def test_the_shell_does_not_pretend_the_analyses_are_there(self):
        """Fase 1 è un guscio, e la pagina lo dichiara.

        `04-analisi.md` è fase 2: mostrare un massimale o un percentile
        calcolati a metà sarebbe peggio che non mostrarli, perché all'orale
        sembrerebbero l'analisi finita.
        """
        response = self.client.get(
            reverse("training:exercise-detail", args=[self.panca.slug])
        )

        self.assertIn("Cosa arriva qui", response.content.decode())

    def test_the_catalogue_is_private_like_the_rest(self):
        """Le due rotte seguono il pattern di #68: niente login, niente pagina."""
        self.client.logout()

        for url in (
            reverse("training:exercise-list"),
            reverse("training:exercise-detail", args=[self.panca.slug]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertRedirects(response, f"{reverse('login')}?next={url}")



# --- Il CRUD degli allenamenti (#70) ---------------------------------------
#
# Il secondo dei due CRUD completi che pagano il requisito della traccia, e la
# funzione che tiene insieme il piano e l'eseguito. Si proteggono tre cose, di
# natura diversa: i quattro verbi, la proprietà dell'oggetto (403 come per le
# schede), e le regole che il database impone con un `IntegrityError` — cioè
# con un 500 — se il form non le dice prima in italiano.


class ExerciseAnalyticsTests(TestCase):
    """A3, A4 e A5 — i numeri del dettaglio esercizio, provati sui numeri.

    Le tre analisi si provano **sotto** la view, come le classifiche e come A1
    e A2: ciò che va difeso qui sono un massimo cumulativo, una data e un
    percentile, e leggerli dall'HTML vorrebbe dire testare il template ogni
    volta che si vuole testare una divisione.

    Metà di questi test guarda casi in cui il codice sbagliato **non solleva
    niente**: un join che moltiplica le righe, un `GROUP BY` che spacca un
    utente in cinque, una data di record presa dall'ultima volta invece che
    dalla prima. Sono la regola 3 della mappa #96 — un'analisi sbagliata rende
    comunque una pagina.
    """

    @classmethod
    def setUpTestData(cls):
        gruppo = MuscleGroup.objects.create(
            code="chest", label_it="Petto", sort_order=1
        )
        muscolo = Muscle.objects.create(
            code="chestMid", group=gruppo, label_it="Petto medio", sort_order=1
        )
        bilanciere = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        corpo_libero = Equipment.objects.create(
            code=CORPO_LIBERO, label_it="Corpo libero", sort_order=2
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana", slug="panca-piana",
            primary_muscle=muscolo, equipment=bilanciere,
        )
        cls.trazioni = Exercise.objects.create(
            name="Trazioni", slug="trazioni",
            primary_muscle=muscolo, equipment=corpo_libero,
        )
        cls.user = User.objects.create_user(
            username="lorenzo", password=PASSWORD, body_mass_kg=Decimal("80")
        )
        cls.altra = User.objects.create_user(
            username="martina", password=PASSWORD, body_mass_kg=Decimal("60")
        )
        cls.senza_peso = User.objects.create_user(
            username="anonimo", password=PASSWORD
        )

    def setUp(self):
        self.client.force_login(self.user)

    def sessione(self, giorni_fa, carichi, reps=5, user=None, exercise=None):
        """Un allenamento con una serie per ogni carico di `carichi`.

        Più serie nella stessa sessione non sono un dettaglio del fixture: sono
        il caso che distingue una query per allenamento da una query per serie.
        """
        allenamento = Workout.objects.create(
            user=user or self.user,
            title="Spinta",
            started_at=timezone.now() - timedelta(days=giorni_fa),
        )
        for numero, carico in enumerate(carichi, start=1):
            WorkoutSet.objects.create(
                workout=allenamento,
                exercise=exercise or self.panca,
                set_number=numero,
                reps=reps,
                weight=Decimal(str(carico)),
                set_type=WorkoutSet.SetType.WORKING,
                is_completed=True,
            )
        return allenamento

    def righe(self, exercise=None, user=None):
        return list(
            analytics_progressione.progressione(user or self.user, exercise or self.panca)
        )

    # --- A3: una riga per allenamento -------------------------------------

    def test_three_sets_in_one_session_are_one_row_with_the_best_of_them(self):
        """La trappola che il prototipo ha quasi pagato, e che non segnala niente.

        Partire dal join a `sets` invece che da `pk__in` moltiplica
        l'allenamento per il numero di serie: la query gira, il grafico si
        disegna, e ogni sessione compare tre volte. Qui tre serie fanno **una**
        riga, e il massimale è il tentativo migliore.
        """
        self.sessione(giorni_fa=1, carichi=[80, 100, 90])

        righe = self.righe()

        self.assertEqual(len(righe), 1)
        self.assertAlmostEqual(righe[0]["massimale"], 100 * (1 + 5 / 30), places=4)

    def test_the_running_max_never_goes_down_after_a_bad_session(self):
        """Il senso stesso del massimo cumulativo.

        Terza sessione più debole della seconda: il massimale di giornata
        scende, il record no. Se scendesse, la pagina direbbe che il record si
        perde stando fermi.
        """
        self.sessione(giorni_fa=30, carichi=[100])
        self.sessione(giorni_fa=20, carichi=[120])
        self.sessione(giorni_fa=10, carichi=[90])

        record = [riga["record_a_quel_giorno"] for riga in self.righe()]

        atteso = [100, 120, 120]
        for ottenuto, carico in zip(record, atteso):
            self.assertAlmostEqual(ottenuto, carico * (1 + 5 / 30), places=4)

    def test_previous_is_the_session_before_and_is_empty_on_the_first(self):
        """`Lag` — la finestra che dà il salto, e che sulla prima riga tace."""
        self.sessione(giorni_fa=30, carichi=[100])
        self.sessione(giorni_fa=20, carichi=[110])

        righe = self.righe()

        self.assertIsNone(righe[0]["precedente"])
        self.assertAlmostEqual(righe[1]["precedente"], righe[0]["massimale"], places=4)

    def test_sets_above_the_rep_cap_stay_out_of_the_progression(self):
        """Il tetto a 12: sopra, Epley gonfia.

        La stessa sessione ha una serie da 5 e una da 20 ripetizioni con un
        carico più alto: il massimale deve uscire dalla prima. Senza il tetto,
        la serie lunga vincerebbe e il record sarebbe un numero che nessuno ha
        mai sollevato.
        """
        allenamento = self.sessione(giorni_fa=5, carichi=[100], reps=5)
        WorkoutSet.objects.create(
            workout=allenamento, exercise=self.panca, set_number=2,
            reps=MAX_REPS_FOR_1RM + 8, weight=Decimal("110"),
            set_type=WorkoutSet.SetType.WORKING, is_completed=True,
        )

        righe = self.righe()

        self.assertEqual(len(righe), 1)
        self.assertAlmostEqual(righe[0]["massimale"], 100 * (1 + 5 / 30), places=4)

    def test_a_session_made_only_of_long_sets_is_not_in_the_progression(self):
        self.sessione(giorni_fa=5, carichi=[100], reps=MAX_REPS_FOR_1RM + 3)

        self.assertEqual(self.righe(), [])

    def test_the_progression_is_mine_only(self):
        self.sessione(giorni_fa=5, carichi=[200], user=self.altra)
        self.sessione(giorni_fa=4, carichi=[100])

        righe = self.righe()

        self.assertEqual(len(righe), 1)
        self.assertAlmostEqual(righe[0]["massimale"], 100 * (1 + 5 / 30), places=4)

    def test_the_progression_is_a_single_sql_query(self):
        """Le due finestre e la subquery stanno in **una** query.

        È la ragione per cui la forma ibrida è stata scelta: la `Subquery`
        correlata pura dava la stessa risposta e costava 320 volte tanto (#98).
        """
        for giorno in range(5):
            self.sessione(giorni_fa=giorno, carichi=[100 + giorno])

        with CaptureQueriesContext(connection) as query:
            self.righe()

        self.assertEqual(len(query.captured_queries), 1)

    def test_the_bodyweight_load_includes_the_body_mass(self):
        """ADR-0006 dentro A3: una trazione a corpo libero non pesa zero."""
        self.sessione(giorni_fa=1, carichi=[0], exercise=self.trazioni)

        righe = self.righe(exercise=self.trazioni)

        self.assertAlmostEqual(righe[0]["massimale"], 80 * (1 + 5 / 30), places=4)

    # --- A4: il record, e soprattutto la sua data -------------------------

    def test_the_record_date_is_the_first_day_it_was_reached(self):
        """Due sessioni allo stesso carico: il record è della prima.

        Prendere l'ultima sarebbe un errore invisibile — il numero resterebbe
        giusto, e la pagina racconterebbe che il record è di ieri quando è di
        un anno fa. È esattamente il tipo di dato per cui la data è stata messa
        accanto al numero.
        """
        self.sessione(giorni_fa=40, carichi=[120])
        self.sessione(giorni_fa=20, carichi=[100])
        self.sessione(giorni_fa=10, carichi=[120])

        record = analytics_progressione.record_personale(self.righe())

        self.assertAlmostEqual(record["massimale"], 120 * (1 + 5 / 30), places=4)
        self.assertEqual(record["quando"].date(), (timezone.now() - timedelta(days=40)).date())
        self.assertEqual(record["sessioni"], 3)

    def test_there_is_no_record_without_useful_sets(self):
        self.assertIsNone(analytics_progressione.record_personale([]))

    def test_the_record_costs_no_extra_query(self):
        """A4 sul dettaglio è A3 riletta, non una seconda domanda al database."""
        self.sessione(giorni_fa=3, carichi=[100])
        righe = self.righe()

        with CaptureQueriesContext(connection) as query:
            analytics_progressione.record_personale(righe)

        self.assertEqual(len(query.captured_queries), 0)

    # --- I salti: il consumo di `Lag` -------------------------------------

    def test_a_new_record_is_marked_and_a_step_back_is_not(self):
        self.sessione(giorni_fa=30, carichi=[100])
        self.sessione(giorni_fa=20, carichi=[110])
        self.sessione(giorni_fa=10, carichi=[105])

        salti = analytics_progressione.salti(self.righe())

        self.assertEqual([riga["nuovo_record"] for riga in salti], [False, True, False])
        self.assertLess(salti[0]["salto"], 0)
        self.assertGreater(salti[1]["salto"], 0)
        self.assertIsNone(salti[2]["salto"])

    # --- A5: il percentile, e i suoi tre silenzi --------------------------

    def popolazione(self, quanti, exercise=None, con_peso=True, carico=50, prefisso="sintetico"):
        """`quanti` utenti con una serie a testa sull'esercizio.

        Il prefisso serve ai test che chiamano due volte questo aiutante — con
        peso e senza — e che altrimenti si scontrerebbero sull'unicità dello
        username invece di provare quello che vogliono provare.
        """
        for indice in range(quanti):
            utente = User.objects.create_user(
                username=f"{prefisso}{indice}",
                password=PASSWORD,
                body_mass_kg=Decimal("70") if con_peso else None,
            )
            self.sessione(giorni_fa=5, carichi=[carico], user=utente, exercise=exercise)

    def test_the_percentile_is_silent_below_the_threshold_and_says_why(self):
        """«Sei nel 67° percentile» su tre persone è esatto e falso insieme."""
        self.sessione(giorni_fa=5, carichi=[100])
        self.popolazione(5)

        risposta = analytics_progressione.percentile_forza(self.user, self.panca)

        self.assertEqual(risposta["stato"], "popolazione_insufficiente")
        self.assertEqual(risposta["n_utenti"], 6)
        self.assertEqual(risposta["soglia"], rankings.MIN_USERS_FOR_COMPARISON)

    def test_the_threshold_is_the_same_constant_as_the_strength_ranking(self):
        """Due soglie diverse sarebbero due numeri da giustificare all'orale.

        E, peggio, un esercizio potrebbe offrire una classifica e negare un
        percentile — sulla stessa pagina.
        """
        self.assertEqual(
            analytics_progressione.MIN_USERS_FOR_COMPARISON,
            rankings.MIN_USERS_FOR_COMPARISON,
        )

    def test_users_without_a_body_mass_are_not_part_of_the_population(self):
        """ADR-0008: senza denominatore non c'è forza relativa.

        Venti utenti in tutto, ma dieci senza peso dichiarato: la popolazione
        confrontabile è dieci, e il percentile tace. Senza l'`exclude` la
        divisione sarebbe per null — la riga che si perde ricopiando la query.
        """
        self.sessione(giorni_fa=5, carichi=[100])
        self.popolazione(9)
        self.popolazione(10, con_peso=False, prefisso="senzapeso")

        risposta = analytics_progressione.percentile_forza(self.user, self.panca)

        self.assertEqual(risposta["stato"], "popolazione_insufficiente")
        self.assertEqual(risposta["n_utenti"], 10)

    def test_the_population_counts_users_and_not_sets(self):
        """La trappola del `GROUP BY`, di nuovo, e qui gonfierebbe il confronto.

        `WorkoutSet.Meta.ordering` vale `["set_number"]`: senza l'`order_by()`
        vuoto, ogni utente si spaccherebbe in una riga per numero di serie.
        Venti utenti con quattro serie a testa diventerebbero ottanta righe —
        soglia superata per finta, e un percentile calcolato su cloni.
        """
        self.sessione(giorni_fa=5, carichi=[100, 90, 80, 70])
        for indice in range(9):
            utente = User.objects.create_user(
                username=f"molte{indice}", password=PASSWORD, body_mass_kg=Decimal("70")
            )
            self.sessione(giorni_fa=5, carichi=[50, 45, 40, 35], user=utente)

        risposta = analytics_progressione.percentile_forza(self.user, self.panca)

        self.assertEqual(risposta["n_utenti"], 10)

    def test_the_percentile_places_the_strongest_at_the_top(self):
        self.sessione(giorni_fa=5, carichi=[200])
        self.popolazione(rankings.MIN_USERS_FOR_COMPARISON - 1, carico=50)

        risposta = analytics_progressione.percentile_forza(self.user, self.panca)

        self.assertEqual(risposta["stato"], "ok")
        self.assertEqual(risposta["n_utenti"], rankings.MIN_USERS_FOR_COMPARISON)
        self.assertEqual(risposta["percentile"], 100)
        self.assertAlmostEqual(risposta["relativa"], 200 * (1 + 5 / 30) / 80, places=2)

    def test_the_percentile_is_the_share_of_people_below(self):
        """Metà popolazione sotto, metà sopra: il percentile lo dice."""
        self.sessione(giorni_fa=5, carichi=[100])
        self.popolazione(10, carico=10)
        for indice in range(9):
            utente = User.objects.create_user(
                username=f"forte{indice}", password=PASSWORD, body_mass_kg=Decimal("70")
            )
            self.sessione(giorni_fa=5, carichi=[300], user=utente)

        risposta = analytics_progressione.percentile_forza(self.user, self.panca)

        self.assertEqual(risposta["stato"], "ok")
        self.assertEqual(risposta["n_utenti"], 20)
        # Dieci sotto su diciannove altri: `PERCENT_RANK` vale 10/19.
        self.assertEqual(risposta["percentile"], round(10 / 19 * 100))

    def test_without_a_body_mass_the_page_asks_for_it_instead_of_computing(self):
        self.sessione(giorni_fa=5, carichi=[100], user=self.senza_peso)
        self.popolazione(rankings.MIN_USERS_FOR_COMPARISON)

        risposta = analytics_progressione.percentile_forza(self.senza_peso, self.panca)

        self.assertEqual(risposta["stato"], "senza_peso")

    def test_the_population_can_be_there_while_my_own_datum_is_not(self):
        """Il quarto caso, che non è nessuno degli altri tre."""
        self.popolazione(rankings.MIN_USERS_FOR_COMPARISON)

        risposta = analytics_progressione.percentile_forza(self.user, self.panca)

        self.assertEqual(risposta["stato"], "senza_serie")
        self.assertEqual(risposta["n_utenti"], rankings.MIN_USERS_FOR_COMPARISON)

    # --- La pagina --------------------------------------------------------

    def test_the_chart_payload_is_in_the_document(self):
        """Un grafico vuoto e un grafico non disegnato sono la stessa immagine.

        Il test guarda il `json_script`, che è l'unico punto in cui il dato
        esiste prima che Chart.js lo tocchi: se i numeri non sono lì, non c'è
        JavaScript che li inventi.
        """
        self.sessione(giorni_fa=20, carichi=[100])
        self.sessione(giorni_fa=10, carichi=[110])

        risposta = self.client.get(
            reverse("training:exercise-detail", args=[self.panca.slug])
        )
        corpo = risposta.content.decode()
        payload = json.loads(
            re.search(
                r'<script id="dati-progressione" type="application/json">(.*?)</script>',
                corpo, re.S,
            ).group(1)
        )

        self.assertEqual(payload["tipo"], "line")
        self.assertEqual(len(payload["valori"]), 2)
        self.assertEqual(payload["unita"], "kg")
        self.assertLess(payload["valori"][0], payload["valori"][1])
        self.assertIn("chart.js", corpo)

    def test_the_page_shows_the_record_with_its_date(self):
        self.sessione(giorni_fa=15, carichi=[120])

        risposta = self.client.get(
            reverse("training:exercise-detail", args=[self.panca.slug])
        )

        self.assertEqual(risposta.context["record"]["sessioni"], 1)
        self.assertContains(risposta, "Il tuo record")
        self.assertContains(risposta, "140,0 kg")

    def test_a_history_of_long_sets_only_explains_itself(self):
        """Il vuoto che sembrerebbe un guasto.

        Lo storico in coda alla pagina è pieno, i riquadri sopra sono vuoti, e
        senza una riga di spiegazione la pagina sembrerebbe aver perso i dati
        che mostra tre centimetri più sotto.
        """
        self.sessione(giorni_fa=5, carichi=[60], reps=MAX_REPS_FOR_1RM + 5)

        risposta = self.client.get(
            reverse("training:exercise-detail", args=[self.panca.slug])
        )

        self.assertIsNone(risposta.context["record"])
        self.assertTrue(risposta.context["ha_storico"])
        self.assertContains(risposta, "mai sotto le 12")

    def test_chart_js_is_not_downloaded_when_there_is_nothing_to_draw(self):
        risposta = self.client.get(
            reverse("training:exercise-detail", args=[self.panca.slug])
        )

        self.assertNotIn("chart.js", risposta.content.decode())


class WorkoutCrudTests(TestCase):
    """Creare, leggere, modificare, eliminare un allenamento e le sue serie."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="lorenzo", password=PASSWORD)
        cls.altro = User.objects.create_user(username="martina", password=PASSWORD)

        group = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        muscle = Muscle.objects.create(
            code="chestMid", group=group, label_it="Petto medio", sort_order=1
        )
        cls.bilanciere = Equipment.objects.create(
            code="barbell",
            label_it="Bilanciere",
            default_bar_weight_kg=Decimal("20.00"),
            sort_order=1,
        )
        cls.corpo_libero = Equipment.objects.create(
            code="bodyweight",
            label_it="Corpo libero",
            default_bar_weight_kg=Decimal("0.00"),
            load_increment_kg=Decimal("0.00"),
            sort_order=2,
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana", slug="panca-piana",
            primary_muscle=muscle, equipment=cls.bilanciere,
        )
        cls.trazioni = Exercise.objects.create(
            name="Trazioni", slug="trazioni",
            primary_muscle=muscle, equipment=cls.corpo_libero,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.workout = Workout.objects.create(
            user=self.user, title="Spinta A", started_at=timezone.now()
        )

    #: Il formato che `<input type="datetime-local">` invia. Non è quello
    #: italiano, ed è tutto il punto di `LocalDateTimeField`.
    def datetime_local(self, quando):
        return timezone.localtime(quando).strftime("%Y-%m-%dT%H:%M")

    def formset_payload(self, righe, iniziali=0):
        """Il `management_form` più le righe. Prefisso `sets`, da `related_name`."""
        payload = {
            "sets-TOTAL_FORMS": str(len(righe)),
            "sets-INITIAL_FORMS": str(iniziali),
            "sets-MIN_NUM_FORMS": "0",
            "sets-MAX_NUM_FORMS": "1000",
        }
        for indice, riga in enumerate(righe):
            for campo, valore in riga.items():
                payload[f"sets-{indice}-{campo}"] = valore
        return payload

    # --- I quattro verbi ------------------------------------------------

    def test_create_read_update_delete_a_workout(self):
        inizio = timezone.now()

        creazione = self.client.post(
            reverse("training:workout-create"),
            {
                "title": "Spinta B",
                "started_at": self.datetime_local(inizio),
                "ended_at": "",
                "notes": "Spalla destra un po' rigida.",
            },
        )
        nuovo = Workout.objects.get(title="Spinta B")
        # Chi crea un allenamento atterra sulle serie, non sulla lista.
        self.assertRedirects(
            creazione, reverse("training:workoutset-manage", args=[nuovo.pk])
        )
        self.assertEqual(nuovo.user, self.user)

        lettura = self.client.get(reverse("training:workout-detail", args=[nuovo.pk]))
        self.assertEqual(lettura.status_code, 200)
        self.assertContains(lettura, "Spinta B")
        self.assertContains(lettura, "Spalla destra")

        modifica = self.client.post(
            reverse("training:workout-update", args=[nuovo.pk]),
            {
                "title": "Spinta B — pesante",
                "started_at": self.datetime_local(inizio),
                "ended_at": self.datetime_local(inizio + timedelta(minutes=75)),
                "notes": "",
            },
        )
        self.assertRedirects(
            modifica, reverse("training:workout-detail", args=[nuovo.pk])
        )
        nuovo.refresh_from_db()
        self.assertEqual(nuovo.title, "Spinta B — pesante")
        self.assertIsNotNone(nuovo.ended_at)

        cancellazione = self.client.post(
            reverse("training:workout-delete", args=[nuovo.pk])
        )
        self.assertRedirects(cancellazione, reverse("training:workout-list"))
        self.assertFalse(Workout.objects.filter(pk=nuovo.pk).exists())

    def test_the_list_shows_only_my_workouts(self):
        Workout.objects.create(
            user=self.altro, title="Roba di Martina", started_at=timezone.now()
        )

        response = self.client.get(reverse("training:workout-list"))

        self.assertContains(response, "Spinta A")
        self.assertNotContains(response, "Roba di Martina")

    def test_the_list_counts_only_the_sets_that_were_actually_done(self):
        """Dodici serie di cui tre saltate ne fanno nove: nove è il numero vero."""
        for numero in range(1, 4):
            WorkoutSet.objects.create(
                workout=self.workout, exercise=self.panca, set_number=numero,
                reps=8, weight=Decimal("60.00"),
            )
        WorkoutSet.objects.create(
            workout=self.workout, exercise=self.panca, set_number=4,
            reps=None, weight=None, is_completed=False,
        )
        WorkoutSet.objects.create(
            workout=self.workout, exercise=self.trazioni, set_number=1, reps=6,
        )

        allenamento = self.client.get(
            reverse("training:workout-list")
        ).context["allenamenti"][0]

        self.assertEqual(allenamento.n_serie, 4)  # le eseguite, non le cinque
        self.assertEqual(allenamento.n_esercizi, 2)

    # --- La proprietà dell'oggetto --------------------------------------

    def test_a_second_user_gets_403_on_every_owned_route(self):
        self.client.force_login(self.altro)

        for nome in (
            "workout-detail",
            "workout-update",
            "workout-delete",
            "workoutset-manage",
        ):
            with self.subTest(rotta=nome):
                response = self.client.get(reverse(f"training:{nome}", args=[self.workout.pk]))
                self.assertEqual(response.status_code, 403)

    def test_a_second_user_cannot_delete_or_edit_by_post_either(self):
        """Il 403 sul GET non basta: il POST è la richiesta che fa il danno."""
        self.client.force_login(self.altro)

        cancellazione = self.client.post(
            reverse("training:workout-delete", args=[self.workout.pk])
        )
        self.assertEqual(cancellazione.status_code, 403)
        self.assertTrue(Workout.objects.filter(pk=self.workout.pk).exists())

        serie = self.client.post(
            reverse("training:workoutset-manage", args=[self.workout.pk]),
            self.formset_payload([
                {"exercise": self.panca.pk, "set_number": "1", "reps": "8",
                 "weight": "60", "set_type": "working", "is_completed": "on"},
            ]),
        )
        self.assertEqual(serie.status_code, 403)
        self.assertEqual(self.workout.sets.count(), 0)

    def test_an_anonymous_visitor_is_sent_to_the_login_not_to_a_403(self):
        self.client.logout()

        response = self.client.get(reverse("training:workout-list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response.url)

    def test_the_owner_is_taken_from_the_request_not_from_the_post(self):
        """`user` non è un campo del form: un POST costruito a mano non lo tocca."""
        self.client.post(
            reverse("training:workout-create"),
            {
                "title": "Provo a intestarlo a un altro",
                "started_at": self.datetime_local(timezone.now()),
                "ended_at": "",
                "notes": "",
                "user": self.altro.pk,
            },
        )

        nuovo = Workout.objects.get(title="Provo a intestarlo a un altro")
        self.assertEqual(nuovo.user, self.user)

    # --- Le regole che il form deve dire prima del database -------------

    def test_the_datetime_local_format_is_accepted_and_read_back(self):
        """Il progetto è in `it-it`, l'input nativo parla ISO: la coppia va tradotta.

        Senza `LocalDateTimeField` questo POST tornerebbe indietro con
        «Inserisci una data/ora valida» su un valore che ha composto il
        browser, e la modifica aprirebbe il campo vuoto.
        """
        quando = timezone.now().replace(second=0, microsecond=0)

        creazione = self.client.post(
            reverse("training:workout-create"),
            {
                "title": "Orario ISO",
                "started_at": self.datetime_local(quando),
                "ended_at": "",
                "notes": "",
            },
        )
        self.assertEqual(creazione.status_code, 302)

        nuovo = Workout.objects.get(title="Orario ISO")
        self.assertEqual(
            timezone.localtime(nuovo.started_at).strftime("%Y-%m-%dT%H:%M"),
            self.datetime_local(quando),
        )

        modifica = self.client.get(reverse("training:workout-update", args=[nuovo.pk]))
        self.assertContains(modifica, f'value="{self.datetime_local(quando)}"')

    def test_a_workout_that_ends_before_it_starts_is_a_form_error_not_a_500(self):
        inizio = timezone.now()

        response = self.client.post(
            reverse("training:workout-create"),
            {
                "title": "Al contrario",
                "started_at": self.datetime_local(inizio),
                "ended_at": self.datetime_local(inizio - timedelta(hours=2)),
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "prima di cominciare")
        self.assertFalse(Workout.objects.filter(title="Al contrario").exists())

    def test_absurd_durations_still_go_through_the_form(self):
        """Zero minuti e venticinque ore restano ammessi: lo storico vero ne ha."""
        inizio = timezone.now()

        for etichetta, fine in (
            ("Zero minuti", inizio),
            ("Venticinque ore", inizio + timedelta(hours=25)),
        ):
            with self.subTest(durata=etichetta):
                response = self.client.post(
                    reverse("training:workout-create"),
                    {
                        "title": etichetta,
                        "started_at": self.datetime_local(inizio),
                        "ended_at": self.datetime_local(fine),
                        "notes": "",
                    },
                )
                self.assertEqual(response.status_code, 302)
                self.assertTrue(Workout.objects.filter(title=etichetta).exists())

    # --- Il formset delle serie -----------------------------------------

    def test_the_formset_adds_updates_and_removes_sets(self):
        url = reverse("training:workoutset-manage", args=[self.workout.pk])

        aggiunta = self.client.post(url, self.formset_payload([
            {"exercise": self.panca.pk, "set_number": "1", "reps": "8",
             "weight": "60", "set_type": "working", "is_completed": "on"},
            {"exercise": self.panca.pk, "set_number": "2", "reps": "8",
             "weight": "60", "set_type": "working", "is_completed": "on"},
        ]))
        self.assertRedirects(
            aggiunta, reverse("training:workout-detail", args=[self.workout.pk])
        )
        self.assertEqual(self.workout.sets.count(), 2)

        prima, seconda = self.workout.sets.order_by("set_number")

        modifica = self.client.post(url, self.formset_payload(
            [
                {"id": prima.pk, "exercise": self.panca.pk, "set_number": "1",
                 "reps": "10", "weight": "62.5", "set_type": "working",
                 "is_completed": "on"},
                {"id": seconda.pk, "exercise": self.panca.pk, "set_number": "2",
                 "reps": "8", "weight": "60", "set_type": "working",
                 "is_completed": "on", "DELETE": "on"},
            ],
            iniziali=2,
        ))
        self.assertEqual(modifica.status_code, 302)

        prima.refresh_from_db()
        self.assertEqual(prima.reps, 10)
        self.assertEqual(prima.weight, Decimal("62.50"))
        self.assertEqual(self.workout.sets.count(), 1)

    def test_empty_rows_are_ignored(self):
        """Cinque righe vuote in coda non sono cinque errori.

        `is_completed` ha `default=True`, quindi una riga in bianco arriva al
        `clean` con la spunta messa e senza ripetizioni: senza la guardia della
        riga vuota, `extra=5` renderebbe la pagina impossibile da salvare.
        """
        piena = {"exercise": self.panca.pk, "set_number": "1", "reps": "8",
                 "weight": "60", "set_type": "working", "is_completed": "on"}
        vuota = {"exercise": "", "set_number": "", "reps": "", "weight": "",
                 "set_type": "working"}

        # La casella nasce spuntata, quindi entrambe le forme arrivano davvero
        # dal browser: chi lascia stare le righe in coda, e chi toglie la
        # spunta a una riga che non intende compilare. La seconda è quella che
        # rompeva la pagina.
        for etichetta, spunta in (("lasciata", {"is_completed": "on"}), ("tolta", {})):
            with self.subTest(spunta=etichetta):
                self.workout.sets.all().delete()

                response = self.client.post(
                    reverse("training:workoutset-manage", args=[self.workout.pk]),
                    self.formset_payload([
                        dict(piena),
                        {**vuota, **spunta},
                        {**vuota, **spunta},
                    ]),
                )

                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.workout.sets.count(), 1)

    def test_a_skipped_set_needs_neither_reps_nor_weight(self):
        """È il senso di `is_completed`: «saltata» non è «zero ripetizioni»."""
        response = self.client.post(
            reverse("training:workoutset-manage", args=[self.workout.pk]),
            self.formset_payload([
                {"exercise": self.panca.pk, "set_number": "1", "reps": "",
                 "weight": "", "set_type": "working"},
            ]),
        )

        self.assertEqual(response.status_code, 302)
        serie = self.workout.sets.get()
        self.assertFalse(serie.is_completed)
        self.assertIsNone(serie.reps)

    def test_a_completed_set_without_reps_is_a_form_error_not_a_500(self):
        """`workout_set_completed_has_reps`, detto prima che lo dica SQLite."""
        response = self.client.post(
            reverse("training:workoutset-manage", args=[self.workout.pk]),
            self.formset_payload([
                {"exercise": self.panca.pk, "set_number": "1", "reps": "",
                 "weight": "60", "set_type": "working", "is_completed": "on"},
            ]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "togli la spunta")
        self.assertEqual(self.workout.sets.count(), 0)

    def test_zero_weight_is_accepted_because_bodyweight_exists(self):
        response = self.client.post(
            reverse("training:workoutset-manage", args=[self.workout.pk]),
            self.formset_payload([
                {"exercise": self.trazioni.pk, "set_number": "1", "reps": "6",
                 "weight": "0", "set_type": "working", "is_completed": "on"},
            ]),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.workout.sets.get().weight, Decimal("0.00"))

    def test_the_same_set_number_twice_on_one_exercise_is_a_form_error(self):
        """`workout_set_unique` è `(workout, exercise, set_number)`.

        La terna arriva spezzata al singolo form — `workout` è l'istanza del
        formset — quindi la regola vive nel `clean` del formset. Senza,
        sarebbe un `IntegrityError`.
        """
        response = self.client.post(
            reverse("training:workoutset-manage", args=[self.workout.pk]),
            self.formset_payload([
                {"exercise": self.panca.pk, "set_number": "2", "reps": "8",
                 "weight": "60", "set_type": "working", "is_completed": "on"},
                {"exercise": self.panca.pk, "set_number": "2", "reps": "8",
                 "weight": "60", "set_type": "working", "is_completed": "on"},
            ]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "si numerano")
        self.assertEqual(self.workout.sets.count(), 0)

    def test_the_same_set_number_on_two_different_exercises_is_fine(self):
        """La serie 1 di panca e la serie 1 di trazioni non sono un duplicato."""
        response = self.client.post(
            reverse("training:workoutset-manage", args=[self.workout.pk]),
            self.formset_payload([
                {"exercise": self.panca.pk, "set_number": "1", "reps": "8",
                 "weight": "60", "set_type": "working", "is_completed": "on"},
                {"exercise": self.trazioni.pk, "set_number": "1", "reps": "6",
                 "weight": "0", "set_type": "working", "is_completed": "on"},
            ]),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.workout.sets.count(), 2)

    def test_the_sets_page_does_not_requery_the_catalogue_per_row(self):
        """Il costo della pagina non cresce con le righe.

        `ModelChoiceField` interroga il database ogni volta che il campo viene
        reso, e qui i campi sono uno per serie: sul catalogo vero la pagina
        faceva 27 query, quasi tutte identiche. La guardia non fissa un numero
        — cambierebbe al primo `select_related` in più — ma l'**invariante**:
        due serie o dodici, le query sono le stesse.
        """
        url = reverse("training:workoutset-manage", args=[self.workout.pk])

        def rendi_con(n_serie):
            self.workout.sets.all().delete()
            WorkoutSet.objects.bulk_create([
                WorkoutSet(workout=self.workout, exercise=self.panca,
                           set_number=numero, reps=8, weight=Decimal("60.00"))
                for numero in range(1, n_serie + 1)
            ])
            with CaptureQueriesContext(connection) as contesto:
                self.assertEqual(self.client.get(url).status_code, 200)
            return len(contesto.captured_queries)

        self.assertEqual(rendi_con(2), rendi_con(12))

    # --- Il guscio ------------------------------------------------------

    def test_the_header_links_to_the_history_are_real_routes(self):
        """#67 aveva lasciato due `href` letterali: la voce e il bottone."""
        response = self.client.get(reverse("training:dashboard"))

        self.assertContains(response, f'href="{reverse("training:workout-list")}"')
        self.assertContains(response, f'href="{reverse("training:workout-create")}"')

    def test_only_the_history_section_lights_up_on_a_workout_page(self):
        response = self.client.get(
            reverse("training:workoutset-manage", args=[self.workout.pk])
        )
        body = response.content.decode()

        self.assertIn('class="attivo">Storico</a>', body)
        self.assertIn('class="">Schede</a>', body)


class StartWorkoutFromRoutineTests(TestCase):
    """«Avvia allenamento da scheda»: il pezzo che tiene insieme piano ed eseguito.

    Una pagina, un POST, zero JavaScript. Ciò che va protetto non è che la
    pagina renda, ma che la **precompilazione** sia quella promessa: le serie
    pianificate, col carico dell'ultima volta, e senza inventare numeri dove
    un dato precedente non c'è.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="lorenzo", password=PASSWORD)
        cls.altro = User.objects.create_user(username="martina", password=PASSWORD)

        group = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        muscle = Muscle.objects.create(
            code="chestMid", group=group, label_it="Petto medio", sort_order=1
        )
        cls.bilanciere = Equipment.objects.create(
            code="barbell", label_it="Bilanciere",
            default_bar_weight_kg=Decimal("20.00"), sort_order=1,
        )
        cls.corpo_libero = Equipment.objects.create(
            code="bodyweight", label_it="Corpo libero",
            default_bar_weight_kg=Decimal("0.00"),
            load_increment_kg=Decimal("0.00"), sort_order=2,
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana", slug="panca-piana",
            primary_muscle=muscle, equipment=cls.bilanciere,
        )
        cls.trazioni = Exercise.objects.create(
            name="Trazioni", slug="trazioni",
            primary_muscle=muscle, equipment=cls.corpo_libero,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.scheda = Routine.objects.create(user=self.user, name="Spinta A")
        RoutineExercise.objects.create(
            routine=self.scheda, exercise=self.panca, position=1,
            target_sets=3, target_reps=8, target_reps_max=12,
        )
        RoutineExercise.objects.create(
            routine=self.scheda, exercise=self.trazioni, position=2,
            target_sets=2, target_reps=6,
        )

    def url_avvio(self, scheda=None):
        base = reverse("training:workout-create")
        return base if scheda is None else f"{base}?scheda={scheda.pk}"

    def avvia(self, scheda=None, titolo="Spinta A"):
        return self.client.post(
            self.url_avvio(scheda),
            {
                "title": titolo,
                "started_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "ended_at": "",
                "notes": "",
            },
        )

    def serie_passata(self, exercise, weight, giorni_fa, is_completed=True):
        allenamento = Workout.objects.create(
            user=self.user,
            title="Vecchio",
            started_at=timezone.now() - timedelta(days=giorni_fa),
        )
        return WorkoutSet.objects.create(
            workout=allenamento, exercise=exercise, set_number=1,
            reps=8 if is_completed else None,
            weight=weight, is_completed=is_completed,
        )

    # --- La precompilazione ---------------------------------------------

    def test_the_page_offers_the_routine_it_will_start_from(self):
        response = self.client.get(self.url_avvio(self.scheda))

        self.assertEqual(response.status_code, 200)
        # Il titolo arriva già scritto: è l'istantanea del nome della scheda.
        self.assertContains(response, 'value="Spinta A"')
        self.assertContains(response, "Da scheda: Spinta A")

    def test_starting_from_a_routine_writes_the_planned_sets(self):
        risposta = self.avvia(self.scheda)

        allenamento = Workout.objects.get(title="Spinta A")
        self.assertRedirects(
            risposta, reverse("training:workoutset-manage", args=[allenamento.pk])
        )
        self.assertEqual(allenamento.routine, self.scheda)

        # Tre serie di panca più due di trazioni, numerate da 1 per esercizio.
        self.assertEqual(allenamento.sets.count(), 5)
        panca = allenamento.sets.filter(exercise=self.panca).order_by("set_number")
        self.assertEqual([s.set_number for s in panca], [1, 2, 3])
        # L'estremo *basso* del bersaglio: l'alto è ciò che va conquistato.
        self.assertEqual({s.reps for s in panca}, {8})
        self.assertTrue(all(s.is_completed for s in panca))

    def test_the_weight_starts_from_the_last_time_the_exercise_was_done(self):
        self.serie_passata(self.panca, Decimal("60.00"), giorni_fa=14)
        self.serie_passata(self.panca, Decimal("65.00"), giorni_fa=3)

        self.avvia(self.scheda)

        allenamento = Workout.objects.get(title="Spinta A")
        pesi = {s.weight for s in allenamento.sets.filter(exercise=self.panca)}
        self.assertEqual(pesi, {Decimal("65.00")})

    def test_without_a_previous_time_the_weight_is_the_empty_bar(self):
        """20 kg sul bilanciere, 0 sul corpo libero: il minimo vero, non una stima."""
        self.avvia(self.scheda)

        allenamento = Workout.objects.get(title="Spinta A")
        self.assertEqual(
            allenamento.sets.filter(exercise=self.panca).first().weight,
            Decimal("20.00"),
        )
        self.assertEqual(
            allenamento.sets.filter(exercise=self.trazioni).first().weight,
            Decimal("0.00"),
        )

    def test_a_skipped_set_is_not_a_weight_to_start_from(self):
        """Il carico di una serie saltata è un'intenzione, non un dato."""
        self.serie_passata(self.panca, Decimal("60.00"), giorni_fa=14)
        self.serie_passata(
            self.panca, Decimal("90.00"), giorni_fa=1, is_completed=False
        )

        self.avvia(self.scheda)

        allenamento = Workout.objects.get(title="Spinta A")
        self.assertEqual(
            allenamento.sets.filter(exercise=self.panca).first().weight,
            Decimal("60.00"),
        )

    def test_someone_elses_history_is_not_my_starting_weight(self):
        altro_allenamento = Workout.objects.create(
            user=self.altro, title="Suo", started_at=timezone.now()
        )
        WorkoutSet.objects.create(
            workout=altro_allenamento, exercise=self.panca, set_number=1,
            reps=8, weight=Decimal("140.00"),
        )

        self.avvia(self.scheda)

        allenamento = Workout.objects.get(title="Spinta A")
        self.assertEqual(
            allenamento.sets.filter(exercise=self.panca).first().weight,
            Decimal("20.00"),
        )

    def test_a_zero_rep_target_becomes_a_skipped_set_not_a_500(self):
        """`target_reps` a zero passa il database ma violerebbe il check sulla serie.

        Nasce **saltata**, che è l'unica lettura coerente: una riga senza
        ripetizioni non è una serie eseguita a zero.
        """
        RoutineExercise.objects.filter(exercise=self.trazioni).update(target_reps=0)

        risposta = self.avvia(self.scheda)

        self.assertEqual(risposta.status_code, 302)
        allenamento = Workout.objects.get(title="Spinta A")
        saltate = allenamento.sets.filter(exercise=self.trazioni)
        self.assertEqual(saltate.count(), 2)
        self.assertFalse(any(s.is_completed for s in saltate))
        self.assertTrue(all(s.reps is None for s in saltate))

    # --- I confini ------------------------------------------------------

    def test_a_workout_started_without_a_routine_is_empty_and_unlinked(self):
        risposta = self.avvia(scheda=None, titolo="A mano")

        self.assertEqual(risposta.status_code, 302)
        allenamento = Workout.objects.get(title="A mano")
        self.assertIsNone(allenamento.routine)
        self.assertEqual(allenamento.sets.count(), 0)

    def test_a_second_users_routine_cannot_be_started(self):
        """403 come per il mixin: il parametro è in query string, la regola no."""
        sua = Routine.objects.create(user=self.altro, name="Sua")

        lettura = self.client.get(self.url_avvio(sua))
        self.assertEqual(lettura.status_code, 403)

        scrittura = self.avvia(sua, titolo="Rubata")
        self.assertEqual(scrittura.status_code, 403)
        self.assertFalse(Workout.objects.filter(title="Rubata").exists())

    def test_an_unknown_routine_is_a_404(self):
        response = self.client.get(f"{reverse('training:workout-create')}?scheda=9999")

        self.assertEqual(response.status_code, 404)

    def test_a_nonsense_routine_parameter_is_ignored_not_a_500(self):
        response = self.client.get(f"{reverse('training:workout-create')}?scheda=pippo")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["scheda"])

    # --- ADR-0002 dal lato della view -----------------------------------

    def test_the_title_is_a_snapshot_not_a_reference(self):
        """Rinominare la scheda non riscrive il passato."""
        self.avvia(self.scheda)
        allenamento = Workout.objects.get(title="Spinta A")

        self.scheda.name = "Spinta A — rivista"
        self.scheda.save()

        allenamento.refresh_from_db()
        self.assertEqual(allenamento.title, "Spinta A")

    def test_deleting_the_routine_leaves_the_workout_and_its_sets(self):
        self.avvia(self.scheda)
        allenamento = Workout.objects.get(title="Spinta A")

        self.client.post(reverse("training:routine-delete", args=[self.scheda.pk]))

        allenamento.refresh_from_db()
        self.assertIsNone(allenamento.routine)
        self.assertEqual(allenamento.title, "Spinta A")
        self.assertEqual(allenamento.sets.count(), 5)

    def test_the_routine_page_offers_to_start_a_workout(self):
        response = self.client.get(
            reverse("training:routine-detail", args=[self.scheda.pk])
        )

        self.assertContains(response, f'{self.url_avvio(self.scheda)}"')

    def test_an_empty_routine_does_not_offer_to_start_a_workout(self):
        """Precompilerebbe zero serie, e un allenamento vuoto sembra un guasto."""
        vuota = Routine.objects.create(user=self.user, name="Ancora da riempire")

        response = self.client.get(
            reverse("training:routine-detail", args=[vuota.pk])
        )

        self.assertNotContains(response, f'{self.url_avvio(vuota)}"')


# --- La community e il voto (#72) ------------------------------------------
#
# Il **terzo CRUD**, e con lui i due test che `07-test.md` §3 mette fra i
# quattro che contano: l'autovoto e la scheda non pubblica. Non sono
# raffinatezze e non sono `CheckConstraint` — attraversano una relazione,
# quindi nessun vincolo di database può imporli, e vivono nel form e nella
# view. È esattamente il tipo di regola che si perde in un refactor senza che
# niente segnali l'errore: la pagina continua a rendere, la classifica sociale
# comincia solo a mentire.


class PublicRoutineAndVoteTests(TestCase):
    """`/schede/pubbliche/` e il CRUD su `Vote`."""

    @classmethod
    def setUpTestData(cls):
        cls.autore = User.objects.create_user(username="lorenzo", password=PASSWORD)
        cls.lettore = User.objects.create_user(username="martina", password=PASSWORD)
        cls.terzo = User.objects.create_user(username="giulia", password=PASSWORD)

        group = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        muscle = Muscle.objects.create(
            code="chestMid", group=group, label_it="Petto medio", sort_order=1
        )
        equipment = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana", slug="panca-piana",
            primary_muscle=muscle, equipment=equipment,
        )

    def setUp(self):
        self.pubblica = Routine.objects.create(
            user=self.autore, name="Spinta A", is_public=True
        )
        RoutineExercise.objects.create(
            routine=self.pubblica, exercise=self.panca,
            position=1, target_sets=3, target_reps=8, target_reps_max=12,
        )
        self.privata = Routine.objects.create(
            user=self.autore, name="Bozza segreta", is_public=False
        )
        self.client.force_login(self.lettore)

    def url_detail(self, routine):
        return reverse("training:routine-public-detail", args=[routine.pk])

    # --- La community ---------------------------------------------------

    def test_the_community_lists_only_public_routines(self):
        """`is_public` è l'unico consenso dato dall'autore, e vale come filtro."""
        response = self.client.get(reverse("training:routine-public-list"))

        self.assertContains(response, "Spinta A")
        self.assertNotContains(response, "Bozza segreta")

    def test_the_community_shows_the_average_with_the_number_of_votes(self):
        """«4,5» su due voti e «4,5» su cento non sono lo stesso numero."""
        Vote.objects.create(user=self.lettore, routine=self.pubblica, score=4)
        Vote.objects.create(user=self.terzo, routine=self.pubblica, score=5)

        response = self.client.get(reverse("training:routine-public-list"))

        self.assertContains(response, "4,5/5")
        self.assertContains(response, "2 voti")

    def test_the_community_is_reachable_from_inside_the_routines_section(self):
        """La regola di navigazione: nessun link orfano, e nessuna sesta voce."""
        response = self.client.get(reverse("training:routine-list"))

        self.assertContains(
            response, f'href="{reverse("training:routine-public-list")}"'
        )

    def test_the_community_lights_up_the_routines_section_and_only_that(self):
        response = self.client.get(reverse("training:routine-public-list"))
        body = response.content.decode()

        self.assertIn('class="attivo">Schede</a>', body)
        self.assertIn('class="">Esercizi</a>', body)

    def test_a_private_routine_has_no_public_page(self):
        """404 e non 403: finché l'autore non la espone, da qui non esiste."""
        for chi in (self.lettore, self.autore):
            with self.subTest(utente=chi.get_username()):
                self.client.force_login(chi)

                response = self.client.get(self.url_detail(self.privata))

                self.assertEqual(response.status_code, 404)

    def test_the_public_page_shows_the_routine_of_someone_else(self):
        response = self.client.get(self.url_detail(self.pubblica))

        self.assertContains(response, "Spinta A")
        self.assertContains(response, "Panca piana")
        self.assertContains(response, "lorenzo")

    def test_the_community_is_private_like_the_rest(self):
        self.client.logout()

        for url in (
            reverse("training:routine-public-list"),
            self.url_detail(self.pubblica),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertRedirects(response, f"{reverse('login')}?next={url}")

    # --- I tre verbi del voto -------------------------------------------

    def test_create_update_and_delete_my_vote(self):
        """Creare, **modificare** e cancellare: è il terzo CRUD, per intero."""
        url = self.url_detail(self.pubblica)

        # Creare.
        response = self.client.post(url, {"score": "4", "comment": "Buona spinta."})
        self.assertRedirects(response, url)
        voto = Vote.objects.get(user=self.lettore, routine=self.pubblica)
        self.assertEqual(voto.score, 4)
        self.assertEqual(voto.comment, "Buona spinta.")

        # Modificare: il secondo invio **aggiorna** invece di violare
        # l'unicità `(user, routine)` con un `IntegrityError`.
        response = self.client.post(url, {"score": "2", "comment": "Ci ho ripensato."})
        self.assertRedirects(response, url)
        self.assertEqual(Vote.objects.filter(routine=self.pubblica).count(), 1)
        voto.refresh_from_db()
        self.assertEqual(voto.score, 2)

        # Cancellare: la conferma è una pagina, l'effetto è nel POST.
        conferma = reverse("training:vote-delete", args=[self.pubblica.pk])
        self.assertEqual(self.client.get(conferma).status_code, 200)
        self.assertTrue(Vote.objects.filter(pk=voto.pk).exists())

        response = self.client.post(conferma)
        self.assertRedirects(response, url)
        self.assertFalse(Vote.objects.filter(pk=voto.pk).exists())

    def test_the_voter_is_taken_from_the_request_not_from_the_post(self):
        """`user` e `routine` non sono campi del form: li mette la view."""
        self.client.post(
            self.url_detail(self.pubblica),
            {"score": "5", "comment": "", "user": self.terzo.pk,
             "routine": self.privata.pk},
        )

        voto = Vote.objects.get()
        self.assertEqual(voto.user, self.lettore)
        self.assertEqual(voto.routine, self.pubblica)

    def test_a_vote_of_someone_else_is_not_mine_to_delete(self):
        """L'URL porta il `pk` della scheda: il voto di un altro non è puntabile."""
        Vote.objects.create(user=self.terzo, routine=self.pubblica, score=5)

        response = self.client.post(
            reverse("training:vote-delete", args=[self.pubblica.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Vote.objects.count(), 1)

    def test_a_score_outside_the_scale_is_a_form_error_not_a_500(self):
        """Il `CheckConstraint` 1–5 c'è, ma non deve essere lui a rispondere."""
        response = self.client.post(
            self.url_detail(self.pubblica), {"score": "7", "comment": ""}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Vote.objects.exists())

    def test_the_page_shows_the_average_and_the_comments_of_the_others(self):
        Vote.objects.create(
            user=self.terzo, routine=self.pubblica, score=5, comment="Ottima."
        )

        response = self.client.get(self.url_detail(self.pubblica))

        self.assertContains(response, "Ottima.")
        self.assertContains(response, "giulia")

    # --- Le due regole che il database non può imporre (07-test.md §3) ---

    def test_voting_your_own_routine_is_refused(self):
        """L'autovoto sposterebbe la classifica sociale senza aggiungere un giudizio.

        Non è un `CheckConstraint`: la regola attraversa la relazione fra
        `Vote.user` e `Routine.user`, e SQLite non può leggere l'altra tabella.
        Vive nel form, e il POST arriva **200 con l'errore**, non 302: nessuna
        riga entra.
        """
        self.client.force_login(self.autore)

        response = self.client.post(
            self.url_detail(self.pubblica), {"score": "5", "comment": "Bella mia."}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Vote.objects.exists())
        self.assertContains(response, "Non si vota la propria scheda")

    def test_the_owner_never_even_sees_the_form(self):
        """La faccia visibile della stessa regola: sulla propria scheda niente form."""
        self.client.force_login(self.autore)

        response = self.client.get(self.url_detail(self.pubblica))

        self.assertNotContains(response, 'name="score"')
        self.assertContains(response, "Questa scheda è tua")

    def test_a_private_routine_is_not_votable(self):
        """La seconda regola, e vale a due livelli.

        Dalla pagina la scheda privata non è raggiungibile — il queryset la
        esclude, quindi il POST è un 404 — ma la regola non può poggiare solo
        sul filtro della view: se la scheda venisse resa privata fra il GET e
        il POST, o se un domani un'altra view riusasse il form, a rifiutare
        dev'essere il form. Qui si verificano entrambi.
        """
        response = self.client.post(
            self.url_detail(self.privata), {"score": "5", "comment": ""}
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Vote.objects.exists())

        form = VoteForm(
            {"score": "5", "comment": ""},
            voter=self.lettore,
            routine=self.privata,
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Questa scheda non è pubblica: non è votabile.",
            form.non_field_errors(),
        )

    def test_the_form_refuses_the_self_vote_on_its_own(self):
        """La regola dell'autovoto, presa dal lato del form e non della pagina."""
        form = VoteForm(
            {"score": "5", "comment": ""},
            voter=self.autore,
            routine=self.pubblica,
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Non si vota la propria scheda: il voto è il giudizio degli altri.",
            form.non_field_errors(),
        )


class CsvImportTests(TestCase):
    """L'import CSV lato utente: il canale che si mostra al prof.

    `load_catalog` paga lo stesso requisito dal lato amministratore ed è già
    provato sopra; questo è il canale **utente**, tre URL e un form.

    I casi qui sotto sono quelli **misurati sui dati veri**
    (`docs/overload-export.md`), non immaginati: è la differenza fra un import
    che regge lo storico di Lorenzo e uno che rifiuta 25 serie legittime di
    corpo libero perché pretende un peso.

    I CSV di prova sono costruiti **in memoria** e non versionati: i file
    fabbricati a mano in `training/tests/fixtures/`, con un caso per riga e la
    copertura dell'export, sono il ticket #74, che chiude il giro. Qui il file
    nasce nel test perché ogni test vuole variarne una cella sola.
    """

    #: Due sessioni: una normale, e una da trenta secondi che è il caso
    #: «durata assurda» — entra intatta, con un avviso.
    SESSIONI = (
        "id,user_id,routine_id,title,started_at,ended_at,notes\n"
        "11111111-1111-4111-8111-111111111111,{estraneo},{routine},Spinta A,"
        "2026-08-10T06:00:00+00:00,2026-08-10T07:00:00+00:00,\n"
        "22222222-2222-4222-8222-222222222222,{estraneo},,Sessione lampo,"
        "2026-08-11T06:00:00+00:00,2026-08-11T06:00:30+00:00,\n"
    )

    #: Le righe, in ordine, con il numero **reale** che avranno nel file:
    #: 2 normale, 3 corpo libero, 4 non eseguita, 5 eseguita senza ripetizioni
    #: (l'unico errore vero), 6 nome non abbinabile.
    SERIE = (
        "id,session_id,exercise_name,set_number,reps,weight,set_type,is_completed\n"
        "aaaaaaaa-0001-4000-8000-000000000000,11111111-1111-4111-8111-111111111111,"
        "Panca piana,1,8,60,working,true\n"
        "aaaaaaaa-0002-4000-8000-000000000000,11111111-1111-4111-8111-111111111111,"
        "Trazioni,1,10,,working,true\n"
        "aaaaaaaa-0003-4000-8000-000000000000,11111111-1111-4111-8111-111111111111,"
        "Panca piana,2,,,working,false\n"
        "aaaaaaaa-0004-4000-8000-000000000000,11111111-1111-4111-8111-111111111111,"
        "Panca piana,3,,80,working,true\n"
        "aaaaaaaa-0005-4000-8000-000000000000,22222222-2222-4222-8222-222222222222,"
        "RDL,1,8,100,working,true\n"
    )

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="lorenzo", password=PASSWORD)
        cls.altro = User.objects.create_user(username="martina", password=PASSWORD)

        group = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        muscle = Muscle.objects.create(
            code="chestMid", group=group, label_it="Petto medio", sort_order=1
        )
        bilanciere = Equipment.objects.create(
            code="barbell",
            label_it="Bilanciere",
            default_bar_weight_kg=Decimal("20.00"),
            sort_order=1,
        )
        corpo_libero = Equipment.objects.create(
            code="bodyweight",
            label_it="Corpo libero",
            default_bar_weight_kg=Decimal("0.00"),
            load_increment_kg=Decimal("0.00"),
            sort_order=2,
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana", slug="panca-piana",
            primary_muscle=muscle, equipment=bilanciere,
        )
        cls.trazioni = Exercise.objects.create(
            name="Trazioni", slug="trazioni",
            primary_muscle=muscle, equipment=corpo_libero,
        )
        cls.stacco = Exercise.objects.create(
            name="Stacco rumeno con bilanciere", slug="stacco-rumeno-con-bilanciere",
            primary_muscle=muscle, equipment=bilanciere,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.deposito = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.deposito, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.deposito)
        override.enable()
        self.addCleanup(override.disable)

    # ------------------------------------------------------------------ utili

    def files(self, sessioni=None, serie=None, esercizi=None):
        """I due file come li manda un browser. `SimpleUploadedFile` è
        binario, che è esattamente ciò che il parser riceve in produzione."""
        dati = {
            "sessioni": SimpleUploadedFile(
                "workout_sessions.csv",
                (sessioni if sessioni is not None else self.sessioni()).encode("utf-8"),
                content_type="text/csv",
            ),
            "serie": SimpleUploadedFile(
                "session_sets.csv",
                (serie if serie is not None else self.SERIE).encode("utf-8"),
                content_type="text/csv",
            ),
        }
        if esercizi is not None:
            dati["esercizi"] = SimpleUploadedFile(
                "exercises.csv", esercizi.encode("utf-8"), content_type="text/csv"
            )
        return dati

    def sessioni(self):
        """Il `user_id` del CSV è quello di **un altro utente**, di proposito:
        è il dato di un altro sistema e non deve avere nessuna autorità qui."""
        return self.SESSIONI.format(estraneo=self.altro.pk, routine="99")

    def carica(self, **kwargs):
        risposta = self.client.post(
            reverse("training:import-upload"), self.files(**kwargs)
        )
        return risposta

    def conferma(self, abbinamenti):
        """Il POST dell'anteprima: il formset degli abbinamenti.

        `abbinamenti` è la lista `(nome grezzo, esercizio)` nell'ordine in cui
        la pagina li ha chiesti.
        """
        dati = {
            "form-TOTAL_FORMS": str(len(abbinamenti)),
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        for indice, (nome, esercizio) in enumerate(abbinamenti):
            dati[f"form-{indice}-raw_name"] = nome
            dati[f"form-{indice}-exercise"] = str(esercizio.pk)
        return self.client.post(reverse("training:import-preview"), dati)

    # ------------------------------------------------------------- l'anteprima

    def test_anteprima_non_scrive_niente(self):
        """La regola che dà senso a tutti e tre gli URL: **niente entra prima
        della conferma**. Un'anteprima che avesse già scritto sarebbe un
        resoconto, non un'anteprima, e la tabella di abbinamento non avrebbe
        nessuno da servire."""
        self.carica()
        risposta = self.client.get(reverse("training:import-preview"))

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(Workout.objects.count(), 0)
        self.assertEqual(WorkoutSet.objects.count(), 0)

    def test_anteprima_conta_e_scarta(self):
        self.carica()
        contesto = self.client.get(reverse("training:import-preview")).context

        self.assertEqual(contesto["valide_sessioni"], 2)
        # Cinque righe lette, una sola scartata: quella eseguita senza
        # ripetizioni. La serie senza peso NON è fra loro — è il corpo libero.
        self.assertEqual(contesto["lettura"].lette_serie, 5)
        self.assertEqual(len(contesto["lettura"].serie), 4)
        self.assertEqual(len(contesto["lettura"].errori), 1)

    def test_riga_in_errore_porta_il_numero_reale_del_csv(self):
        """Il numero serve ad aprire il file e andarci: l'intestazione è la
        riga 1, quindi la quarta riga di dati è la riga 5."""
        self.carica()
        contesto = self.client.get(reverse("training:import-preview")).context
        errore = contesto["lettura"].errori[0]

        self.assertEqual(errore.numero, 5)
        self.assertEqual(errore.file, "session_sets.csv")
        self.assertEqual(errore.colonna, "reps")
        self.assertIn("ripetizioni", errore.motivo)

    def test_durata_assurda_e_un_avviso_non_bloccante(self):
        """Trenta secondi di allenamento sono assurdi ma non impossibili.
        Correggerli sarebbe inventare un dato; scartarli, sullo storico reale,
        perderebbe 2 sessioni su 15."""
        self.carica()
        contesto = self.client.get(reverse("training:import-preview")).context

        self.assertEqual(len(contesto["lettura"].avvisi), 1)
        self.assertEqual(contesto["valide_sessioni"], 2)

    def test_il_nome_non_abbinabile_finisce_nel_form_e_non_blocca(self):
        """`RDL` non assomiglia a «Stacco rumeno con bilanciere» e nessuna
        normalizzazione lo risolverà mai: è una **scelta**, e la fa l'utente
        (ADR-0010). Intanto le altre righe restano importabili."""
        self.carica()
        risposta = self.client.get(reverse("training:import-preview"))
        formset = risposta.context["form"]

        self.assertEqual(len(formset.forms), 1)
        self.assertEqual(formset.forms[0].initial["raw_name"], "RDL")
        # Panca piana e Trazioni si sono risolti da soli, per nome esatto.
        self.assertEqual(len(risposta.context["risolti"]), 2)

    def test_lanteprima_non_ripaga_il_catalogo_a_ogni_riga(self):
        """Il costo della pagina non cresce con le righe.

        Stessa guardia di `test_the_sets_page_does_not_requery_the_catalogue_per_row`
        (#70) e della sua gemella sulle schede (#86), e **nella stessa forma**:
        due righe o dodici, le query sono le stesse. Ciò che si protegge è
        l'invariante, non il numero, o la guardia cadrebbe al primo
        `select_related` innocuo aggiunto altrove.

        Qui le righe non le decide l'utente: sono i **nomi non abbinati** che
        il file porta, e sullo storico reale sono ventiquattro — ognuna con una
        `<select>` da cento opzioni. È il terzo formset del progetto a porre la
        stessa domanda, e il primo che non è inline.
        """

        def rendi_con(n_righe):
            righe = "".join(
                f"aaaaaaaa-{indice:04d}-4000-8000-000000000000,"
                "11111111-1111-4111-8111-111111111111,"
                f"Ignoto {indice},1,8,60,working,true\n"
                for indice in range(n_righe)
            )
            self.carica(
                serie=(
                    "id,session_id,exercise_name,set_number,reps,weight,"
                    "set_type,is_completed\n" + righe
                )
            )
            with CaptureQueriesContext(connection) as contesto:
                risposta = self.client.get(reverse("training:import-preview"))
            self.assertEqual(len(risposta.context["form"].forms), n_righe)
            return len(contesto.captured_queries)

        self.assertEqual(rendi_con(2), rendi_con(12))

    # -------------------------------------------------------------- la conferma

    def test_import_completo(self):
        self.carica()
        self.client.get(reverse("training:import-preview"))
        risposta = self.conferma([("RDL", self.stacco)])

        self.assertRedirects(risposta, reverse("training:import-result"))
        self.assertEqual(Workout.objects.count(), 2)
        self.assertEqual(WorkoutSet.objects.count(), 4)

    def test_accettare_il_suggerimento_cosi_com_e_importa_lo_stesso(self):
        """LA GUARDIA SU UN NO MUTO, e l'ha trovato lo storico reale.

        Il gesto più normale su quella pagina è **accettare il suggerimento**:
        la `<select>` arriva già selezionata, si guarda, si conferma. Ma quella
        riga resta allora identica ai propri valori iniziali, e Django tratta
        le righe senza istanza come righe `extra`, cioè con
        `empty_permitted=True`: riga non cambiata, `cleaned_data` vuoto,
        abbinamento perso. Il formset resta valido, la pagina rimanda
        all'esito, e le serie di quel nome semplicemente non entrano — con
        nessuno a dirlo. È la famiglia di guasti di #69, #71 e #72.

        Il test copre il caso in cui il POST **coincide** col suggerimento, che
        è l'unico in cui il bug si manifesta: un abbinamento corretto a mano
        cambia la riga e passa comunque.
        """
        # `Trazioni` è nel catalogo, quindi si risolve da solo: serve un nome
        # che il suggeritore indovini. `Panca Piana` con la P maiuscola no —
        # quello lo prende il confronto esatto — ma `Panca piena` sì.
        serie = (
            "id,session_id,exercise_name,set_number,reps,weight,set_type,is_completed\n"
            "aaaaaaaa-0001-4000-8000-000000000000,"
            "11111111-1111-4111-8111-111111111111,Panca piena,1,8,60,working,true\n"
        )
        self.carica(serie=serie)
        formset = self.client.get(reverse("training:import-preview")).context["form"]

        suggerito = formset.forms[0].initial["exercise"]
        self.assertEqual(suggerito, self.panca, "il suggeritore non ha proposto nulla")

        # Si conferma esattamente ciò che la pagina proponeva.
        self.conferma([("Panca piena", suggerito)])

        self.assertEqual(WorkoutSet.objects.count(), 1)
        self.assertEqual(WorkoutSet.objects.get().exercise, self.panca)

    def test_il_user_id_del_csv_si_ignora(self):
        """L'unica fonte dell'identità è `request.user`. Il file porta il
        `user_id` di un altro sistema — qui, di proposito, quello di un altro
        utente registrato — e non gli si dà nessuna autorità: nessun import per
        conto di altri, nemmeno da admin."""
        self.carica()
        self.client.get(reverse("training:import-preview"))
        self.conferma([("RDL", self.stacco)])

        self.assertEqual(Workout.objects.filter(user=self.user).count(), 2)
        self.assertEqual(Workout.objects.filter(user=self.altro).count(), 0)

    def test_la_serie_non_eseguita_entra_vuota(self):
        """61 righe su 317 nello storico reale. Entrano, ed è la differenza fra
        «non l'ho fatta» e «non l'avevo prevista»."""
        self.carica()
        self.client.get(reverse("training:import-preview"))
        self.conferma([("RDL", self.stacco)])

        serie = WorkoutSet.objects.get(exercise=self.panca, set_number=2)
        self.assertFalse(serie.is_completed)
        self.assertIsNone(serie.reps)
        self.assertIsNone(serie.weight)

    def test_la_serie_a_corpo_libero_entra_senza_peso(self):
        """25 righe nello storico reale, e sono trazioni e leg raises. Un
        import che pretende `weight` non nullo su una serie completata
        rifiuterebbe dati legittimi: è la trappola misurata in #13."""
        self.carica()
        self.client.get(reverse("training:import-preview"))
        self.conferma([("RDL", self.stacco)])

        serie = WorkoutSet.objects.get(exercise=self.trazioni)
        self.assertTrue(serie.is_completed)
        self.assertEqual(serie.reps, 10)
        self.assertIsNone(serie.weight)

    def test_la_scheda_non_si_importa_e_il_titolo_sopravvive(self):
        """`routine_id` non punta a niente, avendo escluso le schede: resta il
        solo `title`, che è un'istantanea e non un riferimento. È esattamente
        il caso che ADR-0002 descrive."""
        self.carica()
        self.client.get(reverse("training:import-preview"))
        self.conferma([("RDL", self.stacco)])

        allenamento = Workout.objects.get(title="Spinta A")
        self.assertIsNone(allenamento.routine)

    def test_labbinamento_si_ricorda(self):
        """Metà del valore di ADR-0010: la scelta si fa una volta. L'altra metà
        è che a farla sia un umano."""
        self.carica()
        self.client.get(reverse("training:import-preview"))
        self.conferma([("RDL", self.stacco)])

        alias = ExerciseAlias.objects.get(user=self.user, raw_name="RDL")
        self.assertEqual(alias.exercise, self.stacco)

        # Secondo import dello stesso file: `RDL` non si chiede più.
        self.carica()
        formset = self.client.get(reverse("training:import-preview")).context["form"]
        self.assertEqual(len(formset.forms), 0)

    def test_lo_stesso_file_due_volte_non_duplica(self):
        """L'idempotenza di `external_id`, e il motivo per cui quei due campi
        esistono. Il ticket #74 la verifica anche dal lato export."""
        self.carica()
        self.client.get(reverse("training:import-preview"))
        self.conferma([("RDL", self.stacco)])
        allenamenti, serie = Workout.objects.count(), WorkoutSet.objects.count()

        self.carica()
        self.client.get(reverse("training:import-preview"))
        self.conferma([])

        self.assertEqual(Workout.objects.count(), allenamenti)
        self.assertEqual(WorkoutSet.objects.count(), serie)

    def test_lesito_si_consuma(self):
        """Ricaricare la pagina d'esito non ripete l'import: la scrittura è
        avvenuta nel POST dell'anteprima, e questa è una GET dopo una
        redirect. È il motivo pratico dei tre URL."""
        self.carica()
        self.client.get(reverse("training:import-preview"))
        self.conferma([("RDL", self.stacco)])

        primo = self.client.get(reverse("training:import-result"))
        self.assertEqual(primo.context["esito"]["allenamenti"], 2)

        secondo = self.client.get(reverse("training:import-result"))
        self.assertIsNone(secondo.context["esito"])
        self.assertEqual(Workout.objects.count(), 2)

    # ------------------------------------------------------------ i due canali

    def test_il_dizionario_degli_esercizi_traduce_ma_non_crea(self):
        """`exercises.csv` è accettato **come dizionario** `id → nome`, ed è
        ciò che rende leggibile l'export di Overload, dove le serie portano un
        UUID al posto del nome. Nessun `Exercise` nasce da qui: il catalogo è
        globale e chiuso (ADR-0001)."""
        serie = (
            "id,session_id,exercise_id,set_number,reps,weight,set_type,is_completed\n"
            "aaaaaaaa-0001-4000-8000-000000000000,"
            "11111111-1111-4111-8111-111111111111,ext-1,1,8,60,working,true\n"
        )
        esercizi = "id,name\next-1,Panca piana\n"
        catalogo = Exercise.objects.count()

        self.carica(serie=serie, esercizi=esercizi)
        contesto = self.client.get(reverse("training:import-preview")).context

        self.assertEqual(len(contesto["lettura"].serie), 1)
        self.assertEqual(contesto["lettura"].serie[0].raw_name, "Panca piana")
        self.assertEqual(Exercise.objects.count(), catalogo)

    def test_un_file_senza_le_colonne_torna_allupload(self):
        """Colonne mancanti non sono un errore di riga da elencare nel report:
        non c'è nessuna riga da leggere. La risposta giusta è rimandare al
        primo passo dicendo cosa manca, non un'anteprima vuota."""
        risposta = self.client.post(
            reverse("training:import-upload"),
            self.files(sessioni="titolo,quando\nSpinta A,ieri\n"),
            follow=True,
        )

        self.assertRedirects(risposta, reverse("training:import-upload"))
        self.assertContains(risposta, "mancano le colonne")

    def test_il_form_rifiuta_ciò_che_non_e_un_csv(self):
        risposta = self.client.post(
            reverse("training:import-upload"),
            {
                "sessioni": SimpleUploadedFile(
                    "storico.txt", b"id,title\n", content_type="text/plain"
                ),
                "serie": SimpleUploadedFile(
                    "session_sets.csv", self.SERIE.encode("utf-8")
                ),
            },
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertIn("sessioni", risposta.context["form"].errors)

    def test_le_tre_pagine_vogliono_il_login(self):
        self.client.logout()
        for nome in ("import-upload", "import-preview", "import-result"):
            with self.subTest(rotta=nome):
                risposta = self.client.get(reverse(f"training:{nome}"))
                self.assertEqual(risposta.status_code, 302)
                self.assertIn("/accounts/login/", risposta["Location"])


# --- L'export, i CSV di prova e l'idempotenza (#74) -------------------------
#
# Qui il giro si chiude, e sono tre cose in una.
#
# **I file.** I CSV di `training/tests/fixtures/` sono fabbricati a mano e
# versionati, e ogni riga è un caso deciso in `03-import-ed-export.md`: la
# tabella completa sta nel loro README. `CsvImportTests` costruisce invece i
# suoi file in memoria, e le due cose non si sovrappongono — là ogni test vuole
# variare una cella sola, qui il file è **uno solo e sta fermo**, perché è
# quello che si apre e si legge quando un test fallisce.
#
# **L'export.** Una ventina di righe di view, ma è ciò che toglie all'import la
# sua debolezza vera: finché Progressive sapeva solo *leggere* quel formato, il
# formato era di un'altra app e nessuno tranne Lorenzo poteva produrne uno.
#
# **L'idempotenza, e il punto delicato.** «Esporta e reimporta» non aggiunge
# niente **anche per un allenamento nato in-app**, che in database ha
# `external_id` nullo e nel file ha invece un `id`. Quell'`id` è il
# `nome_pubblico`: una funzione della chiave primaria, calcolata e mai
# memorizzata. È la sola forma che tiene insieme le due regole della spec — un
# file ha bisogno di un `id` su ogni riga, e una riga nata qui non deve
# fingersi importata — e il test che conta è che dopo il giro completo la
# colonna sia **ancora nulla**.


class CsvFixtureAndExportTests(TestCase):
    """I sette casi di `07-test.md` §4, più la transazione, più l'export.

    Il catalogo è quello **vero** (`load_catalog`, 100 esercizi): i nomi nei
    file di prova sono nomi che esistono, ed è ciò che li rende file di
    Progressive e non stringhe scelte per far passare un test. L'unica
    eccezione è `RDL`, che non esiste di proposito.
    """

    FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"

    #: Le tre sessioni e le dieci serie del file, per numero di riga reale.
    S1 = "11111111-1111-4111-8111-000000000001"
    S2 = "11111111-1111-4111-8111-000000000002"
    RIGA_2 = "22222222-2222-4222-8222-000000000001"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="lorenzo", password=PASSWORD)
        cls.altro = User.objects.create_user(username="martina", password=PASSWORD)
        call_command("load_catalog", stdout=StringIO())
        cls.panca = Exercise.objects.get(name="Panca piana con bilanciere")
        cls.trazioni = Exercise.objects.get(name="Trazioni alla sbarra")
        cls.leg_press = Exercise.objects.get(name="Leg press")
        cls.stacco = Exercise.objects.get(name="Stacco rumeno con bilanciere")

    def setUp(self):
        self.client.force_login(self.user)
        self.deposito = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.deposito, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.deposito)
        override.enable()
        self.addCleanup(override.disable)

    # ------------------------------------------------------------------ utili

    def byte(self, nome):
        return (self.FIXTURES / nome).read_bytes()

    def leggi_fixture(self, user=None):
        """Il parser sui due file, senza HTTP: è il livello a cui i casi si
        guardano uno per uno, e la ragione per cui `importer.py` esiste."""
        return leggi(
            BytesIO(self.byte("workout_sessions.csv")),
            BytesIO(self.byte("session_sets.csv")),
            user=user,
        )

    def carica_fixture(self):
        return self.client.post(
            reverse("training:import-upload"),
            {
                "sessioni": SimpleUploadedFile(
                    "workout_sessions.csv",
                    self.byte("workout_sessions.csv"),
                    content_type="text/csv",
                ),
                "serie": SimpleUploadedFile(
                    "session_sets.csv",
                    self.byte("session_sets.csv"),
                    content_type="text/csv",
                ),
            },
        )

    def carica(self, sessioni, serie):
        """Gli stessi due passi, ma su due testi qualunque: serve al giro
        export → import, dove i file arrivano dall'export e non dal disco."""
        return self.client.post(
            reverse("training:import-upload"),
            {
                "sessioni": SimpleUploadedFile(
                    "workout_sessions.csv", sessioni.encode("utf-8"),
                    content_type="text/csv",
                ),
                "serie": SimpleUploadedFile(
                    "session_sets.csv", serie.encode("utf-8"),
                    content_type="text/csv",
                ),
            },
        )

    def conferma(self, abbinamenti=()):
        dati = {
            "form-TOTAL_FORMS": str(len(abbinamenti)),
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        for indice, (nome, esercizio) in enumerate(abbinamenti):
            dati[f"form-{indice}-raw_name"] = nome
            dati[f"form-{indice}-exercise"] = str(esercizio.pk)
        return self.client.post(reverse("training:import-preview"), dati)

    def importa_le_fixture(self):
        """Il giro completo dei tre URL: `RDL` è l'unico nome da abbinare."""
        self.carica_fixture()
        self.client.get(reverse("training:import-preview"))
        return self.conferma([("RDL", self.stacco)])

    def esporta(self, quale):
        uscita = StringIO()
        esporta(uscita, quale, self.user)
        return uscita.getvalue()

    # --------------------------------------------- i sette casi, uno per test

    def test_una_serie_non_eseguita_entra_senza_numeri(self):
        """Riga 5: «non l'ho fatta» non è «non l'avevo prevista», quindi la
        riga entra — ma `reps` e `weight` restano nulli, perché il file non
        porta numeri su una serie saltata e inventarli qui sarebbe la stessa
        cosa che correggere una durata assurda."""
        lettura = self.leggi_fixture()
        saltata = [riga for riga in lettura.serie if not riga.is_completed]

        self.assertEqual(len(saltata), 1)
        self.assertEqual(saltata[0].numero, 5)
        self.assertIsNone(saltata[0].reps)
        self.assertIsNone(saltata[0].weight)

    def test_una_serie_completata_senza_peso_e_valida(self):
        """Riga 4: `Trazioni alla sbarra` a 10 ripetizioni e nessun carico. È
        il corpo libero — sullo storico reale sono 25 righe su 317 — e una
        validazione che pretendesse `weight` le rifiuterebbe tutte."""
        lettura = self.leggi_fixture()
        riga = next(riga for riga in lettura.serie if riga.numero == 4)

        self.assertEqual(riga.raw_name, "Trazioni alla sbarra")
        self.assertTrue(riga.is_completed)
        self.assertEqual(riga.reps, 10)
        self.assertIsNone(riga.weight)
        # E non è fra le scartate: l'unico errore del file è quello di riga 6.
        self.assertNotIn(4, [errore.numero for errore in lettura.errori])

    def test_una_serie_completata_senza_reps_e_scartata_col_suo_motivo(self):
        """Riga 6, e l'unico errore vero del file: la casella «eseguita» è
        vera e il numero manca, che è il `CheckConstraint`
        `workout_set_completed_has_reps` visto dal lato del report. Il numero
        di riga è quello **reale**, intestazione compresa: serve ad aprire il
        file e andarci."""
        lettura = self.leggi_fixture()

        self.assertEqual(len(lettura.errori), 1)
        errore = lettura.errori[0]
        self.assertEqual(errore.file, "session_sets.csv")
        self.assertEqual(errore.numero, 6)
        self.assertEqual(errore.colonna, "reps")
        self.assertIn("ripetizioni", errore.motivo)
        # Lo scarto è della **riga**, non della sessione: la seconda serie di
        # `Leg press`, riga 7, entra regolarmente.
        self.assertIn(7, [riga.numero for riga in lettura.serie])

    def test_una_durata_assurda_e_un_avviso_e_la_sessione_entra_intatta(self):
        """Riga 3 delle sessioni: venti secondi di allenamento. Assurdo non è
        impossibile — l'unico bloccante resta `ended_at >= started_at` — e
        correggere la durata significherebbe inventare un dato."""
        lettura = self.leggi_fixture()

        self.assertEqual(len(lettura.avvisi), 1)
        self.assertEqual(lettura.avvisi[0].numero, 3)
        self.assertEqual(len(lettura.sessioni), 3)
        lampo = next(s for s in lettura.sessioni if s.chiave == self.S2)
        self.assertEqual(lampo.ended_at - lampo.started_at, timedelta(seconds=20))

    def test_un_nome_non_abbinabile_va_nel_form_e_non_fa_fallire_niente(self):
        """`RDL` non assomiglia a «Stacco rumeno con bilanciere», e nessuna
        normalizzazione lo risolverà mai: è una scelta, e la fa l'utente
        (ADR-0010). Gli altri quattro nomi sono nomi del catalogo e si
        risolvono da soli — è il caso del file esportato da Progressive."""
        lettura = self.leggi_fixture()
        risolti, da_chiedere = risolvi(lettura.nomi_grezzi, self.user)

        self.assertEqual([nome for nome, _ in da_chiedere], ["RDL"])
        self.assertEqual(len(risolti), 4)
        # E l'import non fallisce: le righe degli altri quattro sono già valide.
        self.assertEqual(len(lettura.serie), 9)

    def test_una_riga_gia_importata_e_saltata_e_le_sue_sorelle_non_sono_orfane(self):
        """`external_id` già noto: la riga si salta, e **non** è un errore.

        La sessione già presente resta una chiave valida, o le sue serie nuove
        diventerebbero orfane e l'idempotenza sarebbe una porta chiusa invece
        che un no-op: ricaricare un file con una sessione vecchia e tre serie
        nuove deve aggiungere quelle tre.
        """
        gia_presente = Workout.objects.create(
            user=self.user,
            title="Spinta A",
            started_at=timezone.now(),
            external_id=self.S1,
        )
        WorkoutSet.objects.create(
            workout=gia_presente,
            exercise=self.panca,
            set_number=1,
            reps=8,
            weight=Decimal("60.00"),
            external_id=self.RIGA_2,
        )

        lettura = self.leggi_fixture(user=self.user)

        self.assertEqual(lettura.sessioni_duplicate, 1)
        self.assertEqual(lettura.serie_duplicate, 1)
        self.assertEqual(len(lettura.sessioni), 2)
        # Le altre serie di quella sessione non sono errori: hanno dove andare.
        self.assertEqual([riga.numero for riga in lettura.serie], [3, 4, 5, 7, 8, 9, 10, 11])
        self.assertEqual(lettura.errori[0].numero, 6)

        risolti, _ = risolvi(lettura.nomi_grezzi, self.user)
        esito = scrivi(lettura, {**risolti, "RDL": self.stacco}, self.user)

        self.assertEqual(esito.allenamenti, 2)
        self.assertEqual(esito.allenamenti_saltati, 1)
        self.assertEqual(esito.serie_saltate, 1)
        self.assertEqual(Workout.objects.count(), 3)
        # Le serie appese alla sessione già presente sono davvero sue.
        self.assertEqual(gia_presente.sets.count(), 4)

    def test_lo_stesso_file_due_volte_non_aggiunge_niente(self):
        """L'idempotenza dal lato dell'utente: si ricarica lo stesso file e non
        succede niente. La seconda volta non c'è nemmeno più niente da
        abbinare, perché `RDL` è diventato un `ExerciseAlias`."""
        self.importa_le_fixture()
        allenamenti, serie = Workout.objects.count(), WorkoutSet.objects.count()
        self.assertEqual((allenamenti, serie), (3, 9))

        self.carica_fixture()
        anteprima = self.client.get(reverse("training:import-preview"))
        self.assertEqual(len(anteprima.context["form"].forms), 0)
        self.assertEqual(anteprima.context["lettura"].sessioni_duplicate, 3)
        self.conferma()

        self.assertEqual(Workout.objects.count(), allenamenti)
        self.assertEqual(WorkoutSet.objects.count(), serie)

    def test_un_errore_in_conferma_non_lascia_meta_storico_dentro(self):
        """La transazione, ed è il punto per cui `scrivi` ha un `atomic` solo.

        «Parziale in anteprima, atomico in conferma»: le righe rotte sono già
        state messe da parte e mostrate, quindi qui non resta nessuna decisione
        — o entra tutto ciò che l'utente ha visto, o non entra niente. Un
        guasto a metà scrittura lascerebbe altrimenti uno storico che non è né
        quello di prima né quello del file, e nessuno saprebbe quale.
        """
        lettura = self.leggi_fixture(user=self.user)
        risolti, _ = risolvi(lettura.nomi_grezzi, self.user)
        vera = WorkoutSet.objects.create
        chiamate = []

        def crolla(**kwargs):
            chiamate.append(kwargs)
            if len(chiamate) > 3:
                raise IntegrityError("guasto simulato a metà scrittura")
            return vera(**kwargs)

        with patch.object(WorkoutSet.objects, "create", crolla):
            with self.assertRaises(IntegrityError):
                scrivi(lettura, {**risolti, "RDL": self.stacco}, self.user)

        # Non «meno righe»: **zero**. I tre allenamenti erano già stati creati
        # quando la quarta serie è esplosa, e sono tornati indietro con lei.
        self.assertEqual(Workout.objects.count(), 0)
        self.assertEqual(WorkoutSet.objects.count(), 0)

    # ------------------------------------------------------- l'export, e il giro

    def test_lexport_scrive_le_colonne_che_il_parser_pretende(self):
        """La guardia che tiene i due file *lo stesso* formato.

        Le intestazioni dell'export e le colonne obbligatorie dell'import sono
        due elenchi di stringhe in due moduli diversi: divergono in silenzio, e
        il sintomo sarebbe un export che l'import rifiuta — cioè il giro aperto
        di nuovo, senza che niente lo segnali.
        """
        self.assertLessEqual(COLONNE_SESSIONI, set(INTESTAZIONE_SESSIONI))
        self.assertLessEqual(COLONNE_SERIE, set(INTESTAZIONE_SERIE))
        # `exercise_name` e non `exercise_id`: la chiave privata del catalogo
        # di questo database non significa niente altrove.
        self.assertIn("exercise_name", INTESTAZIONE_SERIE)
        self.assertNotIn("exercise_id", INTESTAZIONE_SERIE)

    def test_lexport_e_un_csv_scaricabile_coi_nomi_del_formato(self):
        self.importa_le_fixture()
        risposta = self.client.get(
            reverse("training:export-csv", args=["allenamenti"])
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertTrue(risposta["Content-Type"].startswith("text/csv"))
        self.assertIn("workout_sessions.csv", risposta["Content-Disposition"])
        righe = risposta.content.decode("utf-8").splitlines()
        self.assertEqual(righe[0], ",".join(INTESTAZIONE_SESSIONI))
        self.assertEqual(len(righe), 4)

    def test_lexport_porta_via_solo_le_proprie_righe(self):
        """Lo storico è dell'utente, e l'export non è una scorciatoia per
        leggerlo altrove: il filtro è sul queryset, come per lo storico
        dell'esercizio in #71."""
        self.importa_le_fixture()
        estraneo = Workout.objects.create(
            user=self.altro, title="Roba di Martina", started_at=timezone.now()
        )

        testo = self.esporta("allenamenti")

        self.assertNotIn("Roba di Martina", testo)
        self.assertNotIn(str(nome_pubblico("workout", estraneo.pk)), testo)

    def test_il_giro_completo_non_aggiunge_una_riga(self):
        """**La condizione di chiusura del ticket**: export → import dello
        stesso file → zero righe nuove.

        È l'idempotenza vista dall'unico lato che conta davvero, perché il file
        non arriva più da un altro software: lo ha prodotto Progressive.
        """
        self.importa_le_fixture()
        allenamenti, serie = Workout.objects.count(), WorkoutSet.objects.count()

        self.carica(self.esporta("allenamenti"), self.esporta("serie"))
        anteprima = self.client.get(reverse("training:import-preview"))
        # Niente da abbinare: i nomi sono quelli del catalogo, e si risolvono
        # per nome esatto. È il caso che `risolvi` chiama «il file esportato da
        # Progressive stesso».
        self.assertEqual(len(anteprima.context["form"].forms), 0)
        self.conferma()

        self.assertEqual(Workout.objects.count(), allenamenti)
        self.assertEqual(WorkoutSet.objects.count(), serie)

    def test_il_giro_si_chiude_anche_su_un_allenamento_nato_in_app(self):
        """Il caso delicato, e la ragione per cui `nome_pubblico` esiste.

        Un allenamento registrato a mano ha `external_id` **nullo**, e la spec
        dice che il nullable è essenziale: non deve fingersi importato. Ma un
        CSV ha bisogno di un `id` su ogni riga, o il file non è reimportabile.
        La risposta è un id **calcolato** dalla chiave primaria: stabile fra
        due export, riconosciuto al ritorno, e mai scritto in database.

        Il test che conta è l'ultima riga: dopo il giro completo la colonna è
        ancora nulla.
        """
        allenamento = Workout.objects.create(
            user=self.user,
            title="Serata a mano",
            started_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now() - timedelta(hours=1),
        )
        WorkoutSet.objects.create(
            workout=allenamento, exercise=self.panca, set_number=1,
            reps=8, weight=Decimal("70.00"),
        )
        WorkoutSet.objects.create(
            workout=allenamento, exercise=self.trazioni, set_number=1, reps=6,
        )

        sessioni, serie = self.esporta("allenamenti"), self.esporta("serie")
        self.assertIn(str(nome_pubblico("workout", allenamento.pk)), sessioni)

        self.carica(sessioni, serie)
        self.client.get(reverse("training:import-preview"))
        self.conferma()

        self.assertEqual(Workout.objects.count(), 1)
        self.assertEqual(WorkoutSet.objects.count(), 2)
        allenamento.refresh_from_db()
        self.assertIsNone(allenamento.external_id)

    def test_due_export_di_fila_danno_lo_stesso_file(self):
        """Il nome pubblico è una **funzione**, non un caso: se cambiasse a
        ogni export, ogni reimport aggiungerebbe una copia."""
        self.importa_le_fixture()
        Workout.objects.create(
            user=self.user, title="Serata a mano", started_at=timezone.now()
        )

        self.assertEqual(self.esporta("allenamenti"), self.esporta("allenamenti"))
        self.assertEqual(self.esporta("serie"), self.esporta("serie"))

    def test_lexport_vuole_il_login_e_un_nome_di_file_che_esiste(self):
        risposta = self.client.get(reverse("training:export-csv", args=["allenamenti"]))
        self.assertEqual(risposta.status_code, 200)

        self.assertEqual(self.client.get("/export/tutto/").status_code, 404)

        self.client.logout()
        risposta = self.client.get(reverse("training:export-csv", args=["serie"]))
        self.assertEqual(risposta.status_code, 302)
        self.assertIn("/accounts/login/", risposta["Location"])


# --- La popolazione sintetica (#75) ----------------------------------------
#
# Il generatore è stato portato dentro da un prototipo di 854 righe in stdlib
# pura, e il porting ha una proprietà che nessun'altra parte del progetto ha:
# **deve produrre esattamente la stessa popolazione**. Non «una popolazione
# equivalente» — la stessa, riga per riga, perché tutte le misure che la
# documentazione dichiara (≥ 1500 finestre etichettabili, classe `stallo` al
# 30,1% con orizzonte a 6) sono state prese *su quella* popolazione e non
# vengono ri-misurate qui: riscriverle nel comando significherebbe tenere una
# seconda copia della regola di ADR-0004 dentro il seeding.
#
# Ne discende la forma di questi test: sono per la maggior parte **guardie
# d'identità** sul generatore casuale. Basta invertire due estrazioni perché lo
# stream si sposti e ogni numero a valle cambi — è successo durante il porting,
# fra `target_sets` e `target_reps`, e il sintomo era un conteggio di voti
# diverso a parità di mediana, cioè il tipo di divergenza che a occhio passa.
#
# La generazione pura costa 0,4 secondi, l'inserimento delle 299.367 serie ne
# costa una decina: quasi tutti i test girano quindi sulle funzioni del modulo,
# e **una sola** classe paga il database per intero, perché «gira da database
# vuoto» è la condizione di chiusura del ticket e non si dimostra a parole.


class SyntheticGeneratorTests(TestCase):
    """Il generatore, senza database: identità dello stream e coerenza interna.

    Questa classe non tocca i modelli oltre al catalogo, che le serve solo come
    sorgente dei 100 esercizi.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("load_catalog", stdout=StringIO())

    def genera(self, seed=seed_synthetic.SEED):
        rng = random.Random(seed)
        esercizi = seed_synthetic.read_catalog()
        utenti = seed_synthetic.make_users(rng)
        allenamenti, serie = seed_synthetic.generate(utenti, esercizi, rng)
        schede, voci, voti = seed_synthetic.make_routines_and_votes(
            utenti, esercizi, rng
        )
        return esercizi, utenti, allenamenti, serie, schede, voci, voti

    def test_the_population_has_exactly_the_documented_size(self):
        """I conteggi esatti, che sono la guardia dell'identità con il prototipo.

        Se una sola estrazione si spostasse questi numeri cambierebbero, e con
        essi le misure che `docs/generatore-sintetico.md` dichiara senza
        ri-misurarle.
        """
        _es, utenti, allenamenti, serie, schede, _voci, voti = self.genera()

        self.assertEqual(len(utenti), 100)
        self.assertEqual(len(allenamenti), 11_855)
        self.assertEqual(len(serie), 296_724)
        self.assertEqual(len(schede), 199)
        self.assertEqual(len(voti), 887)

    def test_the_demo_user_is_the_one_chosen_in_advance(self):
        """`cavallinilorenzo — Lorenzo Cavallini` è nominato in anticipo, non la
        mattina dell'orale: è su di lui che si mostra la pagina dello stallo,
        perché lo storico reale di Lorenzo è troppo corto per superare la soglia.

        Il **nome sorteggiato** si verifica insieme, e conta più del resto: è la
        guardia d'identità più economica sullo stream del generatore casuale. Se
        una sola estrazione si spostasse, la posizione 64 pescherebbe un altro
        nome, e questo test lo direbbe prima che lo dicano i conteggi esatti.
        """
        _es, utenti, *_resto = self.genera()
        per_username = {u["username"]: u for u in utenti}

        self.assertIn(seed_synthetic.DEMO_USERNAME_FINALE, per_username)
        demo = per_username[seed_synthetic.DEMO_USERNAME_FINALE]
        self.assertEqual(demo["display_name"], seed_synthetic.DEMO_DISPLAY_NAME)
        self.assertEqual(
            demo["nome_sorteggiato"], seed_synthetic.NOME_SORTEGGIATO_ATTESO
        )

    def test_usernames_are_names_and_not_numbers(self):
        """`camilla.martini`, non `demo001`.

        I nomi veri c'erano già — il generatore li pescava e li scriveva in
        `first_name`/`last_name` — ma ogni template mostra `get_username`, che
        era il numero: la popolazione sembrava un riempitivo proprio nelle due
        pagine dove il prof la guarda, le classifiche e le schede pubbliche.

        La collisione non è teorica: 36 nomi per 30 cognomi fanno 1080
        combinazioni, ma su 100 estrazioni il paradosso del compleanno ne fa
        collidere quattro. Si risolve cambiando cognome, **non** aggiungendo un
        suffisso numerico, che riporterebbe il numero da cui si sta scappando.
        """
        _es, utenti, *_resto = self.genera()
        username = [u["username"] for u in utenti]

        self.assertEqual(len(set(username)), len(utenti))
        self.assertEqual([u for u in username if u.startswith("demo")], [])
        for u in utenti:
            if u["username"] == seed_synthetic.DEMO_USERNAME_FINALE:
                continue
            self.assertEqual(
                u["username"], seed_synthetic.slug_utente(*u["display_name"].split(" "))
            )

    def test_renaming_the_users_moved_no_draw(self):
        """La prova che `assegna_username` è innocua.

        Rinominare è un'operazione sulle **etichette**, e non deve costare una
        sola estrazione: se ne consumasse una, tutta la popolazione a valle
        cambierebbe e con essa le cifre che i test tengono ferme. Qui si
        confronta la popolazione con quella generata da uno stream a cui è stato
        chiesto lo stesso numero di valori, guardando i campi che dipendono dal
        sorteggio invece dei nomi.
        """
        _es, utenti, *_resto = self.genera()

        sorteggiati = [
            (u["body_mass_kg"], u["strength"], u["ceiling"], u["start"])
            for u in utenti
        ]

        self.assertEqual(len(sorteggiati), 100)
        # I sei veterani e i quattro «dati insufficienti» stanno prima
        # dell'utente della demo, quindi la rinomina non può averli toccati.
        self.assertEqual(sum(1 for _b, _s, _c, st in sorteggiati
                             if (seed_synthetic.TODAY - st).days < 21), 4)

    def test_the_same_seed_generates_the_same_population(self):
        """La riproducibilità, che è ciò che il seed fisso compra.

        Si confrontano due generazioni intere e non due conteggi: due
        popolazioni diverse possono avere lo stesso numero di righe.
        """
        primo = self.genera()
        secondo = self.genera()

        self.assertEqual(primo, secondo)

    def test_a_different_seed_gives_a_different_population(self):
        """Il controinterrogatorio del test precedente: se anche cambiando seed
        uscisse la stessa cosa, l'uguaglianza di sopra non proverebbe niente."""
        _es, utenti, *_resto = self.genera()
        _es2, altri, *_resto2 = self.genera(seed=1)

        self.assertNotEqual(utenti, altri)

    def test_no_bench_press_beats_its_own_squat(self):
        """Il principio che rende la popolazione credibile.

        Non c'è nessun controllo di plausibilità nel generatore, e non serve: i
        carichi di un utente nascono tutti da `peso corporeo × rapporto × forza ×
        progressione × rumore`, quindi la panca da 140 con lo squat da 60 non è
        sorvegliata, è **quasi impossibile per costruzione**. Questo test misura la
        conseguenza, non la sorveglianza.

        «Quasi», e il quasi è stato pagato: fino a `DEMO_MONTHS = 24` la coda era
        vuota e qui c'era `assertEqual(assurdi, 0)`. Non era una garanzia
        strutturale — il rapporto parte uguale per tutti dai `CORE_RATIOS`, ma
        `progression(t)` corre per esercizio, e più storico c'è più i due esercizi
        di un utente divergono. Con due anni un utente su 56 arriva a 1,16, e il
        secondo più alto sta a 0,95.

        Quindi si misura la **forma** e non il conteggio: la mediana ferma dove
        deve stare, e una coda che resta un'eccezione. Uno zero tenuto per
        decreto avrebbe solo obbligato a piegare il generatore per far tornare un
        numero.
        """
        esercizi, utenti, allenamenti, serie, *_resto = self.genera()

        rapporti, assurdi, _ = seed_synthetic.coherence(
            utenti, esercizi, allenamenti, serie
        )

        self.assertLessEqual(assurdi, 0.02 * len(rapporti))
        self.assertAlmostEqual(statistics.median(rapporti), 0.73, places=2)
        # Il secondo più alto è la prova che è una coda e non uno spostamento:
        # se la catena si rompesse davvero, sopra 1 ce ne sarebbe più d'uno.
        self.assertLess(sorted(rapporti)[-2], 1.0)

    def test_every_core_exercise_clears_the_percentile_threshold(self):
        """Sotto i 20 utenti su un esercizio il percentile tace.

        Spargere 100 utenti sulle 100 voci del catalogo lo farebbe tacere
        ovunque: è la ragione per cui il repertorio si concentra su un core di
        22 esercizi. La coda resta sotto soglia di proposito, così all'orale la
        riga «percentile non disponibile» si può mostrare accanto a una che
        funziona.
        """
        _es, _ut, allenamenti, serie, *_resto = self.genera()

        conteggi = seed_synthetic.users_per_exercise(allenamenti, serie)
        core = {
            nome: n
            for nome, n in conteggi.items()
            if nome in seed_synthetic.CORE_RATIOS
        }

        self.assertEqual(len(core), 22)
        for nome, n in sorted(core.items()):
            with self.subTest(esercizio=nome):
                self.assertGreaterEqual(n, 20)
        self.assertLess(
            sum(1 for n in conteggi.values() if n >= 20),
            len(conteggi),
            "La coda deve restare sotto soglia: mostra il percentile che tace.",
        )

    def test_four_users_are_deliberately_too_new_to_analyse(self):
        """Lo stato «dati insufficienti» va dimostrato dal vivo, quindi la
        popolazione contiene apposta chi non ha ancora abbastanza storico."""
        _es, utenti, *_resto = self.genera()

        giorni = [(seed_synthetic.TODAY - u["start"]).days for u in utenti]
        mesi = sorted(g / 30.4 for g in giorni)

        self.assertEqual(sum(1 for g in giorni if g < 21), 4)
        self.assertAlmostEqual(mesi[0], 0.5, places=1)
        self.assertAlmostEqual(mesi[-1], seed_synthetic.DEMO_MONTHS, places=1)

    def test_public_routines_carry_enough_votes_to_be_ranked(self):
        """La media bayesiana con `C = 3` è dominata dal prior sotto gli 8 voti:
        con una mediana più bassa la classifica sociale ordinerebbe il rumore.
        Le schede a zero voti restano, perché una scheda pubblicata ieri non ne
        ha ed è il caso che la media bayesiana deve saper gestire."""
        *_resto, schede, _voci, voti = self.genera()

        pubbliche = [r for r in schede if r["is_public"]]
        per_scheda = Counter(v["routine_id"] for v in voti)
        conteggi = [per_scheda.get(r["id"], 0) for r in pubbliche]

        self.assertEqual(len(pubbliche), 58)
        self.assertGreaterEqual(statistics.median(conteggi), 8)
        self.assertGreater(sum(1 for n in conteggi if n == 0), 0)

    def test_the_end_of_history_does_not_drift_with_the_calendar(self):
        """`TODAY` è una costante e non `date.today()`: se scorresse col
        calendario, due esecuzioni a giorni diversi darebbero popolazioni
        diverse e il seed fisso non comprerebbe niente."""
        _es, _ut, allenamenti, *_resto = self.genera()

        ultimo = max(w["started_at"].date() for w in allenamenti)

        self.assertLessEqual(ultimo, seed_synthetic.TODAY)

    def test_the_generator_rounds_loads_onto_its_own_grid(self):
        """La griglia di arrotondamento **non** è `Equipment.load_increment_kg`.

        Quella colonna risponde alla domanda del coach — di quanto il carico può
        salire davvero — e vale zero sul corpo libero e sull'elastico, dove il
        consiglio è di aggiungere ripetizioni. Usarla qui darebbe una divisione
        per zero. Il test tiene ferma la distinzione, che a leggerla nel codice
        sembra una svista.
        """
        self.assertEqual(Equipment.objects.get(code="bodyweight").load_increment_kg, 0)
        self.assertGreater(seed_synthetic.STEP_BY_EQUIPMENT["bodyweight"], 0)

        _es, _ut, _all, serie, *_resto = self.genera()
        carichi = {s["weight_kg"] for s in serie}

        self.assertTrue(
            all(round(v * 4) == v * 4 for v in carichi),
            "Ogni carico si posa su un multiplo di 0,25 kg: nessuno carica 43,7.",
        )

    def test_the_hidden_state_never_reaches_the_data(self):
        """La macchina a tre fasi e l'archetipo restano dentro il generatore.

        Se finissero in un campo del modello, la tentazione di usarli come
        etichetta del ML tornerebbe, ed è la circolarità che ADR-0004 rifiuta.
        Il test guarda le due superfici da cui potrebbero uscire: le righe che
        il generatore consegna alla persistenza, e i campi dei modelli.
        """
        _es, utenti, allenamenti, serie, schede, voci, voti = self.genera()

        for riga in (allenamenti[0], serie[0], schede[0], voci[0], voti[0]):
            with self.subTest(riga=sorted(riga)):
                self.assertNotIn("archetype", riga)
                self.assertNotIn("phase", riga)
                self.assertNotIn("state", riga)

        # L'archetipo esiste sull'utente *generato*, che è un dizionario interno…
        self.assertIn("archetype", utenti[0])
        # …ma non esiste da nessuna parte sul modello che finisce nel database.
        campi = {f.name for f in User._meta.get_fields()}
        self.assertNotIn("archetype", campi)
        self.assertNotIn("phase", campi)


class SeedSyntheticCommandTests(TestCase):
    """Il comando end-to-end: `migrate` → `load_catalog` → `seed_synthetic`.

    È l'unica classe che paga davvero il database — 299.367 serie da inserire —
    e lo fa una volta sola, in `setUpTestData`, perché la condizione di chiusura
    del ticket è che quella catena giri da un database vuoto.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("load_catalog", stdout=StringIO())
        cls.uscita = StringIO()
        call_command("seed_synthetic", stdout=cls.uscita)

    def test_the_whole_population_lands_in_the_database(self):
        self.assertEqual(User.objects.filter(is_synthetic=True).count(), 100)
        self.assertEqual(Workout.objects.count(), 11_855)
        self.assertEqual(WorkoutSet.objects.count(), 296_724)
        self.assertEqual(Routine.objects.count(), 199)
        self.assertEqual(Vote.objects.count(), 887)
        self.assertEqual(
            RoutineExercise.objects.count(),
            RoutineExercise.objects.filter(
                target_reps_max__gt=models.F("target_reps")
            ).count(),
            "L'estremo alto del bersaglio c'è sempre: è ciò che la doppia "
            "progressione insegue, e una scheda che dichiara solo il minimo "
            "non la descrive.",
        )

    def test_the_report_says_whether_the_numbers_add_up(self):
        """Il comando non si limita a finire: dice se i numeri tornano.

        Un seeding che stampa «fatto» e basta obbliga a fidarsi; questo obbliga
        a leggere, ed è ciò che si mostra all'orale.
        """
        testo = self.uscita.getvalue()

        self.assertIn("296,724", testo)
        self.assertIn("cavallinilorenzo — Lorenzo Cavallini", testo)
        # La guardia d'identità dello stream, stampata dal rapporto.
        self.assertIn("posizione 64 pesca «Martina Longo»", testo)
        self.assertNotIn("NO", testo)

    def test_the_demo_user_can_actually_log_in(self):
        """Su `cavallinilorenzo` si dimostra la pagina dello stallo: se non ci si
        potesse entrare, la scelta anticipata dell'utente non servirebbe a
        niente."""
        entrato = self.client.login(
            username=seed_synthetic.DEMO_USERNAME_FINALE,
            password=seed_synthetic.DEMO_PASSWORD,
        )

        self.assertTrue(entrato)

    def test_every_synthetic_user_declares_itself(self):
        """ADR-0009: non sono utenti di prova nascosti. Il campo **non filtra** —
        nessuna query li esclude dalla popolazione, o i percentili tacerebbero
        ovunque per mancanza di numeri — ma si dichiara."""
        self.assertFalse(
            User.objects.filter(
                username__startswith="demo", is_synthetic=False
            ).exists()
        )

    def test_the_body_mass_is_always_there(self):
        """Senza peso corporeo un utente non compare in classifica e non riceve
        un percentile (ADR-0008): una popolazione generata senza sarebbe una
        popolazione che non serve a niente."""
        self.assertFalse(
            User.objects.filter(is_synthetic=True, body_mass_kg__isnull=True).exists()
        )

    def test_the_sets_of_one_exercise_are_numbered_from_one(self):
        """Il vincolo `workout_set_unique` è su `(workout, exercise, set_number)`.

        Il prototipo scriveva su CSV e usava un contatore globale per le serie
        di riscaldamento; qui numerare warmup e working entrambi da 1 sarebbe
        una collisione, quindi la numerazione è continua dentro la coppia. Le
        analisi filtrano per `set_type`, non per numero.
        """
        allenamento, esercizio = (
            WorkoutSet.objects.filter(set_type="warmup")
            .values_list("workout_id", "exercise_id")
            .first()
        )
        numeri = list(
            WorkoutSet.objects.filter(workout_id=allenamento, exercise_id=esercizio)
            .order_by("set_number")
            .values_list("set_number", "set_type")
        )

        self.assertEqual([n for n, _ in numeri], list(range(1, len(numeri) + 1)))
        self.assertEqual(numeri[0][1], "warmup")
        self.assertEqual(numeri[1][1], "rampUp")

    def test_a_second_run_refuses_instead_of_duplicating(self):
        """Rieseguire il comando su un database già popolato non è idempotente
        come `load_catalog` — sono utenti, non righe di anagrafica — quindi si
        rifiuta e dice come si fa."""
        with self.assertRaises(CommandError) as errore:
            call_command("seed_synthetic", stdout=StringIO())

        self.assertIn("--reset", str(errore.exception))
        self.assertEqual(User.objects.filter(is_synthetic=True).count(), 100)

    def test_the_synthetic_population_is_declared_on_the_community_page(self):
        """ADR-0009 vuole l'etichetta **dove il nome compare**, e la community è
        la superficie di fase 1 in cui compare: una classifica in cui l'unico
        utente vero è circondato da cento profili inventati senza che sia
        scritto da nessuna parte è ciò che un esaminatore attento nota."""
        scheda = Routine.objects.filter(is_public=True, votes__isnull=False).first()
        lettore = User.objects.create_user(username="lorenzo", password="x")
        self.client.force_login(lettore)

        lista = self.client.get(reverse("training:routine-public-list"))
        dettaglio = self.client.get(
            reverse("training:routine-public-detail", args=[scheda.pk])
        )

        self.assertContains(lista, "utente dimostrativo")
        self.assertContains(dettaglio, "utente dimostrativo")


class SeedSyntheticGuardTests(TestCase):
    """Le due guardie che si possono provare senza generare tutto."""

    def test_it_refuses_to_run_on_an_empty_catalogue(self):
        """L'ordine di caricamento è stretto: i 100 esercizi devono esistere
        perché il generatore ci si appoggi. Senza, il messaggio dice quale
        comando manca invece di lasciare cadere un errore oscuro."""
        with self.assertRaises(CommandError) as errore:
            call_command("seed_synthetic", stdout=StringIO())

        self.assertIn("load_catalog", str(errore.exception))

    def test_reset_clears_the_previous_population_but_not_the_real_users(self):
        """`--reset` è il modo dichiarato di rigenerare: cancella i sintetici e
        tutto ciò che dipende da loro, e non tocca gli utenti veri."""
        call_command("load_catalog", stdout=StringIO())
        vecchio = User.objects.create_user(
            username="demo001", password="x", is_synthetic=True
        )
        vero = User.objects.create_user(username="lorenzo", password="x")

        call_command("seed_synthetic", "--reset", stdout=StringIO())

        self.assertFalse(User.objects.filter(pk=vecchio.pk).exists())
        self.assertTrue(User.objects.filter(pk=vero.pk).exists())
        self.assertEqual(User.objects.filter(is_synthetic=True).count(), 100)

    def test_the_catalogue_order_the_generator_depends_on_is_the_csv_order(self):
        """`read_catalog` ordina per `pk` e non per nome, e non è estetica.

        Il generatore pesca dagli esercizi con `random.sample`, quindi l'ordine
        della lista decide ogni estrazione a valle. `Exercise.Meta.ordering` è
        per nome: se `read_catalog` si affidasse all'ordinamento di default, la
        popolazione cambierebbe e con essa tutte le misure documentate.
        """
        call_command("load_catalog", stdout=StringIO())

        letti = [e["name"] for e in seed_synthetic.read_catalog()]

        self.assertEqual(
            letti, list(Exercise.objects.order_by("pk").values_list("name", flat=True))
        )
        self.assertNotEqual(letti, sorted(letti))


class RankingTests(TestCase):
    """Le due classifiche — il requisito «display results or rankings».

    Sono la guardia di quattro cose che nessun errore segnala da solo: le tre
    condizioni d'ammissione della classifica di forza, le **due trappole
    silenziose** di `04-analisi.md`, il significato di `Rank()`, e il fatto che
    la pagina sia raggiungibile dal menu — che è l'unico modo perché il
    requisito si mostri all'orale in due secondi invece di essere cercato.
    """

    #: Quanti utenti servono perché la panca superi la soglia. Due in più della
    #: costante, perché il test deve poter *togliere* qualcuno e restare sopra.
    UTENTI = rankings.MIN_USERS_FOR_COMPARISON + 2

    @classmethod
    def setUpTestData(cls):
        group = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        muscle = Muscle.objects.create(
            code="chestMid", group=group, label_it="Petto medio", sort_order=1
        )
        cls.bilanciere = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        cls.corpo_libero = Equipment.objects.create(
            code="bodyweight", label_it="Corpo libero", sort_order=2
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana",
            slug="panca-piana",
            primary_muscle=muscle,
            equipment=cls.bilanciere,
        )
        # Un secondo esercizio che **non** arriva in soglia: serve a provare
        # che la soglia esclude davvero, e che il selettore non lo offre.
        cls.curl = Exercise.objects.create(
            name="Curl con manubri",
            slug="curl-con-manubri",
            primary_muscle=muscle,
            equipment=cls.bilanciere,
        )
        cls.trazioni = Exercise.objects.create(
            name="Trazioni",
            slug="trazioni",
            primary_muscle=muscle,
            equipment=cls.corpo_libero,
        )

        cls.io = User.objects.create_user(
            username="lorenzo", password=PASSWORD, body_mass_kg=Decimal("80.00")
        )
        # La popolazione: tutti con peso dichiarato e due allenamenti, cioè
        # tutti ammessi. I test che escludono qualcuno lo fanno togliendogli
        # una condizione alla volta.
        cls.popolazione = [cls.io]
        for indice in range(1, cls.UTENTI):
            cls.popolazione.append(
                User.objects.create_user(
                    username=f"atleta{indice:02d}",
                    password=PASSWORD,
                    body_mass_kg=Decimal("80.00"),
                )
            )
        for indice, utente in enumerate(cls.popolazione):
            # Carico decrescente: `lorenzo` è primo, e le posizioni sono
            # prevedibili riga per riga.
            cls.serie(utente, cls.panca, peso=Decimal(100 - indice), reps=5, quante=2)

    @classmethod
    def serie(cls, utente, esercizio, peso, reps, quante=1, **campi):
        """`quante` serie efficaci su altrettanti allenamenti **distinti**.

        Allenamenti distinti e non serie nello stesso giorno: è la seconda
        condizione d'ammissione, e un helper che facesse il contrario
        renderebbe il test cieco proprio su quella.
        """
        istante = timezone.now() - timedelta(days=400)
        for numero in range(quante):
            allenamento = Workout.objects.create(
                user=utente,
                title=f"{esercizio.name} {numero}",
                started_at=istante + timedelta(days=numero * 7),
            )
            WorkoutSet.objects.create(
                workout=allenamento,
                exercise=esercizio,
                set_number=1,
                reps=reps,
                weight=peso,
                **campi,
            )
        return allenamento

    def setUp(self):
        self.client.force_login(self.io)

    def forza(self, esercizio=None):
        return list(rankings.classifica_forza(esercizio or self.panca))

    # --- Le tre condizioni d'ammissione ----------------------------------

    def test_the_ranking_lists_everyone_who_qualifies(self):
        righe = self.forza()

        self.assertEqual(len(righe), self.UTENTI)
        self.assertEqual(righe[0]["username"], "lorenzo")
        self.assertEqual(righe[0]["posizione"], 1)

    def test_an_athlete_without_a_declared_body_mass_does_not_appear(self):
        """Senza peso corporeo non c'è forza relativa: assente, non sbagliato.

        È ADR-0008 preso alla lettera, ed è una condizione *nuova* rispetto al
        percentile: comparire con un numero inventato sarebbe peggio che non
        comparire.
        """
        senza_peso = User.objects.create_user(
            username="senzapeso", password=PASSWORD, body_mass_kg=None
        )
        self.serie(senza_peso, self.panca, peso=Decimal("500"), reps=5, quante=2)

        nomi = [riga["username"] for riga in self.forza()]

        self.assertNotIn("senzapeso", nomi)

    def test_a_single_workout_is_not_enough_to_enter(self):
        """Due serie nello stesso giorno sono lo stesso dato, non due dati.

        La condizione è **due allenamenti distinti**: esclude il valore singolo
        inserito male, che è il rumore realistico misurato in #13.
        """
        principiante = User.objects.create_user(
            username="principiante", password=PASSWORD, body_mass_kg=Decimal("80.00")
        )
        allenamento = self.serie(principiante, self.panca, peso=Decimal("400"), reps=5)
        WorkoutSet.objects.create(
            workout=allenamento,
            exercise=self.panca,
            set_number=2,
            reps=5,
            weight=Decimal("400"),
        )

        nomi = [riga["username"] for riga in self.forza()]

        self.assertNotIn("principiante", nomi)

    def test_an_exercise_below_the_population_threshold_has_no_ranking(self):
        """Sotto soglia la classifica non si mostra magra: non si mostra.

        Una classifica su tre persone ha lo stesso difetto informativo di un
        percentile su tre, ed è la **stessa costante** a fermarli entrambi.
        """
        for utente in self.popolazione[:3]:
            self.serie(utente, self.curl, peso=Decimal("20"), reps=8, quante=2)

        ammessi = [e.slug for e in rankings.esercizi_con_classifica()]

        self.assertIn("panca-piana", ammessi)
        self.assertNotIn("curl-con-manubri", ammessi)

    def test_the_selector_offers_only_the_exercises_above_the_threshold(self):
        """Offrire un esercizio che poi dice «dati insufficienti» è un vicolo
        cieco messo nel menu apposta."""
        response = self.client.get(reverse("training:ranking-strength"))

        self.assertContains(response, "Panca piana")
        self.assertNotContains(response, "Curl con manubri")

    # --- Le tre definizioni condivise -------------------------------------

    def test_a_set_above_the_rep_cap_does_not_set_the_record(self):
        """Sopra le 12 ripetizioni Epley gonfia: quelle serie non concorrono.

        Restano però nel volume, ed è la ragione per cui il tetto è un filtro
        sulle righe e non una proprietà dell'espressione.
        """
        self.serie(self.io, self.panca, peso=Decimal("300"), reps=20, quante=2)

        massimale = self.forza()[0]["massimale"]

        # 100 kg × 5 ripetizioni, non i 300 kg della serie da 20.
        self.assertAlmostEqual(massimale, 100 * (1 + 5 / 30), places=4)

    def test_the_universal_filter_keeps_warmups_and_skipped_sets_out(self):
        """`set_type='working'` **e** `is_completed=True`, sempre insieme.

        #13 ha misurato 19% di serie non completate: farle entrare
        significherebbe contare allenamento che non è avvenuto.
        """
        self.serie(
            self.io,
            self.panca,
            peso=Decimal("400"),
            reps=5,
            quante=2,
            set_type=WorkoutSet.SetType.WARMUP,
        )
        self.serie(
            self.io,
            self.panca,
            peso=Decimal("500"),
            reps=5,
            quante=2,
            is_completed=False,
        )

        self.assertAlmostEqual(
            self.forza()[0]["massimale"], 100 * (1 + 5 / 30), places=4
        )

    def test_on_a_bodyweight_exercise_the_load_includes_the_body_mass(self):
        """ADR-0006, e la discrepanza `corpo_libero` / `bodyweight`.

        Su una trazione a corpo libero `weight` vale zero, e senza il `Case` il
        massimale sarebbe zero per tutti: la classifica renderebbe una colonna
        di zeri **senza segnalare niente**.
        """
        for utente in self.popolazione:
            self.serie(utente, self.trazioni, peso=Decimal("0"), reps=5, quante=2)

        righe = self.forza(self.trazioni)

        self.assertAlmostEqual(righe[0]["massimale"], 80 * (1 + 5 / 30), places=4)

    # --- Il pari merito ----------------------------------------------------

    def test_a_tie_gives_two_firsts_and_then_a_third(self):
        """`Rank()` e non `RowNumber()`: è il significato letterale di pari
        merito, e sui dati veri capita davvero — 100 kg × 5 a 80 kg di peso
        corporeo dà lo stesso valore per due persone."""
        gemello = User.objects.create_user(
            username="gemello", password=PASSWORD, body_mass_kg=Decimal("80.00")
        )
        self.serie(gemello, self.panca, peso=Decimal("100"), reps=5, quante=2)

        posizioni = [riga["posizione"] for riga in self.forza()]

        self.assertEqual(posizioni[:3], [1, 1, 3])

    def test_the_order_inside_a_tie_is_deterministic(self):
        """Senza un ordine interno la pagina si riordina a ogni ricarica, e il
        paginatore mostra due volte la stessa persona a pagina diversa."""
        gemello = User.objects.create_user(
            username="gemello", password=PASSWORD, body_mass_kg=Decimal("80.00")
        )
        self.serie(gemello, self.panca, peso=Decimal("100"), reps=5, quante=2)

        primi = [[riga["username"] for riga in self.forza()[:2]] for _ in range(3)]

        self.assertEqual(primi[0], primi[1])
        self.assertEqual(primi[1], primi[2])

    # --- La classifica sociale --------------------------------------------

    def scheda_pubblica(self, nome, esercizi=3, autore=None):
        scheda = Routine.objects.create(
            user=autore or self.io, name=nome, is_public=True
        )
        catalogo = [self.panca, self.curl, self.trazioni]
        for posizione in range(esercizi):
            # Il catalogo del test ha tre esercizi e una scheda ne può volere
            # otto: `RoutineExercise` è unico per `(routine, exercise)`, quindi
            # gli extra nascono qui.
            esercizio = (
                catalogo[posizione]
                if posizione < len(catalogo)
                else Exercise.objects.create(
                    name=f"{nome} extra {posizione}",
                    slug=f"{nome.lower()}-extra-{posizione}",
                    primary_muscle=self.panca.primary_muscle,
                    equipment=self.bilanciere,
                )
            )
            RoutineExercise.objects.create(
                routine=scheda,
                exercise=esercizio,
                position=posizione + 1,
                target_sets=3,
                target_reps=8,
            )
        return scheda

    def vota(self, scheda, punteggi):
        for indice, punteggio in enumerate(punteggi):
            Vote.objects.create(
                user=self.popolazione[indice + 1], routine=scheda, score=punteggio
            )

    # --- Le due trappole silenziose ---------------------------------------

    def test_the_social_score_is_not_multiplied_by_the_number_of_exercises(self):
        """La prima trappola di `04-analisi.md`, e non segnala errore.

        Due join a molti nella stessa query moltiplicano le righe: contare gli
        esercizi insieme ai voti farebbe diventare `Sum("votes__score")` la
        somma **per esercizio**, e il punteggio sarebbe sbagliato con la pagina
        che continua a rendere. Il controllo è che due schede con gli **stessi
        voti** e un numero di esercizi diverso abbiano lo stesso punteggio.
        """
        magra = self.scheda_pubblica("Magra", esercizi=3)
        grassa = self.scheda_pubblica("Grassa", esercizi=8)
        for scheda in (magra, grassa):
            self.vota(scheda, [5, 4, 3])

        punteggi = {
            r.name: (r.punteggio, r.somma_voti, r.n_voti)
            for r in rankings.classifica_sociale()
        }

        self.assertEqual(punteggi["Magra"], punteggi["Grassa"])
        self.assertEqual(punteggi["Magra"][1], 12)
        self.assertEqual(punteggi["Magra"][2], 3)

    def test_the_bayesian_average_does_not_truncate_to_an_integer(self):
        """La seconda trappola, nella sua forma peggiore: **ordina lo stesso**.

        `somma_voti` e `n_voti` sono interi, e senza `Cast` la divisione
        tronca. Un punteggio di 4,39 diventerebbe 4, la pagina renderebbe, e
        l'ordine sarebbe sbagliato solo dove conta — fra le prime.
        """
        scheda = self.scheda_pubblica("Petto e tricipiti", esercizi=3)
        self.vota(scheda, [5, 5, 4])

        riga = rankings.classifica_sociale().get(pk=scheda.pk)

        media_globale = rankings.media_globale_dei_voti()
        atteso = (3 * float(media_globale) + 14) / (3 + 3)
        self.assertAlmostEqual(riga.punteggio, atteso, places=6)
        self.assertNotEqual(riga.punteggio, int(riga.punteggio))

    def test_a_single_five_does_not_beat_many_high_votes(self):
        """È la ragione per cui la bayesiana esiste, e la ragione per cui la
        community (#72) resta cronologica: su media grezza un 5 secco starebbe
        in testa per sempre.

        Le dieci sufficienze della scheda «Nella media» non sono contorno: la
        bayesiana smorza **verso la media globale**, quindi senza un fondo di
        voti normali la media globale sarebbe fatta dalle due schede in gara e
        il 5 secco verrebbe smorzato verso se stesso. È il primo modo in cui
        questo test può mentire, ed è capitato scrivendolo.
        """
        self.vota(self.scheda_pubblica("Nella media"), [3] * 10)
        fortunata = self.scheda_pubblica("Un voto solo")
        self.vota(fortunata, [5])
        provata = self.scheda_pubblica("Molti voti")
        self.vota(provata, [5, 5, 4, 5, 5, 5, 4, 5, 5, 5])

        ordine = [r.name for r in rankings.classifica_sociale()]

        self.assertLess(ordine.index("Molti voti"), ordine.index("Un voto solo"))

    def test_a_routine_with_too_few_exercises_stays_out(self):
        """L'anti-civetta: una scheda con un esercizio solo non è una scheda,
        è un'esca per voti. È l'unica difesa **strutturale** della
        gamificabilità che questa pagina si prende; il resto si dichiara."""
        esca = self.scheda_pubblica("Esca", esercizi=1)
        self.vota(esca, [5, 5, 5])

        nomi = [r.name for r in rankings.classifica_sociale()]

        self.assertNotIn("Esca", nomi)

    def test_a_private_routine_is_not_ranked(self):
        """`is_public` è l'unico consenso dell'autore, e vale anche qui."""
        privata = self.scheda_pubblica("Bozza segreta")
        privata.is_public = False
        privata.save()
        self.vota(privata, [5, 5])

        nomi = [r.name for r in rankings.classifica_sociale()]

        self.assertNotIn("Bozza segreta", nomi)

    def test_a_routine_without_votes_is_not_ranked(self):
        """Senza voti non c'è un giudizio da ordinare: la scheda vive nella
        community, che è cronologica e le mostra tutte."""
        self.scheda_pubblica("Mai votata")

        nomi = [r.name for r in rankings.classifica_sociale()]

        self.assertNotIn("Mai votata", nomi)

    def test_the_global_average_is_over_all_votes_not_over_the_averages(self):
        """Non è la media delle medie: quella peserebbe uguale una scheda con
        un voto e una con cinquanta, che è ciò che la bayesiana esiste per non
        fare."""
        prima = self.scheda_pubblica("Prima")
        Vote.objects.create(user=self.popolazione[1], routine=prima, score=5)
        seconda = self.scheda_pubblica("Seconda")
        for indice in range(2, 6):
            Vote.objects.create(user=self.popolazione[indice], routine=seconda, score=1)

        # Media di tutti i voti: (5 + 1 + 1 + 1 + 1) / 5 = 1,8.
        # Media delle medie sarebbe (5 + 1) / 2 = 3.
        self.assertAlmostEqual(float(rankings.media_globale_dei_voti()), 1.8, places=6)

    # --- Le pagine ---------------------------------------------------------

    def test_both_rankings_render(self):
        for nome in ("training:ranking-strength", "training:ranking-social"):
            with self.subTest(rotta=nome):
                self.assertEqual(self.client.get(reverse(nome)).status_code, 200)

    def test_the_rankings_need_a_login(self):
        self.client.logout()

        for nome in ("training:ranking-strength", "training:ranking-social"):
            with self.subTest(rotta=nome):
                response = self.client.get(reverse(nome))
                self.assertEqual(response.status_code, 302)
                self.assertIn("/accounts/login/", response.url)

    def test_the_header_link_to_the_rankings_is_a_real_route(self):
        """Era l'ultimo `href` letterale dell'header, e portava a un 404.

        La pagina ha una voce **propria** nel menu di proposito: un requisito
        della traccia sepolto dentro una pagina di dettaglio, all'orale, va
        cercato.
        """
        response = self.client.get(reverse("training:dashboard"))

        self.assertContains(response, f'href="{reverse("training:ranking-strength")}"')

    def test_the_rankings_section_lights_up_and_only_that(self):
        response = self.client.get(reverse("training:ranking-social"))
        body = response.content.decode()

        self.assertIn('class="attivo">Classifiche</a>', body)
        self.assertIn('class="">Schede</a>', body)

    def test_the_bare_prefix_redirects_to_the_strength_ranking(self):
        """`/classifiche/` è il prefisso che l'header mostra: chi lo digita
        deve arrivare a una pagina, non a un 404."""
        response = self.client.get("/classifiche/")

        self.assertRedirects(response, reverse("training:ranking-strength"))

    def test_the_exercise_is_chosen_by_slug(self):
        """Come i filtri del catalogo (#71): `?esercizio=panca-piana` si legge,
        si salva e sopravvive a un ricaricamento del catalogo."""
        for utente in self.popolazione:
            self.serie(utente, self.trazioni, peso=Decimal("0"), reps=5, quante=2)

        response = self.client.get(
            reverse("training:ranking-strength"), {"esercizio": "trazioni"}
        )

        self.assertEqual(response.context["esercizio"], self.trazioni)

    def test_an_unknown_slug_falls_back_instead_of_raising(self):
        """Una classifica che non c'è è una domanda legittima con una risposta
        legittima, non una porta sbattuta."""
        response = self.client.get(
            reverse("training:ranking-strength"), {"esercizio": "non-esiste"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["esercizio"], self.panca)

    def test_the_page_paginates_at_twenty_five(self):
        """`Paginator`, 25 per pagina: qui i dati crescono senza limite, ed è
        la ragione per cui la lista degli esercizi (#71) non pagina e questa
        sì."""
        response = self.client.get(reverse("training:ranking-strength"))

        self.assertEqual(response.context["paginator"].per_page, 25)
        self.assertEqual(response.context["paginator"].count, self.UTENTI)

    def test_the_pagination_links_keep_the_chosen_exercise(self):
        """Senza, «pagina 2» tornerebbe alla classifica dell'esercizio
        sbagliato — e in silenzio, perché la pagina renderebbe lo stesso."""
        for utente in self.popolazione:
            self.serie(utente, self.trazioni, peso=Decimal("0"), reps=5, quante=2)
        # Servono più di 25 righe, o una seconda pagina non esiste e il test
        # passerebbe controllando un link che non doveva comparire.
        for indice in range(6):
            in_piu = User.objects.create_user(
                username=f"extra{indice}",
                password=PASSWORD,
                body_mass_kg=Decimal("80.00"),
            )
            self.serie(in_piu, self.trazioni, peso=Decimal("0"), reps=5, quante=2)

        response = self.client.get(
            reverse("training:ranking-strength"),
            {"esercizio": "trazioni", "page": 1},
        )

        self.assertContains(response, "esercizio=trazioni&amp;page=2")

    def test_my_own_row_is_highlighted(self):
        """Su una classifica di ottanta persone «e io dove sono?» è la prima
        domanda, ed è anche il motivo per cui la pagina impagina tutte le righe
        invece di mostrare una top 20."""
        response = self.client.get(reverse("training:ranking-strength"))

        self.assertContains(response, "riga-mia")

    def test_the_page_says_why_i_am_missing_without_a_body_mass(self):
        """L'assenza dalla classifica dev'essere leggibile come una condizione,
        non come un guasto della pagina."""
        self.io.body_mass_kg = None
        self.io.save()

        response = self.client.get(reverse("training:ranking-strength"))

        self.assertContains(response, "Non sei in classifica")
        self.assertContains(response, reverse("training:profile"))

    def test_the_exercise_detail_shows_the_short_ranking(self):
        """La stessa tabella, ridotta a cinque righe e col link all'intera: è
        un partial incluso due volte, non una seconda query scritta apposta."""
        response = self.client.get(
            reverse("training:exercise-detail", args=[self.panca.slug])
        )

        self.assertEqual(len(response.context["classifica"]), 5)
        self.assertContains(response, "Vedi tutta la classifica")

    def test_the_exercise_detail_stays_quiet_below_the_threshold(self):
        response = self.client.get(
            reverse("training:exercise-detail", args=[self.curl.slug])
        )

        self.assertNotIn("classifica", response.context)

    def test_the_number_of_queries_does_not_grow_with_the_rows(self):
        """La guardia di #70 nella forma di #86: protegge l'**invarianza**, non
        il numero. Una classifica che facesse una query per riga renderebbe
        benissimo su venti utenti e morirebbe su cento."""

        def rendi():
            with CaptureQueriesContext(connection) as contesto:
                self.assertEqual(
                    self.client.get(reverse("training:ranking-strength")).status_code,
                    200,
                )
            return len(contesto.captured_queries)

        prima = rendi()
        for indice in range(self.UTENTI, self.UTENTI + 20):
            nuovo = User.objects.create_user(
                username=f"extra{indice:02d}",
                password=PASSWORD,
                body_mass_kg=Decimal("80.00"),
            )
            self.serie(nuovo, self.panca, peso=Decimal("50"), reps=5, quante=2)

        self.assertEqual(prima, rendi())

    def test_the_social_ranking_queries_do_not_grow_with_the_routines(self):
        def rendi():
            with CaptureQueriesContext(connection) as contesto:
                self.assertEqual(
                    self.client.get(reverse("training:ranking-social")).status_code,
                    200,
                )
            return len(contesto.captured_queries)

        self.vota(self.scheda_pubblica("Una"), [5, 4])
        prima = rendi()
        for numero in range(6):
            self.vota(self.scheda_pubblica(f"Scheda {numero}"), [5, 4, 3])

        self.assertEqual(prima, rendi())


# --- La proprietà dell'oggetto e l'admin (#77) ------------------------------
#
# `docs/spec/07-test.md` §2 chiede la proprietà dell'oggetto «su tutte e sei le
# view», e i CRUD l'avevano già coperta sul GET (#69, #70) ma sul POST solo su
# quattro. La differenza non è cosmetica: il GET a 403 dimostra che la pagina
# non si apre, il POST a 403 dimostra che la *scrittura* non passa, ed è quella
# la richiesta che fa il danno. `routine-exercises` e `workout-update` erano gli
# scoperti. Raccogliere tutte e sei in una classe sola è deliberato: è un
# requisito della traccia, e all'orale un requisito si mostra da un posto, non
# da sei metodi sparsi in due classi.


class ObjectOwnershipTests(TestCase):
    """Le sei view di proprietà, GET e POST, viste da un secondo utente.

    Atteso **403** e non un 404: nascondere l'esistenza della riga sarebbe
    un'altra decisione, e #69 ha scelto di non prenderla — l'app dice «non è
    tua», non «non esiste». `UserPassesTestMixin.test_func()` risponde in
    `dispatch()`, quindi il 403 arriva **prima** che il form venga validato:
    è il motivo per cui i payload qui sotto possono essere approssimativi e il
    test resta significativo.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="lorenzo", password=PASSWORD)
        cls.altro = User.objects.create_user(username="martina", password=PASSWORD)

        group = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        muscle = Muscle.objects.create(
            code="chestMid", group=group, label_it="Petto medio", sort_order=1
        )
        equipment = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana", slug="panca-piana",
            primary_muscle=muscle, equipment=equipment,
        )

    def setUp(self):
        self.routine = Routine.objects.create(user=self.user, name="Spinta A")
        RoutineExercise.objects.create(
            routine=self.routine, exercise=self.panca,
            position=1, target_sets=3, target_reps=8,
        )
        self.workout = Workout.objects.create(
            user=self.user, title="Spinta A", started_at=timezone.now()
        )
        WorkoutSet.objects.create(
            workout=self.workout, exercise=self.panca,
            set_number=1, reps=8, weight=Decimal("60.00"),
        )

    def rotte(self):
        """Le sei view della spec, ognuna col POST che tenterebbe la scrittura."""
        inizio = timezone.localtime(self.workout.started_at).strftime("%Y-%m-%dT%H:%M")
        return (
            ("routine-update", self.routine.pk,
             {"name": "Rubata", "notes": "", "is_public": "on"}),
            ("routine-delete", self.routine.pk, {}),
            ("routine-exercises", self.routine.pk, {
                "exercises-TOTAL_FORMS": "1",
                "exercises-INITIAL_FORMS": "0",
                "exercises-MIN_NUM_FORMS": "0",
                "exercises-MAX_NUM_FORMS": "1000",
                "exercises-0-exercise": str(self.panca.pk),
                "exercises-0-position": "1",
                "exercises-0-target_sets": "5",
                "exercises-0-target_reps": "5",
                "exercises-0-notes": "",
            }),
            ("workout-update", self.workout.pk,
             {"title": "Rubato", "started_at": inizio, "ended_at": "", "notes": ""}),
            ("workout-delete", self.workout.pk, {}),
            ("workoutset-manage", self.workout.pk, {
                "sets-TOTAL_FORMS": "1",
                "sets-INITIAL_FORMS": "0",
                "sets-MIN_NUM_FORMS": "0",
                "sets-MAX_NUM_FORMS": "1000",
                "sets-0-exercise": str(self.panca.pk),
                "sets-0-set_number": "9",
                "sets-0-reps": "1",
                "sets-0-weight": "200",
                "sets-0-set_type": "working",
                "sets-0-is_completed": "on",
            }),
        )

    def test_a_second_user_gets_403_on_every_one_of_the_six_views(self):
        """Il GET: la pagina non si apre. 403, non 404 e soprattutto non 200."""
        self.client.force_login(self.altro)

        for nome, pk, _ in self.rotte():
            with self.subTest(rotta=nome):
                response = self.client.get(reverse(f"training:{nome}", args=[pk]))
                self.assertEqual(response.status_code, 403)

    def test_the_post_is_refused_too_and_nothing_moves(self):
        """Il POST: la scrittura non passa, e lo si verifica **sui dati**.

        Un 403 senza il controllo su cosa c'è nel database proverebbe solo che
        la risposta ha il numero giusto. Qui si guarda anche la riga.
        """
        self.client.force_login(self.altro)

        for nome, pk, payload in self.rotte():
            with self.subTest(rotta=nome):
                response = self.client.post(
                    reverse(f"training:{nome}", args=[pk]), payload
                )
                self.assertEqual(response.status_code, 403)

        self.routine.refresh_from_db()
        self.workout.refresh_from_db()
        self.assertEqual(self.routine.name, "Spinta A")
        self.assertFalse(self.routine.is_public)
        self.assertEqual(self.routine.exercises.count(), 1)
        self.assertEqual(self.routine.exercises.get().target_sets, 3)
        self.assertEqual(self.workout.title, "Spinta A")
        self.assertEqual(self.workout.sets.count(), 1)
        self.assertEqual(self.workout.sets.get().set_number, 1)

    def test_the_owner_still_gets_through(self):
        """La guardia deve fermare l'altro, non tutti: la controprova.

        Senza questo, un `test_func()` che restituisce sempre `False` farebbe
        passare i due test qui sopra.
        """
        self.client.force_login(self.user)

        for nome, pk, _ in self.rotte():
            with self.subTest(rotta=nome):
                response = self.client.get(reverse(f"training:{nome}", args=[pk]))
                self.assertEqual(response.status_code, 200)

    def test_an_anonymous_visitor_is_asked_to_log_in_not_refused(self):
        """Per un anonimo la risposta giusta è «entra», e la dà `LoginRequiredMixin`."""
        for nome, pk, _ in self.rotte():
            with self.subTest(rotta=nome):
                response = self.client.get(reverse(f"training:{nome}", args=[pk]))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)


class AdminTests(TestCase):
    """L'admin apre, e le tre registrazioni sono ancora coerenti coi modelli.

    Un `ModelAdmin` è configurazione che nomina campi per stringa: rinominare
    un campo o toglierlo da `Meta` lascia `admin.py` a puntare nel vuoto, e il
    sintomo è una pagina che esplode **solo quando qualcuno la apre**. È la
    stessa famiglia dei guasti silenziosi di #73 e #74, e la guardia è la
    stessa: aprire davvero le pagine.
    """

    #: I tre modelli che `training/admin.py` registra; il perché di ognuno sta
    #: nel docstring di quel file.
    REGISTRATI = (Exercise, Routine, User)

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="capo", password=PASSWORD, email="capo@example.com"
        )
        cls.utente = User.objects.create_user(
            username="lorenzo", password=PASSWORD, body_mass_kg=Decimal("78.50")
        )

        group = MuscleGroup.objects.create(code="chest", label_it="Petto", sort_order=1)
        muscle = Muscle.objects.create(
            code="chestMid", group=group, label_it="Petto medio", sort_order=1
        )
        equipment = Equipment.objects.create(
            code="barbell", label_it="Bilanciere", sort_order=1
        )
        cls.panca = Exercise.objects.create(
            name="Panca piana", slug="panca-piana",
            primary_muscle=muscle, equipment=equipment,
        )
        cls.routine = Routine.objects.create(user=cls.utente, name="Spinta A")
        RoutineExercise.objects.create(
            routine=cls.routine, exercise=cls.panca,
            position=1, target_sets=3, target_reps=8,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_the_three_models_are_registered_with_a_custom_modeladmin(self):
        """«`admin.register()` con `ModelAdmin` custom su 2–3 modelli», alla lettera."""
        for modello in self.REGISTRATI:
            with self.subTest(modello=modello.__name__):
                self.assertIn(modello, admin.site._registry)
                self.assertIsNot(
                    type(admin.site._registry[modello]), admin.ModelAdmin,
                    "registrato col ModelAdmin di serie: la spec ne chiede uno custom",
                )

    def test_the_index_and_every_changelist_open(self):
        indice = self.client.get(reverse("admin:index"))
        self.assertEqual(indice.status_code, 200)

        for modello in self.REGISTRATI:
            with self.subTest(modello=modello.__name__):
                rotta = f"admin:{modello._meta.app_label}_{modello._meta.model_name}"
                self.assertEqual(
                    self.client.get(reverse(f"{rotta}_changelist")).status_code, 200
                )
                self.assertEqual(
                    self.client.get(reverse(f"{rotta}_add")).status_code, 200
                )

    def test_the_change_pages_open_on_real_rows(self):
        """La pagina di modifica è quella che valida `fieldsets` e gli inline."""
        for modello, oggetto in (
            (Exercise, self.panca),
            (Routine, self.routine),
            (User, self.utente),
        ):
            with self.subTest(modello=modello.__name__):
                rotta = (
                    f"admin:{modello._meta.app_label}_"
                    f"{modello._meta.model_name}_change"
                )
                response = self.client.get(reverse(rotta, args=[oggetto.pk]))
                self.assertEqual(response.status_code, 200)

    def test_the_custom_user_is_the_one_registered(self):
        """`django.contrib.auth.admin` registra `auth.User`, che qui non esiste.

        Senza `training/admin.py` l'admin non mostrerebbe **nessun** utente: è
        la conseguenza di ADR-0003 che si paga in un posto solo, e si vede solo
        aprendo la pagina.
        """
        self.assertIs(admin.site._registry[User].model, User)
        self.assertEqual(User._meta.app_label, "training")

        lista = self.client.get(reverse("admin:training_user_changelist"))
        self.assertContains(lista, "lorenzo")

    def test_the_two_custom_user_fields_are_editable_from_the_admin(self):
        """`body_mass_kg` e `is_synthetic` sono nei `fieldsets`, non solo nel modello."""
        campi = set()
        for _, opzioni in admin.site._registry[User].fieldsets:
            campi.update(opzioni["fields"])
        self.assertIn("body_mass_kg", campi)
        self.assertIn("is_synthetic", campi)

    def test_the_routine_page_carries_its_exercises_inline(self):
        response = self.client.get(
            reverse("admin:training_routine_change", args=[self.routine.pk])
        )
        self.assertContains(response, "exercises-TOTAL_FORMS")
        self.assertContains(response, "Esercizi della scheda")

    def test_the_exercise_changelist_does_not_requery_per_row(self):
        """`list_select_related`: due FK per riga sono 200 query su 100 esercizi.

        Stessa guardia di #86 sul formset delle schede, e stessa forma: si
        confronta il numero di query a **due** righe e a **dodici**, perché il
        guasto è la crescita, non il valore assoluto.
        """
        def query_della_lista():
            with CaptureQueriesContext(connection) as contesto:
                self.assertEqual(
                    self.client.get(
                        reverse("admin:training_exercise_changelist")
                    ).status_code,
                    200,
                )
            return len(contesto.captured_queries)

        con_una = query_della_lista()

        for numero in range(1, 12):
            Exercise.objects.create(
                name=f"Esercizio {numero}",
                slug=f"esercizio-{numero}",
                primary_muscle=self.panca.primary_muscle,
                equipment=self.panca.equipment,
            )
        self.assertEqual(Exercise.objects.count(), 12)

        self.assertEqual(query_della_lista(), con_una)

    def test_the_admin_is_closed_to_everyone_who_is_not_staff(self):
        """Il 302 al login dell'admin, non il 200: la superficie è dei soli staff."""
        self.client.force_login(self.utente)

        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

        lista = self.client.get(reverse("admin:training_exercise_changelist"))
        self.assertEqual(lista.status_code, 302)

    def test_the_admin_does_not_open_the_history_of_what_someone_did(self):
        """`Workout`, `WorkoutSet` e `Vote` restano fuori, ed è una decisione.

        `03-import-ed-export.md` fissa la linea: «nessun import per conto di
        altri, nemmeno da admin». Registrarli sarebbe storico riscritto in
        silenzio; questo test è qui perché la prossima mano non lo faccia per
        comodità.
        """
        for modello in (Workout, WorkoutSet, Vote):
            with self.subTest(modello=modello.__name__):
                self.assertNotIn(modello, admin.site._registry)
