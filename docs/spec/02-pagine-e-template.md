# 02 — Pagine, URL, template

Fonte: [#19](https://github.com/cavallinilorenzo/progetto-django-uni/issues/19) (guscio e sitemap), [#22](https://github.com/cavallinilorenzo/progetto-django-uni/issues/22) (convenzioni del corso), [#37](https://github.com/cavallinilorenzo/progetto-django-uni/issues/37) (heatmap), [#33](https://github.com/cavallinilorenzo/progetto-django-uni/issues/33) (classifiche).

**Il prototipo è già nel repo** e non va reinventato: `prototypes/t19-pagine/`, con i tre gusci candidati, la sitemap navigabile in `/mappa/` e la heatmap in `/heatmap/`. Si avvia con una riga:

```
uv run --with 'django>=6.0.3' python prototypes/t19-pagine/manage.py runserver
```

Vale come sorgente primaria per il markup: `base_a.html` e `dashboard_a.html` sono da portare, non da riscrivere.

## `base.html` — sei blocchi

La traccia impone `base.html` con **almeno 3 blocchi** — header, content, footer — e che **tutte** le pagine lo estendano. Ne facciamo sei:

```
{% block title %}        {% block extra_head %}
{% block header %}       {% block content %}
{% block footer %}       {% block scripts %}
```

I tre imposti sono `header`, `content`, `footer`, e sono blocchi **pieni**, non vuoti: sovrascriverli è l'eccezione (lo fanno le pagine di autenticazione). Gli altri tre sono comodità.

Questo è **più conforme alla traccia del `base.html` dell'esempio del prof**, che ha solo `title`/`extra_style`/`content` ([#21](https://github.com/cavallinilorenzo/progetto-django-uni/issues/21)). È un punto da fare all'orale, non un caso.

**Regola non negoziabile: nessun template senza `{% extends "base.html" %}`.** Vale anche per le pagine di errore e per i frammenti. Un template orfano è la via più semplice per fallire un requisito minimo, e va verificato con un test (vedi `07-test.md` nell'indice).

## Il guscio: variante A, «Scoreboard»

Progressive eredita l'identità **Pulse** di Overload:

- canvas near-black `ink` **#0A0B0D**
- `volt` **#C9FF3D** come **unico** colore acceso
- tipografia compressa e maiuscola per le etichette
- il chip delta `▲ +2.5` come elemento firma

Sopra **Bootstrap 5.3.0 da CDN**, con **~100 righe di CSS custom**: quasi tutte token di colore più tre classi di utilità (`.eyebrow`, `.hero-num`, `.delta`). All'orale si difende in una frase — è la palette di un'app che esiste già.

La gerarchia della dashboard è **il numero**: la riga di cifre hero apre la pagina, il resto la spiega. Lo stallo compare come avviso sul rail volt, non come pannello: il coach avvisa, non è il prodotto.

**Niente JavaScript applicativo.** L'unica eccezione è Chart.js, alimentato da `json_script` (vedi `04-analisi.md`).

## La regola di navigazione

L'header porta **sei sezioni**. Ogni altra pagina si raggiunge **da dentro la sezione a cui appartiene per dominio, mai da un link orfano.**

> Cinque fino a [#99](https://github.com/cavallinilorenzo/progetto-django-uni/issues/99), che ha aggiunto **Analisi**. Non è un ripensamento sulla regola: è la sanatoria di una contraddizione fra questo documento e `04-analisi.md`, che assegnava A1 e A2 a una «Analisi muscolare» a cui la sitemap qui sotto non dava alcun URL. La pagina era nominata e non esisteva. L'alternativa — infilare A1 e A2 in dashboard — sovraccaricava la prima pagina e lasciava la heatmap unico contenuto di una pagina che non c'era.

Questa regola nasce da un'obiezione precisa in #19: cinque voci nell'header contro le undici che una sidebar avrebbe mostrato — dove finiscono le altre? Non spariscono, **si annidano**:

| Pagina | Dove sta |
|---|---|
| Schede della community | dentro **Schede** |
| Stalli e progressione | dentro la pagina del **singolo esercizio**, che *è* la sua storia |
| Importa storico | menu utente, con Profilo ed Esci |

## Sitemap e URL

`app_name = "training"`, nomi di rotta **col trattino** come nell'esempio del corso. Tutte **class-based view**.

### 1. Dashboard — `/`

`name="dashboard"`. Le sei analisi come widget, ognuna un varco verso la pagina che la approfondisce. Ospita la **heatmap muscolare** (unica pagina in cui vive) e **un solo consiglio** del coach, quello a priorità più alta.

### 2. Schede — `/schede/`

CRUD **completo** su `Routine`, ed è uno dei due che pagano il requisito.

| URL | Nome | View |
|---|---|---|
| `/schede/` | `routine-list` | `ListView` — le mie |
| `/schede/nuova/` | `routine-create` | `CreateView` |
| `/schede/<pk>/` | `routine-detail` | `DetailView` |
| `/schede/<pk>/modifica/` | `routine-update` | `UpdateView` |
| `/schede/<pk>/elimina/` | `routine-delete` | `DeleteView` |
| `/schede/<pk>/esercizi/` | `routine-exercises` | Gestione di `RoutineExercise` via formset |
| `/schede/pubbliche/` | `routine-public-list` | La community |
| `/schede/pubbliche/<pk>/` | `routine-public-detail` | Con voto e commento |

Il voto è il **terzo CRUD**, su `Vote`: creare, modificare, cancellare il proprio voto da `routine-public-detail`.

### 3. Storico — `/allenamenti/`

CRUD **completo** su `Workout` più le sue serie.

| URL | Nome | Note |
|---|---|---|
| `/allenamenti/` | `workout-list` | |
| `/allenamenti/nuovo/` | `workout-create` | `?scheda=<pk>` **precompila** dalla scheda |
| `/allenamenti/<pk>/` | `workout-detail` | |
| `/allenamenti/<pk>/modifica/` | `workout-update` | |
| `/allenamenti/<pk>/elimina/` | `workout-delete` | |
| `/allenamenti/<pk>/serie/` | `workoutset-manage` | Formset sulle serie |

**«Avvia allenamento da scheda»** è un bottone sulla scheda: crea un `Workout` e lo precompila con le serie pianificate e il carico dell'ultima volta; l'utente corregge i numeri veri e deseleziona ciò che ha saltato. Una pagina, un `POST`, zero JavaScript — è il motivo per cui `is_completed` esiste, col significato «eseguita» contro «saltata».

### 3-bis. Analisi — `/analisi/`

| URL | Nome | View |
|---|---|---|
| `/analisi/` | `analysis` | `TemplateView` — A1 (volume nel tempo) e A2 (distribuzione sui sei gruppi) |

La divisione del lavoro con la dashboard, che è la ragione per cui sono due pagine e non una: **la heatmap in dashboard è il richiamo visivo, `/analisi/` è dove si va a capire perché.**

Una rotta sola e nessuna sotto. Le altre analisi hanno già la loro sezione — la progressione del carico sta dentro la pagina dell'esercizio, che *è* la sua storia — e la heatmap vive solo in dashboard.

Finestra di **12 settimane**, non 12 mesi: la finestra lunga nasconde il buco che la pagina si dà la pena di riempire, e una settimana saltata dentro un punto mensile è un punto un po' più basso, non un avvallamento. Il toggle settimana/mese resta da specificare.

Qui entrano i **primi due grafici** del progetto, e con essi la convenzione per il terzo: Chart.js sta nel blocco `scripts` della **pagina** (`training/_grafici_js.html`), mai in `base.html`, o la libreria arriverebbe addosso anche a chi apre il form di una scheda. I dati passano da `training/_grafico.html`, che è un `json_script` più un canvas; il payload è dichiarativo e porta il tipo di figura, quindi `static/js/grafici.js` non sa cosa sta disegnando e il terzo grafico non lo tocca.

### 4. Esercizi — `/esercizi/`

| URL | Nome | Note |
|---|---|---|
| `/esercizi/` | `exercise-list` | Sola lettura, filtrabile per gruppo/muscolo/attrezzo |
| `/esercizi/<slug>/` | `exercise-detail` | **La pagina più densa del progetto** |

`exercise-detail` è la pagina della storia di un esercizio: progressione del massimale (A3), PR (A4), percentile (A5), **stato di stallo**, consiglio di carico, e la classifica di forza ridotta alle prime 5 righe.

Il filtro della lista paga il requisito «select/view **grouped** objects».

### 5. Classifiche — `/classifiche/`

| URL | Nome |
|---|---|
| `/classifiche/forza/` | `ranking-strength` |
| `/classifiche/schede/` | `ranking-social` |

Pagina **propria e nel menu**, non sepolta: la traccia elenca «display results or rankings» fra i minimi, e un requisito che ha una voce nel menu si mostra all'orale in due secondi. `Paginator`, 25 per pagina, riga dell'utente corrente evidenziata.

### 6. Utente

`/profilo/` (`profile`, dove si dichiara `body_mass_kg`), i tre URL dell'import (vedi `03-import-ed-export.md`), più login/logout/registrazione da `django.contrib.auth` con i template in `templates/registration/`, come nell'esempio del corso.

## Convenzioni del corso, da rispettare

Dal rilievo su slide e progetto d'esempio ([#22](https://github.com/cavallinilorenzo/progetto-django-uni/issues/22)):

- **Class-based view** ovunque
- `app_name` + nomi rotta col trattino
- **`UserPassesTestMixin` con `test_func()`** per la proprietà dell'oggetto: una scheda o un allenamento si modificano solo se sono tuoi. È il pattern che il prof ha insegnato, e va usato quello
- `LoginRequiredMixin` su tutto ciò che non è pubblico
- Template in **sottocartella per modello**: `templates/training/routine_list.html`, ecc.
- `admin.register()` con `ModelAdmin` custom su 2–3 modelli

## La heatmap muscolare

Vive **solo in dashboard**. Figura anatomica sui **23 muscoli**, non sui 6 gruppi: i sei totali stanno in una banda stretta e il corpo esce verde uniforme, mentre le barre separano quegli stessi valori meglio.

Sta in piedi **senza JavaScript**: `_corpo.svg` è un partial statico con `class="g-<gruppo> m-<muscolo>"` su ogni path, e la view emette un `<style>` con un `fill` per classe. Stesso principio di `json_script`.

Sotto, la lista dei muscoli **annidata sotto i sei gruppi** con `<details>`/`<summary>` — HTML nativo, sei righe che si aprono una per volta. **Due scale di colore tenute separate**: il gruppo sulla scala dei gruppi, i muscoli su quella dei muscoli, perché «quale gruppo peso di più» e «dentro questo gruppo cosa trascuro» sono domande diverse. Scala normalizzata sul **massimo**, non sul totale.

**La finestra e la misura**, decise in [#101](https://github.com/cavallinilorenzo/progetto-django-uni/issues/101) portando il prototipo in dashboard:

- **Quattro settimane**, cioè i 28 giorni dello squilibrio di `04-analisi.md`, ma contate sulla **griglia dei lunedì** di `/analisi/`: «settimana» deve voler dire una cosa sola in tutto il progetto, o le stesse serie cadrebbero in settimane diverse su due pagine e nessuna delle due sarebbe sbagliata.
- **Serie, non chili.** Fra regioni del corpo i kg non si confrontano — una serie di squat ne muove dieci volte una di alzate laterali — quindi una mappa normalizzata sul volume avrebbe le gambe accese e le spalle spente per sempre, e direbbe dell'anatomia invece che dell'allenamento. I kg per gruppo stanno su `/analisi/` (A2): sono due grandezze diverse, con due nomi diversi, e ogni pagina dichiara la propria.
- **Un corpo tutto spento non si disegna.** La scala è normalizzata sul massimo: senza serie nella finestra il massimo è finto, e un corpo grigio si legge come «non ti alleni» mentre la verità è «non lo so». Al suo posto va detto perché, distinguendo chi non ha mai registrato niente da chi ha uno storico e un mese fermo.

**Da dichiarare, due volte.**

1. **Limite noto:** la figura vede **solo il muscolo primario**, perché il catalogo ne tagga uno solo per esercizio: uno spento è un muscolo non allenato *direttamente*, non per forza trascurato. La dichiarazione sta in pagina e non è condizionata, perché il limite è strutturale.
   > I «4 su 23 sempre spenti» erano una misura del prototipo #37 sui suoi dati finti. Sul catalogo vero tutti e 23 i muscoli hanno almeno un esercizio che li ha come primari, e quei quattro erano zeri dell'utente della demo, non del modello (#101).
2. **Provenienza:** `_corpo.svg` è versionato ma **non è lavoro nostro**. `prototypes/t37-heatmap/build_body_svg.mjs` non ridisegna niente: copia i path anatomici di Overload identici e ci aggiunge solo le classi. Questo va scritto nel README **e detto all'orale** — è la conclusione di [#40](https://github.com/cavallinilorenzo/progetto-django-uni/issues/40), e tenerlo in `.gitignore` era peggio, perché il progetto non girava più da un clone pulito.
