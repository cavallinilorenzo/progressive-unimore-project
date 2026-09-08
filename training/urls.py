"""Le rotte di Progressive.

`app_name` più nomi di rotta **col trattino**, come nell'esempio del corso
(#22). La sitemap completa — cinque sezioni e i loro URL — è in
`docs/spec/02-pagine-e-template.md`; qui ci sono la dashboard e le pagine
dell'utente, e le altre entrano coi ticket della mappa #53.

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
]
