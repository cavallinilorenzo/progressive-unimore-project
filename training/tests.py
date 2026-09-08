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

from training import views
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
