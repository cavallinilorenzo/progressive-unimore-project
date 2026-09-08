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
    # Gli esercizi vanno per `slug` e non per `pk`: lo slug è generato una
    # volta da `load_catalog`, quindi l'URL di un esercizio è stabile e
    # leggibile — `/esercizi/panca-piana/`, non `/esercizi/37/`.
    path("esercizi/", views.ExerciseListView.as_view(), name="exercise-list"),
    path(
        "esercizi/<slug:slug>/",
        views.ExerciseDetailView.as_view(),
        name="exercise-detail",
    ),
]
