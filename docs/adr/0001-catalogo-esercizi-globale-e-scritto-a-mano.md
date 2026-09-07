---
status: accepted
---

# Il catalogo esercizi è globale e scritto a mano

Il motore analitico di `Progressive` calcola percentili di forza e classifiche confrontando utenti diversi sullo stesso esercizio, il che è possibile solo se «panca piana» è **una sola riga `Exercise`** condivisa da tutti. Abbiamo quindi scartato la libreria personale per utente che usa Overload (dove `exercises.user_id` è `not null`), e con essa anche l'ipotesi ibrida di un catalogo condiviso più esercizi custom: un esercizio custom sarebbe invisibile a ogni classifica, cioè un buco silenzioso nella funzione principale dell'app. Chi ha bisogno di un esercizio mancante lo chiede, e lo si aggiunge dall'admin Django.

## Considered Options

La ricerca [#12](https://github.com/cavallinilorenzo/progetto-django-uni/issues/12) aveva concluso di importare `yuhonas/free-exercise-db` (Unlicense, 678 voci utili). L'abbiamo ribaltata, e proprio sulla base di quello che quella ricerca ha misurato: la mappatura delle etichette del dataset sui nostri 23 muscoli richiede un'euristica sul nome che risolve l'81% dei 306 casi ambigui, **più una tabella di override scritta a mano per i 57 residui** — e i 678 nomi sono in inglese, mentre l'interfaccia è in italiano. Scrivere a mano **~80–100 esercizi** già in italiano e già taggati costa meno di quell'euristica più la traduzione, e non lascia niente da difendere all'orale.

L'argomento decisivo però è statistico, non di costo: 678 esercizi spalmati su ~100 utenti sintetici diluiscono i dati al punto che ogni percentile diventa poco significativo, mentre un catalogo stretto e curato li concentra. `free-exercise-db` resta utile come lista di controllo della copertura, non come sorgente.

## Consequences

Il patch di nebbia «nomi italiani degli esercizi» sparisce: li scriviamo direttamente in italiano. Il catalogo diventa un artefatto versionato del repo, e va scritto prima di poter generare i dati sintetici.
