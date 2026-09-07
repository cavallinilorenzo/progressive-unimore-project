"""PROTOTIPO — ticket #19."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("<path:resto>", views.segnaposto, name="segnaposto"),
]
