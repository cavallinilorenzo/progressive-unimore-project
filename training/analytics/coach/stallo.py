"""Il deload — l'unica azione che il coach propone in risposta a uno stallo.

**Una singola sessione al 90% del massimo di finestra**, poi si torna alla
doppia progressione da quel carico. Le altre tre risposte possibili sono state
scartate in `05-coach-e-stallo.md` per ragioni misurabili: **cambiare
esercizio** romperebbe la serie storica su cui girano stallo, record e
percentili — il consiglio distruggerebbe il dato che lo ha prodotto;
**aumentare la frequenza** non ha nessuna query dietro, perché niente qui
misura il recupero; **aumentare le ripetizioni** non è una risposta allo
stallo, è la doppia progressione ordinaria.

Il deload è **proposto, mai rilevato**: riconoscere un ciclo di scarico dai
dati è fuori dai confini di #11 e ribadito da ADR-0004.

Ha un modulo suo per la regola del pacchetto — **un tipo di consiglio guadagna
un modulo solo se ha una query propria** — e la query propria è quella qui
sotto, che è anche la scoperta di questo ticket.

## Il «massimo di finestra» del deload non è `Finestra.massimo`

La spec dice «90% del **massimo di finestra**», e #114 si aspettava che questo
modulo leggesse `Finestra.massimo`. Non lo legge, e la ragione è aritmetica
prima che empirica.

`Finestra.massimo` è il massimo **massimale stimato** (Epley), che è la
metrica su cui gira tutto il rilevamento. Ma Epley è
`carico × (1 + reps/30)`, quindi il 90% di un massimale stimato supera il
carico che l'ha prodotto ogni volta che quella serie aveva **4 ripetizioni o
più**: `0,9 × (1 + reps/30) ≥ 1` per `reps ≥ 3,33`. Un deload calcolato così
non sarebbe un deload, sarebbe un aumento — e proprio sull'esercizio in cui
l'utente è bloccato.

**Misurato il 2026-09-10 su `cavallinilorenzo` (pk 64):** degli 11 esercizi in
stallo, il 90% del massimo Epley è **sopra il carico più pesante della
finestra in tutti e 11**. Sulla panca piana la finestra ha un massimo Epley di
143,3 e un carico massimo di 120 kg: il «deload» direbbe **129 kg**, nove chili
*più* del massimo mai sollevato in quella finestra. È il modo di sbagliare che
la regola 2 della mappa #111 esiste per intercettare — un numero plausibile,
una pagina perfetta, e un consiglio falso.

La base è quindi il **carico di lavoro più pesante della finestra**, nella
stessa unità in cui l'utente lo riscrive nel form (`WorkoutSet.weight`,
bilanciere compreso, mai `EFFECTIVE_LOAD`) — la stessa scelta di `carico.py`,
per la stessa ragione: la domanda è *cosa scrivo la prossima volta*.

Le due letture di «massimo di finestra» restano **diverse e dichiarate**, non
riconciliate, come le due finestre della costanza (#112): il rilevamento chiede
se la finestra è piatta e guarda i massimali, il deload chiede da quale bilanciere
ripartire e guarda i carichi.

## L'arrotondamento scende di incrementi interi da un carico davvero sollevato

Il 90% quasi mai cade sulla griglia dell'attrezzo. Si scende quindi dal massimo
di finestra di **un numero intero di `Equipment.load_increment_kg`**, il più
piccolo che porti a 90% o sotto: è la costruzione di `carico.py` percorsa
all'indietro, e garantisce che il carico proposto sia caricabile esattamente
come lo era quello da cui parte.

**Non** «il multiplo dell'incremento più vicino sotto il 90%», che è la lettura
ingenua: i multipli di 2,5 partendo da zero includono 2,5 e 5 kg, che su un
bilanciere da 20 kg non esistono. Ancorare a un carico vero è l'unica griglia
che questo progetto può giustificare.

Il prezzo si vede quando il massimo di finestra **non sta** sulla griglia
dell'attrezzo, e sui dati veri capita: `pk 64` ha 17,5 kg di massimo sul crunch
alla macchina, che ha incremento 5 — il deload scende a 12,5 kg, cioè al 71%
invece che all'86% del multiplo di 5 più vicino. Va bene, e la direzione conta:
uno scarico più profondo del necessario è prudente, un carico non caricabile è
un consiglio che non si può eseguire.

## Il deload non si ricorda: si rilegge dai dati

Non si persiste niente (ADR-0012), quindi la domanda «l'ha già fatto?» non ha
una memoria a cui rivolgersi — e senza risposta il coach direbbe «scarica» a
ogni ricarica finché lo stallo dura, cioè per settimane, mentre la spec dice
**una singola sessione**.

La risposta non serve ricordarla perché è **scritta nel log**: se l'ultima
sessione della finestra sta già a quel carico o sotto, il deload è stato fatto
(o l'utente è comunque già sceso), e il consiglio tace lasciando la parola alla
doppia progressione — che è esattamente il «poi si torna alla doppia
progressione da quel carico» della spec.

**Misurato il 2026-09-10 su `pk 64`:** degli 11 esercizi in stallo, **4** hanno
l'ultima sessione già a quel livello o sotto — squat, military press, calf
raise in piedi, torsioni russe — e ricevono la doppia progressione invece di un
secondo «scarica». Il meccanismo non è una promessa: si vede sui dati della
demo.

## Attrezzo a incremento zero: nessun numero, e si dice

Su `bodyweight` e `band` il carico non ha un passo con cui scendere, quindi il
deload non ha un numero — è lo stesso confine di #113 visto dall'altra parte.
Il consiglio **c'è lo stesso** e resta azionabile (una sessione più leggera:
meno ripetizioni per serie, o una variante più facile), e il `limite` dichiara
che il coach non sa scegliere quel passo. Due dei 28 esercizi di `pk 64` sono
qui — crunch a terra e sollevamento gambe alla sbarra — e sono entrambi in
stallo, quindi il ramo si guarda davvero all'orale.

Qui il consiglio **non** tace mai finché lo stallo dura: senza un numero non
c'è modo di leggere dal log se la sessione più leggera sia stata fatta, e
l'alternativa sarebbe cedere la parola alla doppia progressione, cioè dire
«aggiungi una ripetizione» a chi è bloccato — «per sempre corretto e per sempre
inutile», il guasto che #113 ha chiamato per nome.
"""

