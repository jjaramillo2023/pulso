"use strict";
/* pulso · frontend. Un único canvas (#cv) a pantalla completa: los mismos 1.200 puntos forman el mapa
   del inicio, vuelan a la vista de resultados y votan. Los datos vienen del motor local (/api/...). */

/* ================= utilidades ================= */
const RM = matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = s => document.querySelector(s);
const fmt = n => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
const pct = (x, d = 0) => (x * 100).toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d }) + " %";
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const sleep = ms => new Promise(r => setTimeout(r, RM ? Math.min(ms, 60) : ms));
function rng(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const hex2 = h => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
// orden de marca: coral, navy, naranja, azul; a partir de la quinta opción, tonos suaves de los mismos
const PAL = ["#F0442E", "#1A1F3A", "#FF8A1F", "#3E7CB1", "#F59A8C", "#6B7194", "#FFC285", "#93B7D6"], NSC = "#A9AEC0";
const N = 1200, BEAT = 1.6;
const SPAR = 1.2241, PAR = 0.62;

/* ================= versión publicada (sin servidor) ================= */
// En GitHub Pages no hay motor: las respuestas salen de resultados ya calculados (datos/).
const ESTATICO = !!window.PULSO_ESTATICO;
let INDICE = null;
async function indice() { if (!INDICE) INDICE = await (await fetch("datos/indice.json")).json(); return INDICE; }
const normTxt = t => String(t).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9ñ ]+/g, " ").replace(/\s+/g, " ").trim();
const VACIAS = new Set("que los las del por para con una uno unos unas como mas muy esta este estos estas sus tus mis hay ser son has han tu te se le lo la el en de y a o u al es si no cree crees usted ustedes vas va van".split(" "));
const raices = t => new Set(normTxt(t).split(" ").filter(w => w.length > 2 && !VACIAS.has(w)).map(w => w.slice(0, 5)));
function parecido(a, b) { const A = raices(a), B = raices(b); if (!A.size || !B.size) return 0; let n = 0; A.forEach(w => { if (B.has(w)) n++; }); return n / Math.max(A.size, B.size); }
async function buscarPreparada(q, extra) {
  const idx = await indice(), tipo = extra ? extra.tipo : "pregunta";
  const texto = extra ? extra.mensajes.join(" ") : q;
  const puntuadas = idx.filter(e => e.tipo === tipo).map(e => [parecido(texto, extra ? e.mensajes.join(" ") : e.pregunta), e])
    .concat(tipo === "pregunta" ? [] : idx.filter(e => e.tipo !== tipo).map(e => [parecido(texto, e.mensajes.join(" ")) * .8, e]))
    .sort((a, b) => b[0] - a[0]);
  return { mejor: puntuadas[0] && puntuadas[0][0] >= .5 ? puntuadas[0] : null, sugerencias: puntuadas.slice(0, 4).map(x => x[1]) };
}
async function preguntarEstatico(q, extra) {
  setSteps(0); await sleep(500);
  const { mejor, sugerencias } = await buscarPreparada(q, extra);
  if (!mejor) throw Object.assign(new Error("NO_PREPARADA"), { sugerencias });
  setSteps(1); await sleep(450);
  setSteps(2); for (let k = 10; k <= 100; k += 15) { $("#stProg").textContent = ` · ${k} de 100 perfiles`; await sleep(90); }
  const res = await (await fetch(`datos/consultas/${mejor[1].archivo}`)).json();
  res._entrada = mejor[1]; res._aproximada = mejor[0] < .85 && normTxt(q) !== normTxt(mejor[1].pregunta);
  return res;
}

/* ================= mapa y regiones ================= */
const REG = [
  ["GA", "Galicia", .10, .13], ["AS", "Asturias", .25, .05], ["CB", "Cantabria", .39, .08], ["PV", "País Vasco", .49, .10],
  ["NA", "Navarra", .56, .15], ["RI", "La Rioja", .50, .19], ["AR", "Aragón", .63, .30], ["CT", "Cataluña", .79, .25],
  ["CL", "Castilla y León", .34, .24], ["MD", "Madrid", .41, .43], ["CM", "Castilla-La Mancha", .46, .57], ["EX", "Extremadura", .22, .59],
  ["VC", "C. Valenciana", .645, .56], ["MC", "Murcia", .58, .75], ["AN", "Andalucía", .34, .82], ["IB", "Illes Balears", .88, .53],
  ["CN", "Canarias", .095, .905]
].map(([id, name, x, y]) => ({ id, name, x, y, pts: [] }));
const RI = Object.fromEntries(REG.map((r, i) => [r.id, i]));
SP.forEach(([x, y]) => {
  let best = 0, bd = 1e9;
  if (x > .82 && y > .44 && y < .64) best = RI.IB;
  else REG.forEach((r, i) => { if (r.id === "IB" || r.id === "CN") return; const d = (x - r.x) ** 2 + ((y - r.y) * 1.05) ** 2; if (d < bd) { bd = d; best = i; } });
  REG[best].pts.push([x, y]);
});
const CNBOX = { x: .012, y: .862, w: .19, h: .1 };
{ const R = rng(7); [[.93, .22, .07, .14, 14], [.83, .58, .06, .2, 20], [.6, .68, .07, .14, 22], [.4, .48, .09, .14, 26], [.27, .56, .03, .06, 5], [.12, .32, .03, .1, 7], [.08, .86, .03, .05, 4]]
  .forEach(([cx, cy, rx, ry, n]) => { for (let i = 0; i < n; i++) { const a = R() * 6.283, r = Math.sqrt(R()); REG[RI.CN].pts.push([CNBOX.x + (cx + Math.cos(a) * rx * r) * CNBOX.w, CNBOX.y + (cy + Math.sin(a) * ry * r) * CNBOX.h]); } }); }
const MAPPTS = []; REG.forEach((r, i) => r.pts.forEach(p => MAPPTS.push([p[0], p[1], i])));
const MADRID = [.41, .43];
// silueta humana para la vista por sexo
const FIG = (() => { const R = rng(11), out = [];
  const inside = (x, y) => { const X = (x - .5) * PAR, hy = .1;
    if (X * X + (y - hy) ** 2 < .088 ** 2) return true;
    if (y > .2 && y < .23 && Math.abs(X) < .05) return true;
    if (y >= .22 && y < .6) { const sh = .2 - Math.max(0, y - .3) * .08;
      if (Math.abs(X) < sh && !(y > .32 && Math.abs(X) > .135 && Math.abs(X) < .155)) { if (y < .27) return Math.abs(X) < .2 - (.27 - y) * 1.6; return true; } }
    if (y >= .6 && y <= 1 && Math.abs(X) < .115 && Math.abs(X) > .012) return true;
    return false; };
  while (out.length < 1400) { const x = R(), y = R(); if (inside(x, y)) out.push([x, y]); }
  return out.sort((a, b) => b[1] - a[1]); })();
const AGEB = ["18-29", "30-44", "45-59", "60-74", "75+"];
const ageBin = a => a < 30 ? 0 : a < 45 ? 1 : a < 60 ? 2 : a < 75 ? 3 : 4;
const FN = ["Lucía", "María", "Carmen", "Laura", "Marta", "Ana", "Paula", "Sara", "Elena", "Cristina", "Julia", "Alba", "Nuria", "Pilar", "Rosa", "Irene", "Andrea", "Claudia", "Noelia", "Teresa", "Inés", "Aitana", "Montse", "Dolores", "Ainhoa", "Lorena", "Raquel", "Silvia", "Begoña", "Xiana"];
const MN = ["Javier", "David", "Daniel", "Carlos", "Pablo", "Sergio", "Álvaro", "Jorge", "Manuel", "Antonio", "José", "Raúl", "Iván", "Adrián", "Rubén", "Hugo", "Marc", "Iker", "Miguel", "Francisco", "Óscar", "Alberto", "Diego", "Andrés", "Jordi", "Xabier", "Rafael", "Ignacio", "Luis", "Mario"];

/* ================= partículas ================= */
const P = [];
{ const R = rng(2026), cn = REG[RI.CN].pts, main = SP.slice();
  for (let i = main.length - 1; i > 0; i--) { const j = Math.floor(R() * (i + 1)); [main[i], main[j]] = [main[j], main[i]]; }
  const home = cn.concat(main.slice(0, N - cn.length));
  home.forEach(([hx, hy], i) => P.push({ i, hx, hy, mx: hx, my: hy, x: R() * innerWidth, y: R() * innerHeight, tx: 0, ty: 0, at: 0, d: R(),
    k: .07 + R() * .07, sz: .75 + R() * .5, hue: R() < .1 ? 1 : R() < .04 ? 2 : 0, ox: 0, oy: 0, flash: 0, pop: 0, col: [26, 31, 58, 0],
    ca: R() * 6.283, cr: Math.sqrt(R()), cw: (.15 + R() * .35) * (R() < .5 ? 1 : -1), u: R(), per: null, ans: -1, voted: false, active: true })); }

/* ================= estado ================= */
let MODE = "home";          // home | app
let VIEW = "hemi";          // vista elegida en el control segmentado
let DIM = "Ideología";      // dimensión de la vista «Grupos»
let LAYOUT = "map";         // disposición actual de los puntos: map | hemi | sex | age | cloud
let SORTED = false, labelA = 0, heatA = 0, hover = null, busy = false, rings = [], beats = [];
let RES = null, D = null, LIVE = null;  // resultado del motor, estadísticas mostradas, recuento en directo
const F = { reg: "all", sex: "all", aMin: 18, aMax: 90 };
let mouse = { x: -1e4, y: -1e4 };

/* ================= canvas ================= */
const cv = $("#cv"), cx = cv.getContext("2d");
let VW = 0, VH = 0, DPR = 1, SX = 0, SY = 0, W = 0, H = 0;
function resize() { DPR = Math.min(2, devicePixelRatio || 1); VW = innerWidth; VH = innerHeight; cv.width = VW * DPR; cv.height = VH * DPR; cx.setTransform(DPR, 0, 0, DPR, 0, 0); stageRect(); if (MODE === "app") layout(LAYOUT, SORTED, true); setViewBtn(VIEW); }
function stageRect() { const r = $("#cw").getBoundingClientRect(); const dy = r.top - SY; SX = r.left; SY = r.top; W = r.width; H = r.height; return dy; }
addEventListener("resize", resize);
function homeBox() {
  const heroB = $(".hero").getBoundingClientRect().bottom + 18, askT = $("#ask").getBoundingClientRect().top - 22;
  const h = Math.max(120, Math.min(askT - heroB, VW * .86 / SPAR)), w = h * SPAR;
  return { x: (VW - w) / 2, y: heroB + (askT - heroB - h) / 2, w, h };
}
const PADT = () => (W < 600 ? 92 : 104);
function mapBox() { const pt = PADT(), pad = 26, h = Math.min(H - pt - pad, (W - 2 * pad) / SPAR), w = h * SPAR; return { x: (W - w) / 2, y: pt + (H - pt - pad - h) / 2, w, h }; }
function dotR() { return MODE === "home" ? clamp(homeBox().w / 330, 1.4, 3.2) : clamp(Math.sqrt(W * H / N) * .17, 1.3, 3.4); }

