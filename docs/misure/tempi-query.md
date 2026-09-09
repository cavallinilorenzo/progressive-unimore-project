# La misura dei tempi di query, e il verdetto sui valori derivati

Questo documento risponde alla questione che `docs/spec/00-indice.md` ha
rinviato fin dall'inizio: **i valori derivati — volume, massimale, punteggi —
vanno materializzati in colonne, o si continuano a calcolare nell'ORM a ogni
query?**

La spec la rinviava con una formulazione precisa:

> Oggi si calcolano nell'ORM a ogni query, per scelta, ed è proprio ciò che il
> progetto deve dimostrare. La decisione si riapre **solo** se la misura sui
> 296.724 record al termine della fase 2 mostra query lente — **dopo** averle
> scritte, non prima.

Le query sono scritte (mappa #96, sei analisi su tre superfici). Questo è il
«dopo».

---

## La soglia, scritta prima dei numeri

**La parte di questo documento che conta è questa sezione, ed è stata scritta e
committata prima che una sola misura fosse eseguita** (si verifica nel `git
log`: il commit che introduce metodologia e soglia precede quello che aggiunge
la tabella dei risultati). Senza questa precauzione il verdetto lo detterebbe la
sensazione del momento: si guardano i numeri, e poi si decide che «lento»
significa qualunque cosa i numeri dicano.

### Sui tempi

Si cronometra **la richiesta intera** — dalla `GET` alla risposta renderizzata,
quindi view più query più template — e non la sola query ORM. La query più
veloce del mondo dentro una pagina che ci mette due secondi non è una buona
notizia, e ciò che conta è quello che vede chi guarda lo schermo.

Tre bande, decise ora:

| Banda | Tempo mediano | Significato |
| --- | --- | --- |
| 🟢 | **< 300 ms** | La pagina è a posto. Non se ne parla più. |
| 🟡 | **300 ms – 1 s** | Percepibile. Si annota, **non** riapre nulla. |
| 🔴 | **> 1 s** | «Lento» nel senso di `00-indice.md`: il ticket deve produrre un rimedio. |

Un secondo è la soglia oltre cui una pagina smette di sembrare istantanea a chi
guarda uno schermo condiviso, ed è larga abbastanza da non far scattare
l'allarme per una macchina che quel giorno sta compilando altro.

### Sul numero di query

Il tempo non basta: una pagina che rende in 40 ms con 200 query è un guasto
diverso ma reale, ed è la guardia di #86 e #70.

Qui però **la soglia non è un numero assoluto**. Un tetto tipo «massimo 25
query» è una cifra scelta a occhio: la dashboard ne fa 12 e va benissimo, una
lista paginata potrebbe farne trenta legittimamente. Il criterio è invece
l'**invarianza**:

> Il numero di query di una pagina non deve crescere né con lo storico
> dell'utente, né con la popolazione del database.

Un N+1 è un guasto a 15 query come a 200. Il numero assoluto si registra
comunque nella tabella, come **dato**, non come test.

---

## La metodologia

Lo strumento è `scripts/misura_tempi.py`, uno script una tantum, non un test.

- **Database vero.** Si misura contro `db.sqlite3` — 100 utenti, 296.724 serie,
  generate da `seed_synthetic` — e non contro il database di test, che è vuoto e
  misurerebbe il nulla. Il file non è versionato (è in `.gitignore`), quindi lo
  script prende il percorso con `--db`.
- **`DEBUG = False`.** Obbligatorio: con `DEBUG = True` Django accumula in
  memoria ogni query eseguita, e i tempi risultano falsi **in peggio**.
- **Warm-up scartato.** La prima richiesta paga import, compilazione dei
  template e cache fredda del sistema operativo: non è ciò che si vuole sapere.
- **Mediana di 10 ripetizioni**, non la media: un singolo scatto del disco non
  deve decidere un verdetto.
- **Utente della demo.** `cavallinilorenzo` (pk 64) — 24 mesi dichiarati, 443
  allenamenti, 11.159 serie. Le pagine si guardano su di lui perché una misura
  su un account quasi vuoto non è una misura.

### Le pagine misurate

Sette, e ognuna ha una ragione per essere nell'elenco:

| Pagina | Perché |
| --- | --- |
| `/` (dashboard) | La prima pagina che si apre all'orale; porta heatmap e costanza |
| `/analisi/` | Le due analisi di volume, taglio settimanale (default) |
| `/analisi/?periodo=mese` | Il taglio annuale di #106: dodici mesi invece di dodici settimane |
| `/esercizi/panca-piana-con-bilanciere/` | Il dettaglio più caricato: 585 serie, con A3 + A4 + percentile |
| `/allenamenti/` | 443 allenamenti: l'unica lista lunga, dove un N+1 si nasconderebbe meglio |
| `/classifiche/forza/` | Cresce con i **100 utenti**, non con lo storico personale |
| `/classifiche/schede/` | Come sopra, sull'altra classifica |

Le due classifiche sono fase 1 e già chiuse (#76), ma entrano lo stesso: sono le
uniche query che toccano *tutti* gli utenti, quindi le uniche il cui costo
cresce con la popolazione.

### La verifica di invarianza

Il conteggio delle query si misura **due volte per pagina**: sull'utente della
demo (11.159 serie) e su un utente dallo storico molto più corto. Se il numero
cambia, la pagina ha un N+1 — indipendentemente da quanto è veloce.

---

## I risultati

<!-- compilato dall'esecuzione dello script; vedi il commit successivo -->

## Il verdetto

<!-- compilato dopo i risultati -->
