# CONTEXT — Progressive

Glossario del dominio di `Progressive`, l'applicazione web Django per l'esame di IWC 2026.

Regola di lingua fissata per il progetto: **il codice e i modelli sono in inglese, l'interfaccia è in italiano.** Ogni voce qui sotto dà entrambi i nomi. Quando un documento, un titolo di issue o un nome di test nomina un concetto del dominio, usa il termine di questa tabella e non un sinonimo.

Questo file è **solo un glossario**. Le decisioni sul perché di un modello stanno in `docs/adr/`; il dettaglio dei campi e dei vincoli sta nella risoluzione del ticket che lo ha deciso.

## Modelli del dominio

### Exercise — «Esercizio»

Un movimento con un nome, un muscolo primario e un attrezzo: «Panca piana con bilanciere», «Curl con manubri». Il catalogo è **globale**: esiste una sola riga `Exercise` per esercizio, condivisa da tutti gli utenti, e nessuno può crearne di propri. È questa condivisione a rendere possibili i percentili e le classifiche — due utenti sono confrontabili sulla panca piana solo se «panca piana» è la stessa riga per entrambi. Il catalogo è scritto a mano, in italiano, e si popola da fixture. Vedi [ADR-0001](docs/adr/0001-catalogo-esercizi-globale-e-scritto-a-mano.md).

### Routine — «Scheda»

Il **piano**: quali esercizi fare, in che ordine, con quante serie e quante ripetizioni obiettivo. Una scheda appartiene a un utente ed è **mutabile** — si modifica quando il programma di allenamento cambia. Una scheda può essere resa **pubblica** (`is_public`), e solo in quel caso è votabile dagli altri utenti.

### RoutineExercise — «Esercizio in scheda»

Una voce di una scheda: l'esercizio, la sua posizione nell'ordine, e gli obiettivi (serie e ripetizioni, eventualmente come intervallo). Un esercizio compare una volta sola per scheda.

### Workout — «Allenamento»

L'**eseguito**: un allenamento realmente svolto, con una data di inizio e una di fine. È un **log immutabile** — modificare o cancellare la scheda da cui è nato non lo altera mai, perché ne conserva il nome come istantanea. Un allenamento può nascere da una scheda, che ne precompila le serie pianificate, oppure essere libero, senza nessuna scheda dietro. Vedi [ADR-0002](docs/adr/0002-allenamento-log-immutabile.md).

Il modello si chiama `Workout` e **non** `WorkoutSession`: in un progetto Django «session» significa già `django.contrib.sessions`, e la collisione renderebbe ambiguo ogni file in cui compaiono entrambe.

### WorkoutSet — «Serie»

L'unità elementare del dato: un esercizio, un numero di ripetizioni, un carico. È la riga su cui gira l'intero motore analitico. Ogni serie ha un **tipo** (`set_type`):

- `working` — **serie di lavoro**: l'unica che conta nelle analisi.
- `warmup` — **riscaldamento**.
- `rampUp` — **avvicinamento**: le serie intermedie che salgono verso il carico di lavoro.

Sommare riscaldamenti e avvicinamenti insieme alle serie di lavoro falserebbe volume e massimale, quindi ogni query di analisi filtra su `working`.

### Vote — «Voto»

Il giudizio di un utente su una **scheda pubblica**: un punteggio da 1 a 5 e un commento facoltativo. Un utente esprime al massimo un voto per scheda, e non può votare le proprie schede. È da qui che nasce la seconda classifica, quella sociale, di natura diversa dalla classifica di forza.

### Muscle e MuscleGroup — «Muscolo» e «Gruppo muscolare»

Anagrafica dei **23 muscoli** raggruppati in **6 gruppi** (petto, schiena, spalle, braccia, gambe, core). Ogni esercizio ha **un solo** muscolo primario: i muscoli secondari sono deliberatamente fuori dal modello, perché attribuire loro una quota di volume richiederebbe un coefficiente inventato e non misurato.

La tassonomia è tenuta **identica a `reporting.muscle_taxonomy` di Overload** — stessi muscoli, stessi gruppi, stesse etichette italiane — perché i dati di Progressive devono restare importabili nella dashboard personale di Overload.

### Equipment — «Attrezzo»

Bilanciere, manubri, macchina, cavi, corpo libero. Serve a filtrare e raggruppare il catalogo, e porta il peso a vuoto dell'attrezzo (`default_bar_weight_kg`): il peso del bilanciere è una proprietà **dell'attrezzo**, non del singolo esercizio.

## Termini da non confondere

