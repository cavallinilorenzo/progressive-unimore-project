"""Genera la popolazione sintetica di Progressive: 100 utenti con storico credibile.

    python manage.py migrate
    python manage.py load_catalog     # i 100 esercizi devono esistere...
    python manage.py seed_synthetic   # ...perché il generatore ci si appoggia

Le classifiche, i percentili e il rilevamento dello stallo hanno bisogno di una
popolazione, e non esiste un dataset pubblico di log di allenamento veri. Qui si
genera — ma in modo che le analisi che ci gireranno sopra significhino qualcosa.
Le ragioni per esteso stanno in `docs/generatore-sintetico.md` e in `06-dati.md`;
qui si ripetono solo quelle che il codice deve rispettare riga per riga.

**Nel repo entra il generatore, non i dati.** I CSV prodotti dal prototipo pesano
13 MB e una fixture JSON equivalente molti di più: chi clona rigenera, ed è il
seed fisso a tenere fermi i numeri fra oggi e l'orale.

Tre cose che questo file non fa, e ognuna è una decisione:

1. **Non scrive lo stato nascosto da nessuna parte.** La macchina a tre fasi
   (crescita, plateau, deload) e l'archetipo vivono solo dentro il generatore:
   non sono campi del modello e l'applicazione non li conosce. Se ci finissero,
   la tentazione di usarli come etichetta del ML tornerebbe, ed è la circolarità
   che ADR-0004 rifiuta.
2. **Non sorveglia la plausibilità dei carichi**, perché non ci sono carichi
   implausibili da intercettare: nascono tutti dalla stessa catena
   `massimale = peso corporeo × rapporto dell'esercizio × forza dell'utente ×
   progressione(t) × rumore`, quindi la panca da 140 con lo squat da 60 non è
   sorvegliata, è impossibile per costruzione.
3. **Non ri-misura la regola di etichettatura di ADR-0004.** Le due misure che
   la riguardano — ≥ 1500 finestre etichettabili, classe `stallo` al 31,0% con
   orizzonte a 6 — sono proprietà *di quella regola applicata a questa
   popolazione*, misurate nel rapporto del prototipo. Riscriverle qui
   significherebbe tenere una seconda copia della regola dentro un comando di
   seeding, che la fase 2 dovrebbe poi non far divergere. A tenerle ferme è
   invece l'**identità** della popolazione: questo comando consuma il generatore
   casuale nello stesso ordine del prototipo, quindi produce gli stessi utenti,
   gli stessi allenamenti e le stesse serie — e i conteggi esatti, verificati dai
   test, sono la guardia che quell'identità non si è rotta.

   **Quell'identità è un patto a due, e si è già dovuto onorare una volta.**
   `DEMO_MONTHS` è nato qui, e la stessa clausola è stata scritta anche nel
   prototipo: senza, le due popolazioni divergevano e le due misure sopra
   restavano appese a una popolazione che non esisteva più. Sono state **rifatte**
   girando il prototipo, non estrapolate — 26.948 finestre e 31,0%, entrambe
   dentro i requisiti. Chi tocca `make_users` di qui in avanti tocca due file.

Il prototipo `scripts/prototype_seed_synthetic.py` resta nel repo come sorgente
del ragionamento e del rapporto di validazione. Non è questo comando: era codice
in stdlib pura, scritto quando il progetto Django non esisteva ancora.
"""

import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from training.models import (
    Exercise,
    Routine,
    RoutineExercise,
    User,
    Vote,
    Workout,
    WorkoutSet,
)

# --------------------------------------------------------------------------------
# Costanti di generazione
# --------------------------------------------------------------------------------

SEED = 20260907  # fisso: i numeri mostrati all'orale non devono cambiare
N_USERS = 100

# La data di fine dello storico è **fissa**, non `date.today()`: se scorresse col
# calendario, due esecuzioni a giorni diversi darebbero popolazioni diverse e il
# seed fisso non servirebbe a niente.
TODAY = date(2026, 9, 7)

# Tutti gli utenti sintetici condividono la stessa password. È un dato di
# dimostrazione, non un account: serve a poter entrare come `demo064` e mostrare
# dal vivo la pagina dello stallo, che sullo storico reale di Lorenzo è troppo
# corto per esistere.
DEMO_PASSWORD = "progressive"

# L'utente su cui si dimostra la pagina dello stallo, scelto in anticipo dal
# rapporto del prototipo (1904 finestre etichettabili) e non la mattina
# dell'orale.
#: L'indice con cui l'utente della demo nasce dentro `make_users`, prima che
#: `assegna_username` sostituisca i numeri coi nomi. Resta `demo064` perché è
#: **la posizione nella sequenza** del generatore casuale, non un nome: cambiarlo
#: sposterebbe l'utente e con lui il suo storico.
DEMO_USERNAME = "demo064"

#: Come si chiama all'arrivo. È l'account di Lorenzo, e i dati che ci stanno
#: dentro sono generati: la contraddizione è **voluta e dichiarata**, non
#: nascosta. `is_synthetic` resta vero anche su di lui, quindi dove il suo nome
#: compare in pubblico l'interfaccia scrive «utente dimostrativo» (ADR-0009) —
#: che all'orale è esattamente la frase da dire, invece di una da evitare.
DEMO_USERNAME_FINALE = "cavallinilorenzo"
DEMO_DISPLAY_NAME = "Lorenzo Cavallini"

#: Il nome che la posizione 64 **pesca** prima di essere ribattezzata. Non è
#: decorazione: è la guardia d'identità più economica che esista sullo stream del
#: generatore casuale — se una sola estrazione si spostasse, qui comparirebbe un
#: altro nome. Prima che l'utente della demo prendesse il nome di Lorenzo, questo
#: era il suo, e il rapporto lo verifica ancora.
NOME_SORTEGGIATO_ATTESO = "Martina Longo"

