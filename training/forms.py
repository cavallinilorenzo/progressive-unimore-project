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

from training.models import User


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
