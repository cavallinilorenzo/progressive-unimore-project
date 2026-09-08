---
status: accepted
---

# Il nome pubblico di una riga si calcola, non si memorizza

L'import è idempotente grazie a `external_id`, e la regola che lo tiene onesto è che quel campo sia **nullable**: un allenamento nato dentro Progressive non ha nessun identificativo esterno e non deve fingerne uno ([03-import-ed-export.md](../spec/03-import-ed-export.md)). Finché Progressive sapeva solo *leggere* quel formato la regola non costava niente.

L'export la mette in crisi. Un CSV ha bisogno di un `id` su ogni riga — è la colonna su cui l'import deduplica — ma le righe che l'export porta fuori sono in maggioranza righe nate qui, con `external_id` nullo. Sulla popolazione sintetica sono **tutte**: 311 allenamenti e 7.858 serie dell'utente dimostrativo, nessuno dei quali è mai stato importato.

Quindi ogni riga ha un **nome pubblico**: l'identificativo con cui compare in un file. Per una riga importata è il suo `external_id`, cioè il nome che aveva nel sistema di provenienza. Per una riga nata qui è un UUID **derivato dalla sua chiave primaria** (`uuid5` su un namespace fisso di Progressive), che ha le due sole proprietà che servono: è lo stesso a ogni export, quindi il file è stabile e il reimport riconosce la riga; e non viene **mai scritto in database**, quindi `external_id` resta nullo e continua a significare esattamente ciò che significava — «questa riga viene da fuori, e là si chiamava così».

L'import, dal canto suo, riconosce i due nomi come la stessa cosa: un `id` che il database già conosce è un `id` da saltare, che arrivi da un `external_id` memorizzato o dal nome pubblico calcolato di una riga dell'utente.

## Alternative scartate

**Timbrare `external_id` al momento dell'export.** Una riga di codice in meno e l'idempotenza esatta, ma è precisamente ciò che la spec vieta: dopo un export, un allenamento registrato a mano avrebbe un identificativo esterno pur non essendo mai stato importato da nessuna parte, e il campo smetterebbe di distinguere le due provenienze. In più farebbe **scrivere una GET**, dove tutto il resto del progetto ha già deciso il contrario — l'uscita è un POST, il voto è un POST, «un effetto non sta dietro una richiesta di sola lettura».

**Dare un `external_id` a ogni riga alla nascita.** Elimina il caso, ma cancella la distinzione insieme al problema: la colonna diventerebbe una seconda chiave primaria, che è l'alternativa già scartata quando si è deciso di non usare l'UUID come PK.

**Esportare solo le righe importate.** Rende il giro dimostrabile e l'export inutile: chi si iscrive oggi e registra i suoi allenamenti a mano — cioè l'utente normale — scaricherebbe un file vuoto.

**Non esportare affatto.** È lo stato da cui si parte, ed è l'obiezione che ha riorientato l'import: un formato che l'app sa solo leggere è il formato di un'altra app, e un estraneo che si iscrive trova un import che non può usare.

## Consequences

Il nome pubblico vive quanto la **chiave primaria** che lo genera. Un database ricreato da zero riassegna i numeri e quindi riassegna i nomi: un file esportato prima e reimportato dopo verrebbe riconosciuto come già presente pur non essendo la stessa riga. È un limite dei **backup**, non dell'import — l'export non è un formato d'archivio, è il modo in cui Progressive produce il formato che sa leggere — e va dichiarato invece che nascosto.

L'import ha ora bisogno di sapere **chi** sta importando già in lettura, non solo in scrittura: i nomi pubblici da riconoscere sono quelli delle righe dell'utente. Non è un'incrinatura della regola per cui l'identità viene solo da `request.user` — è la stessa regola applicata prima.

`external_id` resta nullo per tutte le righe nate in-app, e c'è un test che lo verifica **dopo** un giro export → import completo: è l'unico modo di accorgersi se un domani qualcuno decidesse di timbrarlo.