# Lo storico dell'utente della demo è l'unico **dichiarato** invece che
# sorteggiato, ed è due anni tondi. Prima era 17,2 mesi, ma per caso: `demo064`
# non è fra i sei veterani di `i <= 6`, e quella lunghezza gliela dava la banda
# del suo archetipo. Un numero che regge la demo per coincidenza è un numero che
# la prossima modifica del generatore può togliere senza che nessuno se ne
# accorga, quindi qui si dice.
#
# Due anni e non diciotto mesi perché è la finestra su cui gira tutta l'analisi
# mostrata all'orale: copre per intero i 12 mesi delle analisi di volume **più**
# un anno di confronto dietro, quindi `TruncMonth` ha due cicli stagionali da
# mettere a confronto invece di uno troncato.
DEMO_MONTHS = 24.0

EPLEY_MAX_REPS = 12  # oltre, Epley gonfia

# Il core: gli esercizi che quasi ogni scheda pesca, con il **rapporto di riferimento
# al peso corporeo** del massimale a forza 1.0 (un intermedio). È questa tabella a
# rendere strutturalmente impossibile la panca da 140 con lo squat da 60: tutti i
# carichi di un utente nascono dallo stesso peso corporeo e dallo stesso scalare.
# Per i manubri il rapporto è **per manubrio**, come si registra in palestra.
CORE_RATIOS = {
    "Squat con bilanciere": 1.40,
    "Panca piana con bilanciere": 1.00,
    "Stacco da terra con bilanciere": 1.75,
    "Stacco rumeno con bilanciere": 1.35,
    "Hip thrust con bilanciere": 1.80,
    "Military press con bilanciere": 0.62,
    "Panca inclinata con bilanciere": 0.85,
    "Panca piana presa stretta": 0.80,
    "Rematore con bilanciere": 0.90,
    "Curl con bilanciere": 0.45,
    "Trazioni alla sbarra": 1.20,
    "Dip alle parallele": 1.25,
    "Lat machine avanti": 0.85,
    "Pulley basso ai cavi": 0.85,
    "Leg press": 3.00,
    "Leg extension": 1.10,
    "Leg curl sdraiato": 0.70,
    "Calf raise in piedi alla macchina": 1.60,
    "Spinte su panca piana con manubri": 0.40,
    "Alzate laterali con manubri": 0.12,
    "Push down ai cavi con barra": 0.50,
    "Crunch ai cavi": 0.45,
}

# Rapporti di ripiego per la coda del catalogo, per gruppo muscolare: servono solo a
# tenere plausibili gli esercizi accessori, che nessuna analisi guarda da vicino.
TAIL_RATIOS = {
    "chest": 0.45,
    "back": 0.60,
    "shoulders": 0.20,
    "arms": 0.35,
    "legs": 1.00,
    "core": 0.30,
}

# La griglia di arrotondamento del carico: nessuno carica 43,7 kg.
#
# **Non è `Equipment.load_increment_kg`**, e la divergenza è voluta: quella colonna
# risponde alla domanda del coach — «di quanto può salire davvero il carico su
# questo attrezzo?» — e vale zero sul corpo libero e sull'elastico, dove il
# consiglio è di aggiungere ripetizioni e mai carico. Qui la domanda è un'altra:
# «su che griglia si posa un numero perché sembri scritto da una persona?», e sul
# corpo libero il sovraccarico si mette col disco da 2,5 kg. Due domande diverse
# sulla stessa parola; usare la colonna del coach come griglia darebbe una
# divisione per zero, e sui cavi sposterebbe tutti i carichi generati.
STEP_BY_EQUIPMENT = {
    "barbell": 2.5,
    "ez_bar": 2.5,
    "smith_machine": 2.5,
    "dumbbell": 2.0,
    "kettlebell": 4.0,
    "machine": 2.5,
    "cable": 1.25,
    "band": 1.0,
    "bodyweight": 2.5,
}

# I cinque archetipi. `gain` è il guadagno per sessione sul massimale latente in
# fase di crescita; `plateau_len` la durata media in sessioni di una fase piatta;
# `noise` la deviazione del rumore moltiplicativo sessione per sessione.
#
# I guadagni sono tarati **contro la regola di etichettatura**, non a occhio: con
# rumore al 3% una crescita sotto lo 0,6% a sessione è indistinguibile da uno
# stallo, ed è la ragione per cui qui il rumore è più basso e i guadagni più alti
# di quanto la carta suggerirebbe. La misura sta in `docs/generatore-sintetico.md`.
ARCHETYPES = {
    "principiante": dict(
        share=0.25, gain=0.055, p_plateau=0.020, plateau_len=4.0,
        noise=0.022, p_deload=0.005, days_week=(3, 4), months=(3, 12),
    ),
    "intermedio_plateau": dict(
        share=0.30, gain=0.022, p_plateau=0.050, plateau_len=7.0,
        noise=0.022, p_deload=0.010, days_week=(3, 5), months=(6, 18),
    ),
    "incostante": dict(
        share=0.20, gain=0.027, p_plateau=0.040, plateau_len=6.0,
        noise=0.045, p_deload=0.005, days_week=(1, 3), months=(4, 15),
    ),
    "avanzato": dict(
        share=0.15, gain=0.013, p_plateau=0.055, plateau_len=8.0,
        noise=0.018, p_deload=0.030, days_week=(4, 5), months=(12, 18),
    ),
    "abbandono": dict(
        share=0.10, gain=0.045, p_plateau=0.035, plateau_len=5.0,
        noise=0.026, p_deload=0.005, days_week=(2, 4), months=(2, 9),
    ),
}

