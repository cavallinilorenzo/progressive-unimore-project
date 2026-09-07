# Convenzioni del corso IWC: cosa ha insegnato il prof. Faenza

**Ticket**: [#22](https://github.com/cavallinilorenzo/progetto-django-uni/issues/22)
**Data**: 2026-09-07

## Fonti (tutte primarie, lette per intero)

Repo del corso: `secloud-classes/internet-web-and-cloud` su `git.wl.ing.unimore.it`,
letto via API GitLab senza autenticazione.

| Sigla | Fonte | Note |
|---|---|---|
| `S1` | `docs/slides/01_IWC_django_fundamentals.pdf` | 46 slide, datate 5 maggio 2026 |
| `S2` | `docs/slides/02_IWC_django_template_and_views.pdf` | 42 slide |
| `S3` | `docs/slides/03_IWC_django_authentication.pdf` | 28 slide |
| `E` | codice dell'esempio su `main` | `blog/`, `config/`, `templates/`, `README.md` |

Le slide 01 e 02 si sovrappongono parzialmente: le sezioni Templates, CBV e debug VSCode
sono ripetute quasi identiche in entrambe. Il corso, per come risulta da questi tre file,
copre **tre lezioni** e nient'altro.

Albero completo dell'esempio (nessun file omesso, a parte immagini e `uv.lock`):

```
manage.py  pyproject.toml  uv.lock  .python-version  .vscode/launch.json
README.md  docs/UV.md  docs/vscode-debug.md  docs/slides/*.pdf
config/    __init__ settings.py urls.py views.py asgi.py wsgi.py
blog/      __init__ admin.py apps.py models.py views.py urls.py tests.py
           migrations/0001_initial.py 0002_alter_post_options.py
           static/blog/css/main.css  static/blog/image/...
           templates/blog/post/{listview,detailview,deleteview,post_form}.html
templates/ base.html
templates/registration/ login.html signup.html logged_out.html
                        password_reset_{form,done,confirm,complete}.html
```

Il fatto che salta all'occhio: **non esiste `blog/forms.py`**. Vedi §4.

---

## 1. Viste: class-based, punto

**Convenzione**: tutte le viste di Progressive sono CBV generiche. Le FBV solo dove una CBV
sarebbe una forzatura, e con una motivazione pronta per l'orale.

- `E blog/views.py` contiene **solo classi**, nessuna funzione. Zero FBV in tutto il progetto.
  `config/views.py` è un file da 37 byte con dentro un solo `from django.http import HttpResponse`
  e nient'altro — residuo, non una vista.
- `S1 p23` «Why Class-Based Views (CBV)?» elenca solo i vantaggi delle CBV. `S1 p46` assegna
  come compito: «Create a simple blog with CRUD operations **using CBVs**».
- `S2 p18` è l'unico posto dove mostra una FBV, e la mette **a confronto** con la CBV
  equivalente. `S2 p19` dà la regola esplicita del quando usare le FBV: «Very simple views
  with one HTTP method» e «when you need maximum explicitness and don't plan to reuse».
  Quindi le FBV le ha spiegate, ma come termine di paragone.

**Le CBV che ha nominato** (`S1 p32`, tabella; `S2 p21`, tabella con gli URL tipici):
`ListView`, `DetailView`, `CreateView`, `UpdateView`, `DeleteView`, `TemplateView`,
`RedirectView`, `FormView`, più `View` base (`S1 p24`).

**Le CBV che ha davvero usato** (`E blog/views.py`): `ListView`, `DetailView`, `CreateView`,
`UpdateView`, `DeleteView`. Mai `TemplateView`, mai `FormView`, mai `View` grezza.

**Gli hook di personalizzazione che ha mostrato**: `get_queryset()`, `get_context_data()`,
`form_valid()`, `get_success_url()`, `test_func()` (`S1 p26`, `S1 p29`, `S2 p22`, `S2 p33`).
Nell'esempio usa solo `form_valid()` e `test_func()`.

Attributi di classe che compaiono sempre nello stesso ordine in `E blog/views.py`:
`model`, `fields`, `template_name`, `context_object_name`, `success_url`.

## 2. URL: `path()`, `app_name`, nomi con il trattino

**Convenzioni** (da `E blog/urls.py`, che è il file più denso di convenzioni dell'intero repo):

- Solo `path()`. **`re_path()` non compare mai**, né nelle slide né nel codice. Non ha mai
  nominato le regex negli URL.
- `app_name = 'blog'` nell'`urls.py` dell'app, e quindi riferimenti namespaced
  `{% url 'blog:post-detail' %}` nei template. Nota: `app_name` **non è nelle slide** —
  `S1 p30` e `S2 p20` mostrano `name='post-detail'` senza namespace. È una convenzione che
  compare solo nel codice, dove però è applicata con coerenza.
- **Nomi delle rotte con il trattino, non l'underscore**: `post-list`, `post-detail`,
  `post-create`, `post-update`, `post-delete`. (Unica eccezione nelle slide: `S2 p18` usa
  `redirect('post_list')` in una FBV di esempio — refuso.)
- **Schema degli URL**, identico fra `S1 p30`, `S2 p21` e `E blog/urls.py`:

  ```
  ''                       -> ListView    name="post-list"
  'post/<int:pk>/'         -> DetailView  name="post-detail"
  'post/create/'           -> CreateView  name="post-create"
  'post/<int:pk>/update/'  -> UpdateView  name="post-update"
  'post/<int:pk>/delete/'  -> DeleteView  name="post-delete"
  ```

  Cioè: **singolare** per il segmento della risorsa (`post/`, non `posts/`), `<int:pk>`
  per l'identificativo, verbo in coda. `S2 p21` in tabella scrive `/posts/<int:pk>/edit/`,
  ma il codice usa `update/`: **segui il codice**.
- L'esempio registra la lista **due volte**, su `''` con `name="homepage"` e su `'list-posts/'`
  con `name="post-list"` (`E blog/urls.py`). È una sciatteria dell'esempio, non un pattern
  da imitare — `homepage` non è poi referenziata da nessuna parte.
- `config/urls.py` monta l'app alla radice: `path("", include("blog.urls"))`, più
  `path("accounts/", include("django.contrib.auth.urls"))` e `path("admin/", admin.site.urls)`
  (`E config/urls.py`, coerente con `S1 p31` e `S3 p7`).
- `signup/` sta nell'`urls.py` **dell'app**, non del progetto, ed è quindi
  `blog:signup` (`E blog/urls.py`). Le altre rotte di auth restano sotto `accounts/`
  senza namespace: `{% url 'login' %}`, `{% url 'logout' %}`, `{% url 'password_reset' %}`.

## 3. Template: nomi, posizione, ereditarietà

- **Posizione**: `templates/` alla radice per il layout e per `registration/`;
  `<app>/templates/<app>/...` per il resto (`S1 p34`, `S2 p8`, e `E config/settings.py`
  che ha `DIRS: [BASE_DIR / 'templates']` **insieme a** `APP_DIRS: True`).
- **Nomi dei template**: qui slide e codice divergono, ed è la divergenza più visibile
  di tutto il materiale.
  - Le slide dicono `blog/post_list.html`, `blog/post_detail.html`, `blog/post_form.html`,
    `blog/post_confirm_delete.html` — i default di Django (`S1 p26`, `S1 p29`, `S2 p13`).
  - Il codice usa `blog/post/listview.html`, `blog/post/detailview.html`,
    `blog/post/deleteview.html` — **nomi ricavati dalla classe della vista**, in una
    sottocartella per modello. Ma tiene `post_form.html` (default) per create/update.
  - `template_name` è **sempre dichiarato esplicitamente** in ogni vista dell'esempio,
    proprio perché i nomi non seguono la convenzione automatica.

  **Raccomandazione per Progressive**: usa la sottocartella per modello
  (`workouts/templates/workouts/routine/...`) perché scala meglio con 5-6 modelli, ma dai ai
  file i nomi standard di Django (`routine_list.html`, `routine_detail.html`,
  `routine_form.html`, `routine_confirm_delete.html`) e dichiara comunque `template_name`.
  Così sei allineato sia alla struttura che ha scritto lui sia ai nomi che ha proiettato.
- **`base.html`**: quello dell'esempio ha i blocchi **`title`**, **`extra_style`**, **`content`**
  e basta (`E templates/base.html`). Header e footer sono hard-coded, fuori da qualsiasi blocco.
  La traccia d'esame chiede almeno tre blocchi header/content/footer: il nostro `base.html`
  deve quindi essere **più conforme dell'esempio** (già registrato nel commento su #21).
  Il blocco `extra_style` è una buona idea da tenere: serve a caricare CSS per pagina.
- **Struttura fissa del `base.html`** da replicare: navbar Bootstrap `navbar-dark bg-dark`,
  `<main class="container">` che contiene il blocco messaggi + `{% block content %}`,
  footer, script Bootstrap in fondo. Bootstrap 5.3.0 e Bootstrap Icons 1.11.0 da CDN jsDelivr,
  nessun asset locale a parte `blog/static/blog/css/main.css`.
- Il template figlio apre sempre con `{% extends 'base.html' %}` e, se usa `{% static %}`,
  `{% load static %}` subito sotto.
- Filtri e tag effettivamente usati/nominati: `truncatewords`, `date:"F d, Y"`, `default`,
  `striptags`, `length`, `lower`/`upper`, `safe`, `slugify`, `{% now "Y" %}`, `{% with %}`,
  `{% for %}...{% empty %}`, `{% include %}` (`S1 p41`, `S2 p15`, `E` template vari).
  `{% empty %}` è usato in ogni lista dell'esempio: mettilo sempre.
- Marcatura dello stato attivo della navbar via
  `{% if request.resolver_match.url_name == 'post-list' %}active{% endif %}`
  (`E templates/base.html`) — dettaglio che non è nelle slide.

## 4. Form: le slide li spiegano, l'esempio non li usa

Questa è la discrepanza più importante del materiale.

- `S2 p23-38` è una sezione intera sui form: `forms.Form` vs `forms.ModelForm` con tanto di
  gerarchia di ereditarietà (`p25`), `forms.py` dentro l'app (`p26`), `is_valid()` /
  `cleaned_data` (`p27-28`), rendering con `{{ form.as_p }}` (`p29`), **validazione a due
  livelli** — `clean_<campo>()` per campo e `clean()` per la validazione incrociata (`p30`) —
  visualizzazione degli errori con `form.non_field_errors` e `field.errors` (`p31`),
  `Meta.model/fields/widgets/labels/help_texts` di `ModelForm` (`p32`),
  `form_class = PostForm` sulla CBV (`p33`), template unico create/update discriminato da
  `form.instance.pk` (`p34`), CSRF (`p35`), e upload di file con `FileField` + `request.FILES`
  + `enctype="multipart/form-data"` (`p37-38`).
- **Nell'esempio non c'è `blog/forms.py`.** Le CBV usano `fields = ['title', 'content',
  'published', 'categories']`, cioè il `ModelForm` implicito generato da Django
  (`E blog/views.py`). L'unico `form_class` è `UserCreationForm` in `SignUpView`.

**Convenzione per Progressive**: usa `ModelForm` espliciti in `<app>/forms.py` con
`form_class = ...` sulle CBV. È esattamente ciò che `S2 p32-33` insegna, ed è la strada su cui
puoi mostrare `clean_<campo>()` e `clean()` — che lui ha spiegato ma non ha mai messo in pratica.
È un punto dove superare l'esempio costa poco e paga all'orale.

Rendering dei form: le slide mostrano `{{ form.as_p }}` (`S2 p29`, `S3 p13`), l'esempio
**scrive gli `<input>` a mano** con le classi Bootstrap e `is-invalid` +
`<div class="invalid-feedback">` (`E blog/templates/blog/post/post_form.html`,
`templates/registration/login.html`, `signup.html`). Il rendering manuale è verboso e fragile
(nel `post_form.html` la `<select multiple>` delle categorie è ricostruita a mano, con un
`{% if choice.0 in form.categories.value %}` che è fragile). Per Progressive: `{{ form.as_p }}`
o un partial di rendering campo-per-campo riusabile, ma **niente `<input>` copiati per ogni form**.

`{% csrf_token %}` in ogni `<form method="post">`, senza eccezioni (`S2 p35`, `S3 p11`,
e ogni form dell'esempio). Il form del `DeleteView` è un `<form method="post">` con solo il
token e il bottone (`E deleteview.html`).

## 5. Autenticazione

Tutto quello che serve è in `S3` e in `E`, e le due fonti concordano.

- **`User` di `django.contrib.auth`, non custom.** `S3 p6` spiega `AbstractUser` +
  `AUTH_USER_MODEL` e avverte di farlo prima della prima migrazione, ma l'esempio **non lo fa**:
  usa `User` e ci attacca un profilo `Author` con `OneToOneField(User, on_delete=CASCADE)`
  (`E blog/models.py`, e `S1 p14` mostra lo stesso identico pattern).
  **Per Progressive: profilo separato con `OneToOneField`, non custom user.**
- **URL di auth**: `path("accounts/", include("django.contrib.auth.urls"))` (`S3 p7`,
  `E config/urls.py`). Dà login, logout, password_change, password_reset e i loro `done`/`confirm`.
- **Template in `templates/registration/`**, nomi fissati da Django: `login.html`,
  `logged_out.html`, `password_reset_form.html`, `password_reset_done.html`,
  `password_reset_confirm.html`, `password_reset_complete.html` (`S3 p8`, e i file dell'esempio).
  L'esempio li ha scritti **tutti e sette** compresi quelli di reset password: è il livello
  di completezza atteso.
- **Signup fatto a mano**, perché Django non ne fornisce uno: `SignUpView(CreateView)` con
  `form_class = UserCreationForm`, `success_url = reverse_lazy('login')`,
  `template_name = 'registration/signup.html'` (`S3 p12-13`, `E blog/views.py`).
  L'esempio aggiunge il pezzo che le slide non hanno: override di `form_valid()` che chiama
  `super()` e poi crea il profilo `Author` collegato a `self.object`.
  **Per Progressive: identico, creando il profilo utente nel `form_valid()` del signup.**
- **Impostazioni** (`S3 p10`, `E config/settings.py`, in fondo sotto il commento
  `# Authentication settings`):
  ```python
  LOGIN_REDIRECT_URL = "blog:post-list"
  LOGOUT_REDIRECT_URL = "blog:post-list"
  LOGIN_URL = "login"
  ```
- **Logout è POST**, mai un link `<a>` (`S3 p11` lo dice esplicitamente,
  `E templates/base.html` lo implementa come `<form>` dentro il dropdown della navbar).
  In Django 6 non c'è alternativa comunque, ma è un punto che ha sottolineato.
- **Protezione delle viste**, tre modi (`S3 p14`): `@login_required` per le FBV (`p15`),
  `LoginRequiredMixin` per le CBV (`p17`), `request.user.is_authenticated` inline.
  `S3 p17` avverte: **«LoginRequiredMixin MUST be placed before the generic view class»**.
  L'esempio rispetta l'ordine ovunque: `class PostCreateView(LoginRequiredMixin, CreateView)`.
- **Permessi**: quelli automatici `add_/change_/delete_/view_<model>` (`S3 p19`) e quelli
  custom dichiarati in `Meta.permissions` (`S3 p20-21`). L'esempio ne definisce tre su `Post`:
  `can_publish_post`, `can_unpublish_post`, `can_edit_any_post` (`E blog/models.py`), e li
  materializza con una migrazione dedicata (`0002_alter_post_options.py`).
  Nel template: `{% if perms.blog.can_edit_any_post %}` (`S3 p19`, `E detailview.html`).
- **Proprietà dell'oggetto**: `UserPassesTestMixin` + `test_func()`. È il pattern che
  l'esempio usa per «solo l'autore o chi ha il permesso può modificare» e «solo l'autore o
  un superuser può cancellare» (`E blog/views.py`). Curiosamente **`UserPassesTestMixin`
  non compare in nessuna slide** — `S3 p23` mostra solo `PermissionRequiredMixin` con
  `raise_exception = True` e `handle_no_permission()`. È il pattern chiave da avere pronto:
  è nel suo codice ma non nelle sue slide, quindi lo riconoscerà e vorrà sentirtelo spiegare.
- **Gruppi**: `S3 p22` e `S3 p24` (esempio «Authors / Editors / Admins»). Nel codice
  dell'esempio i gruppi **non sono usati**: i controlli sono per permesso e per proprietà.
- Nascondere le azioni non permesse anche nel template, non solo nella vista
  (`E detailview.html`: i bottoni Edit e Delete sono dentro `{% if user == object.author.user
  or perms.blog.can_edit_any_post %}`). Doppio controllo, vista + template.

## 6. Modelli e ORM: molto meno di quanto ci serve

Questo è il punto in cui Progressive si allontana di più dal corso.

**Cosa ha spiegato davvero**:
- Campi (`S1 p13`): `CharField`, `TextField`, `IntegerField`, `FloatField`, `BooleanField`,
  `DateTimeField`, `EmailField`, `URLField`, `FileField`, `ImageField`. Opzioni:
  `max_length`, `null`, `blank`, `default`, `unique`, `on_delete`.
  **`DecimalField` non è nella lista** — per i carichi in kg usa `DecimalField` comunque,
  ma sappi che non l'ha nominato.
- Relazioni (`S1 p13-14`): `ForeignKey`, `OneToOneField`, `ManyToManyField`, con la regola
  «ForeignKey goes on the "many" side». `related_name` **non è mai nominato**, né nelle
  slide né nel codice: l'esempio interroga con il default `post_set` / lookup `post`.
- `class Meta: ordering = ['-created_at']` e `__str__` (`S1 p11`). L'esempio scrive
  `__str__` su tutti e tre i modelli, con il formato `f'{self.name} (id: {self.id})'`;
  **non** definisce `ordering` (usa `Meta` solo per `permissions`).
- Migrazioni: `makemigrations`, `migrate`, `showmigrations`, `migrate <app> zero`
  per il rollback (`S1 p16`). «Never edit migration files manually».
- CRUD via ORM (`S1 p18`): `create()`, `all()`, `get()`, `filter()`, `save()`,
  `update()` bulk, `delete()` bulk.
- QuerySet (`S1 p19`): `filter()`, `exclude()`, `order_by()`, `Q()` con `|`, `count()`,
  e — unica riga di ORM avanzato in tutto il corso —
  `Author.objects.annotate(post_count=Count('post'))`.
  Lookup: `__exact`, `__iexact`, `__contains`, `__icontains`, `__gt`, `__gte`, `__lt`,
  `__lte`, `__in`, `__startswith`, `__year`, `__month`, `__day`.

**Cosa NON ha mai nominato** (rilevante per il motore analitico di Progressive):
`aggregate()`, `Sum`/`Avg`/`Max`/`Min`, `F()`, `Value`, `Case`/`When`, `Subquery`/`OuterRef`,
`Window`/`Lag`/`Lead`/`Rank`, `select_related`/`prefetch_related`, `values()`/`values_list()`,
`distinct()`, `only()`/`defer()`, `bulk_create()`, `get_object_or_404()`, `transaction.atomic()`,
manager e queryset custom, indici, `constraints`, `UniqueConstraint`, campi JSON.

`annotate` è l'unico ponte che esiste fra ciò che ha spiegato e ciò che vogliamo fare:
**parti da lì quando lo racconti**. «Lei ci ha mostrato `annotate(Count(...))`; io ho seguito
lo stesso principio — calcolare nel database, non in Python — fino a `Window` e `Subquery`».

Nota su `count()`: l'esempio non usa nemmeno quello. Il livello di ORM del suo codice è
`Post.objects.all()` implicito dentro `ListView`, e basta.

## 7. Organizzazione del progetto

Fissata da `S1 p7-9` e confermata da `E`:

- Progetto creato con `uv run django-admin startproject config .` — quindi il package di
  progetto si chiama **`config`** e sta alla radice, non annidato.
- **`uv` come gestore pacchetti**: `uv init`, `uv add django`, `uv sync`,
  `uv run python manage.py <cmd>`. Mai `pip`, mai `source .venv/bin/activate`
  (`S1 p6-7`, `E README.md`, `docs/UV.md`). Nel README: «Always run `uv sync` after switching».
- `pyproject.toml` + `uv.lock` versionati, `.venv/` no, `db.sqlite3` **non versionato**
  (`E README.md`).
- **Una sola app** nell'esempio (`blog`), registrata in `INSTALLED_APPS` come stringa
  semplice `'blog'` in coda alle app di `django.contrib` (`S1 p9`, `E config/settings.py`).
  Con 5-6 modelli e un motore analitico, più app in Progressive sono difendibili, ma
  **l'esempio non offre un precedente**: se le separi, sappi motivarlo.
- Statici: `blog/static/blog/css/main.css` — cioè `<app>/static/<app>/...`, con il doppio
  livello che evita le collisioni. `settings.py` dichiara anche
  `STATICFILES_DIRS = [BASE_DIR / 'static']`, ma **quella cartella non esiste nel repo**:
  è dichiarata e non usata. Nel template: `{% load static %}` + `{% static 'blog/css/main.css' %}`.
- SQLite di default, `DEBUG = True`, `SECRET_KEY` in chiaro nel settings, `ALLOWED_HOSTS = []`:
  l'esempio lascia il `settings.py` generato da `startproject` così com'è, cambiando solo
  `INSTALLED_APPS`, `TEMPLATES['DIRS']`, `STATICFILES_DIRS` e le tre righe di auth in fondo.
  Nessun `.env`, nessuna separazione dev/prod. **Non over-engineerizzare il settings.**
  `LANGUAGE_CODE = "en-us"` e `TIME_ZONE = "UTC"` sono rimasti i default: per Progressive
  `it-it` / `Europe/Rome` è una deviazione minima e sensata (interfaccia in italiano).
- `.vscode/launch.json` con la configurazione `debugpy` per Django (`S1 p43-44`, `S2 p5-6`).
  L'ha ripetuta in due lezioni su tre: tienila nel repo, è gratis.
- **Test**: `blog/tests.py` esiste ed è sostanzioso — 13 KB, 25 metodi `test_*`, tutti su
  autenticazione e permessi, con `django.test.TestCase` + `Client` + `reverse()` +
  `self.client.login(...)` e assert sugli status code 200/302/403 (`S3 p25`). Un singolo file
  `tests.py` per app, niente pytest, niente factory.
  Questo risponde a una delle voci «Not yet specified» della mappa: la strategia di test
  attesa è `TestCase` + `Client` su un file solo, concentrata su chi può fare cosa.

## 8. Argomenti che ha spiegato e che noi rischiamo di non usare

Sono i punti su cui può interrogarti perché li ha proiettati lui. Ognuno vale o una feature
in Progressive o una risposta pronta.

| Argomento | Fonte | Nota |
|---|---|---|
| `paginate_by` su `ListView` | `S1 p26` | Nell'esempio non è usato. **Da mettere**: costa una riga e le nostre liste sono lunghe. |
| `get_queryset()` per filtrare | `S1 p26`, `S3 p17` | Ci serve comunque (dati per utente). Assicurati che ci sia. |
| `get_context_data()` | `S1 p26` | Idem: ci serve per le dashboard. |
| `FormView` | `S2 p21`, `S2 p36` | Non usato nell'esempio. **L'import CSV è il candidato naturale**: form non legato a un modello. |
| Upload file con `FileField` / `request.FILES` / `enctype` | `S2 p37-38` | Direttamente applicabile all'import CSV. Da fare esattamente così. |
| `forms.Form` e `ModelForm` in `forms.py` | `S2 p25-33` | Spiegato ma non usato nell'esempio. Usalo. |
| `clean_<campo>()` e `clean()` | `S2 p30` | Il posto giusto è la validazione riga per riga del CSV. |
| Gruppi (`Group`) | `S3 p22`, `S3 p24` | Progressive è multiutente ma senza ruoli. Se non li usi, sappi dire perché (nessun ruolo redazionale: ogni utente vede i propri dati). |
| `PermissionRequiredMixin` + `raise_exception` | `S3 p23` | Se usi solo `UserPassesTestMixin`, tienilo presente come alternativa da citare. |
| Custom `ModelAdmin` (`list_display`, `list_filter`, `search_fields`, `date_hierarchy`) | `S1 p21` | L'esempio fa solo `admin.site.register(Model)` nudo. Un `ModelAdmin` custom su 2-3 modelli è un guadagno a costo quasi zero. |
| Permessi custom in `Meta.permissions` | `S3 p20`, `E models.py` | Probabilmente non ci servono. Risposta pronta: i nostri confini sono di proprietà del dato, non di ruolo. |
| `TemplateView` e `RedirectView` | `S1 p32` | Solo tabellati. `TemplateView` può servire per una home statica. |
| `Q()` con OR | `S1 p19` | Se aggiungi una ricerca esercizi, usalo — è farina del suo sacco. |
| Custom User via `AbstractUser` | `S3 p6` | Non lo usiamo. Risposta pronta: lui stesso ha scelto il profilo `OneToOne` nel suo esempio. |
| Rollback delle migrazioni (`migrate app zero`) | `S1 p16` | Da sapere a voce. |
| Messaggi framework (`{% if messages %}`) | `S1 p37`, `E base.html` | Il `base.html` dell'esempio ha il blocco messaggi ma **nessuna vista chiama `messages.success()`**. Noi dobbiamo usarli davvero. |

## 9. Argomenti che useremo e che lui non ha spiegato

Da saper giustificare all'orale, ciascuno con una frase che lo aggancia a qualcosa che
*ha* spiegato.

| Cosa | Aggancio a ciò che ha spiegato |
|---|---|
| `aggregate()`, `Sum`/`Avg`/`Max` | Estensione diretta di `annotate(Count(...))`, `S1 p19`. |
| `F()`, `Subquery`/`OuterRef`, `Window`/`Lag`, percentili | Stesso principio dell'ORM di `S1 p12`: «il calcolo sta nel database, non in Python». |
| `select_related` / `prefetch_related` | Non nominato. Motivazione: la N+1 sulle liste — dimostrabile con la debug toolbar o con `queryset.query`. |
| `values()` / `values_list()` | Serve per alimentare gli endpoint dei grafici. |
| `get_object_or_404` | `S2 p20` dice che con `DetailView` «no manual `get_object_or_404` needed» — cioè lo nomina solo per dire che non serve. Se lo usi, è in una FBV o in un endpoint dati. |
| Management command (`BaseCommand`) | Mai nominato. Serve per l'import della libreria esercizi. Motivazione: è import una tantum, non interazione utente — quello passa dal form. |
| `related_name` | Mai nominato. Con 5-6 modelli correlati i `_set` diventano illeggibili. Motivazione puramente di leggibilità. |
| `DecimalField` | Non nella lista di `S1 p13`. Motivazione: i carichi sono valori monetariamente esatti, il float li rovinerebbe. |
| `constraints` / `UniqueConstraint` / indici | Mai nominati. |
| `transaction.atomic()` | Mai nominato. Serve per rendere atomico l'import CSV. |
| Chart.js su endpoint Django | Nessun JavaScript applicativo in tutto il corso; l'unico `<script>` è il bundle Bootstrap. **È l'unica deviazione dichiarata dallo stack del corso** (già registrata sulla mappa #11): va motivata come «i grafici sono la resa del motore analitico, e i dati arrivano da una vista Django». |
| Chiusura `messages` usata sul serio | Il framework è configurato nel suo `base.html` ma mai invocato. Usarlo è un miglioramento, non una deviazione. |
| Più di una app | L'esempio ne ha una. Se separi, motiva. |
| ML / scikit-learn | Fuori corso a ogni titolo. È l'ultima cosa da costruire e la prima da tagliare (ordine deciso sulla mappa #11). |

---

## Riepilogo azionabile

Le regole da applicare scrivendo codice, in ordine di quanto sono vincolanti:

1. **Solo CBV generiche** (`ListView`/`DetailView`/`CreateView`/`UpdateView`/`DeleteView`),
   `template_name` sempre esplicito, `LoginRequiredMixin` per primo nella lista delle basi.
2. **`path()` soltanto**, `app_name` in ogni app, nomi rotta `modello-verbo` col trattino,
   URL `''` / `model/<int:pk>/` / `model/create/` / `model/<int:pk>/update/` /
   `model/<int:pk>/delete/`.
3. **`templates/` alla radice** per `base.html` e `registration/`, `<app>/templates/<app>/<modello>/`
   per il resto, `DIRS` + `APP_DIRS: True` insieme.
4. **`base.html`** con Bootstrap 5.3.0 e Bootstrap Icons da CDN, navbar dark, blocco messaggi
   dentro `<main>`, script in fondo; blocchi `title`, `extra_style`, e i tre della traccia
   (`header`/`content`/`footer`) — più dell'esempio, perché la traccia lo chiede.
5. **`ModelForm` in `<app>/forms.py`** con `form_class` sulle CBV, `clean_<campo>()`/`clean()`
   dove serve validare, `{% csrf_token %}` sempre, `{{ form.as_p }}` o un partial riusabile.
6. **Auth**: `User` standard + profilo `OneToOneField`, `include('django.contrib.auth.urls')`,
   tutti i template di `registration/` compreso il reset password, `SignUpView(CreateView)`
   con `UserCreationForm` e creazione del profilo in `form_valid()`, le tre impostazioni
   `LOGIN_REDIRECT_URL`/`LOGOUT_REDIRECT_URL`/`LOGIN_URL`, logout via POST,
   `UserPassesTestMixin.test_func()` per la proprietà del dato, controllo ripetuto nel template.
7. **`uv` sempre**: `uv run python manage.py ...`, `pyproject.toml` + `uv.lock` versionati,
   `db.sqlite3` no.
8. **`settings.py` minimale**, quello di `startproject` con le poche righe che servono.
   Niente `.env`, niente split dev/prod.
9. **Test**: un `tests.py` per app, `TestCase` + `Client` + `reverse()`, concentrati su
   chi può fare cosa (status 200/302/403).
10. **`paginate_by`, `get_queryset()`, `get_context_data()`, `messages`, `ModelAdmin` custom**:
    tutti spiegati, tutti assenti dal suo esempio, tutti a costo quasi nullo. Metterli è il
    modo più economico di far vedere che le slide sono state lette.
