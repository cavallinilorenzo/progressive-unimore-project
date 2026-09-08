"""Le rotte del progetto.

Tutto ciò che è di dominio vive in `training/urls.py` sotto `app_name`; qui
restano l'admin, l'autenticazione e l'inclusione. Le pagine d'errore usano gli
handler di default di Django, che raccolgono `templates/404.html` e
`templates/500.html` — entrambe estendono `base.html`, come impone la traccia.

`django.contrib.auth.urls` sotto `/accounts/` porta login, logout e le quattro
rotte di reimpostazione password, con nomi di rotta **senza namespace**
(`{% url 'login' %}`). I template li mette il progetto in
`templates/registration/`, che è il percorso dove quelle view li cercano: è il
pattern del progetto d'esempio del corso. La registrazione non è fra queste —
`django.contrib.auth` non la porta — e sta in `training/urls.py`.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("training.urls")),
]
