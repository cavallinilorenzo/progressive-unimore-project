"""Le rotte di Progressive.

`app_name` più nomi di rotta **col trattino**, come nell'esempio del corso
(#22). La sitemap completa — cinque sezioni e i loro URL — è in
`docs/spec/02-pagine-e-template.md`; qui ci sono la dashboard, le pagine
dell'utente, le schede, lo storico e il catalogo; le classifiche e l'import
entrano coi ticket rimasti della mappa #53.

Login e logout non stanno qui: vivono sotto `/accounts/` in `config/urls.py`,
perché sono le view di `django.contrib.auth` e i loro nomi di rotta (`login`,
`logout`) sono senza namespace. La registrazione invece è nostra, ed è di
dominio come le altre: `training:signup`.
"""

from django.urls import path

from training import views

app_name = "training"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("registrazione/", views.SignUpView.as_view(), name="signup"),
    path("profilo/", views.ProfileUpdateView.as_view(), name="profile"),
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
]
