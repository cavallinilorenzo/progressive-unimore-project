# Lo storico reale di Overload: export, formato, volume

Risolve il ticket [Esportare lo storico reale di Overload e capirne formato e volume](https://github.com/cavallinilorenzo/progetto-django-uni/issues/13).
I dati stanno in `data/overload-real/` — **fuori dal versionamento** (`.gitignore`), perché sono
dati personali e il repo d'esame è pubblico.

## Come si rigenera

```bash
python3 scripts/export_overload.py
```

Legge il token della Supabase CLI dal portachiavi di macOS (serve `supabase login` una volta),
poi interroga il progetto `Overload-Database` via endpoint SQL della Management API. Non usa
`supabase db dump` perché quello richiede Docker. Nessuna credenziale è nel repo.

Ogni query filtra sull'account di Lorenzo: Overload è pubblica sull'App Store e nel database
esistono altri tre profili (oggi senza dati). **Il filtro non va tolto.**

## Volume — il fatto che conta

**26 giorni di storico, dal 2026-08-10 al 2026-09-04.**

| tabella | righe |
| --- | --- |
| `profiles` | 1 |
| `exercises` | 24 |
| `routines` | 4 |
| `routine_exercises` | 32 |
| `workout_sessions` | 15 |
| `session_sets` | 317 |

Non è un caso: le migrazioni `0006` e `0007` di Overload hanno azzerato tutti i dati utente
remoti, quindi il database contiene solo ciò che è stato registrato **dopo** quel reset. Lo
storico precedente non esiste su Supabase (`GymLog/lorenzo.md`, sezione «Limiti onesti»).

### Nessun esercizio ha una serie storica sufficiente per uno stallo

Il ticket chiedeva quanti esercizi arrivano a ≥ 8–10 sessioni. Il massimo assoluto è **8**, e lo
raggiungono cinque esercizi; nessuno va oltre.

| sessioni | serie | esercizio |
| --- | --- | --- |
| 8 | 24 | d'Annunzio crunch |
| 8 | 24 | Spinte panca inclinata 30 smith machine |
| 8 | 21 | Overhead extention singolo al cavo |
| 8 | 21 | Alzate laterali singole al cavo |
| 8 | 16 | Pushdown corda |
| 7 | 21 | Trazioni |
| 7 | 18 | Curl in piedi |
| 7 | 18 | Pulley presa larga |
| 5 | 15 | Russian twist, Chest press |
| ≤ 4 | | i restanti 13 esercizi |

Otto sedute distribuite su 26 giorni sono **poco più di tre settimane**. Uno stallo si definisce
sull'assenza di progresso protratta nel tempo: su tre settimane il carico può ancora salire per
semplice adattamento iniziale, quindi questi dati **non permettono di validare il rilevamento
dello stallo**. Servono i dati sintetici, e i dati reali valgono come caso di prova dell'import
CSV e come banco di realismo per il generatore, non come set di validazione.

## Quanto sono sporchi

Sporcizia vera, quella che l'import CSV deve saper reggere:

- **61 serie su 317 (19%) non completate** (`is_completed = false`): serie programmate dalla
  routine e mai eseguite. Hanno sistematicamente `reps`, `weight`, `rest_seconds_used` e
  `completed_at` a null. Nessuna serie non completata porta un peso — le due cose sono coerenti.
- **25 serie completate senza peso**: sono gli esercizi a corpo libero. `Trazioni` (21 serie),
  `Leg raises` (9) e `Avambracci verso il basso` (12) non hanno **mai** un peso. Un import che
  pretende `weight` non nullo su una serie completata rifiuterebbe dati legittimi.
- **2 serie completate senza `reps`**: queste sono errori veri di inserimento.
- **2 sessioni su 15 con una durata assurda**: una da **0 minuti** (10 agosto, 22 serie
  registrate) e una da **1516 minuti**, cioè 25 ore (3 settembre). `ended_at` esiste sempre ma
  non è affidabile: l'app lo scrive quando l'utente chiude la sessione, e capita che se ne
  dimentichi. La durata va trattata come dato sospetto, non come misura.
- **Colonne di fatto costanti**: `set_type` vale `working` su tutte e 317 le serie,
  `intensity` vale `moderate` su tutte e 15 le sessioni, `is_warmup` è sempre `false`,
  `notes` è sempre vuoto su ogni sessione. Sono campi che l'app espone ma che nell'uso reale
  non variano — modellarli in Progressive va giustificato, non dato per scontato.
- **Un esercizio senza `primary_muscle`**: `Spinte spalle macchinario`.
- **Nomi puliti**: 24 esercizi, 24 nomi distinti, nessun duplicato e nessun archiviato. I nomi
  sono in italiano e scritti a mano (con apostrofi tipografici: `d'Annunzio`, `Avambracci verso
  l'alto`), quindi non si agganciano a `free-exercise-db` per uguaglianza di stringa.
- **Nessuna sessione orfana**: `ended_at` mai null, `routine_id` mai null, `title` mai null.

## Schema CSV effettivo

Una riga d'intestazione per file, colonne nell'ordine del database. Convenzioni del formato:
null → campo vuoto; booleani → `true` / `false`; timestamp → `YYYY-MM-DD HH:MM:SS.ssssss+00`
(sempre UTC); `jsonb` → JSON compatto; virgolette CSV standard.

```
profiles.csv          id, display_name, default_rest_seconds, weight_unit, created_at,
                      updated_at, body_mass_kg

exercises.csv         id, user_id, name, default_rest_seconds, notes, is_archived,
                      created_at, updated_at, primary_muscle

routines.csv          id, user_id, name, notes, is_archived, created_at, updated_at

routine_exercises.csv id, routine_id, exercise_id, position, target_sets, target_reps,
                      target_reps_max, is_per_side, rest_seconds, set_types, notes,
                      created_at, updated_at

workout_sessions.csv  id, user_id, routine_id, title, started_at, ended_at, notes,
                      created_at, updated_at, intensity

session_sets.csv      id, session_id, exercise_id, set_number, reps, weight, is_warmup,
                      set_type, is_completed, rest_seconds_used, completed_at,
                      created_at, updated_at
```

Note sui tipi che l'import dovrà gestire:

- **Tutte le chiavi sono UUID**, non interi. L'import deve decidere se conservarli (utile per
  reimportare senza duplicare) o rimapparli su chiavi Django.