/* ================= colores y estadísticas ================= */
const isNS = o => /ns\/?nc|no sabe/i.test(o);
function optColor(i) { if (!RES) return NSC; const o = RES.opciones[i]; if (isNS(o)) return NSC; let k = 0; for (let j = 0; j < i; j++) if (!isNS(RES.opciones[j])) k++; return PAL[k % PAL.length]; }
function filtered() { return F.reg !== "all" || F.sex !== "all" || F.aMin > 18 || F.aMax < 90; }
function applyFilter() { P.forEach(p => p.active = !p.per || ((F.reg === "all" || p.per.ccaa === F.reg) && (F.sex === "all" || p.per.sexo === F.sex) && p.per.edad >= F.aMin && (F.aMax >= 90 || p.per.edad <= F.aMax))); }
function liveStats() { // recuento de votos visibles (escrutinio en directo)
  const k = RES.opciones.length, c = new Array(k).fill(0); let n = 0;
  P.forEach(p => { if (p.per && p.active && p.voted) { c[p.ans]++; n++; } });
  return { n, share: c.map(v => n ? v / n : 0) };
}
function displayStats() { // cifras oficiales: agregados ponderados del motor (25.000 personas) o, con filtros, media sobre la muestra
  const k = RES.opciones.length, A = RES.agregados, z = () => new Array(k).fill(0), d = { k, reg: {}, sex: {}, age: [] };
  if (!filtered()) {
    d.share = A.total.map(v => v / 100); d.n = RES.n_poblacion;
    for (const [id, v] of Object.entries(A.ccaa)) d.reg[id] = v.map(x => x / 100);
    for (const s of ["F", "M"]) if (A.sexo[s]) d.sex[s] = A.sexo[s].map(x => x / 100);
    d.age = AGEB.map(b => A.edad[b] ? A.edad[b].map(x => x / 100) : null);
  } else {
    const acc = (list) => { if (!list.length) return null; const s = z(); list.forEach(p => p.per.p.forEach((v, j) => s[j] += v)); return s.map(v => v / list.length); };
    const act = P.filter(p => p.per && p.active);
    d.share = acc(act) || z(); d.n = act.length;
    REG.forEach(r => { const g = act.filter(p => p.per.ccaa === r.id); if (g.length) d.reg[r.id] = acc(g); });
    ["F", "M"].forEach(s => { const g = act.filter(p => p.per.sexo === s); if (g.length) d.sex[s] = acc(g); });
    d.age = AGEB.map((_, b) => acc(act.filter(p => ageBin(p.per.edad) === b)));
  }
  // vista «Grupos»: agregados del motor o, con filtros (o en consultas antiguas), media sobre la muestra
  d.grp = {};
  gruposOrden().forEach(v => {
    if (!filtered() && A.grupos && A.grupos[DIM] && A.grupos[DIM][v]) d.grp[v] = A.grupos[DIM][v].map(x => x / 100);
    else { const g = P.filter(p => p.per && p.active && p.per.g && p.per.g[DIM] === v); if (g.length) { const s = new Array(k).fill(0); g.forEach(p => p.per.p.forEach((x, j) => s[j] += x)); d.grp[v] = s.map(x => x / g.length); } }
  });
  d.lead = d.share.indexOf(Math.max(...d.share));
  return d;
}
/* asigna una respuesta a cada punto según su probabilidad, respetando el reparto del motor en cada franja de edad
   (así las columnas de la vista por edad coinciden con sus porcentajes y el total queda casi exacto) */
function assignAnswers() {
  const R = rng(4242);
  P.forEach(p => p.ans = -1);
  AGEB.forEach((ab, b) => {
    const g = P.filter(p => ageBin(p.per.edad) === b), shares = (RES.agregados.edad[ab] || RES.agregados.total).map(v => v / 100);
    const raw = shares.map(v => v * g.length), cap = raw.map(Math.floor);
    raw.map((v, j) => [v - Math.floor(v), j]).sort((x, y) => y[0] - x[0]).slice(0, g.length - cap.reduce((x, y) => x + y, 0)).forEach(([, j]) => cap[j]++);
    const cand = [];
    g.forEach(p => p.per.p.forEach((v, j) => cand.push([Math.log(Math.max(v, 1e-6)) - Math.log(-Math.log(R() || .5)), p, j])));
    cand.sort((x, y) => y[0] - x[0]);
    for (const [, p, j] of cand) if (p.ans < 0 && cap[j] > 0) { p.ans = j; cap[j]--; }
  });
  P.forEach(p => { if (p.ans < 0) p.ans = p.per.p.indexOf(Math.max(...p.per.p)); });
}

/* ================= disposiciones ================= */
const ordered = list => list.slice().sort((a, b) => (a.ans - b.ans) || (a.u - b.u));
const shuffled = list => list.slice().sort((a, b) => a.u * 7 % 1 - b.u * 7 % 1);
function layout(view, sorted, instant = false) {
  LAYOUT = view; SORTED = sorted;
  const now = performance.now() / 1000, stag = instant ? 0 : .45;
  const set = (p, x, y) => { p.tx = SX + x; p.ty = SY + y; p.at = now + (instant ? 0 : Math.random() * stag); if (instant) { p.x = p.tx; p.y = p.ty; } };
  if (view === "cloud") { P.forEach(p => p.at = now + Math.random() * .25); return; }
  if (view === "map") { const B = mapBox(); P.forEach(p => set(p, B.x + p.mx * B.w, B.y + p.my * B.h)); }
  if (view === "hemi") {
    const pt = PADT(), cxh = W / 2, R1 = Math.max(60, Math.min(W / 2 - 30, H - pt - 50)), cyh = pt + R1 + 6, R0 = R1 * .36;
    const rows = Math.max(8, Math.round(Math.sqrt(N) * .46)), rs = [];
    for (let i = 0; i < rows; i++) rs.push(R0 + (R1 - R0) * i / (rows - 1));
    const sum = rs.reduce((a, b) => a + b, 0); let seats = [], left = N;
    rs.forEach((r, i) => { const n = i === rows - 1 ? left : Math.round(N * r / sum); left -= n; for (let j = 0; j < n; j++) { const a = Math.PI - Math.PI * (j + .5) / n; seats.push({ a, x: cxh + Math.cos(a) * r, y: cyh - Math.sin(a) * r }); } });
    seats.sort((a, b) => b.a - a.a);
    (sorted ? ordered(P) : shuffled(P)).forEach((p, i) => { const s = seats[Math.min(i, seats.length - 1)]; set(p, s.x, s.y); });
    layout.hemi = { cx: cxh, cy: cyh, R0, R1 };
  }
  if (view === "sex") {
    const pt = PADT(), nar = W < 600, fh = Math.max(80, Math.min(H - pt - 70, (W * (nar ? .25 : .34)) / PAR)), fw = fh * PAR, gap = nar ? W * .22 : Math.min(W * .16, 170);
    const xs = { F: W / 2 - gap / 2 - fw, M: W / 2 + gap / 2 }, fy = pt;
    layout.sex = { xs, fy, fw, fh };
    ["F", "M"].forEach(sx => { const g = P.filter(p => p.per ? p.per.sexo === sx : (p.i % 2 ? "M" : "F") === sx), L = sorted ? ordered(g) : shuffled(g), n = L.length;
      L.forEach((p, i) => { const q = FIG[Math.floor(i * FIG.length / n)]; set(p, xs[sx] + q[0] * fw, fy + q[1] * fh); }); });
  }
  if (view === "grp") layoutGrupos(sorted, set);
  if (view === "age") {
    const bajo = H < 460, pt = bajo ? 34 : PADT() + 28, pad = W < 600 ? 14 : 40, cw = (W - 2 * pad) / 5, cols = W < 600 ? 7 : 10;
    const groups = AGEB.map((_, b) => P.filter(p => (p.per ? ageBin(p.per.edad) : p.i % 5) === b)), maxRows = Math.max(...groups.map(g => Math.ceil(g.length / cols)));
    const d = Math.min(cw * .78 / cols, (H - pt - 100) / maxRows), base = H - 48, alto = maxRows * d;
    layout.age = { pad, cw, d, base, cols, groups, alto, bajo };
    // todas las columnas miden lo mismo (100 %): cada franja de color ocupa lo que pesa esa respuesta
    groups.forEach((g, b) => { const L = sorted ? ordered(g) : shuffled(g), cxa = pad + (b + .5) * cw, filas = Math.max(1, Math.ceil(g.length / cols)), dy = alto / filas;
      L.forEach((p, i) => { const row = Math.floor(i / cols), col = i % cols; set(p, cxa + (col - (cols - 1) / 2) * d, base - d / 2 - row * dy); }); });
  }
}
function gruposOrden() {
  if (!RES) return [];
  const presentes = new Set(P.filter(p => p.per && p.per.g && p.per.g[DIM]).map(p => p.per.g[DIM]));
  const orden = (RES.agregados.grupos_orden && RES.agregados.grupos_orden[DIM]) || [...presentes];
  return orden.filter(v => presentes.has(v));
}
function layoutGrupos(sorted, set) {
  const pt = PADT() + 30, sm = W < 600, labelW = sm ? 96 : 160, left = (sm ? 10 : 28) + labelW, right = sm ? 46 : 74, ancho = W - left - right;
  const vals = gruposOrden(), R = Math.max(1, vals.length), rowH = Math.min((H - pt - 20) / R, 64), K = Math.max(2, Math.floor(rowH * .62 / 6.5));
  layout.grp = { left, ancho, rowH, pt, vals, labelW };
  P.forEach(p => { const v = p.per && p.per.g ? p.per.g[DIM] : null, r = vals.indexOf(v); p.enGrupo = r >= 0; });
  vals.forEach((v, r) => { const g = P.filter(p => p.enGrupo && p.per.g[DIM] === v), L = sorted ? ordered(g) : shuffled(g), cols = Math.max(1, Math.ceil(L.length / K)), dx = ancho / cols, y0 = pt + r * rowH + (rowH - (K - 1) * 6.5) / 2 - 6;
    L.forEach((p, i) => set(p, left + (Math.floor(i / K) + .5) * dx, y0 + (i % K) * 6.5)); });
  P.filter(p => !p.enGrupo).forEach(p => set(p, W / 2, H + 30)); // sin dato: fuera de la vista
}
function placePeople() { // cada persona sintética se coloca en su comunidad
  const R = rng(99);
  P.forEach(p => { const reg = REG[RI[p.per.ccaa]] || REG[RI.MD], a = R() * 6.283, rr = Math.sqrt(R()) * (reg.id === "CN" ? .004 : .011), anchor = reg.pts[Math.floor(R() * reg.pts.length)];
    p.mx = anchor[0] + Math.cos(a) * rr; p.my = anchor[1] + Math.sin(a) * rr * 1.2; p.name = (p.per.sexo === "F" ? FN : MN)[Math.floor(rng(p.i + 7)() * 30)]; });
}

