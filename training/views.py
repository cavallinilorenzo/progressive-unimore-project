"""Le view di Progressive.

Class-based view ovunque, come il progetto d'esempio del corso (#22). Qui ci
sono la dashboard e le due pagine dell'utente: le sezioni arrivano una alla
volta con i ticket della mappa #53.

Login, logout e reimpostazione password **non** compaiono in questo file: sono
le view già pronte di `django.contrib.auth`, incluse in `config/urls.py` sotto
`/accounts/`, e ciò che il progetto ci mette del suo sono i template in
`templates/registration/`. È il pattern del corso, e scrivere a mano una
`LoginView` sarebbe lavoro in più con meno garanzie.
"""

from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.edit import CreateView, UpdateView

from training.forms import ProfileForm, SignUpForm
from training.models import Equipment, Exercise, Muscle, MuscleGroup, Workout, WorkoutSet


class DashboardView(LoginRequiredMixin, TemplateView):
    """`/` — il guscio della dashboard.

    In fase 1 la pagina non calcola niente: le sei analisi che la riempiono
    sono fase 2 (`docs/spec/04-analisi.md`). Esiste ora perché `/` è una delle
    cinque voci dell'header, e una voce che porta a un 404 non è un guscio.

    Il `LoginRequiredMixin` entra qui, con questo ticket: #67 l'aveva lasciato
    fuori di proposito, perché finché `/accounts/login/` non esisteva la
    redirect avrebbe reso il progetto non avviabile da un clone pulito. Ora
    quella rotta c'è, e la dashboard è una pagina personale: senza un utente
    non ha niente da dire.
    """

    template_name = "training/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["oggi"] = timezone.localdate()
        return context


class SignUpView(CreateView):
    """`/registrazione/` — l'unica pagina di autenticazione scritta da noi.

    `django.contrib.auth` porta login e logout ma non la registrazione, e il
    form non può essere `UserCreationForm` liscio perché l'utente è il nostro
    (vedi `training.forms.SignUpForm`).

    Chi si registra entra subito: la coppia registrazione + login manuale è un
    passaggio in più che non protegge niente, e all'orale «mi registro ed è
    fatta» si dimostra in un gesto solo.
    """

    form_class = SignUpForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("training:profile")

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


class ProfileUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    """`/profilo/` — dove si dichiara il peso corporeo.

    Non c'è `UserPassesTestMixin` e non serve: `get_object` restituisce
    `request.user`, quindi non esiste un `pk` in URL con cui puntare al
    profilo di un altro. Il mixin della proprietà arriva dove l'oggetto è
    scelto dall'URL — schede e allenamenti, #69 e #70.
    """

    form_class = ProfileForm
    template_name = "training/profile.html"
    success_url = reverse_lazy("training:profile")
    success_message = "Il profilo è aggiornato."

    def get_object(self, queryset=None):
        return self.request.user


