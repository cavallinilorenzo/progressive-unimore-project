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

## Emendamento (2026-09-07, ratificato in #20): l'orizzonte futuro passa da 4 a 6 sessioni

La regola qui sopra lascia aperto *quanto* futuro guardare. La prima stesura diceva **4 sessioni**, con una tolleranza del **2%** sul massimo di finestra. Il generatore di dati sintetici ([#18](https://github.com/cavallinilorenzo/progetto-django-uni/issues/18)) ha misurato che con quel valore la quota di finestre `stallo` **non è portabile** nella banda 15–35% richiesta: 74,8%, poi 58,3%, poi 45,1% su tre calibrazioni successive del generatore.

La causa non è il generatore, ed è per questo che l'emendamento tocca l'ADR e non i parametri della popolazione. Sono due effetti distinti:

1. **Indistinguibilità reale.** Misurata su serie storiche pure, sotto lo **0,5% di crescita a sessione** uno stallo e una crescita vera non sono separabili — e un atleta intermedio cresce esattamente in quella fascia. Nessuna soglia poteva salvarlo.
2. **Distorsione strutturale del confronto.** Il massimo di una finestra di **6** sessioni veniva confrontato col massimo delle **4** successive: meno estrazioni a destra, quindi un massimo atteso più basso, quindi un bias sistematico *a favore* dell'etichetta `stallo`. Il confronto era truccato dalla sua stessa forma.

**Ratificato: l'orizzonte futuro è di 6 sessioni**, tolleranza invariata al 2%. Risultato misurato: `stallo` al **30,1%**, dentro la banda, senza toccare un solo parametro del generatore.

Non è solo un numero che torna. Su un esercizio allenato circa 1,5 volte a settimana, sei sessioni sono **un mese** di calendario invece di tre settimane, e «in un mese non ho superato il mio massimo» è una definizione di stallo più difendibile — all'orale e per l'utente — di quanto lo fosse la precedente.

**Conseguenza:** la coda non etichettabile di ogni serie storica si allunga da 4 a 6 sessioni. Il dataset di training si riduce ulteriormente, ed è il prezzo accettato: #18 ha comunque verificato ≥ 1500 finestre etichettabili sulla popolazione da 100 utenti.
