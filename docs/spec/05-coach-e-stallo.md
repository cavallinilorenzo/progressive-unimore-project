# 05 — Il coach e il rilevamento dello stallo

Fonte: [#31](https://github.com/cavallinilorenzo/progetto-django-uni/issues/31) (perimetro del coach), [#17](https://github.com/cavallinilorenzo/progetto-django-uni/issues/17) (rilevamento dello stallo), [#18](https://github.com/cavallinilorenzo/progetto-django-uni/issues/18) (validazione).

Sono le **fasi 3 e 4** dell'ordine di costruzione. Il ML è l'ultima cosa che si scrive ed è **l'unica tagliabile** se il tempo stringe: se si taglia, la pagina dello stallo mostra il baseline a soglia e lo si dichiara.

## Il coach

`training/analytics/coach.py`. **Non è un modello Django e non persiste nulla**: a ogni richiesta calcola i consigli dalle serie già registrate.

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

### Dove si mostrano — è parte della definizione

- **Dashboard: uno solo**, quello a priorità più alta, in un riquadro
- **Dettaglio esercizio:** solo il consiglio di carico e, se rilevato, lo stallo
- **Non esiste una pagina che li elenca tutti** — un coach che dice cinque cose non dice niente

Nessun onboarding, nessuna pagina dedicata: il coach affina `02-pagine-e-template.md` senza spostarlo.

### Doppia progressione — l'unica regola di carico

Prima salgono le **ripetizioni**, poi il **carico**.

1. Finché le ripetizioni non hanno raggiunto `target_reps_max` su **tutte** le serie di lavoro → *stesso carico, una ripetizione in più*
2. Quando lo raggiungono → *il carico sale di un `Equipment.load_increment_kg`*, e le ripetizioni ripartono da `target_reps`

**L'incremento è fisso per attrezzo, mai una percentuale del massimale.** La percentuale produce carichi che non esistono come dischi (83,7 kg) e andrebbe comunque arrotondata. Sul **corpo libero** l'incremento è zero e il coach consiglia ripetizioni, non carico.

Il target viene dalla scheda dell'**ultimo allenamento** che ha registrato quell'esercizio — l'allenamento è un log immutabile e conserva la scheda da cui è nato, quindi con lo stesso esercizio in più schede **non serve nessuna regola di precedenza**.

Per un allenamento **libero**, senza scheda e quindi senza target: il carico sale quando lo stesso carico è stato ripetuto due volte con ripetizioni uguali o crescenti.

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

Costanza e squilibrio girano in `coach.py`. Il catalogo delle analisi resta a **sei voci**.

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

> ⚠️ **L'orizzonte era 4 sessioni nel ticket #17.** È stato portato a **6** e ratificato in #20 — vedi l'emendamento in coda ad [ADR-0004](../adr/0004-ground-truth-dello-stallo-dal-futuro-della-finestra.md). Con 4 la quota di `stallo` non era portabile nella banda 15–35% (74,8% → 58,3% → 45,1%); con 6 va al **30,1%** senza toccare un parametro del generatore. **Usare 6.**

Finestra doppia perché solo le sessioni non bastano (quattro sedute in cinque giorni sono un microciclo, non uno stallo) e solo i giorni è peggio (un mese senza panca è assenza, non stallo).

**Nessun rilevatore di deload.** `intensity` è costante su tutte le 15 sessioni reali e non esiste un campo affidabile: inventare un rilevatore significa aggiungere un secondo problema non validabile. Se un deload volontario produce un falso positivo, è un limite che **si dichiara all'orale**.

### Classi

**Binario: `stallo` / `non stallo`.** La regola di etichettatura è binaria per costruzione, e una terza classe «regressione» richiederebbe una seconda soglia inventata a mano, per giunta rara: renderebbe illeggibile proprio la riga della matrice di confusione che interessa.

- **«Dati insufficienti» è uno stato, non una classe** — non entra mai nel training set né nella matrice di confusione
- **«In regressione» è un'etichetta descrittiva calcolata**, non appresa: pendenza di finestra significativamente negativa, due righe di ORM. Si mostra nell'interfaccia e non inquina la valutazione

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

> **Se il modello non batte la regola, si dice e si spedisce la regola.** Chiamare «machine learning» una regola travestita è un rischio all'orale, non un punto. Questa frase è di Lorenzo, ed è la parte di #17 che vale più di qualsiasi F1.

Diagnostica già misurata da #18: la fase `plateau` del generatore viene letta come stallo nel **57,4%** dei casi contro il **23,1%** della fase `crescita`. Il segnale c'è ed è forte. (È diagnostica, **mai** usata come etichetta.)

### Come vive dentro Django

- **Nessun settimo modello.** Niente tabella `PlateauAssessment`: sarebbe una cache travestita da modello, e offusca la lettura «5–6 modelli correlati» che il prof deve fare
- **Addestramento offline, inferenza in Python puro.** `scikit-learn` è dipendenza di **sviluppo**, mai a runtime: si addestra e si valuta fuori dal ciclo di richiesta, e in Progressive entrano i **coefficienti appresi come costanti** in `analytics/plateau.py`. L'app resta «Django e basta», e il ML resta tagliabile per ultimo senza toccare il resto. Vedi [ADR-0005](../adr/0005-il-ml-non-entra-a-runtime.md)
- **Nessuna persistenza né cache** finché non si è **misurato** che serve

### Utente nuovo

«Dati insufficienti» si mostra come **avanzamento, non come errore**:

> *4 allenamenti su 6 — 12 giorni su 21*

E il coach **non tace**: quando non può valutare lo stallo dà il consiglio non-ML, cioè la doppia progressione sul carico dell'ultima sessione.

### Vincolo per la demo

Lo storico reale di Lorenzo (26 giorni, nessun esercizio oltre 8 sessioni) **è troppo corto** per superare la soglia. La pagina dello stallo si dimostra su un **utente sintetico**, già scelto e nominato: **`demo064` — Martina Longo**, 17 mesi di storico, 1199 finestre etichettabili.