# Le sedute della settimana per split, come liste di gruppi muscolari.
SPLITS = {
    "full_body": [["chest", "back", "legs", "shoulders", "arms", "core"]],
    "upper_lower": [
        ["chest", "back", "shoulders", "arms"],
        ["legs", "core"],
    ],
    "ppl": [
        ["chest", "shoulders", "triceps"],
        ["back", "biceps"],
        ["legs", "core"],
    ],
}

NOMI = [
    "Alessandro", "Giulia", "Marco", "Chiara", "Luca", "Sara", "Matteo", "Elena",
    "Andrea", "Francesca", "Davide", "Martina", "Simone", "Alice", "Federico",
    "Giorgia", "Riccardo", "Beatrice", "Tommaso", "Valentina", "Lorenzo", "Anna",
    "Filippo", "Sofia", "Stefano", "Ilaria", "Gabriele", "Camilla", "Nicola",
    "Aurora", "Emanuele", "Silvia", "Pietro", "Noemi", "Daniele", "Greta",
]
COGNOMI = [
    "Rossi", "Ferrari", "Russo", "Bianchi", "Romano", "Gallo", "Costa", "Conti",
    "Esposito", "Ricci", "Bruno", "Greco", "Marino", "Rizzo", "Moretti", "Barbieri",
    "Lombardi", "Giordano", "Colombo", "Mancini", "Longo", "Leone", "Martini",
    "Serra", "Vitale", "Caruso", "Ferrara", "Galli", "Villa", "Sala",
]

ROUTINE_NAMES = [
    "Push", "Pull", "Gambe", "Upper", "Lower", "Full body",
    "Petto e tricipiti", "Schiena e bicipiti", "Forza",
]


# --------------------------------------------------------------------------------
# Il catalogo, letto dal database
# --------------------------------------------------------------------------------


def read_catalog():
    """Legge i 100 esercizi e li restituisce nella forma che il generatore usa.

    **L'ordine è `pk` crescente, e non è un dettaglio estetico**: è l'ordine in cui
    `load_catalog` ha scritto le righe del CSV, ed è lo stesso ordine su cui il
    prototipo ha misurato. Il generatore pesca dagli esercizi con `random.sample` e
    `random.random`, quindi cambiare l'ordine cambierebbe ogni estrazione a valle e
    con essa i conteggi che i test proteggono. `Exercise.Meta.ordering` è per nome,
    ed è la ragione per cui qui l'`order_by` è esplicito.
    """
    exercises = []
    query = Exercise.objects.select_related("primary_muscle__group", "equipment")
    for row in query.order_by("pk"):
        exercises.append(
            dict(
                id=row.pk,
                name=row.name,
                muscle=row.primary_muscle.code,
                group=row.primary_muscle.group.code,
                equipment=row.equipment.code,
                bar=float(row.equipment.default_bar_weight_kg),
                is_core=row.name in CORE_RATIOS,
                ratio=CORE_RATIOS.get(
                    row.name, TAIL_RATIOS[row.primary_muscle.group.code]
                ),
            )
        )
    if not exercises:
        raise CommandError(
            "Il catalogo è vuoto: esegui prima `python manage.py load_catalog`."
        )
    missing = set(CORE_RATIOS) - {e["name"] for e in exercises}
    if missing:
        raise CommandError(
            f"Esercizi del core assenti dal catalogo: {sorted(missing)}"
        )
    return exercises


# --------------------------------------------------------------------------------
# Utenti
# --------------------------------------------------------------------------------


def make_users(rng):
    """Crea i 100 utenti sintetici: archetipo, peso corporeo, forza, storico.

    Lo storico è **variabile per costruzione**: sei veterani che riempiono la
    finestra a 12 mesi delle analisi di volume, la maggior parte fra 4 e 12 mesi, e
    quattro utenti sotto i 21 giorni perché la pagina dello stallo possa mostrare
    dal vivo lo stato «dati insufficienti» come avanzamento e non come errore.
    """
    pool = []
    for name, cfg in ARCHETYPES.items():
        pool += [name] * round(cfg["share"] * N_USERS)
    while len(pool) < N_USERS:
        pool.append("intermedio_plateau")
    rng.shuffle(pool)

    users = []
    for i, archetype in enumerate(pool[:N_USERS], start=1):
        cfg = ARCHETYPES[archetype]
        if i <= 6:
            months = rng.uniform(15, 18)        # i veterani della demo
        elif i <= 10:
            months = rng.uniform(0.3, 0.7)      # i «dati insufficienti»
        else:
            months = rng.uniform(*cfg["months"])
        # L'utente della demo prende `DEMO_MONTHS`, ma **dopo** che il sorteggio
        # è avvenuto: il numero si scarta invece di non estrarlo. Sembra uno
        # spreco ed è il contrario — il generatore casuale è una sequenza, e
        # saltare un'estrazione sposterebbe tutte quelle successive. Così di
        # tutta `make_users` cambia una cosa sola: lo `start` dell'utente 64.
        #
        # Il contenimento finisce qui, e vale detto: in `generate` ogni utente
        # consuma un numero di estrazioni che dipende dalla **lunghezza** del
        # suo storico, quindi da 64 in poi il flusso slitta e i 37 utenti a
        # valle cambiano allenamenti. Gli utenti 1–63 no — e lì stanno sia i sei
        # veterani sia i quattro «dati insufficienti», cioè le due proprietà
        # della popolazione che la demo non può permettersi di perdere.
        if f"demo{i:03d}" == DEMO_USERNAME:
            months = DEMO_MONTHS
        body_mass = round(min(105.0, max(48.0, rng.gauss(73, 12))), 1)
        users.append(
            dict(
                id=i,
                username=f"demo{i:03d}",
                display_name=f"{rng.choice(NOMI)} {rng.choice(COGNOMI)}",
                body_mass_kg=body_mass,
                archetype=archetype,
                # forza relativa: lognormale, così la coda dei forti è più lunga di
                # quella dei deboli, come in una palestra vera
                strength=round(min(1.7, max(0.55, rng.lognormvariate(0, 0.20))), 3),
                # quanto margine di crescita ha davanti: chi comincia ne ha molto,
                # un avanzato quasi niente
                ceiling=round(rng.uniform(1.30, 1.95), 3),
                days_week=rng.randint(*cfg["days_week"]),
                split=rng.choice(["full_body", "upper_lower", "ppl", "ppl"]),
                start=TODAY - timedelta(days=int(months * 30.4)),
                # l'abbandono smette a un certo punto e non torna
                quit_after=rng.uniform(0.35, 0.8) if archetype == "abbandono" else None,
            )
        )
    assegna_username(users)
    return users


