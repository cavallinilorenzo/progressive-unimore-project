"""PROTOTIPO #37 / #40 — la figura schematica, disegnata qui.

Emette `_corpo_schema.svg` con lo **stesso contratto** di `_corpo.svg`: due
figure (fronte e retro), ogni regione con `class="g-<gruppo> m-<muscolo>"`. Il
template della heatmap non cambia di una riga: cambia solo quale partial include.

Perche' esiste. L'anatomia di Overload e' materiale di terzi con licenza ignota
(#40) e questo repo e' pubblico. Le librerie open di body-map hanno lo stesso
problema a monte — nessuna documenta da dove venga il disegno — quindi
adottarne una sposta il rischio, non lo toglie. Una figura **disegnata qui** lo
toglie: e' nostra per costruzione.

Non e' un'illustrazione anatomica e non prova a esserlo. E' un diagramma: a
360px in una card di dashboard i 154 path dell'anatomia vera diventano rumore,
mentre venti forme grandi si leggono a colpo d'occhio — che e' l'unica cosa che
questa vista deve fare.

Uso: python3 build_schema_svg.py
"""

from pathlib import Path

OUT = Path(__file__).parent / "../t19-pagine/templates/prototype/_corpo_schema.svg"

W, H = 420, 300
FRONT_CX, BACK_CX = 108, 312

# I 23 codici sono quelli di data/catalog/muscles.csv, non una variante.
#
# Ogni forma viene emessa **due volte**: una nel gruppo `ombra`, una in
# `regioni`. L'ombra e' la stessa geometria con un bordo spesso del colore del
# fondo, quindi ogni forma si ingrossa e le forme vicine si fondono in una sola
# massa scura. E' quella massa a dare al diagramma la silhouette di un corpo:
# senza, braccia e gambe galleggiano staccate e la figura sembra un robot.
# Costa due righe di CSS e nessuna geometria in piu'.
forme: list[tuple[str, str, str]] = []  # (tag, attributi, classi)


def regione(muscolo: str, gruppo: str, corpo: tuple[str, str]) -> None:
    forme.append((corpo[0], corpo[1], f"g-{gruppo} m-{muscolo}"))


def neutro(corpo: tuple[str, str]) -> None:
    """Testa, mani, piedi: non sono muscoli, restano fuori dalla scala."""
    forme.append((corpo[0], corpo[1], "neutro"))


def profondo(muscolo: str, gruppo: str, corpo: tuple[str, str]) -> None:
    """Muscolo senza superficie propria: vela l'area invece di occuparla."""
    forme.append((corpo[0], corpo[1], f"g-{gruppo} m-{muscolo} profondo"))


def ell(cx: float, cy: float, rx: float, ry: float, rot: float = 0.0):
    t = f' transform="rotate({rot} {cx} {cy})"' if rot else ""
    return ("ellipse", f' cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}"{t}')


def box(x: float, y: float, w: float, h: float, r: float = 5.0):
    return ("rect", f' x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"')


def poly(punti: str):
    return ("polygon", f' points="{punti}"')