/* ================= bucle de dibujo ================= */
function frame(now) {
  const t = now / 1000;
  cx.clearRect(0, 0, VW, VH);
  if (MODE === "home") drawHome(t); else drawApp(t);
  requestAnimationFrame(frame);
}
let lastBeat = 0;
function beat(t) { beats.push(t); lastBeat = t; const d = $("#ldot"); d.classList.remove("beat"); void d.offsetWidth; d.classList.add("beat"); if (MODE === "home") for (let i = 0; i < 24; i++) P[Math.floor(Math.random() * N)].flash = 1; }
function drawHome(t) {
  if (t - lastBeat > BEAT && !RM) beat(t);
  const B = homeBox(), mad = { x: B.x + MADRID[0] * B.w, y: B.y + MADRID[1] * B.h }, rad = dotR(), speed = B.w * .55;
  beats = beats.filter(b => t - b < 2.6);
  beats.forEach(b => { const k = (t - b) / 2.6, r = 8 + k * B.w * .8; cx.strokeStyle = `rgba(240,68,46,${(.32 * (1 - k)).toFixed(3)})`; cx.lineWidth = 1.5; cx.beginPath(); cx.arc(mad.x, mad.y, r, 0, 6.283); cx.stroke(); });
  for (const p of P) {
    const tx = B.x + p.hx * B.w, ty = B.y + p.hy * B.h;
    if (t > .2 + p.d * .9) { p.x += (tx - p.x) * p.k; p.y += (ty - p.y) * p.k; }
    const dist = Math.hypot(tx - mad.x, ty - mad.y); let pulse = 0;
    for (const b of beats) { const ph = (t - b) - dist / speed; pulse += Math.exp(-((ph / .11) ** 2)); }
    const mx = p.x - mouse.x, my = p.y - mouse.y, md = Math.hypot(mx, my), R0 = 110;
    let fx = 0, fy = 0; if (md < R0 && md > .1) { const f = (R0 - md) / R0; fx = mx / md * f * 30; fy = my / md * f * 30; }
    p.ox += (fx - p.ox) * .12; p.oy += (fy - p.oy) * .12;
    const ux = dist ? (tx - mad.x) / dist : 0, uy = dist ? (ty - mad.y) / dist : 0;
    p.flash *= .955;
    const X = p.x + p.ox + ux * pulse * 4, Y = p.y + p.oy + uy * pulse * 4, r = rad * p.sz * (1 + pulse * .55 + p.flash * .9);
    let c = p.hue === 1 ? "240,68,46" : p.hue === 2 ? "255,138,31" : "26,31,58", a = p.hue ? .85 : .4;
    if (p.flash > .05) { c = "240,68,46"; a = .45 + .4 * p.flash; }
    cx.fillStyle = `rgba(${c},${a.toFixed(3)})`; cx.beginPath(); cx.arc(X, Y, r, 0, 6.283); cx.fill();
  }
  canariasFrame(B, 0, 0);
}
function canariasFrame(B, ox, oy) {
  cx.strokeStyle = "rgba(26,31,58,.16)"; cx.lineWidth = 1; cx.beginPath();
  cx.moveTo(ox + B.x + (CNBOX.x - .005) * B.w, oy + B.y + (CNBOX.y - .014) * B.h); cx.lineTo(ox + B.x + (CNBOX.x + CNBOX.w + .012) * B.w, oy + B.y + (CNBOX.y - .014) * B.h);
  cx.lineTo(ox + B.x + (CNBOX.x + CNBOX.w + .012) * B.w, oy + B.y + (CNBOX.y + CNBOX.h + .012) * B.h); cx.stroke();
}
function colorTarget(p) {
  if (!p.active) return [26, 31, 58, .07];
  if (p.voted && RES) { const c = hex2(optColor(p.ans)); return [c[0], c[1], c[2], .93]; }
  if (!RES && p.hue) return p.hue === 1 ? [240, 68, 46, .8] : [255, 138, 31, .8];
  return [26, 31, 58, LAYOUT === "cloud" ? .45 : .32];
}
let lastW = 0, lastH = 0;
function drawApp(t) {
  const dy = stageRect();
  // si el área del gráfico cambia de tamaño (p. ej. crece la tarjeta de resultados), se recoloca todo
  if (!inTransition && (Math.abs(H - lastH) > 2 || Math.abs(W - lastW) > 2)) { if (lastH) layout(LAYOUT, SORTED, false); lastW = W; lastH = H; }
  if (dy && !inTransition) P.forEach(p => { p.x += dy; p.y += dy; p.tx += dy; p.ty += dy; }); // desplazamiento en móvil
  if (!RM && t - lastBeat > BEAT) beat(t);
  cx.save();
  if (!inTransition) { cx.beginPath(); cx.rect(SX, SY, W, H); cx.clip(); }
  const r0 = dotR(), done = D && LAYOUT !== "cloud" && !voting;
  heatA += ((LAYOUT === "map" && done && labelA > 0 ? 1 : 0) - heatA) * .06;
  if (heatA > .01 && D) { const hc = heatLayer(); cx.globalAlpha = heatA; cx.drawImage(hc.cv, SX + hc.x, SY + hc.y, hc.w, hc.h); cx.globalAlpha = 1; }
  if (LAYOUT === "map") canariasFrame(mapBox(), SX, SY);
  const idle = !RES && LAYOUT === "map", breath = idle && !RM ? Math.exp(-(((t - lastBeat) / .18) ** 2)) : 0;
  const ccx = SX + W / 2, ccy = SY + (H + PADT()) / 2 - 20, CR = Math.min(W, H - PADT()) * .34;
  for (const p of P) {
    if (LAYOUT === "cloud") { const a = p.ca + t * p.cw * 1.4, r = CR * p.cr * (1 + .06 * Math.sin(t * 3 + p.ca * 4)); p.tx = ccx + Math.cos(a) * r; p.ty = ccy + Math.sin(a) * r * .78; }
    if (t >= p.at) { p.x += (p.tx - p.x) * p.k * 1.2; p.y += (p.ty - p.y) * p.k * 1.2; }
    const ct = colorTarget(p); for (let i = 0; i < 4; i++) p.col[i] += (ct[i] - p.col[i]) * .12;
    p.pop *= .9;
    const r = r0 * p.sz * (1 + p.pop * 1.6 + breath * .5);
    cx.fillStyle = `rgba(${p.col[0] | 0},${p.col[1] | 0},${p.col[2] | 0},${p.col[3].toFixed(3)})`;
    cx.beginPath(); cx.arc(p.x, p.y, r, 0, 6.283); cx.fill();
  }
  rings = rings.filter(g => t - g.t < .7);
  rings.forEach(g => { const k = (t - g.t) / .7; cx.strokeStyle = `rgba(${g.c[0]},${g.c[1]},${g.c[2]},${(.55 * (1 - k)).toFixed(3)})`; cx.lineWidth = 1.4; cx.beginPath(); cx.arc(g.p.x, g.p.y, 2 + k * 14, 0, 6.283); cx.stroke(); });
  if (hover) { cx.strokeStyle = "#1A1F3A"; cx.lineWidth = 2; cx.beginPath(); cx.arc(hover.x, hover.y, r0 * 2.6 + Math.sin(t * 6), 0, 6.283); cx.stroke(); }
  labelA += ((done && (SORTED || LAYOUT === "map") ? 1 : 0) - labelA) * .08;
  if (labelA > .02 && D) { cx.translate(SX, SY); drawLabels(); }
  cx.restore();
}
// capa de calor por comunidad: se dibuja una vez en un canvas aparte y se reutiliza en cada fotograma
const HEAT = { key: "", cv: document.createElement("canvas") };
function heatLayer() {
  const B = mapBox(), lead = D.lead, key = [B.w | 0, B.h | 0, lead, D.share.join(), Object.values(D.reg).map(v => v[lead]).join()].join("|");
  const pad = B.w / 20;
  if (HEAT.key !== key) {
    HEAT.key = key; const c = HEAT.cv, g = c.getContext("2d");
    c.width = (B.w + 2 * pad) * DPR; c.height = (B.h + 2 * pad) * DPR; g.setTransform(DPR, 0, 0, DPR, 0, 0); g.clearRect(0, 0, B.w + 2 * pad, B.h + 2 * pad);
    const vals = REG.map(r => D.reg[r.id] ? D.reg[r.id][lead] : null).filter(v => v !== null), mn = Math.min(...vals), mx = Math.max(...vals), col = hex2(optColor(lead)), rr = B.w / 46;
    MAPPTS.forEach(([x, y, ri]) => { const v = D.reg[REG[ri].id]; if (!v) return; const s = (v[lead] - mn) / (mx - mn || 1);
      g.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},${(.02 + .1 * s).toFixed(3)})`; g.beginPath(); g.arc(pad + x * B.w, pad + y * B.h, rr, 0, 6.283); g.fill(); });
  }
  return { cv: HEAT.cv, x: B.x - pad, y: B.y - pad, w: B.w + 2 * pad, h: B.h + 2 * pad };
}
function txt(s, x, y, size, color, align = "center", weight = 600, font = "display") {
  cx.font = `${weight} ${size}px ${font === "mono" ? '"JetBrains Mono", monospace' : '"Space Grotesk", sans-serif'}`; cx.textAlign = align; cx.textBaseline = "alphabetic";
  cx.lineWidth = 5; cx.strokeStyle = `rgba(255,244,232,${(.92 * labelA).toFixed(3)})`; cx.lineJoin = "round"; cx.strokeText(s, x, y);
  cx.fillStyle = color; cx.globalAlpha = labelA; cx.fillText(s, x, y); cx.globalAlpha = 1;
}
const shortOpt = o => { const s = RES.opciones[o]; return "«" + (s.length > 22 ? s.slice(0, 21) + "…" : s) + "»"; };
// etiqueta con fondo blanco redondeado (legible encima de los puntos)
function pill(t, x, y, size) {
  cx.font = `700 ${size}px "JetBrains Mono", monospace`; const w = cx.measureText(t).width + 12, h = size + 9;
  cx.globalAlpha = labelA * .92; cx.fillStyle = "#fff"; cx.beginPath(); cx.roundRect(x - w / 2, y - h / 2, w, h, h / 2); cx.fill();
  cx.globalAlpha = labelA; cx.fillStyle = "#1A1F3A"; cx.textAlign = "center"; cx.textBaseline = "middle"; cx.fillText(t, x, y + .5); cx.textBaseline = "alphabetic"; cx.globalAlpha = 1;
}
// leyenda de colores dentro del gráfico (arriba a la izquierda)
function drawLegend(sm) {
  if (LAYOUT === "hemi") return;
  let x = sm ? 10 : 24; const y = 20, size = sm ? 11 : 12.5;
  cx.font = `500 ${size}px "Space Grotesk", sans-serif`;
  RES.opciones.forEach((o, i) => { const etiqueta = o.length > 24 ? o.slice(0, 23) + "…" : o, w = cx.measureText(etiqueta).width;
    if (x + w + 22 > W - 10) return;
    cx.globalAlpha = labelA; cx.fillStyle = optColor(i); cx.beginPath(); cx.arc(x + 5, y - 4, 5, 0, 6.283); cx.fill(); cx.globalAlpha = 1;
    txt(etiqueta, x + 15, y, size, "#1A1F3A", "left", 500); x += w + 34; });
}
const UMBRAL_N = 120;
const nGrupo = (tipo, clave) => { const g = RES && RES.confianza && RES.confianza.n_grupos; return g && g[tipo] && g[tipo][clave] != null ? g[tipo][clave] : null; };
function drawLabels() {
  const lead = D.lead, lc = optColor(lead), sm = W < 600;
  if (LAYOUT === "hemi" && layout.hemi) { const h = layout.hemi;
    txt(pct(D.share[lead]), h.cx, h.cy - h.R0 * .25, Math.min(64, h.R0 * .6), lc, "center", 700);
    txt(RES.opciones[lead], h.cx, h.cy - 4, sm ? 12 : 14, "#5A6075", "center", 500); }
  if (LAYOUT === "sex" && layout.sex) { const L = layout.sex;
    [["F", "Mujeres"], ["M", "Hombres"]].forEach(([s, name]) => { const v = D.sex[s]; if (!v) return; const x = L.xs[s] + L.fw / 2;
      txt(name, x, L.fy + L.fh + 24, sm ? 15 : 18, "#1A1F3A", "center", 600);
      txt(`${pct(v[lead])} ${shortOpt(lead)}`, x, L.fy + L.fh + 44, sm ? 10.5 : 12, "#5A6075", "center", 400, "mono");
      const left = s === "F", bx = left ? L.xs[s] - 10 : L.xs[s] + L.fw + 10;
      for (let o = 0; o < D.k; o++) { if (v[o] < .06) continue; const g = P.filter(p => p.per && p.per.sexo === s && p.ans === o); if (!g.length) continue;
        const y = g.reduce((a, p) => a + p.ty, 0) / g.length - SY; txt(pct(v[o]), bx, y + 5, sm ? 12 : 15, optColor(o), left ? "right" : "left", 700); } }); }
  if (LAYOUT === "age" && layout.age) { const A = layout.age, pts = [];
    AGEB.forEach((ab, b) => { const x = A.pad + (b + .5) * A.cw; txt(ab + " años", x, A.base + 28, sm ? 11 : 14, "#1A1F3A", "center", 600); const v = D.age[b]; if (!v) return;
      pts.push([x, 0, v[lead]]);
      if (!SORTED) return;
      // porcentaje de cada franja, centrado sobre ella
      let acum = 0; v.forEach((share, o) => { const yc = A.base - (acum + share / 2) * A.alto; acum += share; if (share < .07) return; pill(pct(share), x, yc, sm ? 10.5 : 12.5); }); });
    if (A.bajo) return drawLegend(sm);
    const techo = A.base - A.alto - 30, vs = pts.map(p => p[2]), lo = Math.min(...vs), hi = Math.max(...vs);
    pts.forEach(p => p[1] = techo - (hi > lo ? (p[2] - lo) / (hi - lo) : .5) * Math.min(46, techo - 30));
    cx.globalAlpha = labelA * .55; cx.strokeStyle = lc; cx.lineWidth = 2; cx.setLineDash([4, 5]); cx.beginPath(); pts.forEach(([x, y], i) => i ? cx.lineTo(x, y - 6) : cx.moveTo(x, y - 6)); cx.stroke(); cx.setLineDash([]); cx.globalAlpha = 1;
    pts.forEach(([x, y, v]) => { cx.globalAlpha = labelA; cx.fillStyle = lc; cx.beginPath(); cx.arc(x, y - 6, 4, 0, 6.283); cx.fill(); cx.globalAlpha = 1; txt(pct(v), x, y - 16, sm ? 13 : 17, lc, "center", 700); }); }
  if (LAYOUT === "grp" && layout.grp) { const G = layout.grp;
    G.vals.forEach((v, r) => { const sh = D.grp[v]; if (!sh) return; const yc = G.pt + r * G.rowH + G.rowH / 2;
      txt(v, G.left - 14, yc + 4, sm ? 11 : 13.5, "#1A1F3A", "right", 600);
      let acum = 0; sh.forEach((x, o) => { const xc = G.left + (acum + x / 2) * G.ancho; acum += x; if (x >= (sm ? .14 : .09)) pill(pct(x), xc, yc, sm ? 10 : 11.5); });
      txt(pct(sh[lead]), G.left + G.ancho + 10, yc + 5, sm ? 12 : 15, lc, "left", 700); }); }
  drawLegend(sm);
  if (LAYOUT === "map") { const B = mapBox();
    REG.forEach(r => { const v = D.reg[r.id]; if (!v || r.id === "NA" || r.id === "RI" || (W < 760 && ["CB", "AS", "MC", "IB"].includes(r.id))) return;
      const x = B.x + (r.id === "CN" ? .11 : r.x) * B.w, y = B.y + (r.id === "CN" ? .845 : r.y) * B.h;
      const pocos = nGrupo("ccaa", r.id) !== null && nGrupo("ccaa", r.id) < UMBRAL_N;
      txt(r.name + (pocos ? "*" : ""), x, y - 2, sm ? 9.5 : 11, "#1A1F3A", "center", 600); txt(pct(v[lead]), x, y + 13, sm ? 11 : 13, pocos ? "#8A8FA3" : lc, "center", 700, "mono"); });
    if (REG.some(r => (nGrupo("ccaa", r.id) ?? 1e9) < UMBRAL_N)) txt(`* menos de ${UMBRAL_N} entrevistas reales: tomar con cautela`, W - (sm ? 10 : 24), H - 12, sm ? 9.5 : 11, "#5A6075", "right", 500, "mono"); }
}

/* ================= interacción con el canvas ================= */
const tip = $("#tip");
addEventListener("pointermove", e => {
  mouse.x = e.clientX; mouse.y = e.clientY;
  if (MODE !== "app" || !RES || LAYOUT === "cloud" || e.clientX < SX || e.clientX > SX + W || e.clientY < SY || e.clientY > SY + H || e.target.closest(".results,.stage-top,.chat,.cfg,.drawer")) { hover = null; tip.classList.remove("on"); return; }
  let best = null, bd = 144; for (const p of P) { const d = (p.x - e.clientX) ** 2 + (p.y - e.clientY) ** 2; if (d < bd) { bd = d; best = p; } }
  hover = best; if (!best || !best.per) { tip.classList.remove("on"); hover = null; return; }
  const p = best, ans = p.voted ? RES.opciones[p.ans] : null, c = ans ? optColor(p.ans) : NSC;
  const v = ans && RES.voces && RES.voces[p.ans], quote = v ? v[p.i % v.length] : "Aún no ha respondido.";
  tip.innerHTML = `<div class="who"><span class="ini" style="background:${c}">${p.name[0]}</span><div><b>${p.name}, ${p.per.edad}</b><span>${(REG[RI[p.per.ccaa]] || {}).name || ""}</span></div></div>
    <div class="tags"><span>${p.per.sexo === "F" ? "Mujer" : "Hombre"}</span>${p.per.tags.map(t => `<span>${t}</span>`).join("")}</div>
    ${ans ? `<div class="ans"><i style="background:${c}"></i>${ans}</div>` : ""}<q>${quote}</q><div class="fake">Persona sintética · no existe</div>`;
  const tw = 256, x = e.clientX + 18 + tw > VW ? e.clientX - tw - 18 : e.clientX + 18; tip.style.left = x + "px"; tip.style.top = clamp(e.clientY - 40, 8, VH - 200) + "px"; tip.classList.add("on");
});
addEventListener("pointerleave", () => { mouse.x = mouse.y = -1e4; hover = null; tip.classList.remove("on"); });

/* ================= audio ================= */
let AC = null, MUTE = false;
function audio() { if (!AC) { try { AC = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { AC = null; } } if (AC && AC.state === "suspended") AC.resume(); }
function tone(f, d = .08, v = .05, type = "sine", when = 0) { if (!AC || MUTE) return; const t = AC.currentTime + when, o = AC.createOscillator(), g = AC.createGain(); o.type = type; o.frequency.setValueAtTime(f, t); g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(v, t + .008); g.gain.exponentialRampToValueAtTime(.0001, t + d); o.connect(g).connect(AC.destination); o.start(t); o.stop(t + d + .02); }
function whoosh(up = true) { if (!AC || MUTE) return; const t = AC.currentTime, len = .7, b = AC.createBuffer(1, AC.sampleRate * len, AC.sampleRate), d = b.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / d.length); const s = AC.createBufferSource(), f = AC.createBiquadFilter(), g = AC.createGain(); s.buffer = b; f.type = "bandpass"; f.Q.value = 1.2; f.frequency.setValueAtTime(up ? 300 : 2400, t); f.frequency.exponentialRampToValueAtTime(up ? 2600 : 300, t + len); g.gain.setValueAtTime(.0001, t); g.gain.exponentialRampToValueAtTime(.1, t + .15); g.gain.exponentialRampToValueAtTime(.0001, t + len); s.connect(f).connect(g).connect(AC.destination); s.start(t); }
function chord() { [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => tone(f, 1.1, .04, "triangle", i * .06)); }
const NOTES = [659.25, 523.25, 783.99, 587.33, 440];
$("#snd").onclick = () => { MUTE = !MUTE; $("#sndW").style.opacity = MUTE ? 0 : 1; $("#snd").setAttribute("aria-label", MUTE ? "Activar sonido" : "Silenciar sonido"); if (!MUTE) { audio(); tone(660, .12, .05); } };

/* ================= transición inicio → resultados ================= */
let inTransition = false;
async function toApp() {
  if (MODE === "app") return;
  const ask = $("#ask"), first = ask.getBoundingClientRect();
  const ghost = ask.cloneNode(true); ghost.removeAttribute("id"); ghost.querySelectorAll("[id]").forEach(n => n.removeAttribute("id"));
  Object.assign(ghost.style, { position: "fixed", left: first.left + "px", top: first.top + "px", width: first.width + "px", height: first.height + "px", margin: 0, transform: "none", zIndex: 50, pointerEvents: "none" });
  document.body.appendChild(ghost);
  inTransition = true; MODE = "app"; document.body.classList.replace("home", "app"); ask.style.opacity = 0; $("#q").placeholder = "Haz otra pregunta…";
  resize();
  const last = ask.getBoundingClientRect();
  ghost.animate([{ left: first.left + "px", top: first.top + "px", width: first.width + "px", height: first.height + "px", borderRadius: "999px" },
    { left: last.left + "px", top: last.top + "px", width: last.width + "px", height: last.height + "px", borderRadius: "22px" }], { duration: RM ? 1 : 600, easing: "cubic-bezier(.2,.9,.3,1)", fill: "forwards" });
  layout("map", false); whoosh(true);
  await sleep(620); ghost.remove(); ask.style.opacity = ""; inTransition = false;
}

/* ================= vistas ================= */
const viewsEl = $("#views");
function setViewBtn(v) { viewsEl.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.v === v)); const b = viewsEl.querySelector(`[data-v="${v}"]`), pill = viewsEl.querySelector(".pill"); if (b && b.offsetWidth) { pill.style.left = b.offsetLeft + "px"; pill.style.width = b.offsetWidth + "px"; } }
viewsEl.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; switchView(b.dataset.v); });
function renderDims() {
  const el = $("#dims"); el.hidden = VIEW !== "grp" || !RES;
  if (el.hidden) return;
  const dims = (RES.agregados.grupos_orden && Object.keys(RES.agregados.grupos_orden)) || ["Ideología", "Estudios", "Trabajo", "Renta del hogar", "Vivienda", "Vive solo", "Uso de IA", "Municipio"];
  el.innerHTML = dims.map(d => `<button type="button" class="${d === DIM ? "on" : ""}">${d}</button>`).join("");
}
$("#dims").addEventListener("click", e => { const b = e.target.closest("button"); if (!b || voting) return; DIM = b.textContent; renderDims(); D = displayStats(); labelA = 0; layout("grp", true, false); renderInsight(); });
function switchView(v) { VIEW = v; setViewBtn(v); renderDims(); if (busy && !RES) return; if (voting) return; labelA = 0; whoosh(v !== "map"); layout(v, !!D, false); if (D) renderInsight(); }
addEventListener("keydown", e => { if (e.target.closest && e.target.closest("textarea,input,select")) return; const m = { 1: "hemi", 2: "map", 3: "sex", 4: "age", 5: "grp" }[e.key]; if (m && MODE === "app") switchView(m); });

/* ================= tira de resultados ================= */
function renderResults(final) {
  const st = final ? D : LIVE; if (!st || !RES) return;
  const lead = st.share.indexOf(Math.max(...st.share));
  $("#res").classList.remove("wait");
  $("#stack").innerHTML = RES.opciones.map((o, i) => `<i style="background:${optColor(i)};width:${(st.share[i] * 100).toFixed(2)}%"></i>`).join("");
  $("#legend").innerHTML = RES.opciones.map((o, i) => `<span><i style="background:${optColor(i)}"></i>${o} <b>${pct(st.share[i])}</b></span>`).join("");
  $("#big").textContent = pct(st.share[lead]); $("#big").style.color = optColor(lead) === "#1A1F3A" ? "#1A1F3A" : "";
  $("#bigL").textContent = `responde «${RES.opciones[lead]}»`;
  if (!final) return;
  const c = RES.confianza, L = c.nivel;
  $("#sema").dataset.l = L; $("#semaT").textContent = ["", "Confianza baja", "Confianza media", "Confianza alta"][L];
  $("#sema").title = c.texto;
  const err = c.error_pp != null ? `±${String(c.error_pp).replace(".", ",")} pp` : "±? pp";
  $("#moe").textContent = filtered() ? `${err} · ${fmt(D.n)} personas en el filtro` : `${err} · n = ${fmt(c.n)}${RES.modo === "evidencia" ? "" : " perfiles"}`;
  drawSpark(); renderInsight();
}
function drawSpark() {
  const s = RES.serie || [], sv = $("#spark");
  if (s.length < 2) { sv.innerHTML = `<text x="0" y="20" font-size="9.5" fill="#5A6075" font-family="JetBrains Mono, monospace">${RES.modo === "evidencia" ? "una sola ola del CIS" : "sin serie histórica"}</text>`; return; }
  const v = s.map(p => p.valor), mn = Math.min(...v) - 3, mx = Math.max(...v) + 3, X = i => 6 + i * (138 / (s.length - 1)), Y = x => 26 - (x - mn) / (mx - mn) * 20, c = optColor(0);
  const d = v.map((x, i) => (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(x).toFixed(1)).join(" ");
  sv.innerHTML = `<path d="${d} L${X(s.length - 1)} 28 L${X(0)} 28 Z" fill="${c}" opacity=".1"/><path d="${d}" fill="none" stroke="${c}" stroke-width="2" stroke-linecap="round"/>
    ${v.map((x, i) => `<circle cx="${X(i)}" cy="${Y(x)}" r="${i === v.length - 1 ? 3.4 : 1.8}" fill="${i === v.length - 1 ? c : "#A9AEC0"}"><title>${s[i].etiqueta}: ${String(x).replace(".", ",")} %</title></circle>`).join("")}
    <text x="0" y="34" font-size="8" fill="#5A6075" font-family="JetBrains Mono, monospace">${s[0].etiqueta}</text><text x="150" y="34" font-size="8" fill="#5A6075" text-anchor="end" font-family="JetBrains Mono, monospace">${s[s.length - 1].etiqueta}</text>`;
}
function facts() {
  const lead = D.lead, f = {};
  const regs = REG.map(r => ({ r, v: D.reg[r.id] ? D.reg[r.id][lead] : null })).filter(o => o.v !== null).sort((a, b) => b.v - a.v);
  f.regHi = regs[0]; f.regLo = regs[regs.length - 1];
  const ages = AGEB.map((a, b) => ({ a, v: D.age[b] ? D.age[b][lead] : null })).filter(o => o.v !== null);
  f.ageY = ages[0]; f.ageO = ages[ages.length - 1]; f.ageHi = ages.slice().sort((a, b) => b.v - a.v)[0];
  f.F = D.sex.F ? D.sex.F[lead] : 0; f.M = D.sex.M ? D.sex.M[lead] : 0;
  const s2 = D.share.slice().sort((a, b) => b - a); f.margin = (s2[0] - (s2[1] || 0)) * 100;
  const gaps = [];
  if (f.regHi && f.regLo) gaps.push(["territorial", Math.abs(f.regHi.v - f.regLo.v)]);
  f.unaEdad = ages.length < 2;
  if (f.ageY && f.ageO && !f.unaEdad) gaps.push(["generacional", Math.abs(f.ageY.v - f.ageO.v)]);
  gaps.push(["de género", Math.abs(f.F - f.M)]);
  f.maxGap = gaps.sort((a, b) => b[1] - a[1])[0][0];
  return f;
}
const pp = x => Math.round(Math.abs(x) * 100) + " pp";
function insightFor(v) {
  const f = facts(), o = shortOpt(D.lead);
  if (v === "hemi") return `<small>Mayor brecha · ${f.maxGap}</small>${o} gana con <b>${pct(D.share[D.lead])}</b>, ${Math.round(f.margin)} pp por delante de la segunda opción.`;
  if (v === "map" && f.regHi) { const aviso = [f.regHi, f.regLo].filter(x => (nGrupo("ccaa", x.r.id) ?? 1e9) < UMBRAL_N).map(x => x.r.name);
    return `<small>Brecha territorial · ${pp(f.regHi.v - f.regLo.v)}</small>Más alto en <b>${f.regHi.r.name} (${pct(f.regHi.v)})</b>. Más bajo en ${f.regLo.r.name} (${pct(f.regLo.v)}).` +
      (aviso.length ? ` <span style="color:var(--mute);font-size:12px">${aviso.join(" y ")}: pocas entrevistas reales.</span>` : ""); }
  if (v === "sex") return `<small>Brecha de género · ${pp(f.F - f.M)}</small>${o}: mujeres <b>${pct(f.F)}</b>, hombres <b>${pct(f.M)}</b>.`;
  if (v === "grp") { const g = Object.entries(D.grp).map(([k, x]) => [k, x[D.lead]]).sort((a, b) => b[1] - a[1]);
    if (g.length >= 2) return `<small>Brecha por ${DIM.toLowerCase()} · ${pp(g[0][1] - g[g.length - 1][1])}</small>${o}: <b>${g[0][0]} ${pct(g[0][1])}</b> frente a ${g[g.length - 1][0]} ${pct(g[g.length - 1][1])}.`; }
  if (v === "age" && f.unaEdad && f.ageY) return `<small>Filtro de edad activo</small>${o}: <b>${pct(f.ageY.v)}</b> entre las personas de ${f.ageY.a} años.`;
  if (v === "age" && f.ageY) return `<small>Brecha generacional · ${pp(f.ageY.v - f.ageO.v)}</small>${o}: ${f.ageY.a} años <b>${pct(f.ageY.v)}</b>, ${f.ageO.a} años <b>${pct(f.ageO.v)}</b>.`;
  return `<small>Lectura rápida</small>No hay suficientes personas con estos filtros.`;
}
function renderInsight() { if (D) $("#insight").innerHTML = insightFor(VIEW); }

/* ================= chat ================= */
const msgs = $("#msgs");
const scrollChat = () => { msgs.scrollTop = msgs.scrollHeight; };
function addUser(t) { const d = document.createElement("div"); d.className = "msg user"; d.textContent = t; msgs.appendChild(d); scrollChat(); }
function addBot(html = "", cls = "") { const d = document.createElement("div"); d.className = "msg bot " + cls; d.innerHTML = `<span class="av"></span><div class="tx">${html}</div>`; msgs.appendChild(d); scrollChat(); return d.querySelector(".tx"); }
async function streamBot(html, el, cls) {
  el = el || addBot("", cls); const tmp = document.createElement("div"); tmp.innerHTML = html; el.innerHTML = "";
  async function walk(src, dst) { for (const n of [...src.childNodes]) {
    if (n.nodeType === 3) { const words = n.textContent.split(/(\s+)/), tn = document.createTextNode(""); dst.appendChild(tn); for (const w of words) { tn.textContent += w; if (w.trim()) { await sleep(RM ? 0 : 24); scrollChat(); } } }
    else { const c = n.cloneNode(false); dst.appendChild(c); await walk(n, c); } } }
  await walk(tmp, el); scrollChat(); return el;
}
function chips(list, target = "#sugg") { const s = $(target); s.innerHTML = ""; list.forEach(([label, fn], i) => { const b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = label; b.style.animationDelay = (i * .07 + (target === "#homeChips" ? 1.4 : 0)) + "s"; b.onclick = fn; s.appendChild(b); }); }
// [texto del botón, consulta que se lanza]
const EJEMPLOS = [["¿Te preocupa el cambio climático?"], ["¿Te sientes solo a menudo?"],
  ["Test A/B: ahorro o huella de carbono", "«Ahorra 200 € al año en tu factura» vs «Reduce tu huella de carbono»"],
  ["¿Zapatos rojos o azules?", "¿Qué atrae más a los jóvenes: zapatos rojos o azules?"]];
const exampleChips = target => chips(EJEMPLOS.map(([t, q]) => [t, () => ask(q || t)]), target);
function followChips() { chips([["Ver por comunidades", () => ask("Ver por comunidades")], ["Ver por sexo", () => ask("Ver por sexo")], ["Ver por edad", () => ask("Ver por edad")], ["Ver por ideología, renta…", () => ask("Ver por grupos")],
  ...(RES && RES.modo === "evidencia" && (!ESTATICO || (RES._entrada && RES._entrada.comparar)) ? [["LLM sin datos vs pulso", abrirComparacion]] : []),
  ["¿Cómo lo sabemos?", abrirValidacion], ["Otra pregunta", () => { exampleChips(); $("#q").focus(); }]]); }

/* ================= diseñador de encuesta ================= */
const TOPICS = ["Vivienda", "Soledad", "Tecnología e IA", "Medio ambiente", "Salud", "Consumo"];
let curTopic = null, OPTS = ["Sí", "No"], TIPO = "pregunta";
const OPTS_CAMPANA = ["Me convence", "Me es indiferente", "No me convence"];
function setTipo(t) {
  TIPO = t; segOn($("#fTipo"), $(`#fTipo [data-v="${t}"]`));
  $("#cqLbl").textContent = t === "pregunta" ? "Pregunta" : t === "campana" ? "Mensaje o iniciativa" : "Mensaje A";
  $("#fldB").hidden = t !== "ab"; $("#fldOpts").hidden = t === "ab";
  if (t === "campana" && !RES?.tipo?.startsWith("campana")) { OPTS = OPTS_CAMPANA.slice(); renderOpts(); }
}
function renderTopics() { $("#topics").innerHTML = TOPICS.map(t => `<button type="button" class="${t === curTopic ? "on" : ""}">${t}</button>`).join(""); }
$("#topics").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; curTopic = b.textContent; $("#topicAuto").textContent = "elegido a mano"; renderTopics(); });
function renderOpts() {
  $("#opts").innerHTML = OPTS.map((o, i) => `<div class="opt"><i style="background:${isNS(o) ? NSC : PAL[i % PAL.length]}"></i><input id="opt${i}" value="${o.replace(/"/g, "&quot;")}" aria-label="Opción ${i + 1}"><button type="button" data-i="${i}" aria-label="Quitar opción">×</button></div>`).join("");
  $("#addOpt").hidden = OPTS.length >= 4;
}
$("#opts").addEventListener("input", e => { const m = e.target.id.match(/^opt(\d)$/); if (m) OPTS[+m[1]] = e.target.value; });
$("#opts").addEventListener("click", e => { const b = e.target.closest("button"); if (!b || OPTS.length <= 2) return; OPTS.splice(+b.dataset.i, 1); renderOpts(); });
$("#addOpt").addEventListener("click", () => { OPTS.push("Nueva opción"); renderOpts(); });
$("#fReg").innerHTML = `<option value="all">Toda España</option>` + REG.slice().sort((a, b) => a.name.localeCompare(b.name, "es")).map(r => `<option value="${r.id}">${r.name}</option>`).join("");
function renderYears(disp) { $("#fYear").innerHTML = [2021, 2022, 2023, 2024, 2025, 2026].map(y => { const ok = y === 2026; return `<button type="button" data-v="${y}" class="${ok ? "on" : ""}" ${ok ? "" : `disabled title="${disp && disp.includes(y) ? "Datos de esta ola en la tendencia" : "Sin datos CIS cargados para este año"}"`}>${y}</button>`; }).join(""); }
function segOn(el, b) { el.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); }
$("#fReg").addEventListener("change", e => { F.reg = e.target.value; refilter(); });
$("#fSex").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; segOn($("#fSex"), b); F.sex = b.dataset.v; refilter(); });
function syncAge() { let a = +$("#aMin").value, b = +$("#aMax").value; if (a > b - 2) { if (document.activeElement === $("#aMin")) a = b - 2; else b = a + 2; $("#aMin").value = a; $("#aMax").value = b; }
  F.aMin = a; F.aMax = b; $("#ageLbl").textContent = `${a} - ${b === 90 ? "90+" : b} años`; $("#ageTr").style.left = ((a - 18) / 72 * 100) + "%"; $("#ageTr").style.right = ((90 - b) / 72 * 100) + "%"; }
