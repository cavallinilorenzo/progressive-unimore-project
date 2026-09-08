# 07 — Test

Fonte: [#22](https://github.com/cavallinilorenzo/progetto-django-uni/issues/22) (convenzioni del corso), [#26](https://github.com/cavallinilorenzo/progetto-django-uni/issues/26) (i CSV di prova).

I test qui non servono a raggiungere una copertura: servono a **proteggere i requisiti della traccia** e le poche regole che il database non può imporre da solo. Tutto il resto è di contorno.

## La forma, come la insegna il corso

`training/tests.py`, un file solo, `TestCase` + `Client`, assert su **200 / 302 / 403**. È il pattern del progetto d'esempio, e vale la pena seguirlo anche dove un file per area sarebbe più ordinato: all'orale è riconoscibile.

## I quattro test che contano davvero

### 1. Tutte le pagine estendono `base.html`

È l'unico requisito della traccia che si può violare **senza accorgersene**, aggiungendo un template in fretta a fine progetto. Va protetto da un test, non dalla buona volontà.

Il test scandisce `training/templates/` e `templates/` e verifica che ogni file `.html` che non sia un partial (prefisso `_`) contenga `{% extends %}` — direttamente o attraverso una catena che finisce su `base.html`. Fallisce sul file, non sul totale, così il messaggio dice quale.

### 2. La proprietà dell'oggetto

Il pattern del corso è `UserPassesTestMixin` + `test_func()`, e la conseguenza va verificata: un utente **non** può modificare né cancellare la scheda o l'allenamento di un altro. Atteso **403**, non un 404 e non un 200.

Vale per: `routine-update`, `routine-delete`, `routine-exercises`, `workout-update`, `workout-delete`, `workoutset-manage`.

### 3. Le regole che il database non può imporre

Due, entrambe già segnalate in [01-modelli.md](01-modelli.md):

- **L'autovoto è vietato** — attraversa una relazione, quindi non è un `CheckConstraint`: vive nel form e nella vista, ed è esattamente il tipo di regola che si perde in un refactor
- **Una scheda non pubblica non è votabile** — stesso motivo

### 4. L'import, sui CSV di prova

I CSV in `training/tests/fixtures/` sono fabbricati a mano perché contengano **uno per uno** i casi decisi in [03-import-ed-export.md](03-import-ed-export.md). Un test per caso:

| Caso nel file | Atteso |
|---|---|
| Serie non eseguita | entra, `is_completed=False`, `reps`/`weight` null |
| Serie completata senza peso (corpo libero) | entra, valida |
| Serie completata senza `reps` | **scartata**, e compare nel report con riga e motivo |
| Sessione con `ended_at` assurdo | entra, con **warning non bloccante** |
| Nome libero non abbinabile | compare nel form di abbinamento, non fa fallire l'import |
| Riga già importata (`external_id` noto) | **saltata**, nessun duplicato |
| Stesso file caricato due volte | nessuna riga in più — è il test dell'idempotenza |

Più uno sulla transazione: un errore in fase di conferma **non deve lasciare metà storico dentro**.

## Cosa vale la pena testare del motore analitico

Non le sei analisi in blocco, ma le **tre definizioni** su cui poggiano tutte, perché un errore lì è silenzioso e si propaga ovunque:

- **Carico effettivo** — su un esercizio a corpo libero il valore deve includere `body_mass_kg`; su un bilanciere no. È il test che avrebbe preso la discrepanza `corpo_libero` / `bodyweight`
- **Il filtro universale** — una serie `warmup` e una `is_completed=False` non devono entrare nel volume
- **Epley con il tetto** — una serie da 15 ripetizioni non concorre al massimale ma resta nel volume

E le **due trappole silenziose** di [04-analisi.md](04-analisi.md), entrambe perché non segnalano errore:

- Il punteggio sociale su una scheda con più esercizi **non** dev'essere moltiplicato per il numero di esercizi
- La divisione della media bayesiana **non** deve troncare a intero

## Cosa non si testa

Il rendering del CSS, i grafici Chart.js, i coefficienti del modello di ML (si valutano offline con precision/recall, che è un'altra cosa da un test), e la popolazione sintetica — che ha già il proprio rapporto di validazione in `docs/generatore-sintetico.md`.
