// PROTOTIPO #37 — genera UN SOLO SVG del corpo umano in cui ogni path porta il
// gruppo e il muscolo a cui appartiene, come classi CSS. Il colore non e' qui:
// lo decide la view Django, scrivendo un <style> che colora per classe. Cosi'
// l'SVG resta un file statico da `{% include %}`, e la heatmap costa una
// manciata di righe di CSS generate.
//
// Deriva dall'anatomia di Overload (`Scripts/build_muscle_maps.mjs`): sei SVG
// dello stesso corpo (fronte + retro, 154 path, viewBox 0 0 1448 1448) in cui i
// path del gruppo evidenziato sono volt. Da li' il gruppo si legge gratis; i 23
// muscoli richiedono gli ancoraggi con point-in-polygon, ripresi tali e quali
// perche' sono gia' misurati e verificati.
//
// Uso: node build_body_svg.mjs [percorso-di-GymLog]

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const GYMLOG = process.argv[2] || `${process.env.HOME}/Developer/GymLog`;
const ASSETS = join(GYMLOG, "GymLog/Resources/Assets.xcassets");
// L'SVG esce direttamente fra i template: e' un partial da `{% include %}`,
// statico, e non ha nessun bisogno di passare per la view.
const OUT = join(
  dirname(fileURLToPath(import.meta.url)),
  "../t19-pagine/templates/prototype/_corpo.svg",
);

const VOLT = "#C9FF3D";
const GROUPS = ["chest", "back", "shoulders", "arms", "legs", "core"];
const CANVAS = 1448;
const CURVE_STEPS = 12;

// ---------- parse (identico a Overload) ----------
function paths(svg) {
  return [...svg.matchAll(/<path\s+d="([^"]+)"[^>]*fill="(#[0-9A-Fa-f]{6})"[^>]*\/>/g)]
    .map((m) => ({ d: m[1], fill: m[2] }));
}
const readGroup = (g) =>
  paths(readFileSync(`${ASSETS}/muscle-${g}.imageset/muscle-${g}.svg`, "utf8"));

const ARGC = { m: 2, l: 2, h: 1, v: 1, c: 6, s: 4, q: 4, t: 2, a: 7, z: 0 };

function flatten(d) {
  const subpaths = [];
  let cur = [];
  let i = 0, cmd = null, x = 0, y = 0, sx = 0, sy = 0, cpx = 0, cpy = 0, prev = "";
  const skip = () => { while (i < d.length && /[\s,]/.test(d[i])) i++; };
  const readFlag = () => { skip(); return Number(d[i++]); };
  const readNum = () => {
    skip();
    const m = /^[+-]?(?:\d*\.\d+|\d+\.?)(?:[eE][+-]?\d+)?/.exec(d.slice(i));
    if (!m) { i++; return NaN; }
    i += m[0].length;
    return Number(m[0]);
  };
  const cubic = (x1, y1, x2, y2, x3, y3) => {
    const x0 = x, y0 = y;
    for (let s = 1; s <= CURVE_STEPS; s++) {
      const t = s / CURVE_STEPS, u = 1 - t;
      cur.push([
        u * u * u * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x3,
        u * u * u * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y3,
      ]);
    }
    cpx = x2; cpy = y2; x = x3; y = y3;
  };
  const quad = (x1, y1, x2, y2) => {
    const x0 = x, y0 = y;
    for (let s = 1; s <= CURVE_STEPS; s++) {
      const t = s / CURVE_STEPS, u = 1 - t;
      cur.push([
        u * u * x0 + 2 * u * t * x1 + t * t * x2,
        u * u * y0 + 2 * u * t * y1 + t * t * y2,
      ]);
    }
    cpx = x1; cpy = y1; x = x2; y = y2;
  };
  const endSub = () => { if (cur.length > 1) subpaths.push(cur); cur = []; };

  while (i < d.length) {
    skip();
    if (i >= d.length) break;
    if (/[a-zA-Z]/.test(d[i])) { cmd = d[i]; i++; }
    else if (cmd == null) { i++; continue; }
    const lower = cmd.toLowerCase();
    const rel = cmd === lower && lower !== "z";
    if (ARGC[lower] === undefined) { i++; continue; }
    const a = [];
    if (lower === "a") {
      a.push(readNum(), readNum(), readNum(), readFlag(), readFlag(), readNum(), readNum());
    } else {
      for (let k = 0; k < ARGC[lower]; k++) a.push(readNum());
    }
    const ax = (v) => (rel ? x + v : v), ay = (v) => (rel ? y + v : v);
    switch (lower) {
      case "m":
        endSub();
        x = ax(a[0]); y = ay(a[1]); sx = x; sy = y; cur = [[x, y]];
        cmd = rel ? "l" : "L";
        break;
      case "l": x = ax(a[0]); y = ay(a[1]); cur.push([x, y]); break;
      case "h": x = ax(a[0]); cur.push([x, y]); break;
      case "v": y = ay(a[0]); cur.push([x, y]); break;
      case "c": cubic(ax(a[0]), ay(a[1]), ax(a[2]), ay(a[3]), ax(a[4]), ay(a[5])); break;
      case "s": {
        const sm = /[cs]/.test(prev);
        cubic(sm ? 2 * x - cpx : x, sm ? 2 * y - cpy : y,
              ax(a[0]), ay(a[1]), ax(a[2]), ay(a[3]));
        break;
      }
      case "q": quad(ax(a[0]), ay(a[1]), ax(a[2]), ay(a[3])); break;
      case "t": {
        const sm = /[qt]/.test(prev);
        quad(sm ? 2 * x - cpx : x, sm ? 2 * y - cpy : y, ax(a[0]), ay(a[1]));
        break;
      }
      case "a": x = ax(a[5]); y = ay(a[6]); cur.push([x, y]); break;
      case "z": x = sx; y = sy; cur.push([x, y]); endSub(); cmd = null; break;
    }
    prev = lower;
  }
  endSub();
  return subpaths;
}

function bbox(subpaths) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const poly of subpaths) for (const [px, py] of poly) {
    if (px < minX) minX = px; if (px > maxX) maxX = px;
    if (py < minY) minY = py; if (py > maxY) maxY = py;
  }
  return { minX, minY, maxX, maxY, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 };
}

