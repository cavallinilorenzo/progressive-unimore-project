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

## Il coach

### Coach — «Coach»

La parte di `Progressive` che **dice cosa fare**, in opposizione al motore analitico che mostra cosa è successo. Non è un modello Django e non persiste nulla: è il servizio `analytics/coach.py`, che a ogni richiesta calcola i consigli dalle serie già registrate. Il coach non prescrive fisiologia — non cambia esercizio, non tocca la frequenza — perché ogni sua affermazione deve poggiare su una query e sui dati che il modello possiede davvero. Vedi [ADR-0007](docs/adr/0007-il-coach-dice-una-cosa-sola.md).

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

- **Carico** — il peso sollevato in una serie. Mai «peso» da solo.
- **Peso corporeo** — il peso dell'utente. Serve alla **forza relativa**, cioè al massimale diviso il peso corporeo, che è il criterio con cui utenti di taglia diversa diventano confrontabili.
- **Volume** — carico × ripetizioni, sommato sulle sole serie di lavoro.
- **Massimale** — l'1RM *stimato* a partire da carico e ripetizioni. Non è mai un massimale realmente testato.
- **Stallo** — l'assenza di progressione su un esercizio nel tempo. In codice si chiama `plateau`, che è il termine tecnico inglese.
- **Aderenza al piano** — quanto delle serie previste è stato davvero chiuso. Non è un'analisi: le analisi scartano le serie non completate (sono il 19% dei dati reali). Diventa un consiglio in un caso solo — se *tutte* le serie di lavoro di un esercizio sono rimaste incomplete, il coach non fa salire niente e dice di riprovare lo stesso carico.

## Confini del dominio

`Progressive` è il piano di sopra rispetto a **Overload**, l'app iOS che si usa in palestra durante l'allenamento. Progressive **legge** lo storico e ne ricava quello che Overload non dice: stalli, percentili, squilibri, cosa fare la prossima volta. Non è un tracker dal vivo — non ha timer di recupero né spunta serie per serie — e Overload resta la sorgente dello schema e dei dati reali, mai un bersaglio di modifiche.
