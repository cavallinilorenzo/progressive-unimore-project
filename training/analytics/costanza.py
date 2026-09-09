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

## Da #112 questo modulo conta gli allenamenti anche per il coach

Il consiglio di costanza (`05-coach-e-stallo.md`) chiede un numero che W1 non
dà — gli allenamenti in **14 giorni mobili** — e la tentazione era scriverne il
`Count` dentro il coach. Sarebbe stata la divergenza di #75 nel punto peggiore:
il riquadro del consiglio e il riquadro W1 stanno a un palmo l'uno dall'altro
sulla stessa pagina, e due conteggi degli stessi allenamenti calcolati in due
file diversi si sarebbero allontanati al primo ripensamento sul fuso orario.

Quindi c'è **un solo modulo che sa contare gli allenamenti di un utente**, e da
qui escono entrambe le finestre, ciascuna col suo nome e la sua ragione:
`costanza()` per la griglia dei lunedì che si mostra, `allenamenti_per_il_coach()`
per i giorni mobili su cui si decide. Il perché siano diverse è scritto per
esteso su `GIORNI_DEL_CONSIGLIO`.
"""

from datetime import datetime, time, timedelta

from django.db.models import Count, Q
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


#: La finestra del **consiglio** di costanza: 14 giorni **mobili**, e non le
#: due settimane di calendario della griglia qui sopra.
#:
#: Le due finestre restano diverse ed è una decisione, non una svista (#112).
#: Il riquadro W1 **confronta settimane fra loro**, e per confrontarle deve
#: tagliarle dove le taglia `TruncWeek`, o la colonnina di questa settimana
#: conterrebbe giorni della scorsa. Il consiglio risponde a un'altra domanda —
#: «adesso, ti stai allenando?» — e sulla griglia dei lunedì quella risposta
#: cambierebbe da sola ogni lunedì mattina: chi si allena una volta a settimana
#: ha 2 allenamenti in 14 giorni mobili (nessun consiglio, ed è ciò che la spec
#: chiede) ma solo 1 nelle ultime due settimane di calendario appena scoccata
#: la mezzanotte della domenica. Un consiglio che compare e sparisce senza che
#: l'utente abbia fatto niente di diverso è un difetto che si vede in pagina,
#: ed è lo stesso da cui `media` si difende dividendo per i giorni trascorsi.
#:
#: Il rischio delle due finestre è la divergenza di #75, e la difesa è che
#: **vivono nello stesso modulo**: c'è un solo posto che sa contare gli
#: allenamenti di un utente, e da lì escono entrambi i numeri con le loro due
#: etichette. Due misure discordi sono un problema quando non si sa quale
#: guardare; qui il riquadro dice «negli ultimi 14 giorni» e W1 dice «in 4
#: settimane», e la pagina non lascia scegliere al lettore.
GIORNI_DEL_CONSIGLIO = 14

#: Sotto questa soglia di allenamenti nei `GIORNI_DEL_CONSIGLIO` il coach parla
#: di costanza (`05-coach-e-stallo.md`).
ALLENAMENTI_DELLA_SOGLIA = 2

#: E non parla affatto a chi non ha ancora questo storico alle spalle: a due
#: allenamenti totali «ti stai allenando poco» non è un consiglio, è un
#: rimprovero a chi ha appena cominciato, e per giunta basato su niente.
STORICO_MINIMO = 4


def allenamenti_per_il_coach(user, finestra_squilibrio=None, oggi=None):
    """I tre conteggi che le regole del coach leggono, in **una query sola**.

    Tre `Count` condizionati in un `aggregate()`, e non tre `.count()`: sono la
    stessa scansione della stessa tabella, e chiederla tre volte metterebbe
    tre query in cima alla pagina più visitata del progetto per un risultato
    identico. È anche la tecnica del ponte che il corso non ha mostrato e che
    all'orale si racconta in una riga — `Count(filter=Q(...))`.

    - `totali` — lo storico, per la soglia di ammissione del consiglio di
      costanza. **Nessun filtro di data**: «se ne ha già almeno 4» parla della
      vita dell'utente, non della finestra.
    - `recenti` — i `GIORNI_DEL_CONSIGLIO` mobili del consiglio di costanza.
    - `nella_finestra` — gli allenamenti nella finestra dello **squilibrio**,
      che è quella della heatmap: il conteggio e le serie per gruppo devono
      guardare gli stessi giorni, o le due metà della condizione parlerebbero
      di due periodi diversi e il consiglio potrebbe dire «zero gambe in un
      mese con 8 allenamenti» contando gli 8 altrove.

    Nessuno dei tre cresce con lo storico: sono aggregati, ed è la guardia di
    #86 sulla dashboard.
    """
    finestra_squilibrio = finestra_squilibrio or finestra_settimanale(
        SETTIMANE_COSTANZA, oggi=oggi
    )
    # `- 1` perché **oggi conta**: 14 giorni che finiscono stasera cominciano
    # 13 giorni fa, non 14. Ed è una data e non un `now() - 14 giorni` per la
    # ragione di tutto il modulo: un allenamento fatto stamattina alle 7 non
    # deve entrare o uscire dalla finestra a seconda dell'ora in cui l'utente
    # apre la dashboard.
    da_recenti = (oggi or timezone.localdate()) - timedelta(
        days=GIORNI_DEL_CONSIGLIO - 1
    )

    return Workout.objects.filter(user=user).aggregate(
        totali=Count("id"),
        recenti=Count(
            "id",
            filter=Q(
                started_at__gte=timezone.make_aware(
                    datetime.combine(da_recenti, time.min)
                )
            ),
        ),
        nella_finestra=Count(
            "id",
            filter=Q(started_at__gte=inizio_della_finestra(finestra_squilibrio)),
        ),
    )