def assegna_username(users):
    """Trasforma `demo001` nel nome della persona: `camilla.martini`.

    Un `demo064` in cima alla dashboard e nelle classifiche fa sembrare la
    popolazione un riempitivo, e i nomi veri **c'erano già** — il generatore
    pescava `display_name` e lo scriveva in `first_name`/`last_name`, ma ogni
    template mostra `get_username`, che era il numero. Qui si allinea l'uno
    all'altro.

    **Non consuma nessuna estrazione**, ed è la proprietà che rende questa
    funzione innocua: la deduplica scorre `COGNOMI` in ordine invece di
    ripescare, quindi la popolazione — allenamenti, serie, schede, voti — resta
    identica al bit. Cambiano solo le etichette, e nessuna delle cifre che i
    test tengono ferme.

    La collisione va gestita e non è un caso di scuola: 36 nomi per 30 cognomi
    fanno 1080 combinazioni, ma su 100 estrazioni il paradosso del compleanno ne
    fa collidere **quattro**. Non si risolve con un suffisso numerico, che
    riporterebbe il numero da cui si sta scappando: si cambia cognome.
    """
    presi = set()
    for u in users:
        if u["username"] == DEMO_USERNAME:
            # Il nome **sorteggiato** si conserva prima di sovrascriverlo, e non
            # per nostalgia: era la guardia d'identità più economica dell'intero
            # stream — se una sola estrazione si spostasse, l'utente 64 pescherebbe
            # un altro nome. Sovrascriverlo e basta avrebbe buttato via il
            # controllo insieme al nome. Il rapporto lo verifica ancora.
            u["nome_sorteggiato"] = u["display_name"]
            u["username"] = DEMO_USERNAME_FINALE
            u["display_name"] = DEMO_DISPLAY_NAME
            presi.add(DEMO_USERNAME_FINALE)
            continue
        nome, cognome = u["display_name"].split(" ")
        if slug_utente(nome, cognome) in presi:
            # Il primo cognome libero in ordine di elenco: deterministico, quindi
            # due esecuzioni danno gli stessi nomi senza che il seed c'entri.
            cognome = next(
                (c for c in COGNOMI if slug_utente(nome, c) not in presi), cognome
            )
            u["display_name"] = f"{nome} {cognome}"
        u["username"] = slug_utente(nome, cognome)
        presi.add(u["username"])


def slug_utente(nome, cognome):
    """`Camilla`, `Martini` → `camilla.martini`.

    Il punto separa perché è ciò che fa un'azienda vera, e rende il nome
    leggibile a colpo d'occhio in una classifica. Gli accenti non si tolgono
    perché in `NOMI` e `COGNOMI` non ce ne sono: se un giorno ce ne fossero,
    questo è il posto dove normalizzarli.
    """
    return f"{nome}.{cognome}".lower()


def pick_exercises(user, exercises, rng):
    """Sceglie il repertorio dell'utente: il core quasi sempre, la coda per realismo.

    Il percentile tace sotto i 20 utenti per esercizio: è questa funzione a decidere
    se quella soglia si raggiunge, ed è il motivo per cui il core si pesca con
    probabilità alta invece che uniformemente sulle 100 voci del catalogo. Spargere
    cento utenti su cento esercizi significherebbe **zero** esercizi sopra soglia,
    cioè nessun percentile e nessuna classifica in tutta la demo.
    """
    core = [e for e in exercises if e["is_core"]]
    tail = [e for e in exercises if not e["is_core"]]
    chosen = [e for e in core if rng.random() < 0.80]
    chosen += rng.sample(tail, rng.randint(6, 14))
    by_group = defaultdict(list)
    for e in chosen:
        by_group[e["group"]].append(e)
    return chosen, by_group


# --------------------------------------------------------------------------------
# Traiettoria del massimale: la macchina delle fasi
# --------------------------------------------------------------------------------


