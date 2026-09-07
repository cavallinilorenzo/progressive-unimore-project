# Tailwind + HTMX in Django senza toolchain pesante

Ricerca per l'issue [#15](https://github.com/cavallinilorenzo/progetto-django-uni/issues/15). Data: 2026-09-07.
Contesto: progetto d'esame IWC, SQLite, solo locale, niente deploy. **La semplicità del setup conta più della sofisticatezza.**

Tutte le affermazioni sono verificate contro fonti primarie (docs ufficiali, registri di pacchetti, sorgente e test suite),
non contro blog post.

---

## 0. TL;DR — la raccomandazione

| Pezzo | Scelta | Perché |
|---|---|---|
| Tailwind | **CLI standalone** via `pytailwindcss` (binario, niente Node) | zero `package.json`, zero `node_modules`, un solo processo di watch |
| HTMX | **file statico, versione 2.0.10 pinnata** | htmx 4 è uscito il 2026-08-28 e ha rotto l'ereditarietà degli attributi; htmx.org ora documenta la 4 |
| Frammenti | **`{% partialdef %}` nativo di Django 6.0** | niente app in più, niente doppio template, e i partial *non* ereditano `base.html` |
| CSRF | `hx-headers` sul `<body>` con `{{ csrf_token }}` | una riga in `base.html`, vale per tutte le richieste |
| Chart.js | **endpoint JSON dedicato** + `JsonResponse` | il template resta HTML, il grafico si ricarica senza ricaricare la pagina |
| Django | **6.1** (oppure 5.2 LTS se serve conservatività) | 6.0+ è l'unica che ha i template partials nativi |

