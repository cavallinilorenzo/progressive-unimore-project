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
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.edit import CreateView, DeleteView, UpdateView

from training.forms import (
    ProfileForm,
    RoutineExerciseFormSet,
    RoutineForm,
    SignUpForm,
    VoteForm,
)
from training.models import (
    Equipment,
    Exercise,
    Muscle,
    MuscleGroup,
    Routine,
    Vote,
    Workout,
    WorkoutSet,
)


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



class RoutinePublicListView(LoginRequiredMixin, ListView):
    """`/schede/pubbliche/` — la community, dentro Schede e non nell'header.

    È la regola di navigazione di `02-pagine-e-template.md` presa alla lettera:
    l'header porta cinque voci, e ogni altra pagina si raggiunge da dentro la
    sezione a cui appartiene per dominio. Le schede degli altri sono schede,
    quindi si entra da `/schede/`.

    L'ordine è **cronologico, non per media**: la classifica sociale è una
    pagina propria (#76) e ordina per media bayesiana, che è un'altra cosa
    dalla media grezza — con un voto solo, un 5 secco starebbe in testa alla
    community per sempre. Qui la media si *mostra* accanto a ogni scheda, e
    ordinare tocca alla pagina che lo dichiara.
    """

    model = Routine
    context_object_name = "routines"
    template_name = "training/routine_public_list.html"

    def get_queryset(self):
        # `annotate` invece di calcolare in template: media e conteggio in una
        # query sola, contro due per riga. `select_related` sull'autore per la
        # stessa ragione — il nome compare su ogni card.
        return (
            Routine.objects.filter(is_public=True)
            .select_related("user")
            .annotate(media=Avg("votes__score"), voti=Count("votes"))
        )


class RoutinePublicDetailView(LoginRequiredMixin, DetailView):
    """`/schede/pubbliche/<pk>/` — la scheda di un altro, con voto e commento.

    Questa pagina è **anche il form del terzo CRUD**: creare e modificare il
    proprio voto succedono qui, sullo stesso URL, come il formset di
    `RoutineExercisesView` — un `DetailView` con un `post()`, e non due rotte
    separate, perché il voto non ha una pagina propria: si esprime guardando la
    scheda. La cancellazione ha invece la sua rotta (`vote-delete`), perché
    cancellare è un POST con una conferma.

    Il queryset è filtrato su `is_public`: una scheda privata **non esiste** da
    qui, e ci si arriva con un 404 — è la seconda delle due regole, applicata a
    monte del form. Non è un 403 come per le rotte di `OwnerRequiredMixin`: là
    la domanda è «è tua?» e la risposta onesta è «non è tua», qui la domanda è
    «esiste una scheda pubblica con questo numero?», e finché l'autore non la
    espone la risposta è no.

    Il proprietario può aprire la propria scheda pubblica — è così che vede
    cosa ne pensano gli altri — ma non trova il form: `posso_votare` è falso, e
    se lo aggirasse con un POST lo fermerebbe `VoteForm.clean`.
    """

    model = Routine
    context_object_name = "routine"
    template_name = "training/routine_public_detail.html"

    def get_queryset(self):
        return (
            Routine.objects.filter(is_public=True)
            .select_related("user")
            .prefetch_related(
                "exercises__exercise__equipment",
                "exercises__exercise__primary_muscle",
            )
        )

    def get_mio_voto(self):
        return Vote.objects.filter(
            user=self.request.user, routine=self.object
        ).first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        mio_voto = self.get_mio_voto()
        context["mio_voto"] = mio_voto
        context["e_mia"] = self.object.user_id == self.request.user.pk
        context["posso_votare"] = not context["e_mia"]

        # Se il POST è fallito, il form in contesto è quello con gli errori e i
        # dati dell'utente: non va ricostruito, o li si perde.
        context.setdefault(
            "form",
            VoteForm(
                instance=mio_voto, voter=self.request.user, routine=self.object
            ),
        )

        voti = self.object.votes.select_related("user").exclude(
            user=self.request.user
        )
        context["voti"] = voti
        aggregato = self.object.votes.aggregate(
            media=Avg("score"), conteggio=Count("pk")
        )
        context["media"] = aggregato["media"]
        context["conteggio"] = aggregato["conteggio"]
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Un voto per utente per scheda (`vote_unique_per_user_routine`): il
        # secondo invio **modifica** il primo invece di infrangere l'unicità
        # con un `IntegrityError`. È la U del CRUD, ed è anche il motivo per
        # cui la pagina non ha bisogno di un «hai già votato, vai di là».
        mio_voto = self.get_mio_voto()
        form = VoteForm(
            request.POST,
            instance=mio_voto,
            voter=request.user,
            routine=self.object,
        )

        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        # Chi vota e cosa vota li mette la view, mai il form: un campo in
        # pagina è un campo riscrivibile in un POST costruito a mano.
        form.instance.user = request.user
        form.instance.routine = self.object
        form.save()

        messages.success(
            request,
            "Il tuo voto è aggiornato." if mio_voto else "Il tuo voto è registrato.",
        )
        return redirect("training:routine-public-detail", pk=self.object.pk)


class VoteDeleteView(LoginRequiredMixin, DeleteView):
    """`/schede/pubbliche/<pk>/voto/elimina/` — la D del terzo CRUD.

    L'URL porta il numero della **scheda**, non quello del voto: dalla pagina
    della community il voto che si toglie è sempre il proprio, e un `pk` di
    `Vote` in URL sarebbe un numero che l'utente non ha modo di conoscere e che
    inviterebbe a puntare quello di un altro.

    Per questo non c'è `UserPassesTestMixin`, e non manca: `get_object` cerca
    il voto **di `request.user`** su quella scheda, quindi il voto di un altro
    non è raggiungibile — non esiste un `pk` con cui puntarlo. È la stessa
    ragione di `ProfileUpdateView`. Chi non ha votato riceve un 404: non c'è
    niente da cancellare.
    """

    model = Vote
    template_name = "training/vote_confirm_delete.html"

    def get_object(self, queryset=None):
        return get_object_or_404(
            Vote.objects.select_related("routine"),
            user=self.request.user,
            routine_id=self.kwargs["pk"],
        )

    def get_success_url(self):
        return reverse("training:routine-public-detail", args=[self.kwargs["pk"]])

    def form_valid(self, form):
        messages.success(self.request, "Il tuo voto è stato tolto.")
        return super().form_valid(form)