["aMin", "aMax"].forEach(id => $("#" + id).addEventListener("input", () => { syncAge(); refilter(); }));
let filterT = 0;
function refilter() { applyFilter(); if (!RES || voting) return; D = displayStats(); renderResults(true); clearTimeout(filterT); filterT = setTimeout(() => { if (LAYOUT !== "map") layout(LAYOUT, true); }, 250); }
const urlPoblacion = n => ESTATICO ? `datos/poblacion_${n}.csv` : `/api/poblacion?n=${n}`;
if (ESTATICO) $("#fTam").querySelectorAll("button").forEach(b => { if (+b.dataset.v > 25000) { b.disabled = true; b.title = "Disponible en la versión con motor local"; } });
$("#dlPob").href = urlPoblacion(25000);
$("#fTam").addEventListener("click", e => { const b = e.target.closest("button"); if (!b || b.disabled) return; segOn($("#fTam"), b);
  $("#tamLbl").textContent = `${fmt(+b.dataset.v)} personas`; $("#dlPob").href = urlPoblacion(b.dataset.v); });
$("#fTipo").addEventListener("click", e => { const b = e.target.closest("button"); if (b) setTipo(b.dataset.v); });
$("#launch").addEventListener("click", () => { closePanels(); const q = $("#cq").value.trim(); if (!q || busy) return; const opts = OPTS.map(o => o.trim()).filter(Boolean);
  if (TIPO === "ab") { const b = $("#cq2").value.trim(); if (!b) return; return ask(`«${q}» vs «${b}»`, null, true, { tipo: "ab", mensajes: [q, b] }); }
  if (TIPO === "campana") return ask(`Campaña: ${q}`, opts, true, { tipo: "campana", mensajes: [q] });
  const same = RES && q === RES.pregunta && opts.join("|") === RES.opciones.join("|"); ask(q, same ? null : opts, true); });
