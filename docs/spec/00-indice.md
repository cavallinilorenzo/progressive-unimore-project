# Progressive — la spec

Questo è **il documento**: la mappa, la checklist dei requisiti, l'ordine di costruzione e i confini. Gli altri file sono il suo corpo.

Chiude [#20](https://github.com/cavallinilorenzo/progetto-django-uni/issues/20), l'ultimo ticket della mappa [#11](https://github.com/cavallinilorenzo/progetto-django-uni/issues/11). Da qui in poi non c'è più niente da decidere: si costruisce.

## Cos'è Progressive

Un'applicazione web Django sull'**allenamento con i pesi e il sovraccarico progressivo**, erede concettuale dell'app iOS *Overload*. Progetto d'esame di **IWC 2026** (prof. Francesco Faenza, UniMoRe), individuale, consegnato come repo GitHub pubblico e discusso all'orale.

Tre strati, in ordine di importanza decrescente: il **coach** che dice cosa fare, il **motore analitico** che lo giustifica, la **parte sociale** come contorno.

## Dove si legge cosa

| File | Contenuto |
|---|---|
| **[01-modelli.md](01-modelli.md)** | I sei modelli campo per campo, le anagrafiche, i vincoli, e **sei discrepanze fra i ticket risolte** |
| **[02-pagine-e-template.md](02-pagine-e-template.md)** | `base.html`, il guscio, la sitemap, gli URL, le convenzioni del corso, la heatmap |
| **[03-import-ed-export.md](03-import-ed-export.md)** | I due canali di import, la validazione misurata sui dati veri, l'abbinamento dei nomi |
| **[04-analisi.md](04-analisi.md)** | Le sei analisi con le query, le due classifiche, le trappole dell'ORM |
| **[05-coach-e-stallo.md](05-coach-e-stallo.md)** | Le regole del coach, il rilevamento dello stallo, la validazione del ML |
| **[06-dati.md](06-dati.md)** | Catalogo, storico reale, popolazione sintetica, ordine di caricamento |
| **[07-test.md](07-test.md)** | Cosa si testa, e il test che protegge un requisito della traccia |

Fuori da qui: **[`CONTEXT.md`](../../CONTEXT.md)** per i termini, **[`docs/adr/`](../adr/)** per i perché. La spec non ridefinisce niente — è l'unico posto dove sta il *come*.

## Lo stack, e la regola che lo ha scelto

> Si adotta ciò che il prof usa nel suo progetto d'esempio, perché ogni deviazione costa tempo e non rende voto.

Regola posta da Lorenzo il 2026-09-07, e ha deciso quasi tutto lo stack:

- **Django 6** (`django>=6.0.3`, unica dipendenza dell'esempio del corso)
- **`uv`** come gestore pacchetti
- **Bootstrap 5.3.0 da CDN**
- **SQLite**
- **Niente JavaScript applicativo** — l'unica eccezione è Chart.js, alimentato da `json_script`
- **Solo locale**, nessun deploy

Le due deviazioni consapevoli, **entrambe da dichiarare all'orale**: il **custom user model** al posto di `Profile` in OneToOne ([ADR-0003](../adr/0003-custom-user-model.md)), e le **~200 righe di CSS custom** del guscio Pulse.

## Checklist della traccia, riga per riga

Traccia in `temp/05_IWC_django_progetti_esame.pdf`, sezione *Minimum Technical Requirements*. Ogni riga è verificabile, non una buona intenzione.

| Requisito del prof | Dove è soddisfatto | Fase |
|---|---|---|
| **Dynamic, database-driven (SQLite is fine)** | SQLite; ogni pagina rende da query, nessun contenuto statico | 1 |
| **Models: 5–6 related models** | **Sei di prima classe**: `Exercise`, `Routine`, `RoutineExercise`, `Workout`, `WorkoutSet`, `Vote`. Più le anagrafiche (`Muscle`, `MuscleGroup`, `Equipment`) e `ExerciseAlias`, che **non si contano**. Vedi [01](01-modelli.md) | 1 |
| **CRUD operations on main objects** | CRUD **completo** su `Routine` (`/schede/`) e su `Workout` + le sue serie (`/allenamenti/`); un terzo su `Vote`. `Exercise` è **in sola lettura per scelta** (ADR-0001) — deviazione da dichiarare, non dimenticanza. Vedi [02](02-pagine-e-template.md) | 1 |
| **User interaction: select/view single or grouped objects** | `/esercizi/` filtrabile per gruppo, muscolo, attrezzo; `/schede/pubbliche/`; `/allenamenti/` | 1 |
| **User interaction: vote, modify, insert via forms** | **Voto** su scheda pubblica (`Vote`, 1–5 + commento, un voto per utente, autovoto vietato); **inserimento** di schede, allenamenti e serie via ModelForm e formset; **modifica** ovunque | 1 |
| **Display results or rankings** | **Due classifiche di natura diversa**: forza relativa per esercizio, e schede pubbliche per punteggio bayesiano. Pagina propria `/classifiche/` **nel menu**, non sepolta. Vedi [04](04-analisi.md) | 1 |
| **Data import — Django Forms** | Ogni CreateView/UpdateView; e il form di upload dell'import è esso stesso un Django Form con validazione | 1 |
| **Data import — CSV upload (parse and insert)** | **Due canali**: `load_catalog` (amministratore) e l'**import dello storico** (utente): upload di due file, parsing a streaming, validazione riga per riga, abbinamento interattivo dei nomi, anteprima, report errori, conferma atomica. Più l'**export** nello stesso formato. Vedi [03](03-import-ed-export.md) | 1 |
| **`base.html` with at least 3 blocks** | **Sei blocchi**: i tre imposti (`header`, `content`, `footer`) più `title`, `extra_head`, `scripts`. Più conforme del `base.html` dell'esempio del prof, che ne ha tre diversi | 1 |
| **All pages extend `base.html`** | Regola non negoziabile, incluse le pagine d'errore. **Protetta da un test** che fallisce se un template non eredita. Vedi [07](07-test.md) | 1 |
| **«Make it meaningful — use your passions»** | Il tema è la palestra, che Lorenzo pratica; il dominio viene dallo schema di un'app iOS che ha davvero scritto; **i dati della demo sono il suo storico vero**. Non è un blog travestito | — |
| **Fully functional, sensible interface, clear purpose** | Il guscio Pulse ereditato da Overload; la regola di navigazione «nessun link orfano»; il coach che dà **un** consiglio alla volta | 1–3 |

**A fine fase 1 la checklist è chiusa al 100%.** Tutto ciò che viene dopo aggiunge voto, non lo mette in sicurezza.

## L'ordine di costruzione

Vincolo di scope, non un suggerimento. Il ragionamento: **sui requisiti minimi non ci sono punti da guadagnare, solo da perdere.** Costruire la parte affascinante prima di quella necessaria è il modo in cui i progetti finiscono senza finire — lezione già pagata con Pratica.

### Fase 1 — la checklist, finita e funzionante

Nell'ordine, perché ogni passo dipende dal precedente:

1. `startproject` + `uv` + SQLite + `settings.py`. **`AUTH_USER_MODEL` va messo prima della primissima migrazione**, o dopo costa caro
2. Modelli, tutti e sei più le anagrafiche e `ExerciseAlias`; `slug` su `Exercise`, `load_increment_kg` su `Equipment`; migrazioni
3. `load_catalog` adattato ai due campi nuovi, e caricato
4. `base.html` a sei blocchi + il guscio Pulse portato dal prototipo `prototypes/t19-pagine/`
5. Autenticazione: registrazione, login, logout, `/profilo/` con `body_mass_kg`
6. CRUD `Routine` + `RoutineExercise`
7. CRUD `Workout` + `WorkoutSet`, incluso «avvia allenamento da scheda»
8. `Exercise` in sola lettura, lista filtrabile
9. Schede pubbliche + `Vote` (il terzo CRUD)
10. Import CSV: i tre URL, l'abbinamento, l'anteprima, il report — **più l'export**
11. Le due classifiche
12. `seed_synthetic` portato dentro come management command
13. `tests.py` e l'admin

**Qui il voto è al sicuro. Non si prosegue prima che questa lista sia chiusa.**

### Fase 2 — il motore analitico

Il custom QuerySet, poi **A3 per prima** (è l'unica con un'incognita: `Window` sopra un aggregato), poi le altre cinque, i tre grafici via `json_script`, la pagina di analisi muscolare, la heatmap.

Alla fine della fase 2 va fatta **una misura vera** dei tempi di query di percentile e classifica su 299.367 serie: è la condizione a cui è subordinata la questione dei valori derivati (vedi *Confini*).

### Fase 3 — il coach

Le quattro regole, la doppia progressione, il riquadro in dashboard, il consiglio sul dettaglio esercizio.

### Fase 4 — il ML

Estrazione delle finestre, etichettatura dal futuro (**orizzonte 6**), le sei feature, training offline con `scikit-learn`, confronto col baseline, coefficienti come costanti in `plateau.py`.

**È l'unica cosa tagliabile.** Se si taglia, la pagina dello stallo mostra il baseline a soglia, e lo si dichiara — che è comunque la risposta prevista se il modello non batte la regola.

## Le tecniche non insegnate, e come si introducono

Il corso è **tre lezioni** (46+42+28 slide) più il progetto d'esempio, e **l'unica riga di ORM avanzato che ha insegnato è `annotate(Count(...))`**. Tutto il motore analitico sta sopra quella riga.

Quella riga **è il ponte**, e all'orale si percorre in un ordine solo: *da `annotate(Count(...))` a tutto il resto, un passo per volta, e ogni passo risolve un problema concreto che il precedente non risolveva.*

| Tecnica | Dove | La frase che la introduce |
|---|---|---|
| `annotate(Count(...))` | classifica sociale | Il punto di partenza: è quella del corso |
| `aggregate` | media globale dei voti | «`annotate` dà un numero per riga, `aggregate` uno per l'intero queryset» |
| `F()` | volume, carico effettivo | «serve moltiplicare due colonne fra loro, e in Python significherebbe scaricare 299.367 righe» |
| `Case`/`When` | carico effettivo | «sul corpo libero il carico è un'altra cosa, e la condizione deve stare nel database» |
| `Subquery`/`OuterRef` | PR, `best_at` | «per ogni riga serve un valore che viene da un'altra query» |
| `Window` + `Lag` | progressione | «serve confrontare una riga con la precedente, e `GROUP BY` non sa farlo» |
| `Window` + `PercentRank` | percentile | «SQLite non ha `percentile_cont`, quindi il percentile si costruisce con una window function» |
| `Window` + `Rank` | pari merito | «due primi devono essere entrambi primi» |
| `TruncWeek`/`TruncMonth` | volume nel tempo | «raggruppare per settimana senza portare le date in Python» |
| custom `QuerySet`/`Manager` | `querysets.py` | «tre definizioni comparivano in quasi ogni query: o si ripetono, o si nominano una volta» |
| `select_related` | liste | «una lista di 25 allenamenti faceva 26 query» |
| `transaction.atomic` | conferma import | «317 righe entrano tutte o nessuna» |
| management command | `load_catalog`, `seed_synthetic` | «è il posto dove Django mette gli script, e ha già il ciclo di vita giusto» |

**Il criterio con cui difenderle è uno solo**, ed è lo stesso che le ha ammesse: ognuna **alimenta una decisione dell'utente**. Nessuna è lì per far vedere che si sa fare.

## I limiti che si dichiarano

Questo progetto sceglie di **dire** i propri limiti invece di nasconderli, ed è una posizione da tenere all'orale, non una scusa. Sono cinque, tutti già scritti negli ADR:

1. **Il percentile tace sotto i 20 utenti** su un esercizio, e dice perché
2. **Lo stallo dice «dati insufficienti»** come avanzamento, non come errore
3. **4 muscoli su 23 sono sempre spenti** nella heatmap, perché il catalogo tagga un solo muscolo primario: la mappa dice «trascurato» dove la verità è «non misurato»
4. **Il peso corporeo riscrive il passato**, e sul corpo libero lo riscrive due volte ([ADR-0008](../adr/0008-peso-corporeo-corrente-come-denominatore.md))
5. **`_corpo.svg` non è lavoro nostro**: è copiato dai path anatomici di Overload, e va detto nel repo e all'orale ([#40](https://github.com/cavallinilorenzo/progetto-django-uni/issues/40))

E uno che è quasi un limite: **se il modello di ML non batte la regola a soglia, si spedisce la regola.**

## Confini — cosa resta fuori, e perché

Fuori scope per decisione presa, non per dimenticanza:

- **Deploy online** — la traccia non lo chiede e SQLite basta; il tempo va nelle query, non in Docker
- **HTMX, Tailwind, React/SPA** — nessuno compare nel progetto d'esempio del corso. Una SPA in particolare renderebbe `base.html` e l'ereditarietà dei template una finta, cioè esattamente un requisito minimo
- **Tracciamento dal vivo** (timer di recupero, spunta serie per serie) — è JavaScript per definizione. «Avvia allenamento da scheda» è la versione server-rendered che sopravvive
- **Esercizi custom** — un esercizio inventato sarebbe invisibile a percentili e classifiche ([ADR-0001](../adr/0001-catalogo-esercizi-globale-e-scritto-a-mano.md))
- **Storico dei pesi corporei** — sarebbe un settimo modello per un effetto che sui dati sintetici non si manifesta ([ADR-0008](../adr/0008-peso-corporeo-corrente-come-denominatore.md))
- **Rilevatore di deload** — nessun campo affidabile per riconoscerlo: sarebbe un secondo problema non validabile ([ADR-0004](../adr/0004-ground-truth-dello-stallo-dal-futuro-della-finestra.md))
- **Classifica di forza generale** stile «total» — e qui la ragione è **misurata**, non stimata: panca, squat e stacco compaiono in 78, 84 e 82 storici su 100, ma **tutti e tre insieme in soli 55**. Una classifica composita escluderebbe 45 utenti su 100
- **Import di schede** — si rifanno a mano in dieci minuti, e raddoppierebbero i livelli di FK per zero requisito
- **Corpus pubblico di standard di forza** — i percentili si calcolano sulla popolazione interna
- **Modifiche a Overload** — è la sorgente dello schema e dei dati, non un bersaglio di lavoro

**Rinviato a dopo la fase 2, con una condizione precisa:** materializzare i valori derivati (volume, massimale, punteggi). Oggi si calcolano nell'ORM a ogni query, per scelta, ed è proprio ciò che il progetto deve dimostrare. La decisione si riapre **solo** se la misura sui 299.367 record al termine della fase 2 mostra query lente — **dopo** averle scritte, non prima.

**Rinviato a dopo la build:** la **demo orale** — quali dati caricare, in che ordine mostrare le pagine, cosa dire su ogni requisito. Ha bisogno dell'app che gira per essere provata; deciderla ora significherebbe deciderla al buio. Due vincoli sono però già fissati: lo storico reale è troppo corto per la pagina dello stallo, e l'utente su cui si dimostra è già scelto — **`demo064`, Martina Longo**.
