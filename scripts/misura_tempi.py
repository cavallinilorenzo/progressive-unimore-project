"""Cronometra le pagine di Progressive sul database vero, e conta le query.

Uno **script una tantum**, non un test — e la distinzione è deliberata
(#102). I *conteggi* di query diventano test permanenti in `training/tests.py`,
perché sono deterministici; i *tempi* no, perché un test che fallisce quando la
macchina è occupata è un test che si impara a ignorare, ed è peggio di non
averlo.

La metodologia e la soglia stanno in `docs/misure/tempi-query.md`, e ci stavano
**prima** che questo file esistesse.

Uso:

    python3 scripts/misura_tempi.py --db /percorso/di/db.sqlite3

Il percorso serve perché `db.sqlite3` non è versionato (dati personali, repo
pubblico), quindi in un worktree non c'è: sta nel checkout principale.
"""

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# `DEBUG = False` **prima** di `django.setup()`: con `DEBUG = True` Django
# tiene in memoria ogni query eseguita, e i tempi risultano falsi in peggio.
# Non si tocca `config/settings.py`, che resta il file d'esame con
# `DEBUG = True`: qui si sovrascrive per il solo processo di misura.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.models import Count  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

# Le sette pagine e il perché di ognuna: `docs/misure/tempi-query.md`.
PAGINE = [
    ("Dashboard", "/"),
    ("Analisi (settimane)", "/analisi/"),
    ("Analisi (mesi)", "/analisi/?periodo=mese"),
    ("Dettaglio esercizio", "/esercizi/panca-piana-con-bilanciere/"),
    ("Storico allenamenti", "/allenamenti/"),
    ("Classifica forza", "/classifiche/forza/"),
    ("Classifica schede", "/classifiche/schede/"),
]

RIPETIZIONI = 10
DEMO_PK = 64


def _cronometra(client, url):
    """Mediana di RIPETIZIONI richieste, warm-up scartato, più il conteggio query.

    Il warm-up non è cortesia verso la macchina: la prima richiesta paga import
    dei moduli, compilazione dei template e cache fredda del filesystem, cioè
    tre costi che si pagano una volta e che non sono la pagina.
    """
    risposta = client.get(url)
    if risposta.status_code != 200:
        raise SystemExit(f"{url} ha risposto {risposta.status_code}, non 200")

    tempi = []
    for _ in range(RIPETIZIONI):
        inizio = time.perf_counter()
        client.get(url)
        tempi.append((time.perf_counter() - inizio) * 1000)

    with CaptureQueriesContext(connection) as query:
        client.get(url)

    return statistics.median(tempi), min(tempi), max(tempi), len(query)


def _conta_query(client, url):
    """Solo il conteggio, per la verifica di invarianza sul secondo utente."""
    client.get(url)  # warm-up: la prima richiesta di una sessione fa query in più
    with CaptureQueriesContext(connection) as query:
        risposta = client.get(url)
    if risposta.status_code != 200:
        return None
    return len(query)


def _banda(millisecondi):
    if millisecondi < 300:
        return "verde"
    if millisecondi < 1000:
        return "giallo"
    return "ROSSO"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(BASE_DIR / "db.sqlite3"),
        help="percorso di db.sqlite3 (non versionato: sta nel checkout principale)",
    )
    argomenti = parser.parse_args()

    percorso = Path(argomenti.db).resolve()
    if not percorso.exists():
        raise SystemExit(f"database non trovato: {percorso}")

    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.DATABASES["default"]["NAME"] = str(percorso)

    Utente = get_user_model()
    demo = Utente.objects.get(pk=DEMO_PK)

    # Il secondo utente della verifica di invarianza: quello con **meno** serie
    # fra chi ne ha almeno una. Se il conteggio di query cambia fra i due, la
    # pagina ha un N+1 — a prescindere da quanto è veloce.
    corto = (
        Utente.objects.annotate(n=Count("workouts__sets"))
        .filter(n__gt=0)
        .exclude(pk=DEMO_PK)
        .order_by("n")
        .first()
    )

    serie_demo = demo.workouts.aggregate(n=Count("sets"))["n"]
    serie_corto = corto.workouts.aggregate(n=Count("sets"))["n"]

    print(f"database  : {percorso} ({percorso.stat().st_size / 1e6:.1f} MB)")
    print(f"DEBUG     : {settings.DEBUG}")
    print(f"demo      : {demo.username} — {serie_demo} serie")
    print(f"confronto : {corto.username} — {serie_corto} serie")
    print(f"mediana su {RIPETIZIONI} richieste, warm-up scartato\n")

    client = Client()
    client.force_login(demo)

    client_corto = Client()
    client_corto.force_login(corto)

    intestazione = f"{'pagina':<24} {'mediana':>9} {'min':>8} {'max':>8} {'query':>6} {'q.corto':>8}  banda"
    print(intestazione)
    print("-" * len(intestazione))

    righe = []
    for nome, url in PAGINE:
        mediana, minimo, massimo, query = _cronometra(client, url)
        query_corto = _conta_query(client_corto, url)
        banda = _banda(mediana)
        righe.append((nome, url, mediana, minimo, massimo, query, query_corto, banda))
        mostrato = "n/d" if query_corto is None else str(query_corto)
        print(
            f"{nome:<24} {mediana:>8.1f}ms {minimo:>7.1f}ms {massimo:>7.1f}ms "
            f"{query:>6} {mostrato:>8}  {banda}"
        )

    print()
    peggiore = max(righe, key=lambda r: r[2])
    print(f"pagina più lenta: {peggiore[0]} — {peggiore[2]:.1f} ms ({peggiore[7]})")

    divergenti = [r for r in righe if r[6] is not None and r[5] != r[6]]
    if divergenti:
        print("\nINVARIANZA VIOLATA — il conteggio query cambia con lo storico:")
        for r in divergenti:
            print(f"  {r[0]}: {r[5]} query su {serie_demo} serie, {r[6]} su {serie_corto}")
    else:
        print("invarianza: ok — nessuna pagina cambia numero di query con lo storico")


if __name__ == "__main__":
    main()
