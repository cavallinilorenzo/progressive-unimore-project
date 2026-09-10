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

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import FileSystemStorage
from django.db import transaction
from django.db.models import Avg, Count, F, Prefetch, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView
from django.views.generic.detail import SingleObjectMixin
from django.views.generic.edit import CreateView, DeleteView, FormView, UpdateView

from training import querysets, rankings
from training.analytics import coach as analytics_coach
from training.analytics import costanza as analytics_costanza
from training.analytics import muscles as analytics_muscles
from training.analytics import plateau as analytics_plateau
from training.analytics import progressione as analytics_progressione
from training.analytics import volume as analytics_volume
from training.forms import (
    AbbinamentoFormSet,
    ImportUploadForm,
    ProfileForm,
    RoutineExerciseFormSet,
    RoutineForm,
    SignUpForm,
    VoteForm,
    WorkoutForm,
    WorkoutSetFormSet,
)
from training.exporter import FILE as FILE_EXPORT
from training.exporter import esporta_esercizi, esporta_zip
from training.importer import FormatoNonValido, leggi, ricorda, risolvi, scrivi
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


#: Le finestre della dashboard, in giorni. Sono **mobili** e non «settimana
#: corrente» / «mese corrente», e la ragione è concreta: la popolazione
#: sintetica finisce a una data fissa (`seed_synthetic.TODAY`), quindi al primo
#: lunedì successivo una dashboard ancorata al calendario tornerebbe a zero e la
#: pagina sembrerebbe rotta il giorno dell'orale. Una finestra mobile guarda
#: sempre indietro dello stesso tratto, e su dati fermi continua a rispondere.
#:
#: La costanza non è più qui da #101: è passata a `analytics/costanza.py` (W1) e
#: con lei la finestra, che è diventata **quattro settimane di calendario**
#: invece di 28 giorni mobili. Non è un ripensamento sulla regola qui sopra —
#: la griglia dei lunedì resta ancorata a *oggi*, quindi scorre con i dati — ma
#: l'allineamento alla griglia su cui `/analisi/` (#99) e la heatmap
#: raggruppano: «settimana» deve voler dire una cosa sola in tutto il progetto.
GIORNI_RECENTI = 7
GIORNI_MESE = 30


class DashboardView(LoginRequiredMixin, TemplateView):
    """`/` — le quattro cifre, la heatmap muscolare, e gli ultimi allenamenti.

    Fino a #78 questa pagina era un **guscio**: quattro riquadri con un trattino
    e «analisi in arrivo», perché le sei analisi che la riempiono sono fase 2
    (`docs/spec/04-analisi.md`). Reggeva finché il database era vuoto. Con due
    anni di storico dentro non regge più: `/` è la **prima pagina che il prof
    vede**, e una prima pagina che non dice niente su 443 allenamenti fa
    sembrare rotto ciò che invece funziona.

    Quindi qui si calcola, ma si calcola **poco e per intero**: quattro
    aggregati sopra le righe che l'utente ha già registrato, niente percentili,
    niente confronto con gli altri, nessuna finestra scorrevole. La linea di
    fase 2 non è «la dashboard mostra numeri», è **il confronto fra persone e
    la progressione nel tempo** — e quella resta di là.

    Delle tecniche del ponte (`docs/spec/00-indice.md`) ne usa una sola,
    `F()`, e per la ragione già scritta lì: il volume è `ripetizioni × carico
    effettivo` su 296.724 righe, e farlo in Python vorrebbe dire scaricarle
    tutte.

    Con #97 le due definizioni condivise che questa pagina usa — il filtro
    universale e il volume — smettono di essere riscritte qui e arrivano dal
    custom QuerySet. Non è ordine: la copia scritta a mano calcolava il volume
    **senza carico effettivo**, quindi su corpo libero valeva zero, e nessun
    test lo segnalava perché nessuno confrontava questa pagina con le analisi
    (#75). Il riquadro del volume, dopo, mostra un numero più alto: è la
    schiena che era sparita.

    Con #101 la pagina smette di essere quattro cifre. Entra la **heatmap
    muscolare**, che vive solo qui (`02-pagine-e-template.md`) ed è il richiamo
    visivo di cui `/analisi/` è la spiegazione, e la costanza diventa **W1**:
    la stessa media di prima, ma con sotto le quattro settimane una per una,
    vuote comprese. Due misure di costanza sulla stessa pagina sarebbero la
    divergenza di #75 un'altra volta, quindi W1 *è* quel riquadro, non un
    secondo.

    Con #112 la pagina smette di raccontare solo il passato: in cima, **sopra
    le quattro cifre**, entra il riquadro del coach con **un** consiglio, quello
    a priorità più alta (ADR-0007). È la prima superficie del progetto che dice
    cosa fare invece di cosa è successo, e il posto in cui sta è parte della
    decisione: in fondo alla pagina sarebbe un piè di pagina della heatmap.

    Il conto delle query resta **invariante rispetto allo storico**, che è la
    guardia lasciata da #86: la heatmap ne aggiunge quattro — l'aggregazione e
    tre letture di catalogo — e il coach una, l'aggregato dei tre conteggi di
    `analytics/costanza.py`. Nessuna delle cinque cresce con le righe.

    Il `LoginRequiredMixin` entra con #68: la dashboard è una pagina personale,
    senza un utente non ha niente da dire.
    """

    template_name = "training/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["oggi"] = timezone.localdate()

        adesso = timezone.now()
        da_recenti = adesso - timedelta(days=GIORNI_RECENTI)
        da_mese = adesso - timedelta(days=GIORNI_MESE)

        # Il **filtro universale** arriva dal custom QuerySet, non riscritto qui:
        # solo le serie di lavoro e completate contano, il riscaldamento non è
        # volume allenante e una serie programmata ma non spuntata non è
        # successa. Fino a #97 questa riga era una seconda copia della stessa
        # regola, ed è così che il volume aveva finito per divergere.
        serie = WorkoutSet.objects.working().filter(workout__user=self.request.user)
        allenamenti = Workout.objects.filter(user=self.request.user)

        # `with_volume()` e non `Sum(F("reps") * F("weight"))`: la seconda forma
        # è ciò che questa view faceva fino a #97, e su corpo libero dava
        # **zero** — le trazioni e i piegamenti non entravano nel riquadro che
        # apre la prima pagina. Il volume ha un nome solo (ADR-0006), e la
        # dashboard e le analisi di fase 2 lo leggono dallo stesso posto.
        #
        # La view chiama il **metodo** e non importa l'espressione: le query
        # stanno nel QuerySet, qui sta la domanda.
        context["volume_recente"] = (
            serie.filter(workout__started_at__gte=da_recenti)
            .with_volume()
            .aggregate(v=Sum("volume"))["v"]
        )

        context["allenamenti_mese"] = allenamenti.filter(
            started_at__gte=da_mese
        ).count()
        context["allenamenti_totali"] = allenamenti.count()

        # W1 — la costanza. La media resta la cifra hero, perché «quante volte
        # a settimana» è la domanda che un utente si fa davvero, ma sotto ci
        # sono adesso le quattro settimane una per una, **vuote comprese**: la
        # media di 2 può essere due settimane da 4 e due da zero, e quelle due
        # storie meritano consigli opposti.
        context["costanza"] = analytics_costanza.costanza(self.request.user)

        # Il record è il carico più alto del mese, non il massimale stimato:
        # Epley è roba del motore analitico, e qui basta un `Max` su una colonna.
        record = (
            serie.filter(workout__started_at__gte=da_mese)
            .order_by("-weight")
            .select_related("exercise")
            .first()
        )
        context["record"] = record

        context["ultimi_allenamenti"] = (
            allenamenti.order_by("-started_at")
            .select_related("routine")
            .annotate(n_serie=Count("sets"))[:5]
        )
        # La heatmap muscolare, che vive **solo qui** (`02-pagine-e-template.md`).
        # Misura in **serie** e non in kg, ed è una scelta e non una svista: il
        # volume non si confronta fra regioni del corpo, perché una serie di
        # squat pesa dieci volte una di alzate laterali e la mappa direbbe una
        # cosa sull'anatomia invece che sull'allenamento. Il perché sta per
        # esteso in `analytics/muscles.py`, la dichiarazione in pagina.
        heatmap = analytics_muscles.serie_per_muscolo(self.request.user)
        context["heatmap"] = heatmap

        # **Un corpo tutto spento non si mostra.** Sarebbe indistinguibile da
        # «non ti alleni», mentre la verità è «non lo so»: la figura è una
        # scala normalizzata sul massimo, e senza serie nella finestra il
        # massimo è finto. Al posto suo va detto perché non c'è niente, e i due
        # vuoti sono diversi — chi non ha mai registrato niente si invita a
        # cominciare, chi ha 443 allenamenti ma nessuno nelle ultime quattro
        # settimane si manda allo storico. È la regola già scritta su
        # `/analisi/` (#99), e vale doppio sulla prima pagina.
        context["heatmap_ha_dati"] = heatmap["totale"] > 0

        # **Il coach, e sta in cima** (#112). La dashboard è già a otto riquadri
        # e a dodici query: se «dire cosa fare» è la tesi del progetto, il
        # consiglio non può stare in fondo, sotto la heatmap, dove si arriva
        # scorrendo. Sopra le quattro cifre, quindi — è la prima cosa che si
        # legge, e la decisione è reversibile in dieci righe di template.
        #
        # La heatmap si passa perché **è già stata calcolata due righe sopra**:
        # lo squilibrio legge le stesse serie per gruppo che la figura disegna,
        # e ricalcolarle qui vorrebbe dire quattro query in più per ottenere
        # l'oggetto identico. Le query che il coach aggiunge sono quindi
        # **una**, l'aggregato dei tre conteggi, e non cresce con lo storico:
        # la guardia di #86 resta in piedi e il test la verifica.
        #
        # `None` è un esito normale e non un errore: con due dei quattro tipi
        # ancora da scrivere capita spesso, e il template in quel caso **non
        # disegna il riquadro**. Un riquadro vuoto che dicesse «nessun
        # consiglio» sarebbe peggio del silenzio: suonerebbe come «va tutto
        # bene» mentre metà delle regole non esiste ancora, cioè una diagnosi
        # rassicurante emessa da un coach che non ha guardato. Il caso si
        # stringe quasi a zero col consiglio di carico, che scatta per chiunque
        # abbia registrato una serie.
        context["consiglio"] = analytics_coach.consiglio_per_dashboard(
            self.request.user, heatmap=heatmap
        )

        # Il limite noto — i muscoli che nessun esercizio ha come primario —
        # esce già dalla riga della heatmap, e la pagina lo dichiara: la mappa
        # direbbe «trascurato» dove la verità è «non misurato» (#37, #40).

        context["giorni_recenti"] = GIORNI_RECENTI
        context["giorni_mese"] = GIORNI_MESE
        return context


