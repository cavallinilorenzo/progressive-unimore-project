# Il catalogo esercizi di Progressive

Il catalogo è **globale e scritto a mano** ([ADR-0001](adr/0001-catalogo-esercizi-globale-e-scritto-a-mano.md)):
esiste una sola riga `Exercise` per esercizio, condivisa da tutti gli utenti, ed è
questa condivisione a rendere possibili percentili e classifiche. Vive come quattro
CSV versionati in `data/catalog/`, che sono **la sorgente di verità** — si modificano
a mano, con un editor di testo, e si ricaricano.

## I quattro file

| File                | Righe | Colonne                                        |
| ------------------- | ----: | ---------------------------------------------- |
| `muscle_groups.csv` |     6 | `code,label_it,sort_order`                     |
| `muscles.csv`       |    23 | `code,group_code,label_it,sort_order`          |
| `equipment.csv`     |     9 | `code,label_it,default_bar_weight_kg,sort_order` |
| `exercises.csv`     |   100 | `name,muscle_code,equipment_code`              |

Si caricano con:

```bash
python manage.py load_catalog
```

Il comando è **idempotente**: rieseguirlo aggiorna le righe esistenti invece di
duplicarle, quindi correggere un nome nel CSV e ricaricare è sicuro. Tutto gira in
un solo `transaction.atomic`, e un `muscle_code` o `equipment_code` sconosciuto
fa fallire l'intero caricamento citando file e numero di riga: un catalogo caricato
a metà è peggio di nessun catalogo, perché le analisi girerebbero su muscoli
scoperti senza dirlo.

Questo è il canale d'import «da amministratore», distinto dall'import CSV dello
storico allenamenti, che passa invece da un form web.

## La tassonomia dei muscoli

I 23 muscoli e i 6 gruppi sono copiati da `reporting.muscle_taxonomy` di Overload
(migrazione `0008_reporting_schema.sql`). I **`code` sono identici**, ed è quella
identità a tenere i dati di Progressive reimportabili nella dashboard personale
di Overload.

Le `label_it` sono solo testo d'interfaccia e possono divergere. Divergono in tre
punti, dove Overload aveva lasciato l'inglese in un campo che si chiama `label_it`:

| `code`       | Overload      | Progressive     |
| ------------ | ------------- | --------------- |
| `upperBack`  | `Upper back`  | `Schiena alta`  |
| `middleBack` | `Middle back` | `Schiena media` |
| `lowerBack`  | `Lower back`  | `Lombari`       |

## Gli attrezzi

`Equipment` porta il peso a vuoto dell'attrezzo (`default_bar_weight_kg`), che in
Overload stava invece sul singolo esercizio (`exercises.bar_weight_kg`, migrazione
`0009`). Il peso del bilanciere è una proprietà dell'attrezzo, non del movimento:
tenerlo per esercizio significava ripetere «20» un centinaio di volte e poterlo
sbagliare un centinaio di volte.

I valori: bilanciere 20 kg, bilanciere EZ 10 kg, multipower 15 kg (il contrappeso
rende il bilanciere guidato più leggero di uno olimpico), tutto il resto 0.

## Criterio di completezza: copertura, non quantità

Cento esercizi non sono un obiettivo, sono il risultato. I vincoli veri:

- **Tutti e 23 i muscoli hanno almeno un esercizio.** Il minimo è 2 (trapezio,
  adduttori), e per quei due muscoli è onestamente tutto lo spazio di movimento
  che una palestra offre.
- **Ogni gruppo regge una scheda vera**: petto 16, schiena 20, spalle 12,
  braccia 17, gambe 24, core 11.
- **I fondamentali ci sono tutti**: panca piana, squat, stacco da terra, trazioni
  alla sbarra, military press, rematore con bilanciere.
- **Ognuno dei 24 esercizi dello storico reale di Lorenzo** ha un corrispondente
  nel catalogo, altrimenti l'import del suo storico avrebbe dei buchi.

`yuhonas/free-exercise-db` è servito da **lista di controllo** della copertura,
mai da sorgente da importare: la ricerca [#12](https://github.com/cavallinilorenzo/progetto-django-uni/issues/12)
aveva misurato che mapparlo costava 57 override a mano più la traduzione di 678
nomi inglesi, e [#14](https://github.com/cavallinilorenzo/progetto-django-uni/issues/14)
ha concluso che 678 esercizi su ~100 utenti sintetici diluiscono ogni percentile.

## Aggiungere un esercizio

Si aggiunge una riga a `exercises.csv` e si rilancia `load_catalog`. A progetto
avviato lo si può fare anche dall'admin Django: l'admin e i CSV restano coerenti
finché nessuno rinomina un esercizio solo da una delle due parti — il `name` è
la chiave con cui il comando riconosce una riga già caricata.