class Trajectory:
    """Il massimale latente di una coppia (utente, esercizio), sessione per sessione.

    Tre stati — crescita, plateau, deload — più il rumore. Lo stallo **non** è un
    archetipo di utente ma una fase che quasi tutti attraversano: è questa macchina
    a produrlo, ed è per questo che la percentuale finale si misura sui dati
    generati invece di essere dichiarata a priori.

    Lo stato di questa classe **non finisce in nessun campo del modello**: le
    etichette del ML si ricavano dai dati con la stessa regola che gira sui dati
    reali, mai da qui, o l'esperimento sarebbe circolare (ADR-0004).
    """

    def __init__(self, user, exercise, rng):
        cfg = ARCHETYPES[user["archetype"]]
        self.rng = rng
        self.cfg = cfg
        base = user["body_mass_kg"] * exercise["ratio"] * user["strength"]
        # ogni esercizio ha una sua confidenza: nessuno è ugualmente bravo su tutto
        self.value = base * rng.uniform(0.48, 0.66) * rng.uniform(0.94, 1.06)
        # Il tetto è generoso di proposito: con un tetto stretto la fase di
        # «crescita» diventa piatta di fatto appena ci si avvicina, e la regola di
        # etichettatura la legge — correttamente — come stallo.
        #
        # È un potenziale **dell'utente**, non del singolo esercizio: tirandolo per
        # esercizio in modo indipendente ricompare proprio l'incoerenza che la
        # catena del carico rende impossibile (misurato sul prototipo: un utente
        # con la panca sopra lo squat).
        self.ceiling = base * user["ceiling"] * rng.uniform(0.95, 1.05)
        self.state = "crescita"
        self.left = 0
        self.pre_deload = None

    def step(self):
        """Avanza di una sessione e restituisce il massimale latente."""
        cfg, rng = self.cfg, self.rng

        if self.state == "crescita":
            # il guadagno si spegne avvicinandosi al tetto: è il rendimento
            # decrescente vero, non un plateau imposto a mano
            room = max(0.0, 1 - self.value / self.ceiling)
            self.value *= 1 + cfg["gain"] * room
            if rng.random() < cfg["p_plateau"]:
                self.state, self.left = "plateau", max(
                    3, round(rng.expovariate(1 / cfg["plateau_len"]))
                )
            elif rng.random() < cfg["p_deload"]:
                self.state, self.left = "deload", rng.randint(2, 3)
                self.pre_deload = self.value
                self.value *= 0.90
        elif self.state == "plateau":
            self.value *= 1 + rng.gauss(0, 0.002)  # piatto, non immobile
            self.left -= 1
            if self.left <= 0:
                # piatto-poi-riparte: uno dei casi difficili che il ML deve vedere
                self.state = "crescita"
                self.ceiling *= rng.uniform(1.0, 1.06)
        elif self.state == "deload":
            self.left -= 1
            if self.left <= 0:
                self.state = "crescita"
                self.value = self.pre_deload * rng.uniform(1.0, 1.02)
        return self.value

    def detrain(self, days):
        """Una pausa lunga costa forza, e al ritorno si risale in fretta."""
        loss = min(0.14, 0.0022 * days)
        self.value *= 1 - loss
        self.state, self.left = "crescita", 0


# --------------------------------------------------------------------------------
# Generazione delle sessioni
# --------------------------------------------------------------------------------


def round_to(value, step):
    return max(step, round(value / step) * step)


def generate(users, exercises, rng):
    """Produce allenamenti e serie per tutti gli utenti."""
    workouts, sets = [], []
    wid = sid = 0

    for user in users:
        repertoire, by_group = pick_exercises(user, exercises, rng)
        traj = {e["name"]: Trajectory(user, e, rng) for e in repertoire}
        split = SPLITS[user["split"]]
        total_days = (TODAY - user["start"]).days
        end = user["start"] + timedelta(
            days=int(total_days * user["quit_after"])
            if user["quit_after"]
            else total_days
        )

        day = user["start"]
        day_index = 0
        last_seen = user["start"]
        while day <= end:
            # una pausa vera: vacanza, infortunio, vita
            if rng.random() < 0.010:
                pause = rng.randint(12, 45)
                day += timedelta(days=pause)
                for t in traj.values():
                    t.detrain(pause)
                continue

            # la settimana: `days_week` sedute distribuite, con salti
            if rng.random() > user["days_week"] / 7:
                day += timedelta(days=1)
                continue

            focus = split[day_index % len(split)]
            day_index += 1
            pool = []
            for g in focus:
                pool += by_group.get(g, [])
            if len(pool) < 4:
                pool = repertoire
            n_ex = min(len(pool), rng.randint(6, 9))
            todays = rng.sample(pool, n_ex)

            wid += 1
            started = datetime.combine(
                day, time(rng.randint(7, 20), rng.choice([0, 15, 30, 45]))
            )
            workouts.append(
                dict(
                    id=wid,
                    user_id=user["id"],
                    title=f"{user['split'].replace('_', ' ').title()} — giorno {day_index}",
                    started_at=started,
                    ended_at=started + timedelta(minutes=rng.randint(45, 95)),
                )
            )

            for order, ex in enumerate(todays, start=1):
                t = traj[ex["name"]]
                one_rm = t.step() * rng.lognormvariate(
                    0, ARCHETYPES[user["archetype"]]["noise"]
                )
                sid = emit_sets(sets, sid, wid, user, ex, one_rm, order, rng)
            last_seen = day
            day += timedelta(days=1)
        assert last_seen <= TODAY
    return workouts, sets


def emit_sets(sets, sid, wid, user, ex, one_rm, order, rng):
    """Scrive le serie di un esercizio in un allenamento.

    Il carico si ricava **invertendo Epley** dal massimale latente, così la stessa
    formula che le analisi useranno per stimarlo è quella che lo ha prodotto: il
    generatore e il motore analitico parlano la stessa lingua.

    `set_number` **riparte da 1 per ogni coppia (allenamento, esercizio)** e conta
    anche riscaldamento e avvicinamento. Il prototipo scriveva su CSV e ci metteva
    un contatore globale; qui c'è il vincolo `workout_set_unique` su
    `(workout, exercise, set_number)`, e numerare le serie efficaci da 1 accanto a
    un riscaldamento anch'esso numerato 1 sarebbe una collisione. Le analisi
    filtrano per `set_type`, non per numero, quindi la numerazione continua non
    toglie niente a nessuno e in pagina si legge come l'ordine di esecuzione.
    """
    step = STEP_BY_EQUIPMENT[ex["equipment"]]
    scheme = rng.choice([(5, 3), (8, 3), (10, 3), (12, 4), (6, 4), (10, 2)])
    target_reps, n_sets = scheme
    number = 0

    # riscaldamento e avvicinamento sui multiarticolari pesanti: senza di loro il
    # filtro `working` delle analisi non filtrerebbe niente e non dimostrerebbe niente
    if ex["is_core"] and ex["ratio"] >= 0.80 and order <= 3:
        for kind, frac, reps in (("warmup", 0.45, 12), ("rampUp", 0.75, 6)):
            w = weight_for(one_rm * frac, reps, ex, user, step)
            sid += 1
            number += 1
            sets.append(row(sid, wid, ex, number, reps, w, kind, True))

    for i in range(n_sets):
        reps = max(3, target_reps - rng.choice([0, 0, 0, 1, 1, 2]) * (i > 0))
        w = weight_for(one_rm, target_reps, ex, user, step)
        completed = rng.random() > 0.19  # gli 81% completati dei dati reali
        sid += 1
        number += 1
        sets.append(row(sid, wid, ex, number, reps, w, "working", completed))
    return sid


