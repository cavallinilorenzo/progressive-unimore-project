# 05 — Il coach e il rilevamento dello stallo

Fonte: [#31](https://github.com/cavallinilorenzo/progetto-django-uni/issues/31) (perimetro del coach), [#17](https://github.com/cavallinilorenzo/progetto-django-uni/issues/17) (rilevamento dello stallo), [#18](https://github.com/cavallinilorenzo/progetto-django-uni/issues/18) (validazione).

Sono le **fasi 3 e 4** dell'ordine di costruzione. Il ML è l'ultima cosa che si scrive ed è **l'unica tagliabile** se il tempo stringe: se si taglia, la pagina dello stallo mostra il baseline a soglia e lo si dichiara.

## Il coach

`training/analytics/coach/` — un **pacchetto**, non un modulo unico. **Non è un modello Django e non persiste nulla**: a ogni richiesta calcola i consigli dalle serie già registrate.

> **Corretto in [#112](https://github.com/cavallinilorenzo/progetto-django-uni/issues/112).** Questa spec diceva `coach.py`, modulo unico. I quattro tipi di consiglio condividono la **selezione per priorità**, che è il cuore di ADR-0007 e non può esistere in due copie, e con un modulo solo i quattro ticket della fase 3 avrebbero scritto tutti sullo stesso file. La forma è quindi: `__init__.py` è **l'unica superficie pubblica** e tiene la priorità (`consiglio_per_dashboard(user)`, `consigli_per_esercizio(user, exercise)`); un tipo di consiglio guadagna un modulo suo **solo se ha una query propria**.

La regola che governa tutto: **un consiglio è azionabile e ha dietro una query.** Un'osservazione che non diventa azione («stai trascurando le gambe») **non è un consiglio** e resta nel motore analitico. È la distinzione che impedisce al coach di ridiventare un cruscotto. Vedi [ADR-0007](../adr/0007-il-coach-dice-una-cosa-sola.md).

### Quattro tipi, priorità costante sul tipo

Non un punteggio calcolato: una priorità fissa, in ordine decrescente.

| # | Tipo | Condizione |
|---|---|---|
| 1 | **Costanza** | < 2 allenamenti in 14 giorni, e solo per chi ne ha già ≥ 4 |
| 2 | **Squilibrio** | Un gruppo muscolare a **zero** serie di lavoro negli ultimi 28 giorni, in un periodo con ≥ 8 allenamenti |
| 3 | **Stallo** | Vedi sotto |
| 4 | **Carico** | La doppia progressione |

Se non ci si allena, nessun altro consiglio conta: per questo la costanza è prima.

Lo squilibrio usa una soglia di **assenza**, non di proporzione: *«non hai allenato le gambe in un mese»* è un fatto; *«le tue spalle sono al 9% invece che al 15%»* richiederebbe una ripartizione ideale inventata.

**E dichiara sempre ciò che non vede.** Il catalogo tagga un solo muscolo primario per esercizio (ADR-0001), quindi «zero serie» significa *zero serie dirette*. Misurato sul database della demo in #112: la regola scatta per **33 utenti su 55** con almeno 8 allenamenti nella finestra, e in **32 casi su 33** il gruppo mancante è **braccia**, cioè proprio quello che riceve più lavoro da secondario. Il consiglio resta vero e resta azionabile, ma senza la parola «direttamente» in pagina direbbe una cosa più grande di quella che sa.

### Dove si mostrano — è parte della definizione

- **Dashboard: uno solo**, quello a priorità più alta, in un riquadro
- **Dettaglio esercizio:** solo il consiglio di carico e, se rilevato, lo stallo

  **Lo stato di progressione non è un consiglio, ed è la distinzione che [#114](https://github.com/cavallinilorenzo/progetto-django-uni/issues/114) ha dovuto fare.** Il riquadro «Stato di progressione» sul dettaglio esercizio c'è **sempre**, anche a zero sessioni, perché risponde alla domanda per cui si è aperta la pagina — *sto migliorando su questo esercizio?* — e perché è l'unico posto in cui la soglia è scritta: a chi apre un esercizio mai provato dice quanto manca invece di tacere. Un consiglio invece compare solo quando ha qualcosa da far fare, e ADR-0007 vale su quelli. Il **consiglio** di stallo — il deload al 90% — è un'altra cosa e arriva con #115.
- **Non esiste una pagina che li elenca tutti** — un coach che dice cinque cose non dice niente
- **E quando nessuna regola scatta, il riquadro non c'è.** Deciso in [#112](https://github.com/cavallinilorenzo/progetto-django-uni/issues/112) in via provvisoria: un riquadro che dicesse «nessun consiglio» suonerebbe come «va tutto bene» mentre metà delle regole non esiste ancora, cioè una diagnosi rassicurante emessa da un coach che non ha guardato.

  **Diventa definitivo in [#113](https://github.com/cavallinilorenzo/progetto-django-uni/issues/113), per misura.** Col consiglio di carico — che scatta per chiunque abbia registrato una serie di lavoro — sui 100 utenti del database **nessuno** resta senza consiglio: 40 sentono il carico, 32 lo squilibrio, 28 la costanza. Il silenzio è ormai solo l'**utente appena registrato**, che è il vuoto vero e sulla dashboard parla già da #101: non c'è più un caso da arredare.

Nessun onboarding, nessuna pagina dedicata: il coach affina `02-pagine-e-template.md` senza spostarlo.

### Doppia progressione — l'unica regola di carico

Prima salgono le **ripetizioni**, poi il **carico**.

1. Finché le ripetizioni non hanno raggiunto `target_reps_max` su **tutte** le serie di lavoro → *stesso carico, una ripetizione in più*
2. Quando lo raggiungono → *il carico sale di un `Equipment.load_increment_kg`*, e le ripetizioni ripartono da `target_reps`

**L'incremento è fisso per attrezzo, mai una percentuale del massimale.** La percentuale produce carichi che non esistono come dischi (83,7 kg) e andrebbe comunque arrotondata.

> **Corretto in [#113](https://github.com/cavallinilorenzo/progetto-django-uni/issues/113).** Questa spec diceva «sul **corpo libero** l'incremento è zero». La regola non è «corpo libero», è **«attrezzo a incremento zero»**, e nel catalogo (`data/catalog/equipment.csv`) sono **due**: `bodyweight` **e `band`**. La differenza non è cosmetica — sul corpo libero il carico si muove comunque, perché la zavorra si scrive in `weight` e `EFFECTIVE_LOAD` somma il peso corporeo (ADR-0006); sull'**elastico** no, e col termine sbagliato l'elastico non sarebbe coperto da nessuna regola: il coach direbbe «una ripetizione in più» per sempre, per sempre corretto e per sempre inutile, senza che niente lo segnali. È la stessa famiglia di guasto muto di `corpo_libero` scritto al posto di `bodyweight` (#16). Su un attrezzo a incremento zero il consiglio **dichiara il limite**: che il passo successivo — una variante più difficile, o della zavorra — è una scelta che il coach non misura.

**Il carico proposto è quello che l'utente riscrive nel form** — `WorkoutSet.weight`, bilanciere compreso — e **non** passa da `EFFECTIVE_LOAD`: il carico effettivo è la definizione giusta per il volume e il massimale, dove la domanda è *quanto hai spostato*; qui la domanda è *cosa scrivo la prossima volta*. Per la stessa ragione **non si arrotonda**: è un carico davvero sollevato più un incremento dell'attrezzo, quindi sta già sulla griglia dei dischi. L'arrotondamento serve al **deload**, che parte da un massimo calcolato (#113).

Il target viene dalla scheda dell'**ultimo allenamento** che ha registrato quell'esercizio — l'allenamento è un log immutabile e conserva la scheda da cui è nato, quindi con lo stesso esercizio in più schede **non serve nessuna regola di precedenza**.

Per un allenamento **libero**, senza scheda e quindi senza target: il carico sale quando lo stesso carico è stato ripetuto due volte con ripetizioni uguali o crescenti. Il confronto è fra **due sessioni consecutive** — due righe lette in Python, nessuna finestra: `Lag` risponderebbe alla domanda dell'*andamento*, che è quella di A3 (#98), non questa.

> **Misurato in #113: 0 allenamenti su 11.855 hanno una scheda collegata.** Il generatore sintetico crea schede e allenamenti senza legarli, e l'import da Overload non ha una scheda da portarsi dietro. Il ramo «target dalla scheda» esiste ed è testato, ma è **invisibile alla demo**: la pagina che si guarda all'orale gira tutta sul ramo dell'allenamento libero, e il consiglio lo dichiara nel proprio limite invece di far finta di aver letto un target che non c'era.
>
> **La sessione è letta dalla sua serie di punta**, cioè dal massimo carico fra le serie di lavoro completate, e le ripetizioni che contano sono quelle eseguite a quel carico. Con carichi diversi nella stessa sessione — una discesa, un back-off — «tutte le serie hanno raggiunto il target» sarebbe falso per sempre. Sulle 82.180 coppie (allenamento, esercizio) del database le serie completate stanno tutte a un carico solo: è una guardia per i log veri, non un comportamento osservabile oggi.

**Caso limite (aderenza al piano):** se *tutte* le serie di lavoro di un esercizio sono rimaste incomplete, il coach **non fa salire niente** e dice di riprovare lo stesso carico.

### Deload — una sola azione, dichiarata come euristica

In risposta a uno stallo: **una singola sessione al 90% del massimo di finestra**, arrotondato all'incremento dell'attrezzo; poi si torna alla doppia progressione da quel carico.

La base è il **massimo di finestra** e non l'ultimo carico, che potrebbe essere già una giornata storta.

Le altre tre risposte possibili sono state scartate per ragioni misurabili:

- **Cambiare esercizio** — romperebbe la serie storica su cui girano stallo, PR e percentili: il consiglio distruggerebbe il dato che lo ha prodotto
- **Aumentare la frequenza** — non ha **nessuna query dietro**: non abbiamo niente che misuri il recupero
- **Aumentare le ripetizioni** — non è una risposta allo stallo, è la doppia progressione ordinaria

Il deload è **proposto, mai rilevato**: non esiste un campo affidabile per riconoscerlo. Nel modello non c'è nulla che rappresenti un ciclo di scarico di più settimane.

### Le due query del coach non entrano nel catalogo

Il catalogo delle analisi resta a **sei voci**: le due condizioni sono un `Count` e un `Max`, e non superano il secondo asse di ammissione di [#16](https://github.com/cavallinilorenzo/progetto-django-uni/issues/16).

Ma **non girano nel coach**, ed è la correzione di [#112](https://github.com/cavallinilorenzo/progetto-django-uni/issues/112): quando la spec è stata scritta né la costanza né la heatmap esistevano, e oggi esistono entrambe. Il coach le **consuma**.

- La **costanza** viene da `training/analytics/costanza.py` (W1, #101), che resta l'unico modulo che sa contare gli allenamenti di un utente. Una seconda misura di costanza sarebbe la divergenza di [#75](https://github.com/cavallinilorenzo/progetto-django-uni/issues/75) un'altra volta, e stavolta con le due misure a un palmo l'una dall'altra sulla stessa pagina.
- Lo **squilibrio** legge le serie per gruppo di `training/analytics/muscles.py` (la heatmap, #101), che la dashboard calcola comunque per disegnare la figura.

Due finestre restano **diverse e dichiarate**, non riconciliate: il consiglio di costanza guarda **14 giorni mobili**, W1 la **griglia dei lunedì**. Sulla griglia, il lunedì mattina, chi si allena una volta a settimana risulterebbe a 1 allenamento invece che a 2, e il consiglio comparirebbe e sparirebbe da solo ogni settimana senza che l'utente abbia fatto niente di diverso. Le due vivono nello stesso modulo perché non possano divergere; il perché per esteso sta su `GIORNI_DEL_CONSIGLIO`.

## Il rilevamento dello stallo

### Il problema vero era il ground truth, non il modello

I dati reali non possono etichettare niente: 8 sessioni al massimo per esercizio. E prendere le etichette dallo **stato nascosto del generatore** sarebbe **circolare** — il modello imparerebbe a invertire il generatore, e il numero che si porta all'orale misurerebbe la bravura a generare dati, non a rilevare stalli.

La via scelta è l'**etichetta dal futuro**: una finestra è `stallo` se nelle sessioni successive il massimale stimato non supera il massimo della finestra oltre una soglia di tolleranza. Il modello vede solo la finestra; l'etichetta viene da dati che non ha visto. Vedi [ADR-0004](../adr/0004-ground-truth-dello-stallo-dal-futuro-della-finestra.md).

### Definizione operativa

| Parametro | Valore |
|---|---|
| Metrica | **1RM stimato (Epley)** sulla miglior serie di lavoro, `reps ≤ 12` |
| Unità | **(utente, esercizio)** — mai per utente in blocco, mai per gruppo muscolare |
| Finestra | ≥ **6 allenamenti** di quell'esercizio **E** ≥ **21 giorni** di calendario |
| Interruzione | un buco > **28 giorni** spezza la serie: si riparte a contare |
| Orizzonte futuro | **6 sessioni** ⚠️ |
| Tolleranza | **2%** sul massimo di finestra |

> ⚠️ **L'orizzonte era 4 sessioni nel ticket #17.** È stato portato a **6** e ratificato in #20 — vedi l'emendamento in coda ad [ADR-0004](../adr/0004-ground-truth-dello-stallo-dal-futuro-della-finestra.md). Con 4 la quota di `stallo` non era portabile nella banda 15–35% (74,8% → 58,3% → 45,1%); con 6 va al **31,0%** senza toccare un parametro del generatore. **Usare 6.**

Finestra doppia perché solo le sessioni non bastano (quattro sedute in cinque giorni sono un microciclo, non uno stallo) e solo i giorni è peggio (un mese senza panca è assenza, non stallo).

> **Precisato in [#114](https://github.com/cavallinilorenzo/progetto-django-uni/issues/114), costruendola.** La riga «≥ 6 allenamenti **E** ≥ 21 giorni» si legge in due modi, e la tabella non dice quale: **sei sedute fisse** da validare sul calendario, oppure **quante ne servono** per coprire entrambi i minimi. La finestra è la seconda cosa — il **suffisso più corto** della serie corrente che soddisfa entrambi i vincoli.
>
> La differenza è misurata sull'utente della demo, che si allena quattro volte a settimana: sulle 28 coppie (utente, esercizio) del suo storico, le ultime **sei** sedute stanno in **meno di 21 giorni** in due casi (pulley basso 19, stacco da terra 18). Con la finestra fissa quei due esercizi direbbero «dati insufficienti» per sempre — e, la parte che decide, **allenandosi di più peggiorerebbero**: sei sedute più fitte coprono meno calendario, quindi la barra di avanzamento andrebbe all'indietro proprio mentre l'utente fa la cosa giusta. Col suffisso minimo prendono sette sedute e rispondono.
>
> Il prezzo è che la finestra non ha larghezza costante fra un esercizio e l'altro, e va bene qui, dove la domanda è *questo utente su questo esercizio adesso* e la pagina dichiara quante sessioni ha guardato. La riga «finestre consecutive condividono cinque punti su sei» in §Validazione parla delle finestre a scorrimento dell'**etichettatura offline**, che sono un'altra cosa e restano a larghezza fissa.
>
> **E i 21 giorni sono di calendario, non d'orologio.** Sottrarre due `datetime` tronca le ore: la panca piana di `pk 64` ha una seduta il 15 agosto alle 16:45 e una il 5 settembre alle 12:15 — ventuno giorni sul calendario, **venti** su `timedelta.days` — e la finestra si allargava a sette sedute senza che niente lo segnalasse. Sette sedute sono una finestra legittima, solo non quella descritta qui: è un guasto muto, della stessa famiglia di `corpo_libero` scritto al posto di `bodyweight` (#16). Il confine si attraversa una volta sola, quando le righe di A3 diventano sessioni.

**Nessun rilevatore di deload.** `intensity` è costante su tutte le 15 sessioni reali e non esiste un campo affidabile: inventare un rilevatore significa aggiungere un secondo problema non validabile. Se un deload volontario produce un falso positivo, è un limite che **si dichiara all'orale**.

### Classi

**Binario: `stallo` / `non stallo`.** La regola di etichettatura è binaria per costruzione, e una terza classe «regressione» richiederebbe una seconda soglia inventata a mano, per giunta rara: renderebbe illeggibile proprio la riga della matrice di confusione che interessa.

- **«Dati insufficienti» è uno stato, non una classe** — non entra mai nel training set né nella matrice di confusione
- **«In regressione» è un'etichetta descrittiva calcolata**, non appresa: pendenza di finestra significativamente negativa, due righe di ORM. Si mostra nell'interfaccia e non inquina la valutazione

> **La soglia della regressione non è un numero scelto**, deciso in [#114](https://github.com/cavallinilorenzo/progetto-django-uni/issues/114): è la **tolleranza del 2%** di questa stessa tabella distribuita sulla finestra minima, cioè `-2% / 3 settimane = -0,67% a settimana`. Se ADR-0004 considera piatta una finestra che si muove entro il 2%, allora una discesa è *netta* esattamente quando su 21 giorni esce da quella banda — la banda dentro cui il progetto ha già dichiarato di non saper distinguere il movimento dal rumore. Scritta come divisione e non come letterale, così che cambiare la tolleranza o la finestra minima la trascini dietro. Sarebbe stata la terza soglia inventata a mano del progetto, e non lo è.
>
> Sui dati veri scatta per **147 coppie su 2.517** e per **4 dei 28 esercizi** dell'utente della demo — abbastanza rara da essere un'informazione, abbastanza frequente da vedersi all'orale.

### Le sei feature

Tutte **solo sulla finestra** — nessuna può guardare le sessioni successive, o l'etichetta rientra dalla porta di servizio.

1. **Pendenza relativa del massimale** (% a settimana) — la feature portante
2. **Varianza residua attorno alla retta** — piatta e pulita è stallo, piatta e caotica è spesso sotto-allenamento
3. **Sessioni dall'ultimo record**
4. **Massimale corrente in frazione del massimo di finestra**
5. **Frequenza** (allenamenti di quell'esercizio a settimana)
6. **Pendenza relativa del volume** — volume su con massimale piatto è un profilo diverso da entrambi giù

**Escluse deliberatamente:** recupero (il campo non esiste), durata della sessione (2 su 15 assurde), **peso corporeo e forza assoluta** — non dicono nulla sullo stallo e farebbero imparare «i forti stallano», che è un artefatto del generatore.

Le feature si calcolano **nell'ORM** (`Window`, `Lag`, `Max`, aggregazioni): la stessa vetrina del motore analitico, riusata. La pendenza si esprime con soli `Sum`/`Count`, perché SQLite non ha `stddev` (vedi `04-analisi.md`).

### Validazione

- **Split per utente sintetico, 70/30.** Mai per finestra: finestre consecutive condividono cinque punti su sei, e uno split casuale per riga renderebbe il test quasi identico al training
- **Metrica: precision e recall sulla classe `stallo`**, non l'accuratezza — con stalli al 30%, «non stalla mai» ha il 70% di accuratezza
- **Baseline obbligatorio:** la regola a soglia «nessun record nelle ultime sessioni». Il numero che va all'orale è **la differenza fra modello e baseline**

> **Il baseline esiste, ed è in produzione da [#114](https://github.com/cavallinilorenzo/progetto-django-uni/issues/114).** È la regola che decide lo stato di progressione sul dettaglio esercizio, non uno script di laboratorio scritto il giorno del confronto: la fase 4 arriva quando il suo termine di paragone è già una cosa che gli utenti vedono.
>
> **N = 3 sessioni**, cioè metà della finestra minima. La spec non dava il numero, e il numero è stato scelto **alla cieca** — prima che esistesse una finestra, un modello o uno script di confronto — e committato **da solo, prima del resto del ticket**, con la scelta motivata in `training/analytics/plateau.py`: il `git log` è l'unica prova dell'ordine che una dichiarazione a posteriori non può dare (è il trucco di [#102](https://github.com/cavallinilorenzo/progetto-django-uni/issues/102) sulla soglia dei tempi di pagina). Un `N` tarato dopo aver visto il modello non sarebbe un termine di paragone, sarebbe un avversario truccato, e nessuno all'orale potrebbe distinguerlo da uno onesto.
>
> **«Record» qui è il massimo di sempre, non il massimo di finestra** — e la divergenza con l'etichetta è dichiarata, non riconciliata, come le due finestre della costanza (#112). L'etichetta di ADR-0004 chiede se la finestra è piatta *rispetto a sé stessa*; il baseline chiede se l'utente sta ancora migliorando. Vince il massimo di sempre perché è il numero che il dettaglio esercizio mostra due riquadri sopra, sotto «Il tuo record» (A4): un baseline che dicesse «nessun record da 3 sessioni» mentre la stessa pagina ne festeggia uno sarebbe una contraddizione visibile, e il progetto non ha un secondo posto in cui spiegare che «record» qui vuol dire un'altra cosa.
>
> **Come si comporta, misurato il 2026-09-09.** Sulle 2.517 coppie (utente, esercizio) del database: **1.110 dati insufficienti**, **729 stallo**, **678 non stallo** — cioè il 52% delle coppie giudicabili. Sull'utente della demo, **11 stalli su 28 esercizi**. Il baseline è quindi **generoso**, sopra la banda 15–35% in cui #20 ha portato l'etichetta: è un fatto da avere in mano *prima* del confronto, ed è esattamente l'informazione che una scelta a posteriori di `N` avrebbe cancellato. Non si ritocca — un baseline che si aggiusta finché non perde bene non è un baseline.

> **Se il modello non batte la regola, si dice e si spedisce la regola.** Chiamare «machine learning» una regola travestita è un rischio all'orale, non un punto. Questa frase è di Lorenzo, ed è la parte di #17 che vale più di qualsiasi F1.

Diagnostica già misurata da #18: la fase `plateau` del generatore viene letta come stallo nel **57,4%** dei casi contro il **23,1%** della fase `crescita`. Il segnale c'è ed è forte. (È diagnostica, **mai** usata come etichetta.)

### Come vive dentro Django

- **Nessun settimo modello.** Niente tabella `PlateauAssessment`: sarebbe una cache travestita da modello, e offusca la lettura «5–6 modelli correlati» che il prof deve fare
- **Addestramento offline, inferenza in Python puro.** `scikit-learn` è dipendenza di **sviluppo**, mai a runtime: si addestra e si valuta fuori dal ciclo di richiesta, e in Progressive entrano i **coefficienti appresi come costanti** in `analytics/plateau.py`. L'app resta «Django e basta», e il ML resta tagliabile per ultimo senza toccare il resto. Vedi [ADR-0005](../adr/0005-il-ml-non-entra-a-runtime.md)

> **Dove si taglia, deciso in [#114](https://github.com/cavallinilorenzo/progetto-django-uni/issues/114).** Il modulo `analytics/plateau.py` espone una funzione sola che la fase 4 sostituisce: **`rileva_stallo(finestra) -> bool`**. Tutto il resto — la serie spezzata dal buco, la finestra, lo stato, l'avanzamento, il riquadro in pagina — resta identico quando al posto della regola a soglia ci sarà un prodotto scalare di coefficienti. La fase 4 sostituisce un'implementazione, non riscrive una pagina.
>
> La firma è la parte che conta, e ogni pezzo è una scelta:
>
> - **una `Finestra` e non `(utente, esercizio)`**, perché il tipo porta **solo** le sessioni della finestra: la condizione di ADR-0004 — il rilevatore vede la finestra, l'etichetta viene da dati che non ha visto — smette di essere una promessa da mantenere a mano in ogni funzione a valle e diventa una proprietà del tipo. Una feature che sbircia il futuro non fa fallire niente: fa salire i numeri;
> - **una `Finestra` e non le sei feature già estratte**, perché scegliere le feature è mestiere del rilevatore — la regola ne usa una, il modello ne userà sei — e una firma che le elencasse costringerebbe la fase 4 a cambiare anche la riga che non le appartiene. Cinque delle sei si calcolano già dal tipo com'è; la sesta (pendenza del volume) chiede un dato in più, e allargare `Finestra` è esattamente il punto in cui si vuole che quella modifica cada;
> - **un `bool` e non un punteggio**, perché le classi sono binarie e la pagina mostra uno stato, non una probabilità. Se servisse una confidenza, allargare il tipo di ritorno è un cambiamento che si vede; restituire un `float` da una funzione che si chiama `rileva_` non lo sarebbe.

- **Nessuna persistenza né cache** finché non si è **misurato** che serve

### Utente nuovo

«Dati insufficienti» si mostra come **avanzamento, non come errore**:

> *4 allenamenti su 6 — 12 giorni su 21*

E il coach **non tace**: quando non può valutare lo stallo dà il consiglio non-ML, cioè la doppia progressione sul carico dell'ultima sessione.

### Vincolo per la demo

Lo storico reale di Lorenzo (26 giorni, nessun esercizio oltre 8 sessioni) **è troppo corto** per superare la soglia. La pagina dello stallo si dimostra su un **utente sintetico**, già scelto e nominato: **`cavallinilorenzo` — Lorenzo Cavallini**, **24 mesi** di storico e **1904 finestre etichettabili**. È l'account di Lorenzo con dati generati: la contraddizione è dichiarata, non nascosta, e `is_synthetic` resta vero anche su di lui.
