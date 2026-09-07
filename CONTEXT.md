# CONTEXT — Progressive

Glossario del dominio di `Progressive`, l'applicazione web Django per l'esame di IWC 2026.

Regola di lingua fissata per il progetto: **il codice e i modelli sono in inglese, l'interfaccia è in italiano.** Ogni voce qui sotto dà entrambi i nomi. Quando un documento, un titolo di issue o un nome di test nomina un concetto del dominio, usa il termine di questa tabella e non un sinonimo.

Questo file è **solo un glossario**. Le decisioni sul perché stanno in `docs/adr/`; il *come* costruire sta in `docs/spec/`; il ragionamento per esteso sta nella risoluzione del ticket che lo ha deciso.

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

Sommare riscaldamenti e avvicinamenti insieme alle serie di lavoro falserebbe volume e massimale, quindi ogni query di analisi filtra su `working` **e** su `is_completed`: i due filtri vanno sempre insieme, mai uno solo.

### Vote — «Voto»

Il giudizio di un utente su una **scheda pubblica**: un punteggio da 1 a 5 e un commento facoltativo. Un utente esprime al massimo un voto per scheda, e non può votare le proprie schede. È da qui che nasce la seconda classifica, quella sociale, di natura diversa dalla classifica di forza.

### ExerciseAlias — «Abbinamento esercizio»

Il ricordo di una traduzione: «in un file importato da *questo* utente, il nome libero *X* significa l'esercizio *Y* del catalogo». Nasce quando l'utente, durante l'anteprima di un import, sceglie a mano a quale esercizio del catalogo corrisponde un nome che l'app non ha riconosciuto — `RDL` → «Stacco rumeno con bilanciere» — e serve solo perché al secondo import quella scelta non venga richiesta di nuovo.

Non è un esercizio e non allarga il catalogo: è **infrastruttura dell'import**, appartiene a un utente e non compare in nessuna analisi. Creare un esercizio nuovo resta vietato (vedi [ADR-0001](docs/adr/0001-catalogo-esercizi-globale-e-scritto-a-mano.md)); l'abbinamento è il modo in cui un nome estraneo entra nel dominio senza sporcarlo. Vedi [ADR-0010](docs/adr/0010-abbinamento-nomi-import-interattivo.md).

### Muscle e MuscleGroup — «Muscolo» e «Gruppo muscolare»

Anagrafica dei **23 muscoli** raggruppati in **6 gruppi** (petto, schiena, spalle, braccia, gambe, core). Ogni esercizio ha **un solo** muscolo primario: i muscoli secondari sono deliberatamente fuori dal modello, perché attribuire loro una quota di volume richiederebbe un coefficiente inventato e non misurato.

La tassonomia è tenuta **identica a `reporting.muscle_taxonomy` di Overload** — stessi muscoli, stessi gruppi, stesse etichette italiane — perché i dati di Progressive devono restare importabili nella dashboard personale di Overload.

### Equipment — «Attrezzo»

Bilanciere, manubri, macchina, cavi, corpo libero. Serve a filtrare e raggruppare il catalogo, e porta due proprietà che appartengono **all'attrezzo e non al singolo esercizio**: il peso a vuoto (`default_bar_weight_kg`) e l'**incremento di carico** (`load_increment_kg`), il passo minimo con cui su quell'attrezzo il carico può realmente salire.

### Utente sintetico — «Utente dimostrativo»

Uno dei ~100 utenti generati, riconoscibile da `is_synthetic`. Esiste perché percentili e classifiche hanno bisogno di una popolazione che un progetto d'esame non ha. Non è un utente di prova nascosto: entra nelle statistiche come tutti gli altri **ed è dichiarato nell'interfaccia**. Vedi [ADR-0009](docs/adr/0009-la-popolazione-sintetica-si-dichiara.md).

### Archetipo — «Archetipo»

Il profilo di progressione di un utente sintetico: principiante, intermedio in plateau, incostante, avanzato, abbandono. Vive **solo nel generatore** — non è un campo del modello e l'applicazione non lo conosce. Da non confondere con lo **stato di progressione**, che è una proprietà osservata di una coppia (utente, esercizio), non una qualità della persona: nessun archetipo «stalla», è una fase che quasi tutti attraversano.

## Il coach

### Coach — «Coach»

La parte di `Progressive` che **dice cosa fare**, in opposizione al motore analitico che mostra cosa è successo. Non è un modello Django e non persiste nulla: è il servizio `training/analytics/coach.py`, che a ogni richiesta calcola i consigli dalle serie già registrate. Il coach non prescrive fisiologia — non cambia esercizio, non tocca la frequenza — perché ogni sua affermazione deve poggiare su una query e sui dati che il modello possiede davvero. Vedi [ADR-0007](docs/adr/0007-il-coach-dice-una-cosa-sola.md).

