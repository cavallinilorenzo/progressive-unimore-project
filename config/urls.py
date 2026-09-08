"""Le rotte del progetto.

Tutto ciò che è di dominio vive in `training/urls.py` sotto `app_name`; qui
restano solo l'admin e l'inclusione. Le pagine d'errore usano gli handler di
default di Django, che raccolgono `templates/404.html` e `templates/500.html`
— entrambe estendono `base.html`, come impone la traccia.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("training.urls")),
]
