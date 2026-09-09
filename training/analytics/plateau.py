"""Il rilevamento dello stallo — oggi una regola a soglia, domani un modello.

Questo file nasce **vuoto tranne un numero**, e nasce così apposta.

`docs/spec/05-coach-e-stallo.md` impone alla fase 4 un **termine di paragone
obbligatorio**: la regola a soglia «nessun record nelle ultime *N* sessioni
della finestra», contro cui il modello dovrà misurarsi. Il numero che va
all'orale non è l'F1 del modello, è la **differenza fra modello e baseline**.

Ma la spec non dà *N*. E un baseline il cui parametro si sceglie *dopo* aver
visto come si comporta il modello non è un termine di paragone: è un avversario
truccato. Basta provare 2, 3 e 4 e tenere quello che perde meglio, e nessuno,
all'orale, potrebbe distinguere quella scelta da questa.

Quindi *N* si sceglie **adesso**, prima che esista qualunque finestra,
qualunque modello e qualunque script di confronto, e in un **commit suo** — il
`git log` è l'unica prova dell'ordine che una dichiarazione a posteriori non
può dare. È il trucco di
[#102](https://github.com/cavallinilorenzo/progetto-django-uni/issues/102),
dove la soglia dei tempi di pagina fu committata prima di misurare un solo
millisecondo.
"""

#: Le sessioni senza record che fanno scattare il baseline a soglia.
#:
#: **Tre**, cioè **metà della finestra minima** da 6 allenamenti
#: (`docs/spec/05-coach-e-stallo.md`, §«Definizione operativa»). Il numero è
#: scelto alla cieca, e la ragione della scelta è tutta qui:
#:
#: - **1 o 2 sarebbero rumore.** Un massimale stimato oscilla di suo fra una
#:   sessione e l'altra; due sedute senza record sono una settimana storta, non
#:   uno stallo, e il baseline direbbe «stallo» quasi sempre.
#: - **5 o 6 sarebbero l'intera finestra.** «Nessun record in tutte e sei le
#:   sessioni» non è una soglia: è la definizione stessa di finestra piatta, e
#:   il baseline diventerebbe una tautologia con un recall vicino a zero.
#: - **Metà finestra è l'unico punto che non richiede di aver visto i dati.**
#:   Non c'è niente di magico nel 3: c'è che è il centro dell'unico intervallo
#:   che la spec fissa, e sceglierlo non richiede di sapere nulla su come si
#:   distribuiscono gli stalli.
#:
#: Se la fase 4 trovasse che un altro *N* rende il baseline più forte, quella è
#: **un'informazione, non una correzione**: si dichiara, e il confronto resta
#: quello contro questo numero qui.
SESSIONI_SENZA_RECORD_PER_STALLO = 3
