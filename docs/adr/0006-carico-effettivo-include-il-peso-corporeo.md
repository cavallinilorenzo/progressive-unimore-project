---
status: accepted
---

# Il carico effettivo include il peso corporeo sul corpo libero

Il volume è carico × ripetizioni, ma sul corpo libero il carico registrato è legittimamente **zero** — l'export dei dati reali ([#13](https://github.com/cavallinilorenzo/progetto-django-uni/issues/13)) lo ha confermato, non è sporcizia da ripulire. Con la formula ingenua ogni trazione e ogni piegamento pesano zero, e nella distribuzione del volume per gruppo muscolare la schiena semplicemente **sparisce**: una schermata che dice a un utente di allenare di più una cosa che sta già allenando. Definiamo quindi il **carico effettivo** come `weight + body_mass_kg` quando l'attrezzo è il corpo libero, e `weight` altrimenti — un `Case`/`When` dentro l'espressione ORM, quindi ancora interamente calcolato nel database.

## Considered Options

**Escludere gli esercizi a corpo libero dal volume** era più semplice, ma sposta il problema invece di risolverlo: la schiena resta sotto-rappresentata, e per giunta in modo invisibile.

**Accettare lo zero** significa che il volume misura «peso spostato dall'esterno», che è una definizione difendibile in astratto e inutile in pratica: il motore analitico esiste per dire all'utente cosa sta trascurando.

## Consequences

Il volume di un utente che si allena molto a corpo libero è strutturalmente più alto di quello di un utente di pari impegno che usa i bilancieri, perché il peso corporeo è un moltiplicatore grande. Il volume resta quindi confrontabile **nel tempo per lo stesso utente**, che è l'uso che ne facciamo, ma **non fra utenti**: il confronto fra persone passa dalla forza relativa e dal percentile, mai dal volume. Nessuna classifica può usare il volume come criterio.

Il vantaggio collaterale: le trazioni zavorrate vengono giuste gratis, perché sono peso corporeo più carico aggiunto, che è esattamente la formula.
