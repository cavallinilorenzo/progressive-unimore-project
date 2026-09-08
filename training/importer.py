"""Il parser dell'import CSV: il dominio dell'import, fuori dalle view.

Questo modulo non conosce HTTP. Prende dei file aperti, ne ricava una
**lettura** — sessioni, serie, errori, avvisi, duplicati — e sa scriverla nel
database dentro una transazione. Le tre view di `/import/` lo chiamano due
volte: una per l'anteprima e una alla conferma, sugli stessi file riletti da
disco (`docs/spec/03-import-ed-export.md`, «Dove sta il file fra i due passi»).

Sta in un file suo e non in `views.py` per una ragione pratica: è la parte che
va provata riga per riga sui CSV sporchi, e provarla attraverso il client HTTP
significherebbe passare da un upload per ogni caso.

IL FORMATO È DI PROGRESSIVE, e Progressive lo esporta (#74). Due file:

| file | colonne lette |
| --- | --- |
| `workout_sessions.csv` | `id`, `title`, `started_at`, `ended_at`, `notes` |
| `session_sets.csv` | `id`, `session_id`, `exercise_name`, `set_number`, `reps`, `weight`, `set_type`, `is_completed` |

**L'esercizio viaggia per nome, non per id**, ed è la colonna su cui gira tutto
l'abbinamento interattivo di ADR-0010: un id è la chiave privata di un
database, e fra due sistemi non significa niente — è la stessa ragione per cui
`routine_id` non punta a nulla e `user_id` si ignora.

IL TERZO FILE, FACOLTATIVO. L'export di Overload — cioè lo storico reale su cui
questa validazione è stata misurata — porta in `session_sets.csv` un
`exercise_id` UUID e tiene i nomi in `exercises.csv`. Quel file si accetta
**come dizionario** `id → nome`, mai come sorgente di esercizi: nessuna riga di
`Exercise` nasce dall'import, che è il divieto di ADR-0001 e resta intatto.
L'alternativa era far ricucire i due file all'utente prima del caricamento,
cioè ripulire i dati *fuori* dall'app — proprio ciò che la spec scarta quando
rifiuta il CSV unico denormalizzato.

Il parsing è **a streaming**: `csv.DictReader` su un `TextIOWrapper`, mai un
`.read()`. Il limite di 5 MB lo impone il form, ed è ~25.000 serie contro le
317 dello storico reale.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from difflib import get_close_matches
from uuid import UUID, uuid5

from django.db import transaction
from django.utils.dateparse import parse_datetime

from training.models import Exercise, ExerciseAlias, Workout, WorkoutSet

#: 5 MB per file. Lo storico reale sta in ~60 KB, quindi il limite è ~80 volte
#: il caso vero: è una difesa contro il file sbagliato, non contro l'uso.
LIMITE_BYTE = 5 * 1024 * 1024

FILE_SESSIONI = "workout_sessions.csv"
FILE_SERIE = "session_sets.csv"
FILE_ESERCIZI = "exercises.csv"

COLONNE_SESSIONI = {"id", "title", "started_at"}
COLONNE_SERIE = {"id", "session_id", "set_number"}

#: Il namespace UUID di Progressive, fisso e scritto qui una volta sola.
#:
#: Serve al **nome pubblico** di una riga nata in-app (`nome_pubblico`), ed è
#: la metà del giro che l'export chiude: si esporta anche ciò che non è mai
#: stato importato, e in un file ogni riga ha bisogno di un `id`.
NAMESPACE_PROGRESSIVE = UUID("6f3b1c2e-5a4d-4e7b-9c81-0a2b3c4d5e6f")


def nome_pubblico(modello, pk):
    """L'`id` con cui una riga **nata in Progressive** compare in un export.

    Si **calcola e non si memorizza**, ed è la decisione che tiene in piedi due
    regole insieme. `03-import-ed-export.md` dice che il nullable di
    `external_id` è essenziale — «un allenamento nato dentro Progressive non ha
    nessun `external_id` e non deve fingerne uno» — quindi l'export non può
    timbrare la colonna al passaggio; ma un CSV senza `id` non è
    reimportabile, e il giro export → import non si chiuderebbe.

    Un UUID versione 5 risolve entrambe: è una **funzione** della chiave
    primaria, quindi due export della stessa riga portano lo stesso `id` e il
    reimport la riconosce come duplicato, mentre la colonna in database resta
    nulla. Il costo dichiarato: il nome pubblico vive quanto la chiave
    primaria, quindi un database ricreato da zero riusa i numeri e riuserebbe i
    nomi — che è un limite dei backup, non dell'import.
    """
    return uuid5(NAMESPACE_PROGRESSIVE, f"progressive:{modello}:{pk}")

#: Sotto e sopra queste soglie la durata è **sospetta, non impossibile**: lo
#: storico reale contiene una sessione da 0 minuti e una da 25 ore, ed entrano
#: entrambe. Correggerle sarebbe inventare dati; scartarle perderebbe 2
#: sessioni su 15. L'unico bloccante resta `ended_at >= started_at`, che è un
#: `CheckConstraint` del modello.
DURATA_MINIMA = timedelta(minutes=1)
DURATA_MASSIMA = timedelta(hours=6)


class FormatoNonValido(Exception):
    """Il file non ha le colonne che servono: non è un errore di riga.

    Un errore di riga si elenca nel report e si scarta; questo invece ferma
    tutto prima di leggere anche solo una riga, e la risposta giusta è
    rimandare l'utente all'upload con un messaggio sul file.
    """


@dataclass(frozen=True)
class Errore:
    """Una riga scartata. Il `numero` è quello **reale** del CSV, intestazione
    compresa: è il numero che si cerca aprendo il file, non l'indice della riga
    di dati."""

    file: str
    numero: int
    colonna: str
    valore: str
    motivo: str


@dataclass(frozen=True)
class Avviso:
    """Una riga che entra così com'è, ma su cui c'è qualcosa da dire."""

    file: str
    numero: int
    motivo: str


@dataclass
class SessioneLetta:
    #: L'`id` grezzo del CSV: è la chiave con cui le serie ritrovano la loro
    #: sessione *dentro il file*, e resta una stringa perché il file di un
    #: altro sistema non deve per forza usare UUID.
    chiave: str
    external_id: UUID | None
    title: str
    started_at: object
    ended_at: object
    notes: str
    numero: int


@dataclass
class SerieLetta:
    chiave_sessione: str
    external_id: UUID | None
    raw_name: str
    set_number: int
    reps: int | None
    weight: Decimal | None
    set_type: str
    is_completed: bool
    numero: int


@dataclass
class Lettura:
    """Cosa i due file contengono, dopo che le righe rotte sono state messe da
    parte. È ciò che l'anteprima mostra e ciò che la conferma scrive."""

    sessioni: list = field(default_factory=list)
    serie: list = field(default_factory=list)
    errori: list = field(default_factory=list)
    avvisi: list = field(default_factory=list)
    #: Righe già presenti nel database per `external_id`: non sono errori, è
    #: l'idempotenza che funziona. Si contano e si dichiarano.
    sessioni_duplicate: int = 0
    serie_duplicate: int = 0
    lette_sessioni: int = 0
    lette_serie: int = 0
    #: Chi sta importando, e **solo** per riconoscere i propri `nome_pubblico`
    #: (vedi `leggi`). Non entra in nessuna riga scritta: quello lo fa `scrivi`
    #: col `request.user` che riceve a parte.
    user: object = None

    @property
    def nomi_grezzi(self):
        """I nomi distinti apparsi nelle serie valide, in ordine di prima
        comparsa: è l'ordine del file, che è quello che l'utente riconosce."""
        visti = {}
        for serie in self.serie:
            visti.setdefault(serie.raw_name, None)
        return list(visti)

    @property
    def periodo(self):
        if not self.sessioni:
            return (None, None)
        date = [sessione.started_at for sessione in self.sessioni]
        return (min(date), max(date))


