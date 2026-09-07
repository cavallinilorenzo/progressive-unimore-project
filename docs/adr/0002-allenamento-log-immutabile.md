---
status: accepted
---

# L'allenamento è un log immutabile, la scheda è un piano mutabile

Una `Routine` («scheda») cambia nel tempo: si toglie un esercizio, si alzano le serie obiettivo, la si cancella. Un `Workout` («allenamento») invece è un fatto avvenuto, e non deve mai cambiare retroattivamente perché è cambiato il piano. Perciò l'allenamento tiene una FK **nullable** alla scheda con `on_delete=SET_NULL` più un'**istantanea del nome** (`title`), e i `WorkoutSet` puntano direttamente a `Exercise`, **mai** a `RoutineExercise`. È la stessa risposta che dà lo schema di Overload, adottata qui deliberatamente.

Un allenamento può nascere da una scheda — che al momento della creazione ne **semina** le serie pianificate — ma da quell'istante in poi la scheda non lo governa più.

## Consequences

Il confronto «pianificato vs eseguito» su un allenamento vecchio non è affidabile, perché la scheda nel frattempo può essere cambiata. Il rilevamento dello stallo deve quindi basarsi **solo sulle serie eseguite**, non sugli obiettivi della scheda.
