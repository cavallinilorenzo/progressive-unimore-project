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

Misurati il **9 settembre 2026**, su `db.sqlite3` da 29,7 MB — 100 utenti,
296.724 serie — con l'utente della demo (11.159 serie) e, per l'invarianza,
`martina.gallo` (75 serie). Macchina: portatile, SQLite locale, `DEBUG = False`.

| Pagina | Mediana | min | max | Query | Query (75 serie) | Banda |
| --- | ---: | ---: | ---: | ---: | ---: | :---: |
| Dashboard | **12,1 ms** | 11,8 | 12,6 | 12 | 12 | 🟢 |
| `/analisi/` (settimane) | **7,5 ms** | 7,3 | 8,7 | 6 | 6 | 🟢 |
| `/analisi/?periodo=mese` | **17,4 ms** | 17,2 | 18,3 | 6 | 6 | 🟢 |
| Dettaglio esercizio (585 serie) | **38,4 ms** | 38,0 | 42,6 | 10 | 10 | 🟢 |
| Storico allenamenti (443) | **46,0 ms** | 43,5 | 54,1 | 3 | 3 | 🟢 |
| Classifica forza | **234,3 ms** | 227,5 | 249,6 | 5 | 5 | 🟢 |
| Classifica schede | **6,1 ms** | 5,7 | 6,9 | 6 | 6 | 🟢 |

**Sette pagine su sette in banda verde.** La più lenta sta a 234 ms, cioè a un
quarto della soglia rossa e sotto anche quella gialla.

**Invarianza: rispettata ovunque.** Nessuna pagina cambia numero di query fra un
utente da 11.159 serie e uno da 75. Le sei analisi costano un numero di query
fisso, e quel numero è piccolo: la dashboard ne fa 12 con dentro heatmap,
costanza e volume; `/analisi/` ne fa 6 con due grafici; lo storico ne fa 3 su
443 allenamenti.

### Il ritrovamento: la pagina più lenta non è lenta per l'analisi

I 234 ms della classifica di forza sembrano dire «l'analisi più cara è la
classifica», ed è la conclusione che una misura frettolosa avrebbe scritto.
Scomponendo la pagina query per query:

| Query | Tempo |
| --- | ---: |
| Sessione e utente | ~0 ms |
| **`esercizi_con_classifica()` — il menu a tendina** | **176,0 ms** |
| `COUNT` per la paginazione | 8,0 ms |
| La classifica vera e propria | 9,0 ms |

**Tre quarti del tempo della pagina più lenta del progetto sono il selettore**,
non la classifica: è la query che scandisce tutte le serie per decidere quali
esercizi hanno abbastanza popolazione da meritare una classifica (`#76`, fase
1). La classifica in sé — `RANK()` su una finestra, forza relativa, 12.352
serie su 100 utenti — costa **9 ms**.

Questo non produce un'azione, e il fatto che non la produca è il motivo per cui
la soglia era scritta prima: 176 ms è un numero che *invita* a ottimizzare, ma è
dentro la banda verde, e la banda verde dice «non se ne parla più». Ottimizzarlo
sarebbe lavoro fatto per la soddisfazione di far scendere un numero, non per un
problema che qualcuno ha.

---

## Il verdetto

**I valori derivati non si materializzano. La questione rinviata da
`00-indice.md` si chiude qui, e non si riapre.**

La condizione della spec era esplicita — si riapre *solo* se la misura mostra
query lente — e la misura non le mostra. Il caso peggiore del database, su
296.724 serie, sta a 234 ms; il caso peggiore delle *analisi* sta a 46 ms.

Vale la pena dire cosa si sarebbe perso accettando la materializzazione senza
misurare, perché è il senso dell'ordine che il ticket ha imposto:
materializzare volume, massimale e punteggi significa **spostare il calcolo
dal database all'applicazione**, cioè rinunciare esattamente a ciò che questo
progetto vuole dimostrare. Le `Window`, le `Subquery` con `OuterRef`, il
`PERCENT_RANK`, le espressioni condizionali sul carico effettivo diventerebbero
colonne riempite da codice Python, e la fase 2 non avrebbe più niente da
mostrare. Sarebbe stato un prezzo pagato per una lentezza mai osservata.

L'esito ha anche il valore contrario: dice che il calcolo nel database **non è
stato un atto di fede**. È stato misurato, con una soglia scritta prima, e ha
retto.

### Cosa resta come guardia

I *tempi* di questa tabella non diventano un test: un test a tempo fallisce
quando la macchina è occupata, e un test che fallisce a caso è un test che si
impara a ignorare. Restano qui, datati, come la fotografia di un database su una
macchina.

I *conteggi* di query sì, perché sono deterministici. `#102` ne aggiunge due a
quelle che già c'erano (dashboard, catalogo, classifiche, formset): l'invarianza
di `/analisi/` in **entrambi** i tagli, e quella del dettaglio esercizio, dove
A3, A4 e il percentile si sommano sulla stessa pagina. Vivono in
`training/tests.py`, accanto alle altre.

La decisione, con le sue conseguenze, è in
[ADR-0012](../adr/0012-valori-derivati-non-materializzati.md).