/* atajos en el chat: «Campaña: …» y «mensaje A» vs «mensaje B» */
function interpretarEntrada(t) {
  const c = t.match(/^campa[ñn]a\s*:\s*(.+)$/i); if (c) return { tipo: "campana", mensajes: [c[1].replace(/^[«"]|[»"]$/g, "")] };
  const ab = t.match(/«([^»]+)»\s*(?:vs\.?|frente a|o)\s*«([^»]+)»/i) || t.match(/^(?:test\s*)?a\/b\s*:\s*(.+?)\s+(?:vs\.?|\|)\s+(.+)$/i);
  if (ab) return { tipo: "ab", mensajes: [ab[1].trim(), ab[2].trim()] };
  return null;
}
const escritorio = () => innerWidth > 1180;
function openCfg() {
  if (escritorio()) { const abierto = document.body.classList.toggle("cfg-abierto"); $("#cfgBtn").classList.toggle("on", abierto); return; }
  $("#cfg").classList.add("open"); $("#scrim").classList.add("on");
}
function closeCfg() { document.body.classList.remove("cfg-abierto"); $("#cfgBtn").classList.remove("on"); closePanels(); }
function closePanels() { $("#cfg").classList.remove("open"); $("#hist").classList.remove("open"); $("#valid").classList.remove("open"); $("#comp").classList.remove("open"); $("#scrim").classList.remove("on"); }
$("#cfgBtn").onclick = openCfg; $("#validClose").onclick = () => closePanels(); $("#cfgClose").onclick = closeCfg; $("#scrim").onclick = closePanels; $("#histClose").onclick = closePanels;
addEventListener("keydown", e => { if (e.key === "Escape") closePanels(); });

