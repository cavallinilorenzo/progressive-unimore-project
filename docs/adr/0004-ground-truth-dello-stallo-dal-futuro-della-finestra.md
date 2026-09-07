---
status: accepted
---

# Il ground truth dello stallo viene dal futuro della finestra, non dal generatore

Il rilevamento dello stallo è l'unica feature di machine learning di `Progressive`, e ha un problema che precede la scelta del modello: **da dove vengono le etichette**.

Lo storico reale non può fornirle. L'export di Overload copre 26 giorni e nessun esercizio supera le 8 sessioni, perché le migrazioni `0006`/`0007` avevano azzerato i dati remoti: su tre settimane un carico che sale è indistinguibile dal semplice adattamento iniziale. Non c'è niente da etichettare a mano.

La strada ovvia sarebbe far dichiarare al generatore di dati sintetici quali atleti ha messo in stallo, e usare quel flag come etichetta. È **circolare**: il modello imparerebbe a invertire il generatore, e la metrica misurerebbe la coerenza del generatore con se stesso, non la capacità di riconoscere uno stallo.

Perciò l'etichetta si ricava **dal futuro della finestra**: una finestra è `stallo` se, nelle sessioni immediatamente successive, il massimale stimato non supera il massimo raggiunto dentro la finestra oltre una soglia di tolleranza. Il modello vede solo la finestra; l'etichetta viene da dati che non ha visto. Le feature sono vincolate a restare interne alla finestra, altrimenti l'etichetta rientra dalla porta di servizio.

## Consequences

Le ultime sessioni di ogni serie storica non sono etichettabili, perché non hanno un futuro: il dataset di training è più piccolo di quanto la mole dei dati suggerisca.

La stessa identica regola gira sui dati reali e su quelli sintetici. Sui reali non produce quasi nessuna finestra etichettabile — ed è un risultato onesto da mostrare, non un fallimento da nascondere.

Il generatore di dati sintetici eredita un requisito preciso: deve produrre abbastanza finestre etichettabili, con una quota di stalli né trascurabile né dominante, e includere i casi difficili (piatto-poi-riparte, rumoroso-ma-in-crescita, deload volontario). **Non deve esporre il proprio stato interno**: se lo facesse, la tentazione di usarlo come etichetta tornerebbe.

Poiché l'etichetta è una previsione sul futuro, il modello va confrontato con un baseline a soglia («nessun record recente»). Se non lo batte, si spedisce il baseline: chiamare «machine learning» una regola travestita è un rischio all'orale, non un punto.