### Advice — «Consiglio»

Una raccomandazione **azionabile**: dice cosa fare il prossimo allenamento, e ha dietro **una** query. Un'osservazione che non si traduce in un'azione («stai trascurando le gambe») non è un consiglio e resta nel motore analitico: è la distinzione che impedisce al coach di ridiventare un cruscotto.

Ogni consiglio ha un **tipo**, e il tipo porta con sé una **priorità** costante — non un punteggio calcolato. In ordine decrescente:

1. **Costanza** — meno di 2 allenamenti in 14 giorni, e solo per chi ne ha già almeno 4. Se non ci si allena, nessun altro consiglio conta.
2. **Squilibrio** — un gruppo muscolare con zero serie di lavoro negli ultimi 28 giorni, in un periodo con almeno 8 allenamenti. La soglia è di **assenza**, non di proporzione: «non hai allenato le gambe in un mese» è un fatto, «le tue spalle sono al 9% invece che al 15%» richiederebbe una ripartizione ideale inventata.
3. **Stallo** — vedi *Stato di progressione*.
4. **Carico** — la doppia progressione, sotto.

Dove i consigli si mostrano è parte della loro definizione: **uno solo**, quello a priorità più alta, nel riquadro della dashboard; nella pagina di dettaglio esercizio soltanto il consiglio di carico e, se rilevato, lo stallo. Non esiste una pagina che li elenca tutti — un coach che dice cinque cose non dice niente.

### Doppia progressione — «Doppia progressione»

La regola con cui il coach suggerisce il carico della prossima sessione, e l'unica: prima salgono le **ripetizioni**, poi il **carico**. Finché le ripetizioni non hanno raggiunto l'estremo alto del target di scheda su **tutte** le serie di lavoro, il consiglio è stesso carico e una ripetizione in più; quando lo raggiungono, il carico sale di un **incremento dell'attrezzo** (`Equipment.load_increment_kg`) e le ripetizioni ripartono dal minimo del range.

L'incremento è **fisso per attrezzo**, mai una percentuale del massimale: la percentuale produce carichi che non esistono come dischi (83,7 kg) e andrebbe comunque arrotondata. Sul **corpo libero** l'incremento è zero e il coach consiglia ripetizioni, non carico.

Il target viene dalla scheda dell'**ultimo allenamento** che ha registrato quell'esercizio — l'allenamento è un log immutabile e conserva la scheda da cui è nato, quindi con lo stesso esercizio in più schede non serve nessuna regola di precedenza. Per un allenamento **libero**, senza scheda e quindi senza target, il carico sale quando lo stesso carico è stato ripetuto due volte con ripetizioni uguali o crescenti.

### Deload — «Scarico»

L'unica azione che il coach propone in risposta a uno **stallo**: una singola sessione al **90% del massimo di finestra**, arrotondato all'incremento dell'attrezzo, dopo la quale si torna alla doppia progressione da quel carico. La base è il massimo di finestra e non l'ultimo carico, che potrebbe essere già una giornata storta.

Il deload è **proposto, mai rilevato**: [ADR-0004](docs/adr/0004-ground-truth-dello-stallo-dal-futuro-della-finestra.md) ha escluso di riconoscere un deload dai dati, perché recupero e durata delle sessioni sono inaffidabili. Nel modello non esiste nulla che rappresenti un ciclo di scarico di più settimane: sarebbe un piano di allenamento, e non abbiamo né il modello per descriverlo né i dati per validarlo.

## Termini da non confondere

