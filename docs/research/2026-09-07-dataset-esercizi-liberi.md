# Dataset liberi di esercizi da palestra — indagine

Ticket: [#12](https://github.com/cavallinilorenzo/progetto-django-uni/issues/12) · Mappa: [#11](https://github.com/cavallinilorenzo/progetto-django-uni/issues/11)
Data: 2026-09-07 · Tutti i dati sono stati verificati scaricando le fonti, non leggendo riassunti.

## Risposta breve

**Sì: `yuhonas/free-exercise-db`, 876 esercizi, licenza Unlicense (pubblico dominio), JSON singolo.**
Ma va usato **solo per i metadati** (nome, muscoli, attrezzatura, meccanica, livello): **le immagini e con ogni probabilità il testo delle `instructions` non sono liberi** — sono scraped, e il mantenitore a monte lo dichiara per iscritto. Vedi [§4](#4-il-problema-delle-immagini-il-punto-che-decide).

La tassonomia dei muscoli è **più grossolana della nostra**: 17 etichette contro i nostri 23 muscoli. 13 dei 23 si raggiungono con una corrispondenza diretta; 9 (i tre capi del petto, i tre deltoidi, `rectusAbdominis`, `obliques`, `transverse`) richiedono una disambiguazione sul nome; `upperBack` non è raggiungibile affatto. Vedi [§5](#5-mappatura-sui-23-muscoli--6-gruppi).

`wger` è legalmente più pulito ma la sua tassonomia è **ancora più povera** (15 muscoli, senza avambracci, adduttori, abduttori, lombari, deltoidi laterale/posteriore): non regge il motore analitico. Serve come **fonte secondaria** per nomi italiani e immagini lecite. `ExerciseDB` non è un dataset: è un'API commerciale.

---

## 1. Metro di paragone: la tassonomia di Overload

Fonte primaria: `~/Developer/GymLog/SupabaseMigrations/0008_reporting_schema.sql`, tabella `reporting.muscle_taxonomy`.

23 muscoli in 6 gruppi (`chest`, `back`, `shoulders`, `arms`, `legs`, `core`):

| gruppo | muscoli |
| --- | --- |
| chest | `chestUpper`, `chestMid`, `chestLower` |
| back | `lats`, `traps`, `upperBack`, `middleBack`, `lowerBack` |
| shoulders | `deltoidFront`, `deltoidLateral`, `deltoidRear` |
| arms | `biceps`, `triceps`, `forearms` |
| legs | `quads`, `hamstrings`, `glutes`, `calves`, `adductors`, `abductors` |
| core | `rectusAbdominis`, `obliques`, `transverse` |

Il file commenta esplicitamente che il mapping 23→6 «esiste SOLO in Swift» ed è duplicato in SQL, e che le view fanno `LEFT JOIN`, quindi *un valore non mappato compare come gruppo NULL invece di sparire dagli aggregati*. Vale la pena replicare la stessa scelta difensiva in Django.

---

## 2. Candidato 1 — `yuhonas/free-exercise-db` ✅ raccomandato (con tagli)

Fonti: [repo](https://github.com/yuhonas/free-exercise-db), `LICENSE.md`, `dist/exercises.json` scaricato il 2026-09-07.

| voce | valore verificato |
| --- | --- |
| esiste ancora | sì, non archiviato, ultimo push 2026-08-30 |
| stelle | 1846 |
| licenza (dichiarata) | **Unlicense** (`LICENSE.md`, riconosciuta dall'API GitHub come `Unlicense`) |
| formato | un JSON per esercizio in `exercises/`, più il combinato `dist/exercises.json`; c'è un `schema.json` JSON-Schema e un target `make dist/exercises.nd.json` per l'import in Postgres |
| dimensione | **876 esercizi** (il ticket dava ~800 come metro: superato) |
| immagini | 1746 file, 873 esercizi su 876 ne hanno almeno una — **ma vedi §4** |

Schema di ogni voce (chiavi effettivamente presenti nel file):

```json
{
  "id": "3_4_Sit-Up",
  "name": "3/4 Sit-Up",
  "force": "pull",            // push | pull | static | null
  "level": "beginner",        // beginner | intermediate | expert
  "mechanic": "compound",     // compound | isolation | null
  "equipment": "body only",
  "primaryMuscles": ["abdominals"],
  "secondaryMuscles": [],
  "instructions": ["Lie down on the floor and secure your feet. ..."],
  "category": "strength",
  "images": ["3_4_Sit-Up/0.jpg", "3_4_Sit-Up/1.jpg"]
}
```

Copre **tutti** i campi chiesti dal ticket, compresi i due opzionali: `mechanic` dà compound/isolation e `level` dà il livello.

Distribuzioni misurate:

- `category`: strength 584, stretching 123, plyometrics 61, powerlifting 38, olympic weightlifting 35, strongman 21, cardio 14.
- `equipment` (13 valori): barbell 170, dumbbell 123, other 122, body only 111, cable 81, **null 77**, machine 67, kettlebells 56, bands 20, medicine ball 17, exercise ball 12, foam roll 11, e-z curl bar 9.
- `level`: beginner 525, intermediate 294, expert 57.
- `mechanic`: compound 491, isolation 298, **null 87**.
- `force`: pull 371, push 371, static 104, **null 30**.

Qualità: **0 esercizi senza `primaryMuscles`**, **0 nomi duplicati**, **1 solo esercizio con più di un muscolo primario**. Il README dichiara apertamente che `force`, `mechanic` ed `equipment` sono incompleti in alcuni file (per questo lo schema ammette `null`).

**Filtro consigliato.** Tenendo solo `category ∈ {strength, powerlifting, olympic weightlifting, strongman}` restano **678 esercizi** — ed è qui che i buchi spariscono quasi del tutto: in quel sottoinsieme gli `equipment` nulli scendono da 77 a **6**. Vengono scartati 123 stretching, 61 pliometrici, 14 cardio, che per una app di sovraccarico progressivo sono comunque rumore.

## 3. Candidato 2 — `wrkout/exercises.json` (l'originale, superato)

Fonti: [repo](https://github.com/wrkout/exercises.json), `LICENSE.md`, `CONTRIBUTING.md`, README.

Esiste ancora (non archiviato), 632 stelle, ma ultimo push **2025-02-16**: fermo da oltre un anno e mezzo. Anche questo Unlicense. `free-exercise-db` è dichiaratamente un fork/ristrutturazione di questo dataset (README di yuhonas, sezione «Special Thanks»), con dati riorganizzati e uno schema validabile. **Non c'è motivo di usare l'originale al posto del fork**: stessa origine, stessa licenza, meno manutenzione, nessun JSON-Schema.

Da notare: il README di wrkout punta ora a `wrkout.xyz`, un prodotto **a pagamento** con 2500+ esercizi e immagini/video utilizzabili commercialmente. È il segnale che la versione gratuita non è pensata come prodotto legalmente completo.

## 4. Il problema delle immagini (il punto che decide)

Questa è la scoperta che cambia la raccomandazione, e viene da fonti primarie di prima mano.

**`CONTRIBUTING.md` di wrkout**, testualmente:

> Currently all exercises have two images, these have been scrapped off the internet, therefore l do not own the copy right for these images and would advise against using them in comercial projects.

**Il mantenitore di free-exercise-db**, nella [issue #2](https://github.com/yuhonas/free-exercise-db/issues/2) del suo repo:

> the derived project is licensed using Unlicense license though **I actually have no idea where the images are from or if they are royalty free** so usage would be at your own risk

E nella [wrkout #305](https://github.com/wrkout/exercises.json/issues/305) un utente ricostruisce la provenienza via reverse image search fino a bodybuilding.com, citandone i termini d'uso, e conclude che lo stato della licenza è «clearly infringing». Nella [free-exercise-db #13](https://github.com/yuhonas/free-exercise-db/issues/13) un altro contributore riconosce immagini di ExRx.net.

Conseguenze operative per `Progressive`:

1. **Non committare le immagini nel repo pubblico** e non farne mirror. Il repo del progetto d'esame è pubblico su GitHub.
2. L'**Unlicense copre ciò che i mantenitori potevano dedicare al pubblico dominio**, cioè la struttura del dataset. Non può sanare a valle materiale di terzi: `nemo dat quod non habet`. La dichiarazione di licenza del repo **non è** una garanzia sui contenuti scraped.
3. Anche il testo delle **`instructions`** ha la stessa provenienza (prosa descrittiva, copiata insieme alle foto). Va trattato con la stessa cautela: prosa originale è opera dell'ingegno, un elenco di nomi/muscoli/attrezzi no. **Per il progetto d'esame non servono**: si importano solo i metadati e si lascia `instructions` fuori, oppure la si riscrive dove serve davvero.
4. Nome, muscolo primario, muscoli secondari, attrezzatura, meccanica, livello sono **fatti**, non espressione creativa. Sono la parte del dataset su cui si può stare tranquilli — ed è esattamente la parte che il ticket chiede.

> Nota su Overload: il piano `~/Developer/GymLog/docs/superpowers/plans/2026-07-17-stock-exercise-catalog.md` prevedeva di caricare proprio quelle foto su un bucket Supabase pubblico. Quel piano **non è mai stato eseguito** (né `Scripts/build_exercise_catalog.mjs` né `Scripts/exercise_name_translations.json` né `GymLog/Resources/exercise_catalog.json` esistono sul disco). Se un giorno lo si esegue, questo paragrafo è il motivo per rivederne la parte immagini.

## 5. Mappatura sui 23 muscoli / 6 gruppi

`free-exercise-db` usa **17 etichette** sia per `primaryMuscles` sia per `secondaryMuscles`. Sono più grossolane delle nostre.

### 5.1 Corrispondenze dirette (13 dei 23 muscoli)

| free-exercise-db | `muscle_taxonomy` | gruppo | # come primario |
| --- | --- | --- | --- |
| `quadriceps` | `quads` | legs | 148 |
| `hamstrings` | `hamstrings` | legs | 79 |
| `triceps` | `triceps` | arms | 73 |
| `biceps` | `biceps` | arms | 53 |
| `lats` | `lats` | back | 38 |
| `middle back` | `middleBack` | back | 34 |
| `calves` | `calves` | legs | 28 |
| `lower back` | `lowerBack` | back | 27 |
| `forearms` | `forearms` | arms | 25 |
| `glutes` | `glutes` | legs | 22 |
| `traps` | `traps` | back | 15 |
| `adductors` | `adductors` | legs | 13 |
| `abductors` | `abductors` | legs | 8 |

### 5.2 Collassi da disambiguare (3 etichette → 8 muscoli)

| free-exercise-db | si spacca in | # come primario |
| --- | --- | --- |
| `shoulders` | `deltoidFront`, `deltoidLateral`, `deltoidRear` | 129 |
| `abdominals` | `rectusAbdominis`, `obliques`, `transverse` | 93 |
| `chest` | `chestUpper`, `chestMid`, `chestLower` | 84 |

**306 esercizi su 876 (35%)** cadono su un'etichetta ambigua. Ho misurato quanto recupera un'euristica sul nome (`incline`→`chestUpper`, `decline`/`dip`→`chestLower`, `lateral`/`upright`→`deltoidLateral`, `rear`/`reverse fly`/`face pull`→`deltoidRear`, `front`/`press`/`overhead`→`deltoidFront`, `oblique`/`twist`/`side bend`/`russian`→`obliques`, `plank`/`vacuum`/`hollow`→`transverse`, resto→`chestMid`/`rectusAbdominis`):

```
rectusAbdominis  73     deltoidLateral  14
chestMid         59     deltoidRear     11
NON RISOLTI      57     chestLower      10
deltoidFront     47     transverse       2
obliques         18     chestUpper      15
```

**249 su 306 risolti automaticamente (81%); restano 57 casi**, tutti spalle, tutti effettivamente ambigui anche per un umano al primo sguardo: *Alternating Deltoid Raise*, *Arm Circles*, *Band Pull Apart*, *Clean and Jerk*, *Dumbbell Scaption*, *External Rotation*… Sono pochi abbastanza da **rivedere a mano una volta sola** e congelare in una tabella di override versionata. Sui 678 dopo il filtro §2 il numero è ancora più basso.

### 5.3 Perdite secche

- **`upperBack`**: non c'è alcuna etichetta sorgente che ci mappi (esistono solo `middle back` e `lower back`). Nessun esercizio importato lo popolerà. È un muscolo che nel dataset semplicemente non esiste.
- **`neck`** (8 esercizi: *Isometric Neck Exercise*, *Neck-SMR*, *Side Neck Stretch*, …): non ha casa nei nostri 23 e sono tutti stretching/isometrie. **Da scartare** — e il filtro `category` di §2 li elimina già quasi tutti.

### 5.4 Come implementarlo

Il `muscle_taxonomy` va portato in Django come tabella/fixture, non come `choices` hardcoded, così le query analitiche possono fare `JOIN` e aggregare per gruppo dentro il DB (coerente con la direttiva ORM avanzato della mappa #11). Il management command di import allora è:

1. Scarica/legge `dist/exercises.json` (committabile nel repo: sono metadati, ~2 MB con le instructions, molto meno senza).
2. Filtra per `category`.
3. Mappa 1:1 i 13 muscoli diretti tramite un dizionario esplicito.
4. Applica l'euristica sul nome per `chest`/`shoulders`/`abdominals`.
5. Consulta una **tabella di override** `{slug: muscolo}` versionata per i 57 casi.
6. **Come Overload, non far sparire l'ignoto**: se un muscolo non si mappa, salva il valore grezzo e lascia il collegamento nullo, poi segnalalo nel report finale del comando. È lo stesso ragionamento del `LEFT JOIN` commentato in `0008`.
7. Mappa `equipment` sui valori che ha senso mostrare in italiano; `null` diventa "non specificato", non un errore.

`secondaryMuscles` si mappa con lo stesso dizionario e diventa una `ManyToManyField` — utile per il motore analitico (volume indiretto per gruppo) e praticamente gratis da importare.

## 6. Candidato 3 — wger (fonte secondaria per italiano e immagini)

Fonti: API pubblica `https://wger.de/api/v2/` interrogata il 2026-09-07, [repo](https://github.com/wger-project/wger), docs `wger.readthedocs.io/en/latest/api/api.html`.

| voce | valore verificato |
| --- | --- |
| esiste ancora | sì, molto vivo: 6868 stelle, ultimo push 2026-09-06 |
| licenza del **software** | AGPL-3.0 |
| licenza dei **dati** | **per-oggetto**, esposta nel JSON. Su un campione di 200: CC-BY-SA 3.0 (118), CC-BY-SA 4.0 (64), CC0 (18). Ogni voce ha un `license_author` |
| dimensione | **871 esercizi** (`/api/v2/exercise/?limit=1` → `count: 871`) |
| formato | REST JSON. `/exerciseinfo/` restituisce tutto denormalizzato in un colpo. Lettura **senza autenticazione**, endpoint non throttlati (i rate limit documentati riguardano auth/ingredienti) |
| offline | il progetto ha un management command Django `sync-exercises` (`wger/exercises/management/commands/sync-exercises.py`) che sincronizza da un'istanza wger |
| italiano | esiste (`language` id 13) ma copre **solo 142 esercizi su 871**. Per confronto: en 871, es 646, de 628, fr 582 |
| immagini | presenti su una minoranza (82 su 200 nel campione), ma **con licenza esplicita e autore**: queste si possono ridistribuire dando attribuzione |

**Perché non è la fonte principale.** La sua tassonomia muscolare ha **15 voci anatomiche**:

`Anterior deltoid`, `Biceps brachii`, `Biceps femoris`, `Brachialis`, `Gastrocnemius`, `Gluteus maximus`, `Latissimus dorsi`, `Obliquus externus abdominis`, `Pectoralis major`, `Quadriceps femoris`, `Rectus abdominis`, `Serratus anterior`, `Soleus`, `Trapezius`, `Triceps brachii`.

Confrontata con i nostri 23 mancano del tutto: **avambracci, adduttori, abduttori, lombari, upper back, middle back, deltoide laterale, deltoide posteriore** — e i tre capi del petto sono un solo `Pectoralis major`. Cioè: `wger` non distingue nemmeno le alzate laterali dalle military press, e non ha alcun muscolo per stacchi/lombari. Anche `equipment` è ridotto a 12 valori e `category` a 8 gruppi generici (Abs, Arms, Back, Calves, Cardio, Chest, Legs, Shoulders). **Un motore analitico costruito su questa tassonomia sarebbe più povero della app che dovrebbe emulare.**

**Come vale la pena usarlo** (opzionale, non bloccante):

- Come **fonte di nomi italiani** per i 142 esercizi tradotti, incrociati per nome inglese con free-exercise-db.
- Come **fonte di immagini legalmente pulite** dove esistono, con attribuzione (`license_author` + link alla licenza) — l'unico modo onesto per avere foto nel repo pubblico.
- Nota copyleft: CC-BY-SA è **share-alike sui dati**, non sul codice Django che li legge. Il file dati importato da wger va quindi accompagnato da attribuzione e nota di licenza; il codice del progetto resta libero di avere la licenza che vuole.

## 7. Candidato 4 — ExerciseDB ❌ non è un dataset

Fonte: [`ExerciseDB/exercisedb-api`](https://github.com/ExerciseDB/exercisedb-api), 623 stelle, ultimo push 2025-11-25, licenza AGPL-3.0.

**Il repository contiene esattamente due file: `LICENSE` e `README.md`.** Nessun codice, nessun dato. Il README pubblicizza 11.000+ esercizi, 20.000 immagini e 5.000 GIF, ma il tutto è servito da un'**API ospitata a pagamento** (RapidAPI / `exercisedb.dev`), con CDN proprietario. L'AGPL sul repo copre un repo vuoto: non concede alcun diritto sui dati.

Non è ridistribuibile in un repo pubblico e introdurrebbe una dipendenza di rete a runtime. **Scartato.**

## 8. Ripiego, se un giorno servisse

Il ticket chiedeva di indicare il ripiego. Non serve: il candidato principale funziona. Ma per completezza, il ripiego naturale sarebbe la libreria stock di Overload — che però **non esiste ancora**: il piano `2026-07-17-stock-exercise-catalog.md` non è mai stato eseguito e i suoi artefatti (`exercise_catalog.json`, la tabella di traduzioni italiane) non sono sul disco. E soprattutto: **quel piano genera il catalogo esattamente da `free-exercise-db`** (`const SRC = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"`). Ripiego e raccomandazione sono la stessa fonte. Tanto vale andare alla sorgente.

Un effetto collaterale utile: la traduzione italiana dei nomi è lavoro che serve a **entrambi** i progetti. Se `Progressive` produce la tabella `{slug: nome italiano}`, quella tabella è riusabile in Overload così com'è.

---

## Raccomandazione operativa

1. **Fonte**: `yuhonas/free-exercise-db`, file `dist/exercises.json`, licenza Unlicense.
2. **Cosa importare**: `id`, `name`, `primaryMuscles`, `secondaryMuscles`, `equipment`, `mechanic`, `level`, `force`, `category`. **Escludere `images` e `instructions`** (provenienza scraped, §4).
3. **Cosa committare**: il JSON filtrato nel repo (dati fattuali, ~678 voci), più una tabella di override dei muscoli e una tabella di traduzioni italiane, entrambe versionate e curate a mano una volta sola.
4. **Filtro**: `category ∈ {strength, powerlifting, olympic weightlifting, strongman}` → 678 esercizi, di cui solo 6 senza attrezzatura.
5. **Mappatura**: dizionario esplicito per 13 muscoli, euristica sul nome per `chest`/`shoulders`/`abdominals` (81% dei 306 ambigui), override manuale per i ~57 residui, `upperBack` resta vuoto, `neck` scartato. Muscolo non mappato → collegamento nullo + riga nel report del comando, mai riga scartata in silenzio.
6. **Opzionale**: incrociare con l'API wger per nomi italiani (142) e immagini con licenza esplicita, citando `license_author`.

---

## Fonti

Tutte consultate il 2026-09-07.

- `~/Developer/GymLog/SupabaseMigrations/0008_reporting_schema.sql` — `reporting.muscle_taxonomy`, 23 muscoli / 6 gruppi
- `~/Developer/GymLog/docs/superpowers/plans/2026-07-17-stock-exercise-catalog.md` — piano non eseguito del catalogo stock di Overload
- https://github.com/yuhonas/free-exercise-db — repo, `LICENSE.md`, `README.md`, `schema.json`
- https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json — dataset scaricato e analizzato
- https://github.com/yuhonas/free-exercise-db/issues/2 — il mantenitore sulla provenienza ignota delle immagini
- https://github.com/yuhonas/free-exercise-db/issues/13 — immagini riconosciute come ExRx.net
- https://github.com/wrkout/exercises.json — repo e `LICENSE.md`
- https://raw.githubusercontent.com/wrkout/exercises.json/master/CONTRIBUTING.md — «scrapped off the internet … advise against using them»
- https://github.com/wrkout/exercises.json/issues/305 — analisi della provenienza (bodybuilding.com) e dei suoi termini d'uso
- https://wger.de/api/v2/{exercise,exerciseinfo,muscle,equipment,exercisecategory,language,exercise-translation}/ — interrogati direttamente
- https://github.com/wger-project/wger — licenza AGPL-3.0, `wger/exercises/management/commands/sync-exercises.py`
- https://wger.readthedocs.io/en/latest/api/api.html — accesso pubblico senza autenticazione, rate limit
- https://github.com/ExerciseDB/exercisedb-api — repo con soli `LICENSE` e `README.md`
