---
status: accepted
---

# Il coach dice una cosa sola, e ogni cosa che dice ha una query dietro

Il coach è l'asse portante di `Progressive`: la app non mostra grafici, dice cosa fare. Questo lo espone a due modi di fallire, opposti fra loro, ed entrambi si pagano all'orale.

Il primo è **dire troppo**. Stallo, squilibrio, calo di costanza e suggerimento del carico possono scattare tutti insieme sullo stesso utente; un riquadro che li elenca tutti e quattro non è un coach, è un secondo cruscotto. Perciò i consigli hanno una **priorità costante per tipo** — costanza, squilibrio, stallo, carico — e nella dashboard ne compare **uno solo**. La priorità è un intero cablato sul tipo e non un punteggio calcolato: un punteggio sarebbe una terza cosa da giustificare, e nessuno dei suoi pesi sarebbe misurato.

Il secondo è **dire cose non giustificabili**. Davanti a uno stallo le raccomandazioni disponibili sono quattro: cambiare esercizio, scaricare, aumentare la frequenza, aumentare le ripetizioni a parità di carico. Tre sono state scartate. *Cambiare esercizio* rompe la serie storica su cui girano il rilevamento dello stallo, i PR e i percentili — il consiglio distruggerebbe il dato che lo ha prodotto. *Aumentare la frequenza* non poggia su nessuna query: non abbiamo niente che misuri il recupero, e [ADR-0004](0004-ground-truth-dello-stallo-dal-futuro-della-finestra.md) ha già rifiutato di inventarlo. *Aumentare le ripetizioni* non è una risposta allo stallo, è la doppia progressione ordinaria. Resta **una sola azione**: una singola sessione al 90% del massimo di finestra, dichiarata come euristica e non come prescrizione fisiologica.

Da qui la regola che governa tutto il perimetro: **ogni consiglio ha dietro una query, e un'osservazione che non si traduce in un'azione non è un consiglio**. È lo stesso criterio che in [#16](https://github.com/cavallinilorenzo/progetto-django-uni/issues/16) ha tagliato tre analisi su nove, applicato all'altra metà del progetto. Ne discende anche la soglia dello squilibrio: un gruppo muscolare **assente** da 28 giorni è un fatto verificabile, mentre «le tue spalle sono sotto la quota ideale» richiederebbe una ripartizione ideale che nessuno ha misurato.

## Consequences

Il coach **non ha modelli propri e non persiste nulla**: è il servizio `analytics/coach.py`, che riusa il custom `QuerySet` di `WorkoutSet`. Le due query che gli servono in proprio — la doppia progressione e lo squilibrio per assenza — restano nel servizio e **non entrano nel catalogo delle analisi**: sono un `Max` e un `Count`, non superano il secondo asse di ammissione di #16, che chiede ORM che il corso non ha insegnato. Il catalogo resta a sei voci.

Il consiglio di carico legge il target dalla scheda dell'**ultimo allenamento** che ha registrato quell'esercizio, e ne legge il valore **corrente**. [ADR-0002](0002-allenamento-log-immutabile.md) avverte che il confronto «pianificato vs eseguito» non è affidabile sul passato, perché la scheda nel frattempo può essere cambiata — ma qui non si giudica il passato, si propone la **prossima** sessione, e a governarla è il piano in vigore adesso. La regola vale finché il coach guarda avanti; il giorno in cui volesse dire «hai rispettato la scheda?» quella domanda ricadrebbe sotto ADR-0002 e non sarebbe rispondibile.

Serve un campo nuovo, `Equipment.load_increment_kg`, sul modello che c'è già: nessun modello in più, e il conteggio 5–6 della traccia resta intatto.

Il prezzo accettato è che il coach **taccia** su cose vere. Un utente in stallo su tre esercizi vede un solo consiglio; un utente con uno squilibrio e un calo di costanza non sente parlare dello squilibrio finché non torna ad allenarsi. È deliberato: la cosa più utile che un coach fa è scegliere.