function contains(subpaths, px, py) {
  let inside = false;
  for (const poly of subpaths) {
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > py) !== (yj > py)
          && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
    }
  }
  return inside;
}

// ---------- tabella dei path ----------
const table = new Map();
const order = [];
for (const g of GROUPS) {
  for (const p of readGroup(g)) {
    let entry = table.get(p.d);
    if (!entry) {
      const poly = flatten(p.d);
      entry = { d: p.d, group: null, muscle: null, poly, box: bbox(poly) };
      table.set(p.d, entry);
      order.push(entry);
    }
    if (p.fill.toUpperCase() === VOLT) entry.group = g;
  }
}
const ALL = order;
const inGroup = (g) => ALL.filter((p) => p.group === g);

const FRONT_MAX_X = (() => {
  const iv = ALL.map((p) => [p.box.minX, p.box.maxX]).sort((a, b) => a[0] - b[0]);
  let end = iv[0][1], best = 0, at = 0;
  for (const [lo, hi] of iv) {
    if (lo > end && lo - end > best) { best = lo - end; at = (end + lo) / 2; }
    if (hi > end) end = hi;
  }
  return at;
})();
const isFront = (p) => p.box.cx < FRONT_MAX_X;
const spanMid = (ps) =>
  (Math.min(...ps.map((p) => p.box.minX)) + Math.max(...ps.map((p) => p.box.maxX))) / 2;
const FRONT_MID = spanMid(ALL.filter(isFront));
const BACK_MID = spanMid(ALL.filter((p) => !isFront(p)));
const midlineAt = (x) => (x < FRONT_MAX_X ? FRONT_MID : BACK_MID);

// ---------- ancoraggi (ripresi da Overload, gia' verificati) ----------
let failures = 0;
function at(group, x, y, who) {
  const hits = inGroup(group).filter((p) => contains(p.poly, x, y));
  if (hits.length !== 1) {
    console.error(`  !! ${who}: ancora (${x},${y}) in "${group}" ha colpito ${hits.length} path`);
    failures++;
  }
  return hits;
}
const pair = (group, x, y, who) =>
  [...at(group, x, y, who), ...at(group, 2 * midlineAt(x) - x, y, who)];
const anchors = (group, pts, who) => pts.flatMap(([x, y]) => pair(group, x, y, who));

const chest = inGroup("chest");
const chestSpan = {
  min: Math.min(...chest.map((p) => p.box.minY)),
  max: Math.max(...chest.map((p) => p.box.maxY)),
};
const chestBand = (i) => {
  const h = (chestSpan.max - chestSpan.min) / 3;
  return [0, chestSpan.min + i * h, CANVAS, h];
};

const deltoidFront = anchors("shoulders", [[496, 347]], "deltoidFront");
const deltoidRear = anchors("shoulders", [[1219, 353]], "deltoidRear");
const LATERAL_FRACTION = 0.45;
const deltoidLateral = [...deltoidFront, ...deltoidRear].map((p) => {
  const w = (p.box.maxX - p.box.minX) * LATERAL_FRACTION;
  const outerIsLeft = p.box.cx < midlineAt(p.box.cx);
  return {
    path: p,
    rect: [outerIsLeft ? p.box.minX : p.box.maxX - w, p.box.minY, w, p.box.maxY - p.box.minY],
  };
});