def weight_for(one_rm, reps, ex, user, step):
    """Epley invertito, poi arrotondato all'incremento dell'attrezzo.

    Sul corpo libero il carico registrato è il **sovraccarico**, non il peso mosso:
    il peso corporeo lo aggiunge il carico effettivo di ADR-0006, quindi qui si
    sottrae, e chi non arriva al proprio peso corporeo registra zero — che è
    esattamente ciò che fanno le trazioni di chi comincia.
    """
    raw = one_rm / (1 + reps / 30)
    if ex["equipment"] == "bodyweight":
        added = raw - user["body_mass_kg"]
        return round_to(added, step) if added >= step else 0.0
    return round_to(max(step, raw), step)


def row(sid, wid, ex, number, reps, weight, set_type, completed):
    return dict(
        id=sid,
        workout_id=wid,
        exercise_id=ex["id"],
        exercise_name=ex["name"],
        set_number=number,
        weight_kg=weight,
        reps=reps,
        set_type=set_type,
        is_completed=completed,
    )


# --------------------------------------------------------------------------------
# Schede e voti
# --------------------------------------------------------------------------------


def make_routines_and_votes(users, exercises, rng):
    """Schede pubbliche e voti: senza di loro la classifica sociale non esiste.

    La distribuzione dei voti è deliberatamente **sbilanciata** — poche schede molto
    votate, molte con zero — perché una classifica in cui tutti hanno tre voti non
    ordina niente e all'orale non dimostra niente.
    """
    routines, links, votes = [], [], []
    rid = lid = vid = 0
    public = []
    for user in users:
        for _ in range(rng.randint(1, 3)):
            rid += 1
            is_public = rng.random() < 0.30
            routines.append(
                dict(
                    id=rid,
                    user_id=user["id"],
                    name=rng.choice(ROUTINE_NAMES),
                    is_public=is_public,
                )
            )
            if is_public:
                public.append((rid, user["id"]))
            for order, ex in enumerate(
                rng.sample(exercises, rng.randint(5, 8)), start=1
            ):
                lid += 1
                # L'ordine di queste due estrazioni è quello del prototipo, e non è
                # indifferente: invertirle sposta ogni estrazione successiva e
                # cambia i voti generati più sotto. Misurato: 728 voti invece di 438.
                target_sets = rng.randint(3, 4)
                target_reps = rng.choice([5, 8, 10, 12])
                links.append(
                    dict(
                        id=lid,
                        routine_id=rid,
                        exercise_id=ex["id"],
                        position=order,
                        target_sets=target_sets,
                        target_reps=target_reps,
                        # L'estremo alto è **derivato**, non estratto: è ciò che la
                        # doppia progressione insegue, e una scheda che dichiara
                        # solo il minimo non la descrive. Derivato e non tirato a
                        # sorte perché una chiamata in più al generatore casuale
                        # sposterebbe tutto lo stream a valle, e con esso i voti.
                        target_reps_max=target_reps + 2,
                    )
                )

    # Popolarità a coda lunga, ma con un livello di fondo: sotto una mediana di 8
    # voti per scheda pubblica la media bayesiana con `C = 3` è dominata dal prior
    # e la classifica sociale finisce per ordinare il rumore. Le schede a zero voti
    # restano (una scheda pubblicata ieri non ne ha), ma sono una minoranza
    # dichiarata invece che il caso tipico.
    rng.shuffle(public)
    for _rank, (routine_id, owner) in enumerate(public, start=1):
        if rng.random() < 0.15:
            n = 0  # pubblicata da poco, o semplicemente ignorata
        else:
            n = max(1, round(rng.lognormvariate(math.log(13), 0.75)))
        voters = [u for u in users if u["id"] != owner]
        for voter in rng.sample(voters, min(n, len(voters))):
            vid += 1
            votes.append(
                dict(
                    id=vid,
                    routine_id=routine_id,
                    user_id=voter["id"],
                    score=rng.choices([1, 2, 3, 4, 5], weights=[3, 6, 18, 40, 33])[0],
                )
            )
    return routines, links, votes


# --------------------------------------------------------------------------------
# Persistenza
# --------------------------------------------------------------------------------

BATCH = 1000


