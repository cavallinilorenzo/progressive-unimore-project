---
status: accepted
---

# I valori derivati non si materializzano: restano calcolati nell'ORM

Volume, massimale stimato, carico effettivo, forza relativa, punteggio sociale: nessuno di questi è una colonna. Sono **espressioni dell'ORM**, calcolate a ogni query da `training/querysets.py` e dalle funzioni di `training/analytics/`, su 296.724 serie.

L'alternativa — colonne materializzate su `WorkoutSet`, `Workout` o `User`, riempite da un `save()` o da un segnale — è la scelta che qualunque manuale di ottimizzazione suggerisce quando i record diventano tanti. È stata tenuta aperta per tutto il progetto, con una condizione precisa scritta in `docs/spec/00-indice.md`: si riapre **solo** se una misura sui 296.724 record mostra query lente, **dopo** aver scritto le query, non prima.

La misura è stata fatta (#102) ed è in [docs/misure/tempi-query.md](../misure/tempi-query.md). **Sette pagine su sette in banda verde**, con la soglia — 300 ms verde, 1 s rosso — scritta e committata *prima* che una sola misura girasse. La pagina più lenta sta a 234 ms; la più lenta fra quelle costruite dal motore analitico sta a 46 ms. Nessuna pagina cambia numero di query fra un utente da 11.159 serie e uno da 75.

La condizione non si è verificata, quindi la decisione è quella di default: **non si materializza**, e la questione non si riapre.

## Consequences

**Ciò che si conserva è il contenuto del progetto.** Materializzare significa spostare il calcolo dal database all'applicazione: `Window`, `Subquery` con `OuterRef`, `PERCENT_RANK`, le espressioni condizionali sul carico effettivo diventerebbero colonne riempite da codice Python. La fase 2 esiste per mostrare che il database sa fare questi conti; materializzarla la svuota. Sarebbe stato un prezzo pagato per una lentezza mai osservata.

**Una definizione resta in un posto solo.** È la ragione strutturale, indipendente dai tempi, ed è la lezione di #75 e #97: una colonna materializzata è una seconda copia di una regola, che diverge al primo ripensamento. La dashboard che calcolava il volume senza carico effettivo (#97) è già successa una volta con due *espressioni*; con una colonna il ripensamento non si vedrebbe affatto, perché il vecchio valore resterebbe scritto.

**Il costo lo paga la lettura, e per questo progetto è il verso giusto.** Ogni pagina ricalcola, ma il ricalcolo costa decine di millisecondi e la scrittura resta banale. Materializzando si invertirebbe: scritture più care, e il problema nuovo dei **backfill** — cambiare la formula di Epley o la soglia delle 12 ripetizioni vorrebbe dire riscrivere 296.724 righe, mentre oggi è la modifica di una costante.

**Il limite si dichiara.** Questa decisione vale per **SQLite in locale, 100 utenti, 296.724 serie, una pagina alla volta**. Non è una tesi generale sul fatto che materializzare non serva mai: è la constatazione che a questa scala non serve. Con utenti concorrenti veri, o con due ordini di grandezza di dati in più, la misura andrebbe rifatta — e la strada resterebbe aperta, perché una colonna derivata si aggiunge dopo, mentre un progetto costruito su colonne materializzate non si converte facilmente all'indietro.

**Se un giorno servisse davvero**, l'ordine dei rimedi è scritto e non parte dalla materializzazione: prima l'indice mancante, poi il `select_related`, poi la query riscritta. La colonna è l'ultima carta, non la prima.

## Il ritrovamento che rende la decisione più solida, non meno

La pagina più lenta del progetto — la classifica di forza, 234 ms — non è lenta per l'analisi. Scomposta query per query, **176 ms su 234 sono la query che riempie il menu a tendina**, cioè quella che decide quali esercizi hanno abbastanza popolazione per meritare una classifica. La classifica vera e propria — `RANK()` su una finestra, forza relativa, 12.352 serie su 100 utenti — costa **9 ms**.

Vale per due ragioni. La prima è che indebolisce l'argomento a favore della materializzazione proprio dove sembrava più forte: il numero grande non veniva dai valori derivati. La seconda è che 176 ms è un numero che *invita* a ottimizzare, e sta in banda verde: la soglia scritta prima ha impedito di trasformare una misura in un cantiere. È l'ordine — soglia, poi numeri — che ha prodotto questa astensione, e sarebbe bastato invertirlo per perderla.
