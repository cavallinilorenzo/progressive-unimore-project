# 01 — Modelli

Fonte: [#14](https://github.com/cavallinilorenzo/progetto-django-uni/issues/14) (modello di dominio), [#26](https://github.com/cavallinilorenzo/progetto-django-uni/issues/26) (`ExerciseAlias`, campi nullable), [#31](https://github.com/cavallinilorenzo/progetto-django-uni/issues/31) (`load_increment_kg`), [#27](https://github.com/cavallinilorenzo/progetto-django-uni/issues/27) (le quattro anagrafiche, già scritte).

Tutto vive in **una sola app, `training`**. Nessuna seconda app: `analytics/` è un sottopacchetto, non un'app, perché non ha modelli propri ([ADR-0005](../adr/0005-il-ml-non-entra-a-runtime.md)).

```
training/
├── models.py            # tutti i modelli, in un file solo come nell'esempio del prof
├── querysets.py         # il custom QuerySet di WorkoutSet (vedi 04-analisi.md)
├── rankings.py          # le due classifiche come query, senza HTTP (#76)
├── forms.py
├── admin.py
├── urls.py
├── views/               # pacchetto, non un file: sono ~30 view
├── analytics/
│   ├── plateau.py       # servizio stallo + coefficienti appresi come costanti
│   └── coach/           # le regole del coach (pacchetto, #112)
├── management/commands/
│   ├── load_catalog.py  # già scritto
│   └── seed_synthetic.py
├── templates/training/
└── tests/
```

## Il conteggio della traccia

La traccia chiede **5–6 related models**. Ne contiamo **sei di prima classe**, cioè quelli con CRUD e pagine proprie:

`Exercise` · `Routine` · `RoutineExercise` · `Workout` · `WorkoutSet` · `Vote`

Non entrano nel conteggio, e all'orale la frase è *«sei entità del dominio, più le anagrafiche»*:

- le anagrafiche `MuscleGroup`, `Muscle`, `Equipment` — popolate da fixture, nessun CRUD utente;
- `ExerciseAlias` — infrastruttura dell'import, non un'entità del dominio ([ADR-0010](../adr/0010-abbinamento-nomi-import-interattivo.md));
- `User` — infrastruttura di autenticazione.

## Sei discrepanze risolte qui

I ticket sono stati decisi in momenti diversi e non concordano su tutto. **Vale quanto scritto in questo file**, non la versione nel ticket d'origine.

| # | Discrepanza | Cosa vale |
|---|---|---|
| 1 | #14 scrive `Exercise.muscle`; #16 e il codice già scritto usano `primary_muscle` | **`primary_muscle`** — il codice su `main` è già così |
| 2 | #14 dichiara `Exercise.equipment` nullable; il codice scritto in #27 lo ha non-null | **non-null** — tutte e 100 le voci del catalogo hanno un attrezzo, e la query del carico effettivo diventa più semplice |
| 3 | La query A5 di #16 filtra su `equipment__code="corpo_libero"` | **`"bodyweight"`** — è il codice vero in `data/catalog/equipment.csv`. La query nel ticket è sbagliata |
| 4 | #14 impone `reps > 0` e `weight >= 0`; #26 rende entrambi nullable per le serie saltate | **nullable, con check condizionale** (sotto) |
| 5 | #19 usa `/esercizi/<slug>/` ma `Exercise` non ha `slug` | **si aggiunge `slug`**, unico, popolato da `load_catalog` |
| 6 | #31 usa `Equipment.load_increment_kg`, che non esiste ancora | **si aggiunge**, con una migrazione e una colonna nel CSV |

## Anagrafiche — già scritte, due modifiche

`MuscleGroup`, `Muscle` ed `Equipment` sono in `training/models.py` su `main` e si caricano con `load_catalog`. Due sole modifiche:

**`Equipment.load_increment_kg`** — `DecimalField(max_digits=4, decimal_places=2, default=2.5)`. Il passo minimo con cui su quell'attrezzo il carico può realmente salire; è il numero su cui gira la doppia progressione del coach. Valori: bilanciere 2.5, bilanciere EZ 2.5, manubri 2.0, kettlebell 4.0, multipower 2.5, macchina 5.0, cavi 2.5, elastico 0, **corpo libero 0**. Va aggiunta la colonna a `data/catalog/equipment.csv` e letta da `load_catalog`.

Sul corpo libero l'incremento è zero e il coach consiglia ripetizioni, mai carico: non è un valore mancante, è la regola.

## I sei modelli

### `Exercise` — catalogo globale, sola lettura

| Campo | Tipo | Note |
|---|---|---|
| `name` | `CharField(120)`, unique | In italiano |
| `slug` | `SlugField`, unique | **Nuovo.** Generato da `name` in `load_catalog`, non a runtime: gli URL devono essere stabili |
| `primary_muscle` | FK `Muscle`, `PROTECT` | Uno solo. I secondari sono fuori dal modello per scelta |
| `equipment` | FK `Equipment`, `PROTECT` | Non-null |

**Nessun CRUD utente**: il catalogo è globale e chiuso ([ADR-0001](../adr/0001-catalogo-esercizi-globale-e-scritto-a-mano.md)). È una **deviazione da dichiarare all'orale** prima che sembri una dimenticanza — il CRUD completo che la traccia chiede sta su `Routine` e `Workout`.

L'unicità di `name` è già `unique=True`. #14 la voleva *case-insensitive*: si ottiene con un `UniqueConstraint(Lower('name'))` in `Meta.constraints`. Vale la pena perché il catalogo si carica da CSV e un duplicato di sola maiuscola passerebbe silenziosamente.

### `Routine` — la scheda, mutabile

| Campo | Tipo | Note |
|---|---|---|
| `user` | FK `settings.AUTH_USER_MODEL`, `CASCADE` | `related_name="routines"` |
| `name` | `CharField(120)` | |
| `notes` | `TextField`, blank | |
| `is_public` | `BooleanField(default=False)` | Solo se `True` è votabile |
| `created_at` | `DateTimeField(auto_now_add=True)` | |

### `RoutineExercise` — una voce della scheda

| Campo | Tipo | Note |
|---|---|---|
| `routine` | FK `Routine`, `CASCADE` | `related_name="exercises"` |
| `exercise` | FK `Exercise`, `PROTECT` | |
| `position` | `PositiveSmallIntegerField` | |
| `target_sets` | `PositiveSmallIntegerField` | |
| `target_reps` | `PositiveSmallIntegerField` | Estremo basso del range |
| `target_reps_max` | `PositiveSmallIntegerField`, nullable | Estremo alto; è **questo** che la doppia progressione insegue |
| `notes` | `CharField(200)`, blank | |

`Meta.ordering = ["position"]`.

**Unicità su `(routine, exercise)`, non su `(routine, position)`.** È la scelta meno ovvia del modello: riordinare due esercizi violerebbe un vincolo su `position` a metà transazione, e SQLite non ha vincoli differibili usabili — servirebbero posizioni temporanee. L'unicità su `(routine, exercise)` è invece una regola di dominio vera (un esercizio compare una volta per scheda) e l'ordine lo tiene `ordering`.

### `Workout` — l'allenamento, log immutabile

| Campo | Tipo | Note |
|---|---|---|
| `user` | FK utente, `CASCADE` | |
| `routine` | FK `Routine`, **`SET_NULL`**, nullable | Cancellare la scheda non cancella la storia |
| `title` | `CharField(120)` | **Istantanea** del nome della scheda al momento dell'esecuzione |
| `started_at` | `DateTimeField` | |
| `ended_at` | `DateTimeField`, nullable | |
| `notes` | `TextField`, blank | |
| `external_id` | `UUIDField`, nullable, unique | Idempotenza dell'import. Null per gli allenamenti nati in-app |

`SET_NULL` + `title` insieme sono [ADR-0002](../adr/0002-allenamento-log-immutabile.md): modificare o cancellare la scheda non riscrive mai il passato.

### `WorkoutSet` — la serie

| Campo | Tipo | Note |
|---|---|---|
| `workout` | FK `Workout`, `CASCADE` | `related_name="sets"` |
| `exercise` | FK `Exercise`, `PROTECT` | Punta a `Exercise`, **mai** a `RoutineExercise` |
| `set_number` | `PositiveSmallIntegerField` | |
| `reps` | `PositiveSmallIntegerField`, **nullable** | Null se la serie è stata saltata |
| `weight` | `DecimalField(6,2)`, **nullable** | Null se saltata. **Zero è legittimo** sul corpo libero |
| `set_type` | `CharField`, choices | `working` / `warmup` / `rampUp` |
| `is_completed` | `BooleanField(default=True)` | «Eseguita» contro «saltata» |
| `external_id` | `UUIDField`, nullable, unique | Idempotenza dell'import |

`weight` è **sempre già comprensivo del bilanciere**. `Equipment.default_bar_weight_kg` serve solo a precompilare il form e non entra in nessuna analisi: sommarlo a valle significherebbe non sapere più se un numero l'ha scritto l'utente o inventato la query.

Unicità su `(workout, exercise, set_number)`.

### `Vote` — il voto su una scheda pubblica

| Campo | Tipo | Note |
|---|---|---|
| `user` | FK utente, `CASCADE` | |
| `routine` | FK `Routine`, `CASCADE` | `related_name="votes"` |
| `score` | `PositiveSmallIntegerField` | 1–5 |
| `comment` | `TextField`, blank | |
| `created_at` | `DateTimeField(auto_now_add=True)` | |

Unicità su `(user, routine)`. Scala 1–5 e non pollice su/giù, perché serve una media da ordinare.

**Il divieto di autovoto non è esprimibile come vincolo di database** — attraversa una relazione. Vive nel form e nella vista, e va testato lì.

## `ExerciseAlias` — infrastruttura dell'import

| Campo | Tipo |
|---|---|
| `user` | FK utente, `CASCADE` |
| `raw_name` | `CharField(160)` |
| `exercise` | FK `Exercise`, `CASCADE` |

Unicità su `(user, raw_name)`. Non compare in nessuna analisi e non allarga il catalogo: è il modo in cui un nome estraneo entra nel dominio senza sporcarlo.

## `User` — custom user model

`AUTH_USER_MODEL = "training.User"`, sottoclasse di `AbstractUser`. **Va fatto alla primissima migrazione**: dopo costa una migrazione dolorosa, ed è l'unica ragione per cui vale la deviazione.

| Campo aggiunto | Tipo | Note |
|---|---|---|
| `body_mass_kg` | `DecimalField(5,2)`, nullable | Un solo valore **corrente**, non uno storico ([ADR-0008](../adr/0008-peso-corporeo-corrente-come-denominatore.md)) |
| `is_synthetic` | `BooleanField(default=False)` | Utente generato, **dichiarato in interfaccia** ([ADR-0009](../adr/0009-la-popolazione-sintetica-si-dichiara.md)) |

`body_mass_kg` nullable non è una svista: senza di esso l'utente **non compare** in classifica e non riceve un percentile, con l'invito a compilare il profilo. Meglio assente che sbagliato.

Questa è una **deviazione dal progetto d'esempio del corso**, che usa `Profile` in OneToOne. È la raccomandazione della documentazione Django, costa zero solo se presa subito, e va **spiegata all'orale** ([ADR-0003](../adr/0003-custom-user-model.md)).

## Vincoli e indici

**Check constraints:**

- `Vote.score` fra 1 e 5
- `Workout`: `ended_at` nullo **oppure** `>= started_at` — l'unico bloccante sulle durate
- `WorkoutSet`: **`is_completed=False` OPPURE `reps > 0`** (risoluzione della discrepanza 4). Non si può pretendere `reps` su una serie saltata, e non si può accettare una serie eseguita a zero ripetizioni
- `WorkoutSet`: `weight` nullo **oppure** `>= 0` — zero è valido, negativo no

**Indici:** `WorkoutSet(exercise)` e `Workout(user, -started_at)`.

Nota onesta: Overload ha `session_sets(exercise_id, completed_at desc)`, dichiarato come l'indice che regge le query di progressione. Avendo tolto `completed_at` dalla serie, quell'indice non è costruibile e ogni query di progressione passa da un join su `Workout` per la data. Con ~100 utenti sintetici SQLite non se ne accorge — è una scelta, non una svista, e va detta così.

## Cosa di Overload non passa, e perché

Overload si usa **durante** l'allenamento; Progressive si compila **dopo**. Escono tutte le colonne che servivano solo alla prima situazione: i quattro campi del riposo, `set_types` jsonb (opaca all'ORM, che qui è tutto il progetto), `is_per_side`, `completed_at` sulla serie, `is_warmup`, `intensity`, l'intero `daily_health_activity` (viene da Apple Health), `weight_unit` (tutto in kg), `is_archived`.

Misurato sullo storico reale ([#13](https://github.com/cavallinilorenzo/progetto-django-uni/issues/13)): `set_type` è `working` su tutte e 317 le serie, `intensity` è `moderate` su tutte e 15 le sessioni, `is_warmup` è sempre falso. Sono campi che l'app espone ma che non variano mai.

Sopravvivono due, con motivo: **`set_type`**, perché ogni analisi conta le sole serie `working`; e **`body_mass_kg`**, perché la forza relativa è ciò che rende confrontabili utenti di taglia diversa.
