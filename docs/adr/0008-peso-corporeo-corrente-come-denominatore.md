---
status: accepted
---

# Il peso corporeo corrente è il denominatore della forza relativa

La **forza relativa** — massimale stimato diviso peso corporeo — è il criterio con cui utenti di taglia diversa diventano confrontabili: alimenta il percentile di forza e ordina la classifica di forza. Il denominatore è `user.body_mass_kg`, cioè **un solo valore corrente sull'utente**, applicato anche a massimali raggiunti mesi prima.

È un'approssimazione, e va detta per intero: chi dimagrisce vede salire **retroattivamente** tutta la propria storia di forza relativa, perché lo stesso massimale di sei mesi fa viene diviso per il peso di oggi.

Le due alternative sono state valutate e scartate:

- **Un campo `body_mass_kg` nullable su `Workout`** (il peso di quel giorno). Nel modello costerebbe quasi nulla, ma il formato CSV di importazione non ha quella colonna, e il generatore di dati sintetici dovrebbe produrre una traiettoria di peso credibile per un centinaio di utenti. Costo reale, effetto invisibile nella demo.
- **Un modello di storico pesi**. È un settimo modello di prima classe per un problema che sui dati sintetici non si manifesta, e la traccia chiede 5–6 modelli correlati, non il maggior numero possibile.

## Consequences

Il peso corporeo diventa una **condizione di ammissione** alle graduatorie: un utente senza `body_mass_kg` non ha forza relativa e non compare in classifica né riceve un percentile — non con un valore sbagliato, ma assente, con l'invito a compilare il profilo.

L'approssimazione retroattiva è un limite noto e si dichiara alla discussione orale. Se un giorno servisse la precisione storica, la strada è il campo su `Workout`: si aggiunge nullable e le righe vecchie continuano a ricadere sul peso corrente.