def _testo(riga, chiave):
    return (riga.get(chiave) or "").strip()


def _uuid(valore):
    """Un `external_id` illeggibile non è un motivo per scartare la riga.

    L'id è la chiave dell'idempotenza, non un dato di dominio: senza, la riga
    entra lo stesso e semplicemente non è deduplicabile — che è la stessa
    condizione di ogni allenamento nato dentro Progressive, dove `external_id`
    è nullo per costruzione.
    """
    if not valore:
        return None
    try:
        return UUID(valore)
    except ValueError:
        return None


def _apri(fileobj):
    """Il file arriva come `UploadedFile` o come file di `MEDIA_ROOT`: in
    entrambi i casi è binario, e `csv` vuole del testo.

    `utf-8-sig` e non `utf-8`: un CSV passato per un foglio di calcolo porta il
    BOM, e con `utf-8` il BOM finisce dentro il nome della **prima colonna**,
    che diventa `﻿id` e non combacia più con niente. Fallirebbe sul file
    giusto, dicendo che manca una colonna che si vede a occhio.
    """
    fileobj.seek(0)
    return io.TextIOWrapper(fileobj, encoding="utf-8-sig", newline="")


def _colonne_mancanti(reader, richieste, nome_file):
    presenti = set(reader.fieldnames or [])
    mancanti = sorted(richieste - presenti)
    if mancanti:
        raise FormatoNonValido(
            f"In «{nome_file}» mancano le colonne: {', '.join(mancanti)}."
        )


