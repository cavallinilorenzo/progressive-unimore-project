"""Le rotte di Progressive.

`app_name` più nomi di rotta **col trattino**, come nell'esempio del corso
(#22). La sitemap completa — cinque sezioni e i loro URL — è in
`docs/spec/02-pagine-e-template.md`; qui ci sono la dashboard, le pagine
dell'utente, le schede, lo storico, il catalogo, l'import,
l'export e le classifiche.

Login e logout non stanno qui: vivono sotto `/accounts/` in `config/urls.py`,
perché sono le view di `django.contrib.auth` e i loro nomi di rotta (`login`,
`logout`) sono senza namespace. La registrazione invece è nostra, ed è di
dominio come le altre: `training:signup`.
"""

from django.urls import path
from django.views.generic import RedirectView

from training import views

app_name = "training"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("registrazione/", views.SignUpView.as_view(), name="signup"),
    path("profilo/", views.ProfileUpdateView.as_view(), name="profile"),
    # Analisi — la **sesta** voce dell'header, e l'unica aggiunta alla sitemap
    # di `02-pagine-e-template.md` dopo #19. La pagina era nominata in
    # `04-analisi.md` («Analisi muscolare») e senza URL: o le si dava un
    # indirizzo, o A1 e A2 finivano in dashboard a sovraccaricare la prima
    # pagina. Una rotta sola e nessuna sotto: le altre analisi hanno già la
    # loro sezione — la progressione sta dentro l'esercizio, che *è* la sua
    # storia, e la heatmap vive solo in dashboard.
    path("analisi/", views.AnalysisView.as_view(), name="analysis"),
    # Schede — il primo dei due CRUD completi che pagano il requisito della
    # traccia. `nuova/` precede `<pk>/` di proposito: l'ordine di `urlpatterns`
    # è quello di risoluzione, e un `<int:pk>` non catturerebbe «nuova», ma la
    # regola vale appena una rotta usa `<str:...>`.
    path("schede/", views.RoutineListView.as_view(), name="routine-list"),
    path("schede/nuova/", views.RoutineCreateView.as_view(), name="routine-create"),
    path("schede/<int:pk>/", views.RoutineDetailView.as_view(), name="routine-detail"),
    path(
        "schede/<int:pk>/modifica/",
        views.RoutineUpdateView.as_view(),
        name="routine-update",
    ),
    path(
        "schede/<int:pk>/elimina/",
        views.RoutineDeleteView.as_view(),
        name="routine-delete",
    ),
    path(
        "schede/<int:pk>/esercizi/",
        views.RoutineExercisesView.as_view(),
        name="routine-exercises",
    ),
    # La community sta **dentro Schede**, non è una sesta voce dell'header: è
    # la regola di navigazione di `02-pagine-e-template.md`. Le due rotte
    # stanno sotto `schede/` per la stessa ragione per cui il link ci sta
    # dentro — l'URL dice a quale sezione appartiene la pagina.
    #
    # `pubbliche/` non ha bisogno di precedere `<int:pk>/`, perché un
    # `<int:pk>` non cattura una parola; sta comunque qui in blocco, con le sue.
    path(
        "schede/pubbliche/",
        views.RoutinePublicListView.as_view(),
        name="routine-public-list",
    ),
    path(
        "schede/pubbliche/<int:pk>/",
        views.RoutinePublicDetailView.as_view(),
        name="routine-public-detail",
    ),
    # Il `pk` è quello della **scheda**, non quello del voto: da qui il voto
    # che si toglie è sempre il proprio, e la view lo cerca per `request.user`.
    path(
        "schede/pubbliche/<int:pk>/voto/elimina/",
        views.VoteDeleteView.as_view(),
        name="vote-delete",
    ),
    # Storico — il secondo dei due CRUD completi, e quello che tiene insieme
    # il piano e l'eseguito: `nuovo/` accetta `?scheda=<pk>` ed è «Avvia
    # allenamento da scheda». Il parametro viaggia in query string e non in
    # URL perché non identifica la risorsa: `/allenamenti/nuovo/` resta la
    # stessa pagina, la scheda è il suo punto di partenza facoltativo.
    path("allenamenti/", views.WorkoutListView.as_view(), name="workout-list"),
    path(
        "allenamenti/nuovo/",
        views.WorkoutCreateView.as_view(),
        name="workout-create",
    ),
    path(
        "allenamenti/<int:pk>/",
        views.WorkoutDetailView.as_view(),
        name="workout-detail",
    ),
    path(
        "allenamenti/<int:pk>/modifica/",
        views.WorkoutUpdateView.as_view(),
        name="workout-update",
    ),
    path(
        "allenamenti/<int:pk>/elimina/",
        views.WorkoutDeleteView.as_view(),
        name="workout-delete",
    ),
    # `workoutset-manage` e non `workout-sets`: il nome della rotta segue il
    # modello che gestisce, come `routine-exercises` fa con `RoutineExercise`.
    path(
        "allenamenti/<int:pk>/serie/",
        views.WorkoutSetsView.as_view(),
        name="workoutset-manage",
    ),
    # Esercizi — e qui l'avvertenza di sopra si vede all'opera: `<slug:slug>`
    # cattura anche «panca-piana», quindi nessuna rotta letterale può stargli
    # sotto. Lo slug è generato una volta da `load_catalog`, non a runtime,
    # perché l'URL di un esercizio dev'essere stabile e leggibile —
    # `/esercizi/panca-piana/`, non `/esercizi/37/`.
    path("esercizi/", views.ExerciseListView.as_view(), name="exercise-list"),
    path(
        "esercizi/<slug:slug>/",
        views.ExerciseDetailView.as_view(),
        name="exercise-detail",
    ),
    # Classifiche — due pagine e non una con un `if` dentro, perché ordinano
    # cose diverse: la prima gli **utenti** su un esercizio, la seconda le
    # **schede**. Sono due classifiche di natura diversa, e la traccia si
    # considera soddisfatta due volte proprio per quello.
    #
    # `/classifiche/` da sola non è una pagina: è il prefisso che l'header
    # mostra, e chi lo digita finisce sulla classifica di forza. Una redirect e
    # non un indice, perché un indice con due voci sarebbe un clic in più per
    # dire ciò che le due schede in cima a ogni pagina già dicono.
    path(
        "classifiche/",
        RedirectView.as_view(pattern_name="training:ranking-strength"),
        name="ranking-index",
    ),
    path(
        "classifiche/forza/",
        views.RankingStrengthView.as_view(),
        name="ranking-strength",
    ),
    path(
        "classifiche/schede/",
        views.RankingSocialView.as_view(),
        name="ranking-social",
    ),
    # Import — **tre URL, non una vista con tre rami dentro `post()`**. Ogni
    # passo ha il suo indirizzo, quindi lo stato dell'import vive
    # nell'indirizzo e non dentro un `if`: si carica, si abbina, si legge
    # l'esito. È anche ciò che rende la conferma non ripetibile con un
    # ricaricamento — la scrittura avviene nel POST dell'anteprima e l'esito è
    # una GET dopo una redirect.
    #
    # L'import non è una sesta voce dell'header: sta nel menu utente, come
    # prescrive la regola di navigazione di `02-pagine-e-template.md`.
    path("import/", views.ImportUploadView.as_view(), name="import-upload"),
    path(
        "import/anteprima/",
        views.ImportPreviewView.as_view(),
        name="import-preview",
    ),
    path("import/esito/", views.ImportResultView.as_view(), name="import-result"),
    # Export — la seconda metà del giro, e la ragione per cui l'import non è
    # «il formato di un'altra app»: Progressive produce i due file che sa
    # leggere. Il nome del file sta **nell'URL** e non in query string, perché
    # qui il parametro identifica davvero la risorsa — `allenamenti` e `serie`
    # sono due file con due intestazioni — al contrario di `?scheda=<pk>` su
    # «avvia allenamento», che lascia la pagina la stessa.
    path("export/<slug:quale>/", views.ExportCsvView.as_view(), name="export-csv"),
]
