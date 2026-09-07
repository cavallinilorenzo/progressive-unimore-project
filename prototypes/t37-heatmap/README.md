# Prototipo #37 — la heatmap muscolare

**Codice usa e getta.** Tre risposte alla domanda del ticket, sulla stessa
rotta, nel guscio della variante A vinta in #19.

## L'esito

**Vince C, la figura anatomica a 23 muscoli**, con la lista dei muscoli
annidata sotto i sei gruppi: sei righe che si aprono una per volta, invece di
23 righe piatte. Il menu e' `details`/`summary`, HTML nativo, quindi la
revisione non costa una riga di JavaScript.

Resta un blocco fuori dal design: la **provenienza dell'anatomia** (in fondo).

## Avvio

```
uv run --with django==6.1.1 python prototypes/t19-pagine/manage.py runserver
```

Poi <http://127.0.0.1:8000/heatmap/>. Frecce &larr; &rarr; o `?variant=A|B|C`.

| | Variante | Cosa mostra |
|---|---|---|
| **A** | Barre per gruppo | Il ripiego a costo zero, gia' in `dashboard_a.html` |
| **B** | Figura anatomica, 6 gruppi | Poche regioni, tutte accendibili |
| **C** | Figura anatomica, 23 muscoli | Precisa; 4 regioni spente per come e' fatto il catalogo |

## La cosa che ha cambiato la domanda

Il ticket dava per scontato che la figura anatomica costasse molto: «trovare o
disegnare un SVG del corpo umano con le regioni etichettate e mapparle sui 23
muscoli». **Quel lavoro e' gia' fatto**, in Overload:
`~/Developer/GymLog/Scripts/build_muscle_maps.mjs` risolve i 154 path di
un'anatomia condivisa (fronte + retro, viewBox 1448×1448) sui 23 muscoli con
ancoraggi point-in-polygon, e **fallisce la build** se un'ancora diventa ambigua
o non risolve a esattamente un path.

E i codici dei muscoli in quello script sono **identici** a quelli di
`data/catalog/muscles.csv` scritto in #27 — `chestUpper`, `deltoidLateral`,
`rectusAbdominis`, tutti e 23. Non c'e' nessuna mappatura da inventare.

## Come funziona senza JavaScript

`build_body_svg.mjs` riusa quella logica ma emette **un solo** SVG in cui ogni
path porta `class="g-<gruppo> m-<muscolo>"`, in
`prototypes/t19-pagine/templates/prototype/_corpo.svg` (51 KB, 154 path,
23/23 muscoli coperti — lo script lo verifica ed esce con errore altrimenti).

Da li' in poi e' Django puro:

- l'SVG e' un **partial statico**, incluso con `{% include %}`; la view non lo tocca mai;
- la view emette solo un blocco `<style>` con una riga di `fill` per classe.

Stesso principio di `json_script` scelto in #16: i dati entrano nella pagina
come dati, non come DOM costruito a mano. Zero JavaScript applicativo, come
vuole la mappa.

## Cosa e' vero anche fuori dal prototipo

- **La scala normalizza sul massimo, non sul totale.** La domanda della heatmap
  e' «cosa alleno di piu' e cosa trascuro»: un confronto fra regioni, non una
  quota. La radice (`t ** 0.65`) schiarisce i valori bassi, altrimenti 6 serie
  su 34 sono indistinguibili da zero e la mappa mente per arrotondamento.
- **Grigio = zero serie = nessun dato.** Sono la stessa tinta, e la variante C
  lo espone invece di nasconderlo.
- I numeri finti sono i sei gruppi di #19 (317 serie, le proporzioni dello
  storico vero di #13) disaggregati sui 23 muscoli.

## Due cose misurate qui, non supposte

1. **A 6 gruppi la figura non comunica.** I sei totali (62/74/41/48/68/24)
   stanno in una banda stretta, quindi il corpo esce verde quasi uniforme: si
   distingue solo il core. Le barre di A separano quegli stessi sei valori in
   modo molto piu' netto. **La figura si guadagna il posto solo a 23 muscoli.**
2. **I muscoli sempre spenti sono 4 su 23**, non «molti» come temeva il ticket:
   schiena alta, adduttori, abduttori, trasverso. Sono i muscoli che non sono
   primari di quasi nessun esercizio comune, dato che il catalogo di #27 tagga
   un solo muscolo primario.

## Il nodo aperto: la provenienza dell'SVG

I sei SVG di gruppo di Overload sono entrati nel repo nel commit iniziale e
**la loro provenienza non e' documentata da nessuna parte**. `Progressive` e'
un repo pubblico: prima di committare `_corpo.svg` va accertato da dove
vengono. Se non sono ridistribuibili, la variante A resta, ed e' gia' pronta.
