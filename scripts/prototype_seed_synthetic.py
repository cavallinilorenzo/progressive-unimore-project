#!/usr/bin/env python3
"""PROTOTIPO — generatore della popolazione sintetica di Progressive (ticket #18).

**Questo file è codice usa-e-getta.** Non è il management command `seed_synthetic`:
il progetto Django non esiste ancora (niente `manage.py`), quindi qui si genera su
CSV per poter *misurare* se il modello di popolazione regge. Ciò che va tenuto è la
forma del generatore — archetipi, catena del carico, macchina delle fasi — non queste
righe, che nella sessione di costruzione si riscrivono dentro `training/management/`.

    python3 scripts/prototype_seed_synthetic.py

Legge il catalogo versionato da `data/catalog/`, scrive i CSV in `data/synthetic/`
(fuori dal versionamento) e stampa il rapporto di validazione: è il rapporto, non i
CSV, la risposta del ticket.

I requisiti che il rapporto deve verificare vengono da altri due ticket:

- **#17**: ≥ 1500 finestre etichettabili, classe `stallo` fra il 15% e il 35%, e casi
  difficili presenti (piatto-poi-riparte, rumoroso-in-crescita, deload).
  Le etichette si ricavano dai dati generati con la stessa regola dei dati reali,
  **mai** dallo stato nascosto del generatore: sarebbe circolare.
- **#16**: ≥ 20 utenti per esercizio o il percentile tace, quindi la popolazione si
  concentra su un core di esercizi invece di spargersi sulle 100 voci del catalogo.
"""

import csv
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

# --------------------------------------------------------------------------------
# Costanti di generazione
# --------------------------------------------------------------------------------

SEED = 20260907  # fisso: i numeri mostrati all'orale non devono cambiare
N_USERS = 100
TODAY = date(2026, 9, 7)

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_DIR = BASE_DIR / "data" / "catalog"
OUT_DIR = BASE_DIR / "data" / "synthetic"

EPLEY_MAX_REPS = 12  # oltre, Epley gonfia: #17 e #16 usano lo stesso tetto

# L'orizzonte futuro della regola di etichettatura. #17 aveva scritto **4**; questo
# prototipo ha misurato che a 4 sessioni la classe `stallo` sta al 45,1% su una
# popolazione realistica, fuori dalla banda 15-35% che #17 stesso chiedeva, mentre a
# **6** sta al 33,4% senza toccare nient'altro. Non e' una taratura di comodo: un
# esercizio si allena ~1,5 volte a settimana, quindi 4 sessioni sono meno di tre
# settimane — troppo poco per dichiarare uno stallo — e 6 sono circa un mese.
# **Emendamento a #17, da ratificare.**
FUTURE_SESSIONS = 6

# La spazzata di sensibilita' sulla regola di etichettatura.
HORIZONS = (4, 6, 8, 10)
THRESHOLDS = (1.00, 1.01, 1.02)

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

# Incremento minimo dell'attrezzo: nessuno carica 43,7 kg.
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
# I guadagni sono tarati **contro la regola di etichettatura di #17**, non a occhio:
# per non essere letta come stallo, una finestra deve vedere il massimale superare di
# oltre il 2% il massimo di sei sessioni rumorose entro le quattro successive. Con
# rumore al 3% quel massimo è già gonfiato di ~1,5 deviazioni, quindi una crescita
# sotto lo 0,6% a sessione è **indistinguibile da uno stallo** — e infatti la prima
# taratura, con guadagni realistici sulla carta ma lenti, etichettava stallo il 74,8%
# delle finestre. Non è un difetto del generatore: è la sensibilità vera della regola,
# ed è la ragione per cui il rumore qui è più basso e i guadagni più alti.
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

# --------------------------------------------------------------------------------
# Catalogo
# --------------------------------------------------------------------------------


def load_catalog():
    """Legge i quattro CSV versionati e restituisce la lista degli esercizi."""
    groups = {r["code"]: r for r in _read(CATALOG_DIR / "muscle_groups.csv")}
    muscles = {r["code"]: r for r in _read(CATALOG_DIR / "muscles.csv")}
    equipment = {r["code"]: r for r in _read(CATALOG_DIR / "equipment.csv")}
    exercises = []
    for i, row in enumerate(_read(CATALOG_DIR / "exercises.csv"), start=1):
        muscle = muscles[row["muscle_code"]]
        exercises.append(
            dict(
                id=i,
                name=row["name"],
                muscle=muscle["code"],
                group=muscle["group_code"],
                equipment=row["equipment_code"],
                bar=float(equipment[row["equipment_code"]]["default_bar_weight_kg"]),
                is_core=row["name"] in CORE_RATIOS,
                ratio=CORE_RATIOS.get(row["name"], TAIL_RATIOS[muscle["group_code"]]),
            )
        )
    assert set(groups)  # i gruppi servono solo a validare i codici
    missing = set(CORE_RATIOS) - {e["name"] for e in exercises}
    if missing:
        raise SystemExit(f"Esercizi del core assenti dal catalogo: {sorted(missing)}")
    return exercises