/* ================= consultas anteriores ================= */
$("#histBtn").onclick = async () => {
  $("#hist").classList.add("open"); $("#scrim").classList.add("on");
  const list = $("#histList"); list.innerHTML = `<p class="mono" style="font-size:12px;color:var(--mute)">Cargando…</p>`;
  if (ESTATICO) $("#hist h3").firstChild.textContent = "Preguntas preparadas ";
  try { const h = ESTATICO ? (await indice()).map(e => ({ ...e, pregunta: e.pregunta })) : await (await fetch("/api/historial")).json();
    list.innerHTML = h.length ? "" : `<p style="color:var(--mute);font-size:14px">Todavía no hay consultas. Pregunta algo y aparecerá aquí.</p>`;
    h.forEach(c => { const b = document.createElement("button"); b.type = "button"; b.className = "hist";
      b.innerHTML = `<b>${c.pregunta}</b><span>${c.tema} · ${{ evidencia: "Evidencia CIS", analogia: "Analogía", simulacion: "Simulación" }[c.modo]} · <em>${String(c.valor).replace(".", ",")} % ${c.lider}</em></span>`;
      b.onclick = () => { closePanels(); ask(c.pregunta, null, false, c.tipo && c.tipo !== "pregunta" ? { tipo: c.tipo, mensajes: c.mensajes } : null); }; list.appendChild(b); list.appendChild(document.createElement("div")).style.height = "10px"; });
  } catch (e) { list.innerHTML = `<p style="color:var(--mute);font-size:14px">No se pudo conectar con el motor local.</p>`; }
};

/* ================= ¿cómo lo sabemos? ================= */
const COND = { solo_demografia: ["Solo demografía (LLM + edad, sexo, región…)", "#A9AEC0"], demografia_y_actitudes: ["Demografía + actitudes CIS", "#FF8A1F"], actitudes_relevantes: ["Demografía + actitudes CIS relacionadas", "#F0442E"] };
const num = (x, d = 1) => Number(x).toLocaleString("es-ES", { maximumFractionDigits: d, minimumFractionDigits: d });
async function abrirValidacion() {
  $("#valid").classList.add("open"); $("#scrim").classList.add("on");
  const body = $("#validBody");
  try {
    const v = await (await fetch(ESTATICO ? "datos/validacion.json" : "/api/validacion")).json(); let h = "";
    h += `<div class="vcard"><small><i style="background:#3BD27E"></i>Verde · respuestas reales del CIS</small>
      <div><span class="big">±${num(v.evidencia.error_misma_ola_pp)} pp</span></div>
      <div>Error medio de la población sintética frente al CIS en ${v.evidencia.preguntas} preguntas reales (${fmt(v.evidencia.entrevistas)} entrevistas). Cada pregunta tiene su propio modelo entrenado con microdatos y aplicado a las 25.000 personas.</div></div>`;
    if (v.temporal) { const r = Object.fromEntries(v.temporal.map(x => [x.validacion + "|" + x.desglose, x]));
      const b = k => r["B_reanclada|" + k];
      h += `<div class="vcard"><small><i style="background:#FFC24B"></i>Predicción en el tiempo · clima dic 2025 → sep 2026</small>
        <div>Entrenado con diciembre y comparado con septiembre (que el modelo no vio). Con el total nacional conocido, el reparto por grupos acierta:</div>
        <table><tr><th>Desglose</th><th class="n">Error pulso</th><th class="n">Sin modelo</th></tr>
        ${["sexo", "grupo_edad", "ccaa"].filter(b).map(k => `<tr><td>${{ sexo: "Sexo", grupo_edad: "Edad", ccaa: "Comunidad" }[k]}</td><td class="n">${num(b(k).error_medio_pts)} pp</td><td class="n">${b(k).error_sin_modelo_pts != null ? num(b(k).error_sin_modelo_pts) + " pp" : "-"}</td></tr>`).join("")}</table>
        <div style="font-size:12.5px;color:var(--mute)">La opinión cambió de verdad entre olas (+9 pp, verano de incendios): por eso pulso ancla el nivel con el dato más reciente.</div></div>`; }
    if (v.simulacion) { const R = v.simulacion.resumen, best = R.slice().sort((a, b) => a.error_total_pts - b.error_total_pts)[0];
      h += `<div class="vcard"><small><i style="background:#FF5A4A"></i>Rojo · preguntas nuevas simuladas con el LLM</small>
        <div>Tratamos cada pregunta real del CIS como si fuera nueva (sin dejar que el perfil la conozca) y comparamos la simulación con lo que respondió la gente.</div>
        <table><tr><th>Cómo responde el LLM</th><th class="n">Error medio</th><th class="n">Patrón por edad (r)</th></tr>
        ${R.map(x => `<tr class="${x === best ? "best" : ""}"><td>${(COND[x.condicion] || [x.condicion])[0]}</td><td class="n">${num(x.error_total_pts)} pp</td><td class="n">${num(x.correlacion_edad, 2)}</td></tr>`).join("")}
        <tr><td>Referencia: repartir a partes iguales</td><td class="n">${num(R[0].error_uniforme_pts)} pp</td><td class="n">-</td></tr></table>
        <div class="scatter-wrap">${scatter(v.simulacion.puntos)}</div>
        <div style="font-size:12.5px;color:var(--mute)">Cada punto es una pregunta real: horizontal, lo que respondió España; vertical, lo que simuló pulso. Cuanto más cerca de la diagonal, mejor.</div></div>`; }
    else h += `<div class="vcard"><small>Simulación</small><div>La calibración del simulador todavía se está calculando.</div></div>`;
    body.innerHTML = h;
  } catch (e) { body.innerHTML = `<p style="color:var(--mute)">No se pudo cargar la validación.</p>`; }
}
function scatter(puntos) {
  const S = 300, m = 34, X = v => m + v / 100 * (S - m - 10), Y = v => S - m - v / 100 * (S - m - 10);
  const ejes = [0, 25, 50, 75, 100].map(t => `<line x1="${X(t)}" y1="${Y(0)}" x2="${X(t)}" y2="${Y(100)}" stroke="rgba(26,31,58,.06)"/><line x1="${X(0)}" y1="${Y(t)}" x2="${X(100)}" y2="${Y(t)}" stroke="rgba(26,31,58,.06)"/>
    <text x="${X(t)}" y="${S - m + 14}" font-size="9" text-anchor="middle" fill="#5A6075" font-family="JetBrains Mono, monospace">${t}</text><text x="${m - 6}" y="${Y(t) + 3}" font-size="9" text-anchor="end" fill="#5A6075" font-family="JetBrains Mono, monospace">${t}</text>`).join("");
  const pts = puntos.filter(p => COND[p.condicion]).map(p => `<circle cx="${X(p.real)}" cy="${Y(p.simulado)}" r="4" fill="${COND[p.condicion][1]}" opacity=".85"><title>${p.pregunta}\nReal ${num(p.real)} % · simulado ${num(p.simulado)} %</title></circle>`).join("");
  const ley = Object.values(COND).map(([t, c], i) => `<circle cx="${m + 4}" cy="${12 + i * 13}" r="4" fill="${c}"/><text x="${m + 12}" y="${15 + i * 13}" font-size="9.5" fill="#1A1F3A" font-family="Space Grotesk, sans-serif">${t}</text>`).join("");
  return `<svg width="100%" viewBox="0 0 ${S} ${S}" style="max-width:420px;display:block;margin:auto" role="img" aria-label="Simulado frente a real">${ejes}
    <line x1="${X(0)}" y1="${Y(0)}" x2="${X(100)}" y2="${Y(100)}" stroke="#1A1F3A" stroke-dasharray="4 4" opacity=".35"/>${pts}${ley}
    <text x="${S / 2}" y="${S - 4}" font-size="9.5" text-anchor="middle" fill="#5A6075" font-family="JetBrains Mono, monospace">real CIS (%)</text></svg>`;
}
$("#sema").onclick = abrirValidacion;

