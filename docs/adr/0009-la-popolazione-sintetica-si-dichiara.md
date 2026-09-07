---
status: accepted
---

# La popolazione sintetica si dichiara

I ~100 utenti generati da `seed_synthetic` portano un booleano `is_synthetic` sul modello utente, e l'interfaccia li marca come «utente dimostrativo» ovunque il loro nome compaia: classifiche, percentile di forza, schede pubbliche.

Entrano a pieno titolo nella popolazione statistica — il percentile di forza si calcola su tutti gli utenti del database, sintetici e reali insieme, ed è l'unica regola — ma non si spacciano per persone.

L'alternativa era tacere. Sarebbe stata più semplice e avrebbe reso le pagine più pulite, ma una classifica in cui l'unico utente vero è circondato da cento profili inventati **senza che sia scritto da nessuna parte** è precisamente la cosa che un esaminatore attento nota e chiede. A quel punto la risposta è una giustificazione; scritta prima, è una scelta di progetto. Il campo costa quasi niente perché il modello utente è già nostro ([ADR-0003](0003-custom-user-model.md)).

## Consequences

Il modello utente ha un campo in più, che le viste di classifica e percentile devono leggere per rendere l'etichetta. Il campo **non** filtra: nessuna query esclude i sintetici dalla popolazione, o i percentili di [#16](https://github.com/cavallinilorenzo/progetto-django-uni/issues/16) tacerebbero ovunque per mancanza di numeri.

Ne discende anche che l'utente su cui si dimostra la pagina dello stallo è dichiaratamente sintetico, il che è coerente con il fatto che lo storico reale è troppo corto per superare la soglia.