from decimal import Decimal

from django.db.models import Max

from training.analytics import plateau
from training.analytics.coach.consiglio import Consiglio, carico_in_frase, kg
from training.models import WorkoutSet

#: La frazione del massimo di finestra da cui si riparte. È l'euristica della
#: spec, e si dichiara tale in pagina: non esce da nessuna misura di questo
#: progetto, e non c'è niente qui dentro che possa validarla.
FRAZIONE_DEL_DELOAD = Decimal("0.90")


def carichi_della_finestra(user, exercise, finestra):
    """I carichi di punta della finestra, un numero per giorno, in ordine.

    **Una query**, ed è l'unica del pacchetto che guarda dentro una finestra
    invece che dentro le ultime due sessioni.

    Il filtro è sui **giorni della finestra** e non su un intervallo di date:
    `finestra.sessioni` porta già le date locali, e un `__date__in` seleziona
    esattamente le sedute su cui il verdetto è stato dato. Un `gte` sul primo
    giorno prenderebbe anche una seduta che la finestra ha escluso — quella
    fatta solo sopra le 12 ripetizioni, che A3 non vede — e il deload
    partirebbe da un carico che il rilevamento non ha guardato.

    `working()` e non il solo `set_type`: qui, al contrario di `carico.py`, le
    serie non completate non servono a niente — non c'è nessun quarto caso da
    riconoscere, e un carico scritto su una serie saltata non è un carico
    sollevato.
    """
    righe = (
        WorkoutSet.objects.working()
        .filter(
            workout__user=user,
            exercise=exercise,
            workout__started_at__date__in=[s.giorno for s in finestra.sessioni],
        )
        .values("workout__started_at__date")
        .annotate(punta=Max("weight"))
        .order_by("workout__started_at__date")
    )
    return [(riga["workout__started_at__date"], riga["punta"]) for riga in righe]


