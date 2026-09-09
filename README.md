# Progressive

Registro degli allenamenti che misura la **progressione del carico**: si
registra quello che si è sollevato, e l'app dice cosa fare di diverso la volta
dopo. Progetto d'esame di Interazione Web e Comunicazione, in Django.

La documentazione sta in [`docs/spec/`](docs/spec/00-indice.md) — indice,
modello dei dati, pagine, analisi — e i perché delle scelte in
[`docs/adr/`](docs/adr/). Il vocabolario del dominio è in
[`CONTEXT.md`](CONTEXT.md).

> Le istruzioni d'installazione, i comandi e la scaletta della demo orale
> arrivano col README di consegna, che è lavoro di una fase successiva
> ([#94](https://github.com/cavallinilorenzo/progetto-django-uni/issues/94)).
> Questo file nasce prima perché la dichiarazione qui sotto non poteva
> aspettarlo.

## Crediti — la figura anatomica non è lavoro nostro

`training/templates/training/_corpo.svg` è la figura umana su cui si accende la
heatmap muscolare della dashboard: 154 path, fronte e retro, ognuno etichettato
`class="g-<gruppo> m-<muscolo>"`.

**Quei contorni non sono stati disegnati per questo progetto.** Lo script che
genera il file — `prototypes/t37-heatmap/build_body_svg.mjs` — non ridisegna
niente: legge i sei SVG di gruppo muscolare di **Overload**, un'applicazione
personale precedente, ne copia ogni attributo `d` **identico**, e si limita ad
aggiungere le classi CSS risolvendo i 23 muscoli con ancoraggi
point-in-polygon. Stessa geometria, stesso `viewBox`, stessi 154 contorni.

Quei sei SVG sono entrati in Overload col commit iniziale e **la loro origine
non è documentata**: non è certo che siano un disegno originale
([#40](https://github.com/cavallinilorenzo/progetto-django-uni/issues/40)). Il
file è versionato qui perché senza il progetto non gira da un clone pulito e la
heatmap resta vuota, ma va detto in chiaro, e va detto anche all'orale: **di
questa figura il progetto ha scritto le classi, non l'anatomia.**

Se un giorno si accertasse che il disegno non è ridistribuibile, si cancella
`_corpo.svg` e la heatmap ripiega sulle barre per gruppo, che sono già
prototipate (`prototypes/t37-heatmap/`, variante A).

Tutto il resto del repo — codice, template, CSS, catalogo degli esercizi, dati
sintetici — è lavoro del progetto.
