/* Vista 3D de partículas: cada punto es una porción igual de dinero.
   Lee los datos de un <script type="application/json"> indicado en data-escena3d.
   Formas: Moneda (reparto como una moneda acuñada), Esferas (una por grupo) y Bloques (cadena de bloques). */
(function () {
  "use strict";
  var el = document.querySelector("[data-escena3d]");
  if (!el) return;
  var datos;
  try { datos = JSON.parse(document.getElementById(el.getAttribute("data-escena3d")).textContent); } catch (e) { return; }

  var TAU = Math.PI * 2, MAXN = 24000, CAM = 26, LX = -0.5, LY = 0.62, LZ = -0.6, INV = 1 / 127;
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function hex(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
  function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function redondo(raw) { var e = Math.pow(10, Math.floor(Math.log10(raw))), best = e, bd = 9; [1, 2, 2.5, 5, 10].forEach(function (m) { var d = Math.abs(Math.log(m * e / raw)); if (d < bd) { bd = d; best = m * e; } }); return best; }
  function num(n, d) { var s = Math.abs(n).toFixed(d).split("."), i = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, "."); return (n < 0 ? "−" : "") + i + (s[1] ? "," + s[1] : ""); }
  function usd(cent, d) { return "US$ " + num(cent / 100, d == null ? 2 : d); }

  var F = function (n) { return new Float32Array(n); };
  var px = F(MAXN), py = F(MAXN), pz = F(MAXN), tx = F(MAXN), ty = F(MAXN), tz = F(MAXN), u1 = F(MAXN), u2 = F(MAXN), u3 = F(MAXN), u4 = F(MAXN), g1 = F(MAXN), g2 = F(MAXN);
  var nx = new Int8Array(MAXN), ny = new Int8Array(MAXN), nz = new Int8Array(MAXN), gOf = new Uint8Array(MAXN), cr = new Uint8Array(MAXN), cg = new Uint8Array(MAXN), cb = new Uint8Array(MAXN), ph = new Uint16Array(MAXN), LUT = F(1024);
  var AX = F(48), AY = F(48), AZ = F(48);
  var rnd = mulberry32(977);
  for (var i = 0; i < MAXN; i++) { u1[i] = rnd(); u2[i] = rnd(); u3[i] = rnd(); u4[i] = rnd(); ph[i] = (rnd() * 1024) | 0; var a0 = 0; while (a0 === 0) a0 = rnd(); var m0 = Math.sqrt(-2 * Math.log(a0)), t0 = TAU * rnd(); g1[i] = m0 * Math.cos(t0); g2[i] = m0 * Math.sin(t0); }
  for (i = 0; i < 1024; i++) LUT[i] = Math.sin(i / 1024 * TAU);

  var cv = el.querySelector(".c-pts"), cG = el.querySelector(".c-glow"), cO = el.querySelector(".c-ovl"), cP = document.createElement("canvas");
  var ctx = cv.getContext("2d"), ctxP = cP.getContext("2d"), ctxG = cG.getContext("2d"), ctxO = cO.getContext("2d");
  var still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var deco = el.classList.contains("decorativo"), heroe = el.classList.contains("heroe"), claro = deco || heroe;
  var VIS = { moneda: [0.3, 0.9, 1], esferas: [0.5, 0.36, 1.28], bloques: [0.7, 0.52, 1.02], orbitas: [0.4, 0.5, 1.3] };
  var NOM = { moneda: "Moneda", esferas: "Esferas", bloques: "Bloques", orbitas: "Órbitas" };
  var OW = F(48), OC = F(48), OS = F(48), orbT = 0, ciclo = 0, tocado = false;
  var G = [], N = 0, total = 0, form = "moneda", sel = -1, W = 0, H = 0, BS = 1, BW = 0, BH = 0, img, d8, d32;
  var yaw = 0.3, pitch = 0.9, zoom = 1, tyaw = 0.3, tpitch = 0.9, tzoom = 1, ease = false, spin = 0, mov = 0, prev = 0, reloj = 0, first = true, unidadTxt = "", drag = null, pinch = 0;
  var lab = [], ptrs = new Map();

  function resize() {
    var w = el.clientWidth; if (!w) return;
    W = w; H = Math.round(heroe ? clamp(w * 0.56, 330, 500) : clamp(w * 0.8, 290, 470)); BS = Math.min(window.devicePixelRatio || 1, 2); BW = Math.round(W * BS); BH = Math.round(H * BS);
    [cv, cO, cP].forEach(function (c) { c.width = BW; c.height = BH; }); cv.style.height = H + "px"; cO.style.height = H + "px";
    cG.width = Math.max(2, BW >> 2); cG.height = Math.max(2, BH >> 2);
    img = ctxP.createImageData(BW, BH); d8 = img.data; d32 = new Uint32Array(d8.buffer);
  }

  function nor(i, x, y, z) { nx[i] = x * 127; ny[i] = y * 127; nz[i] = z * 127; }
  function anc(k, x, y, z) { AX[k] = x; AY[k] = y; AZ[k] = z; }
  function dir(i) { var ct = 2 * u1[i] - 1, st = Math.sqrt(1 - ct * ct), a = TAU * u2[i]; return [st * Math.cos(a), ct, st * Math.sin(a)]; }

  function objetivos() {
    nx.fill(0); ny.fill(0); nz.fill(0); if (!N) return;
    var n = G.length, k, i, j;
    if (form === "moneda") {
      var Rm = 5, Th = 0.9, A0 = -Math.PI / 2 - Math.PI * G[0].cnt / N;
      G.forEach(function (g, k) {
        var span = TAU * g.cnt / N, gap = Math.min(0.01, span * 0.15);
        for (var j = 0; j < g.cnt; j++) {
          var i = g.start + j, th = A0 + gap + (j + u1[i]) / g.cnt * (span - 2 * gap), ct = Math.cos(th), st = Math.sin(th), q;
          if (ph[i] < 760) { q = Rm * Math.sqrt(u3[i]); tx[i] = q * ct; tz[i] = q * st; ty[i] = Th / 2 + (q > 4.5 ? 0.14 : q < 1.1 ? 0.1 : 0) + g1[i] * 0.012; nor(i, 0, 1, 0); }
          else { q = Rm + 0.07 * Math.sin(th * 72); tx[i] = q * ct; tz[i] = q * st; ty[i] = (u3[i] - 0.5) * Th; nor(i, ct, 0, st); }
        }
        var mid = A0 + span / 2, ancho = span > 0.35, rr = ancho ? 3.1 : 5.7 + (k % 3) * 0.45;
        anc(k, rr * Math.cos(mid), ancho ? 0.6 : 0.3 + (k % 2) * 0.45, rr * Math.sin(mid)); A0 += span;
      });
    } else if (form === "esferas") {
      var R = G.map(function (g) { return Math.max(0.3, 0.115 * Math.cbrt(g.cnt)); });
      var P = G.map(function (g, k) { if (k === 0) return [0, 0, 0]; var a = k * 2.39996, d = R[0] + R[k] + 0.4 + 0.1 * k; return [d * Math.cos(a), ((k % 3) - 1) * 0.9, d * Math.sin(a)]; });
      for (var it = 0; it < 240; it++) {
        for (var a = 0; a < n; a++) for (var b = a + 1; b < n; b++) {
          var dx = P[b][0] - P[a][0], dy = P[b][1] - P[a][1], dz = P[b][2] - P[a][2], d = Math.hypot(dx, dy, dz) || 0.001, min = R[a] + R[b] + 0.25;
          if (d < min) { var q = (min - d) / d, fa = a === 0 ? 0 : 0.5, fb = 1 - fa; P[a][0] -= dx * q * fa; P[a][1] -= dy * q * fa; P[a][2] -= dz * q * fa; P[b][0] += dx * q * fb; P[b][1] += dy * q * fb; P[b][2] += dz * q * fb; }
        }
        for (k = 1; k < n; k++) { P[k][0] *= 0.997; P[k][1] *= 0.994; P[k][2] *= 0.997; }
      }
      G.forEach(function (g, k) {
        for (var i = g.start; i < g.start + g.cnt; i++) { var d = dir(i), q = R[k] * Math.pow(u3[i], 0.45); tx[i] = P[k][0] + d[0] * q; ty[i] = P[k][1] + d[1] * q; tz[i] = P[k][2] + d[2] * q; nor(i, d[0], d[1], d[2]); }
        anc(k, P[k][0], P[k][1] + R[k] + 0.35, P[k][2]);
      });
    } else if (form === "orbitas") {
      var R0 = clamp(0.115 * Math.cbrt(G[0].cnt), 0.9, 2.3), paso = n > 1 ? Math.min(0.85, (6.5 - R0 - 0.9) / (n - 1)) : 0;
      OW.fill(0);
      G.forEach(function (g, k) {
        var i;
        if (k === 0) {
          for (i = g.start; i < g.start + g.cnt; i++) { var d = dir(i), q = R0 * Math.pow(u3[i], 0.4); tx[i] = d[0] * q; ty[i] = d[1] * q; tz[i] = d[2] * q; nor(i, d[0], d[1], d[2]); }
          anc(0, 0, R0 + 0.4, 0); return;
        }
        var r = R0 + 0.9 + (k - 1) * paso, inc = ((k % 3) - 1) * 0.16, ancho = clamp(0.012 * Math.sqrt(g.cnt), 0.05, Math.max(0.06, paso * 0.36));
        OW[k] = (k % 2 ? 1 : 0.8) * 0.62 / Math.sqrt(r);
        for (i = g.start; i < g.start + g.cnt; i++) {
          var th = TAU * u1[i], q2 = r + g1[i] * ancho * 0.5, x = q2 * Math.cos(th);
          tx[i] = x; tz[i] = q2 * Math.sin(th); ty[i] = g2[i] * 0.035 + x * inc;
        }
        var a = k * 2.39996; anc(k, r * Math.cos(a), 0.4 + r * Math.cos(a) * inc, r * Math.sin(a));
      });
    } else {
      var side = G.map(function (g) { return Math.max(0.5, 0.15 * Math.cbrt(g.cnt)); });
      var r0 = side[0] / 2 * 1.25 + 0.38 + (side[1] || 0.5) / 2 * 1.25;
      var pt = function (th) { var q = r0 + 0.42 * th; return [q * Math.cos(th), -0.6 + 0.25 * th, q * Math.sin(th)]; };
      var C = [[0, 0, 0]], TH = [0], th = 0;
      for (k = 1; k < n; k++) {
        if (k === 1) { C.push(pt(0)); TH.push(0); continue; }
        var D = side[k - 1] / 2 * 1.2 + 0.36 + side[k] / 2 * 1.2, pv = C[k - 1], q2;
        do { th += 0.01; q2 = pt(th); } while (Math.hypot(q2[0] - pv[0], q2[1] - pv[1], q2[2] - pv[2]) < D && th < 40);
        C.push(q2); TH.push(th);
      }
      G.forEach(function (g, k) {
        var s = side[k], hs = s / 2, c0 = C[k], c1 = k + 1 < n ? C[k + 1] : null, cf = Math.cos(TH[k]), sf = Math.sin(TH[k]);
        for (var i = g.start; i < g.start + g.cnt; i++) {
          var cat = ph[i];
          if (c1 && cat < 52) { var t = u3[i]; tx[i] = c0[0] + (c1[0] - c0[0]) * t + g1[i] * 0.02; ty[i] = c0[1] + (c1[1] - c0[1]) * t + g2[i] * 0.02; tz[i] = c0[2] + (c1[2] - c0[2]) * t; continue; }
          var lx, ly, lz, n0 = 0, n1 = 0, n2 = 0;
          if (cat < 400) { var e = (u1[i] * 12) | 0, ax = e >> 2, aa = e & 1 ? hs : -hs, bb = e & 2 ? hs : -hs, tt = (u2[i] - 0.5) * s; if (ax === 0) { lx = tt; ly = aa; lz = bb; } else if (ax === 1) { lx = aa; ly = tt; lz = bb; } else { lx = aa; ly = bb; lz = tt; } }
          else { var f = (u1[i] * 6) | 0, ax2 = f >> 1, sg = f & 1 ? 1 : -1, p = (u2[i] - 0.5) * s, q3 = (u3[i] - 0.5) * s; if (ax2 === 0) { lx = sg * hs; ly = p; lz = q3; n0 = sg; } else if (ax2 === 1) { lx = p; ly = sg * hs; lz = q3; n1 = sg; } else { lx = p; ly = q3; lz = sg * hs; n2 = sg; } }
          tx[i] = c0[0] + lx * cf - lz * sf; ty[i] = c0[1] + ly; tz[i] = c0[2] + lx * sf + lz * cf; nor(i, n0 * cf - n2 * sf, n1, n0 * sf + n2 * cf);
        }
        anc(k, c0[0], c0[1] + hs + 0.35, c0[2]);
      });
    }
    if (first) { for (i = 0; i < N; i++) { var d0 = dir(i), q0 = 8 + 7 * u3[i]; px[i] = d0[0] * q0; py[i] = d0[1] * q0 * 0.6; pz[i] = d0[2] * q0; } first = false; }
  }
  function pintar() { G.forEach(function (g) { for (var i = g.start; i < g.start + g.cnt; i++) { var k = 0.45 + 0.55 * u4[i]; cr[i] = g.rgb[0] * k; cg[i] = g.rgb[1] * k; cb[i] = g.rgb[2] * k; } }); }
  function controles() {
    el.querySelector(".hud b").textContent = datos.titulo || "";
    el.querySelector(".hud span").textContent = N ? num(N, 0) + " puntos · 1 ≈ " + unidadTxt : "sin posiciones";
    var box = el.querySelector(".s3ctl"); box.textContent = "";
    Object.keys(NOM).forEach(function (f) {
      var b = document.createElement("button"); b.type = "button"; b.textContent = NOM[f]; b.setAttribute("aria-pressed", f === form ? "true" : "false");
      b.addEventListener("click", function () { tocado = true; cambiarForma(f); }); box.appendChild(b);
    });
  }
  function cargar(grupos) {
    total = grupos.reduce(function (s, g) { return s + g.value; }, 0);
    var unit = total > 0 ? Math.max(1, redondo(total / 14000)) : 1, n = 0;
    G = grupos.filter(function (g) { return g.value > 0; }).sort(function (a, b) { return b.value - a.value; }).slice(0, 40);
    G.forEach(function (g, k) { g.rgb = hex(g.col); g.cnt = Math.min(MAXN - n, Math.max(3, Math.round(g.value / unit))); g.start = n; for (var i = n; i < n + g.cnt; i++) gOf[i] = k; n += g.cnt; });
    N = n; sel = -1; unidadTxt = usd(unit, unit >= 100 ? 0 : 2); objetivos(); pintar(); mov = performance.now(); controles();
  }
  function asentar() {  // al salir de Órbitas, deja cada punto donde se lo estaba viendo
    for (var i = 0; i < N; i++) { var k = gOf[i]; if (!OW[k]) continue; var c = Math.cos(OW[k] * orbT), s = Math.sin(OW[k] * orbT), x = px[i], z = pz[i]; px[i] = x * c - z * s; pz[i] = x * s + z * c; }
  }
  function cambiarForma(f) {
    if (form === "orbitas") asentar();
    orbT = 0; form = f; var v = VIS[f], y = v[0];
    while (y - yaw > Math.PI) y -= TAU; while (yaw - y > Math.PI) y += TAU;
    tyaw = y; tpitch = v[1]; tzoom = v[2]; ease = true; spin = 0; objetivos(); mov = performance.now(); controles();
  }
  function escala() { return Math.min(W / 2 / 7, H / 2 / 5.2) * zoom * (heroe && W > 600 ? 1.12 : 1); }
  function rect(x, y, w, h, r) { ctxO.beginPath(); ctxO.moveTo(x + r, y); ctxO.arcTo(x + w, y, x + w, y + h, r); ctxO.arcTo(x + w, y + h, x, y + h, r); ctxO.arcTo(x, y + h, x, y, r); ctxO.arcTo(x, y, x + w, y, r); ctxO.closePath(); }

  function dibujar(now) {
    var cyw = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), S = escala() * BS, cx = BW / 2, cy = BH / 2;
    var t1 = (reloj * 60) | 0, t2 = (reloj * 47) | 0, t3 = (reloj * 150) | 0;
    d32.fill(0);
    var orb = form === "orbitas";
    if (orb) for (var ko = 0; ko < G.length; ko++) { OC[ko] = Math.cos(OW[ko] * orbT); OS[ko] = Math.sin(OW[ko] * orbT); }
    for (var i = 0; i < N; i++) {
      var p = ph[i], x = px[i] + 0.045 * LUT[(p + t1) & 1023], y = py[i] + 0.045 * LUT[(p * 3 + t2) & 1023], z = pz[i];
      if (orb) { var go = gOf[i]; if (OW[go]) { var xo = x; x = xo * OC[go] - z * OS[go]; z = xo * OS[go] + z * OC[go]; } }
      var X = x * cyw + z * syw, Z0 = -x * syw + z * cyw, d = CAM + (-y * sp + Z0 * cp);
      if (d < 3) continue;
      var s = S * CAM / d, sx = (cx + X * s) | 0, sy = (cy - (y * cp + Z0 * sp) * s) | 0, n = (BS * (heroe ? 1.5 : 1.15) * CAM / d + 0.5) | 0;
      if (n < 1) n = 1; else if (n > 4) n = 4;
      if (sx < 0 || sy < 0 || sx > BW - n || sy > BH - n) continue;
      var a = (heroe ? 0.95 : 0.62) * (d > CAM ? Math.max(0.35, 1 - (d - CAM) * 0.045) : 1) * (0.86 + 0.2 * LUT[(p * 7 + t3) & 1023]);
      var n0 = nx[i], n1 = ny[i], n2 = nz[i];
      if (n0 !== 0 || n1 !== 0 || n2 !== 0) { var a1 = n0 * cyw + n2 * syw, b0 = -n0 * syw + n2 * cyw, dl = (a1 * LX + (n1 * cp + b0 * sp) * LY + (-n1 * sp + b0 * cp) * LZ) * INV; a *= dl > 0 ? 0.42 + 0.9 * dl : 0.42 + 0.22 * dl; }
      if (sel >= 0) a *= gOf[i] === sel ? 1.45 : 0.25;
      var rr = cr[i] * a, gg = cg[i] * a, bb = cb[i] * a;
      for (var yy = 0; yy < n; yy++) {
        var k = ((sy + yy) * BW + sx) << 2;
        for (var xx = 0; xx < n; xx++) { var R0 = d8[k], G0 = d8[k + 1], B0 = d8[k + 2], f = 1; if (R0 + rr > 255) f = (255 - R0) / rr; if (G0 + gg * f > 255) f = (255 - G0) / gg; if (B0 + bb * f > 255) f = (255 - B0) / bb; d8[k] = R0 + rr * f; d8[k + 1] = G0 + gg * f; d8[k + 2] = B0 + bb * f; d8[k + 3] = 255; k += 4; }
      }
    }
    ctxP.putImageData(img, 0, 0);
    if (claro) ctx.clearRect(0, 0, BW, BH);
    else { ctx.fillStyle = !still && now - mov < 2600 ? "rgba(8,12,21,0.3)" : "#080C15"; ctx.fillRect(0, 0, BW, BH); }
    ctx.drawImage(cP, 0, 0);
    ctxG.clearRect(0, 0, cG.width, cG.height); ctxG.drawImage(cv, 0, 0, cG.width, cG.height);

    var So = escala();
    var P = function (x, y, z) { var X = x * cyw + z * syw, Z0 = -x * syw + z * cyw, d = CAM + (-y * sp + Z0 * cp), s = So * CAM / Math.max(4, d); return { x: W / 2 + X * s, y: H / 2 - (y * cp + Z0 * sp) * s, d: d }; };
    ctxO.setTransform(BS, 0, 0, BS, 0, 0); ctxO.clearRect(0, 0, W, H); ctxO.textBaseline = "middle"; ctxO.lineJoin = "round";
    ctxO.strokeStyle = "rgba(138,150,173,.14)"; ctxO.lineWidth = 1; ctxO.beginPath();
    for (var q = 2.5; q <= 7.6; q += 2.5) for (var kk = 0; kk <= 48; kk++) { var an = kk / 48 * TAU, w = P(q * Math.cos(an), -4.1, q * Math.sin(an)); if (kk === 0) ctxO.moveTo(w.x, w.y); else ctxO.lineTo(w.x, w.y); }
    ctxO.stroke();
    if (deco) return;
    var fuente = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', mono = 'ui-monospace, Menlo, Consolas, monospace';
    if (!N) { ctxO.font = "600 14px " + fuente; ctxO.textAlign = "center"; ctxO.fillStyle = "#8A96AD"; ctxO.fillText("Todavía no hay dinero invertido", W / 2, H / 2); return; }
    lab.length = 0; var rects = [];
    if (sel >= 0) {
      var g = G[sel], qa = P(AX[sel], AY[sel], AZ[sel]), l1 = g.label, l2 = usd(g.value), l3 = num(g.value / total * 100, 1) + "% del total";
      ctxO.font = "600 12px " + fuente; var w1 = ctxO.measureText(l1).width; ctxO.font = "500 15px " + mono; var w2 = ctxO.measureText(l2).width;
      var bw = Math.min(W - 12, Math.max(w1, w2, 96) + 22), bh = 62, bx = clamp(qa.x + 26, 6, W - bw - 6), by = clamp(qa.y - bh - 30, 46, H - bh - 54);
      ctxO.strokeStyle = "#7C95FF"; ctxO.lineWidth = 1.2; ctxO.beginPath(); ctxO.arc(qa.x, qa.y, 6, 0, TAU); ctxO.stroke();
      ctxO.beginPath(); ctxO.moveTo(qa.x + 4, qa.y - 4); ctxO.lineTo(clamp(qa.x + 26, bx + 8, bx + bw - 8), by + bh); ctxO.stroke();
      rect(bx, by, bw, bh, 9); ctxO.fillStyle = "rgba(13,18,30,.94)"; ctxO.fill(); ctxO.stroke();
      ctxO.textAlign = "left"; ctxO.fillStyle = "#E8ECF5"; ctxO.font = "600 12px " + fuente; ctxO.fillText(l1, bx + 11, by + 15, bw - 22);
      ctxO.font = "500 15px " + mono; ctxO.fillText(l2, bx + 11, by + 33, bw - 22);
      ctxO.font = "500 11px " + mono; ctxO.fillStyle = "#8A96AD"; ctxO.fillText(l3, bx + 11, by + 49, bw - 22);
      rects.push([bx, by, bx + bw, by + bh]);
    }
    ctxO.font = "600 11px " + fuente;
    for (var k2 = 0; k2 < G.length && rects.length < 12; k2++) {
      if (k2 === sel) continue;
      var qb = P(AX[k2], AY[k2], AZ[k2]), tx2 = G[k2].label.length > 16 ? G[k2].label.slice(0, 15) + "…" : G[k2].label, tw = ctxO.measureText(tx2).width, lx2 = clamp(qb.x + 4, 4, W - 4 - tw), ly2 = qb.y;
      if (ly2 < 46 || ly2 > H - 50 || qb.x < -6 || qb.x > W + 6) continue;
      var rc = [lx2 - 4, ly2 - 8, lx2 + tw + 4, ly2 + 8];
      if (rects.some(function (o) { return rc[0] < o[2] && rc[2] > o[0] && rc[1] < o[3] && rc[3] > o[1]; })) continue;
      rects.push(rc); lab.push({ k: k2, x: lx2 + tw / 2, y: ly2 });
      ctxO.globalAlpha = sel >= 0 ? 0.5 : 1; ctxO.textAlign = "left"; ctxO.lineWidth = 3; ctxO.strokeStyle = "rgba(10,14,23,.85)"; ctxO.strokeText(tx2, lx2, ly2); ctxO.fillStyle = "rgba(232,236,245,.95)"; ctxO.fillText(tx2, lx2, ly2);
    }
    ctxO.globalAlpha = 1;
  }
  function elegir(x, y) {
    var best = -1, bd = 24;
    lab.forEach(function (q) { var d = Math.hypot(q.x - x, q.y - y); if (d < bd) { bd = d; best = q.k; } });
    if (best >= 0) return best;
    var cyw = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), So = escala(), b = -1, dm = 16 * 16;
    for (var i = 0; i < N; i++) {
      var x0 = px[i], z0 = pz[i], go = gOf[i];
      if (form === "orbitas" && OW[go]) { x0 = px[i] * OC[go] - pz[i] * OS[go]; z0 = px[i] * OS[go] + pz[i] * OC[go]; }
      var X = x0 * cyw + z0 * syw, Z0 = -x0 * syw + z0 * cyw, d = CAM + (-py[i] * sp + Z0 * cp); if (d < 3) continue;
      var s = So * CAM / d, dx = W / 2 + X * s - x, dy = H / 2 - (py[i] * cp + Z0 * sp) * s - y, q = dx * dx + dy * dy;
      if (q < dm) { dm = q; b = i; }
    }
    return b >= 0 ? gOf[b] : -1;
  }
  function cuadro(t) {
    requestAnimationFrame(cuadro);
    var dt = Math.min(0.05, (t - prev) / 1000 || 0); prev = t;
    if (document.hidden || !W || !visible) return;
    if (!still) { reloj += dt; if (form === "orbitas") orbT += dt; }
    if (!ciclo) ciclo = t;
    if ((deco || el.hasAttribute("data-ciclo")) && !still && !tocado && t - ciclo > 9000) { var fs = Object.keys(NOM); ciclo = t; cambiarForma(fs[(fs.indexOf(form) + 1) % fs.length]); }
    var kb = dt * 2.6;
    for (var i = 0; i < N; i++) { var k = Math.min(1, kb * (0.5 + u4[i] * 1.5)); px[i] += (tx[i] - px[i]) * k; py[i] += (ty[i] - py[i]) * k; pz[i] += (tz[i] - pz[i]) * k; }
    if (ease) { var ke = Math.min(1, dt * 2.6); yaw += (tyaw - yaw) * ke; pitch += (tpitch - pitch) * ke; zoom += (tzoom - zoom) * ke; if (Math.abs(tyaw - yaw) + Math.abs(tpitch - pitch) + Math.abs(tzoom - zoom) < 0.004) ease = false; }
    else if (!drag && Math.abs(spin) > 0.04) { yaw += spin * dt; spin *= Math.exp(-dt * 2.4); }
    else if (!still && !drag) yaw -= dt * 0.085;
    try { dibujar(t); } catch (e) { if (!cuadro.aviso) { cuadro.aviso = true; console.error(e); } }
  }
  cO.addEventListener("pointerdown", function (e) {
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY }); try { cO.setPointerCapture(e.pointerId); } catch (_) {}
    tocado = true;
    if (ptrs.size === 1) { drag = { x: e.clientX, y: e.clientY, mv: 0, t: performance.now() }; spin = 0; }
    else if (ptrs.size === 2) { var a = Array.from(ptrs.values()); pinch = Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y); if (drag) drag.mv = 99; }
  });
  cO.addEventListener("pointermove", function (e) {
    var p = ptrs.get(e.pointerId); if (!p) return;
    if (ptrs.size >= 2) { p.x = e.clientX; p.y = e.clientY; var a = Array.from(ptrs.values()), d = Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y); if (pinch > 0 && d > 0) { zoom = clamp(zoom * d / pinch, 0.5, 3.2); tzoom = zoom; } pinch = d; return; }
    if (!drag) return;
    var now = performance.now(), dx = e.clientX - drag.x, dy = e.clientY - drag.y, dtm = Math.max(4, now - drag.t);
    drag.x = e.clientX; drag.y = e.clientY; drag.t = now; drag.mv += Math.abs(dx) + Math.abs(dy);
    if (drag.mv > 6) ease = false;
    yaw -= dx * 0.008; spin = spin * 0.6 + (-dx * 0.008 / dtm * 1000) * 0.4;
    if (e.pointerType === "mouse") pitch = clamp(pitch + dy * 0.006, -0.2, 1.45);
  });
  function soltar(e) {
    ptrs.delete(e.pointerId); if (ptrs.size < 2) pinch = 0;
    if (!drag || ptrs.size > 0) { if (ptrs.size > 0) drag = null; return; }
    if (e.type === "pointerup" && drag.mv < 8) { spin = 0; var r = cO.getBoundingClientRect(), k = elegir(e.clientX - r.left, e.clientY - r.top); sel = k >= 0 && k !== sel ? k : -1; }
    else if (performance.now() - drag.t > 90 || drag.mv >= 99) spin = 0;
    drag = null;
  }
  cO.addEventListener("pointerup", soltar); cO.addEventListener("pointercancel", soltar);
  var visible = true;
  if ("IntersectionObserver" in window) new IntersectionObserver(function (es) { visible = es[0].isIntersecting; }).observe(el);
  if ("ResizeObserver" in window) new ResizeObserver(resize).observe(el); else window.addEventListener("resize", resize);
  if (NOM[el.getAttribute("data-forma")]) { form = el.getAttribute("data-forma"); var v0 = VIS[form]; yaw = tyaw = v0[0]; pitch = tpitch = v0[1]; zoom = tzoom = v0[2]; }
  resize(); cargar(datos.grupos || []); requestAnimationFrame(cuadro);
})();