class ExerciseListView(LoginRequiredMixin, ListView):
    """`/esercizi/` — il catalogo, in sola lettura e filtrabile su tre assi.

    È la pagina che paga il requisito «select/view **grouped** objects»: gli
    esercizi non escono come lista piatta ma **raggruppati per gruppo
    muscolare**, e i tre filtri — gruppo, muscolo, attrezzo — restringono
    l'insieme in AND.

    `Exercise` è in **sola lettura per scelta**, non per dimenticanza
    (ADR-0001): un esercizio inventato dall'utente sarebbe invisibile a
    percentili e classifiche, che confrontano persone diverse sullo *stesso*
    movimento. Il CRUD completo che la traccia chiede sta su `Routine` e
    `Workout`. È una deviazione da dichiarare all'orale, prima che sembri un
    CRUD mancante.

    I filtri viaggiano per `code`, non per `pk`: un URL come
    `?gruppo=petto&attrezzo=bilanciere` si legge e resta valido anche se il
    catalogo venisse ricaricato da zero, mentre le chiavi primarie no.

    Nessun `Paginator`: sono 100 esercizi, e paginarli spezzerebbe a metà i
    gruppi che sono il punto della pagina. La paginazione arriva dove i dati
    crescono senza limite — le classifiche (#76).
    """

    model = Exercise
    template_name = "training/exercise_list.html"
    context_object_name = "esercizi"

    def get_queryset(self):
        # `select_related` sui due FK e sul gruppo: il template li legge per
        # ogni riga, e senza questo la pagina fa 300 query.
        queryset = Exercise.objects.select_related(
            "primary_muscle__group", "equipment"
        ).order_by("primary_muscle__group__sort_order", "name")

        gruppo = self.request.GET.get("gruppo")
        if gruppo:
            queryset = queryset.filter(primary_muscle__group__code=gruppo)

        muscolo = self.request.GET.get("muscolo")
        if muscolo:
            queryset = queryset.filter(primary_muscle__code=muscolo)

        attrezzo = self.request.GET.get("attrezzo")
        if attrezzo:
            queryset = queryset.filter(equipment__code=attrezzo)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        gruppo = self.request.GET.get("gruppo") or ""
        context["gruppo_scelto"] = gruppo
        context["muscolo_scelto"] = self.request.GET.get("muscolo") or ""
        context["attrezzo_scelto"] = self.request.GET.get("attrezzo") or ""

        context["gruppi"] = MuscleGroup.objects.all()
        # Scelto un gruppo, la tendina dei muscoli mostra solo i suoi: le due
        # anagrafiche sono annidate, e offrire «petto» insieme a «quadricipiti»
        # significa offrire una combinazione che non rende mai una riga.
        muscoli = Muscle.objects.select_related("group")
        if gruppo:
            muscoli = muscoli.filter(group__code=gruppo)
        context["muscoli"] = muscoli
        context["attrezzi"] = Equipment.objects.all()

        context["filtro_attivo"] = any(
            [gruppo, context["muscolo_scelto"], context["attrezzo_scelto"]]
        )
        return context


class ExerciseDetailView(LoginRequiredMixin, DetailView):
    """`/esercizi/<slug>/` — in fase 1 un guscio, e per una ragione.

    La spec la chiama «la pagina più densa del progetto», ma quella densità è
    fase 2 e 3: progressione del massimale, PR, percentile, stato di stallo,
    consiglio di carico, classifica ridotta. Qui ci sono l'anagrafica e lo
    **storico grezzo** delle serie dell'utente su questo esercizio — il dato
    su cui quelle analisi si costruiranno, mostrato senza interpretarlo.

    L'URL poggia sullo `slug`, generato una volta da `load_catalog` e non a
    runtime (`training.models.Exercise.slug`): gli URL degli esercizi devono
    restare stabili, perché è da lì che passeranno i link della progressione.

    Niente `UserPassesTestMixin`: l'esercizio è del catalogo globale, non di
    un utente. Ciò che è personale è lo storico, ed è filtrato per
    `request.user` nel queryset, non protetto da un mixin.
    """

    model = Exercise
    template_name = "training/exercise_detail.html"
    context_object_name = "esercizio"

    #: Quante sessioni recenti mostrare. Lo storico completo di un esercizio
    #: fondamentale è lungo anni; qui serve a far vedere che il dato c'è.
    SESSIONI_RECENTI = 10

    def get_queryset(self):
        return Exercise.objects.select_related("primary_muscle__group", "equipment")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Due query invece di una: prima gli ultimi allenamenti che toccano
        # questo esercizio, poi le loro serie. Un `[:N]` sulle serie taglierebbe
        # a metà l'ultima sessione, e una sessione monca si legge come una
        # sessione fatta male.
        allenamenti_recenti = (
            Workout.objects.filter(
                user=self.request.user, sets__exercise=self.object
            )
            .distinct()
            .order_by("-started_at")[: self.SESSIONI_RECENTI]
        )
        context["serie"] = (
            WorkoutSet.objects.filter(
                workout__in=list(allenamenti_recenti), exercise=self.object
            )
            .select_related("workout")
            .order_by("-workout__started_at", "set_number")
        )
        return context
