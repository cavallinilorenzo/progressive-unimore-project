---
status: accepted
---

# L'abbinamento dei nomi in import è interattivo, e si ricorda

Il catalogo esercizi di `Progressive` è globale, scritto a mano e chiuso: nessuno può crearne di propri ([ADR-0001](0001-catalogo-esercizi-globale-e-scritto-a-mano.md)). Un file importato, però, porta i nomi del sistema che l'ha prodotto, e quelli non combaciano. Misurato sui dati veri: dei **24 nomi** dello storico di Overload contro i **100** del catalogo, la normalizzazione automatica — casefold, apostrofi tipografici, spazi, accenti — ne risolve **quasi zero**. `RDL` sta per «Stacco rumeno con bilanciere», `Polpacci su leg press` per «Calf raise al leg press», `Leg extention` contiene un refuso. Alcuni sono ambigui **anche per un umano**: `d'Annunzio crunch` può essere «Crunch a terra» o «Crunch ai cavi».

Quindi l'abbinamento **non è un problema di stringhe**: è una scelta, e la fa l'utente. L'anteprima dell'import presenta i nomi non riconosciuti in una tabella, ognuno con una `<select>` del catalogo accanto; l'utente sceglie, conferma, e la scelta viene **memorizzata** in `ExerciseAlias` — una riga per `(utente, nome libero)` — così il secondo import dello stesso file non ne richiede nessuna.

## Alternative scartate

**Un file di alias versionato nel repo.** Ventiquattro righe scritte a mano risolvono il caso di Lorenzo e nessun altro: chiunque altro carichi un file si trova davanti a un import che fallisce riga per riga senza via d'uscita. Trasforma una funzione in uno script travestito.

**Creare al volo l'esercizio mancante.** Vietato da ADR-0001, e per il motivo che quell'ADR spiega: un esercizio creato al volo è invisibile a ogni percentile e a ogni classifica, quindi importare dati produrrebbe silenziosamente dati che non partecipano a nessuna analisi — il peggior modo di fallire, perché non si vede.

**Solo il matching automatico, e le righe non risolte si scartano.** Sui dati reali scarterebbe quasi tutto.

## Consequences

L'import guadagna un modello che il dominio non aveva, `ExerciseAlias`, che è infrastruttura e non un'entità del dominio: non entra nel conteggio «5–6 modelli correlati» della traccia, esattamente come non ci entrano `Muscle`, `MuscleGroup` ed `Equipment`.

L'anteprima smette di essere una schermata di sola lettura e diventa un **form**: è il punto in cui l'import chiede qualcosa all'utente invece di limitarsi a informarlo. Il costo è un `formset` e uno stato in più fra le tre viste; il guadagno è che l'import funziona per un utente qualsiasi, che è ciò che lo distingue da uno script di seeding.

Il matching automatico non sparisce, ma cambia ruolo: da meccanismo di risoluzione a **suggerimento**, che preseleziona la voce più probabile nella `<select>` e va bene anche quando sbaglia, perché c'è un umano a correggerlo.
