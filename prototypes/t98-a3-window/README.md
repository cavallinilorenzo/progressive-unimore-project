# Prototipo #98 — A3, una `Window` sopra un aggregato

**Codice usa e getta.** Non entra in `main` come codice applicativo: quello che
resta è la forma della query, che il ticket della pagina di dettaglio copia.

Girato su Django **6.1.1**, SQLite **3.45.3**, il database seedato
(296.724 serie, 100 utenti). Utente della demo: **`cavallinilorenzo`
(Lorenzo Cavallini)**, 146 allenamenti sulla panca piana — che è anche il caso
peggiore dell'intero database.

## L'esito in una riga

**La query di `docs/spec/04-analisi.md` non gira**, e non gira per una ragione
più netta di quella prevista: non è un vincolo su cosa si può filtrare dopo, è
un rifiuto in **costruzione**. Il ripiego che vince **non è** la `Subquery`
correlata pura, che pure funziona: è la forma **ibrida**, che tiene tutte e due
le `Window` e sostituisce solo l'aggregato.

## 1. Cosa rifiuta Django, esattamente

```
FieldError: Cannot compute Max('best_1rm'): 'best_1rm' is an aggregate
```

`Window(Max("best_1rm"))` dove `best_1rm` è a sua volta `Max(EPLEY)`.
L'errore arriva da `django/db/models/aggregates.py` durante
`resolve_expression`, cioè **prima di toccare il database**: non è SQLite a non
saper fare, e non è il vincolo noto sul filtro dopo una finestra. Django non
lascia impilare un aggregato dentro un aggregato, e `Window(Max(...))` conta
come aggregato dentro aggregato.

Conseguenza operativa: nel `probe.py` **tutte** le prove «cosa regge dopo la
finestra» falliscono con lo stesso identico errore, perché nessuna arriva a
costruirsi. Non dicono niente sulle finestre.

Il confine è preciso, e vale la pena saperlo per l'orale:

| forma | esito |
|---|---|
| `Window(Max("best_1rm"))` sopra `Max(EPLEY)` | **rifiutata** — aggregato su aggregato |
| `Window(Lag("best_1rm"))` sopra `Max(EPLEY)` | **accettata** — `Lag` non è un aggregato |
| `Window(Max(EPLEY))` senza il passaggio aggregato | accettata, ma è una riga per **serie**, non per allenamento: risponde a un'altra domanda |

Cioè: metà della query della spec funzionava già. È solo il massimo cumulativo
a non passare.

## 2. La forma che vince (`ibrida.py`)

L'aggregato diventa una **`Subquery` correlata** — che agli occhi della query
esterna è una colonna, non un aggregato — e sopra ci stanno **entrambe** le
finestre. Le righe di base diventano gli **allenamenti**, non le serie.

```python
def progressione(user, exercise):
    massimale_sessione = (
        WorkoutSet.objects.working()
        .filter(workout=OuterRef("pk"), exercise=exercise,
                reps__lte=MAX_REPS_FOR_1RM)
        .values("workout").annotate(m=Max(EPLEY)).values("m"))
    sessioni_con_esercizio = (
        WorkoutSet.objects.working()
        .filter(exercise=exercise, reps__lte=MAX_REPS_FOR_1RM)
        .values("workout_id"))
    return (Workout.objects.filter(user=user, pk__in=sessioni_con_esercizio)
            .annotate(best_1rm=Subquery(massimale_sessione,
                                        output_field=FloatField()))
            .annotate(
                running_max=Window(Max("best_1rm"), order_by="started_at",
                                   frame=RowRange(start=None, end=0)),
                previous=Window(Lag("best_1rm"), order_by="started_at"))
            .values("id", "started_at", "best_1rm", "running_max", "previous")
            .order_by("started_at"))
```

Verificata, non supposta: 146 righe contro 146 allenamenti distinti attesi,
`running_max` monotono crescente su tutta la serie, `previous[i] ==
best_1rm[i-1]` su tutte le righe, **una sola query SQL**, zero righe (non un
errore) su un esercizio mai allenato.

### La trappola che ha quasi vinto, e non segnalava niente

La prima versione partiva da `Workout.objects.filter(user=u, sets__exercise=ex)
.distinct()`. Gira, non solleva niente, e restituisce **281 righe invece di
146**: il join a `sets` moltiplica l'allenamento per il numero di serie, e le
finestre vedono le righe duplicate **prima** che il `DISTINCT` le collassi —
per giunta il `DISTINCT` poi non collassa più niente, perché `previous` è
diverso su ogni duplicato. È esattamente il guasto della regola 3 della mappa:
un'analisi sbagliata rende comunque una pagina.