- **Carico** — il peso sollevato in una serie. Mai «peso» da solo. È sempre **comprensivo del bilanciere**: il peso a vuoto dell'attrezzo non si somma mai a valle, serve solo a precompilare il form.
- **Carico effettivo** — il carico che entra nelle analisi: il carico, più il **peso corporeo** quando l'attrezzo è il corpo libero. Senza questa aggiunta ogni trazione e ogni piegamento peserebbero zero, e nella distribuzione del volume la schiena sparirebbe. Gestisce anche le trazioni zavorrate, che sono peso corporeo più carico aggiunto. Vedi [ADR-0006](docs/adr/0006-carico-effettivo-include-il-peso-corporeo.md).
- **Peso corporeo** — il peso dell'utente (`body_mass_kg`). È **un solo valore corrente**, non uno storico: lo stesso peso di oggi vale anche per gli allenamenti di mesi fa. Entra nel sistema da due porte — è il divisore della **forza relativa** e un addendo del **carico effettivo** sul corpo libero — ed è quindi l'unico valore che, cambiando, riscrive il passato. Vedi [ADR-0008](docs/adr/0008-peso-corporeo-corrente-come-denominatore.md).
- **Forza relativa** — il massimale diviso il peso corporeo. È il criterio con cui utenti di taglia diversa diventano confrontabili, e quindi l'unità di misura sia del percentile di forza sia della classifica di forza. Mai «forza» da sola.
- **Volume** — **carico effettivo** × ripetizioni, sommato sulle sole serie di lavoro eseguite.
- **Massimale** — l'1RM *stimato*, con la formula di Epley. Non è mai un massimale realmente testato. Tre vincoli, tutti e tre necessari: si calcola sulla **miglior serie di lavoro** dell'allenamento, a partire dal **carico effettivo**, e le serie **oltre le 12 ripetizioni non concorrono** — la stima le gonfia — pur restando nel volume.
- **PR** — il massimale più alto mai raggiunto da un utente su un esercizio. Non è un concetto distinto dal massimale: è il suo massimo storico.
- **Percentile di forza** — la posizione dell'utente nella popolazione su un esercizio, calcolata sulla **forza relativa**. Tace sotto la **soglia di popolazione**: sarebbe formalmente corretto e informativamente falso.
- **Stallo** — l'assenza di progressione su un esercizio nel tempo. In codice si chiama `plateau`, che è il termine tecnico inglese. Lo stallo si predica sempre su una coppia **utente + esercizio**, mai su un utente in blocco né su un gruppo muscolare: si stalla *su una panca*, non «in generale».
- **Finestra** — il tratto di storia su cui si giudica la progressione di un esercizio: gli allenamenti più recenti di quell'esercizio, contati sia in numero sia in giorni di calendario. Serve a entrambi i vincoli perché quattro sedute in cinque giorni non sono una storia, e un mese senza toccare l'esercizio non è uno stallo ma un'assenza. Un'interruzione abbastanza lunga **spezza** la finestra: quello che viene prima non entra.
- **Stato di progressione** — cosa la app dice di una coppia utente + esercizio: `stallo`, `non stallo`, oppure **dati insufficienti** quando la finestra non è abbastanza lunga per pronunciarsi. «Dati insufficienti» non è un modo educato di dire «non stallo»: è l'ammissione che la domanda non ha ancora risposta, e all'utente si mostra come avanzamento verso la soglia.
- **Regressione** — la pendenza del massimale nettamente in discesa su una finestra. È un'**osservazione descrittiva**, non uno stato di progressione: si calcola, non si predice, e convive con lo stallo invece di essere una sua terza alternativa.
- **Import** — il caricamento del **proprio storico di allenamenti** da un file CSV, attraverso un form web, con anteprima e conferma. È una funzione dell'utente. Da non confondere con il **caricamento del catalogo**, che è il management command `load_catalog` riservato all'amministratore: sono due canali diversi, con due pubblici diversi.
- **Nome libero** — il nome di un esercizio come appare in un file importato, scritto da un altro sistema e non vincolato al catalogo. Diventa utilizzabile solo attraverso un **abbinamento**.
- **Aderenza al piano** — quanto delle serie previste è stato davvero chiuso. Non è un'analisi: le analisi scartano le serie non completate (sono il 19% dei dati reali). Diventa un consiglio in un caso solo — se *tutte* le serie di lavoro di un esercizio sono rimaste incomplete, il coach non fa salire niente e dice di riprovare lo stesso carico.

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

Il numero minimo di utenti su un esercizio sotto il quale un confronto fra utenti **non si mostra**: né percentile, né classifica. È **una sola costante** per tutto il progetto, non due che per caso coincidono. Sotto quella soglia la app dice **perché** tace, e non inventa una posizione.

### Pari merito

Due righe con lo stesso valore ordinatore condividono la **stessa posizione** — due primi, e il successivo è terzo. L'ordine *dentro* il pari merito resta comunque deterministico, così la pagina non si riordina a ogni ricarica.

## Confini del dominio

`Progressive` è il piano di sopra rispetto a **Overload**, l'app iOS che si usa in palestra durante l'allenamento. Progressive **legge** lo storico e ne ricava quello che Overload non dice: stalli, percentili, squilibri, cosa fare la prossima volta. Non è un tracker dal vivo — non ha timer di recupero né spunta serie per serie — e Overload resta la sorgente dello schema e dei dati reali, mai un bersaglio di modifiche.
