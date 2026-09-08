"""L'export dello storico in CSV — e il giro dell'import che si chiude.

**Perché esiste.** L'import nasce da un formato che era lo schema interno di
un'altra app, e l'obiezione che l'ha riorientato è di Lorenzo: *«quei dati
prima di essere importati sono stati esportati da un altro software»*. Senza
export, un estraneo che si iscrive non ha nessun `session_sets.csv` e trova un
import che fallisce senza via d'uscita. Con l'export, Overload smette di essere
«il formato di un'altra app» e diventa **uno dei produttori** del formato di
Progressive (`03-import-ed-export.md`).

**Stesse colonne, stesso parser.** Le intestazioni qui sotto contengono per
costruzione le colonne che `importer.COLONNE_SESSIONI` e
`importer.COLONNE_SERIE` pretendono, e c'è un test che lo verifica invece di
fidarsi: due elenchi di stringhe in due file diversi divergono in silenzio, ed
è la stessa famiglia di guasti che questo progetto chiude con una guardia.

**Perché un modulo e non solo una view.** La stessa ragione di
`training/importer.py`: qui non c'è niente di HTTP, quindi il giro completo
(esporta → riparsifica → zero righe nuove) si prova su uno `StringIO`, senza
passare da un upload per ogni caso.
"""

import csv

from training.importer import FILE_SERIE, FILE_SESSIONI, nome_pubblico
from training.models import Workout, WorkoutSet

#: `user_id` e `routine_id` escono anche se l'import li ignora: il file è lo
#: stesso formato, non un suo sottoinsieme, e chi lo riceve deve poterlo
#: leggere come legge quello di Overload.
INTESTAZIONE_SESSIONI = (
    "id",
    "user_id",
    "routine_id",
    "title",
    "started_at",
    "ended_at",
    "notes",
)

INTESTAZIONE_SERIE = (
    "id",
    "session_id",
    "exercise_name",
    "set_number",
    "reps",
    "weight",
    "set_type",
    "is_completed",
)

#: I due file che l'export produce, col nome con cui l'import li chiede.
FILE = {
    "allenamenti": FILE_SESSIONI,
    "serie": FILE_SERIE,
}


def _quando(momento):
    """ISO 8601 con l'offset, che è ciò che `parse_datetime` rilegge."""
    return momento.isoformat() if momento else ""


def _identita(riga, modello):
    """L'`id` della riga nel file: quello di provenienza, o il nome pubblico.

    Una riga arrivata da un import porta il nome che aveva **là**, così due
    sistemi continuano a chiamarla allo stesso modo; una nata qui porta il suo
    `nome_pubblico`, calcolato e non memorizzato — `external_id` resta nullo, e
    resta vero che un allenamento nato in Progressive non ne finge uno.
    """
    return str(riga.external_id or nome_pubblico(modello, riga.pk))


def esporta_sessioni(uscita, user):
    """`workout_sessions.csv` dell'utente. Restituisce quante righe ha scritto."""
    writer = csv.writer(uscita)
    writer.writerow(INTESTAZIONE_SESSIONI)
    scritte = 0
    for allenamento in Workout.objects.filter(user=user).order_by("started_at"):
        writer.writerow(
            [
                _identita(allenamento, "workout"),
                allenamento.user_id,
                allenamento.routine_id or "",
                allenamento.title,
                _quando(allenamento.started_at),
                _quando(allenamento.ended_at),
                allenamento.notes,
            ]
        )
        scritte += 1
    return scritte


def esporta_serie(uscita, user):
    """`session_sets.csv` dell'utente. Restituisce quante righe ha scritto.

    `exercise_name` e non `exercise_id`: la chiave privata del catalogo di
    questo database non significa niente altrove, mentre il nome sì — ed è la
    stessa ragione per cui l'import legge i nomi e non gli identificativi. Su
    un file esportato da Progressive l'abbinamento poi si risolve da solo, per
    nome esatto, e all'utente non viene chiesto niente.
    """
    writer = csv.writer(uscita)
    writer.writerow(INTESTAZIONE_SERIE)
    serie = (
        WorkoutSet.objects.filter(workout__user=user)
        .select_related("workout", "exercise")
        .order_by("workout__started_at", "set_number", "pk")
    )
    scritte = 0
    for riga in serie:
        writer.writerow(
            [
                _identita(riga, "workoutset"),
                _identita(riga.workout, "workout"),
                riga.exercise.name,
                riga.set_number,
                "" if riga.reps is None else riga.reps,
                "" if riga.weight is None else riga.weight,
                riga.set_type,
                # Minuscolo, che è ciò che l'import legge e ciò che il file di
                # Overload porta: `str(True)` avrebbe scritto «True».
                "true" if riga.is_completed else "false",
            ]
        )
        scritte += 1
    return scritte


def esporta(uscita, quale, user):
    """Scrive in `uscita` il file `quale` (`allenamenti` o `serie`)."""
    if quale == "allenamenti":
        return esporta_sessioni(uscita, user)
    return esporta_serie(uscita, user)
