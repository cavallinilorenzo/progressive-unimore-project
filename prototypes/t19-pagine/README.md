# Prototipo #19 — struttura delle pagine, `base.html` e il look di Progressive

**Codice usa e getta.** Non e' il progetto vero: quello nasce dopo la spec (#20).
Nessun database, nessuna auth, dati finti in `config/views.py`.

## Avvio

```
uv run --with 'django>=6.0.3' python prototypes/t19-pagine/manage.py runserver
```

Poi <http://127.0.0.1:8000/>. Si salta fra le varianti con la barra in basso,
con le frecce &larr; &rarr; della tastiera, o a mano con `?variant=A|B|C`.

## Le tre varianti

Non sono tre palette: sono tre risposte diverse alla domanda «che cos'e'
Progressive quando lo apri».

| | Variante | Guscio | Cosa mette per primo | Il prezzo |
|---|---|---|---|---|
| **A** | Scoreboard | Nav orizzontale, canvas near-black | La riga di cifre; lo stallo e' un avviso | ~200 righe di CSS custom da mantenere |
| **B** | Coach | Sidebar a sinistra, chiaro, nav per intenzione | Il verdetto e l'azione consigliata | La dashboard smette di essere un cruscotto |
| **C** | Console | Navbar Bootstrap, zero CSS custom | Tabelle e card, densita' alta | Nessuna identita': e' l'esempio del prof |

A eredita l'identita' **Pulse** di Overload (`~/Developer/GymLog/BRAND.md`):
`ink` + `volt`, tipografia compressa maiuscola, il chip delta `▲ +2.5`.
C e' il pavimento del confronto: costa quasi nulla, quindi A e B devono
guadagnarsi la differenza.

## Cosa e' vero anche fuori dal prototipo

- I tre `base_*.html` sono **candidati veri** a `base.html`, ognuno con i tre
  blocchi che la traccia impone (`header`/`content`/`footer`) piu'
  `title`, `extra_head`, `scripts`.
- I grafici sono alimentati da `json_script` nel template, mai da un endpoint
  JSON: e' il pattern deciso in #16.
- I dati finti hanno le proporzioni dello storico reale misurato in #13
  (15 sessioni, 317 serie, 24 esercizi in 26 giorni), perche' una dashboard
  giudicata su dati inventati generosi mente sulla densita' che avra' davvero.

L'unico JavaScript scritto a mano e' la barra di switch in `_switcher.html`,
che e' impalcatura e muore col prototipo.
