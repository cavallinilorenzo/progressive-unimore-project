# Progressive

Registro degli allenamenti che misura la **progressione del carico**: si
registra quello che si è sollevato, e l'app dice cosa fare di diverso la volta
dopo. Progetto d'esame di **Interazione Web e Comunicazione** (prof. Francesco
Faenza, UniMoRe), IWC 2026, individuale, in Django.

Tre strati, in ordine di importanza decrescente: il **coach** che dice cosa
fare, il **motore analitico** che lo giustifica, la **parte sociale** come
contorno. Erede concettuale di *Overload*, un'app iOS scritta in precedenza
dallo stesso autore: da lì vengono lo schema dati, la tassonomia muscolare e
la figura anatomica usata dalla heatmap (vedi *Crediti*, sotto).

---

## Indice

1. [Come si avvia](#come-si-avvia)
2. [Stack e dipendenze](#stack-e-dipendenze)
3. [Struttura del repository, file per file](#struttura-del-repository-file-per-file)
4. [Il modello dei dati](#il-modello-dei-dati)
5. [Comandi utili](#comandi-utili)
6. [Documentazione](#documentazione)
7. [Crediti — la figura anatomica non è lavoro nostro](#crediti--la-figura-anatomica-non-è-lavoro-nostro)
8. [Limiti dichiarati](#limiti-dichiarati)

---

## Come si avvia

Progetto **solo locale**, nessun deploy: SQLite, `DEBUG = True`, niente
Docker, niente servizi esterni da provisionare (a parte i CDN di Bootstrap e
Chart.js, richiamati via `<script>`/`<link>` — serve solo una connessione
internet nel browser che apre l'app, non nel server).

### Prerequisiti

- **Python ≥ 3.12** (vincolo di `pyproject.toml`)
- **[`uv`](https://docs.astral.sh/uv/)** come gestore pacchetti — è la scelta
  di progetto, non un'alternativa a `pip`/`venv`. Se non è installato:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- Nessun Node/npm: non c'è build frontend. Bootstrap 5.3.0 e Chart.js 4.4.1
  arrivano da CDN (`jsdelivr`), a versione fissata, richiamati direttamente
  nei template.

### Setup da zero

```bash
git clone <url-del-repo>
cd progetto-django-uni

# 1. Installa le dipendenze Python in un venv locale (.venv/), da uv.lock
uv sync

# 2. Crea lo schema del database (SQLite, file db.sqlite3 nella root)
uv run python manage.py migrate

# 3. Carica il catalogo esercizi — obbligatorio, quasi tutto il resto vi
#    appoggia una foreign key. Idempotente: si può rilanciare.
uv run python manage.py load_catalog

# 4. Genera la popolazione sintetica (100 utenti con storico credibile):
#    è ciò che dà un senso a classifiche, percentili e stallo, che sui
#    dati reali di un solo utente non avrebbero popolazione su cui girare.
#    Ci mette qualche minuto: genera storico per 100 utenti.
uv run python manage.py seed_synthetic

# 5. (Facoltativo) Rigenera schede e storico dell'utente demo con dati
#    coerenti fra scheda e allenamento — seed_synthetic da solo assegna
#    storico generico anche a lui.
uv run python manage.py seed_demo_lorenzo --reset

# 6. Crea un utente amministratore per /admin/
uv run python manage.py createsuperuser

# 7. Avvia il server di sviluppo
uv run python manage.py runserver
```

L'app risponde su `http://127.0.0.1:8000/`. L'ordine dei passi 2→4 non è
intercambiabile: `AUTH_USER_MODEL` è già fissato su `training.User` prima
della prima migrazione (vedi [ADR-0003](docs/adr/0003-custom-user-model.md)),
e `seed_synthetic` presuppone il catalogo già caricato.

Se si preferisce non usare `uv run` a ogni comando, si può attivare il venv
una volta (`source .venv/bin/activate`) e lanciare `python manage.py ...`
direttamente.

### Login

Dopo `seed_synthetic`, esiste un utente `cavallinilorenzo` (Lorenzo
Cavallini) pensato come account demo, con `is_synthetic=False` e storico
generato — dichiarato come tale in interfaccia. Gli altri ~99 utenti hanno
`is_synthetic=True`. Le password degli utenti sintetici sono generate dal
comando stesso (vedi `docs/generatore-sintetico.md` per i dettagli); in
alternativa si crea un utente nuovo da `/registrazione/`.

---

## Stack e dipendenze

Tutto lo stack segue una regola unica, posta il 2026-09-07 e scritta in
`docs/spec/00-indice.md`: **si adotta ciò che il prof usa nel suo progetto
d'esempio**, perché ogni deviazione costa tempo e non rende voto.

| Livello | Scelta | Perché |
|---|---|---|
| Linguaggio | Python ≥ 3.12 | vincolo `pyproject.toml` |
| Framework | **Django ≥ 6.0.3** | unica dipendenza dell'esempio del corso — è anche l'**unica dipendenza di `pyproject.toml`**, punto |
| Package manager | **`uv`** | gestisce venv e lockfile (`uv.lock`) in un solo tool |
| Database | **SQLite** | `db.sqlite3` nella root, nessun server DB da installare |
| CSS | **Bootstrap 5.3.0 da CDN** | niente build step, versione fissata nell'URL |
| JS applicativo | **nessuno**, salvo **Chart.js 4.4.1 da CDN** | l'unica eccezione dichiarata: alimentato via `{% json_script %}`, mai fetch o stato client |
| Deploy | nessuno | solo locale, l'esame si discute su una macchina |

Le uniche due deviazioni consapevoli dallo stack "puro corso", entrambe da
dichiarare (e spiegate negli ADR):

1. **Custom user model** (`training.User`) al posto di un `Profile` in
   `OneToOne` — [ADR-0003](docs/adr/0003-custom-user-model.md).
2. **~100 righe di CSS custom** della shell "Pulse" in `static/css/`, sopra
   Bootstrap.

`pyproject.toml` per intero:

```toml
[project]
name = "progressive"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "django>=6.0.3",
]
```

Nessun DRF, nessun Celery, nessun Redis, nessuna libreria di test oltre
`django.test` — è una scelta, non un buco: il corso non le richiede e ogni
dipendenza in più è una riga da giustificare all'orale.

---

## Struttura del repository, file per file

```
progetto-django-uni/
├── manage.py                  # entrypoint standard di Django
├── pyproject.toml / uv.lock   # dipendenze (vedi sopra)
├── db.sqlite3                 # database SQLite locale (generato, ignorato da git)
├── CLAUDE.md                  # istruzioni per agenti AI che lavorano sul repo
├── CONTEXT.md                 # glossario del dominio — leggere prima di tutto il resto
├── README.md                  # questo file
│
├── config/                    # progetto Django in senso stretto (settaggi globali)
│   ├── settings.py            # AUTH_USER_MODEL, TEMPLATES, DATABASES, LOGIN_URL...
│   ├── urls.py                # include admin/, accounts/ (auth di Django) e training/
│   ├── wsgi.py / asgi.py      # entrypoint per server di produzione (non usati qui)
│   └── __init__.py
│
├── training/                  # l'unica app Django del progetto — tutto il dominio
│   ├── models.py              # i 6+3+1 modelli, tutti in un file (vedi sotto)
│   ├── views.py                # 2010 righe: tutte le class-based view
│   ├── forms.py                # ModelForm, formset, UserCreationForm custom
│   ├── urls.py                  # rotte sotto app_name="training"
│   ├── querysets.py            # WorkoutSetQuerySet: VOLUME, EPLEY, EFFECTIVE_LOAD...
│   ├── rankings.py             # le due classifiche, come query pure (no HTTP)
│   ├── importer.py             # parser dell'import CSV storico, no HTTP
│   ├── exporter.py             # generazione dei CSV di export, chiude il giro dell'import
│   ├── admin.py                # ModelAdmin custom su Exercise, User, Routine
│   ├── tests.py                # test sulle fondamenta (constraint, unicità)
│   │
│   ├── analytics/              # IL MOTORE ANALITICO — "cosa è successo"
│   │   ├── volume.py           # A1/A2 — volume nel tempo e per gruppo muscolare
│   │   ├── progressione.py     # A3/A4/A5 — progressione, record, percentile
│   │   ├── costanza.py         # W1 — allenamenti a settimana (widget dashboard)
│   │   ├── muscles.py          # la heatmap muscolare (serie per muscolo)
│   │   ├── plateau.py          # rilevamento stallo — regola a soglia (fase 4 ML NON fatta)
│   │   └── coach/               # IL COACH — "cosa fare" (vedi sotto)
│   │       ├── __init__.py     # selezione del consiglio per priorità (ADR-0007)
│   │       ├── consiglio.py    # dataclass Consiglio condiviso dal pacchetto
│   │       ├── carico.py       # doppia progressione (l'unica regola di carico)
│   │       └── stallo.py       # deload — l'unica risposta allo stallo
│   │
│   ├── management/commands/
│   │   ├── load_catalog.py     # carica data/catalog/*.csv nel DB (idempotente)
│   │   ├── seed_synthetic.py   # genera i 100 utenti sintetici con storico
│   │   └── seed_demo_lorenzo.py # rigenera scheda+storico dell'utente demo
│   │
│   ├── migrations/              # cronologia delle migrazioni Django
│   ├── tests/fixtures/          # CSV di prova per i test dell'import
│   │
│   └── templates/training/     # template della app (uno per pagina + parziali `_*`)
│       ├── dashboard.html, profile.html
│       ├── routine_*.html       # CRUD scheda + community (pubbliche, dettaglio, voto)
│       ├── workout_*.html       # CRUD allenamento + gestione serie
│       ├── exercise_*.html      # catalogo (sola lettura)
│       ├── ranking_*.html       # le due classifiche
│       ├── import_*.html        # upload → anteprima → esito
│       ├── analysis.html        # /analisi/, le sei analisi
│       ├── _heatmap.html, _corpo.svg   # figura anatomica (vedi Crediti)
│       ├── _grafici_js.html    # include Chart.js da CDN, uso di json_script
│       ├── _consiglio.html     # riquadro del coach, riusato in due punti
│       └── widgets/             # widget di form riusati (formset serie/esercizi)
│
├── templates/                  # template di progetto, fuori dall'app
│   ├── base.html               # il guscio "Pulse": 6 blocchi, extends obbligatorio
│   ├── 404.html / 500.html     # pagine d'errore, estendono base.html anch'esse
│   └── registration/           # login, signup, i quattro step di reset password
│
├── static/
│   ├── css/progressive.css     # le ~100 righe di CSS custom dichiarate (shell Pulse)
│   └── js/                     # vuoto/minimo: niente JS applicativo per scelta
│
├── data/
│   ├── catalog/                # CSV versionati: equipment, exercises, muscle*, il catalogo
│   └── overload-real/          # storico REALE di Lorenzo da Overload — ignorato da git
│                                # (dati personali; si rigenera con scripts/export_overload.py)
│
├── media/imports/              # CSV caricati dall'utente durante l'import (runtime)
│
├── scripts/                    # utility standalone, fuori dal ciclo di vita Django
│   ├── export_overload.py      # esporta lo storico reale da Supabase → data/overload-real/
│   ├── misura_tempi.py         # cronometra le pagine sul DB vero (docs/misure/)
│   └── prototype_seed_synthetic.py  # prototipo usa-e-getta del generatore sintetico
│
├── prototypes/                 # esperimenti isolati, pre-integrazione nell'app
│   ├── t19-pagine/             # il guscio Pulse, prima di diventare base.html
│   ├── t37-heatmap/            # la heatmap muscolare + build_body_svg.mjs (vedi Crediti)
│   └── t98-a3-window/          # prova della window function dietro A3 (progressione)
│
├── docs/
│   ├── spec/                   # IL COME: 00-indice + 01..07 (modelli, pagine, import,
│   │                           #   analisi, coach, dati, test) — vedi sezione Documentazione
│   ├── adr/                    # I PERCHÉ: 12 Architecture Decision Record
│   ├── misure/tempi-query.md   # misure di performance che hanno chiuso ADR-0012
│   ├── research/                # note di ricerca preliminari (stack, dataset, convenzioni)
│   ├── catalogo-esercizi.md    # note sul catalogo scritto a mano
│   ├── generatore-sintetico.md # spiega archetipi e logica di seed_synthetic
│   ├── overload-export.md      # come funziona scripts/export_overload.py
│   └── agents/                  # istruzioni operative per agenti AI (issue tracker, ADR...)
│
└── temp/                        # scarto di lavorazione, non parte del progetto consegnato
    └── 05_IWC_django_progetti_esame.pdf   # la traccia d'esame originale
```

### Il motore analitico vs. il coach — la distinzione che regge `analytics/`

Sono due cose diverse per disegno, non solo per cartella:

- **`training/analytics/*.py`** (fuori da `coach/`) **mostra cosa è
  successo**: volume, progressione, percentile, heatmap. Sono osservazioni,
  non azioni.
- **`training/analytics/coach/`** **dice cosa fare**: ogni consiglio
  (`Consiglio`, dataclass in `consiglio.py`) è azionabile e ha dietro **una
  sola query** (ADR-0007). Il coach non è un modello Django — non persiste
  niente, è uno strato di servizio ricalcolato a ogni richiesta dalle serie
  già registrate.

Le "espressioni" condivise da entrambi (`VOLUME`, `EPLEY`, `EFFECTIVE_LOAD`)
vivono **una sola volta** in `training/querysets.py` e arrivano ovunque per
nome — mai riscritte, per non ripetere una divergenza già avvenuta una volta
nel progetto (#75: la dashboard calcolava il volume senza carico effettivo, e
nessun test se ne accorgeva perché due copie identiche passano entrambe).

---

## Il modello dei dati

Tutti i modelli sono in `training/models.py`, deliberatamente **un file
solo** (come nel progetto d'esempio del corso). Tre strati:

**1. L'utente** — `User(AbstractUser)`, con `body_mass_kg` (peso corporeo
corrente, un solo valore) e `is_synthetic` (per dichiarare gli utenti
generati). Vedi [ADR-0003](docs/adr/0003-custom-user-model.md).

**2. Le anagrafiche** (popolate da CSV, senza CRUD utente):
`MuscleGroup` (6), `Muscle` (23, tassonomia identica a Overload),
`Equipment` (con `default_bar_weight_kg` e `load_increment_kg`).

**3. Le sei entità di prima classe** (quelle contate dalla traccia come
*related models*), più l'infrastruttura dell'import:

| Modello | Cos'è |
|---|---|
| `Exercise` | il catalogo globale, condiviso da tutti, sola lettura per scelta ([ADR-0001](docs/adr/0001-catalogo-esercizi-globale-e-scritto-a-mano.md)) |
| `Routine` | la **scheda**: il piano, mutabile, di un utente |
| `RoutineExercise` | una voce della scheda: esercizio, posizione, serie/ripetizioni obiettivo |
| `Workout` | l'**allenamento**: un log immutabile dell'eseguito ([ADR-0002](docs/adr/0002-allenamento-log-immutabile.md)) |
| `WorkoutSet` | la **serie**: l'unità elementare su cui gira tutto il motore analitico |
| `Vote` | il voto (1–5 + commento) su una scheda pubblica |
| `ExerciseAlias` | infrastruttura dell'import: ricorda a quale esercizio del catalogo corrisponde un nome libero |

Il glossario completo, coi vincoli e le ragioni di ogni campo, è in
[`CONTEXT.md`](CONTEXT.md) e in
[`docs/spec/01-modelli.md`](docs/spec/01-modelli.md).

---

## Comandi utili

```bash
# Migrazioni
uv run python manage.py makemigrations
uv run python manage.py migrate

# Dati
uv run python manage.py load_catalog          # (ri)carica il catalogo esercizi, idempotente
uv run python manage.py seed_synthetic         # genera i 100 utenti + storico
uv run python manage.py seed_demo_lorenzo --reset  # rigenera scheda/storico dell'utente demo

# Test
uv run python manage.py test

# Server di sviluppo
uv run python manage.py runserver

# Admin
uv run python manage.py createsuperuser
# poi http://127.0.0.1:8000/admin/

# Shell Django
uv run python manage.py shell

# Misura dei tempi di pagina sul DB vero (script una tantum, non un test)
uv run python3 scripts/misura_tempi.py --db db.sqlite3
```

---

## Documentazione

Il progetto tiene una disciplina documentale precisa: se una decisione esiste,
è scritta, e va cercata in quest'ordine:

1. **[`CONTEXT.md`](CONTEXT.md)** — il glossario del dominio. Ogni termine
   (Scheda, Allenamento, Serie, Stallo, Deload, Carico effettivo, Massimale,
   Finestra...) ha una definizione precisa in italiano/inglese: usare quella,
   mai un sinonimo.
2. **[`docs/spec/00-indice.md`](docs/spec/00-indice.md)** — *il* documento:
   checklist della traccia riga per riga, le 4 fasi di costruzione (di cui
   solo 1–3 completate), le tecniche ORM introdotte via via.
3. **[`docs/spec/01`–`07`](docs/spec/)** — il *come*: modelli, pagine e
   template, import/export, analisi, coach, dati, test.
4. **[`docs/adr/`](docs/adr/)** — i *perché* delle 12 decisioni più costose
   (custom user model, log immutabile, valori derivati non materializzati,
   carico effettivo, ecc.).

---

## Crediti — la figura anatomica non è lavoro nostro

`training/templates/training/_corpo.svg` è la figura umana su cui si accende
la heatmap muscolare della dashboard: 154 path, fronte e retro, ognuno
etichettato `class="g-<gruppo> m-<muscolo>"`.

**Quei contorni non sono stati disegnati per questo progetto.** Lo script che
genera il file — `prototypes/t37-heatmap/build_body_svg.mjs` — non ridisegna
niente: legge i sei SVG di gruppo muscolare di **Overload**, un'applicazione
personale precedente, ne copia ogni attributo `d` **identico**, e si limita ad
aggiungere le classi CSS risolvendo i 23 muscoli con ancoraggi
point-in-polygon. Stessa geometria, stesso `viewBox`, stessi 154 contorni.

Quei sei SVG sono entrati in Overload col commit iniziale e **la loro origine
non è documentata**: non è certo che siano un disegno originale
([#40](https://github.com/cavallinilorenzo/progetto-django-uni/issues/40)). Il
file è versionato qui perché senza il progetto non gira da un clone pulito e
la heatmap resta vuota, ma va detto in chiaro, e va detto anche all'orale:
**di questa figura il progetto ha scritto le classi, non l'anatomia.**

Se un giorno si accertasse che il disegno non è ridistribuibile, si cancella
`_corpo.svg` e la heatmap ripiega sulle barre per gruppo, che sono già
prototipate (`prototypes/t37-heatmap/`, variante A).

Tutto il resto del repo — codice, template, CSS, catalogo degli esercizi,
dati sintetici — è lavoro del progetto.

---

## Limiti dichiarati

Il progetto sceglie di **dire** i propri limiti invece di nasconderli:

1. **Il percentile tace sotto una soglia minima di utenti** su un esercizio,
   e dice perché.
2. **Lo stallo dice «dati insufficienti»** come stato di avanzamento verso la
   soglia, non come errore.
3. **La heatmap vede solo il muscolo primario** di ogni esercizio: il lavoro
   ricevuto da un muscolo come secondario non arriva sulla figura.
4. **Il peso corporeo riscrive il passato**: è un solo valore corrente, non
   uno storico, quindi cambiarlo oggi cambia anche le analisi su allenamenti
   di mesi fa ([ADR-0008](docs/adr/0008-peso-corporeo-corrente-come-denominatore.md)).
5. **`_corpo.svg` non è lavoro nostro** (vedi *Crediti*, sopra).
6. **La fase 4 (machine learning) non è stata costruita**: lo stallo è
   rilevato dalla regola a soglia di `training/analytics/plateau.py`, non da
   un modello. Era la fase dichiarata "tagliabile" fin dall'inizio, e questo
   è il caso in cui è stata effettivamente tagliata.

Ognuno di questi punti è ripreso, con più dettaglio, in
`docs/spec/00-indice.md` (§«I limiti che si dichiarano») e negli ADR
corrispondenti.
