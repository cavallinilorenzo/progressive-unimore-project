# 03 — Import ed export

Fonte: [#26](https://github.com/cavallinilorenzo/progetto-django-uni/issues/26), [#13](https://github.com/cavallinilorenzo/progetto-django-uni/issues/13) (i dati veri su cui la validazione è stata scritta), [#27](https://github.com/cavallinilorenzo/progetto-django-uni/issues/27) (`load_catalog`).

Il requisito «data import (at least one)» è pagato **due volte, da due canali con due pubblici diversi**, e i due non si sostituiscono:

| Canale | Pubblico | Come |
|---|---|---|
| `load_catalog` | amministratore | management command, già scritto |
| Import dello storico | utente | form web, upload CSV, anteprima, conferma |

Quello che si mostra al prof è il secondo.

## Il formato è di Progressive, e Progressive lo esporta

Si caricano **due file in un solo form e un solo POST**: `workout_sessions.csv` + `session_sets.csv`.

Questa è la decisione che ha riorientato il ticket, e nasce da un'obiezione di Lorenzo: *«a cosa serve l'import? Quei dati prima di essere importati sono stati esportati da un altro software»*. L'obiezione ha scoperto una debolezza vera — quel formato era lo schema interno di Overload, **e nessuno tranne Lorenzo poteva produrlo**. Un estraneo che si iscrive non ha un `session_sets.csv`, e si troverebbe davanti a un import che fallisce senza via d'uscita.

Quindi: **Progressive esporta gli stessi due file che sa importare.** Una vista da una ventina di righe (`HttpResponse` con `content_type="text/csv"`), stesse colonne, stesso parser. Il giro si chiude, e l'export di Overload smette di essere «il formato di un'altra app» per diventare **uno dei produttori** del formato di Progressive.

Cosa **non** si importa:

- `exercises.csv` — il catalogo è globale e chiuso: gli esercizi si **risolvono**, non si creano ([ADR-0001](../adr/0001-catalogo-esercizi-globale-e-scritto-a-mano.md))
- `profiles.csv` — è un utente solo, ed è quello già loggato
- `routines.csv` / `routine_exercises.csv` — le schede si rifanno a mano in dieci minuti, e importarle raddoppierebbe i livelli di FK per zero requisito

Scartato anche un **CSV unico denormalizzato**: più facile da parsare, ma avrebbe obbligato a trasformare i dati *fuori* dall'app, cioè a ripulirli prima di dimostrare che l'app regge i dati sporchi.

## Idempotenza: `external_id`

PK autoincrement normali, più un campo **`external_id`** (UUID, nullable, unique) su `Workout` e `WorkoutSet`. Due campi in cambio dell'idempotenza: ricarichi lo stesso file e non duplichi niente.

Il **nullable è essenziale**: un allenamento nato dentro Progressive non ha nessun `external_id` e non deve fingerne uno.

E resta vero anche dopo l'export, che è il punto in cui la regola si è dovuta difendere (#74): un CSV ha bisogno di un `id` su ogni riga, ma le righe che escono sono in maggioranza nate qui. Ognuna ha quindi un **nome pubblico** — quello di provenienza se importata, altrimenti uno derivato dalla sua chiave primaria, uguale a ogni export e **mai scritto in database**. L'import riconosce i due allo stesso modo, e così «esporta e reimporta» non aggiunge niente nemmeno a uno storico che non è mai stato importato. Motivazione completa e limite dichiarato in [ADR-0011](../adr/0011-nome-pubblico-calcolato-non-memorizzato.md).

Scartati: l'UUID come PK (imporrebbe la chiave di un altro sistema anche agli allenamenti creati in-app) e la deduplica implicita su `unique(user, started_at)` (si rompe appena l'utente corregge un orario).

## Validazione — scritta sui dati veri, non immaginati

Ogni regola qui sotto è misurata su `docs/overload-export.md`.

| Caso | Quante | Cosa fa l'import |
|---|---|---|
| Serie **non completate** | 61 (19%) | **Entrano**, con `is_completed=False` e `reps`/`weight` a null |
| Serie completate **senza peso** | 25 | **Valide.** È il corpo libero: trazioni e leg raises non hanno *mai* un carico |
| Serie completate **senza `reps`** | 2 | **Errore vero.** Riga, colonna, motivo nel report |
| `ended_at` assurdo (0 min, 25 ore) | 2 su 15 | **Entra intatto, con un warning non bloccante** |

Le prime tre righe sono la trappola in cui l'import sarebbe caduto senza aver prima misurato i dati: una validazione che pretende `weight` non nullo su una serie completata **rifiuterebbe dati legittimi**.

Su `ended_at`: correggere una durata implausibile significherebbe **inventare dati**, e scartare perderebbe 2 sessioni su 15 in un dataset che ne ha quindici. L'unica regola bloccante resta il check di modello, `ended_at >= started_at`.

**Il `user_id` del CSV si ignora.** È un dato di un altro sistema e non ha nessuna autorità qui: l'unica fonte dell'identità è `request.user`. Nessun import per conto di altri, nemmeno da admin — superficie d'abuso in cambio di niente.

**Il `routine_id` non punta a niente**, avendo escluso le schede: `Workout.routine` resta null e sopravvive il solo `title`. È esattamente il caso che [ADR-0002](../adr/0002-allenamento-log-immutabile.md) descrive.

