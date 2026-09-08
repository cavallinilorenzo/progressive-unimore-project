"""I form di Progressive.

Il primo arriva con l'autenticazione: `UserCreationForm` non può restare quello
di `django.contrib.auth` così com'è, perché è legato al modello utente di
Django e qui l'utente è `training.User` (ADR-0003). Django prevede il caso —
si sottoclassa e si punta `Meta.model` al modello del progetto — ed è la sola
conseguenza pratica del custom user model in fase 1, quella da saper spiegare
all'orale insieme alla riga `AUTH_USER_MODEL` di `config/settings.py`.
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.functional import cached_property

from training import importer
from training.models import (
    Exercise,
    Routine,
    RoutineExercise,
    User,
    Vote,
    Workout,
    WorkoutSet,
)


class SignUpForm(UserCreationForm):
    """La registrazione: username e password, niente di più.

    Il peso corporeo **non** sta qui, ed è una scelta: è facoltativo per
    progetto (ADR-0008), e chiederlo alla registrazione lo farebbe sembrare
    obbligatorio o, peggio, invoglierebbe a inventarlo. Si dichiara dal
    profilo, dove la pagina può spiegare a cosa serve.
    """

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)

    def __init__(self, *args, **kwargs):
        """I widget di `UserCreationForm` nascono senza classi Bootstrap.

        Il template rende i campi in ciclo — sono tre e cambiano da una
        versione di Django all'altra — quindi la classe si mette qui una volta
        sola invece di riscrivere ogni `<input>` a mano nel template.
        """
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class ProfileForm(forms.ModelForm):
    """`/profilo/`: l'unico campo di dominio che l'utente porta su di sé.

    `body_mass_kg` resta facoltativo anche qui, e svuotarlo è una risposta
    valida: riporta l'utente fuori dalle graduatorie, che è esattamente ciò
    che ADR-0008 prescrive quando il dato non c'è. Meglio assente che
    sbagliato — e la pagina lo dice invece di tacerlo.
    """

    class Meta:
        model = User
        fields = ("body_mass_kg",)
        widgets = {
            "body_mass_kg": forms.NumberInput(
                attrs={"step": "0.1", "min": "1", "class": "form-control"}
            ),
        }


class RoutineForm(forms.ModelForm):
    """`/schede/nuova/` e `/schede/<pk>/modifica/`.

    `user` **non** è un campo: il proprietario lo mette la view da
    `request.user`. Un campo in pagina è un campo che si può riscrivere in un
    POST costruito a mano, e la proprietà della scheda è esattamente ciò che
    `UserPassesTestMixin` difende dall'altra parte.

    `is_public` invece sta qui, ed è il flag che rende la scheda votabile: è
    l'unico modo che l'utente ha per farla comparire nella community.
    """

    class Meta:
        model = Routine
        fields = ("name", "notes", "is_public")
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Spinta A"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_public": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class RoutineExerciseForm(forms.ModelForm):
    """Una riga del formset: l'esercizio e il bersaglio da inseguire."""

    class Meta:
        model = RoutineExercise
        fields = (
            "position",
            "exercise",
            "target_sets",
            "target_reps",
            "target_reps_max",
            "notes",
        )
        widgets = {
            "position": forms.NumberInput(
                attrs={"class": "form-control", "min": "1", "step": "1"}
            ),
            "exercise": forms.Select(attrs={"class": "form-select"}),
            "target_sets": forms.NumberInput(
                attrs={"class": "form-control", "min": "1"}
            ),
            "target_reps": forms.NumberInput(
                attrs={"class": "form-control", "min": "1"}
            ),
            "target_reps_max": forms.NumberInput(
                attrs={"class": "form-control", "min": "1"}
            ),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cento esercizi in un `<select>`, e le righe del formset sono dieci:
        # senza `select_related` ogni riga ripaga il catalogo per intero.
        self.fields["exercise"].queryset = Exercise.objects.select_related(
            "equipment", "primary_muscle"
        )
        # L'opzione vuota di Django è testo inglese non tradotto in italiano:
        # è l'unica stringa dell'interfaccia che il progetto non scriverebbe.
        self.fields["exercise"].empty_label = "— scegli un esercizio —"

    def clean(self):
        """Il range di ripetizioni deve essere un range.

        Il database non lo impone e non deve: `target_reps_max` è facoltativo,
        perché un bersaglio secco («3×8») è legittimo. La regola è «se c'è, non
        sta sotto il minimo», e vale la pena verificarla perché è l'estremo alto
        che la doppia progressione insegue: invertito, il coach consiglierebbe
        di salire verso un numero già raggiunto.
        """
        cleaned = super().clean()
        reps = cleaned.get("target_reps")
        reps_max = cleaned.get("target_reps_max")

        if reps is not None and reps_max is not None and reps_max < reps:
            self.add_error(
                "target_reps_max",
                "L'estremo alto del range non può stare sotto il minimo.",
            )

        return cleaned


class BaseRoutineExerciseFormSet(forms.BaseInlineFormSet):
    """Il vincolo `routine_exercise_unique`, detto prima che lo dica SQLite.

    `UniqueConstraint(routine, exercise)` sta nel modello ed è la garanzia
    vera; ma qui la coppia arriva spezzata — `routine` è escluso dal form,
    perché lo porta l'istanza del formset — quindi la validazione del singolo
    form non può vederla. Senza questo `clean`, due righe uguali arriverebbero
    al database come `IntegrityError`: un 500 al posto di un errore di form.
    """

    def add_fields(self, form, index):
        """`DELETE` non è un campo del modello: lo aggiunge il formset, dopo
        che il `Meta.widgets` del form è già stato applicato. La classe
        Bootstrap va quindi messa qui, o la casella «Togli» resta nuda."""
        super().add_fields(form, index)
        if "DELETE" in form.fields:
            form.fields["DELETE"].widget.attrs["class"] = "form-check-input"

    def validate_unique(self):
        """Spenta di proposito, e sostituita da `clean` qui sotto.

        `BaseModelFormSet.validate_unique` **vede** il duplicato — l'unico
        `UniqueConstraint` del modello è `(routine, exercise)` — ma dice «Si
        prega di correggere i dati duplicati di exercise», che non è la regola
        di dominio, e per farlo **rimuove il campo da `cleaned_data`**, così
        che nessun controllo successivo possa più leggerlo. Lasciarla accesa
        significherebbe due messaggi per lo stesso errore, uno dei quali
        incomprensibile. La copertura non cambia: il `clean` qui sotto guarda
        la stessa coppia su tutte le righe, e il formset inline le contiene
        tutte per costruzione.
        """

    def clean(self):
        super().clean()

        visti = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue

            esercizio = form.cleaned_data.get("exercise")
            if esercizio is None:
                continue

            if esercizio.pk in visti:
                form.add_error(
                    "exercise",
                    "Questo esercizio compare già nella scheda: "
                    "una scheda lo elenca una volta sola.",
                )
            visti.add(esercizio.pk)


#: Il primo form denso del progetto. `extra=3` perché una scheda si compila in
#: più passaggi e tre righe vuote bastano a farne uno; `can_delete` perché
#: togliere un esercizio è parte del CRUD tanto quanto aggiungerlo.
RoutineExerciseFormSet = forms.inlineformset_factory(
    Routine,
    RoutineExercise,
    form=RoutineExerciseForm,
    formset=BaseRoutineExerciseFormSet,
    extra=3,
    can_delete=True,
)


class LocalDateTimeField(forms.DateTimeField):
    """Un `datetime` che sopravvive al viaggio dentro `<input type="datetime-local">`.

    Il campo HTML nativo è l'unico modo di chiedere data e ora senza
    JavaScript, ma parla un formato solo — `2026-09-08T18:30` — mentre il
    progetto è in `it-it`, e i `DATETIME_INPUT_FORMATS` italiani sono
    `08/09/2026 18:30` e compagnia. Senza questa coppia di formati il POST
    dell'input nativo tornerebbe indietro con «Inserisci una data/ora valida»
    su un valore che il browser ha appena composto lui: un errore di form su un
    campo che l'utente non ha nemmeno digitato a mano.

    Il formato del widget serve alla direzione opposta — rendere il valore
    esistente in modo che il browser lo riconosca in `UpdateView` — e senza di
    esso la modifica di un allenamento aprirebbe il campo vuoto.
    """

    #: I secondi ci sono perché alcuni browser li includono se il valore
    #: iniziale li porta; il minuto è quanto il dominio ha davvero bisogno.
    INPUT_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S")
    WIDGET_FORMAT = "%Y-%m-%dT%H:%M"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("input_formats", self.INPUT_FORMATS)
        kwargs.setdefault(
            "widget",
            forms.DateTimeInput(
                format=self.WIDGET_FORMAT,
                attrs={"type": "datetime-local", "class": "form-control"},
            ),
        )
        super().__init__(*args, **kwargs)


class WorkoutForm(forms.ModelForm):
    """`/allenamenti/nuovo/` e `/allenamenti/<pk>/modifica/`.

    Come in `RoutineForm`, `user` **non** è un campo: lo mette la view da
    `request.user`. E non lo è nemmeno `routine`, per una ragione in più —
    l'allenamento è un log immutabile (ADR-0002), quindi il legame con la
    scheda si stabilisce **una volta**, nel momento in cui l'allenamento nasce
    da quella scheda, e non si riscrive dopo da una tendina. Ciò che resta del
    legame nel tempo è `title`, che è un'istantanea e non un riferimento.

    `title` è quindi un `CharField` normale e modificabile: rinominarlo cambia
    il nome di *questo* allenamento e non tocca la scheda, che è esattamente
    il verso in cui ADR-0002 vuole che l'informazione non scorra.
    """

    started_at = LocalDateTimeField(label="Iniziato il")
    ended_at = LocalDateTimeField(label="Finito il", required=False)

    class Meta:
        model = Workout
        fields = ("title", "started_at", "ended_at", "notes")
        widgets = {
            "title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Spinta A"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def clean(self):
        """`workout_ended_after_started`, detto prima che lo dica SQLite.

        Il `CheckConstraint` è la garanzia vera e resta al suo posto; qui
        serve a trasformare un `IntegrityError` — cioè un 500 — in un errore
        di form sul campo giusto. Le durate assurde (zero minuti, venticinque
        ore) restano ammesse di proposito: lo storico reale ne contiene, e
        l'unico caso davvero impossibile è una fine prima dell'inizio.
        """
        cleaned = super().clean()
        inizio = cleaned.get("started_at")
        fine = cleaned.get("ended_at")

        if inizio is not None and fine is not None and fine < inizio:
            self.add_error(
                "ended_at", "Un allenamento non può finire prima di cominciare."
            )

        return cleaned


class WorkoutSetForm(forms.ModelForm):
    """Una riga del formset delle serie: cosa è stato davvero sollevato.

    `exercise` punta al **catalogo**, mai a `RoutineExercise`: la serie
    sopravvive alla scheda che l'ha suggerita, e il numero registrato resta
    leggibile anche se quella scheda viene riscritta o cancellata.

    `weight` è **sempre già comprensivo del bilanciere**. Il campo chiede il
    peso totale, e `Equipment.default_bar_weight_kg` compare solo come valore
    di partenza quando non c'è una volta precedente da cui copiare: sommarlo a
    valle vorrebbe dire non sapere più se un numero l'ha scritto l'utente o
    inventato la query.
    """

    class Meta:
        model = WorkoutSet
        fields = (
            "exercise",
            "set_number",
            "reps",
            "weight",
            "set_type",
            "is_completed",
        )
        widgets = {
            "exercise": forms.Select(attrs={"class": "form-select"}),
            "set_number": forms.NumberInput(
                attrs={"class": "form-control", "min": "1", "step": "1"}
            ),
            "reps": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            # `step` a 0.25 e non a 2.5: i micro-carichi esistono, e il passo
            # dell'attrezzo (`load_increment_kg`) è un consiglio del coach in
            # fase 3, non un limite di ciò che si può registrare.
            "weight": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "step": "0.25"}
            ),
            "set_type": forms.Select(attrs={"class": "form-select"}),
            "is_completed": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Stessa ragione del formset delle schede: cento esercizi per riga, e
        # qui le righe sono dieci, non tre.
        self.fields["exercise"].queryset = Exercise.objects.select_related(
            "equipment", "primary_muscle"
        )
        self.fields["exercise"].empty_label = "— scegli un esercizio —"

    def clean(self):
        """`workout_set_completed_has_reps`, tradotto in italiano di dominio.

        È il vincolo che dà senso a `is_completed`: una serie **eseguita** ha
        delle ripetizioni, una serie **saltata** non deve averle. Il database
        lo impone; senza questo `clean` lo imporrebbe con un 500, e per giunta
        su un form dove la casella «Eseguita» è proprio ciò che l'utente ha
        appena tolto.

        `weight` invece non si pretende mai: zero è legittimo sul corpo libero,
        e nullo è la risposta giusta per una serie saltata.
        """
        cleaned = super().clean()
        eseguita = cleaned.get("is_completed")
        reps = cleaned.get("reps")

        if eseguita and not self.is_riga_vuota(cleaned):
            if reps is None or reps == 0:
                self.add_error(
                    "reps",
                    "Una serie eseguita ha delle ripetizioni: se l'hai saltata, "
                    "togli la spunta «Eseguita».",
                )

        return cleaned

    def is_riga_vuota(self, cleaned):
        """Una riga senza esercizio è una riga che l'utente non ha compilato.

        Vale per una riga *esistente* svuotata: lì `exercise` ha già il suo
        errore di campo obbligatorio, e pretendere anche le ripetizioni
        aggiungerebbe un secondo messaggio sulla stessa riga rotta. Le righe
        nuove rimaste in bianco non arrivano nemmeno qui — le ferma
        `has_changed`.
        """
        return cleaned.get("exercise") is None

    def has_changed(self):
        """Una riga nuova senza esercizio non è cambiata, spunta o non spunta.

        Qui sta la differenza con il formset delle schede, ed è una casella di
        spunta a farla. Django ignora un form `extra` solo se `has_changed()`
        è falso, e il confronto è con i valori **iniziali**: `is_completed` ha
        `default=True`, quindi la casella «Eseguita» delle righe in coda nasce
        spuntata. Un utente che ne toglie una — gesto ragionevole su una riga
        che non intende compilare — rende quella riga «cambiata», e da lì il
        formset pretende esercizio e numero di serie: cinque errori su cinque
        righe che nessuno ha scritto, e la pagina non si salva più.

        La riga vuota si riconosce dall'esercizio, che è l'unico campo senza
        valore iniziale e senza il quale la serie non esiste. Le righe già
        salvate non passano di qui: svuotarle è una modifica vera, e per
        toglierle c'è la casella «Togli».
        """
        if not self.is_bound or self.instance.pk is not None:
            return super().has_changed()

        if not self.data.get(self.add_prefix("exercise")):
            return False

        return super().has_changed()


class BaseWorkoutSetFormSet(forms.BaseInlineFormSet):
    """Il vincolo `workout_set_unique`, cioè `(workout, exercise, set_number)`.

    Vale la stessa meccanica del formset delle schede: la terna arriva spezzata
    — `workout` è l'istanza del formset, non un campo — quindi il singolo form
    non può vederla, e `validate_unique` di Django la vede ma la annuncia coi
    nomi dei campi invece che con la regola, svuotando `cleaned_data` per
    farlo. È spenta qui e sostituita dal `clean` sotto.

    La regola in italiano: **due serie dello stesso esercizio non possono
    portare lo stesso numero**. Tre serie di panca sono 1, 2, 3; due serie
    numerate entrambe 2 non sono un duplicato di dati, sono un conteggio
    sbagliato.
    """

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if "DELETE" in form.fields:
            form.fields["DELETE"].widget.attrs["class"] = "form-check-input"
        # Il catalogo si legge **una volta per pagina**, non una per riga.
        form.fields["exercise"].choices = self.scelte_esercizio

    @cached_property
    def scelte_esercizio(self):
        """Le cento opzioni del `<select>`, condivise da tutte le righe.

        `ModelChoiceField` costruisce le sue opzioni con un iteratore che
        interroga il database **ogni volta che il campo viene reso**. Su un
        form solo non si nota; qui le righe sono venti, e la pagina delle serie
        misurata sul catalogo vero faceva 27 query, quasi tutte la stessa.
        Valorizzare `choices` con una lista già pronta sostituisce
        l'iteratore e le riduce a una.

        La validazione non passa da qui e non cambia: `to_python` di
        `ModelChoiceField` risolve il valore sul `queryset`, che resta quello
        del form. Questa è la sola forma dell'elenco, non la sua verità.
        """
        esercizi = Exercise.objects.select_related("equipment", "primary_muscle")
        return [("", "— scegli un esercizio —")] + [
            (esercizio.pk, str(esercizio)) for esercizio in esercizi
        ]

    def validate_unique(self):
        """Spenta di proposito: vedi `BaseRoutineExerciseFormSet.validate_unique`."""

    def clean(self):
        super().clean()

        visti = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue

            esercizio = form.cleaned_data.get("exercise")
            numero = form.cleaned_data.get("set_number")
            if esercizio is None or numero is None:
                continue

            if (esercizio.pk, numero) in visti:
                form.add_error(
                    "set_number",
                    f"C'è già una serie {numero} di {esercizio.name} in questo "
                    "allenamento: le serie dello stesso esercizio si numerano "
                    "una per una.",
                )
            visti.add((esercizio.pk, numero))


#: `extra=5` — e la scelta è la conseguenza misurata che #69 aveva già
#: annunciato. Il formset delle serie è più denso di quello delle schede: dieci
#: righe, non tre, e senza JavaScript non esiste un bottone «aggiungi riga», per
#: cui «salva e torna» ci passa peggio. La risposta però non è alzare `extra`
#: fino a coprire un allenamento intero — venti righe vuote su una pagina sono
#: un modulo, non un registro. La risposta è **«Avvia allenamento da scheda»**,
#: che le righe le porta già scritte: chi parte dalla scheda non compila niente,
#: corregge. Le cinque righe in coda servono a chi aggiunge un esercizio fuori
#: programma, ed è un caso da poche righe per definizione.
WorkoutSetFormSet = forms.inlineformset_factory(
    Workout,
    WorkoutSet,
    form=WorkoutSetForm,
    formset=BaseWorkoutSetFormSet,
    extra=5,
    can_delete=True,
)


class VoteForm(forms.ModelForm):
    """Il voto su una scheda della community: il terzo CRUD.

    Qui vivono **le due regole che il database non può imporre**, perché
    entrambe attraversano una relazione e nessun `CheckConstraint` può leggere
    la riga di un'altra tabella (`docs/spec/01-modelli.md`, §Vote):

    1. **l'autovoto è vietato** — il voto misura cosa pensano gli altri, e chi
       si vota da solo sposta la classifica sociale senza aggiungere un
       giudizio;
    2. **una scheda non pubblica non è votabile** — `is_public` è l'unico
       consenso che l'autore ha dato, e votare ciò che non è stato esposto lo
       aggirerebbe.

    Il form riceve chi vota e cosa vota (`voter`, `routine`) perché nessuno dei
    due è un campo in pagina: li mette la view da `request.user` e dall'URL,
    per la stessa ragione per cui `RoutineForm` non espone `user`. Le regole
    sono ripetute nella view — la view non renderizza il form quando non si può
    votare — ma il posto in cui *valgono* è questo: un POST costruito a mano
    non passa dal template, passa da qui.

    La scala è 1–5 e non pollice su/giù, perché il punteggio serve a produrre
    una **media da ordinare**, ed è quella media che alimenta la classifica
    sociale (#76).
    """

    #: Il voto si sceglie da una tendina, non si digita: `score` è un
    #: `PositiveSmallIntegerField` e il widget di Django sarebbe un `number`,
    #: dove «7» si scrive e poi lo rifiuta il `CheckConstraint` con un 500.
    SCELTE = [
        (1, "1 — da rivedere"),
        (2, "2 — sotto la media"),
        (3, "3 — buona"),
        (4, "4 — molto buona"),
        (5, "5 — ottima"),
    ]

    score = forms.TypedChoiceField(
        choices=SCELTE,
        coerce=int,
        label="Voto",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Vote
        fields = ("score", "comment")
        widgets = {
            "comment": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Facoltativo: cosa funziona, cosa no.",
                }
            ),
        }

    def __init__(self, *args, voter=None, routine=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.voter = voter
        self.routine = routine

    def clean(self):
        cleaned = super().clean()

        if self.routine is not None and not self.routine.is_public:
            raise forms.ValidationError(
                "Questa scheda non è pubblica: non è votabile."
            )

        if (
            self.routine is not None
            and self.voter is not None
            and self.routine.user_id == self.voter.pk
        ):
            raise forms.ValidationError(
                "Non si vota la propria scheda: il voto è il giudizio degli altri."
            )

        return cleaned


class CsvField(forms.FileField):
    """Un file CSV, con le due sole difese che il form può davvero fare.

    **Estensione e dimensione**, e nient'altro: il contenuto lo giudica il
    parser, che è l'unico che sa cosa cerca. Un controllo sul `content_type`
    sarebbe teatro — lo dichiara il browser, e su un `.csv` dice
    `text/csv`, `application/vnd.ms-excel` o `application/octet-stream` a
    seconda di cosa è installato sulla macchina di chi carica.

    I 5 MB sono ~25.000 serie contro le 317 dello storico reale: il limite non
    è lì per l'uso normale, è lì perché il campo accetta un upload e un campo
    che accetta un upload senza tetto è un modo di restare in piedi finché
    qualcuno non prova.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "widget", forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".csv"})
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        file = super().clean(data, initial)
        if not file:
            return file

        if not file.name.lower().endswith(".csv"):
            raise forms.ValidationError(
                "Serve un file con estensione .csv: questo si chiama "
                f"«{file.name}»."
            )

        if file.size > importer.LIMITE_BYTE:
            limite = importer.LIMITE_BYTE // (1024 * 1024)
            raise forms.ValidationError(
                f"Il file supera i {limite} MB. Se lo storico è davvero così "
                "grande, caricalo diviso per periodo."
            )

        return file


class ImportUploadForm(forms.Form):
    """`/import/` — i due file in **un solo POST**.

    Due campi e non due passaggi: le serie senza le loro sessioni non si
    possono nemmeno leggere (`session_id` non punterebbe a niente), quindi
    caricarli separatamente vorrebbe dire tenere metà import in sospeso fra
    due richieste per non guadagnare nulla.

    Il terzo campo è **facoltativo ed è un dizionario**, non una sorgente:
    l'export di Overload tiene i nomi degli esercizi in un file a parte e
    mette solo l'`exercise_id` nelle serie. Senza quel file quei nomi
    arriverebbero all'utente come UUID da abbinare a mano, che è un
    abbinamento impossibile. Nessuna riga di `Exercise` nasce da qui: il
    catalogo resta globale e chiuso (ADR-0001).
    """

    sessioni = CsvField(
        label="workout_sessions.csv",
        help_text="Gli allenamenti: una riga per sessione.",
    )
    serie = CsvField(
        label="session_sets.csv",
        help_text="Le serie: una riga per serie, legate alle sessioni da «session_id».",
    )
    esercizi = CsvField(
        label="exercises.csv",
        required=False,
        help_text=(
            "Facoltativo, e serve solo se le serie portano un «exercise_id» "
            "invece del nome — è il caso dell'export di Overload. Si usa come "
            "elenco di nomi: nessun esercizio viene creato."
        ),
    )


class AbbinamentoForm(forms.Form):
    """Una riga della tabella di abbinamento: un nome estraneo, un esercizio.

    Questa è la riga in cui l'import **chiede** invece di informare, ed è tutto
    ADR-0010 in un form: l'abbinamento non è un problema di stringhe, è una
    scelta, e la fa l'utente. Il suggerimento arriva già selezionato e può
    essere sbagliato senza danno — c'è un umano che lo guarda.

    `raw_name` è nascosto perché non è modificabile: è ciò che c'è scritto nel
    file. È in pagina come `hidden` e non tenuto in sessione perché il formset
    deve poter ricostruire la coppia da solo, anche se fra i due POST l'utente
    ha ricaricato la pagina.
    """

    raw_name = forms.CharField(widget=forms.HiddenInput)
    exercise = forms.ModelChoiceField(
        queryset=Exercise.objects.all(),
        label="Esercizio del catalogo",
        empty_label="— scegli un esercizio —",
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class BaseAbbinamentoFormSet(forms.BaseFormSet):
    """Il catalogo si legge **una volta per pagina**, non una per riga.

    È la guardia che #70 ha lasciato in eredità: `ModelChoiceField` costruisce
    le sue opzioni con un iteratore che interroga il database ogni volta che il
    campo viene reso, e qui le righe sono ventiquattro sullo storico reale —
    una `<select>` da cento opzioni per ciascuna. Valorizzare `choices` con una
    lista già pronta sostituisce l'iteratore; la validazione non cambia, perché
    `to_python` risolve comunque sul `queryset` del form.
    """

    def get_form_kwargs(self, index):
        """`empty_permitted=False` su **ogni** riga, e senza questa riga
        l'import perde in silenzio gli abbinamenti accettati così com'erano.

        Il meccanismo: le righe di questo formset non hanno un'istanza, quindi
        Django le tratta tutte come righe `extra` e concede loro
        `empty_permitted=True`, che significa «se non è cambiata rispetto ai
        valori iniziali, `cleaned_data` resta vuoto». Ma qui i valori iniziali
        sono **il suggerimento**, e accettare il suggerimento — cioè il gesto
        più normale che l'utente possa fare su questa pagina — lascia la riga
        identica a com'è nata. Risultato: il formset è valido, la pagina
        rimanda all'esito, e quelle serie non entrano perché il loro nome non
        risulta abbinato a niente.

        È di nuovo la famiglia di guasti di #69, #71 e #72: un no muto, con la
        pagina che continua a rendere. Qui una riga vuota non è mai legittima —
        ogni riga è una domanda a cui bisogna rispondere — quindi il permesso
        si toglie a tutte.
        """
        kwargs = super().get_form_kwargs(index)
        kwargs["empty_permitted"] = False
        return kwargs

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["exercise"].choices = self.scelte_esercizio

    @cached_property
    def scelte_esercizio(self):
        esercizi = Exercise.objects.select_related("equipment", "primary_muscle")
        return [("", "— scegli un esercizio —")] + [
            (esercizio.pk, str(esercizio)) for esercizio in esercizi
        ]


#: `extra=0` e `can_delete=False`: le righe sono esattamente i nomi che il file
#: porta e che non si sono risolti da soli. Non se ne aggiungono e non se ne
#: tolgono — toglierne una vorrebbe dire scartare delle serie, e per farlo
#: basta non importare quel file.
AbbinamentoFormSet = forms.formset_factory(
    AbbinamentoForm, formset=BaseAbbinamentoFormSet, extra=0, can_delete=False
)
