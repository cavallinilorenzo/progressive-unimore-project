"""L'admin di Progressive — tre modelli, non tutti e dieci.

`docs/spec/02-pagine-e-template.md` §Convenzioni chiede «`admin.register()` con
`ModelAdmin` custom su 2–3 modelli», e la scelta di *quali* tre non è arbitraria:
sono i tre punti in cui l'admin è l'**unica** superficie di scrittura del
progetto, o l'unica lettura che l'interfaccia non offre.

- `Exercise` — ADR-0001 lo dice per esteso: il catalogo è globale e non esiste
  l'esercizio custom, quindi «chi ha bisogno di un esercizio mancante lo chiede,
  e lo si aggiunge dall'admin Django». Senza questa registrazione quella frase
  dell'ADR non ha un posto dove avverarsi.
- `User` — è custom (ADR-0003), e un `AbstractUser` esteso **non** è registrato
  da nessuno: `django.contrib.auth.admin` registra `auth.User`, che qui non
  esiste. Senza questo file l'admin di Progressive mostrerebbe i soli gruppi.
  Ed è il posto da cui si separano i 100 utenti sintetici di `seed_synthetic`
  dai reali, distinzione che l'interfaccia non fa e che serve durante la demo.
- `Routine` — il solo modello del progetto con un vero rapporto padre-figlio da
  mostrare, `RoutineExercise` in `TabularInline`.

**Cosa resta fuori, di proposito**: `Workout`, `WorkoutSet` e `Vote`. Sono il
registro di ciò che qualcuno ha fatto, e `docs/spec/03-import-ed-export.md`
fissa la linea — «nessun import per conto di altri, nemmeno da admin». Un
allenamento modificabile dall'admin è storico riscritto in silenzio, cioè
esattamente il tipo di guasto che questo progetto ha imparato a temere. Le tre
anagrafiche (`MuscleGroup`, `Muscle`, `Equipment`) restano fuori per la ragione
opposta: le popola `load_catalog` da CSV, e il CSV è la fonte di verità.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Count

from training.models import Exercise, Routine, RoutineExercise, User

admin.site.site_header = "Progressive — amministrazione"
admin.site.site_title = "Progressive"
admin.site.index_title = "Catalogo, utenti e schede"


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    """Il catalogo, che qui si scrive e altrove si legge soltanto."""

    list_display = ("name", "primary_muscle", "gruppo", "equipment", "slug")
    list_filter = ("equipment", "primary_muscle__group", "primary_muscle")
    search_fields = ("name", "slug")
    ordering = ("name",)
    # `slug` è il segmento di URL di `/esercizi/<slug>/`, quindi la stabilità
    # conta più della comodità: `prepopulated_fields` riempie **solo** in
    # creazione e lascia stare le righe che uno slug ce l'hanno già, che è
    # proprio il patto scritto nell'`help_text` del campo.
    prepopulated_fields = {"slug": ("name",)}
    # 100 esercizi × 2 FK è la stessa trappola N+1 che #86 ha chiuso sul
    # formset delle schede: la lista dell'admin non ne è immune.
    list_select_related = ("primary_muscle", "primary_muscle__group", "equipment")

    @admin.display(description="gruppo", ordering="primary_muscle__group__sort_order")
    def gruppo(self, obj):
        return obj.primary_muscle.group


class RoutineExerciseInline(admin.TabularInline):
    """Le voci della scheda, dentro la scheda: è il senso dell'inline."""

    model = RoutineExercise
    extra = 0
    fields = (
        "position",
        "exercise",
        "target_sets",
        "target_reps",
        "target_reps_max",
        "notes",
    )
    ordering = ("position",)
    # Cento esercizi in un `<select>` ripetuto per riga è la stessa pagina
    # illeggibile che #69 ha rifiutato lato utente; qui la risposta è
    # l'autocomplete, che l'admin dà gratis perché `ExerciseAdmin` ha
    # `search_fields`.
    #
    # **Costo misurato e accettato**: `AutocompleteSelect` interroga per
    # ricostruire l'*opzione selezionata*, quindi è una query per riga — sul
    # dato vero, 21 query per una scheda da 5 esercizi e 29 per una da 8. Non è
    # il caso di #86: lì il ripasso era sull'elenco delle scelte, e si chiudeva
    # condividendo un queryset; qui si cerca per chiave primaria, riga per
    # riga. Resta limitato dalla lunghezza di una scheda (una dozzina di voci) e
    # su una pagina d'amministrazione non vale la pena barattarlo con dodici
    # `<select>` da cento opzioni.
    autocomplete_fields = ("exercise",)


@admin.register(Routine)
class RoutineAdmin(admin.ModelAdmin):
    """La scheda col suo dettaglio, e il flag che la apre alla community."""

    list_display = ("name", "user", "is_public", "numero_di_esercizi", "created_at")
    list_filter = ("is_public",)
    search_fields = ("name", "user__username")
    ordering = ("-created_at",)
    # `created_at` è `auto_now_add`: mostrarlo modificabile sarebbe una bugia.
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user",)
    inlines = [RoutineExerciseInline]
    list_select_related = ("user",)

    def get_queryset(self, request):
        # Il conteggio in `list_display` è una query per riga se lo si chiede al
        # template; annotato è una sola per pagina.
        return super().get_queryset(request).annotate(
            _numero_di_esercizi=Count("exercises")
        )

    @admin.display(description="esercizi", ordering="_numero_di_esercizi")
    def numero_di_esercizi(self, obj):
        return obj._numero_di_esercizi


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """L'utente custom, con i due campi che `AbstractUser` non ha.

    Si eredita da `BaseUserAdmin` e non da `ModelAdmin`: è quello che porta
    l'hashing della password, i permessi e la pagina di cambio password.
    Estenderne i `fieldsets` invece di riscriverli è la stessa scelta di
    ADR-0003 — si estende ciò che Django già fa bene.
    """

    list_display = BaseUserAdmin.list_display + ("body_mass_kg", "is_synthetic")
    list_filter = BaseUserAdmin.list_filter + ("is_synthetic",)
    search_fields = ("username", "first_name", "last_name", "email")
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Progressive",
            {
                "fields": ("body_mass_kg", "is_synthetic"),
                "description": (
                    "Senza peso corporeo l'utente non compare in classifica e non "
                    "riceve un percentile: meglio assente che sbagliato (ADR-0008)."
                ),
            },
        ),
    )
