# 04 — Il motore analitico

Fonte: [#16](https://github.com/cavallinilorenzo/progetto-django-uni/issues/16) (catalogo delle analisi), [#33](https://github.com/cavallinilorenzo/progetto-django-uni/issues/33) (classifiche).

**Sei analisi su nove candidate**, tutte calcolate **nel database**, su quattro pagine. Il criterio di ammissione ha due assi e il primo è **obbligatorio**:

1. **Alimenta una decisione** — l'utente, letta la schermata, fa qualcosa di diverso il prossimo allenamento.
2. **Mostra ORM che il corso non ha insegnato.**

L'asse 2 da solo non basta mai: una vetrina che non serve a niente, all'orale, diventa «e questo perché c'è?».

## Le tre definizioni che tengono insieme tutto

Vanno scritte **una volta sola**, nel custom QuerySet, e riusate. Come costanti sparse sarebbero cinque cose da spiegare all'orale; come QuerySet sono una sola.

### 1. Carico effettivo

`Sum(F('reps') * F('weight'))` dà **zero** per ogni trazione e ogni piegamento — e #13 ha misurato che sul corpo libero i pesi nulli sono **legittimi**, non sporcizia. Nella distribuzione per gruppo muscolare la schiena sparirebbe.

> carico effettivo = `weight` + `body_mass_kg` se l'attrezzo è corpo libero, altrimenti `weight`

Un `Case`/`When`, che gestisce gratis anche le trazioni zavorrate. Vedi [ADR-0006](../adr/0006-carico-effettivo-include-il-peso-corporeo.md).

**Corollario:** `weight` è sempre già comprensivo del bilanciere. `Equipment.default_bar_weight_kg` serve solo a precompilare il form e **non entra in nessuna analisi**.

### 2. Il filtro universale

Ogni analisi conta le sole serie con **`set_type='working'` E `is_completed=True`**. I due filtri vanno sempre insieme.

#13 ha misurato **19% di serie non completate**: farle entrare nel volume significa contare allenamento che non è avvenuto. Le serie saltate non spariscono — diventano il dato dell'**aderenza al piano**, che è materia del coach.

### 3. Epley, con il tetto a 12 ripetizioni

`carico effettivo × (1 + reps/30)`. Epley e non Brzycki perché è una **moltiplicazione**, quindi si legge in una riga di `F()`, mentre Brzycki ha un denominatore che esplode vicino alle 37 ripetizioni.

Sopra le **12 ripetizioni** la stima gonfia, quindi quelle serie **non concorrono al massimale ma restano nel volume**. È la stessa regola di [#17](https://github.com/cavallinilorenzo/progetto-django-uni/issues/17): le due parti del progetto devono usare lo stesso numero.

## Il custom QuerySet

`training/querysets.py`, su `WorkoutSet`, concatenabile:

```python
WorkoutSet.objects.working().with_estimated_1rm()
```

Metodi: `working()`, `with_effective_load()`, `with_volume()`, `with_estimated_1rm()`.

Convive con `analytics/plateau.py` senza sovrapporsi: qui stanno le **espressioni**, lì il **servizio** che le consuma.

```python
# training/querysets.py — i due blocchi condivisi
EFFECTIVE_LOAD = Case(
    When(exercise__equipment__code="bodyweight",
         then=F("weight") + F("workout__user__body_mass_kg")),
    default=F("weight"),
    output_field=FloatField(),
)
EPLEY = EFFECTIVE_LOAD * (Value(1.0) + F("reps") / Value(30.0))
```

> **Attenzione:** #16 scriveva `equipment__code="corpo_libero"`. Il codice vero nel catalogo è **`"bodyweight"`** (`data/catalog/equipment.csv`). La query nel ticket è sbagliata; questa è corretta.

## Il catalogo delle sei

| # | Analisi | Query | Pagina |
|---|---|---|---|
| A1 | **Volume nel tempo** | `Sum` del carico effettivo × ripetizioni, `TruncWeek`/`TruncMonth` | Dashboard (sintesi) + Analisi muscolare |
| A2 | **Distribuzione sui 6 gruppi** | stessa `Sum`, raggruppata per gruppo | Analisi muscolare |
| A3 | **Progressione del carico** | `Window(Max)` cumulativo + `Lag` per il delta | Dettaglio esercizio |
| A4 | **PR** | `Subquery` + `OuterRef` | Dettaglio esercizio |
| A5 | **Percentile di forza relativa** | `Window(PercentRank)` | Dettaglio esercizio |
| W1 | **Costanza** | `Count` allenamenti per periodo | Dashboard (widget) |

W1 è un **widget**, non una pagina: passa l'asse 1 ma non l'asse 2, quindi non guadagna spazio proprio.

### Le query

```python
# A1 — volume nel tempo
(WorkoutSet.objects.working()
    .filter(workout__user=user, workout__started_at__gte=since)
    .annotate(period=TruncWeek("workout__started_at"))     # o TruncMonth
    .values("period")
    .annotate(volume=Sum(EFFECTIVE_LOAD * F("reps")))
    .order_by("period"))

# A2 — distribuzione sui 6 gruppi (stessa finestra temporale di A1)
(... .values("exercise__primary_muscle__group__label_it")
     .annotate(volume=Sum(EFFECTIVE_LOAD * F("reps")))
     .order_by("-volume"))

# A3 — progressione: due passaggi, aggregato poi finestra
per_workout = (WorkoutSet.objects.working()
    .filter(exercise=ex, workout__user=user, reps__lte=12)
    .values("workout_id", "workout__started_at")
    .annotate(best_1rm=Max(EPLEY)))
progression = per_workout.annotate(
    running_max=Window(Max("best_1rm"), order_by="workout__started_at",
                       frame=RowRange(start=None, end=0)),
    previous=Window(Lag("best_1rm"), order_by="workout__started_at"),
)

# A4 — PR per esercizio
best = (WorkoutSet.objects.working()
    .filter(exercise=OuterRef("pk"), workout__user=user, reps__lte=12)
    .annotate(e=EPLEY).order_by("-e").values("e")[:1])
Exercise.objects.annotate(pr=Subquery(best, output_field=FloatField()))

# A5 — percentile: una riga per utente, poi la finestra
(WorkoutSet.objects.working()
    .filter(exercise=ex, reps__lte=12)
    .exclude(workout__user__body_mass_kg__isnull=True)     # da ADR-0008, vedi sotto
    .values("workout__user_id", "workout__user__body_mass_kg")
    .annotate(best=Max(EPLEY))
    .annotate(relative=F("best") / F("workout__user__body_mass_kg"),
              output_field=FloatField())
    .annotate(pct=Window(PercentRank(), order_by=F("relative").asc())))
```

**A3 è l'unica da prototipare per prima**: impila una `Window` sopra un aggregato, che Django supporta ma con vincoli su cosa si può poi filtrare. Se non regge, il ripiego è una `Subquery` correlata — **non** SQL grezzo. Nessuna delle altre cinque ha incognite.

> L'`exclude` su `body_mass_kg` in A5 **non era nel ticket #16**: è arrivato da #33 (terza condizione di ammissione) e va allineato anche qui, o il percentile divide per null.

## SQLite: verificato, non supposto

Girato su SQLite 3.45.3, quella che Python ha in casa.

- **Funzionano:** `LAG`, `MAX ... OVER`, `PERCENT_RANK`, `NTILE`, `RANK`/`DENSE_RANK`, `ROW_NUMBER`, la clausola `FILTER` (cioè `Sum(..., filter=Q(...))`), `julianday`, `strftime`
- **Non esistono:** `stddev`, `variance`, `percentile_cont`, `median`

Due conseguenze operative:

1. Il percentile si calcola con **`PercentRank` su una riga per utente**, mai con un aggregato di percentile — l'aggregato non c'è.
2. La **pendenza di finestra** che #17 usa si esprime con i soli `Sum`/`Count`: `(n·Σxy − Σx·Σy) / (n·Σx² − (Σx)²)`, che è tutta ORM e resta nel database.

## Il percentile tace quando non sa

Popolazione = **tutti gli utenti del DB**, reali e sintetici: un utente reale in più non sposta niente, e la regola resta una sola.

Ma sotto **`MIN_USERS_FOR_COMPARISON = 20`** utenti su quell'esercizio il percentile **non si mostra**: si mostra il motivo. «Sei nel 67° percentile» su tre persone è formalmente corretto e informativamente falso.

È anche una riga che all'orale gioca a favore, per lo stesso motivo per cui lo stallo mostra «dati insufficienti» come avanzamento e non come errore.

## Le due classifiche

Nessuna delle due ordina per volume, e nessuna inventa un numero quando i dati non bastano.

### Classifica di forza — una per esercizio

Ordinata per **forza relativa**, **di sempre**, senza finestra temporale: è una classifica di **record**, non di attività. Chi non si allena da un anno resta in graduatoria; a dire chi si allena c'è W1.

Nessuna finestra anche per una ragione pratica: qualsiasi finestra più corta di 12 settimane **espellerebbe Lorenzo dalla propria demo** (storico reale = 26 giorni).

**Tre condizioni di ammissione, non una:**

1. **≥ 20 utenti** sull'esercizio — la **stessa costante** che fa tacere il percentile, non una seconda
2. **≥ 2 allenamenti distinti** dell'utente — non due serie: due serie nello stesso giorno sono lo stesso dato
3. **Peso corporeo dichiarato** — senza, l'utente non compare, con l'invito a compilare il profilo

```python
MIN_USERS_FOR_COMPARISON = 20
MIN_WORKOUTS_FOR_RANKING = 2

best_at = Subquery(                     # data del massimale, per il pari merito
    WorkoutSet.objects.working()
        .filter(exercise=exercise, reps__lte=12,
                workout__user_id=OuterRef("workout__user_id"))
        .order_by(EPLEY.desc(), "workout__started_at")
        .values("workout__started_at")[:1]
)

(WorkoutSet.objects.working()
    .filter(exercise=exercise, reps__lte=12)
    .exclude(workout__user__body_mass_kg__isnull=True)
    .values("workout__user_id", "workout__user__username",
            "workout__user__body_mass_kg")
    .annotate(best=Max(EPLEY),
              workouts=Count("workout_id", distinct=True),
              best_at=best_at)
    .filter(workouts__gte=MIN_WORKOUTS_FOR_RANKING)
    .annotate(relative=F("best") / F("workout__user__body_mass_kg"),
              output_field=FloatField())
    .annotate(position=Window(Rank(), order_by=F("relative").desc()))
    .order_by("-relative", "best_at", "workout__user_id"))
```

`best_at` è l'unico pezzo con un'incognita. **Ripiego se non regge:** pari merito rotto su `Min("workout__started_at")` — chi pratica quell'esercizio da più tempo — che è un aggregato nella stessa passata e non cambia nessuna altra regola.

### Classifica sociale — media bayesiana

Ordina le **schede pubbliche**, non gli utenti: è questo a renderla di natura diversa dalla prima, ed è la ragione per cui la traccia si considera soddisfatta due volte e in due modi.

`Avg('votes__score')` nudo mette una scheda con un solo 5 sopra una con cinquanta voti a 4.8. Anche la sola soglia minima è scartata: è arbitraria, e una scheda con esattamente tre cinque resta comunque in cima.

```
punteggio = (C · m + Σ voti) / (C + n)      con C = 3
```

`m` = media di **tutti** i `Vote.score` del database (un solo `aggregate`), **non** media delle medie.

Non è complicazione gratuita: è **una riga di ORM in più che elimina la soglia arbitraria invece di aggiungerla**. Media grezza e numero di voti restano in colonna, perché il punteggio che ordina dev'essere ispezionabile.

```python
C = 3
m = Vote.objects.aggregate(m=Avg("score"))["m"] or 0

votable = (RoutineExercise.objects.values("routine")
              .annotate(c=Count("*")).filter(c__gte=MIN_EXERCISES_FOR_RANKING)
              .values("routine"))                     # anti-civetta, >= 3 esercizi

(Routine.objects.filter(is_public=True, pk__in=votable)
    .annotate(n_votes=Count("votes"), sum_votes=Sum("votes__score"),
              avg_votes=Avg("votes__score"))
    .filter(n_votes__gte=1)
    .annotate(social_score=(Value(C) * Value(m) + F("sum_votes"))
                           / (Value(C) + F("n_votes")),
              output_field=FloatField())
    .annotate(position=Window(Rank(), order_by=F("social_score").desc()))
    .order_by("-social_score", "-n_votes", "pk"))
```

### Due trappole silenziose, entrambe trovate scrivendo la query

Vanno lette **prima** di scrivere il codice, perché nessuna delle due segnala errore.

1. **Il conteggio degli esercizi non può stare nello stesso `annotate` dei voti.** Due join a molti nella stessa query moltiplicano le righe: `Count(distinct=True)` salverebbe i conteggi, ma `Sum("votes__score")` verrebbe **moltiplicato per il numero di esercizi** e il punteggio sarebbe sbagliato **senza che niente lo segnali**. Perciò il filtro anti-civetta passa da un `pk__in` su una sottoquery separata.
2. **`sum_votes` e `n_votes` sono interi: senza `output_field=FloatField()` la divisione tronca.** Vale anche per `relative` nella classifica di forza.

### Pari merito

**`Rank()`, non `RowNumber()`**: due primi a pari merito sono entrambi «1°» e il successivo è «3°». È il significato letterale di pari merito e costa zero.

I pari merito sulla forza sono **realistici, non teorici**: 100 kg × 5 a 80 kg di peso corporeo dà lo stesso valore per due utenti, e i dati sintetici usano numeri tondi. L'ordine *dentro* il pari merito è comunque deterministico, o la pagina si riordina a ogni ricarica: forza → `-relative`, `best_at`, `user_id`; sociale → `-social_score`, `-n_votes`, `pk`.

## Il tempo

**Settimana e mese**, con toggle **solo su A1 e A2**. La progressione del carico non è aggregata per periodo — è una serie di allenamenti, uno per punto — quindi lì il toggle non ha senso. Default: **12 settimane** o **12 mesi**.

**I buchi vanno riempiti nella vista.** `TruncWeek` restituisce solo i periodi in cui esiste almeno una serie: una settimana saltata non compare, e il grafico disegna due punti adiacenti che in realtà distano un mese. Con 15 sessioni in 26 giorni i buchi ci sono davvero.

Gli zeri li aggiunge **Python dopo la query** — è presentazione, non calcolo: il database continua a fare l'aggregazione. È anche la struttura di cui W1 ha bisogno per contare i giorni saltati.

## I grafici

**Tre**: volume nel tempo, distribuzione sui gruppi, progressione del carico. Percentile e PR restano **numeri**.

I dati arrivano a Chart.js con **`{{ data|json_script:"..." }}`**, mai da un endpoint JSON. Senza HTMX gli endpoint sono costo puro — una seconda superficie di viste da scrivere, testare e proteggere — e reintrodurrebbero `fetch`, cioè proprio il JavaScript applicativo che #21 ha escluso. Con `json_script` la vista che già rende la pagina mette i dati nel contesto e non nasce nessuna vista in più.

## Cosa è stato tagliato, e perché

- **Densità di allenamento** — dipendeva da `rest_seconds_used`, che #14 ha eliminato. Restava `ended_at − started_at`, ma #13 ha misurato 2 sessioni su 15 con durate assurde: misurerebbe la qualità del dato, non l'allenamento, e **proprio nella demo**
- **Squilibri push/pull** — richiede una classificazione del movimento che il modello non ha: un campo da compilare a mano su tutte e 100 le voci, per un'informazione che A2 già dà quasi tutta
- **Serie efficaci vs riscaldamento** — non è un'analisi, è il filtro `set_type='working'` che sta **dentro** ogni altra query
- **1RM stimato come analisi a sé** — collassa in A4: con Epley, il PR *è* il massimale stimato più alto mai raggiunto. Tenerli separati sono due grafici dello stesso numero
- **Classifica di forza generale** («total» sui tre fondamentali) — vedi `00-indice.md`, sezione fuori scope: #18 ha **misurato** che i tre fondamentali insieme compaiono in soli 55 storici su 100