def persist(users, workouts, sets, routines, links, votes):
    """Scrive la popolazione generata, in un solo blocco atomico.

    Gli `id` che il generatore si dà sono locali e vengono tradotti in chiavi vere
    con un **offset** sul massimo presente: il comando non presume di essere solo
    nel database, e in particolare non calpesta gli allenamenti che Lorenzo
    importerà dal form web dopo il seeding.
    """
    hashed = make_password(DEMO_PASSWORD)  # una volta sola: sono 100 utenti uguali
    User.objects.bulk_create(
        [
            User(
                username=u["username"],
                first_name=u["display_name"].split(" ")[0],
                last_name=u["display_name"].split(" ")[1],
                password=hashed,
                body_mass_kg=Decimal(str(u["body_mass_kg"])),
                is_synthetic=True,
            )
            for u in users
        ],
        batch_size=BATCH,
    )
    user_pk = dict(
        User.objects.filter(username__in=[u["username"] for u in users]).values_list(
            "username", "pk"
        )
    )
    user_pk = {u["id"]: user_pk[u["username"]] for u in users}

    w_offset = Workout.objects.aggregate(m=Max("pk"))["m"] or 0
    s_offset = WorkoutSet.objects.aggregate(m=Max("pk"))["m"] or 0
    r_offset = Routine.objects.aggregate(m=Max("pk"))["m"] or 0

    Workout.objects.bulk_create(
        [
            Workout(
                pk=w_offset + w["id"],
                user_id=user_pk[w["user_id"]],
                # `routine` resta nullo: le schede sintetiche sono un catalogo
                # sociale da votare, non il piano da cui questi allenamenti sono
                # nati, e legarli a caso inventerebbe una storia che nessuno ha
                # vissuto. ADR-0002 tiene comunque `title` come istantanea.
                routine=None,
                title=w["title"],
                started_at=aware(w["started_at"]),
                ended_at=aware(w["ended_at"]),
            )
            for w in workouts
        ],
        batch_size=BATCH,
    )
    WorkoutSet.objects.bulk_create(
        [
            WorkoutSet(
                pk=s_offset + s["id"],
                workout_id=w_offset + s["workout_id"],
                exercise_id=s["exercise_id"],
                set_number=s["set_number"],
                reps=s["reps"],
                weight=Decimal(f"{s['weight_kg']:.2f}"),
                set_type=s["set_type"],
                is_completed=s["is_completed"],
            )
            for s in sets
        ],
        batch_size=BATCH,
    )
    Routine.objects.bulk_create(
        [
            Routine(
                pk=r_offset + r["id"],
                user_id=user_pk[r["user_id"]],
                name=r["name"],
                is_public=r["is_public"],
            )
            for r in routines
        ],
        batch_size=BATCH,
    )
    RoutineExercise.objects.bulk_create(
        [
            RoutineExercise(
                routine_id=r_offset + link["routine_id"],
                exercise_id=link["exercise_id"],
                position=link["position"],
                target_sets=link["target_sets"],
                target_reps=link["target_reps"],
                target_reps_max=link["target_reps_max"],
            )
            for link in links
        ],
        batch_size=BATCH,
    )
    Vote.objects.bulk_create(
        [
            Vote(
                routine_id=r_offset + v["routine_id"],
                user_id=user_pk[v["user_id"]],
                score=v["score"],
            )
            for v in votes
        ],
        batch_size=BATCH,
    )


def aware(value):
    """`USE_TZ` è acceso: un `datetime` naive entrerebbe con un warning e un dubbio."""
    return timezone.make_aware(value, timezone.get_default_timezone())


# --------------------------------------------------------------------------------
# Il rapporto
# --------------------------------------------------------------------------------


def epley(weight, reps, ex, body_mass):
    """Massimale stimato sul **carico effettivo** (ADR-0006): il corpo libero somma
    il peso corporeo, altrimenti trazioni e piegamenti peserebbero zero."""
    load = weight + (body_mass if ex["equipment"] == "bodyweight" else 0.0)
    return load * (1 + reps / 30)


def coherence(users, exercises, workouts, sets):
    """L'autocontrollo del generatore: quante panche superano il proprio squat.

    La risposta dev'essere **una coda trascurabile**, e non perché un filtro la
    tagli: la catena del carico la rende rarissima. È il controllo che dimostra che
    la catena è ancora intatta dopo il porting, ed è aritmetica del generatore, non
    del motore analitico — che in fase 2 farà lo stesso calcolo per un'altra ragione.

    Fino a `DEMO_MONTHS = 24` la coda era **vuota**, e il controllo diceva «zero».
    Non era una garanzia strutturale: il rapporto panca/squat parte dai `CORE_RATIOS`
    ed è quindi lo stesso per tutti, ma `progression(t)` corre **per esercizio**, e
    più storico c'è più i due esercizi di un utente possono divergere. A due anni un
    utente su 56 arriva a 1,16 — col secondo più alto a 0,95. Non è la catena che si
    rompe, è la coda che si allunga, e in palestra quell'utente esiste davvero: è
    quello che spinge di panca e salta le gambe.

    La soglia resta al 2% di chi fa entrambi gli esercizi, perché ciò che il controllo
    deve intercettare non è l'eccezione, è la **mediana** che si sposta.
    """
    by_name = {e["name"]: e for e in exercises}
    owner = {w["id"]: w["user_id"] for w in workouts}
    body_mass = {u["id"]: u["body_mass_kg"] for u in users}
    best = defaultdict(dict)
    for s in sets:
        if s["set_type"] != "working" or not s["is_completed"]:
            continue
        if s["reps"] > EPLEY_MAX_REPS:
            continue
        uid = owner[s["workout_id"]]
        value = epley(
            s["weight_kg"], s["reps"], by_name[s["exercise_name"]], body_mass[uid]
        )
        name = s["exercise_name"]
        best[uid][name] = max(best[uid].get(name, 0.0), value)

    ratios = [
        p["Panca piana con bilanciere"] / p["Squat con bilanciere"]
        for p in best.values()
        if "Panca piana con bilanciere" in p and "Squat con bilanciere" in p
    ]
    absurd = sum(1 for r in ratios if r > 1.15)
    return ratios, absurd, best


