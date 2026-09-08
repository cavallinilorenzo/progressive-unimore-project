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

from training.models import Exercise, Routine, RoutineExercise, User


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