// I muscoli che coincidono con path interi: la classe si scrive sul path stesso.
const SOLID = {
  traps: anchors("back", [[424, 295], [1126, 384]], "traps"),
  upperBack: anchors("back", [[1172, 360]], "upperBack"),
  middleBack: anchors("back", [[978, 396]], "middleBack"),
  lats: anchors("back", [[1151, 493]], "lats"),
  lowerBack: anchors("back", [[1118, 563], [1165, 597]], "lowerBack"),
  deltoidFront,
  deltoidRear,
  biceps: anchors("arms", [[202, 448], [226, 450]], "biceps"),
  triceps: anchors("arms", [[1231, 416], [1256, 479], [1228, 481], [1264, 545]], "triceps"),
  forearms: anchors("arms", [
    [575, 591], [556, 604], [547, 613],
    [1294, 611], [1312, 644], [1271, 619],
  ], "forearms"),
  quads: anchors("legs", [[275, 803], [411, 894]], "quads"),
  hamstrings: anchors("legs", [[999, 878], [1033, 890], [1040, 938]], "hamstrings"),
  glutes: anchors("legs", [[1028, 704]], "glutes"),
  calves: anchors("legs", [
    [278, 1088], [308, 1106], [270, 1176],
    [987, 1062], [1026, 1062], [993, 1224], [1019, 1226],
  ], "calves"),
  adductors: anchors("legs", [[313, 714], [385, 807], [1056, 822]], "adductors"),
  abductors: anchors("legs", [[260, 888], [1014, 641], [972, 829]], "abductors"),
  rectusAbdominis: anchors("core", [[331, 462], [393, 508], [393, 557], [336, 649]], "rectusAbdominis"),
  obliques: anchors("core", [
    [275, 431], [271, 450], [289, 469], [263, 474],
    [286, 495], [285, 521], [285, 550], [289, 609],
  ], "obliques"),
};
for (const [muscle, ps] of Object.entries(SOLID)) for (const p of ps) p.muscle = muscle;

// I muscoli senza path proprio: sovrapposizioni ritagliate, emesse dopo il corpo.
// Il trasverso e' profondo e non ha superficie: tinge tutta la parete addominale.
const OVERLAY = [
  ...chest.map((p) => ({ muscle: "chestUpper", path: p, rect: chestBand(0) })),
  ...chest.map((p) => ({ muscle: "chestMid", path: p, rect: chestBand(1) })),
  ...chest.map((p) => ({ muscle: "chestLower", path: p, rect: chestBand(2) })),
  ...deltoidLateral.map((c) => ({ muscle: "deltoidLateral", path: c.path, rect: c.rect })),
];
const DEEP = inGroup("core").filter(isFront).map((p) => ({ muscle: "transverse", path: p }));

// ---------- emissione ----------
// Ogni path porta le sue classi: `g-<gruppo>` e `m-<muscolo>`. Chi non appartiene
// a nessun gruppo (contorni, testa, mani) resta senza classe e prende il grigio.
const esc = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
const body = [];
for (const p of ALL) {
  const cls = [p.group ? `g-${p.group}` : null, p.muscle ? `m-${p.muscle}` : null]
    .filter(Boolean).join(" ");
  body.push(`<path d="${esc(p.d)}"${cls ? ` class="${cls}"` : ""}/>`);
}
const defs = [];
OVERLAY.forEach((o, k) => {
  const id = `c${k}`;
  const [x, y, w, h] = o.rect;
  defs.push(`<clipPath id="${id}"><rect x="${x.toFixed(1)}" y="${y.toFixed(1)}"`
    + ` width="${w.toFixed(1)}" height="${h.toFixed(1)}"/></clipPath>`);
  body.push(`<path d="${esc(o.path.d)}" class="m-${o.muscle} overlay" clip-path="url(#${id})"/>`);
});
for (const o of DEEP) {
  body.push(`<path d="${esc(o.path.d)}" class="m-${o.muscle} overlay deep"/>`);
}

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${CANVAS} ${CANVAS}"`
  + ` class="corpo" role="img">`
  + `<defs>${defs.join("")}</defs>`
  + body.join("")
  + `</svg>`;
writeFileSync(OUT, svg);

// ---------- resoconto ----------
console.log(`anatomia: ${ALL.length} path, split fronte/retro x=${FRONT_MAX_X.toFixed(0)}`);
for (const g of GROUPS) console.log(`  gruppo ${g}: ${inGroup(g).length} path`);
const CATALOGO = [
  "chestUpper", "chestMid", "chestLower", "lats", "traps", "upperBack", "middleBack",
  "lowerBack", "deltoidFront", "deltoidLateral", "deltoidRear", "biceps", "triceps",
  "forearms", "quads", "hamstrings", "glutes", "calves", "adductors", "abductors",
  "rectusAbdominis", "obliques", "transverse",
];
const coperti = new Set([
  ...ALL.filter((p) => p.muscle).map((p) => p.muscle),
  ...OVERLAY.map((o) => o.muscle),
  ...DEEP.map((o) => o.muscle),
]);
const mancanti = CATALOGO.filter((m) => !coperti.has(m));
console.log(`\nmuscoli del catalogo coperti: ${CATALOGO.length - mancanti.length}/23`);
if (mancanti.length) console.error(`  !! non coperti: ${mancanti.join(", ")}`);
console.log(`scritto ${OUT} (${(svg.length / 1024).toFixed(1)} KB)`);
if (failures) { console.error(`${failures} ancora/e non risolte`); process.exit(1); }
if (mancanti.length) process.exit(1);
