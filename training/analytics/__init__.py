"""Le **domande** del motore analitico, una per modulo.

Il confine con `training/querysets.py` è quello scritto nella mappa #96, e ha
una formulazione sola: se ha senso metterci un `.filter()` dopo, è un metodo
del QuerySet; se restituisce righe pronte per un template, è una funzione di
qui. Le **espressioni** stanno nel QuerySet, le **domande** qui.

Quel confine è la ragione per cui `EFFECTIVE_LOAD`, `EPLEY` e `VOLUME` non
compaiono in nessuno di questi moduli come formule: ci arrivano per nome. Una
definizione scritta due volte diverge al primo ripensamento, ed è già successo
una volta in questo progetto — la dashboard calcolava il volume **senza**
carico effettivo e nessun test lo segnalava, perché due copie che si sono
allontanate passano entrambe (#75, sanato in #97).

**Un pacchetto e non un modulo**, al contrario di `training/rankings.py`, che
pure fa lo stesso mestiere. La ragione non è la dimensione: è la regola 2 della
mappa #96, «mai due ticket sullo stesso file». Le analisi di fase 2 arrivano
una per ticket e convergerebbero tutte su un unico `analytics.py`; con un
pacchetto ogni ticket porta il **proprio** file e due sessioni non si toccano.
`rankings.py` resta dov'è perché le due classifiche sono nate insieme, in un
ticket solo, e spostarlo ora sarebbe churn senza un guadagno.

Nessuno di questi moduli conosce HTTP, per la stessa ragione di `rankings.py`:
ciò che va provato riga per riga sono i **numeri**, e provarli attraverso il
client di test vorrebbe dire leggerli dall'HTML, cioè testare il template ogni
volta che si vuole testare una somma.
"""
