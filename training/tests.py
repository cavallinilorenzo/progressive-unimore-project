"""Test di Progressive — un file solo, `TestCase` + `Client`, come il corso.

Vedi `docs/spec/07-test.md`: i test non inseguono la copertura, proteggono i
requisiti della traccia e le poche regole che il database non può imporre da
solo. I quattro test che contano davvero arrivano coi ticket delle pagine e
dell'import; qui c'è solo la guardia sulle fondamenta — i quattro check
constraint e le unicità decise in `01-modelli.md`, che sono invisibili finché
qualcuno non li rimuove da `Meta` senza accorgersene.
"""

import re
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from training import views
from training.forms import VoteForm
from training.models import (
    Equipment,
    Exercise,
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