- **Carico** — il peso sollevato in una serie. Mai «peso» da solo.
- **Peso corporeo** — il peso dell'utente. È **un solo valore corrente**, non uno storico: lo stesso peso di oggi divide anche i massimali di mesi fa. Vedi [ADR-0008](docs/adr/0008-peso-corporeo-corrente-come-denominatore.md).
- **Forza relativa** — il massimale diviso il peso corporeo. È il criterio con cui utenti di taglia diversa diventano confrontabili, e quindi l'unità di misura sia del percentile di forza sia della classifica di forza. Mai «forza» da sola.
- **Volume** — carico × ripetizioni, sommato sulle sole serie di lavoro.
- **Massimale** — l'1RM *stimato* a partire da carico e ripetizioni. Non è mai un massimale realmente testato. Si calcola sulla **miglior serie di lavoro** di un allenamento, e le serie oltre le 12 ripetizioni non concorrono (la stima le sovrastima).
- **Stallo** — l'assenza di progressione su un esercizio nel tempo. In codice si chiama `plateau`, che è il termine tecnico inglese. Lo stallo si predica sempre su una coppia **utente + esercizio**, mai su un utente in blocco né su un gruppo muscolare: si stalla *su una panca*, non «in generale».
- **Finestra** — il tratto di storia su cui si giudica la progressione di un esercizio: gli allenamenti più recenti di quell'esercizio, contati sia in numero sia in giorni di calendario. Serve a entrambi i vincoli perché quattro sedute in cinque giorni non sono una storia, e un mese senza toccare l'esercizio non è uno stallo ma un'assenza. Un'interruzione abbastanza lunga **spezza** la finestra: quello che viene prima non entra.
- **Stato di progressione** — cosa la app dice di una coppia utente + esercizio: `stallo`, `non stallo`, oppure **dati insufficienti** quando la finestra non è abbastanza lunga per pronunciarsi. «Dati insufficienti» non è un modo educato di dire «non stallo»: è l'ammissione che la domanda non ha ancora risposta, e all'utente si mostra come avanzamento verso la soglia.
- **Regressione** — la pendenza del massimale nettamente in discesa su una finestra. È un'**osservazione descrittiva**, non uno stato di progressione: si calcola, non si predice, e convive con lo stallo invece di essere una sua terza alternativa.

## Le due classifiche

Sono due graduatorie di **natura diversa**, e non vanno chiamate entrambe «classifica» senza aggettivo.

### Classifica di forza — «Classifica di forza»

Ordina gli **utenti** su **un singolo esercizio** per forza relativa decrescente. Non esiste una classifica di forza generale: esiste una classifica per ogni esercizio che abbia abbastanza gente sopra. Un utente vi compare solo se ha un peso corporeo dichiarato e almeno **due allenamenti distinti** con quell'esercizio, e la classifica stessa si mostra solo sopra la **soglia di popolazione** — la stessa che fa tacere il percentile.

È una classifica di **record**, non di attività: il massimale che vi entra è quello di sempre, senza finestra temporale. Chi non si allena da un anno resta in graduatoria; a dire se qualcuno si allena c'è la costanza, che è un'altra cosa.

### Classifica sociale — «Classifica sociale»

Ordina le **schede pubbliche** per **punteggio sociale** decrescente. Il soggetto sono le schede, non gli utenti: è questo a renderla di natura diversa dalla prima.

### Punteggio sociale

Il numero che ordina la classifica sociale: **non** la media dei voti, ma una media **smorzata verso la media globale** di tutti i voti del database, tanto più quanto meno voti ha la scheda. Serve a impedire che una scheda con un solo 5 superi una scheda con cinquanta voti alti. La media grezza e il numero di voti restano mostrati accanto, perché il punteggio che ordina dev'essere ispezionabile.

### Soglia di popolazione

Il numero minimo di utenti su un esercizio sotto il quale un confronto fra utenti **non si mostra**: né percentile, né classifica. Sotto quella soglia la app dice **perché** tace, e non inventa una posizione.

### Pari merito

Due righe con lo stesso valore ordinatore condividono la **stessa posizione** — due primi, e il successivo è terzo. L'ordine *dentro* il pari merito resta comunque deterministico, così la pagina non si riordina a ogni ricarica.

## Confini del dominio

`Progressive` è il piano di sopra rispetto a **Overload**, l'app iOS che si usa in palestra durante l'allenamento. Progressive **legge** lo storico e ne ricava quello che Overload non dice: stalli, percentili, squilibri, cosa fare la prossima volta. Non è un tracker dal vivo — non ha timer di recupero né spunta serie per serie — e Overload resta la sorgente dello schema e dei dati reali, mai un bersaglio di modifiche.
