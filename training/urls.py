"""Le rotte di Progressive.

`app_name` più nomi di rotta **col trattino**, come nell'esempio del corso
(#22). La sitemap completa — cinque sezioni e i loro URL — è in
`docs/spec/02-pagine-e-template.md`; qui c'è la prima, e le altre entrano coi
ticket della mappa #53.
"""

from django.urls import path

from training import views

app_name = "training"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
]