def leggi_dizionario_esercizi(fileobj):
    """`exercises.csv`, e **solo** come tabella di traduzione `id → nome`.

    Non crea niente e non tocca il catalogo (ADR-0001): serve a dare un nome
    leggibile a un `exercise_id` che altrimenti arriverebbe all'utente come un
    UUID da abbinare a mano, cosa che nessuno può fare.
    """
    reader = csv.DictReader(_apri(fileobj))
    _colonne_mancanti(reader, {"id", "name"}, FILE_ESERCIZI)
    return {
        _testo(riga, "id"): _testo(riga, "name")
        for riga in reader
        if _testo(riga, "id") and _testo(riga, "name")
    }


def leggi(file_sessioni, file_serie, file_esercizi=None, user=None):
    """I due file (più il dizionario facoltativo) in una `Lettura`.

    `user` serve **solo all'idempotenza**, e non all'identità: chi importa
    resta `request.user` e il `user_id` del CSV continua a non contare niente.
    Serve perché le righe nate in-app hanno un `id` nel file — il loro
    `nome_pubblico` — che in database non c'è, e senza sapere di chi sono non
    si potrebbe riconoscerle al ritorno. Omettendolo l'import funziona
    esattamente come prima e vede i soli `external_id` memorizzati.
    """
    dizionario = leggi_dizionario_esercizi(file_esercizi) if file_esercizi else {}
    lettura = Lettura()
    lettura.user = user
    _leggi_sessioni(file_sessioni, lettura)
    _leggi_serie(file_serie, lettura, dizionario)
    return lettura


def _nomi_sessioni_note(user):
    """Gli `id` di sessione che il database **già conosce**, come stringhe.

    Due provenienze e un solo insieme: gli `external_id` memorizzati (le righe
    arrivate da un import) e i `nome_pubblico` calcolati delle righe nate
    in-app dell'utente. Dal punto di vista del file sono la stessa cosa — un
    `id` che c'è già — ed è ciò che rende «esporta e reimporta» un no-op anche
    per un allenamento che nessuno ha mai importato.
    """
    noti = {
        str(external_id)
        for external_id in Workout.objects.exclude(external_id=None).values_list(
            "external_id", flat=True
        )
    }
    if user is not None:
        noti |= {
            str(nome_pubblico("workout", pk))
            for pk in Workout.objects.filter(user=user, external_id=None).values_list(
                "pk", flat=True
            )
        }
    return noti


