"""W1 — la costanza: quanti allenamenti a settimana, e in quali settimane.

`docs/spec/04-analisi.md` la elenca come «`Count` allenamenti per periodo,
dashboard (widget)», e widget resta: passa l'asse 1 del criterio d'ammissione
(alimenta una decisione — «mi sto allenando abbastanza spesso?») ma non l'asse
2, perché `Count` è l'unica riga di ORM avanzato che il corso ha insegnato
(#22). Una pagina propria sarebbe spazio guadagnato senza niente da mostrare.

## W1 *è* il riquadro che la dashboard aveva già

#95 aveva scritto in dashboard un riquadro «costanza» — media di allenamenti a
settimana su 28 giorni — con un `Count` dentro la view. W1 non è una seconda
misura accanto a quella: è quella, spostata qui e arricchita dei **periodi
vuoti** che #99 ha insegnato a riempire. Due misure di costanza sulla stessa
pagina sarebbero la divergenza di #75 un'altra volta, con l'aggravante che
sarebbero entrambe giuste e discordi.

Cosa cambia rispetto al riquadro di #95, ed è la ragione per cui il numero si
muove un poco: la finestra non è più «28 giorni indietro da adesso» ma le
**ultime 4 settimane di calendario**, la stessa griglia dei lunedì di
`/analisi/` e della heatmap. Un progetto con due definizioni di «settimana» è
un progetto che prima o poi mostra due conteggi diversi della stessa settimana.
La media si divide quindi per le settimane **trascorse** della finestra, non
per quattro tonde: l'ultima è in corso, e dividere per una settimana che non è
ancora finita farebbe scendere la costanza ogni lunedì mattina senza che
l'utente abbia fatto niente di diverso.
"""

from django.db.models import Count
from django.db.models.functions import TruncWeek
from django.utils import timezone

from training.analytics.volume import (
    data_locale,
    finestra_settimanale,
    inizio_della_finestra,
)
from training.models import Workout

#: Quattro settimane: la finestra più corta in cui la risposta non è dominata
#: da una settimana storta (#95), e la stessa della heatmap, che sta nella
#: stessa pagina — due finestre diverse a un palmo l'una dall'altra si leggono
#: come un errore.
SETTIMANE_COSTANZA = 4


def costanza(user, settimane=None, oggi=None):
    """Gli allenamenti per settimana, **coi buchi**, e la media.

    Il buco è il dato: una settimana saltata non esiste come riga in una
    `values()`, e un widget che mostrasse solo le settimane piene direbbe
    «quattro settimane da tre allenamenti» a chi si è allenato in due di esse.
    È esattamente il difetto che #99 ha corretto sul grafico del volume, sulla
    misura che di costanza parla per mestiere.
    """
    settimane = settimane or finestra_settimanale(SETTIMANE_COSTANZA, oggi=oggi)
    oggi = oggi or timezone.localdate()

    # `.order_by("periodo")` per la ragione di #99: un `Meta.ordering` residuo
    # finirebbe nel `GROUP BY` e spaccherebbe le settimane in più righe.
    righe = (
        Workout.objects.filter(
            user=user, started_at__gte=inizio_della_finestra(settimane)
        )
        .annotate(periodo=TruncWeek("started_at"))
        .values("periodo")
        .annotate(allenamenti=Count("id"))
        .order_by("periodo")
    )
    per_lunedi = {data_locale(riga["periodo"]): riga["allenamenti"] for riga in righe}
    conteggi = [
        {"settimana": lunedi, "allenamenti": per_lunedi.get(lunedi, 0)}
        for lunedi in settimane
    ]

    # L'altezza della colonnina, in percentuale del massimo della finestra. La
    # calcola qui e non il template, che di aritmetica non ne sa fare: quattro
    # divisioni in Python contro un tag custom da scrivere e spiegare.
    massimo = max(riga["allenamenti"] for riga in conteggi)
    for riga in conteggi:
        riga["altezza"] = round(100 * riga["allenamenti"] / massimo) if massimo else 0

    # I giorni davvero trascorsi nella finestra, ultima settimana parziale
    # inclusa: `+ 1` perché oggi conta, e un allenamento fatto stamattina è
    # costanza di questa settimana, non della prossima.
    giorni = (oggi - settimane[0]).days + 1
    sedute = sum(riga["allenamenti"] for riga in conteggi)

    return {
        "settimane": conteggi,
        "sedute": sedute,
        "media": round(sedute / (giorni / 7), 1),
        "massimo": massimo,
        "da": settimane[0],
        "vuote": sum(1 for riga in conteggi if riga["allenamenti"] == 0),
    }
