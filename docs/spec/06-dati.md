# 06 — I dati

Fonte: [#18](https://github.com/cavallinilorenzo/progetto-django-uni/issues/18) (generatore), [#13](https://github.com/cavallinilorenzo/progetto-django-uni/issues/13) (storico reale), [#27](https://github.com/cavallinilorenzo/progetto-django-uni/issues/27) (catalogo).

Tre sorgenti, tre ruoli distinti.

| Sorgente | Cosa | Versionata | Serve a |
|---|---|---|---|
| **Catalogo** | 100 esercizi, 23 muscoli, 6 gruppi, 9 attrezzi | Sì, `data/catalog/` | Il dominio |
| **Storico reale** | 15 sessioni, 317 serie, 26 giorni | **No**, `.gitignore` | Provare l'import, tarare il realismo |
| **Popolazione sintetica** | 100 utenti, 299.367 serie | **No**, si rigenera | Percentili, classifiche, training del ML |

## Catalogo — già fatto

`data/catalog/{muscle_groups,muscles,equipment,exercises}.csv`, caricati da `load_catalog`, che è **idempotente e atomico**. Dettaglio in `docs/catalogo-esercizi.md`.

Il criterio era la **copertura**, non la quantità: tutti e 23 i muscoli hanno almeno un esercizio, i sei fondamentali ci sono, e **ognuno dei 24 esercizi dello storico reale trova un corrispondente** — altrimenti l'import avrebbe avuto buchi proprio nella demo.

Due divergenze volute da Overload: i `code` dei muscoli restano **identici** (è quello a tenere i dati reimportabili), ma tre `label_it` rimaste in inglese sono tradotte; e il peso a vuoto si sposta dall'esercizio all'**attrezzo**.

**Da aggiungere in fase 1:** la colonna `load_increment_kg` in `equipment.csv` e lo `slug` in `exercises.csv` (o generato dal comando) — vedi `01-modelli.md`, discrepanze 5 e 6.

## Storico reale — piccolo, e sporco al punto giusto

Esportato con `python3 scripts/export_overload.py` in `data/overload-real/`, **fuori dal versionamento**. Formato e volume in `docs/overload-export.md`.

**26 giorni** (2026-08-10 → 2026-09-04), **15 sessioni, 317 serie, 24 esercizi**. È piccolo perché le migrazioni 0006/0007 di Overload avevano azzerato i dati remoti.

**Nessun esercizio supera le 8 sessioni**, quindi i dati reali **non bastano** a validare il rilevamento dello stallo: quello si valida sui sintetici. I reali valgono per due cose, entrambe importanti:

1. **Il caso di prova dell'import** — è lo storico che si carica in demo
2. **Il banco di realismo** — ogni regola di validazione in `03-import-ed-export.md` è misurata su questi dati, non immaginata

La sporcizia utile: 19% di serie non completate, pesi nulli **legittimi** sul corpo libero, 2 sessioni su 15 con `ended_at` assurdo (0 minuti e 25 ore), `set_type`/`intensity`/`is_warmup` di fatto costanti.

## Popolazione sintetica

### Il principio: due numeri per utente

```
massimale = peso corporeo × rapporto dell'esercizio × forza dell'utente × progressione(t) × rumore
```

Da qui discende il risultato che conta: la panca da 140 con lo squat da 60 **non è sorvegliata, è impossibile per costruzione**. Rapporto panca/squat mediano 0,73, zero casi assurdi. Non c'è nessun controllo di plausibilità da scrivere, perché la struttura non li produce.

### Lo stallo è una fase, non un archetipo

Una macchina a **tre stati** per ogni coppia (utente, esercizio). Lo stato nascosto **non finisce in nessun CSV**: se lo facesse, la tentazione di usarlo come etichetta tornerebbe, e sarebbe la circolarità che [ADR-0004](../adr/0004-ground-truth-dello-stallo-dal-futuro-della-finestra.md) rifiuta.

L'**archetipo** (principiante, intermedio, incostante, avanzato, abbandono) vive **solo nel generatore**: non è un campo del modello e l'applicazione non lo conosce. Nessun archetipo «stalla» — è una fase che quasi tutti attraversano.

### Numeri prodotti, e i requisiti che soddisfano

| Misura | Valore | Requisito di |
|---|---|---|
| Utenti | 100 | — |
| Allenamenti | 11.916 | — |
| Serie | **299.367** | — |
| Storico per utente | 0,5 – 17,8 mesi, **4 utenti sotto i 21 giorni apposta** | #17 (lo stato «dati insufficienti» va dimostrato) |
| Esercizi core | 22, **tutti sopra i 20 utenti** | #16 (soglia del percentile) |
| Voti per scheda pubblica | mediana **10** | #33 (mediana ≥ 8) |
| Finestre etichettabili | ≥ 1500 | #17 |
| Quota `stallo` | **30,1%** con orizzonte a 6 | #17, dopo l'emendamento |

La concentrazione sugli esercizi core non è un dettaglio: spargere 100 utenti su 100 esercizi significherebbe **zero esercizi sopra la soglia**, cioè nessun percentile e nessuna classifica in tutta la demo.

### Come si esegue

**Management command `seed_synthetic`, con seed fisso, nessuna fixture committata.** I CSV pesano 13 MB e non entrano nel repo: chi clona rigenera, e la riproducibilità è verificata.

Il prototipo è `scripts/prototype_seed_synthetic.py` — **854 righe di codice usa-e-getta**, stdlib pura, scritto quando il progetto Django non esisteva ancora. **Non è** il management command: la fase 1 lo porta dentro `training/management/commands/seed_synthetic.py`, e il prototipo resta come sorgente del ragionamento. Dettaglio in `docs/generatore-sintetico.md`.

### Gli utenti sintetici si dichiarano

`is_synthetic=True`, **dichiarato nell'interfaccia**. Non sono utenti di prova nascosti: entrano nelle statistiche come tutti gli altri, e questo si dice invece di nasconderlo. Vedi [ADR-0009](../adr/0009-la-popolazione-sintetica-si-dichiara.md).

### L'utente della demo

**`demo064` — Martina Longo**, scelto in anticipo come voleva #17: 17 mesi di storico, 1199 finestre etichettabili. È su questo account che si dimostra la pagina dello stallo, perché quello di Lorenzo è troppo corto.

## Ordine di caricamento

Le tre sorgenti hanno una dipendenza stretta, ed è l'ordine in cui vanno eseguite da un database vuoto:

```
1.  python manage.py migrate
2.  python manage.py load_catalog        # i 100 esercizi devono esistere...
3.  python manage.py seed_synthetic      # ...perché il generatore ci si appoggia
4.  import dello storico reale dal form web, come utente Lorenzo
```

Il passo 4 è **deliberatamente manuale**: è la dimostrazione del requisito «data import», e farlo da comando toglierebbe proprio la cosa da mostrare.
