# I CSV di prova dell'import

Fabbricati a mano e **versionati**, come prescrive `docs/spec/03-import-ed-export.md`.
Non sono i dati reali: quelli sono personali e stanno in `.gitignore`. Sono
piccoli — tre sessioni, dieci serie — e ogni riga è **un caso deciso**, non
riempitivo: è la sporcizia misurata su `docs/overload-export.md`, tradotta in
un file che sta in una schermata.

I nomi degli esercizi sono quelli **veri** del catalogo (`data/catalog/`), che
è ciò che rende il file un file di Progressive; l'unica eccezione è voluta ed è
`RDL`.

## `workout_sessions.csv`

| Riga | Sessione | Caso |
|---|---|---|
| 2 | Spinta A | normale, e il `routine_id` **punta a niente**: le schede non si importano |
| 3 | Sessione lampo | `ended_at` **assurdo** (20 secondi): entra intatta, con un avviso non bloccante |
| 4 | Tirata A | normale |

Il `user_id` è `4242` su tutte e tre, e non esiste: è il dato di un altro
sistema, e l'unica fonte dell'identità è `request.user`.

## `session_sets.csv`

Il numero di riga è quello **reale** del file, intestazione compresa — è quello
che il report degli errori mostra.

| Riga | Caso | Atteso |
|---|---|---|
| 2, 3 | serie normali | entrano |
| 4 | `Trazioni alla sbarra` senza peso | **valida**: è il corpo libero, non un dato mancante |
| 5 | serie **non eseguita** | entra, `is_completed=False`, `reps` e `weight` nulli |
| 6 | `Leg press` eseguita **senza `reps`** | **scartata**, e nel report con riga e motivo |
| 7 | seconda `Leg press` | entra: lo scarto è della riga, non della sessione |
| 8 | `RDL` | nome **non abbinabile**: va nel form di abbinamento, non fa fallire l'import |
| 9 | `warmup` | entra: i tipi di serie sono tre |
| 10, 11 | corpo libero senza peso | entrano |

Gli altri due casi della tabella di `07-test.md` §4 — «`external_id` già noto»
e «stesso file due volte» — non sono righe del file ma **stati del database**,
e i test li costruiscono importando due volte questi stessi file.