def users_per_exercise(workouts, sets):
    owner = {w["id"]: w["user_id"] for w in workouts}
    counts = defaultdict(set)
    for s in sets:
        if s["set_type"] == "working":
            counts[s["exercise_name"]].add(owner[s["workout_id"]])
    return {name: len(uids) for name, uids in counts.items()}


# --------------------------------------------------------------------------------


class Command(BaseCommand):
    help = (
        "Genera la popolazione sintetica: 100 utenti con schede, allenamenti, "
        "serie e voti. Richiede un catalogo già caricato."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Cancella prima gli utenti sintetici già presenti, con tutto ciò "
                "che dipende da loro. Senza questo flag il comando si rifiuta di "
                "girare su un database già popolato."
            ),
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=SEED,
            help=(
                f"Seed del generatore casuale. Il valore di default ({SEED}) è "
                "quello su cui i numeri della documentazione sono misurati: "
                "cambiarlo dà una popolazione valida ma diversa."
            ),
        )

    def handle(self, *args, **options):
        existing = User.objects.filter(is_synthetic=True)
        if existing.exists():
            if not options["reset"]:
                raise CommandError(
                    f"Ci sono già {existing.count()} utenti sintetici. "
                    "Usa --reset per rigenerarli da capo."
                )
            self.stdout.write("Cancello la popolazione sintetica precedente…")
            existing.delete()

        rng = random.Random(options["seed"])
        exercises = read_catalog()
        users = make_users(rng)
        workouts, sets = generate(users, exercises, rng)
        routines, links, votes = make_routines_and_votes(users, exercises, rng)

        # Un solo blocco: una popolazione scritta a metà è peggio di nessuna
        # popolazione, perché le classifiche girerebbero su utenti senza storico
        # senza dirlo.
        with transaction.atomic():
            persist(users, workouts, sets, routines, links, votes)

        self.report(users, exercises, workouts, sets, routines, votes)

    def report(self, users, exercises, workouts, sets, routines, votes):
        """Il rapporto che dice se i numeri tornano, non solo che il comando è finito."""
        write = self.stdout.write

        write("")
        write(f"  utenti         {len(users):>8,}")
        write(f"  allenamenti    {len(workouts):>8,}")
        write(f"  serie          {len(sets):>8,}")
        write(f"  schede         {len(routines):>8,}")
        write(f"  voti           {len(votes):>8,}")
        write("")

        counts = users_per_exercise(workouts, sets)
        core = {k: v for k, v in counts.items() if k in CORE_RATIOS}
        core_ok = all(v >= 20 for v in core.values())
        write(
            f"  esercizi core sopra i 20 utenti   "
            f"{sum(1 for v in core.values() if v >= 20)} su {len(core)}   "
            f"{self._ok(core_ok)}"
        )

        short = sum(1 for u in users if (TODAY - u["start"]).days < 21)
        write(f"  utenti sotto i 21 giorni          {short}   {self._ok(short >= 1)}")

        public = [r for r in routines if r["is_public"]]
        per_routine = Counter(v["routine_id"] for v in votes)
        median_votes = statistics.median(
            [per_routine.get(r["id"], 0) for r in public] or [0]
        )
        write(f"  schede pubbliche                  {len(public)} su {len(routines)}")
        write(
            f"  voti per scheda pubblica (mediana) {median_votes:.0f}   "
            f"{self._ok(median_votes >= 8)}"
        )

        ratios, absurd, _best = coherence(users, exercises, workouts, sets)
        write(
            f"  panca / squat (mediana)           "
            f"{statistics.median(ratios):.2f} su {len(ratios)} utenti"
        )
        write(
            f"  panche sopra il proprio squat     {absurd} su {len(ratios)}   "
            f"{self._ok(absurd <= 0.02 * len(ratios))}"
        )

        months = sorted((TODAY - u["start"]).days / 30.4 for u in users)
        write(
            f"  storico in mesi                   "
            f"{months[0]:.1f} – {months[-1]:.1f}, mediana {statistics.median(months):.1f}"
        )
        # L'utente della demo è scelto una volta sola, dal rapporto del prototipo, e
        # non il giorno dell'orale: è su di lui che si mostra la pagina dello stallo,
        # perché lo storico reale di Lorenzo è troppo corto per superare la soglia.
        # Che sia ancora lui è anche il controllo d'identità più economico che
        # esista sull'intero stream del generatore: se una sola estrazione si
        # spostasse, `demo064` avrebbe un altro nome.
        demo = next(
            (u for u in users if u["username"] == DEMO_USERNAME_FINALE), None
        )
        sorteggiato = demo["nome_sorteggiato"] if demo else "—"
        write(
            f"  utente della demo                 {DEMO_USERNAME_FINALE} "
            f"— {DEMO_DISPLAY_NAME}   {self._ok(demo is not None)}"
        )
        # La guardia vera è questa riga, non quella sopra: il nome che l'utente 64
        # ha **pescato** prima di essere ribattezzato. Resta `Martina Longo`
        # finché lo stream è quello di sempre.
        write(
            f"  identità dello stream             posizione 64 pesca "
            f"«{sorteggiato}»   {self._ok(sorteggiato == NOME_SORTEGGIATO_ATTESO)}"
        )

        write("")
        write(
            "  Gli utenti sono dichiarati sintetici (is_synthetic) e l'interfaccia "
            "li marca\n  «utente dimostrativo» dove il loro nome compare: ADR-0009. "
            f"Password: {DEMO_PASSWORD}"
        )
        write("")
        write(
            self.style.SUCCESS(
                f"Popolazione sintetica creata: {len(users)} utenti, "
                f"{len(workouts):,} allenamenti, {len(sets):,} serie."
            )
        )

    def _ok(self, flag):
        return self.style.SUCCESS("OK") if flag else self.style.ERROR("NO")