def _read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------------
# Utenti
# --------------------------------------------------------------------------------

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


def make_users(rng):
    """Crea i 100 utenti sintetici: archetipo, peso corporeo, forza, storico.

    Lo storico è **variabile per costruzione** (Q1): pochi veterani che riempiono la
    finestra a 12 mesi di #16, la maggior parte fra 4 e 10 mesi, e una manciata sotto
    i 21 giorni perché la pagina dello stallo possa mostrare dal vivo lo stato
    «dati insufficienti» che #17 vuole come avanzamento e non come errore.
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
                is_synthetic=True,
            )
        )
    return users


def pick_exercises(user, exercises, rng):
    """Sceglie il repertorio dell'utente: il core quasi sempre, la coda per realismo.

    #16 impone ≥ 20 utenti per esercizio o il percentile tace: è questa funzione a
    decidere se quella soglia si raggiunge, ed è il motivo per cui il core si pesca
    con probabilità alta invece che uniformemente sulle 100 voci.
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
    archetipo di utente ma una fase che quasi tutti attraversano: è questa macchina a
    produrlo, ed è per questo che la percentuale finale si misura sui dati generati
    invece di essere dichiarata a priori.

    Lo stato di questa classe non esce mai dai CSV: le etichette di #17 si ricavano
    dai dati, non da qui, o l'esperimento sarebbe circolare.
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
        # #17 la legge — correttamente — come stallo. Misurato: col tetto a 1,05–1,30
        # metà delle finestre in crescita dichiarata risultava stallo.
        #
        # È un potenziale **dell'utente**, non del singolo esercizio: tirandolo per
        # esercizio in modo indipendente ricompare proprio l'incoerenza che Q2 doveva
        # rendere impossibile (misurato: un utente con la panca sopra lo squat).
        self.ceiling = base * user["ceiling"] * rng.uniform(0.95, 1.05)
        self.state = "crescita"
        self.left = 0
        self.pre_deload = None
        self.phases = Counter()
        self.current_phase = "crescita"

    def step(self):
        """Avanza di una sessione e restituisce il massimale latente."""
        cfg, rng = self.cfg, self.rng
        self.phases[self.state] += 1
        self.current_phase = self.state

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
                # piatto-poi-riparte: il caso difficile che #17 chiede esplicitamente
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
    # Solo diagnostica: la fase nascosta di ogni (utente, esercizio, giorno). Non
    # finisce in nessun CSV e non è mai un'etichetta — serve a verificare che la
    # regola di #17, applicata dall'esterno, ritrovi le fasi che il generatore ha
    # davvero prodotto. Se ci finisse dentro, l'esperimento sarebbe circolare.
    phases = {}
    wid = sid = 0

    for user in users:
        repertoire, by_group = pick_exercises(user, exercises, rng)
        traj = {e["name"]: Trajectory(user, e, rng) for e in repertoire}
        split = SPLITS[user["split"]]
        total_days = (TODAY - user["start"]).days
        end = user["start"] + timedelta(
            days=int(total_days * user["quit_after"]) if user["quit_after"] else total_days
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
            started = datetime.combine(day, time(rng.randint(7, 20), rng.choice([0, 15, 30, 45])))
            workouts.append(
                dict(
                    id=wid,
                    user_id=user["id"],
                    title=f"{user['split'].replace('_', ' ').title()} — giorno {day_index}",
                    started_at=started.isoformat(sep=" "),
                    ended_at=(started + timedelta(minutes=rng.randint(45, 95))).isoformat(sep=" "),
                )
            )

            for order, ex in enumerate(todays, start=1):
                t = traj[ex["name"]]
                one_rm = t.step() * rng.lognormvariate(
                    0, ARCHETYPES[user["archetype"]]["noise"]
                )
                phases[(user["id"], ex["id"], day)] = t.current_phase
                sid = emit_sets(sets, sid, wid, user, ex, one_rm, order, rng)
            last_seen = day
            day += timedelta(days=1)
        assert last_seen <= TODAY
    return workouts, sets, phases


def emit_sets(sets, sid, wid, user, ex, one_rm, order, rng):
    """Scrive le serie di un esercizio in un allenamento.

    Il carico si ricava **invertendo Epley** dal massimale latente, così la stessa
    formula che le analisi useranno per stimarlo è quella che lo ha prodotto: il
    generatore e il motore analitico parlano la stessa lingua.
    """
    step = STEP_BY_EQUIPMENT[ex["equipment"]]
    scheme = rng.choice([(5, 3), (8, 3), (10, 3), (12, 4), (6, 4), (10, 2)])
    target_reps, n_sets = scheme

    # riscaldamento e avvicinamento sui multiarticolari pesanti: senza di loro il
    # filtro `working` delle analisi non filtrerebbe niente e non dimostrerebbe niente
    if ex["is_core"] and ex["ratio"] >= 0.80 and order <= 3:
        for kind, frac, reps in (("warmup", 0.45, 12), ("rampUp", 0.75, 6)):
            w = weight_for(one_rm * frac, reps, ex, user, step)
            sid += 1
            sets.append(row(sid, wid, ex, sid, reps, w, kind, True))

    for i in range(n_sets):
        reps = max(3, target_reps - rng.choice([0, 0, 0, 1, 1, 2]) * (i > 0))
        w = weight_for(one_rm, target_reps, ex, user, step)
        completed = rng.random() > 0.19  # gli 81% completati dei dati reali (#13)
        sid += 1
        sets.append(row(sid, wid, ex, i + 1, reps, w, "working", completed))
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
        reps=reps,
        weight_kg=f"{weight:.2f}",
        set_type=set_type,
        is_completed="true" if completed else "false",
    )


