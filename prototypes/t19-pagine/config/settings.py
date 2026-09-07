"""PROTOTIPO — ticket #19. Impostazioni minime: nessun database, nessuna auth.

Il prototipo risponde a «che aspetto ha Progressive», non «il backend funziona»:
i dati della dashboard sono finti e stanno in `views.py`.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "prototipo-non-usare-in-produzione"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = ["django.contrib.staticfiles"]
MIDDLEWARE = ["django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": ["django.template.context_processors.request"]
        },
    }
]

STATIC_URL = "static/"
USE_TZ = True
LANGUAGE_CODE = "it"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