const CSER = [["CIS real", "#1A1F3A", "real"], ["pulso", "#F0442E", "pulso"], ["LLM sin datos", "#A9AEC0", "llm_solo"]];
async function abrirComparacion() {
  if (!RES || RES.modo !== "evidencia") return;
  closePanels(); $("#comp").classList.add("open"); $("#scrim").classList.add("on");
  const body = $("#compBody");
  body.innerHTML = `<div class="vcard"><small>Preguntando a un LLM sin datos</small><div>Los mismos perfiles sintéticos responden con un LLM que solo conoce su edad, sexo, región, estudios e ideología, como hacen las herramientas de «personas sintéticas» del mercado. <span id="compProg" class="mono"></span></div></div>`;
  try {
    if (ESTATICO) {
      const e = RES._entrada;
      if (!e || !e.comparar) throw new Error("En la versión publicada la comparación solo está calculada para algunas preguntas en verde. Prueben con «¿Te preocupa el cambio climático?».");
      body.innerHTML = renderComparacion(await (await fetch(`datos/comparar/${e.comparar}`)).json()); return;
    }
    const r = await fetch("/api/comparar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pregunta: RES.pregunta }) });
    const { job } = await r.json();
    const c = await esperar(job, e => { if (e.fase === "respondiendo" && e.total > 1) { const el = $("#compProg"); if (el) el.textContent = `· ${e.hechos} de ${e.total} perfiles`; } });
    body.innerHTML = renderComparacion(c);
  } catch (err) { body.innerHTML = `<div class="vcard">${err.message}</div>`; }
}
function renderComparacion(c) {
  const lead = c.real.indexOf(Math.max(...c.real)), op = c.opciones[lead];
  let h = `<div class="vcard"><small>${c.cis.texto} · CIS ${c.cis.estudio} (${c.cis.fecha}) · ${fmt(c.n_real)} entrevistas</small>
    <div class="cerr"><div><small>Error de pulso</small><b style="color:#F0442E">±${num(c.error_pulso)} pp</b></div><div><small>Error de un LLM sin datos</small><b style="color:#5A6075">±${num(c.error_llm_solo)} pp</b></div></div></div>`;
  h += `<div class="vcard"><small>Reparto de respuestas</small>${c.opciones.map((o, i) => `<div class="copt">${o}</div>` +
    CSER.map(([n, col, k]) => `<div class="cbar"><span>${n}</span><div><i style="width:${c[k][i]}%;background:${col}"></i></div><b>${num(c[k][i])} %</b></div>`).join("")).join("")}</div>`;
  const E = Object.keys(c.edad), S = 300, Hh = 170, m = 32, X = i => m + i * (S - 2 * m) / (E.length - 1);
  const vals = E.flatMap(e => CSER.map(([, , k]) => c.edad[e][k] ? c.edad[e][k][lead] : null)).filter(v => v != null), lo = Math.max(0, Math.min(...vals) - 5), hi = Math.min(100, Math.max(...vals) + 5);
  const Y = v => Hh - 24 - (v - lo) / (hi - lo || 1) * (Hh - 50);
  const lineas = CSER.map(([n, col, k]) => { const pts = E.map((e, i) => c.edad[e][k] ? [X(i), Y(c.edad[e][k][lead])] : null).filter(Boolean);
    return `<polyline points="${pts.map(p => p.join(",")).join(" ")}" fill="none" stroke="${col}" stroke-width="2.5" ${k === "llm_solo" ? 'stroke-dasharray="5 4"' : ""}/>` + pts.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="3.5" fill="${col}"/>`).join(""); }).join("");
  const ejes = E.map((e, i) => `<text x="${X(i)}" y="${Hh - 6}" font-size="9.5" text-anchor="middle" fill="#5A6075" font-family="JetBrains Mono, monospace">${e}</text>`).join("");
  const ley = CSER.map(([n, col], i) => `<circle cx="${m + i * 92}" cy="10" r="4" fill="${col}"/><text x="${m + 8 + i * 92}" y="13" font-size="10" fill="#1A1F3A" font-family="Space Grotesk, sans-serif">${n}</text>`).join("");
  const ry = E.map(e => c.edad[e].real ? c.edad[e].real[lead] : 0), ly = E.map(e => c.edad[e].llm_solo ? c.edad[e].llm_solo[lead] : 0);
  const tendencia = a => a[a.length - 1] - a[0] > 3 ? "sube con la edad" : a[0] - a[a.length - 1] > 3 ? "baja con la edad" : "es parecido en todas las edades";
  h += `<div class="vcard"><small>«${op}» por edad · ¿estereotipos?</small>
    <svg width="100%" viewBox="0 0 ${S} ${Hh}" style="max-width:440px;display:block;margin:auto" role="img" aria-label="Comparación por edad">${ley}${lineas}${ejes}</svg>
    <div>En la realidad, «${op}» <b>${tendencia(ry)}</b>. Un LLM sin datos cree que <b>${tendencia(ly)}</b>${tendencia(ry) !== tendencia(ly) ? ": es un estereotipo" : ""}. pulso sigue al CIS porque cada persona sintética lleva actitudes medidas en encuestas reales.</div></div>`;
  return h;
}
$("#compClose").onclick = () => closePanels();

/* ================= la encuesta ================= */
const MODOS = { evidencia: "Respuestas reales del CIS", analogia: "Simulación anclada en una pregunta CIS parecida", simulacion: "Simulación sin pregunta CIS equivalente" };
let voting = false, voteSoundT = 0;
function setSteps(i) { $("#steps").querySelectorAll(":scope > div").forEach((d, j) => { d.classList.toggle("done", j < i); d.classList.toggle("on", j === i); }); }
function tickVote(p, i) { const c = hex2(optColor(p.ans)); if (i % 9 === 0) rings.push({ p, c, t: performance.now() / 1000 });
  const now = performance.now(); if (now - voteSoundT > 45) { voteSoundT = now; tone(NOTES[p.ans % NOTES.length] * (p.per.sexo === "F" ? 2 : 1.5), .06, .016, "triangle"); } }
async function esperar(job, onProg) {
  const t0 = Date.now();
  while (true) {
    await new Promise(r => setTimeout(r, 400));
    const r = await fetch(`/api/progreso/${job}`); if (!r.ok) throw new Error("Se perdió la consulta en el servidor.");
    const e = await r.json(); onProg(e);
    if (e.fase === "listo") return e.resultado;
    if (e.fase === "error") throw new Error(e.error || "Error en el motor.");
    if (Date.now() - t0 > 10 * 60 * 1000) throw new Error("La consulta tardó demasiado.");
  }
}
function viewReply(v) { const f = facts(), o = shortOpt(D.lead);
  if (v === "sex") return `${o}: mujeres <b>${pct(f.F)}</b>, hombres <b>${pct(f.M)}</b>. Diferencia de ${pp(f.F - f.M)}.`;
  if (v === "age") return `${o}: ${f.ageY.a} años <b>${pct(f.ageY.v)}</b> frente a ${f.ageO.a} años <b>${pct(f.ageO.v)}</b>. Brecha de ${pp(f.ageY.v - f.ageO.v)}.`;
  if (v === "map") return `Más alto en <b>${f.regHi.r.name}</b> (${pct(f.regHi.v)}), más bajo en ${f.regLo.r.name} (${pct(f.regLo.v)}). Pasa el cursor por el mapa para conocer a cada persona.`;
  if (v === "grp") return insightFor("grp").replace(/<small>.*?<\/small>/, "") + " Cambien la dimensión arriba a la derecha: ideología, estudios, trabajo, renta, vivienda, vivir solo, uso de IA o municipio.";
  return `En total, ${o} gana con <b>${pct(D.share[D.lead])}</b>.`; }

/* grupo mencionado en la pregunta («los jóvenes», «las mujeres»…): se aplica como filtro */
function filtroDePregunta(q) {
  const s = q.toLowerCase(), f = {};
  if (/j[oó]venes|juventud/.test(s)) Object.assign(f, { aMin: 18, aMax: 29, texto: "18 a 29 años" });
  else if (/mayores|jubilad|tercera edad/.test(s)) Object.assign(f, { aMin: 65, aMax: 90, texto: "65 años o más" });
  if (/\bmujeres\b/.test(s) && !/\bhombres\b/.test(s)) { f.sex = "F"; f.texto = [f.texto, "mujeres"].filter(Boolean).join(", "); }
  else if (/\bhombres\b/.test(s) && !/\bmujeres\b/.test(s)) { f.sex = "M"; f.texto = [f.texto, "hombres"].filter(Boolean).join(", "); }
  return f.texto ? f : null;
}
function aplicarFiltro(f) {
  if (f.aMin) { $("#aMin").value = f.aMin; $("#aMax").value = f.aMax; syncAge(); }
  if (f.sex) { F.sex = f.sex; segOn($("#fSex"), $(`#fSex [data-v="${f.sex}"]`)); }
  applyFilter();
}
async function ask(q, opciones = null, fromPanel = false, extra = null) {
  q = q.trim(); if (busy || !q) return;
  extra = extra || interpretarEntrada(q);
  audio();
  // órdenes de seguimiento sobre el resultado actual
  const s = q.toLowerCase();
  if (D && !fromPanel && !opciones && !extra) { let v = null;
    if (/^ver por sexo|^por sexo|hombres y mujeres|g[eé]nero$/.test(s)) v = "sex"; else if (/^ver por edad|^por edad/.test(s)) v = "age"; else if (/^ver por comunidad|^por comunidad|^mapa/.test(s)) v = "map"; else if (/^ver total|^total$/.test(s)) v = "hemi"; else if (/^ver por grupos|^por grupos|ideolog|renta|estudios/.test(s)) v = "grp";
    if (v) { addUser(q); switchView(v); await sleep(350); await streamBot(viewReply(v)); followChips(); return; } }
  busy = true; $("#send").disabled = $("#launch").disabled = true; closePanels();
  if (MODE === "home") await toApp();
  addUser(q); $("#sugg").innerHTML = "";
  // reinicio visual
  RES = null; D = null; LIVE = null; labelA = 0; P.forEach(p => { p.voted = false; });
  if (!fromPanel) { F.reg = "all"; $("#fReg").value = "all"; F.sex = "all"; segOn($("#fSex"), $('#fSex [data-v="all"]')); $("#aMin").value = 18; $("#aMax").value = 90; syncAge(); }
  $("#res").classList.add("wait"); $("#big").textContent = "--"; $("#bigL").textContent = "Esperando respuestas"; $("#stack").innerHTML = ""; $("#legend").innerHTML = "";
  $("#sema").dataset.l = 0; $("#semaT").textContent = "Confianza"; $("#moe").textContent = "±-- pp · n = --"; $("#spark").innerHTML = "";
  $("#insight").innerHTML = `<small>Lectura rápida</small>Las diferencias entre grupos aparecerán aquí.`;
  $("#qt").textContent = q; $("#eyT").textContent = "Analizando"; $("#stProg").textContent = "";
  $("#steps").style.opacity = 1; setSteps(0);
  layout("cloud"); whoosh(false);
  const th = addBot(`<span class="typing"><span></span><span></span><span></span></span>`);
  let res;
  try {
    if (ESTATICO) { res = await preguntarEstatico(q, extra); }
    else {
    const r = await fetch("/api/preguntar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pregunta: q, opciones: extra && extra.tipo === "ab" ? null : opciones, tipo: extra ? extra.tipo : "pregunta", mensajes: extra ? extra.mensajes : null }) });
    if (!r.ok) throw new Error(r.status === 422 ? "La pregunta es demasiado corta o larga." : "El motor no aceptó la pregunta.");
    const { job } = await r.json();
    const tMin = performance.now() + (RM ? 0 : 1600); // la nube gira al menos un momento
    res = await esperar(job, e => {
      const step = { en_cola: 0, interpretando: 0, convocando: 1, respondiendo: 2, confianza: 3, listo: 3 }[e.fase] ?? 0;
      setSteps(Math.min(step, 2)); // la votación visual empieza cuando llegan los datos
      if (e.fase === "respondiendo" && e.total > 1) $("#stProg").textContent = ` · ${e.hechos} de ${e.total} perfiles`;
      if (e.fase === "confianza") $("#stProg").textContent = " · listo";
    });
    const wait = tMin - performance.now(); if (wait > 0) await sleep(wait);
    }
  } catch (err) {
    th.closest(".msg").remove();
    if (err.message === "NO_PREPARADA") {
      const n = (await indice()).length;
      await streamBot(`Esta versión publicada responde al momento a <b>${n} preguntas y campañas</b> ya calculadas con el motor de pulso, y la tuya todavía no está entre ellas. Estas son las más parecidas:`);
      $("#steps").style.opacity = 0; layout("map", false); $("#eyT").textContent = "Tema";
      busy = false; $("#send").disabled = $("#launch").disabled = false;
      chips(err.sugerencias.map(e => [e.pregunta.length > 70 ? e.pregunta.slice(0, 68) + "…" : e.pregunta, () => ask(e.pregunta, null, false, e.tipo === "pregunta" ? null : { tipo: e.tipo, mensajes: e.mensajes })]));
      return;
    }
    await streamBot(`No he podido completar la consulta. ${err.message === "Failed to fetch" ? "El motor local no responde: comprueben que el servidor está en marcha." : err.message}`, null, "err");
    $("#steps").style.opacity = 0; layout("map", false); $("#eyT").textContent = "Tema";
    busy = false; $("#send").disabled = $("#launch").disabled = false; exampleChips(); return;
  }
  th.closest(".msg").remove();
  // llegan los datos: cada punto pasa a ser una persona sintética concreta
  RES = res; P.forEach((p, i) => p.per = RES.personas[i]); placePeople(); applyFilter(); assignAnswers();
  $("#eyT").textContent = (RES.tipo === "ab" ? "Test A/B · " : RES.tipo === "campana" ? "Campaña · " : "") + RES.tema; $("#qt").textContent = RES.pregunta;
  if (RES.tipo === "ab") { setTipo("ab"); $("#cq").value = RES.mensajes[0]; $("#cq2").value = RES.mensajes[1]; }
  else if (RES.tipo === "campana") { setTipo("campana"); $("#cq").value = RES.mensajes[0]; }
  else { setTipo("pregunta"); $("#cq").value = RES.pregunta; } curTopic = RES.tema; $("#topicAuto").textContent = "detectado automáticamente"; renderTopics();
  OPTS = RES.opciones.slice(); renderOpts(); renderYears(RES.anios_disponibles);
  if (RES._aproximada) await streamBot(`<span class="note">Respondo a la pregunta preparada más parecida: «${RES.pregunta}».</span>`);
  await streamBot(`<span class="note">${MODOS[RES.modo]}${RES.referencia ? ` · CIS ${RES.referencia.estudio} (${RES.referencia.fecha}): «${RES.referencia.texto}»` : ""}</span>`);
  // 2. convocar
  setSteps(1); layout(VIEW, false); whoosh(true);
  await sleep(1300);
  // 3. votar
  setSteps(2); $("#stProg").textContent = ""; $("#count").style.opacity = 1; voting = true;
  const order = P.slice().sort(() => Math.random() - .5), D_MS = RM ? 100 : 3400, t0 = performance.now();
  await new Promise(done => { let i = 0, lastUI = 0; const step = now => { const k = clamp((now - t0) / D_MS, 0, 1), e = k * k * (3 - 2 * k) * .35 + k * k * .65, upto = Math.floor(e * N);
      for (; i < upto; i++) { const p = order[i]; p.voted = true; p.pop = 1; tickVote(p, i); }
      const act = P.filter(p => p.active).length, shown = order.slice(0, upto).filter(p => p.active).length;
      $("#cPct").textContent = pct(upto / N); $("#cN").textContent = `${fmt(shown)} de ${fmt(act)} respuestas`; $("#cBar").style.width = (upto / N * 100) + "%";
      if (now - lastUI > 120) { lastUI = now; LIVE = liveStats(); if (LIVE.n) renderResults(false); }
      if (k < 1) requestAnimationFrame(step); else done(); }; requestAnimationFrame(step); });
  voting = false;
  // 4. confianza
  setSteps(3); await sleep(650); setSteps(4);
  const auto = filtroDePregunta(q); if (auto) aplicarFiltro(auto);
  D = displayStats(); layout(VIEW, true); renderResults(true); renderDims(); chord();
  await sleep(500); $("#count").style.opacity = 0; $("#steps").style.opacity = 0;
  // respuesta en el chat
  const f = facts(), lead = D.lead, voz = RES.voces && RES.voces[lead], cand = P.filter(p => p.ans === lead && p.active),
    quien = cand.length ? cand[Math.floor(rng([...q].reduce((a, c) => a * 31 + c.charCodeAt(0) | 0, 7))() * cand.length)] : null;
  await streamBot(`<b>${pct(D.share[lead])}</b> responde «${RES.opciones[lead]}». ` +
    (f.regHi ? `Donde más, ${f.regHi.r.name} (<b>${pct(f.regHi.v)}</b>); donde menos, ${f.regLo.r.name} (${pct(f.regLo.v)}). ` : "") +
    (f.ageHi && !f.unaEdad ? `Por edad, el máximo está en ${f.ageHi.a} años (${pct(f.ageHi.v)}).` : "") +
    (voz && quien ? `<div class="quote">«${voz[0]}»<small>${quien.name}, ${quien.per.edad} · ${(REG[RI[quien.per.ccaa]] || {}).name || ""} · persona sintética</small></div>` : "") +
    (RES.factores && RES.factores.length ? `<div class="factores"><small>Lo que más se asocia</small>${RES.factores.map(f => `<div><i style="background:${f.dif_pp > 0 ? "#F0442E" : "#3E7CB1"}"></i>${f.texto}</div>`).join("")}</div>` : "") +
    (RES.actitudes_usadas && RES.actitudes_usadas.length ? `<span class="note">Perfiles condicionados con sus actitudes CIS sobre: ${RES.actitudes_usadas.join(", ")}.</span>` : "") +
    (auto ? `<span class="note">Filtro aplicado según la pregunta: ${auto.texto}. Pueden cambiarlo en «Diseña tu encuesta».</span>` : "") +
    `<span class="note">${RES.confianza.texto}</span>`);
  followChips();
  busy = false; $("#send").disabled = $("#launch").disabled = false;
}

/* ================= entrada ================= */
$("#ask").addEventListener("submit", e => { e.preventDefault(); const v = $("#q").value; if (!v.trim()) return; $("#q").value = ""; $("#q").style.height = ""; ask(v); });
$("#q").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask").requestSubmit(); } });
$("#q").addEventListener("input", () => { const q = $("#q"); q.style.height = "auto"; q.style.height = Math.min(120, q.scrollHeight) + "px"; });

/* ================= arranque ================= */
if (innerWidth < 600) $("#q").placeholder = "Pregunta algo sobre España…";
resize(); renderTopics(); renderOpts(); syncAge(); renderYears([]);
exampleChips("#homeChips");
requestAnimationFrame(frame);
(async () => { await sleep(300); await streamBot(`Hola. Soy <b>pulso</b>. Cada punto es una persona sintética de la España real, con actitudes estimadas a partir de encuestas del CIS.`); })();