class AnalysisView(LoginRequiredMixin, TemplateView):
    """`/analisi/` — A1 e A2, e il primo grafico del progetto.

    **La sesta voce dell'header**, e la pagina che `docs/spec/04-analisi.md`
    nominava («Analisi muscolare») senza che `02-pagine-e-template.md` le desse
    un URL. La contraddizione si sana qui, e nel verso di darle l'indirizzo:
    infilare A1 e A2 in dashboard sovraccaricherebbe la prima pagina e
    lascerebbe la heatmap unico contenuto di una pagina che non esiste.

    La divisione del lavoro fra le due superfici è quella, e vale anche per i
    ticket che seguono: **la heatmap in dashboard è il richiamo visivo,
    `/analisi/` è dove si va a capire perché.**

    Le due analisi non hanno incognite — sono la stessa `Sum(VOLUME)`
    raggruppata due volte, e vivono in `training/analytics/volume.py`. Il
    lavoro vero è la presentazione, e sta quasi tutto in due posti: i **buchi**
    (una settimana senza allenamenti non esiste come riga, e un grafico che
    non la disegna mente sulla costanza) e il **vuoto** (un utente appena
    registrato non deve vedere due figure piatte, ma il motivo per cui non c'è
    niente da disegnare — la stessa regola del percentile sotto soglia).

    Il grafico entra da qui e non da un ticket suo, perché «aggiungi il CDN»
    non chiuderebbe su niente di verificabile. Chart.js è l'**unica deviazione
    JavaScript del progetto** e va dichiarata all'orale: i dati arrivano con
    `json_script`, **mai** da un endpoint JSON, che senza HTMX sarebbe una
    seconda superficie di viste da scrivere, testare e proteggere, e
    reintrodurrebbe il `fetch` che #21 ha escluso.

    **Il taglio del periodo sta in querystring** (`?periodo=mese`, #106) e non
    in sessione né in JavaScript: così si legge, si salva nei preferiti e
    sopravvive a un ricaricamento — la stessa regola di `?esercizio=` sulla
    classifica di forza e dei tre filtri del catalogo. Il toggle è quindi due
    **link** e la pagina si ricarica: scambiare due dataset già in memoria
    sarebbe JavaScript applicativo, che #21 ha escluso, e costringerebbe a
    spedire il doppio dei dati a chi ne guarda metà.
    """

    template_name = "training/analysis.html"

    #: Il nome del parametro, in italiano come `?gruppo=` e `?esercizio=`: la
    #: querystring di questo progetto è testo che l'utente legge, non un
    #: protocollo interno.
    PARAMETRO_PERIODO = "periodo"

    def get_context_data(self, **kwargs):
        contesto = super().get_context_data(**kwargs)

        taglio = analytics_volume.taglio_richiesto(
            self.request.GET.get(self.PARAMETRO_PERIODO)
        )
        finestra = taglio.finestra()
        per_periodo = analytics_volume.volume_nel_tempo(
            self.request.user, taglio, finestra
        )
        per_gruppo = analytics_volume.volume_per_gruppo(
            self.request.user, taglio, finestra
        )

        contesto["taglio"] = taglio
        contesto["tagli"] = self._toggle(taglio)
        contesto["punti"] = analytics_volume.PUNTI_DELLA_FINESTRA
        contesto["parziale"] = analytics_volume.quanto_e_trascorso(taglio, finestra)
        contesto["da"] = finestra[0]
        contesto["per_periodo"] = per_periodo
        contesto["per_gruppo"] = per_gruppo
        contesto["volume_totale"] = sum(riga["volume"] for riga in per_periodo)

        # I due payload dei grafici sono **dichiarativi**: portano il tipo di
        # figura insieme ai dati, e il renderer generico di `static/js/grafici.js`
        # non sa niente né di volume né di gruppi muscolari. È ciò che permette
        # al terzo grafico (A3, la progressione) di nascere senza scrivere una
        # riga di JavaScript in più — che è il punto, visto che di JavaScript
        # applicativo questo progetto non ne vuole.
        contesto["grafico_periodi"] = {
            "tipo": "line",
            # Il formato dell'etichetta appartiene al taglio: su dodici mesi
            # servono gli anni (`mar 26`), su dodici settimane no (`3 mar`), e
            # metterli comunque riempirebbe l'asse di rumore.
            "etichette": [
                date_format(riga["periodo"], taglio.formato) for riga in per_periodo
            ],
            "valori": [riga["volume"] for riga in per_periodo],
            "unita": "kg",
            "serie": f"Volume per {taglio.singolare}",
        }
        contesto["grafico_gruppi"] = {
            # **Barre e non torta.** Una torta su sei gruppi è leggibile, ma
            # dice solo delle proporzioni di oggi; le barre condividono l'asse
            # dei kg col grafico sopra, quindi si confrontano fra loro e nel
            # tempo, che è la domanda vera di chi guarda questa pagina.
            "tipo": "bar",
            "etichette": [riga["gruppo"] for riga in per_gruppo],
            "valori": [riga["volume"] for riga in per_gruppo],
            "unita": "kg",
            "serie": "Volume per gruppo",
        }

        # Due vuoti diversi, e confonderli sarebbe il difetto che si nota per
        # primo: chi non ha **mai** registrato niente va invitato a cominciare,
        # chi ha 443 allenamenti ma nessuno nelle ultime 12 settimane va
        # mandato allo storico, non trattato da nuovo iscritto.
        contesto["ha_dati_in_finestra"] = contesto["volume_totale"] > 0
        contesto["ha_dati_in_assoluto"] = (
            WorkoutSet.objects.working().filter(workout__user=self.request.user).exists()
        )
        # Col toggle il secondo vuoto cambia significato: «fuori finestra» su
        # dodici settimane può essere dentro finestra su dodici mesi, e mandare
        # allo storico chi basterebbe rimandare all'altro taglio sarebbe far
        # uscire dalla pagina qualcuno che la pagina poteva servire. Si chiede
        # **solo** quando serve davvero — cioè quando questa finestra è vuota e
        # l'altra è più larga — e costa una `exists()` in un ramo che di query
        # ne ha già fatte due.
        contesto["altro_taglio"] = analytics_volume.altro_taglio(taglio)
        contesto["altro_taglio_ha_dati"] = (
            contesto["ha_dati_in_assoluto"]
            and not contesto["ha_dati_in_finestra"]
            and contesto["altro_taglio"] is analytics_volume.MESE
            and WorkoutSet.objects.working()
            .filter(
                workout__user=self.request.user,
                workout__started_at__gte=analytics_volume.inizio_della_finestra(
                    contesto["altro_taglio"].finestra()
                ),
            )
            .exists()
        )
        return contesto

    def _toggle(self, scelto):
        """I due link del toggle, col default **senza** parametro nell'URL.

        `/analisi/` e `/analisi/?periodo=mese`, non `?periodo=settimana` e
        `?periodo=mese`: due indirizzi per la stessa pagina di default si
        salverebbero nei preferiti in due forme, e il link canonico dell'header
        ne mostrerebbe una terza. È la regola già presa per i filtri del
        catalogo (#71) — il default è l'assenza.
        """
        base = reverse("training:analysis")
        return [
            {
                "chiave": taglio.chiave,
                "etichetta": f"{analytics_volume.PUNTI_DELLA_FINESTRA} {taglio.plurale}",
                "url": base
                if taglio is analytics_volume.TAGLIO_DI_DEFAULT
                else f"{base}?{self.PARAMETRO_PERIODO}={taglio.chiave}",
                "attivo": taglio is scelto,
            }
            for taglio in analytics_volume.TAGLI
        ]


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
    """`/esercizi/<slug>/` — la pagina più densa del progetto.

    Tre delle sei analisi stanno qui, e insieme rispondono a **una** domanda:
    sto migliorando? A3 la guarda nel tempo, A4 nel proprio passato, A5
    rispetto agli altri — ed è l'unico punto del progetto in cui un utente si
    confronta con qualcuno che non è sé stesso di sei mesi fa. I numeri li
    calcola `training/analytics/progressione.py`; qui si decide **cosa la
    pagina mostra e cosa dichiara di non poter mostrare**.

    Sotto le analisi resta lo **storico grezzo** delle serie, che non è un
    residuo di fase 1: è il dato da cui i numeri sopra sono usciti, ed è anche
    l'unico posto in cui compaiono le serie sopra le 12 ripetizioni — che
    allenano, quindi entrano nel volume, ma non concorrono a un record.

    Un solo grafico, la progressione: **PR e percentile restano numeri**
    (`docs/spec/04-analisi.md`, §I grafici). Un percentile disegnato sarebbe
    una figura da un punto, e un record una linea piatta con sopra un gradino.

    L'URL poggia sullo `slug`, generato una volta da `load_catalog` e non a
    runtime (`training.models.Exercise.slug`): gli URL degli esercizi devono
    restare stabili, perché è da lì che passano i link della progressione.

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

    #: Quante righe di classifica mostrare qui: un assaggio con il link alla
    #: pagina intera, non una seconda classifica.
    RIGHE_DI_CLASSIFICA = 5

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

        # La classifica di forza ridotta alle prime cinque righe (#33): è la
        # stessa tabella della pagina propria, inclusa come partial, non una
        # seconda query scritta apposta. Compare solo se **questo** esercizio è
        # sopra soglia — l'`exists()` è la stessa domanda che il selettore fa
        # per tutti, ristretta a uno.
        contesto_classifica = rankings.esercizi_con_classifica().filter(
            pk=self.object.pk
        )
        if contesto_classifica.exists():
            context["classifica"] = rankings.classifica_forza(self.object)[
                : self.RIGHE_DI_CLASSIFICA
            ]

        analisi = self._analisi()
        context.update(analisi)

        # **Il coach, la seconda e ultima superficie su cui parla** (#113), e
        # da #115 **un** consiglio soltanto: se c'è stallo il carico proposto
        # *è* il deload, altrimenti è la doppia progressione. Due riquadri con
        # due carichi diversi per la stessa domanda sarebbero «dire troppo»
        # (ADR-0007) proprio nella pagina che dovrebbe dimostrare il contrario.
        #
        # Sta **dopo** `_analisi()` di proposito: lo stato di progressione è
        # già stato calcolato lì per il proprio riquadro, e passarlo al coach
        # gli risparmia A3 — è lo stesso patto con cui la dashboard passa la
        # heatmap (#112). Invertire le due righe costerebbe una query e non
        # darebbe niente in cambio.
        #
        # Costa **una** query quando c'è stallo (i carichi della finestra) e
        # **due** altrimenti (le ultime due sessioni): nessuna delle tre cresce
        # con lo storico, che è la guardia che #102 ha misurato su questa
        # pagina.
        #
        # `None` su un esercizio mai registrato — si apre dal catalogo per
        # curiosità — e allora il riquadro non c'è, come sulla dashboard. Lo
        # **stato di progressione**, che è un'altra cosa, resta comunque: dice
        # quanto manca alla soglia invece di tacere (#114).
        context["consiglio"] = analytics_coach.consiglio_per_esercizio(
            self.request.user, self.object, stato=analisi["stato_progressione"]
        )
        return context

    def _analisi(self):
        """A3, A4 e A5 per l'utente che guarda, e i due modi in cui sono vuote.

        A3 si materializza **una volta**: A4 legge le stesse righe, e chiedere
        due volte lo stesso record sarebbe una seconda definizione da tenere
        allineata alla prima (#75).
        """
        righe = list(analytics_progressione.progressione(self.request.user, self.object))

        # Due vuoti diversi, come su `/analisi/`, e qui la differenza è ancora
        # più facile da confondere: chi non ha mai fatto l'esercizio e chi lo
        # fa **solo sopra le 12 ripetizioni** vedono entrambi zero righe, ma il
        # secondo ha uno storico pieno appena sotto nella stessa pagina. Senza
        # dirglielo, la pagina sembrerebbe rotta.
        ha_storico = (
            WorkoutSet.objects.working()
            .filter(workout__user=self.request.user, exercise=self.object)
            .exists()
        )

        # **Lo stato di progressione** (#114), e costa **zero query**: A3 è già
        # materializzata sopra per il grafico, e `stato_progressione` la
        # riceve invece di richiederla. È lo stesso patto con cui la dashboard
        # passa la heatmap al coach (#112).
        stato = analytics_plateau.stato_progressione(
            self.request.user, self.object, righe=righe
        )

        analisi = {
            "progressione": righe,
            "stato_progressione": stato,
            "salti": analytics_progressione.salti(righe),
            "record": analytics_progressione.record_personale(righe),
            "percentile": analytics_progressione.percentile_forza(
                self.request.user, self.object
            ),
            "ha_serie_utili": bool(righe),
            "ha_storico": ha_storico,
            "tetto_ripetizioni": querysets.MAX_REPS_FOR_1RM,
            # Le soglie della finestra in un dizionario solo, e non quattro
            # chiavi di contesto: sono un blocco, si leggono insieme in una
            # frase sola, e un template che le nomini una per una renderebbe
            # più facile aggiungerne una quinta senza accorgersene.
            "soglie": {
                "allenamenti": analytics_plateau.ALLENAMENTI_MINIMI,
                "giorni": analytics_plateau.GIORNI_MINIMI,
                "buco": analytics_plateau.BUCO_MASSIMO_GIORNI,
                "senza_record": analytics_plateau.SESSIONI_SENZA_RECORD_PER_STALLO,
            },
        }

        # Il payload del terzo grafico del progetto, nella stessa forma
        # dichiarativa dei primi due: `static/js/grafici.js` non sa cosa
        # disegna, quindi qui non c'è una riga di JavaScript da aggiungere.
        #
        # Una serie sola, il massimale **di sessione**: il massimo cumulativo
        # sarebbe una seconda linea che il renderer generico non disegna, e
        # soprattutto sarebbe una scala monotona, cioè la figura meno
        # informativa possibile. Il record cumulativo si legge dal numero
        # sopra il grafico, che è dove la spec lo vuole.
        if righe:
            analisi["grafico_progressione"] = {
                "tipo": "line",
                "etichette": [
                    date_format(timezone.localtime(riga["started_at"]), "j M y")
                    for riga in righe
                ],
                "valori": [round(riga["massimale"], 1) for riga in righe],
                "unita": "kg",
                "serie": "Massimale stimato",
            }
        return analisi



class WorkoutListView(LoginRequiredMixin, ListView):
    """`/allenamenti/` — lo storico, e solo il mio.

    Come per le schede il filtro sta nel queryset e non in un `if` di template:
    un template che riceve allenamenti altrui li ha già caricati.

    I due conteggi sono annotazioni e non `count()` nel template, perché la
    lista dello storico cresce senza limite — è l'unica pagina di fase 1 in cui
    una query per riga si farebbe sentire davvero. Entrambe le annotazioni
    passano dallo stesso join su `sets`, quindi non si moltiplicano fra loro.
    """

    model = Workout
    context_object_name = "allenamenti"
    template_name = "training/workout_list.html"

    def get_queryset(self):
        return (
            Workout.objects.filter(user=self.request.user)
            .select_related("routine")
            .annotate(
                n_serie=Count("sets", filter=Q(sets__is_completed=True)),
                n_esercizi=Count("sets__exercise", distinct=True),
            )
        )


class WorkoutDetailView(OwnerRequiredMixin, DetailView):
    """`/allenamenti/<pk>/` — le serie eseguite, raggruppate per esercizio.

    I blocchi si susseguono nell'ordine **in cui gli esercizi sono stati
    davvero affrontati**, non alfabetico: `serie_in_ordine` arriva ordinato
    per `pk`, cioè per ordine di creazione, e `get_context_data` costruisce
    `blocchi` scorrendolo una volta sola — un dict Python preserva l'ordine di
    prima comparsa, quindi la chiave (l'esercizio) entra nel blocco solo alla
    sua prima serie. Dentro il blocco le serie tornano ordinate per
    `set_number`, perché lì l'ordine che conta è «serie 1, 2, 3», non quello
    di inserimento.
    """

    model = Workout
    context_object_name = "allenamento"
    template_name = "training/workout_detail.html"

    def get_queryset(self):
        return Workout.objects.select_related("routine").prefetch_related(
            Prefetch(
                "sets",
                queryset=WorkoutSet.objects.select_related(
                    "exercise__equipment"
                ).order_by("pk"),
                to_attr="serie_in_ordine",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        blocchi = {}
        for serie in self.object.serie_in_ordine:
            blocchi.setdefault(serie.exercise, []).append(serie)
        for lista in blocchi.values():
            lista.sort(key=lambda serie: serie.set_number)
        context["blocchi"] = list(blocchi.items())
        return context


class WorkoutCreateView(LoginRequiredMixin, CreateView):
    """`/allenamenti/nuovo/`, e con `?scheda=<pk>` **«Avvia allenamento da scheda»**.

    È il pezzo che tiene insieme il piano e l'eseguito, ed è una pagina sola,
    un `POST`, zero JavaScript: la scheda arriva in query string, il form nasce
    già intitolato col suo nome, e al salvataggio le serie pianificate
    diventano righe vere, precompilate col carico dell'ultima volta. Da lì
    l'utente corregge i numeri e toglie la spunta a ciò che ha saltato — che è
    il motivo per cui `is_completed` esiste, col significato «eseguita» contro
    «saltata», invece di essere un `reps` nullo e basta.

    Il legame con la scheda si stabilisce **qui e solo qui** (ADR-0002): dopo,
    `title` è un'istantanea e `routine` è `SET_NULL`, quindi rinominare o
    cancellare la scheda non riscrive il passato. Vedi `WorkoutForm`, dove
    `routine` non è un campo proprio per questo.
    """

    model = Workout
    form_class = WorkoutForm
    template_name = "training/workout_form.html"

    #: Il nome del parametro in query string. In italiano come le rotte: il
    #: link `/allenamenti/nuovo/?scheda=3` si legge da solo.
    PARAMETRO_SCHEDA = "scheda"

    #: `?libero=1` è la scelta esplicita «parto senza scheda»: senza uno dei
    #: due parametri la pagina mostra solo il bivio (le card), mai il form —
    #: altrimenti chi arriva su `/allenamenti/nuovo/` per guardare le proprie
    #: schede si troverebbe comunque un form vuoto premuto lì sotto.
    PARAMETRO_LIBERO = "libero"

    def vuole_libero(self):
        return self.request.GET.get(self.PARAMETRO_LIBERO) == "1"

    def get_scheda(self):
        """La scheda da cui partire, se il link ne porta una.

        La proprietà si difende **anche qui**, e allo stesso modo del mixin:
        una scheda che non esiste è 404, una che esiste ma è di un altro è
        403. Il parametro è in query string e non in URL, quindi
        `UserPassesTestMixin` non lo copre — `get_object` di questa view
        restituirebbe l'allenamento, che ancora non esiste.
        """
        grezzo = self.request.GET.get(self.PARAMETRO_SCHEDA)
        if not grezzo or not grezzo.isdigit():
            return None

        scheda = get_object_or_404(
            Routine.objects.prefetch_related("exercises__exercise__equipment"),
            pk=int(grezzo),
        )
        if scheda.user != self.request.user:
            raise PermissionDenied

        return scheda

    def get_initial(self):
        initial = super().get_initial()
        # `localtime` e non `now`: i campi `date`/`time` mostrano l'ora del
        # fuso corrente, e proporre l'UTC significherebbe proporre due ore
        # sbagliate d'estate.
        adesso = timezone.localtime()
        initial["giorno"] = adesso.date()
        initial["ora_inizio"] = adesso.time()

        scheda = self.get_scheda()
        if scheda is not None:
            initial["title"] = scheda.name
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scheda = self.get_scheda()
        context["scheda"] = scheda
        context["libero"] = self.vuole_libero()
        # Il form si mostra per una scelta esplicita — una scheda, «libero» —
        # o perché la pagina **è già** un POST: un errore di validazione deve
        # tornare sul form coi suoi messaggi, mai regredire al bivio.
        context["mostra_form"] = (
            scheda is not None
            or context["libero"]
            or self.request.method == "POST"
        )
        # Il bivio si mostra solo finché non se n'è presa una delle due
        # strade — una scheda scelta o «allenamento libero» esplicito: una
        # volta scelta, la pagina è già sul form e rimostrare le card sarebbe
        # un secondo bivio dopo che il primo è già stato preso.
        if not context["mostra_form"]:
            context["schede_disponibili"] = Routine.objects.filter(
                user=self.request.user
            ).order_by("name")
        return context

    def form_valid(self, form):
        scheda = self.get_scheda()

        form.instance.user = self.request.user
        form.instance.routine = scheda

        # L'allenamento e le sue serie nascono insieme o non nascono: un
        # allenamento «avviato da scheda» rimasto senza righe sarebbe la cosa
        # peggiore da trovare, perché sembra vuoto invece che rotto.
        with transaction.atomic():
            response = super().form_valid(form)
            if scheda is not None:
                serie = self.serie_dalla_scheda(scheda)
                WorkoutSet.objects.bulk_create(serie)

        if scheda is not None:
            messages.success(
                self.request,
                f"Allenamento avviato da «{scheda.name}»: le serie sono "
                "precompilate, correggi i numeri veri.",
            )
        else:
            messages.success(
                self.request, "L'allenamento è creato. Ora mettici le serie."
            )
        return response

    def serie_dalla_scheda(self, scheda):
        """Le righe pianificate, con il carico dell'ultima volta.

        Due regole di precompilazione, e nessuna delle due inventa un dato:

        - il **carico** è l'ultimo che l'utente ha davvero usato su
          quell'esercizio; in mancanza è `default_bar_weight_kg`, cioè
          l'attrezzo scarico, che è il minimo vero e non una stima;
        - le **ripetizioni** sono l'estremo *basso* del bersaglio, perché è la
          promessa che la scheda fa, mentre l'estremo alto è ciò che la doppia
          progressione insegue e va conquistato, non precompilato.

        Tutto è comunque modificabile nella pagina delle serie: questi valori
        sono un punto di partenza, e il loro compito è ridurre la digitazione,
        non decidere lo storico.
        """
        voci = list(scheda.exercises.all())
        ultimi = self.ultimo_carico_per_esercizio(voci)

        serie = []
        for voce in voci:
            peso = ultimi.get(
                voce.exercise_id, voce.exercise.equipment.default_bar_weight_kg
            )
            # `target_sets` è positivo per modello, ma `target_reps` a zero
            # passerebbe il database e violerebbe poi
            # `workout_set_completed_has_reps`: una riga senza ripetizioni nasce
            # **saltata**, che è l'unica lettura coerente e non un 500.
            reps = voce.target_reps or None
            for numero in range(1, voce.target_sets + 1):
                serie.append(
                    WorkoutSet(
                        workout=self.object,
                        exercise=voce.exercise,
                        set_number=numero,
                        reps=reps,
                        weight=peso,
                        set_type=WorkoutSet.SetType.WORKING,
                        is_completed=reps is not None,
                    )
                )
        return serie

    def ultimo_carico_per_esercizio(self, voci):
        """`{exercise_id: peso}` in **una query**, non una per esercizio.

        Le serie arrivano ordinate dalla più vecchia alla più recente e il
        dizionario si sovrascrive: l'ultima scritta vince, ed è per costruzione
        la più recente. Un `Subquery` per esercizio direbbe la stessa cosa con
        più codice e la stessa query in più per riga.

        Si guardano solo le serie **eseguite**: il carico di una serie saltata
        è un'intenzione, non un dato, e ripartire da lì significherebbe
        propagare in avanti un numero che non è mai stato sollevato.
        """
        esercizi = [voce.exercise_id for voce in voci]
        if not esercizi:
            return {}

        ultimi = {}
        for exercise_id, peso in (
            WorkoutSet.objects.filter(
                workout__user=self.request.user,
                exercise_id__in=esercizi,
                is_completed=True,
                weight__isnull=False,
            )
            .order_by("workout__started_at", "set_number")
            .values_list("exercise_id", "weight")
        ):
            ultimi[exercise_id] = peso
        return ultimi

    def get_success_url(self):
        # Chi crea un allenamento atterra sulle serie, non sulla lista: come
        # per le schede, il passo successivo è l'unico che abbia senso — con
        # la differenza che qui, se si è partiti da una scheda, le righe sono
        # già lì e la pagina è di correzione, non di compilazione.
        return reverse("training:workoutset-manage", args=[self.object.pk])


def raggruppa_serie_del_formset(formset):
    """`blocchi`/`extra_forms` per un `WorkoutSetFormSet`, in un posto solo.

    La usano sia `WorkoutUpdateView` sia `WorkoutSetsView`: stessa regola di
    `WorkoutDetailView` applicata a un formset invece che a un queryset — le
    righe con un `pk` si raggruppano per esercizio e dentro il gruppo tornano
    ordinate per `set_number`, le righe nuove (senza `pk`, quelle in coda per
    l'esercizio fuori programma) restano a parte. Scritta due volte questa
    regola diverge al primo ripensamento (#75), e le due pagine smetterebbero
    di concordare su cosa vuol dire «raggruppato».
    """
    blocchi = {}
    extra_forms = []
    for riga in formset.forms:
        if riga.instance.pk:
            blocchi.setdefault(riga.instance.exercise, []).append(riga)
        else:
            extra_forms.append(riga)
    for righe in blocchi.values():
        righe.sort(key=lambda riga: riga.instance.set_number)
    return list(blocchi.items()), extra_forms


class WorkoutUpdateView(OwnerRequiredMixin, SingleObjectMixin, View):
    """`/allenamenti/<pk>/modifica/` — titolo *e* serie, sulla stessa pagina.

    È la vista di correzione unica: la stessa disposizione a card per
    esercizio di `WorkoutDetailView`, ma coi valori dentro un `<input>` invece
    che in testo. `form` porta titolo, orari e note; `WorkoutSetFormSet`
    porta le serie. Sono due form indipendenti sulla stessa `<form>` HTML e si
    salvano solo se **entrambi** sono validi — altrimenti l'allenamento
    finirebbe con un titolo nuovo e serie scartate, o viceversa.

    Il raggruppamento in `blocchi` ricalca quello della vista di lettura:
    stesso ordine cronologico di prima comparsa, stesso ordinamento per
    `set_number` dentro il blocco, così chi clicca «Modifica» ritrova
    esattamente la pagina che stava guardando, solo editabile. Le righe senza
    `pk` — quelle in coda del formset, per l'esercizio aggiunto fuori
    programma — non hanno ancora un esercizio con cui raggrupparle, e restano
    a parte in `extra_forms`.
    """

    model = Workout
    template_name = "training/workout_form.html"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = WorkoutForm(instance=self.object)
        formset = WorkoutSetFormSet(
            instance=self.object,
            queryset=self.object.sets.select_related("exercise__equipment").order_by(
                "pk"
            ),
        )
        return self.render_to_response(form, formset)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = WorkoutForm(request.POST, instance=self.object)
        formset = WorkoutSetFormSet(request.POST, instance=self.object)

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "L'allenamento è aggiornato.")
            return redirect("training:workout-detail", pk=self.object.pk)

        return self.render_to_response(form, formset)

    def render_to_response(self, form, formset):
        blocchi, extra_forms = raggruppa_serie_del_formset(formset)

        context = {
            "allenamento": self.object,
            "form": form,
            "formset": formset,
            "blocchi": blocchi,
            "extra_forms": extra_forms,
        }
        return render(self.request, self.template_name, context)


class WorkoutDeleteView(OwnerRequiredMixin, DeleteView):
    """`/allenamenti/<pk>/elimina/` — e qui si perde davvero qualcosa.

    È l'asimmetria di ADR-0002 vista dall'altro lato: cancellare una *scheda*
    non tocca gli allenamenti, perché il log è immutabile; cancellare un
    *allenamento* porta via le sue serie in `CASCADE`, e quei numeri non stanno
    da nessun'altra parte. La pagina di conferma lo dice col conto delle serie.
    """

    model = Workout
    context_object_name = "allenamento"
    template_name = "training/workout_confirm_delete.html"
    success_url = reverse_lazy("training:workout-list")

    def form_valid(self, form):
        messages.success(self.request, f"«{self.object.title}» è eliminato.")
        return super().form_valid(form)


class WorkoutSetsView(OwnerRequiredMixin, UpdateView):
    """`/allenamenti/<pk>/serie/` — il registro delle serie.

    Stessa forma della gestione esercizi di una scheda, `fields = []` compreso
    e per la stessa ragione: la pagina non modifica l'allenamento, modifica le
    sue righe figlie, e `UpdateView` porta già `get_object`, il 403 del mixin e
    il template.

    Ciò che cambia è la densità. Qui le righe sono quante sono le serie di una
    sessione — dieci, quindici — e per questo la pagina esiste soprattutto come
    pagina di **correzione**: chi è partito da una scheda le trova già scritte
    (`WorkoutCreateView`), tocca i numeri che non tornano e toglie la spunta a
    ciò che ha saltato.

    Il raggruppamento in `blocchi` è lo stesso di `WorkoutUpdateView`
    (`raggruppa_serie_del_formset`): la scheda precompila le serie un
    esercizio alla volta, tutte le sue ripetizioni di fila, e l'ordinamento di
    default del modello (`set_number`) le rimescolerebbe — prima tutte le
    serie 1 di ogni esercizio, poi tutte le serie 2. `order_by("pk")` qui sotto
    tiene l'ordine di creazione, che è l'ordine della scheda.

    A differenza di `WorkoutUpdateView` questa pagina non mostra «Eseguita»:
    qui una serie o si registra (con le sue ripetizioni) o si toglie col
    cestino, e «saltata ma ancora pianificata» — il terzo stato che
    «Eseguita» rappresenta altrove — non è un caso che passi da qui. Il campo
    resta nel modello e nel form, solo nascosto (`is_completed.as_hidden`):
    le righe già salvate mantengono il loro valore vero, quelle nuove nascono
    a `True` come sempre.

    Il bottone «+» di un blocco è un secondo submit sulla stessa `<form>`,
    gestito da `_dati_con_riga_extra`: senza JavaScript un «aggiungi riga»
    dinamico non esiste, ma un giro di pagina che aggiunge una riga ai dati
    del POST e ricostruisce il formset — senza salvarlo — sì. Il cestino di
    ogni riga è un terzo submit costruito allo stesso modo
    (`_dati_con_riga_da_togliere`): non è una casella «Togli» da spuntare e
    salvare dopo, è un bottone che segna subito quella riga come da togliere
    — la riga sparisce dalla pagina immediatamente — e resta comunque solo
    marcata (`DELETE`), non cancellata dal database, finché non arriva un
    «Salva le serie» vero.
    """

    model = Workout
    fields = []
    context_object_name = "allenamento"
    template_name = "training/workout_sets.html"

    #: Il nome del bottone «+ Serie» di un blocco: il valore è il pk
    #: dell'esercizio a cui la riga nuova appartiene.
    PARAMETRO_AGGIUNGI = "aggiungi_serie"

    #: Il nome del bottone «cestino» di una riga: il valore è il `prefix` di
    #: quella riga nel formset (`sets-3`), non il suo `pk` — serve anche per
    #: una riga appena aggiunta dal «+» e mai salvata.
    PARAMETRO_RIMUOVI = "rimuovi_serie"

    def get_formset_queryset(self):
        return self.object.sets.select_related("exercise__equipment").order_by("pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Se il POST è fallito il formset in contesto è quello con gli errori e
        # i dati dell'utente: ricostruirlo li perderebbe.
        formset = context.get("formset") or WorkoutSetFormSet(
            instance=self.object, queryset=self.get_formset_queryset()
        )
        context["formset"] = formset
        context.setdefault("mostra_errori", True)
        blocchi, extra_forms = raggruppa_serie_del_formset(formset)
        blocchi, extra_forms = self._assegna_extra_ai_blocchi(blocchi, extra_forms)
        blocchi, extra_forms, righe_nascoste = self._togli_le_marcate(
            blocchi, extra_forms
        )
        context["blocchi"] = blocchi
        context["extra_forms"] = extra_forms
        context["righe_nascoste"] = righe_nascoste
        return context

    @staticmethod
    def _assegna_extra_ai_blocchi(blocchi, extra_forms):
        """Le righe extra il cui `exercise` punta già a un blocco tornano lì.

        È il caso di una riga nata dal bottone «+»: non ha `pk`, quindi
        `raggruppa_serie_del_formset` la vedrebbe come «fuori programma», ma
        il suo `exercise` è già quello di un blocco esistente, ed è lì che
        deve comparire — non in coda insieme alle righe davvero senza
        esercizio.
        """
        per_esercizio = {esercizio.pk: (esercizio, righe) for esercizio, righe in blocchi}
        rimaste = []
        for riga in extra_forms:
            valore = riga["exercise"].value()
            pk_scelto = int(valore) if valore else None
            if pk_scelto in per_esercizio:
                per_esercizio[pk_scelto][1].append(riga)
            else:
                rimaste.append(riga)
        return list(per_esercizio.values()), rimaste

    @staticmethod
    def _togli_le_marcate(blocchi, extra_forms):
        """Le righe col cestino già premuto spariscono dalla pagina.

        Restano nel formset — `DELETE` è ancora `True` nei loro dati, ed è
        quello che alla fine il «Salva le serie» leggerà — ma non fra le
        righe che si vedono: `righe_nascoste` le porta avanti come soli campi
        `hidden`, così un altro giro di pagina (un secondo «+», un altro
        cestino) non le fa riapparire né le perde.
        """
        nascoste = []

        blocchi_visibili = []
        for esercizio, righe in blocchi:
            visibili = [riga for riga in righe if not riga["DELETE"].value()]
            nascoste.extend(riga for riga in righe if riga["DELETE"].value())
            if visibili:
                blocchi_visibili.append((esercizio, visibili))

        extra_visibili = [riga for riga in extra_forms if not riga["DELETE"].value()]
        nascoste.extend(riga for riga in extra_forms if riga["DELETE"].value())

        return blocchi_visibili, extra_visibili, nascoste

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()

        if self.PARAMETRO_AGGIUNGI in request.POST:
            formset = WorkoutSetFormSet(
                self._dati_con_riga_extra(request.POST), instance=self.object
            )
            # Non è un tentativo di salvataggio: mostrare gli errori qui
            # segnalerebbe alla riga appena nata, ancora vuota, che le
            # mancano le ripetizioni prima che l'utente abbia potuto
            # scriverle.
            return self.render_to_response(
                self.get_context_data(formset=formset, mostra_errori=False)
            )

        if self.PARAMETRO_RIMUOVI in request.POST:
            formset = WorkoutSetFormSet(
                self._dati_con_riga_da_togliere(request.POST), instance=self.object
            )
            return self.render_to_response(
                self.get_context_data(formset=formset, mostra_errori=False)
            )

        formset = WorkoutSetFormSet(request.POST, instance=self.object)

        if not formset.is_valid():
            return self.render_to_response(self.get_context_data(formset=formset))

        formset.save()
        messages.success(request, "Le serie dell'allenamento sono aggiornate.")
        return redirect("training:workout-detail", pk=self.object.pk)

    def _dati_con_riga_da_togliere(self, post):
        """I dati del POST con `DELETE` marcato sulla riga del cestino premuto.

        Stessa idea di `_dati_con_riga_extra`, alla rovescia: non aggiunge
        niente, marca una riga sola. Il valore del bottone è il `prefix`
        della riga (`sets-3`), scritto dal template con `riga.prefix`, non il
        suo `pk` — funziona identico per una riga già salvata e per una
        appena nata dal «+», che un `pk` non ce l'ha ancora.
        """
        dati = post.copy()
        prefisso_riga = post[self.PARAMETRO_RIMUOVI]
        dati[f"{prefisso_riga}-DELETE"] = "on"
        return dati

    def _dati_con_riga_extra(self, post):
        """I dati del POST con una riga vuota in più per l'esercizio del «+».

        Non salva niente: prende gli stessi dati che l'utente ha già scritto
        nelle altre righe, ci aggiunge una riga nuova numerata dopo l'ultima
        serie di quell'esercizio e col carico dell'ultima come punto di
        partenza, e alza `TOTAL_FORMS` di conseguenza. Il formset che nasce
        da questi dati è bound ma non viene mai validato né salvato qui: la
        pagina si limita a ridisegnarsi con la riga in più, e il salvataggio
        vero resta un giro di «Salva le serie» a parte.
        """
        prefix = WorkoutSetFormSet.get_default_prefix()
        dati = post.copy()
        esercizio_id = post[self.PARAMETRO_AGGIUNGI]
        totale = int(dati[f"{prefix}-TOTAL_FORMS"])

        numeri = []
        pesi = []
        for indice in range(totale):
            if dati.get(f"{prefix}-{indice}-exercise") != esercizio_id:
                continue
            numero = dati.get(f"{prefix}-{indice}-set_number", "")
            if numero.isdigit():
                numeri.append(int(numero))
            peso = dati.get(f"{prefix}-{indice}-weight")
            if peso:
                pesi.append(peso)

        nuovo = totale
        dati[f"{prefix}-{nuovo}-id"] = ""
        dati[f"{prefix}-{nuovo}-exercise"] = esercizio_id
        dati[f"{prefix}-{nuovo}-set_number"] = str(max(numeri, default=0) + 1)
        dati[f"{prefix}-{nuovo}-reps"] = ""
        dati[f"{prefix}-{nuovo}-weight"] = pesi[-1] if pesi else ""
        dati[f"{prefix}-{nuovo}-set_type"] = WorkoutSet.SetType.WORKING
        dati[f"{prefix}-{nuovo}-is_completed"] = "on"
        dati[f"{prefix}-TOTAL_FORMS"] = str(totale + 1)
        return dati


class WorkoutSaveAsRoutineView(OwnerRequiredMixin, SingleObjectMixin, View):
    """`/allenamenti/<pk>/scheda/`, `POST` soltanto — «vuoi salvarlo come scheda?»

    Nasce per l'allenamento **libero**: quello scritto a mano, senza `routine`.
    Da qui esce una scheda nuova, con un `RoutineExercise` per ogni esercizio
    di lavoro dell'allenamento, nell'ordine in cui compaiono e coi bersagli
    dedotti dalle serie davvero fatte — le ripetizioni minime e massime
    osservate, le serie contate.

    Quello che **non** succede è impostare `allenamento.routine` sulla scheda
    appena nata: significherebbe stabilire il legame *dopo* che l'allenamento
    è nato, ed è proprio ciò che `WorkoutForm` e `WorkoutCreateView` escludono
    per ADR-0002 — il legame si stabilisce una volta sola, alla nascita
    dell'allenamento. Da questa azione esce solo la scheda: un punto di
    partenza per la prossima volta, non una riscrittura del log.
    """

    model = Workout
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        allenamento = self.object

        nome = request.POST.get("nome", "").strip() or allenamento.title
        serie_di_lavoro = list(
            allenamento.sets.filter(
                set_type=WorkoutSet.SetType.WORKING, is_completed=True
            )
            .select_related("exercise")
            .order_by("pk")
        )
        if not serie_di_lavoro:
            messages.error(
                request,
                "Questo allenamento non ha serie di lavoro completate: non "
                "c'è niente da mettere in scheda.",
            )
            return redirect("training:workout-detail", pk=allenamento.pk)

        # Un dict preserva l'ordine di prima comparsa: è così che l'ordine
        # degli esercizi nella scheda nuova ricalca quello dell'allenamento,
        # senza una lista separata a tenerne il conto.
        per_esercizio = {}
        for serie in serie_di_lavoro:
            voce = per_esercizio.setdefault(
                serie.exercise_id, {"exercise": serie.exercise, "reps": []}
            )
            voce["reps"].append(serie.reps)

        with transaction.atomic():
            scheda = Routine.objects.create(user=request.user, name=nome)
            RoutineExercise.objects.bulk_create(
                RoutineExercise(
                    routine=scheda,
                    exercise=voce["exercise"],
                    position=posizione,
                    target_sets=len(voce["reps"]),
                    target_reps=min(voce["reps"]),
                    target_reps_max=(
                        max(voce["reps"])
                        if max(voce["reps"]) != min(voce["reps"])
                        else None
                    ),
                )
                for posizione, voce in enumerate(per_esercizio.values(), start=1)
            )

        messages.success(
            request, f"«{scheda.name}» è creata dalle serie di questo allenamento."
        )
        return redirect("training:routine-detail", pk=scheda.pk)


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


#: La chiave con cui i tre passi dell'import si passano i nomi dei file
#: depositati. Sta in `request.session` e **non** contiene dati: contiene dove
#: trovarli, che è tutta la differenza fra tenere in sessione un puntatore e
#: tenerci ~100 KB di JSON parsato (`03-import-ed-export.md`).
CHIAVE_IMPORT = "import_csv"
CHIAVE_ESITO = "import_csv_esito"


def deposito():
    """`MEDIA_ROOT/imports/`, dove il file aspetta fra anteprima e conferma.

    È una funzione e non una costante di modulo perché `MEDIA_ROOT` si
    sovrascrive nei test: uno storage costruito all'import del modulo
    punterebbe alla cartella vera anche dentro un `override_settings`, e
    lascerebbe file di prova nel repo.
    """
    return FileSystemStorage(location=Path(settings.MEDIA_ROOT) / "imports")


class ImportUploadView(LoginRequiredMixin, FormView):
    """`/import/` — primo dei **tre URL**, e il primo è la scelta dei file.

    Tre URL e non una vista con tre rami dentro `post()`: quella è la forma che
    poi non si riesce a spiegare, perché lo stato del passo vive dentro un `if`
    invece che nell'indirizzo. Qui ogni passo ha il suo indirizzo, il suo
    template e la sua responsabilità — si carica, si abbina, si legge l'esito.

    Questo è il canale **utente** del requisito «data import», e non sostituisce
    `load_catalog`: quello è il canale amministratore, un management command
    che carica il catalogo globale. I due hanno pubblici diversi e la traccia
    li conta entrambi (`03-import-ed-export.md`).
    """

    form_class = ImportUploadForm
    template_name = "training/import_upload.html"

    def form_valid(self, form):
        # I file vanno su disco, non in sessione. Il nome depositato è quello
        # che `FileSystemStorage` restituisce dopo aver risolto le collisioni:
        # due import contemporanei dello stesso file non si sovrascrivono.
        archivio = deposito()
        depositati = {}
        for campo in ("sessioni", "serie", "esercizi"):
            caricato = form.cleaned_data.get(campo)
            if caricato:
                depositati[campo] = archivio.save(f"{uuid4()}.csv", caricato)

        self.request.session[CHIAVE_IMPORT] = depositati
        return redirect("training:import-preview")


class ImportPreviewView(LoginRequiredMixin, FormView):
    """`/import/anteprima/` — **e l'anteprima è un form**, non una schermata.

    È il punto in cui l'import chiede qualcosa invece di limitarsi a informare,
    ed è la conseguenza diretta di ADR-0010: i nomi che il file porta non si
    risolvono da soli — sui 24 nomi reali dello storico la normalizzazione
    automatica non ne indovina quasi nessuno — quindi l'abbinamento lo fa
    l'utente, con un suggerimento accanto e una `<select>` per correggerlo.

    La pagina mostra **cinque cose**, e le prime due sono le uniche su cui si
    agisce, quindi stanno in cima: il riepilogo e la tabella di abbinamento.
    Righe in errore, avvisi e duplicati sono resoconto, e stanno sotto.

    I file si **rileggono da disco** a ogni passaggio, in GET come in POST:
    niente tabella di staging, che sarebbe stata due modelli in più senza
    nessun requisito pagato, e niente parsato in sessione. Il costo è una
    seconda lettura di ~60 KB; il guadagno è che non esiste uno stato
    intermedio da tenere allineato.
    """

    form_class = AbbinamentoFormSet
    template_name = "training/import_preview.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)

        if not request.session.get(CHIAVE_IMPORT):
            messages.error(
                request, "Non c'è nessun file da controllare: ricomincia da qui."
            )
            return redirect("training:import-upload")

        try:
            # `lettura` è una `cached_property`: la si tocca qui perché un
            # formato illeggibile è un errore del **file**, e la risposta
            # giusta è rimandare all'upload — non renderizzare un'anteprima
            # vuota che non dice cosa non va.
            self.lettura
        except FormatoNonValido as errore:
            messages.error(request, str(errore))
            return redirect("training:import-upload")
        except FileNotFoundError:
            request.session.pop(CHIAVE_IMPORT, None)
            messages.error(
                request, "I file caricati non ci sono più: ricomincia da qui."
            )
            return redirect("training:import-upload")

        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def lettura(self):
        archivio = deposito()
        depositati = self.request.session[CHIAVE_IMPORT]
        aperti = []
        try:
            for campo in ("sessioni", "serie", "esercizi"):
                nome = depositati.get(campo)
                aperti.append(archivio.open(nome) if nome else None)
            return leggi(*aperti, user=self.request.user)
        finally:
            for file in aperti:
                if file is not None:
                    file.close()

    @cached_property
    def abbinamenti(self):
        """Il taglio fra ciò che è già risolto e ciò che si chiede."""
        return risolvi(self.lettura.nomi_grezzi, self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        _, da_chiedere = self.abbinamenti
        kwargs["initial"] = [
            {"raw_name": nome, "exercise": suggerito}
            for nome, suggerito in da_chiedere
        ]
        return kwargs

    def get_context_data(self, **kwargs):
        contesto = super().get_context_data(**kwargs)
        lettura = self.lettura
        risolti, _ = self.abbinamenti
        inizio, fine = lettura.periodo

        contesto["lettura"] = lettura
        contesto["risolti"] = sorted(risolti.items())
        contesto["dal"] = inizio
        contesto["al"] = fine
        contesto["valide_serie"] = len(lettura.serie)
        contesto["valide_sessioni"] = len(lettura.sessioni)
        return contesto

    def form_valid(self, formset):
        risolti, _ = self.abbinamenti
        scelti = {
            form.cleaned_data["raw_name"]: form.cleaned_data["exercise"]
            for form in formset
        }

        # Solo le scelte **fatte a mano** diventano alias: quelle risolte per
        # nome esatto non hanno niente da ricordare, e scriverle produrrebbe
        # una riga per ogni esercizio del catalogo al primo import di un file
        # esportato da Progressive stesso.
        ricorda(scelti, self.request.user)

        esito = scrivi(self.lettura, {**risolti, **scelti}, self.request.user)

        self.request.session[CHIAVE_ESITO] = esito.as_dict()
        self.pulisci()
        return redirect("training:import-result")

    def pulisci(self):
        """Il deposito non è un archivio: finito l'import, i file se ne vanno.

        Se restassero, `MEDIA_ROOT/imports/` crescerebbe di un file per ogni
        anteprima aperta, compresi gli import abbandonati a metà — che è il
        prezzo nascosto della scelta «file su disco», e si paga qui.
        """
        archivio = deposito()
        for nome in self.request.session.pop(CHIAVE_IMPORT, {}).values():
            archivio.delete(nome)


class ImportResultView(LoginRequiredMixin, TemplateView):
    """`/import/esito/` — cosa è entrato davvero.

    L'esito arriva dalla sessione e si **consuma**: ricaricare la pagina non
    ripete l'import, e non lo ripete nemmeno un tasto «indietro», perché la
    scrittura è avvenuta nel POST dell'anteprima e questa è una GET dopo una
    redirect. È il motivo per cui i tre passi sono tre URL.
    """

    template_name = "training/import_result.html"

    def get_context_data(self, **kwargs):
        contesto = super().get_context_data(**kwargs)
        contesto["esito"] = self.request.session.pop(CHIAVE_ESITO, None)
        return contesto


class ExportCsvView(LoginRequiredMixin, View):
    """`/export/<quale>/` — `storico` (uno zip) ed `esercizi` (il catalogo).

    **Il giro si chiude qui.** Finché Progressive sapeva solo leggere quel
    formato, il formato era di un'altra app e nessuno tranne Lorenzo poteva
    produrne uno; da qui in avanti Progressive è **uno dei produttori** del
    proprio formato, e chi si iscrive oggi ha qualcosa da reimportare domani.

    **Un solo file per lo storico, non due.** `workout_sessions.csv` e
    `session_sets.csv` sono due risorse diverse — due tabelle, due
    intestazioni — ma l'import le vuole sempre insieme nello stesso POST, e
    uno senza l'altro non basta a reimportare niente: due download separati
    non pagavano nessun caso d'uso reale, solo un click in più. `storico`
    quindi è uno `.zip` con entrambi dentro; il catalogo resta un file a
    parte perché non è storico di nessuno, è lo stesso per ogni utente.

    L'export **non scrive niente**: il `nome_pubblico` di una riga nata in-app
    si calcola, quindi qui non c'è nessun effetto da nascondere dietro una GET.
    """

    def get(self, request, quale):
        if quale not in FILE_EXPORT:
            raise Http404("Non c'è nessun file con questo nome.")

        if quale == "storico":
            risposta = HttpResponse(
                esporta_zip(request.user), content_type="application/zip"
            )
        else:
            risposta = HttpResponse(content_type="text/csv; charset=utf-8")
            esporta_esercizi(risposta)

        risposta["Content-Disposition"] = (
            f'attachment; filename="{FILE_EXPORT[quale]}"'
        )
        return risposta


# --- Le due classifiche ---------------------------------------------------
#
# Il requisito «display results or rankings» della traccia, pagato **due volte
# e in due modi**: una graduatoria di persone su un esercizio, e una di schede
# per giudizio. Che siano di natura diversa non è un vezzo — è ciò che rende la
# seconda non una copia della prima.
#
# Le query non stanno qui ma in `training/rankings.py`, che non conosce HTTP:
# stessa scelta di `importer.py`, perché ciò che va provato riga per riga sono
# i numeri e non l'HTML che li mostra. Qui restano le tre decisioni che *sono*
# di presentazione: quale esercizio si guarda, quante righe per pagina, quale
# riga è la tua.


class RankingStrengthView(LoginRequiredMixin, ListView):
    """`/classifiche/forza/` — la forza relativa su un esercizio, di sempre.

    **Non esiste una classifica di forza generale**, e la ragione è misurata,
    non stimata: un punteggio composito sui tre fondamentali escluderebbe 45
    utenti su 100, perché panca, squat e stacco compaiono insieme in soli 55
    storici (`docs/spec/00-indice.md`, §Confini). Esiste quindi una classifica
    **per esercizio**, e il selettore offre solo quelli la cui popolazione
    supera la soglia: un esercizio che poi dice «dati insufficienti» sarebbe un
    vicolo cieco messo nel menu apposta.

    Senza `?esercizio=`, si apre il **più praticato**: è la classifica più
    piena, quindi quella che dimostra meglio la pagina, e ordinare il selettore
    per popolazione rende la scelta del default una conseguenza dell'ordine
    invece di una seconda regola.

    `Paginator` a 25 righe. Qui la paginazione ha senso e sulla lista degli
    esercizi non ne aveva (#71): 100 esercizi sono un numero chiuso, gli utenti
    di una classifica no.
    """

    template_name = "training/ranking_strength.html"
    context_object_name = "righe"
    paginate_by = 25

    @cached_property
    def esercizi_ammessi(self):
        """Gli esercizi sopra soglia, una volta sola per richiesta.

        Sono letti due volte — per il selettore e per risolvere `?esercizio=` —
        e senza `cached_property` sarebbero due query identiche.
        """
        return list(rankings.esercizi_con_classifica())

    @cached_property
    def esercizio(self):
        """L'esercizio guardato, scelto per **slug** e non per `pk`.

        È la stessa regola dei filtri del catalogo (#71): `?esercizio=panca-piana`
        si legge, si salva nei preferiti e sopravvive a un ricaricamento del
        catalogo, mentre una chiave primaria no.

        Uno slug che non è in soglia non è un errore da 404: è una domanda
        legittima con una risposta legittima — quella classifica non c'è — e la
        pagina ricade sul default invece di sbattere una porta.
        """
        slug = self.request.GET.get("esercizio")
        if slug:
            for esercizio in self.esercizi_ammessi:
                if esercizio.slug == slug:
                    return esercizio
        return self.esercizi_ammessi[0] if self.esercizi_ammessi else None

    def get_queryset(self):
        if self.esercizio is None:
            return WorkoutSet.objects.none()
        return rankings.classifica_forza(self.esercizio)

    def get_context_data(self, **kwargs):
        contesto = super().get_context_data(**kwargs)
        contesto["esercizi"] = self.esercizi_ammessi
        contesto["esercizio"] = self.esercizio
        contesto["soglia_utenti"] = rankings.MIN_USERS_FOR_COMPARISON
        contesto["min_allenamenti"] = rankings.MIN_WORKOUTS_FOR_RANKING
        # Il peso corporeo non è un dettaglio del profilo: senza, non esiste
        # forza relativa e l'utente **non compare** (ADR-0008). Dirglielo qui è
        # l'unico modo perché la sua assenza dalla classifica si legga come una
        # condizione e non come un guasto.
        contesto["senza_peso"] = not self.request.user.has_body_mass
        return contesto


class RankingSocialView(LoginRequiredMixin, ListView):
    """`/classifiche/schede/` — le schede pubbliche per media bayesiana.

    Ordina **schede** e non utenti: è questo a renderla di natura diversa dalla
    classifica di forza, ed è la ragione per cui il requisito della traccia si
    considera pagato due volte e in due modi.

    Il punteggio è la media smorzata verso la media globale di tutti i voti
    (`training.rankings.classifica_sociale`), e non la media grezza: con la
    media grezza una scheda con un solo 5 starebbe in testa per sempre. È la
    stessa ragione per cui la community (#72) resta **cronologica** — ordinare
    è un atto che va dichiarato, e si dichiara qui.

    Media grezza e numero di voti restano in colonna: il punteggio che ordina
    dev'essere ispezionabile, o la pagina chiede di fidarsi.
    """

    template_name = "training/ranking_social.html"
    context_object_name = "righe"
    paginate_by = 25

    def get_queryset(self):
        return rankings.classifica_sociale()

    def get_context_data(self, **kwargs):
        contesto = super().get_context_data(**kwargs)
        contesto["media_globale"] = rankings.media_globale_dei_voti()
        contesto["prior"] = rankings.C_PRIOR_VOTI
        contesto["min_esercizi"] = rankings.MIN_EXERCISES_FOR_RANKING
        contesto["mie_schede"] = rankings.schede_pubbliche_di(self.request.user)
        return contesto