Il rimedio è `pk__in=<subquery>` invece del join: nessuna moltiplicazione, e
lo stesso filtro `working()` + `reps__lte` sta in tutti e due i punti, così le
righe e i valori parlano dello stesso insieme.

## 3. Cosa regge sopra la forma ibrida

Tutto quello che serve alla pagina, **con un'avvertenza sul taglio temporale**.

| operazione | esito |
|---|---|
| `.filter()` su campo normale | regge |
| `.filter()` sull'annotazione di finestra (`running_max__gt=120`) | regge — Django avvolge in una subquery |
| `.order_by("-running_max")` | regge |
| slice `[:12]` | regge |
| `.count()` | regge |

**L'avvertenza.** `.filter(started_at__year__gte=2026)` finisce in `WHERE`,
cioè **prima** della finestra: il massimo cumulativo **riparte dal taglio**.
Sulla panca piana il taglio a 2026 dà `running_max = 108.5` sulla prima riga
quando il massimo di sempre a quella data era 143,3. Non è un errore di Django,
è la semantica giusta di `WHERE`, ma è la risposta sbagliata alla domanda
«mostrami l'ultimo anno».

**Il taglio temporale va fatto in Python, dopo la query.** È la stessa regola
che `04-analisi.md` già applica ai buchi di `TruncWeek`: il database aggrega,
Python presenta. Costa zero — il caso peggiore del database sono 146 righe.
In alternativa il taglio si fa in `WHERE` **solo** se si accetta che il grafico
mostri il record del periodo e non quello di sempre; è una scelta di
presentazione, e va decisa nel ticket della pagina, non qui.

## 4. Quanto costa

Minimo di 5–7 giri, database caldo:

| forma | tempo | righe |
|---|---|---|
| **ibrida** (`Subquery(Max)` + due `Window`) | **5,9 ms** | 146 |
| solo l'aggregato per sessione, senza finestre | 4,4 ms | 146 |
| `Subquery` correlata pura, senza finestre | **1.906 ms** | 146 |

Le due finestre costano **1,5 ms** sopra l'aggregato che comunque serve. A3 non
è un problema di prestazioni, e il ticket della pagina può scriverla senza
guardarsi le spalle.

**Il ripiego puro va scartato, e per la stessa ragione di #76.** La `Subquery`
correlata che rifà il `Max(EPLEY)` per ogni riga costa **320 volte** la forma
ibrida: SQLite la rivaluta riga per riga, esattamente come la `Subquery`
ordinata su espressione che in #76 portò una pagina da 0,01 s a 31 s. La spec
diceva «se non regge, il ripiego è una `Subquery` correlata»: la direzione era
giusta, ma la `Subquery` va messa **sotto** le finestre, non al posto loro.

Il SQL generato ripete la subquery correlata **tre volte** (una per `best_1rm`,
una dentro `MAX ... OVER`, una dentro `LAG`). È brutto da leggere e non conta:
SQLite la valuta una volta per riga in ogni caso, ed è quel numero — 146 — a
tenere basso il costo.

## Come si lancia

Dalla radice del repo, con un `db.sqlite3` seedato:

```
uv run python prototypes/t98-a3-window/probe.py      # 1: cosa rifiuta Django
uv run python prototypes/t98-a3-window/varianti.py   # 2: le strade provate
uv run python prototypes/t98-a3-window/ibrida.py     # 3: la forma che vince
```

## Due note fuori dalla domanda del ticket

- **`demo064` oggi si chiama `cavallinilorenzo`.** `seed_synthetic.DEMO_USERNAME`
  vale ancora `demo064`, ma quello è il nome prima che `assegna_username` lo
  sostituisca. La mappa #96 lo chiama «Martina Longo»: è un residuo di prima
  di #95, e va corretto nelle Notes o il prossimo ticket cerca un utente che
  non esiste.
- **La regola 5 della mappa regge, ma non per la ragione scritta.** Diceva «A3
  non è un metodo: è due passaggi, cioè una risposta». Nella forma ibrida A3 è
  **un solo QuerySet concatenabile** — quindi l'argomento cade. Resta però una
  domanda e non un'espressione: prende `user` ed `exercise` come parametri e
  restituisce righe pronte per un grafico. Va in `analytics/`, ma la
  motivazione da dire all'orale è quella, non «sono due passaggi».