def deload(base, incremento):
    """Il carico del deload: da `base` giù di incrementi interi, fino a ≤ 90%.

    `None` quando non c'è una griglia su cui scendere — attrezzo a incremento
    zero, o una base non positiva, che è lo stesso caso visto dal corpo libero
    senza zavorra.

    Il ciclo termina sempre: `incremento > 0` e l'obiettivo è strettamente
    sotto la base, quindi bastano `ceil(base × 0,1 / incremento)` passi. È
    scritto come ciclo e non come divisione perché il numero di passi è la
    cosa che il consiglio dice in pagina — *«tre incrementi sotto»* — e
    ricavarlo da una divisione intera su `Decimal` sarebbe la stessa riga
    scritta in modo da doverla rileggere due volte.
    """
    base = Decimal(base)
    incremento = Decimal(incremento)
    if incremento <= 0 or base <= 0:
        return None

    obiettivo = base * FRAZIONE_DEL_DELOAD
    passi = 0
    carico = base
    while carico > obiettivo:
        passi += 1
        carico = base - passi * incremento
    return carico, passi


def consiglio_di_stallo(user, exercise, stato=None):
    """Il deload su una coppia (utente, esercizio), o `None`.

    `None` in tre casi, e sono tre silenzi diversi:

    1. **Non c'è stallo** — o non c'è ancora un verdetto. Non è il mestiere di
       questa funzione dirlo: lo stato di progressione lo mostra la pagina, e
       questo è un consiglio, che compare solo quando ha qualcosa da far fare.
    2. **La finestra non ha carichi da leggere.** Non dovrebbe capitare — la
       finestra esiste solo se ci sono sedute — ed è la guardia che tiene la
       funzione muta invece di farla sbagliare su un caso non previsto.
    3. **Il deload è già stato fatto**, cioè l'ultima seduta della finestra sta
       già a quel carico o sotto. È il silenzio che impedisce al coach di dire
       «scarica» per settimane, e cede la parola alla doppia progressione.

    `stato` si passa quando il chiamante ce l'ha già: il dettaglio esercizio lo
    calcola comunque per il riquadro «Stato di progressione», e allora questo
    consiglio costa **una** query invece di due. È lo stesso patto con cui la
    dashboard passa la heatmap al coach (#112) e la pagina passa le righe di A3
    allo stato (#114) — non è una cache, è il chiamante che non fa richiedere
    una risposta che ha in mano.
    """
    stato = stato or plateau.stato_progressione(user, exercise)
    if not stato.e_stallo:
        return None

    carichi = carichi_della_finestra(user, exercise, stato.finestra)
    if not carichi:
        return None

    base = max(punta for _, punta in carichi)
    ultimo = carichi[-1][1]
    sessioni = stato.finestra.sessioni_senza_record
    quante = f"{sessioni} session{'e' if sessioni == 1 else 'i'}"
    proposto = deload(base, exercise.equipment.load_increment_kg)

    if proposto is None:
        return Consiglio(
            tipo="stallo",
            titolo="Fai una sessione più leggera",
            azione=(
                f"Su {exercise.name} il carico è fermo: chiudi una sessione "
                "sotto il tuo solito — meno ripetizioni per serie, o una "
                "variante più facile — e riparti da lì con la doppia "
                "progressione."
            ),
            misura=(
                f"Nessun record personale da {quante}, su una finestra di "
                f"{stato.avanzamento}"
            ),
            limite=(
                f"Su {exercise.equipment.label_it} l'incremento di carico è "
                "zero, quindi il coach non ha una griglia su cui calcolare di "
                "quanto scaricare: il 90% è un numero che qui non esiste, e "
                "quanto alleggerire lo scegli tu."
            ),
            esercizio=exercise,
        )

    carico, passi = proposto
    if ultimo <= carico:
        return None

    return Consiglio(
        tipo="stallo",
        titolo="Scarica una sessione",
        azione=(
            f"Fai una sola sessione di {exercise.name} a "
            f"{carico_in_frase(carico)} — il 90% dei {kg(base)} kg più pesanti "
            f"della finestra, arrotondato giù di {passi} "
            f"increment{'o' if passi == 1 else 'i'} da "
            f"{kg(exercise.equipment.load_increment_kg)} kg — e da lì riparti "
            "con la doppia progressione."
        ),
        misura=(
            f"Nessun record personale da {quante}; nella finestra il carico "
            f"più pesante è {kg(base)} kg, l'ultima seduta {kg(ultimo)} kg"
        ),
        limite=(
            "Il 90% è un'euristica, non una misura di questo progetto: "
            "niente qui dentro sa se il tuo recupero abbia bisogno di più o di "
            "meno. È una sessione sola, e il coach non riconosce i cicli di "
            "scarico più lunghi — nel modello non c'è niente che li rappresenti."
        ),
        esercizio=exercise,
    )
