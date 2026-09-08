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
from django.db import IntegrityError, transaction
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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
