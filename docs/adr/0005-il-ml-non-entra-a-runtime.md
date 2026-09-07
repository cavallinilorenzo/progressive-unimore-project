---
status: accepted
---

# Il machine learning si addestra offline; a runtime entrano solo i coefficienti

Il progetto d'esempio del corso IWC ha **Django come unica dipendenza**, e la regola adottata per `Progressive` è di seguire ciò che il prof usa. `scikit-learn` — che si porta dietro numpy e scipy — sarebbe la deviazione più vistosa dell'intero progetto.

Il compromesso: `scikit-learn` è una dipendenza di **sviluppo**. L'addestramento e la valutazione avvengono fuori dal ciclo di richiesta; dentro l'applicazione entrano i **coefficienti appresi, come costanti**, accanto a un'inferenza scritta in Python puro. Le feature si calcolano nell'ORM, dove si calcola tutto il resto del motore analitico.

Il risultato non è persistito: **non esiste un modello Django per l'esito dello stallo**. La traccia d'esame conta 5–6 modelli correlati, e una tabella che è in realtà una cache confonde proprio la lettura che deve fare chi valuta. Cache e materializzazione si valutano dopo aver misurato una lentezza vera, non prima.

## Consequences

In esecuzione `Progressive` resta «Django e basta», allineato al progetto d'esempio, e l'affermazione «ho addestrato un modello e l'ho valutato così» resta vera e verificabile.

I coefficienti nel codice sono numeri magici finché non si dice da dove vengono: lo script di addestramento e i risultati della valutazione fanno parte del progetto, non sono scarti.

Il machine learning diventa l'**ultima cosa tagliabile** senza toccare nient'altro: un modulo di servizio che nessun modello, nessuna migrazione e nessuna dipendenza di runtime tiene in ostaggio.

Riaddestrare non è un'operazione che l'applicazione sa fare: è un passo manuale che finisce in un commit.
