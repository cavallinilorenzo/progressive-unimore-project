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

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.edit import CreateView, DeleteView, UpdateView

from training.forms import (
    ProfileForm,
    RoutineExerciseFormSet,
    RoutineForm,
    SignUpForm,
)
from training.models import Routine


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


class OwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """La proprietà dell'oggetto, col pattern del corso (#22).

    `UserPassesTestMixin` + `test_func()` è la coppia che il prof ha insegnato,
    ed è quella che va usata: all'orale è riconoscibile a colpo d'occhio.

    La distinzione fra i due mixin non è ridondanza. Per un anonimo
    `LoginRequiredMixin` devia verso il login, perché la risposta giusta è
    «entra». Per un utente **autenticato** che punta la scheda di un altro la
    risposta è **403**, e la dà `AccessMixin.handle_no_permission`, che solleva
    `PermissionDenied` appena l'utente è autenticato.

    403 e non 404: nascondere l'esistenza della riga sarebbe un'altra
    decisione, e su un progetto d'esame «non è tua» è più leggibile di «non
    esiste». Nemmeno 200 su una copia in sola lettura — la scheda di un altro
    si guarda dalla community, e solo se lui l'ha resa pubblica.
    """

    def test_func(self):
        return self.get_object().user == self.request.user


class RoutineListView(LoginRequiredMixin, ListView):
    """`/schede/` — le mie, e solo le mie.

    Il filtro sta in `get_queryset`, non in un `if` nel template: un template
    che riceve schede altrui le ha già caricate, e basta dimenticare una riga
    perché le mostri.
    """

    model = Routine
    context_object_name = "routines"
    template_name = "training/routine_list.html"

    def get_queryset(self):
        # `prefetch_related` perché la lista conta gli esercizi di ogni scheda:
        # senza, è una query per riga.
        return (
            Routine.objects.filter(user=self.request.user)
            .prefetch_related("exercises")
        )


class RoutineDetailView(OwnerRequiredMixin, DetailView):
    """`/schede/<pk>/` — la scheda con i suoi esercizi in ordine.

    Anche la lettura passa dal mixin della proprietà: questa è la pagina della
    *mia* scheda. La versione pubblica, con voto e commento, è un'altra rotta
    (`routine-public-detail`) e un altro ticket.
    """

    model = Routine
    context_object_name = "routine"
    template_name = "training/routine_detail.html"

    def get_queryset(self):
        return Routine.objects.prefetch_related(
            "exercises__exercise__equipment",
            "exercises__exercise__primary_muscle",
        )


class RoutineCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    """`/schede/nuova/` — il nome e poco altro.

    Chi crea una scheda atterra sulla gestione degli esercizi, non sulla lista:
    una scheda senza esercizi non è ancora una scheda, e il passo successivo è
    l'unico che abbia senso proporre.
    """

    model = Routine
    form_class = RoutineForm
    template_name = "training/routine_form.html"
    success_message = "La scheda è creata. Ora mettici gli esercizi."

    def form_valid(self, form):
        # Il proprietario lo mette la view, mai il form: vedi `RoutineForm`.
        form.instance.user = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("training:routine-exercises", args=[self.object.pk])


class RoutineUpdateView(OwnerRequiredMixin, SuccessMessageMixin, UpdateView):
    """`/schede/<pk>/modifica/` — nome, note e il flag `is_public`."""

    model = Routine
    form_class = RoutineForm
    template_name = "training/routine_form.html"
    success_message = "La scheda è aggiornata."

    def get_success_url(self):
        return reverse("training:routine-detail", args=[self.object.pk])


class RoutineDeleteView(OwnerRequiredMixin, DeleteView):
    """`/schede/<pk>/elimina/` — con la conferma, che è un POST.

    Cancellare una scheda **non tocca gli allenamenti** che ne sono nati: la
    FK è `SET_NULL` e il titolo è un'istantanea (ADR-0002). La pagina di
    conferma lo dice, perché è la domanda che l'utente si fa proprio lì.
    """

    model = Routine
    template_name = "training/routine_confirm_delete.html"
    success_url = reverse_lazy("training:routine-list")

    def form_valid(self, form):
        # `SuccessMessageMixin` non copre `DeleteView` in modo utile: l'oggetto
        # a messaggio composto non esiste più. Il nome si legge prima.
        messages.success(self.request, f"«{self.object.name}» è eliminata.")
        return super().form_valid(form)


class RoutineExercisesView(OwnerRequiredMixin, UpdateView):
    """`/schede/<pk>/esercizi/` — il primo form denso del progetto.

    `fields = []` non è una dimenticanza: la pagina non modifica nessun campo
    della scheda, modifica le sue **righe figlie**. Resta una `UpdateView`
    perché il resto — `get_object`, il 403 del mixin, il template — è
    esattamente quello, e riscriverlo come `View` con `get`/`post` a mano
    perderebbe la convenzione senza guadagnare niente.

    Il formset è un `inlineformset_factory`: aggiunge, modifica e cancella le
    righe in un solo POST, dentro una transazione, e con zero JavaScript.
    """

    model = Routine
    fields = []
    template_name = "training/routine_exercises.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Se il POST è fallito, il formset in contesto è quello con gli errori
        # e i dati dell'utente: non va ricostruito, o li si perde.
        context.setdefault("formset", RoutineExerciseFormSet(instance=self.object))
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        formset = RoutineExerciseFormSet(request.POST, instance=self.object)

        if not formset.is_valid():
            return self.render_to_response(self.get_context_data(formset=formset))

        formset.save()
        messages.success(request, "Gli esercizi della scheda sono aggiornati.")
        return redirect("training:routine-detail", pk=self.object.pk)