## L'abbinamento dei nomi lo fa l'utente

**Qui la raccomandazione iniziale era sbagliata, ed è stata corretta misurando.** La proposta era una normalizzazione automatica (casefold, apostrofi tipografici, accenti, spazi). Confrontando i **24 nomi reali** con i **100 del catalogo**, la normalizzazione ne risolve **quasi zero**:

- `RDL` → «Stacco rumeno con bilanciere»
- `Polpacci su leg press` → «Calf raise al leg press»
- `Leg extention` — refuso dentro
- `d'Annunzio crunch` — ambiguo **anche per un umano**: «Crunch a terra» o «Crunch ai cavi»?

Non è un problema di stringhe: è una **scelta, e la fa l'utente**. L'anteprima presenta i nomi non riconosciuti in una tabella, ognuno con una `<select>` del catalogo accanto; la scelta si memorizza in **`ExerciseAlias`**, così il secondo import non la richiede più.

Il matching automatico non sparisce, **cambia ruolo**: da meccanismo di risoluzione a **suggerimento** che preseleziona la voce più probabile, e può sbagliare senza danno perché c'è un umano a correggerlo.

Tutto server-rendered: un `formset` e delle `<select>`, zero JavaScript. Motivazione completa in [ADR-0010](../adr/0010-abbinamento-nomi-import-interattivo.md).

## Anteprima, atomicità, report

**Parziale in anteprima, atomico in conferma.** L'anteprima elenca gli errori e l'utente decide se procedere scartando le righe cattive; la conferma gira dentro un solo `transaction.atomic`.

Il tutto-o-niente puro bloccherebbe 317 righe per due celle sbagliate; il parziale cieco renderebbe l'anteprima decorativa. `transaction.atomic` resta e resta dimostrabile — si sposta solo il punto in cui si applica.

**L'anteprima mostra cinque cose**, e le prime due sono le uniche su cui si agisce, quindi stanno in cima e in grande:

1. il riepilogo — *N allenamenti, N serie, dal … al …*
2. la tabella di abbinamento dei nomi — **è un form, non una schermata di sola lettura**
3. le righe in errore col motivo
4. i warning non bloccanti — durate assurde, serie non eseguite
5. i duplicati già presenti che verranno saltati

Le ultime tre sono resoconto, in tabelle collassate sotto.

**Il report errori** è una tabella con file, **numero di riga reale del CSV** (intestazione = riga 1), colonna, valore trovato, motivo in italiano, preceduta da «lette N, valide N, scartate N». **Tutte** le righe in errore, senza troncamento: se un giorno fossero trecento, quel numero *è* l'informazione che serve.

## Dove sta il file fra i due passi

**Su disco**, in `MEDIA_ROOT/imports/`, con la chiave in `request.session`, e si riparsifica alla conferma.

Scartata la **tabella di staging** (`ImportBatch`/`ImportRow`): due modelli che non pagano nessun requisito, che poi vanno anche ripuliti, e che intorbidano la storia «sei modelli di dominio». Scartati anche il parsato dentro la sessione (~100 KB di JSON) e il doppio upload.

## Gli URL

**Tre URL, non una vista con tre rami dentro `post()`** — quella è la cosa che poi non si riesce a spiegare all'orale.

| URL | Nome | View |
|---|---|---|
| `/import/` | `import-upload` | `FormView` — i due file |
| `/import/anteprima/` | `import-preview` | `FormView` — il formset degli abbinamenti |
| `/import/esito/` | `import-result` | `TemplateView` |
| `/export/allenamenti/` | `export-csv` | `View` — scarica `workout_sessions.csv` |
| `/export/serie/` | `export-csv` | `View` — scarica `session_sets.csv` |

Tre template che estendono `base.html`; l'export non ne ha nessuno, ed è la sua natura — restituisce un file, non una pagina. I link stanno nel menu utente accanto a «Importa storico» e nella pagina di import, che è dove serve a chi un file non ce l'ha.

**Un solo `/export/` è diventato due URL** (#74): i file sono due, e comprimerli in uno ZIP avrebbe obbligato a spacchettarli prima di ricaricarli, cioè a toccare i dati **fuori** dall'app — la stessa ragione per cui è stato scartato il CSV unico denormalizzato. Il nome del file sta nel percorso e non in query string perché qui il parametro *identifica la risorsa*, al contrario di `?scheda=<pk>` su «avvia allenamento», che lascia la pagina la stessa.

## Due decisioni minori

Prese senza chiedere, e segnalate perché si ribaltano a costo zero.

- **Limite 5 MB per file** più estensione `.csv`, verificati nel form. Lo storico reale sta in ~60 KB, quindi 5 MB sono ~25.000 serie. Il parsing è **a streaming** — `csv.DictReader` su un `TextIOWrapper` — mai un `.read()` in memoria.
- **I CSV di prova sono fabbricati a mano e versionati** in `training/tests/fixtures/`, e **non** sono i dati reali (personali, in `.gitignore`). Piccoli — tre sessioni, una decina di serie — e costruiti perché contengano **uno per uno** i casi decisi qui: una serie non eseguita, una completata senza peso, una completata senza `reps`, una sessione con `ended_at` assurdo, un nome non abbinabile, un duplicato. Sono la traduzione in test della sporcizia misurata in #13.