Comandi esatti e struttura di cartelle: sezione [7](#7-raccomandazione-operativa).

---

## 1. Versioni correnti (verificate al 2026-09-07)

| Progetto | Versione stabile | Note |
|---|---|---|
| Django | **6.1.1** | 6.0.8 in extended support; **5.2.17 è l'attuale LTS** (extended fino ad aprile 2028) |
| Tailwind CSS | **4.3.3** (release del 2026-07-16) | binari standalone allegati alla release GitHub |
| htmx | **2.0.10** (dist-tag `latest`) e **4.0.0** (dist-tag `next`) | vedi §3 |
| Chart.js | **4.5.1** | |
| django-tailwind | **4.5.0** | dipende da `django>=4.2.20` e `pytailwindcss>=0.3.0` |
| django-htmx | **1.29.0** | supporta Django 5.2–6.1, Python 3.10–3.15 |
| pytailwindcss | **0.3.1** | |

Fonti: [djangoproject.com/download](https://www.djangoproject.com/download/), GitHub Releases API di
`tailwindlabs/tailwindcss` e `bigskysoftware/htmx`, registry npm, PyPI JSON API.

> **Il ticket ipotizzava «Django 5.x, HTMX 2.x, Tailwind 4.x».** Due delle tre ipotesi vanno aggiornate:
> Django è arrivato alla 6.1, e htmx ha rilasciato la 4.0. Il dettaglio sotto.

---

## 2. Tailwind: le tre opzioni, confronto onesto

### 2.1 Cosa è cambiato in Tailwind 4 (e perché invalida quasi tutte le guide online)

Verificato sulla [upgrade guide ufficiale](https://tailwindcss.com/docs/upgrade-guide). Le guide Django+Tailwind
scritte prima del 2025 sono **tutte sbagliate** su questi punti:

| v3 (guide vecchie) | v4 (realtà) |
|---|---|
| `@tailwind base; @tailwind components; @tailwind utilities;` | **`@import "tailwindcss";`** — una riga sola |
| `tailwind.config.js` con `content: [...]` | **configurazione CSS-first**: `@theme { --color-... }` e `@source "..."` nel CSS |
| config JS auto-rilevato | config JS **non più auto-rilevato**; serve `@config "../../tailwind.config.js"` esplicito |
| `npx tailwindcss` (pacchetto unico) | pacchetti separati: **`@tailwindcss/cli`** e **`@tailwindcss/postcss`** |
| `safelist` nel config | **`@source inline("...")`** |
| — | `corePlugins`, `safelist`, `separator` **non supportati** in v4 |
| supporto browser ampio | solo **Safari 16.4+, Chrome 111+, Firefox 128+** (serve `@property`, `color-mix()`) |

**Il punto che conta di più per Django — il rilevamento automatico delle sorgenti.**
Da [Detecting classes in source files](https://tailwindcss.com/docs/detecting-classes-in-source-files):
Tailwind v4 «uses the current working directory as its starting point when scanning for class names by default»,
escludendo automaticamente `node_modules`, i file binari, i file CSS, i lockfile **e tutto ciò che è in `.gitignore`**.

Conseguenze pratiche per noi:

1. Non serve più elencare i template Django in un `content: []`. Se lanci il CLI dalla root del progetto, i
   `templates/**/*.html` vengono scansionati da soli.
2. **Trappola**: la mappa #11 dice che lo storico reale di Lorenzo sta in `.gitignore`. Va bene, sono CSV.
   Ma se un giorno finisse in `.gitignore` una cartella di template, Tailwind smetterebbe silenziosamente di
   generarne le classi. Da tenere a mente.
3. Se il CLI viene lanciato da una sottocartella (es. `theme/`), serve `@import "tailwindcss" source("../");`
   oppure un `@source` esplicito.

### 2.2 Le tre opzioni

#### Opzione A — `django-tailwind` (4.5.0)

Da [django-tailwind.readthedocs.io](https://django-tailwind.readthedocs.io/en/latest/installation.html) e dalla
pagina `settings.html`:

```
pip install 'django-tailwind[reload]'
# INSTALLED_APPS += ["tailwind", "theme"]
# TAILWIND_APP_NAME = "theme"
python manage.py tailwind init      # crea l'app theme (via cookiecutter)
python manage.py tailwind install   # scarica le dipendenze CSS
python manage.py tailwind dev       # Django + watcher Tailwind insieme (honcho)
python manage.py tailwind build     # build minificata
```

Setting rilevanti, con i default reali:

- `TAILWIND_APP_NAME` — nessun default, convenzione `"theme"`
- `TAILWIND_CSS_PATH` — default `"css/dist/styles.css"`
- **`TAILWIND_USE_STANDALONE_BINARY` — default `False`**
- `TAILWIND_STANDALONE_BINARY_VERSION` — default `"v4.3.0"`
- `NPM_BIN_PATH` — default `"npm"`
- `TAILWIND_STANDALONE_START_COMMAND_ARGS` — default `-i static_src/src/styles.css -o static/css/dist/styles.css --watch`
- `TAILWIND_STANDALONE_BUILD_COMMAND_ARGS` — come sopra ma `--minify`

Nota importante e controintuitiva: **django-tailwind 4.x supporta entrambe le modalità**, ma il *default è npm*.
La modalità standalone (`TAILWIND_USE_STANDALONE_BINARY = True`) usa `pytailwindcss`, non richiede Node,
supporta **solo Tailwind v4** e la doc la descrive come «the simplest possible setup» — al prezzo di
non poter usare plugin (DaisyUI, typography, forms) né PostCSS custom.

Pro: `manage.py tailwind dev` avvia Django e il watcher insieme; integrazione con `django-browser-reload` per il
live reload; il template tag `{% tailwind_css %}` inserisce il `<link>` giusto.
Contro: è comunque una dipendenza in più che nasconde cosa succede; con il default npm ti trascina dentro
`package.json` + `node_modules`; `tailwind init` genera un'app `theme` con una struttura che non hai scelto tu.
All'orale devi saper spiegare cos'è quell'app.

#### Opzione B — CLI standalone (binario, niente Node) ⭐ consigliata

Da [Tailwind CLI docs](https://tailwindcss.com/docs/installation/tailwind-cli): «The Tailwind CLI is also available
as a standalone executable […] without installing Node.js», distribuito nelle GitHub Releases.
Gli asset della release v4.3.3 sono: `tailwindcss-macos-arm64`, `tailwindcss-macos-x64`, `tailwindcss-linux-x64`,
`tailwindcss-linux-arm64`, le varianti musl e `tailwindcss-windows-x64.exe`.

Su un progetto Python la strada più pulita è `pytailwindcss` (0.3.1), il cui claim è letteralmente
«Standalone Tailwind CSS CLI, installable via pip. Use Tailwind CSS without Node.js»:

```
pip install pytailwindcss
tailwindcss_install                       # scarica il binario (l'ultima versione)
export TAILWINDCSS_VERSION=v4.3.3         # per pinnare
tailwindcss -i input.css -o output.css --watch
```

Pro: **nessun Node, nessun `package.json`, nessun `node_modules` nel repo**; la dipendenza sta nel `requirements.txt`
insieme a tutto il resto; il comando è esplicito e spiegabile in dieci secondi all'orale; il file CSS generato è
un normale file `static/`. Contro: due terminali in dev (runserver + watcher) se non usi un `Makefile`;
niente plugin Tailwind; il binario va riscaricato su ogni macchina (ma `tailwindcss_install` lo fa da solo).

#### Opzione C — CDN in dev

Da [Play CDN docs](https://tailwindcss.com/docs/installation/play-cdn):

```html
<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
```

La doc è esplicita: «**The Play CDN is designed for development purposes only, and is not intended for production.**»
Compila il CSS nel browser a runtime.

Pro: zero setup, zero build step, prototipazione istantanea. Contro: FOUC e lentezza percepita; nessun file CSS
versionato; funziona solo con connessione; da mostrare al prof è la scelta che comunica «non ho capito la build».

**Uso raccomandato**: la CDN va bene per i primissimi giorni, mentre si disegnano le pagine, e va sostituita
appena il layout si stabilizza. Non è una scelta architetturale, è un ponteggio.

### 2.3 Cosa finisce nel repo

| | django-tailwind (npm) | django-tailwind (standalone) | CLI standalone | CDN |
|---|---|---|---|---|
| `package.json` / `node_modules` | sì | no | no | no |
| binario Tailwind | no | scaricato, da `.gitignore` | scaricato, da `.gitignore` | no |
| CSS generato | `theme/static/css/dist/styles.css` | idem | dove decidi tu | nessuno |
| dipendenze Python extra | `django-tailwind` (+ honcho, cookiecutter, browser-reload) | idem | `pytailwindcss` | zero |

Il CSS generato **va committato** in un progetto d'esame: garantisce che il prof possa clonare e far girare
`runserver` senza eseguire alcuna build.

---

## 3. HTMX: quale versione, e la trappola del 2026

### 3.1 htmx 4.0.0 è uscito il 2026-08-28

Dall'[annuncio ufficiale](https://github.com/bigskysoftware/htmx/releases/tag/v4.0.0) e da
`www/src/content/docs/whats-new-in-htmx-4.md` nel repo, la citazione decisiva:

> «Note that we are not marking 4.0 as `latest` in NPM because we do not want to force-upgrade users who are relying
> on non-versioned CDN URLs for htmx. Instead, **2.x will remain `latest` and the 4.0 line will remain `next` until
> some point in early 2027**. The website, however, will reference 4.0.»

Confermato dal registry npm: `dist-tags: {latest: 2.0.10, next: 4.0.0}`. E la 2.0.10 è stata pubblicata
il 2026-09-06 — **ieri** — quindi la linea 2 è tutt'altro che abbandonata.

**Questa è la trappola numero uno per chi cerca guide online adesso**: htmx.org mostra la sintassi 4,
mentre ogni tutorial Django+htmx esistente mostra la sintassi 2. Sono incompatibili sul punto che ci serve di più.

### 3.2 Le rotture di htmx 4 che ci toccherebbero

Da `whats-new-in-htmx-4.md` (fonte primaria, repo htmx, tag v4.0.0):

- **Ereditarietà esplicita** — «In htmx 4 attributes are not inherited unless you explicitly say so by adding an
  `:inherited` after the attribute name». È «the largest upgrade burden». **Colpisce direttamente il CSRF**:
  `hx-headers` sul `<body>` smette di funzionare, diventa `hx-headers:inherited`.
- **Le risposte di errore vengono swappate** — htmx 2 non swappava 4xx/5xx; htmx 4 sì (solo 204 e 304 no).
  Con i form Django che rispondono 422/400 su validazione fallita, il comportamento cambia.
- `fetch()` al posto di `XMLHttpRequest` (irreversibile), niente cache history in `localStorage`,
  timeout di default a 60s, ordine degli swap OOB invertito, `hx-ext` rimosso, `hx-disable` → `hx-ignore`,
  `hx-vars`/`hx-params`/`hx-prompt`/`hx-disinherit` rimossi.

### 3.3 Verdetto

**Usa htmx 2.0.10 e pinnalo.** Motivi: è il dist-tag `latest`, è mantenuto attivamente, è la versione che tutta
la documentazione Django di terze parti (inclusa `django-htmx`) assume, e non c'è una singola feature di htmx 4
che serva a questo progetto. In un progetto d'esame la compatibilità con la documentazione esistente vale più
della novità. Se qualcosa non funziona come sul sito htmx.org, è perché il sito documenta la 4.

### 3.4 Statico o CDN?

Snippet CDN dalla doc htmx 2:

```html
<script src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js"
        integrity="sha384-H5SrcfygHmAuTDZphMHqBJLc3FhssKjG7w/CeCpFReSfwBWDTKpkzPP8c+cLsK+V"
        crossorigin="anonymous"></script>
```

**Per questo progetto: file statico.** La mappa #11 dice «solo locale, niente deploy»; un file in `static/vendor/`
garantisce che la demo all'orale funzioni anche senza rete. Scaricalo una volta:

```
curl -L -o static/vendor/htmx.min.js https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js
```

Stesso ragionamento per Chart.js 4.5.1.

---

## 4. CSRF con htmx in Django

### 4.1 Il meccanismo (docs Django)

Da [How to use Django's CSRF protection](https://docs.djangoproject.com/en/6.1/howto/csrf/):
per le richieste AJAX si imposta «a custom `X-CSRFToken` header (as specified by the `CSRF_HEADER_NAME` setting)
to the value of the CSRF token». Django accetta quindi il token in due modi: il campo nascosto
`csrfmiddlewaretoken` (dai form) **oppure** l'header `X-CSRFToken`.

Con i default (`CSRF_USE_SESSIONS = False`, `CSRF_COOKIE_HTTPONLY = False`) il token è leggibile dal cookie
`csrftoken`. Se una vista non renderizza `{% csrf_token %}`, il cookie potrebbe non essere impostato: in quel caso
serve il decoratore `@ensure_csrf_cookie`.

### 4.2 La riga da scrivere (una sola)

Da [django-htmx tips](https://django-htmx.readthedocs.io/en/latest/tips.html):

```html
<body hx-headers='{"x-csrftoken": "{{ csrf_token }}"}'>
```

Due dettagli che si sbagliano spesso:

1. Va usata la **variabile** `{{ csrf_token }}`, non il **tag** `{% csrf_token %}` (che renderizza un `<input>`
   nascosto e produrrebbe HTML rotto dentro un attributo).
2. Funziona perché in **htmx 2** `hx-headers` è ereditato implicitamente da tutti i discendenti del `<body>`.
   In htmx 4 servirebbe `hx-headers:inherited` (§3.2). Un'altra ragione per restare sulla 2.

Con questa riga in `base.html`, ogni `hx-post`/`hx-put`/`hx-delete` della app passa il CSRF senza altro lavoro.
I form normali continuano a usare `{% csrf_token %}` dentro il `<form>` come sempre.

### 4.3 Serve `django-htmx`?

`django-htmx` 1.29.0 aggiunge `django_htmx.middleware.HtmxMiddleware`, che espone `request.htmx` (booleano/oggetto
con gli header `HX-*` parsati). È utile per il pattern «una vista, due risposte» (§5.4). È leggero e onesto —
un middleware e un template tag. **Opzionale ma consigliato**: `if request.htmx:` è molto più leggibile all'orale
di `if request.headers.get("HX-Request"):`, e sono esattamente 3 righe di setup.

---

## 5. `base.html`, i blocchi e i frammenti

Questo è il punto in cui la traccia d'esame e HTMX sembrano confliggere: la traccia impone che **tutte** le pagine
estendano `base.html` con almeno tre blocchi, ma un frammento HTMX deve arrivare al browser **senza** header e footer.

### 5.1 La soluzione buona: template partials nativi di Django 6.0

Django 6.0 (rilasciato il **2025-12-03**) ha assorbito `django-template-partials` nel core.
Da [release notes 6.0](https://docs.djangoproject.com/en/6.1/releases/6.0/) e
[ref/templates](https://docs.djangoproject.com/en/6.1/ref/templates/language/):

```django
{% partialdef nome-partial %}
    {# contenuto riusabile #}
{% endpartialdef %}

{% partial nome-partial %}           {# lo renderizza in loco #}
{% partialdef nome-partial inline %} {# lo definisce E lo renderizza subito #}
```

E — il pezzo che risolve il problema — l'**accesso diretto** con la sintassi `template.html#partial_name`,
utilizzabile da `render()`, `get_template()` e `{% include %}`:

```python
def user_info_partial(request, user_id):
    user = get_object_or_404(User, id=user_id)
    return render(request, "authors.html#user-info", {"user": user})
```

La doc dice esplicitamente: «This approach is particularly useful for AJAX-style requests that update only specific
portions of a page with the rendered template fragment.»

### 5.2 Verifica: il partial eredita `base.html`? **No.**

Non mi sono fidato della doc e ho letto la test suite di Django
(`tests/template_tests/syntax_tests/test_partials.py`, branch `main`). Il test `test_nested_partials` definisce:

```python
"nested_simple": (
    "{% extends 'base.html' %}"
    "{% block content %}"
    "This is my main page."
    "{% partialdef outer inline %}"
    "    It hosts a couple of partials.\n"
    "    {% partialdef inner inline %}"
    "        And an inner one."
    "    {% endpartialdef inner %}"
    "{% endpartialdef outer %}"
    "{% endblock content %}"
),
"use_outer": "{% include 'nested_simple#outer' %}",
```

e asserisce che l'output di `use_outer` è **esattamente**
`["It hosts a couple of partials.", "And an inner one."]` — niente `<html>`, niente `<body>`, niente `base.html`.

**Questa è la risposta definitiva alla domanda del ticket**: un partial definito dentro un template che fa
`{% extends 'base.html' %}` e reso via `template.html#partial` produce **solo** il frammento. Layout e frammento
convivono nello stesso file, e la regola «tutte le pagine estendono `base.html`» resta letteralmente vera —
anzi, si rafforza, perché non c'è nessun template orfano fuori dalla gerarchia.

Altri comportamenti confermati dai test:
- un partial definito dentro un template che estende un altro funziona anche con `{{ block.super }}`;
- `{% include 'file.html#nome' %}` rende solo il partial;
- i nomi duplicati e l'annidamento male chiuso sono errori di sintassi rilevati al caricamento del template.

### 5.3 L'alternativa se si resta su Django 5.2 LTS

I partials nativi esistono **solo da Django 6.0**. Su 5.2 servirebbe:

- `pip install django-template-partials` (stessa sintassi, stesso autore — è l'upstream che è stato assorbito;
  il suo README dice: «Template Partials were added to Django in version 6.0. You should use that in new projects»); oppure
- il pattern **base template intercambiabile** (documentato da django-htmx): il template della pagina fa
  `{% extends base_template %}`, e la vista passa `base_template = "_partial.html"` (un file che contiene solo
  `{% block content %}{% endblock %}`) quando `request.htmx`, altrimenti `"base.html"`; oppure
- **due template separati**: `dashboard.html` che estende `base.html` e include `_grafico.html`, e una vista
  parziale che renderizza direttamente `_grafico.html`. Il più semplice da spiegare, il più prolisso da mantenere.

**Se scegli Django 6.1 (o 6.0), usa i partials nativi.** È la ragione più forte per non stare sulla LTS in questo
progetto: elimina un'intera categoria di duplicazione e permette una risposta pulitissima all'orale sulla domanda
«come fa una pagina a estendere `base.html` e allo stesso tempo servire frammenti?».

### 5.4 Il pattern «una vista, due risposte»

```python
def routine_list(request):
    ctx = {"routines": Routine.objects.select_related("owner")}
    if request.htmx:
        return render(request, "routines/list.html#routine-table", ctx)
    return render(request, "routines/list.html", ctx)
```

Il template `routines/list.html`:

```django
{% extends "base.html" %}
{% block content %}
  <h1>Le tue schede</h1>
  {% partialdef routine-table inline %}
    <div id="routine-table">
      {% for r in routines %}…{% endfor %}
    </div>
  {% endpartialdef %}
{% endblock %}
```

Un file, un contesto, zero duplicazione. Il `{% partialdef ... inline %}` fa sì che la pagina intera continui a
mostrare la tabella nel punto giusto.

---

## 6. Chart.js alimentato da Django

### 6.1 JSON dedicato o dati nel template?

**Endpoint JSON dedicato.** Ragioni concrete per questo progetto:

- La mappa #11 mette al centro le **query ORM avanzate** (`annotate`, `Window`, `Lag`, `Subquery`, percentili).
  Un endpoint `JsonResponse` è il posto naturale dove far vivere quelle query e, all'orale, si può aprire
  l'URL nel browser e mostrare il JSON prodotto dalla query. È una dimostrazione di padronanza molto più diretta
  di un `{{ dati|json_script }}` sepolto in un template.
- Permette l'aggiornamento senza ricaricare la pagina (filtro per periodo, per esercizio, per gruppo muscolare).
- Separa nettamente "pagina" da "dati", che è esattamente la separazione che il prof si aspetta di sentir raccontare.

Se i dati sono pochi e statici per pagina, `{{ data|json_script:"chart-data" }}` (template filter Django) è
accettabile e più semplice; ma appena serve un filtro interattivo, l'endpoint vince.

### 6.2 Come si aggiorna un grafico da HTMX — la sottigliezza

HTMX **swappa HTML**, non JSON. Un `hx-get` che punta a un endpoint `JsonResponse` inserirebbe testo JSON grezzo
nel DOM. Ci sono due pattern corretti, e il secondo è quello giusto qui.

**Pattern A — HTMX carica un frammento che contiene il `<canvas>` e uno `<script>` di init.**
Funziona, ma reinizializza il grafico a ogni swap: va distrutto quello vecchio (`Chart.getChart(canvas)?.destroy()`)
o Chart.js si lamenta del canvas già in uso.

**Pattern B — HTMX gestisce i filtri (HTML), un `fetch()` aggiorna i dati (JSON).** ⭐
Il `<canvas>` resta fisso nel DOM, non viene mai swappato. HTMX serve per la parte HTML (form dei filtri,
tabelle, liste); l'aggiornamento del grafico avviene sui dati.

Dalla [doc Chart.js sugli updates](https://www.chartjs.org/docs/latest/developers/updates.html): si modificano
`chart.data.labels` e `chart.data.datasets[].data` e poi si chiama `chart.update()`; passando `'none'`
(`chart.update('none')`) si salta l'animazione.

```html
<canvas id="volume-chart" data-url="{% url 'analytics:volume-json' %}"></canvas>
<select name="period" hx-get="{% url 'analytics:filters' %}" hx-target="#filters"></select>
```

```js
const el = document.getElementById("volume-chart");
const chart = new Chart(el, { type: "line", data: { labels: [], datasets: [{ label: "Volume", data: [] }] } });

async function refresh(params = "") {
  const res = await fetch(el.dataset.url + params);
  const payload = await res.json();
  chart.data.labels = payload.labels;
  chart.data.datasets[0].data = payload.values;
  chart.update();
}
refresh();
// riaggancia dopo ogni swap htmx che cambia i filtri
document.body.addEventListener("htmx:afterSwap", () => refresh(currentQueryString()));
```

Lato Django:

```python
def volume_json(request):
    qs = (SessionSet.objects
          .filter(session__user=request.user)
          .annotate(...)      # qui vivono Window / Lag / Subquery
          .values("week", "volume"))
    return JsonResponse({
        "labels": [r["week"] for r in qs],
        "values": [r["volume"] for r in qs],
    })
```

`JsonResponse` serializza dict di default; per liste in cima serve `safe=False`.

Chart.js 4.5.1 via CDN (o, meglio, scaricato in `static/vendor/`):
`https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js` (build UMD, quella che espone `Chart` globale
senza moduli).

---

## 7. Raccomandazione operativa

### 7.1 Stack finale

```
Django 6.1.1        (per i template partials nativi)
Tailwind CSS 4.3.3  via pytailwindcss (binario standalone, niente Node)
htmx 2.0.10         file statico pinnato
Chart.js 4.5.1      file statico pinnato
django-htmx 1.29.0  per request.htmx
```

### 7.2 Comandi di setup, in ordine

```bash
# 1. ambiente
python3.13 -m venv .venv
source .venv/bin/activate
pip install "django==6.1.1" django-htmx pytailwindcss

# 2. progetto
django-admin startproject config .
python manage.py startapp training

# 3. Tailwind: binario standalone, niente Node
export TAILWINDCSS_VERSION=v4.3.3
tailwindcss_install

# 4. CSS sorgente
mkdir -p assets/css static/css static/vendor
printf '@import "tailwindcss";\n' > assets/css/input.css

# 5. vendoring di htmx e Chart.js (niente CDN: la demo deve girare offline)
curl -L -o static/vendor/htmx.min.js      https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js
curl -L -o static/vendor/chart.umd.min.js https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js

# 6. build del CSS in watch (terminale 1)
tailwindcss -i assets/css/input.css -o static/css/app.css --watch

# 7. server (terminale 2)
python manage.py migrate && python manage.py runserver
```

Build one-shot per la consegna: `tailwindcss -i assets/css/input.css -o static/css/app.css --minify`.

Comodità: un `Makefile` con `make dev` che lancia i due processi, così all'orale si digita un comando solo.

### 7.3 Struttura di cartelle

```
progetto-django-uni/
├── manage.py
├── requirements.txt
├── Makefile                       # make dev / make css
├── config/                        # settings, urls, wsgi
├── training/                      # app di dominio (models, views, urls)
├── assets/
│   └── css/
│       └── input.css              # @import "tailwindcss";  (sorgente, versionato)
├── static/
│   ├── css/
│   │   └── app.css                # generato da Tailwind — VERSIONATO
│   ├── vendor/
│   │   ├── htmx.min.js
│   │   └── chart.umd.min.js
│   └── js/
│       └── charts.js
├── templates/
│   ├── base.html                  # {% block header %}{% block content %}{% block footer %}
│   ├── partials/                  # frammenti condivisi fra pagine diverse
│   │   └── _routine_card.html
│   └── training/
│       ├── routine_list.html      # extends base.html + {% partialdef %} interni
│       └── dashboard.html
└── data/                          # storico reale di Lorenzo — in .gitignore
```

Perché `assets/` è separato da `static/`: `assets/` è sorgente, `static/` è output. Tenerli distinti evita che
Tailwind si scansioni il proprio output e rende ovvio, guardando il repo, cosa è scritto a mano e cosa è generato.

### 7.4 `settings.py` — le righe che contano

```python
INSTALLED_APPS = [
    ...,
    "django_htmx",
    "training",
]

MIDDLEWARE = [
    ...,
    "django_htmx.middleware.HtmxMiddleware",
]

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    ...
}]

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
```

Nessun setting Tailwind: il CLI standalone vive fuori da Django, e il CSS è un normale file statico.

### 7.5 `base.html` — lo scheletro

```django
{% load static %}
<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Progressive{% endblock %}</title>
  <link rel="stylesheet" href="{% static 'css/app.css' %}">
  <script src="{% static 'vendor/htmx.min.js' %}" defer></script>
  <script src="{% static 'vendor/chart.umd.min.js' %}" defer></script>
</head>
<body class="min-h-screen bg-slate-50 text-slate-900"
      hx-headers='{"x-csrftoken": "{{ csrf_token }}"}'>

  {% block header %}
    <header class="border-b bg-white px-6 py-4">…</header>
  {% endblock %}

  <main class="mx-auto max-w-5xl px-6 py-8">
    {% block content %}{% endblock %}
  </main>

  {% block footer %}
    <footer class="border-t px-6 py-4 text-sm text-slate-500">…</footer>
  {% endblock %}
</body>
</html>
```

Tre blocchi (`header`/`content`/`footer`) come richiede la traccia, più `title` in omaggio.
La riga `hx-headers` copre il CSRF per l'intera applicazione.

### 7.6 `.gitignore` — cosa escludere

```
.venv/
db.sqlite3
data/           # storico reale, fuori dal versionamento (mappa #11)
__pycache__/
```

**Non** escludere `static/css/app.css`: va committato, così il progetto gira dopo un semplice `git clone`.
E attenzione al comportamento di Tailwind v4, che salta i file elencati in `.gitignore` quando cerca le classi:
non mettere mai `templates/` lì dentro.

---

## 8. Trappole da ricordare

1. **htmx.org documenta la 4, npm serve la 2.** Ogni snippet copiato da htmx.org oggi può essere sintassi 4.
   Il segnale d'allarme è `:inherited` sugli attributi. (Fonte: annuncio htmx 4.0.0.)
2. **`hx-headers` sul `<body>` funziona solo con htmx 2.** Con htmx 4 il CSRF si romperebbe silenziosamente
   su tutte le POST.
3. **Tailwind v4 non ha più `tailwind.config.js` auto-rilevato.** Ogni guida che apre con
   `npx tailwindcss init -p` è di era v3 e va scartata in blocco.
4. **`@tailwind base/components/utilities` è morto**, sostituito da `@import "tailwindcss";`.
5. **I template partials richiedono Django ≥ 6.0.** Su 5.2 LTS serve il pacchetto `django-template-partials`.
6. **`{{ csrf_token }}` vs `{% csrf_token %}`**: dentro un attributo HTML serve la variabile, non il tag.
7. **`django-tailwind` di default usa npm**, non il binario: `TAILWIND_USE_STANDALONE_BINARY` è `False`.
   Chi lo installa aspettandosi «niente Node» si ritrova `node_modules`.
8. **Chart.js e HTMX non vanno mescolati sullo stesso nodo**: se HTMX swappa il `<canvas>`, il grafico va
   distrutto e ricreato. Meglio tenere il canvas fuori dai target di swap.
9. **Tailwind v4 richiede browser moderni** (Safari 16.4+, Chrome 111+, Firefox 128+). Irrilevante per una demo
   in locale, ma da sapere se qualcuno chiede.

---

## Fonti

Tutte consultate il 2026-09-07.

**Django**
- Release notes 6.0 — https://docs.djangoproject.com/en/6.1/releases/6.0/
- Template language, partials e accesso diretto — https://docs.djangoproject.com/en/6.1/ref/templates/language/
- Built-in tags `partialdef`/`partial` — https://docs.djangoproject.com/en/6.1/ref/templates/builtins/
- How to use CSRF protection (AJAX, `X-CSRFToken`, `ensure_csrf_cookie`) — https://docs.djangoproject.com/en/6.1/howto/csrf/
- CSRF reference — https://docs.djangoproject.com/en/6.1/ref/csrf/
- Download / versioni supportate — https://www.djangoproject.com/download/
- Test suite dei partials (verifica del comportamento con `{% extends %}`) —
  https://github.com/django/django/blob/main/tests/template_tests/syntax_tests/test_partials.py

**Tailwind CSS**
- CLI installation (incl. binario standalone) — https://tailwindcss.com/docs/installation/tailwind-cli
- Upgrade guide v3 → v4 — https://tailwindcss.com/docs/upgrade-guide
- Detecting classes in source files (`@source`, `.gitignore`) — https://tailwindcss.com/docs/detecting-classes-in-source-files
- Play CDN — https://tailwindcss.com/docs/installation/play-cdn
- Release v4.3.3 e asset dei binari — https://github.com/tailwindlabs/tailwindcss/releases/latest

**htmx**
- Docs 2.x (CDN, `hx-headers`, CSRF) — https://htmx.org/docs/
- Release htmx 4.0.0 e annuncio — https://github.com/bigskysoftware/htmx/releases/tag/v4.0.0
- What's new in htmx 4 (breaking changes) —
  https://github.com/bigskysoftware/htmx/blob/v4.0.0/www/src/content/docs/whats-new-in-htmx-4.md
- dist-tags npm — https://registry.npmjs.org/htmx.org

**Pacchetti Python**
- django-tailwind, installazione — https://django-tailwind.readthedocs.io/en/latest/installation.html
- django-tailwind, settings — https://django-tailwind.readthedocs.io/en/latest/settings.html
- django-tailwind, standalone vs npm — https://django-tailwind.readthedocs.io/en/latest/standalone-vs-npm.html
- pytailwindcss — https://pypi.org/project/pytailwindcss/
- django-htmx, installazione — https://django-htmx.readthedocs.io/en/latest/installation.html
- django-htmx, tips (CSRF e partial) — https://django-htmx.readthedocs.io/en/latest/tips.html
- django-template-partials — https://github.com/carltongibson/django-template-partials

**Chart.js**
- Updating charts — https://www.chartjs.org/docs/latest/developers/updates.html
- Installation — https://www.chartjs.org/docs/latest/getting-started/installation.html
