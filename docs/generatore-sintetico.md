# Il generatore della popolazione sintetica

Risolve il ticket [Generatore di dati sintetici: ~100 utenti con progressioni credibili](https://github.com/cavallinilorenzo/progetto-django-uni/issues/18).

Le classifiche, i percentili e il rilevamento dello stallo hanno tutti bisogno di una
popolazione, e non esiste un dataset pubblico di log di allenamento veri. Va generata —
ma generata in modo che le analisi che ci girano sopra significhino qualcosa.

Il prototipo sta in `scripts/prototype_seed_synthetic.py` ed è **codice usa-e-getta**:

```bash
python3 scripts/prototype_seed_synthetic.py
```

Legge il catalogo versionato da `data/catalog/`, scrive i CSV in `data/synthetic/`
(fuori dal versionamento) e stampa un **rapporto di validazione**. È il rapporto la
risposta del ticket; i CSV sono solo il mezzo per produrlo.

## Le cinque scelte che tengono in piedi il generatore

### 1. Il carico non si genera: si deriva

Il vincolo del ticket era che una panca da 140 kg con uno squat da 60 kg non deve poter
esistere. La coerenza è ottenuta **per costruzione**, non sorvegliata a posteriori:

```
massimale = peso corporeo × rapporto dell'esercizio × forza dell'utente × progressione(t) × rumore
```

Ogni utente ha **un solo** scalare di forza e **un solo** potenziale di crescita; ogni
esercizio del core ha un rapporto di riferimento al peso corporeo (squat 1,40×, panca
1,00×, stacco 1,75×, curl 0,45×). Non c'è modo di generare quella panca con quello
squat, perché nascono dallo stesso numero.

Il carico della singola serie si ottiene **invertendo Epley** dal massimale latente e
arrotondando all'incremento dell'attrezzo (2,5 kg per il bilanciere, 1,25 per i cavi):
la stessa formula che le analisi useranno per stimare il massimale è quella che lo ha
prodotto. Sul corpo libero si registra il **sovraccarico**, non il peso mosso, e chi non
arriva al proprio peso corporeo registra zero — che è ciò che fanno davvero le trazioni
di chi comincia.

Verificato dal rapporto: rapporto panca/squat mediano **0,73** (intervallo 0,45–1,08),
**zero** casi con panca oltre lo squat, forza relativa in panca 0,55×–1,14× il peso
corporeo fra il decimo e il novantesimo percentile.

### 2. Lo stallo è una fase, non un archetipo

Cinque archetipi — principiante 25%, intermedio in plateau 30%, incostante 20%, avanzato
15%, abbandono 10% — ma lo stallo **non è uno di loro**: è uno dei tre stati di una
macchina a fasi (crescita, plateau, deload) che ogni coppia (utente, esercizio) attraversa
per conto suo. Da qui nascono i casi difficili che #17 chiedeva esplicitamente:
piatto-poi-riparte (uscita dal plateau con il tetto alzato), rumoroso-ma-in-crescita
(l'archetipo incostante ha rumore al 4,5%), deload volontario (calo del 10% per due o tre
sessioni, poi ritorno). Le pause lunghe fanno perdere forza, e al ritorno si risale.

Lo stato nascosto della macchina **non finisce in nessun CSV**. Le etichette si ricavano
dai dati generati con la stessa regola che gira sui dati reali: prenderle dal generatore
sarebbe la circolarità che [ADR-0004](adr/0004-ground-truth-dello-stallo-dal-futuro-della-finestra.md)
ha già escluso.

### 3. Storico variabile, non uniforme

Una popolazione in cui tutti hanno la stessa anzianità non esiste, e soprattutto non
serve. Lo storico va da **0,5 a 24,0 mesi**, mediana 10,2:

- **sei veterani** a 15–18 mesi, che riempiono la finestra a 12 mesi delle analisi di
  volume;
- **l'utente della demo a 24 mesi tondi**, unico storico dichiarato invece che
  sorteggiato: due anni coprono i 12 mesi delle analisi di volume *più* un anno di
  confronto dietro, così `TruncMonth` ha due cicli da mettere a fianco invece di uno
  troncato. Prima ne aveva 17,2, ma per caso — `demo064` non è fra i sei veterani;
- la maggior parte fra 4 e 12 mesi;
- **quattro utenti sotto i 21 giorni**, apposta, perché la pagina dello stallo possa
  mostrare dal vivo lo stato «dati insufficienti — 4 allenamenti su 6» che #17 vuole
  presentato come avanzamento e non come errore.

Anche la frequenza è variabile (1–5 sedute a settimana, mediana 2,8). È l'unica ancora di
realismo su cui il generatore **diverge deliberatamente** dai dati reali di Lorenzo, che
stanno a 4,2: quel 4,2 è una persona sola, molto costante, e replicarlo su cento utenti
produrrebbe una palestra di fanatici.

### 4. La popolazione si concentra su un core di 22 esercizi

Il catalogo ha 100 voci, ma #16 non mostra il percentile sotto i 20 utenti su un
esercizio. Spargere cento utenti su cento esercizi lo farebbe tacere ovunque, quindi ogni
utente pesca il **core con probabilità 0,80** e completa con una coda pescata dal resto.

Risultato misurato: **tutti e 22** gli esercizi del core superano la soglia (minimo 36
utenti, mediana 78), e la coda resta sotto — il che è utile, non un difetto: all'orale la
riga «percentile non disponibile» si può mostrare accanto a una che funziona.

### La classifica composita resta fuori, e ora si sa perché

La mappa teneva in nebbia una **classifica di forza generale** sui tre fondamentali, stile
«total», e ne faceva dipendere il ritorno da una misura che toccava a questo ticket:
panca, squat e stacco sono comuni a quasi tutti, o escluderebbero mezza popolazione?

Misurato: panca 78 utenti, squat 84, stacco 82 — ma **tutti e tre insieme solo 55 su
100**. Una classifica composita ne escluderebbe **45**. La misura conferma la decisione
già presa in #33 di scartarla, e questa volta con un numero invece che con un'intuizione.
La nebbia si chiude: la voce esce dalla mappa e va fra le cose fuori scopo.

### 5. Riscaldamenti e serie non completate

Il 19% delle serie risulta non completato, esattamente come nello storico reale, e il
generatore produce anche serie di `warmup` e `rampUp` sui multiarticolari pesanti. Questi
ultimi sono una divergenza voluta dai dati reali, che non ne contengono nessuno: senza di
loro il filtro `working` che ogni analisi applica non filtrerebbe niente, e all'orale non
dimostrerebbe niente.

## Il risultato che il ticket non si aspettava: la regola di #17 va emendata

#17 chiedeva ≥ 1500 finestre etichettabili con la classe `stallo` fra il 15% e il 35%.
Il primo requisito è saturo con niente — anche tre mesi di storico per cento utenti danno
decine di migliaia di finestre. **Il secondo non si raggiungeva**: prima taratura 74,8%,
poi 58,3%, poi 45,1% di stallo, con parametri via via più generosi.

Non era il generatore a sbagliare. Misurando la regola contro serie sintetiche pure:

| crescita vera per sessione | probabilità che la regola dica «stallo» |
| --- | --- |
| 0% (piatto) | 88,5% |
| 0,2% | 76,8% |
| 0,5% | 53,0% |
| 1,0% | 19,5% |
| 1,5% | 5,3% |

Il gradino è **stretto**: sotto lo 0,5% a sessione una crescita reale è indistinguibile da
uno stallo, sopra l'1,5% non lo è quasi mai. Ma un intermedio cresce davvero fra lo 0,5%
e l'1% a sessione, e un avanzato meno: la banda 15–35% richiedeva implicitamente una
popolazione di soli principianti, cioè proprio le «salite pulite» che #17 voleva evitare.

C'è anche una **distorsione strutturale**: la regola confronta il massimo di 6 sessioni
con il massimo delle 4 successive. Il massimo di sei estrazioni è più alto del massimo di
quattro anche senza nessuna tendenza, quindi una serie perfettamente piatta viene letta
come stallo nel 60% dei casi già a soglia zero, contro il 50% che darebbero finestre
simmetriche.

La spazzata su orizzonte e soglia, misurata sulla popolazione finale:

| orizzonte futuro | soglia +0% | +1% | +2% |
| --- | --- | --- | --- |
| 4 sessioni | 34,3% | 37,6% | **42,2%** |
| 6 sessioni | 25,0% | 27,5% | **31,0%** |
| 8 sessioni | 18,5% | 20,2% | 22,9% |
| 10 sessioni | 15,1% | 16,4% | 18,6% |

**Emendamento proposto a #17: l'orizzonte futuro passa da 4 a 6 sessioni**, lasciando la
soglia del 2% dov'è. Con quel solo cambio la classe `stallo` sta al **31,0%**, dentro la
banda, senza toccare un solo parametro del generatore. La motivazione non è di comodo: un
esercizio si allena circa una volta e mezzo a settimana, quindi 4 sessioni sono meno di
tre settimane — troppo poco per dichiarare uno stallo — mentre 6 sono all'incirca un mese.

Il resto della regola di #17 regge alla verifica. La diagnostica che incrocia l'etichetta
con la fase nascosta del generatore — mai usata come etichetta, solo come controllo —
mostra che la fase `plateau` viene letta come stallo nel 57,4% dei casi contro il 23,1%
della fase `crescita`: il segnale c'è ed è forte, ed è esattamente ciò che il
classificatore dovrà imparare a leggere dalle sei feature.

## Dove vive il generatore

**Management command `seed_synthetic` con seed fisso, nessuna fixture committata.** Nel
repo entra il generatore, non i dati: i CSV prodotti pesano **13 MB**, e una fixture JSON
equivalente ne peserebbe molti di più in un repo d'esame che il prof deve clonare.

Il seed è `20260907` e l'esecuzione è **verificata identica** fra due esecuzioni
consecutive: è quello a tenere fermi i numeri fra oggi e l'orale.

Il prototipo **non è** quel comando: è stato scritto quando il progetto Django non
esisteva (non c'era `manage.py`), quindi genera su CSV. Il comando esiste da
[#75](https://github.com/cavallinilorenzo/progetto-django-uni/issues/75), sta in
`training/management/commands/seed_synthetic.py` e scrive nei modelli con `bulk_create`.
Il prototipo resta nel repo come sorgente del ragionamento e del rapporto qui sopra.

Il porting ha una proprietà che vale la pena dichiarare: il comando produce **la stessa
popolazione**, non una equivalente. Consuma il generatore casuale nello stesso ordine del
prototipo, ed è stato verificato riga per riga contro i suoi CSV su tutte e sei le
tabelle — 296.724 serie comprese. È da lì che discende il fatto che le misure di questo
documento restino valide senza essere ri-misurate a ogni seeding: in particolare le due
sullo stallo, che sono proprietà della **regola di etichettatura** applicata a questa
popolazione, e riscriverle nel comando significherebbe tenerne una seconda copia dentro
il seeding. A tenerle ferme sono i conteggi esatti, che i test di `training/tests.py`
proteggono.

## Volume prodotto

| | |
| --- | --- |
| utenti | 100 |
| allenamenti | 11.855 |
| serie | 296.724 |
| schede (di cui pubbliche) | 199 (58) |
| voti | 887 |

I voti hanno distribuzione **a coda lunga con un livello di fondo**: la scheda più votata
ne ha 61, la **mediana è 12**, cinque schede pubbliche ne hanno zero. La mediana non è
estetica — [#33](https://github.com/cavallinilorenzo/progetto-django-uni/issues/33) ne
chiede **almeno 8**, perché sotto quella soglia la media bayesiana con `C = 3` è dominata
dal prior e la classifica sociale finisce per ordinare il rumore. Le schede a zero voti
restano lo stesso: una scheda pubblicata ieri non ne ha, ed è il caso che la media
bayesiana deve saper gestire.

Le **296.724 serie** sono il numero che la mappa aspettava per decidere se materializzare
i valori derivati: quella scelta resta aperta e resta subordinata a una misura vera delle
query, ma ora si sa su quante righe misurare.

## Gli utenti sintetici si dichiarano

Booleano `is_synthetic` sull'utente ed etichetta «utente dimostrativo» dove i loro nomi
compaiono: classifiche, percentile, schede pubbliche. Il percentile li conta nella
popolazione insieme agli utenti veri, come vuole #16, ma una classifica in cui una persona
reale è circondata da cento profili finti **senza che sia scritto da nessuna parte** è
una cosa che un esaminatore attento nota e chiede. La risposta migliore è che c'era già
scritto.

## L'utente della demo

#17 vuole che la pagina dello stallo si dimostri su un utente sintetico «scelto e nominato
in anticipo». Lo sceglie il rapporto, non la fretta del giorno dell'orale:

**`demo064` — Martina Longo**, archetipo intermedio in plateau, **24 mesi** di storico,
**1904 finestre etichettabili**. I due anni sono dichiarati in `DEMO_MONTHS`, non
sorteggiati: prima ne aveva 17,2 e 1199 finestre, e li aveva per caso.