def figura(cx: float, dietro: bool) -> None:
    neutro(ell(cx, 28, 14, 17))          # testa
    neutro(box(cx - 6, 43, 12, 10, 4))   # collo

    # --- trapezio: da davanti due sliver sulle clavicole, da dietro il diamante ---
    if dietro:
        regione("traps", "back", poly(
            f"{cx-19},54 {cx+19},54 {cx+12},100 {cx},112 {cx-12},100"))
    else:
        for lato in (-1, 1):
            regione("traps", "back", ell(cx + lato * 15, 56, 10, 6, -18 * lato))

    # --- spalle: il capo laterale sta all'esterno, su entrambe le viste ---
    delt = "deltoidRear" if dietro else "deltoidFront"
    for lato in (-1, 1):
        regione(delt, "shoulders", ell(cx + lato * 30, 68, 12, 13))
        regione("deltoidLateral", "shoulders", ell(cx + lato * 39, 70, 7, 12))

    # --- torso ---
    if dietro:
        for lato in (-1, 1):
            regione("upperBack", "back", box(cx + lato * 24 - 8, 60, 16, 21, 5))
            regione("middleBack", "back", box(cx + lato * 24 - 8, 83, 16, 19, 5))
            # Gran dorsale: l'ala dall'ascella alla vita.
            regione("lats", "back", poly(
                f"{cx+lato*32},84 {cx+lato*14},108 {cx+lato*12},138 {cx+lato*31},120"))
        regione("lowerBack", "back", box(cx - 11, 116, 22, 30, 6))
    else:
        # Il trasverso e' profondo: si disegna per primo, cosi' resta sotto.
        profondo("transverse", "core", box(cx - 25, 98, 50, 52, 10))
        # Petto: tre fasce, ognuna divisa nei due pettorali.
        for i, m in enumerate(("chestUpper", "chestMid", "chestLower")):
            for lato in (-1, 1):
                regione(m, "chest", box(cx + lato * 13 - 12, 60 + i * 13, 24, 11, 4))
        regione("rectusAbdominis", "core", box(cx - 11, 100, 22, 44, 6))
        for lato in (-1, 1):
            regione("obliques", "core", box(cx + lato * 19 - 6, 102, 12, 38, 5))

    # --- braccia: accostate al torso, altrimenti la figura si smembra ---
    braccio = "triceps" if dietro else "biceps"
    for lato in (-1, 1):
        regione(braccio, "arms", ell(cx + lato * 41, 99, 9, 20))
        regione("forearms", "arms", ell(cx + lato * 45, 137, 8, 21))
        neutro(ell(cx + lato * 48, 163, 7, 8))  # mano

    # --- bacino e gambe ---
    if dietro:
        for lato in (-1, 1):
            regione("glutes", "legs", ell(cx + lato * 12, 160, 14, 15))
            regione("hamstrings", "legs", ell(cx + lato * 14, 203, 12, 30))
    else:
        for lato in (-1, 1):
            regione("quads", "legs", ell(cx + lato * 14, 198, 13, 32))
        # Adduttori: la fascia interna, fra le due cosce.
        regione("adductors", "legs", box(cx - 6, 172, 12, 44, 6))

    # Abduttori: la banda esterna della coscia, su entrambe le viste.
    for lato in (-1, 1):
        regione("abductors", "legs", box(cx + lato * 27 - 5, 170, 10, 46, 5))

    # Polpacci su entrambe le viste.
    for lato in (-1, 1):
        regione("calves", "legs", ell(cx + lato * 14, 250, 10, 25))
        neutro(ell(cx + lato * 14, 281, 9, 6))  # piede


figura(FRONT_CX, dietro=False)
figura(BACK_CX, dietro=True)

ombra = "".join(f"<{t}{a}/>" for t, a, _ in forme)
regioni = "".join(f'<{t} class="{c}"{a}/>' for t, a, c in forme)

svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"'
    f' class="corpo schema" role="img">'
    f'<g class="ombra">{ombra}</g>'
    f'<g class="regioni">{regioni}</g>'
    "</svg>"
)
OUT.resolve().parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(svg)

# --- verifica: tutti e 23 i muscoli devono comparire, o non si spedisce ---
CATALOGO = [
    "chestUpper", "chestMid", "chestLower", "lats", "traps", "upperBack",
    "middleBack", "lowerBack", "deltoidFront", "deltoidLateral", "deltoidRear",
    "biceps", "triceps", "forearms", "quads", "hamstrings", "glutes", "calves",
    "adductors", "abductors", "rectusAbdominis", "obliques", "transverse",
]
presenti = {c.split()[1][2:] for _, _, c in forme if c.startswith("g-")}
mancanti = [m for m in CATALOGO if m not in presenti]
print(f"forme: {len(forme)} (x2 con l'ombra)")
print(f"muscoli coperti: {len(CATALOGO) - len(mancanti)}/23")
print(f"scritto {OUT.resolve()} ({len(svg) / 1024:.1f} KB)")
if mancanti:
    raise SystemExit(f"!! non coperti: {', '.join(mancanti)}")