def _leggi_sessioni(fileobj, lettura):
    reader = csv.DictReader(_apri(fileobj))
    _colonne_mancanti(reader, COLONNE_SESSIONI, FILE_SESSIONI)

    # Un `external_id` già nel database è un duplicato da saltare, ed è
    # l'idempotenza dichiarata da `03-import-ed-export.md`. Il confronto si fa
    # in una query sola invece che una per riga: su 317 serie la differenza fra
    # un `in` su un insieme e 317 `exists()` è tutto il tempo dell'anteprima.
    noti = _nomi_sessioni_note(lettura.user)

    chiavi = set()
    for riga in reader:
        numero = reader.line_num
        lettura.lette_sessioni += 1
        chiave = _testo(riga, "id")

        if not chiave:
            lettura.errori.append(
                Errore(
                    FILE_SESSIONI,
                    numero,
                    "id",
                    "",
                    "Manca l'identificativo della sessione.",
                )
            )
            continue

        if chiave in chiavi:
            lettura.errori.append(
                Errore(
                    FILE_SESSIONI,
                    numero,
                    "id",
                    chiave,
                    "Questo identificativo compare due volte nel file.",
                )
            )
            continue
        chiavi.add(chiave)

        external_id = _uuid(chiave)
        if external_id is not None and str(external_id) in noti:
            # Non è un errore: la sessione c'è già. Le sue serie però possono
            # essere nuove, quindi la chiave resta valida e le righe di
            # `session_sets.csv` che la citano non diventano orfane.
            lettura.sessioni_duplicate += 1
            continue

        grezzo_inizio = _testo(riga, "started_at")
        inizio = parse_datetime(grezzo_inizio) if grezzo_inizio else None
        if inizio is None:
            lettura.errori.append(
                Errore(
                    FILE_SESSIONI,
                    numero,
                    "started_at",
                    grezzo_inizio,
                    "Data di inizio assente o illeggibile.",
                )
            )
            continue

        grezzo_fine = _testo(riga, "ended_at")
        fine = parse_datetime(grezzo_fine) if grezzo_fine else None
        if grezzo_fine and fine is None:
            lettura.errori.append(
                Errore(
                    FILE_SESSIONI,
                    numero,
                    "ended_at",
                    grezzo_fine,
                    "Data di fine illeggibile.",
                )
            )
            continue

        if fine is not None and fine < inizio:
            # L'unico caso davvero impossibile, ed è anche l'unico che il
            # database rifiuterebbe: `workout_ended_after_started`.
            lettura.errori.append(
                Errore(
                    FILE_SESSIONI,
                    numero,
                    "ended_at",
                    grezzo_fine,
                    "L'allenamento finirebbe prima di cominciare.",
                )
            )
            continue

        if fine is not None:
            durata = fine - inizio
            if durata < DURATA_MINIMA or durata > DURATA_MASSIMA:
                minuti = int(durata.total_seconds() // 60)
                lettura.avvisi.append(
                    Avviso(
                        FILE_SESSIONI,
                        numero,
                        f"Durata sospetta: {minuti} minuti. La sessione entra intatta.",
                    )
                )

        titolo = _testo(riga, "title") or "Allenamento importato"
        lettura.sessioni.append(
            SessioneLetta(
                chiave=chiave,
                external_id=external_id,
                title=titolo[:120],
                started_at=inizio,
                ended_at=fine,
                notes=_testo(riga, "notes"),
                numero=numero,
            )
        )


def _leggi_serie(fileobj, lettura, dizionario):
    reader = csv.DictReader(_apri(fileobj))
    _colonne_mancanti(reader, COLONNE_SERIE, FILE_SERIE)

    if not ({"exercise_name", "exercise_id"} & set(reader.fieldnames or [])):
        raise FormatoNonValido(
            f"In «{FILE_SERIE}» serve la colonna «exercise_name» — oppure "
            f"«exercise_id» insieme al file «{FILE_ESERCIZI}» che ne porta i nomi."
        )

    noti = {
        str(external_id)
        for external_id in WorkoutSet.objects.exclude(external_id=None).values_list(
            "external_id", flat=True
        )
    }
    if lettura.user is not None:
        noti |= {
            str(nome_pubblico("workoutset", pk))
            for pk in WorkoutSet.objects.filter(
                workout__user=lettura.user, external_id=None
            ).values_list("pk", flat=True)
        }
    # Le sessioni scartate sopra non sono qui dentro: le loro serie diventano
    # orfane, ed è giusto che lo diventino — una serie senza il suo allenamento
    # non ha dove andare.
    chiavi_valide = {sessione.chiave for sessione in lettura.sessioni}
    duplicate = _chiavi_gia_presenti(lettura)
    tipi = set(WorkoutSet.SetType.values)

    for riga in reader:
        numero = reader.line_num
        lettura.lette_serie += 1

        external_id = _uuid(_testo(riga, "id"))
        if external_id is not None and str(external_id) in noti:
            lettura.serie_duplicate += 1
            continue

        chiave_sessione = _testo(riga, "session_id")
        if chiave_sessione not in chiavi_valide and chiave_sessione not in duplicate:
            lettura.errori.append(
                Errore(
                    FILE_SERIE,
                    numero,
                    "session_id",
                    chiave_sessione,
                    "Non c'è nessuna sessione importabile con questo identificativo.",
                )
            )
            continue

        nome = _testo(riga, "exercise_name")
        if not nome:
            nome = dizionario.get(_testo(riga, "exercise_id"), "")
        if not nome:
            lettura.errori.append(
                Errore(
                    FILE_SERIE,
                    numero,
                    "exercise_name",
                    _testo(riga, "exercise_id"),
                    "Nome dell'esercizio assente, e nessun nome per questo identificativo.",
                )
            )
            continue

        grezzo_numero = _testo(riga, "set_number")
        try:
            set_number = int(grezzo_numero)
        except ValueError:
            set_number = 0
        if set_number < 1:
            lettura.errori.append(
                Errore(
                    FILE_SERIE,
                    numero,
                    "set_number",
                    grezzo_numero,
                    "Il numero di serie manca o non è un intero positivo.",
                )
            )
            continue

        eseguita = _testo(riga, "is_completed").lower() not in {"false", "0", "no", "n"}

        grezzo_reps = _testo(riga, "reps")
        reps = None
        if grezzo_reps:
            try:
                reps = int(grezzo_reps)
            except ValueError:
                lettura.errori.append(
                    Errore(
                        FILE_SERIE,
                        numero,
                        "reps",
                        grezzo_reps,
                        "Le ripetizioni non sono un numero intero.",
                    )
                )
                continue
            if reps < 0:
                lettura.errori.append(
                    Errore(
                        FILE_SERIE,
                        numero,
                        "reps",
                        grezzo_reps,
                        "Le ripetizioni non possono essere negative.",
                    )
                )
                continue

        # LA REGOLA MISURATA, e la trappola in cui l'import sarebbe caduto
        # senza aver prima guardato i dati (`docs/overload-export.md`):
        # una serie **eseguita** deve avere le ripetizioni — è il vincolo
        # `workout_set_completed_has_reps`, e sullo storico reale sono 2 righe
        # su 317. Il **peso** invece non si pretende mai: 25 serie completate
        # non ne hanno, e sono trazioni e leg raises, cioè corpo libero.
        if eseguita and not reps:
            lettura.errori.append(
                Errore(
                    FILE_SERIE,
                    numero,
                    "reps",
                    grezzo_reps,
                    "Una serie eseguita ha delle ripetizioni: qui la casella "
                    "«eseguita» è vera ma il numero manca.",
                )
            )
            continue

        grezzo_peso = _testo(riga, "weight")
        peso = None
        if grezzo_peso:
            try:
                peso = Decimal(grezzo_peso)
            except InvalidOperation:
                lettura.errori.append(
                    Errore(
                        FILE_SERIE,
                        numero,
                        "weight",
                        grezzo_peso,
                        "Il carico non è un numero.",
                    )
                )
                continue
            if peso < 0:
                lettura.errori.append(
                    Errore(
                        FILE_SERIE,
                        numero,
                        "weight",
                        grezzo_peso,
                        "Il carico non può essere negativo. Lo zero invece è "
                        "valido: è il corpo libero.",
                    )
                )
                continue

        if not eseguita:
            # Le 61 serie non eseguite dello storico reale: entrano, ed è la
            # differenza fra «non l'ho fatta» e «non l'avevo prevista». Il
            # vincolo `workout_set_completed_has_reps` guarda solo il caso
            # opposto, ma il file non porta mai numeri su una serie saltata e
            # inventarne qui sarebbe la stessa cosa che correggere una durata.
            reps = None
            peso = None

        tipo = _testo(riga, "set_type") or WorkoutSet.SetType.WORKING
        if tipo not in tipi:
            lettura.errori.append(
                Errore(
                    FILE_SERIE,
                    numero,
                    "set_type",
                    tipo,
                    "Tipo di serie sconosciuto. I valori ammessi sono: "
                    f"{', '.join(sorted(tipi))}.",
                )
            )
            continue

        lettura.serie.append(
            SerieLetta(
                chiave_sessione=chiave_sessione,
                external_id=external_id,
                raw_name=nome[:160],
                set_number=set_number,
                reps=reps,
                weight=peso,
                set_type=tipo,
                is_completed=eseguita,
                numero=numero,
            )
        )


def _chiavi_gia_presenti(lettura):
    """Gli `external_id` delle sessioni **già nel database**.

    Servono a non chiamare orfane le serie di una sessione che c'è già:
    ricaricare un file con una sessione vecchia e tre serie nuove deve
    aggiungere quelle tre, non produrre tre errori.
    """
    if not lettura.sessioni_duplicate:
        return set()
    return _nomi_sessioni_note(lettura.user)


def risolvi(nomi_grezzi, user):
    """Da nomi grezzi a esercizi del catalogo, e quel che resta da chiedere.

    Tre livelli, dal più affidabile al più incerto:

    1. un **`ExerciseAlias`** dell'utente — è la scelta che *lui* ha già fatto
       in un import precedente, e non gliela si richiede;
    2. il **nome esatto**, senza distinzione di maiuscole — è il caso del file
       esportato da Progressive stesso, dove i nomi sono già i suoi;
    3. niente: il nome finisce nel form di abbinamento, col **suggerimento**
       accanto.

    Il suggerimento è la parte che ADR-0010 ha declassato da risolutore a
    proposta: sui 24 nomi reali il matching automatico ne indovina quasi
    nessuno (`RDL`, `Leg extention`, `d'Annunzio crunch`), e va bene così —
    preseleziona la voce più probabile in una `<select>` e può sbagliare senza
    danno, perché c'è un umano a correggerlo. Il danno l'avrebbe fatto se
    avesse deciso da solo.
    """
    catalogo = list(Exercise.objects.all())
    per_nome = {esercizio.name.casefold(): esercizio for esercizio in catalogo}
    alias = {
        riga.raw_name.casefold(): riga.exercise
        for riga in ExerciseAlias.objects.filter(user=user).select_related("exercise")
    }

    risolti = {}
    da_chiedere = []
    for nome in nomi_grezzi:
        chiave = nome.casefold()
        esercizio = alias.get(chiave) or per_nome.get(chiave)
        if esercizio is not None:
            risolti[nome] = esercizio
        else:
            da_chiedere.append((nome, _suggerisci(nome, per_nome)))
    return risolti, da_chiedere


def _suggerisci(nome, per_nome):
    vicini = get_close_matches(nome.casefold(), list(per_nome), n=1, cutoff=0.6)
    return per_nome[vicini[0]] if vicini else None


@dataclass
class Esito:
    """Cosa la conferma ha davvero scritto. Va in `request.session` per essere
    mostrato dalla pagina d'esito, quindi resta fatto di numeri e di stringhe."""

    allenamenti: int = 0
    serie: int = 0
    allenamenti_saltati: int = 0
    serie_saltate: int = 0
    scartate: list = field(default_factory=list)

    def as_dict(self):
        return {
            "allenamenti": self.allenamenti,
            "serie": self.serie,
            "allenamenti_saltati": self.allenamenti_saltati,
            "serie_saltate": self.serie_saltate,
            "scartate": self.scartate,
        }


@transaction.atomic
def scrivi(lettura, abbinamenti, user):
    """La conferma: **un solo `transaction.atomic`**, e questo è il punto.

    «Parziale in anteprima, atomico in conferma»: le righe rotte sono già state
    messe da parte dalla lettura e l'utente ha visto quali, quindi qui non
    resta nessuna decisione da prendere — o entra tutto ciò che è stato
    mostrato, o non entra niente. Il tutto-o-niente puro avrebbe bloccato 317
    righe per due celle sbagliate; il parziale cieco avrebbe reso l'anteprima
    decorativa.

    `user` viene da `request.user` e **da nessun'altra parte**: il `user_id`
    che il CSV porta è il dato di un altro sistema e qui non ha nessuna
    autorità. Nessun import per conto di altri, nemmeno da admin.
    """
    esito = Esito(
        allenamenti_saltati=lettura.sessioni_duplicate,
        serie_saltate=lettura.serie_duplicate,
    )

    per_chiave = {}
    for sessione in lettura.sessioni:
        allenamento = Workout.objects.create(
            user=user,
            # `routine` resta nullo: le schede non si importano, e ciò che
            # sopravvive del legame è il solo `title` — è esattamente il caso
            # che ADR-0002 descrive.
            routine=None,
            title=sessione.title,
            started_at=sessione.started_at,
            ended_at=sessione.ended_at,
            notes=sessione.notes,
            external_id=sessione.external_id,
        )
        per_chiave[sessione.chiave] = allenamento
        esito.allenamenti += 1

    # Le sessioni già presenti: le loro serie nuove vanno appese al loro
    # allenamento, o ricaricare un file aggiornato non aggiungerebbe mai niente.
    duplicate = {}
    for allenamento in Workout.objects.filter(user=user):
        # Le due provenienze dell'`id` di un file, di nuovo insieme: la riga
        # importata si riconosce dal suo `external_id`, quella nata in-app dal
        # suo `nome_pubblico`. Senza la seconda, una serie **nuova** appesa a
        # un allenamento nato qui non troverebbe il suo allenamento e sparirebbe
        # in silenzio — e i no muti in questo progetto si chiudono, non si
        # accettano.
        chiave = allenamento.external_id or nome_pubblico("workout", allenamento.pk)
        duplicate[str(chiave)] = allenamento

    # `(allenamento, esercizio, numero)` è `workout_set_unique`. Due nomi
    # grezzi diversi possono essere abbinati **allo stesso** esercizio — è una
    # scelta legittima dell'utente, «Trazioni» e «Pull up» sono lo stesso
    # movimento — e allora due serie possono collidere sul numero. Il database
    # lo rifiuterebbe con un `IntegrityError`, cioè un 500 in fondo a una
    # transazione: qui si vede prima e diventa una riga del report.
    # Una query sola su tutte le serie dell'utente, non una per allenamento:
    # `duplicate` ora contiene anche gli allenamenti nati in-app, e un ciclo di
    # `values_list` su ognuno sarebbe stato un N+1 che cresce con lo storico.
    presenti = set(
        WorkoutSet.objects.filter(workout__user=user).values_list(
            "workout_id", "exercise_id", "set_number"
        )
    )

    for serie in lettura.serie:
        allenamento = per_chiave.get(serie.chiave_sessione) or duplicate.get(
            serie.chiave_sessione
        )
        if allenamento is None:
            continue

        esercizio = abbinamenti.get(serie.raw_name)
        if esercizio is None:
            esito.scartate.append(
                {
                    "file": FILE_SERIE,
                    "numero": serie.numero,
                    "colonna": "exercise_name",
                    "valore": serie.raw_name,
                    "motivo": "Nessun esercizio abbinato a questo nome.",
                }
            )
            continue

        firma = (allenamento.pk, esercizio.pk, serie.set_number)
        if firma in presenti:
            esito.scartate.append(
                {
                    "file": FILE_SERIE,
                    "numero": serie.numero,
                    "colonna": "set_number",
                    "valore": str(serie.set_number),
                    "motivo": (
                        f"C'è già una serie {serie.set_number} di "
                        f"{esercizio.name} in questo allenamento."
                    ),
                }
            )
            continue
        presenti.add(firma)

        WorkoutSet.objects.create(
            workout=allenamento,
            exercise=esercizio,
            set_number=serie.set_number,
            reps=serie.reps,
            weight=serie.weight,
            set_type=serie.set_type,
            is_completed=serie.is_completed,
            external_id=serie.external_id,
        )
        esito.serie += 1

    return esito


def ricorda(abbinamenti, user):
    """La scelta dell'utente diventa un `ExerciseAlias`: il secondo import non
    la richiede più. È metà del valore di ADR-0010 — l'altra metà è che a
    sceglierlo sia un umano."""
    for raw_name, esercizio in abbinamenti.items():
        ExerciseAlias.objects.update_or_create(
            user=user, raw_name=raw_name, defaults={"exercise": esercizio}
        )
