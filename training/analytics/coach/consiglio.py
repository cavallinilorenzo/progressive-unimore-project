"""Il tipo `Consiglio`, e l'unica ragione per cui non sta in `__init__.py`.

Il dataclass è il vocabolario condiviso del pacchetto: lo costruiscono sia le
regole corte che vivono nella superficie pubblica (`__init__.py`), sia i moduli
che hanno una query propria (`carico.py`). Se restasse in `__init__.py`, ogni
modulo dovrebbe importare il proprio importatore — l'import circolare che
Python risolve solo con l'ordine delle righe, cioè con una trappola per chi
riordina il file.

Resta comunque **una** definizione e **un** punto d'ingresso: `__init__.py` lo
riesporta, e fuori dal pacchetto si continua a scrivere
`analytics_coach.Consiglio`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Consiglio:
    """Una cosa da fare, con dietro il numero che l'ha prodotta.

    `azione` è la frase che dice cosa fare al prossimo allenamento, ed è il
    campo che rende questo dataclass un consiglio invece di un'osservazione: se
    una regola non riesce a riempirlo, quella regola non appartiene al coach.

    `misura` è il numero che l'ha fatto scattare, mostrato in pagina accanto
    alla frase. Un consiglio senza il suo numero è indistinguibile da uno
    inventato — ed è il modo in cui un consiglio *plausibile ma falso* passa
    inosservato, che è il rischio proprio di questa fase: un'analisi sbagliata
    dà un numero che si controlla a mente, un consiglio sbagliato rende una
    pagina perfetta.

    `limite` è ciò che il consiglio **non** sa, quando c'è qualcosa che non sa.
    Sta nel dato e non nel template perché è una proprietà della regola, non
    della pagina: chi aggiunge un tipo di consiglio si trova il campo davanti e
    deve decidere se riempirlo.

    `esercizio` è nullo per i consigli che parlano dell'allenamento in blocco
    (costanza, squilibrio) e valorizzato da quelli che parlano di **una**
    coppia (utente, esercizio), che è l'unità del carico e dello stallo. Serve
    alla dashboard, che mostra il consiglio fuori dalla pagina dell'esercizio e
    deve poterci linkare: senza, il consiglio di carico direbbe «sali a 60 kg»
    senza dire di cosa.
    """

    tipo: str
    titolo: str
    azione: str
    misura: str
    limite: str = ""
    esercizio: object = None


# `Consiglio.priorita`, scritto in #112, è stato tolto qui: non aveva un solo
# consumatore — la selezione legge `REGOLE` **in ordine** e non ha bisogno del
# numero — e per sopravvivere a questo spostamento avrebbe richiesto un import
# dentro il metodo, cioè la stessa circolarità che il file esiste per evitare.
# `PRIORITA` resta dov'era e continua a dare il numero a chi lo chiede.
