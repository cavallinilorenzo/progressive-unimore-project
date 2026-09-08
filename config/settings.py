"""Impostazioni di Progressive.

Progetto locale d'esame: `DEBUG = True`, SQLite, nessun deploy. Lo stack segue
la regola posta in `docs/spec/00-indice.md` — si adotta ciò che il prof usa nel
progetto d'esempio del corso, perché ogni deviazione costa tempo e non rende voto.

L'unica deviazione strutturale è `AUTH_USER_MODEL`, subito sotto: va dichiarata
**prima** della primissima migrazione, e per questo il progetto nasce già con
l'app `training` e il suo `User` al posto. Vedi ADR-0003.
"""

from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-)nhx93d2+vx3ma=lmn#98)y5bvt60f95$nyr4wcx49_xs%+9%7'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    'training',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

# Il custom user model è la prima riga che conta di questo file: cambiarlo dopo
# la migrazione iniziale costa una migrazione dolorosa, prenderlo subito costa
# zero. Vedi docs/adr/0003-custom-user-model.md.
AUTH_USER_MODEL = 'training.User'

# Le tre rotte dell'autenticazione, tutte per nome e non per percorso.
#
# `LOGIN_REDIRECT_URL` va dichiarato: il default di Django è
# `/accounts/profile/`, una rotta che questo progetto non ha — il profilo qui
# è `/profilo/`, di dominio, non sotto `/accounts/`. Chi entra atterra sulla
# dashboard, che è la pagina che risponde alla domanda «come sto andando».
#
# `LOGOUT_REDIRECT_URL` resta invece **non** dichiarato di proposito: senza,
# `LogoutView` rende `registration/logged_out.html`, che è una pagina vera del
# progetto e come tutte le altre estende `base.html`.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "training:dashboard"

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'it-it'

TIME_ZONE = 'Europe/Rome'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

# I CSV dello storico allenamenti caricati dal form d'import atterrano qui e
# vengono riparsificati alla conferma. Vedi docs/spec/03-import-ed-export.md.
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}