# --------------------------------------------------------------------------------
# Schede e voti
# --------------------------------------------------------------------------------


def make_routines_and_votes(users, exercises, rng):
    """Schede pubbliche e voti: senza di loro la seconda classifica non esiste.

    La distribuzione dei voti è deliberatamente **sbilanciata** — poche schede molto
    votate, molte con zero — perché una classifica sociale in cui tutti hanno tre voti
    non ordina niente e all'orale non dimostra niente.
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
                    name=rng.choice(
                        ["Push", "Pull", "Gambe", "Upper", "Lower", "Full body",
                         "Petto e tricipiti", "Schiena e bicipiti", "Forza"]
                    ),
                    is_public="true" if is_public else "false",
                )
            )
            if is_public:
                public.append((rid, user["id"]))
            for order, ex in enumerate(rng.sample(exercises, rng.randint(5, 8)), start=1):
                lid += 1
                links.append(
                    dict(id=lid, routine_id=rid, exercise_id=ex["id"], position=order,
                         target_sets=rng.randint(3, 4), target_reps=rng.choice([5, 8, 10, 12]))
                )

    # popolarità a coda lunga: il rango decide quanti voti arrivano
    rng.shuffle(public)
    for rank, (routine_id, owner) in enumerate(public, start=1):
        n = max(0, round(rng.expovariate(1 / 6.0) * (1.6 / math.sqrt(rank)) * 3))
        voters = [u for u in users if u["id"] != owner]
        for voter in rng.sample(voters, min(n, len(voters))):
            vid += 1
            votes.append(
                dict(id=vid, routine_id=routine_id, user_id=voter["id"],
                     score=rng.choices([1, 2, 3, 4, 5], weights=[3, 6, 18, 40, 33])[0])
            )
    return routines, links, votes


# --------------------------------------------------------------------------------
# Validazione — la vera risposta del ticket
# --------------------------------------------------------------------------------


def epley(weight, reps, ex, body_mass):
    """Massimale stimato sul **carico effettivo** (ADR-0006): il corpo libero somma
    il peso corporeo, altrimenti trazioni e piegamenti peserebbero zero."""
    load = weight + (body_mass if ex["equipment"] == "bodyweight" else 0.0)
    return load * (1 + reps / 30)


def label_windows(users, exercises, workouts, sets, phases, fut_n=FUTURE_SESSIONS, thr=1.02):
    """Applica la regola di #17 ai dati generati, senza guardare il generatore.

    Finestra = 6 allenamenti consecutivi dello stesso esercizio su ≥ 21 giorni.
    Etichetta = `stallo` se nelle `fut_n` sessioni successive il massimale non supera
    il massimo di finestra di più del 2%. Un buco > 28 giorni spezza la serie storica.
    """
    by_ex = {e["id"]: e for e in exercises}
    by_user = {u["id"]: u for u in users}
    wk = {w["id"]: w for w in workouts}

    # una riga per (utente, esercizio, allenamento): il massimale della miglior
    # serie di lavoro, ripetizioni ≤ 12
    best = defaultdict(dict)
    for s in sets:
        if s["set_type"] != "working" or s["is_completed"] != "true":
            continue
        if s["reps"] > EPLEY_MAX_REPS:
            continue
        w = wk[s["workout_id"]]
        user = by_user[w["user_id"]]
        ex = by_ex[s["exercise_id"]]
        e = epley(float(s["weight_kg"]), s["reps"], ex, user["body_mass_kg"])
        key = (w["user_id"], s["exercise_id"])
        d = datetime.fromisoformat(w["started_at"]).date()
        best[key][d] = max(best[key].get(d, 0.0), e)

    total = stalls = 0
    per_user = Counter()
    per_archetype = defaultdict(lambda: [0, 0])  # [finestre, stalli]
    agreement = Counter()  # (fase nascosta, etichetta) — solo diagnostica
    for (uid, exid), series in best.items():
        days = sorted(series)
        runs, run = [], [days[0]]
        for prev, cur in zip(days, days[1:]):
            if (cur - prev).days > 28:
                runs.append(run)
                run = [cur]
            else:
                run.append(cur)
        runs.append(run)

        archetype = by_user[uid]["archetype"]
        for r in runs:
            for i in range(5, len(r) - fut_n):
                window = r[i - 5 : i + 1]
                if (window[-1] - window[0]).days < 21:
                    continue
                wmax = max(series[d] for d in window)
                fut = max(series[d] for d in r[i + 1 : i + 1 + fut_n])
                is_stall = fut <= wmax * thr
                total += 1
                stalls += is_stall
                per_user[uid] += 1
                per_archetype[archetype][0] += 1
                per_archetype[archetype][1] += is_stall
                hidden = phases.get((uid, exid, window[-1]))
                if hidden:
                    agreement[(hidden, "stallo" if is_stall else "non stallo")] += 1
    return total, stalls, per_user, per_archetype, agreement


def report(users, exercises, workouts, sets, routines, votes, phases):
    print("\n" + "=" * 78)
    print("RAPPORTO DI VALIDAZIONE — popolazione sintetica di Progressive (#18)")
    print("=" * 78)

    print(f"\nSeed {SEED} — rigenerabile identico.\n")
    print(f"  utenti            {len(users):>8,}")
    print(f"  allenamenti       {len(workouts):>8,}")
    print(f"  serie             {len(sets):>8,}")
    print(f"  schede            {len(routines):>8,}")
    print(f"  voti              {len(votes):>8,}")

    # --- 1. realismo contro le ancore dei dati veri (#13) ------------------------
    print("\n1. REALISMO — confronto con lo storico reale di Lorenzo (#13)")
    per_w = Counter(s["workout_id"] for s in sets)
    ex_per_w = defaultdict(set)
    for s in sets:
        ex_per_w[s["workout_id"]].add(s["exercise_id"])
    working = [s for s in sets if s["set_type"] == "working"]
    reps = sorted(s["reps"] for s in working)
    spans = []
    for u in users:
        ws = [w for w in workouts if w["user_id"] == u["id"]]
        if len(ws) > 3:
            d = sorted(datetime.fromisoformat(w["started_at"]).date() for w in ws)
            weeks = max(1.0, (d[-1] - d[0]).days / 7)
            spans.append(len(d) / weeks)
    rows = [
        ("serie per allenamento", statistics.median(per_w.values()), 22.0),
        ("esercizi per allenamento", statistics.median(len(v) for v in ex_per_w.values()), 8.0),
        ("ripetizioni (mediana)", statistics.median(reps), 9.0),
        ("sedute a settimana", statistics.median(spans), 4.2),
        ("frazione completata", sum(1 for s in working if s["is_completed"] == "true") / len(working), 0.81),
    ]
    for name, got, real in rows:
        print(f"  {name:<26} sintetico {got:>7.2f}   reale {real:>6.2f}")
    print(f"  {'tipi di serie':<26} {dict(Counter(s['set_type'] for s in sets))}")

    # --- 2. il requisito di #17 --------------------------------------------------
    total, stalls, per_user, per_archetype, agreement = label_windows(
        users, exercises, workouts, sets, phases
    )
    pct = 100 * stalls / total if total else 0
    ok_n = total >= 1500
    ok_pct = 15 <= pct <= 35
    print("\n2. RILEVAMENTO STALLO — requisito consegnato da #17")
    print(f"  orizzonte futuro         {FUTURE_SESSIONS:>8} sessioni   (#17 diceva 4 — vedi la spazzata)")
    print(f"  finestre etichettabili   {total:>8,}   (richieste ≥ 1.500)   {_ok(ok_n)}")
    print(f"  classe `stallo`          {pct:>7.1f}%   (richiesto 15–35%)    {_ok(ok_pct)}")
    print(f"  utenti con ≥ 1 finestra  {len(per_user):>8,} su {len(users)}")
    print(f"  utenti senza finestre    {len(users) - len(per_user):>8,}   "
          f"(sono i «dati insufficienti» da mostrare all'orale)")
    print("  stallo per archetipo:")
    for name, (n, st) in sorted(per_archetype.items(), key=lambda kv: -kv[1][1] / max(1, kv[1][0])):
        print(f"    {name:<20} {100 * st / n:>5.1f}%   su {n:,} finestre")
    print("  l'etichetta ritrova la fase nascosta del generatore?"
          "   (diagnostica, mai usata come etichetta)")
    for hidden in ("crescita", "plateau", "deload"):
        n = sum(v for (h, _), v in agreement.items() if h == hidden)
        if not n:
            continue
        st = agreement[(hidden, "stallo")]
        print(f"    fase {hidden:<10} -> etichettata stallo {100 * st / n:>5.1f}%   su {n:,}")

    # La spazzata: se la banda 15–35%% non si raggiunge, il parametro da muovere non e'
    # nel generatore ma nella **regola** di #17. Questa tabella e' la risposta che il
    # ticket restituisce a #17, misurata invece che stimata.
    print("\n  sensibilita' della regola (orizzonte futuro x soglia):")
    print(f"    {'orizzonte':>10}  " + "  ".join(f"+{100*(t-1):>4.1f}%" for t in THRESHOLDS))
    for fut in HORIZONS:
        cells = []
        for t in THRESHOLDS:
            tot, st, *_ = label_windows(users, exercises, workouts, sets, phases, fut, t)
            cells.append(f"{100*st/tot:>5.1f}%" if tot else "   n/d")
        print(f"    {fut:>7} sess  " + "  ".join(cells))

    # --- 3. il requisito di #16 --------------------------------------------------
    wk = {w["id"]: w["user_id"] for w in workouts}
    users_per_ex = defaultdict(set)
    for s in working:
        users_per_ex[s["exercise_name"]].add(wk[s["workout_id"]])
    counts = {k: len(v) for k, v in users_per_ex.items()}
    core = {k: v for k, v in counts.items() if k in CORE_RATIOS}
    above = sum(1 for v in counts.values() if v >= 20)
    print("\n3. PERCENTILE — requisito consegnato da #16 (≥ 20 utenti o tace)")
    print(f"  esercizi core sopra soglia   {sum(1 for v in core.values() if v >= 20):>3} su {len(core)}   "
          f"{_ok(all(v >= 20 for v in core.values()))}")
    print(f"  utenti per esercizio core    min {min(core.values())}, mediana "
          f"{statistics.median(core.values()):.0f}, max {max(core.values())}")
    print(f"  esercizi totali sopra soglia {above:>3} su {len(counts)}   "
          f"(la coda resta sotto: serve a mostrare il percentile che tace)")

    # --- 4. coerenza interna -----------------------------------------------------
    print("\n4. COERENZA INTERNA — i rapporti fra esercizi")
    pr = defaultdict(dict)
    by_ex = {e["name"]: e for e in exercises}
    bm = {u["id"]: u["body_mass_kg"] for u in users}
    for s in working:
        if s["reps"] > EPLEY_MAX_REPS or s["is_completed"] != "true":
            continue
        uid = wk[s["workout_id"]]
        e = epley(float(s["weight_kg"]), s["reps"], by_ex[s["exercise_name"]], bm[uid])
        pr[uid][s["exercise_name"]] = max(pr[uid].get(s["exercise_name"], 0.0), e)
    ratios = [
        p["Panca piana con bilanciere"] / p["Squat con bilanciere"]
        for p in pr.values()
        if "Panca piana con bilanciere" in p and "Squat con bilanciere" in p
    ]
    absurd = sum(1 for r in ratios if r > 1.15)
    print(f"  panca / squat            mediana {statistics.median(ratios):.2f}   "
          f"({min(ratios):.2f}–{max(ratios):.2f}) su {len(ratios)} utenti")
    print(f"  casi assurdi (panca > squat × 1,15)   {absurd:>3}   {_ok(absurd == 0)}")
    rel = sorted(p["Panca piana con bilanciere"] / bm[u]
                 for u, p in pr.items() if "Panca piana con bilanciere" in p)
    print(f"  forza relativa in panca  p10 {rel[len(rel)//10]:.2f}×  "
          f"mediana {statistics.median(rel):.2f}×  p90 {rel[9*len(rel)//10]:.2f}× peso corporeo")

    # --- 5. i casi difficili -----------------------------------------------------
    print("\n5. CASI DIFFICILI — #17 li chiede esplicitamente")
    print(f"  distribuzione archetipi  {dict(Counter(u['archetype'] for u in users))}")
    hist = sorted((TODAY - u["start"]).days / 30.4 for u in users)
    print(f"  storico in mesi          min {hist[0]:.1f}  mediana "
          f"{statistics.median(hist):.1f}  max {hist[-1]:.1f}")
    print(f"  utenti sotto i 21 giorni {sum(1 for u in users if (TODAY - u['start']).days < 21):>3}")

    # --- 6. la classifica sociale ------------------------------------------------
    pub = [r for r in routines if r["is_public"] == "true"]
    vc = Counter(v["routine_id"] for v in votes)
    top = sorted(vc.values(), reverse=True)
    print("\n6. CLASSIFICA SOCIALE — schede pubbliche e voti")
    print(f"  schede pubbliche {len(pub)} su {len(routines)}; con almeno un voto {len(vc)}")
    if top:
        print(f"  voti per scheda: max {top[0]}, mediana fra le votate "
              f"{statistics.median(top):.0f}, schede a zero voti {len(pub) - len(vc)}")

    # --- 7. l'utente della demo ---------------------------------------------------
    # #17 vuole che la pagina dello stallo si dimostri su un utente sintetico
    # «scelto e nominato in anticipo»: sceglierlo qui, dal rapporto, evita di doverlo
    # cercare a mano il giorno dell'orale.
    print("\n7. UTENTE PER LA DEMO DELLO STALLO — #17 lo vuole scelto in anticipo")
    by_id = {u["id"]: u for u in users}
    cands = [
        (n, by_id[uid]) for uid, n in per_user.most_common()
        if by_id[uid]["archetype"] in ("intermedio_plateau", "avanzato")
    ]
    for n, u in cands[:3]:
        print(f"  {u['username']}  {u['display_name']:<22} {u['archetype']:<19} "
              f"{n:>4} finestre, {(TODAY - u['start']).days // 30} mesi di storico")
    if cands:
        n, u = cands[0]
        print(f"  -> scelto: {u['username']} ({u['display_name']})")

    verdict = ok_n and ok_pct and all(v >= 20 for v in core.values()) and absurd == 0
    print("\n" + "=" * 78)
    print(("VERDETTO: la popolazione soddisfa i requisiti di #16 e #17."
           if verdict else "VERDETTO: requisiti NON soddisfatti — vanno tarati i parametri."))
    print("=" * 78 + "\n")
    return verdict


def _ok(flag):
    return "OK" if flag else "NO"


# --------------------------------------------------------------------------------


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    rng = random.Random(SEED)
    exercises = load_catalog()
    users = make_users(rng)
    workouts, sets, phases = generate(users, exercises, rng)
    routines, links, votes = make_routines_and_votes(users, exercises, rng)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_DIR / "users.csv", users,
              ["id", "username", "display_name", "body_mass_kg", "is_synthetic", "archetype"])
    write_csv(OUT_DIR / "workouts.csv", workouts,
              ["id", "user_id", "title", "started_at", "ended_at"])
    write_csv(OUT_DIR / "workout_sets.csv", sets,
              ["id", "workout_id", "exercise_id", "set_number", "reps", "weight_kg",
               "set_type", "is_completed"])
    write_csv(OUT_DIR / "routines.csv", routines, ["id", "user_id", "name", "is_public"])
    write_csv(OUT_DIR / "routine_exercises.csv", links,
              ["id", "routine_id", "exercise_id", "position", "target_sets", "target_reps"])
    write_csv(OUT_DIR / "votes.csv", votes, ["id", "routine_id", "user_id", "score"])

    ok = report(users, exercises, workouts, sets, routines, votes, phases)
    print(f"CSV scritti in {OUT_DIR} (fuori dal versionamento).\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