- `weight` e `body_mass_kg` sono `numeric`, non interi: i pesi hanno mezzi chili.
- `set_types` è `jsonb` — un array come `["working","working","working"]`, uno per serie
  prevista. Duplica `target_sets`, e nei dati reali è sempre tutto `working`.
- `is_per_side` è salvato ma **l'app lo ignora** nel calcolo del volume (10 ripetizioni con
  manubri da 20 kg contano 200, non 400). Se Progressive lo applicasse, i suoi numeri non
  coinciderebbero con quelli di Overload.
- `rest_seconds_used` **non è il riposo realmente fatto**: è la durata configurata del timer.
  Non ci si può costruire sopra un'analisi del recupero.

## Cosa ne consegue per la mappa

1. **Il rilevamento dello stallo si valida sui dati sintetici**, non su questi. Il generatore
   (#18) va progettato sapendo che è l'unica fonte di serie storiche lunghe.
2. **L'import CSV (#14 e a valle) ha il suo formato**: quello qui sopra, con la sporcizia qui
   sopra. Le serie non completate e i pesi nulli legittimi sono i casi da mostrare al prof nel
   report errori riga per riga.
3. **Il modello di dominio** può copiare lo schema di Overload, ma `set_type`, `intensity`,
   `is_warmup` e `notes` sono campi mai usati davvero: tenerli è una scelta da fare, non
   un'eredità da subire.
