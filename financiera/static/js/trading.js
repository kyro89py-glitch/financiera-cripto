/* Financiera Cripto · pantalla de Trading.
   Gráfico de velas en canvas (con medias móviles, volumen y cruz), libro de órdenes, operaciones del mercado y panel de
   órdenes con revisión antes de confirmar. Los precios en vivo llegan del evento "precios" que dispara app.js. */
(function () {
  "use strict";
  var nodo = document.getElementById("datos-trading");
  if (!nodo) return;
  var D = JSON.parse(nodo.textContent);
  var raiz = document.documentElement;

  // ---------- formato ----------
  function num(n, dec) {
    if (n == null || !isFinite(n)) return "—";
    var neg = n < 0, p = Math.abs(n).toFixed(dec).split(".");
    var s = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".") + (dec ? "," + p[1] : "");
    return (neg ? "−" : "") + s;
  }
  function decPx(p) {
    p = Math.abs(p);
    if (p >= 1 || p === 0) return 2;
    if (p >= 0.01) return 4;
    return Math.min(12, Math.ceil(-Math.log10(p)) + 3);
  }
  function px(n) { return num(n, D.dec); }
  function cant(q) {
    if (q >= 1e6) return num(q / 1e6, 2) + " M";
    if (q >= 1000) return num(q, 0);
    if (q >= 1) return num(q, 4);
    return num(q, 6);
  }
  function usd(n) { return "US$ " + num(n, 2); }
  function leerNum(t) {
    t = String(t || "").trim().replace(/\s|US\$/g, "");
    if (!t) return NaN;
    if (t.indexOf(",") >= 0) t = t.replace(/\./g, "").replace(",", ".");
    else if ((t.match(/\./g) || []).length > 1) t = t.replace(/\./g, "");
    return parseFloat(t);
  }
  function color(v) { return getComputedStyle(raiz).getPropertyValue(v).trim(); }

  // ---------- selector de par ----------
  var parBtn = document.querySelector(".par-btn"), lista = document.getElementById("lista-pares");
  if (parBtn && lista) {
    var buscar = lista.querySelector("input");
    function abrir(si) {
      lista.hidden = !si; parBtn.setAttribute("aria-expanded", si ? "true" : "false");
      if (si) { buscar.value = ""; filtrar(); buscar.focus(); }
    }
    function filtrar() {
      var q = buscar.value.trim().toLowerCase();
      lista.querySelectorAll("a[data-buscar]").forEach(function (a) { a.parentNode.hidden = q && a.getAttribute("data-buscar").indexOf(q) < 0; });
    }
    parBtn.addEventListener("click", function () { abrir(lista.hidden); });
    buscar.addEventListener("input", filtrar);
    document.addEventListener("click", function (e) { if (!lista.hidden && !lista.contains(e.target) && !parBtn.contains(e.target)) abrir(false); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !lista.hidden) { abrir(false); parBtn.focus(); } });
  }

  // ---------- gráfico de velas ----------
  var lienzo = document.getElementById("lienzo"), canvas = document.getElementById("velas");
  var estado = document.getElementById("graf-estado"), leyenda = document.getElementById("leyenda");
  var ctx = canvas.getContext("2d");
  var G = { velas: [], vol: false, seg: 900, i: D.intervalo, hover: -1, mouseY: null, w: 0, h: 0, dpr: 1, ancho: 6, desplaz: 0, inicio: 0 };
  var MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

  function medida() {
    var r = lienzo.getBoundingClientRect();
    G.dpr = window.devicePixelRatio || 1;
    G.w = Math.max(200, r.width); G.h = Math.max(220, r.height);
    canvas.width = Math.round(G.w * G.dpr); canvas.height = Math.round(G.h * G.dpr);
    canvas.style.width = G.w + "px"; canvas.style.height = G.h + "px";
    dibujar();
  }
  // ---- indicadores técnicos (sobre la serie completa) ----
  var IND = { ma: true, ema: false, boll: false, vol: true, rsi: false, macd: false };
  try { var guardado = JSON.parse(localStorage.getItem("fc-indicadores") || "null"); if (guardado) for (var k in IND) if (k in guardado) IND[k] = !!guardado[k]; } catch (e) { /* sin almacenamiento */ }
  var CALC = {};
  var CLASICOS = { ma1: 7, ma2: 25, ema: 20, bb: 20, bbk: 2, rsi: 14, mf: 12, ms: 26, mg: 9 }, PAR = {};
  for (var kk in CLASICOS) PAR[kk] = CLASICOS[kk];
  try { var pg = JSON.parse(localStorage.getItem("fc-ind-param") || "null"); if (pg) for (var k2 in CLASICOS) if (+pg[k2] > 0) PAR[k2] = +pg[k2]; } catch (e) { /* sin almacenamiento */ }
  function sma(n) { var out = [], s = 0, v = G.velas; for (var i = 0; i < v.length; i++) { s += v[i][4]; if (i >= n) s -= v[i - n][4]; out.push(i >= n - 1 ? s / n : null); } return out; }
  function emaDe(vals, n) { var out = [], k = 2 / (n + 1), e = null, s = 0, c = 0; for (var i = 0; i < vals.length; i++) { var x = vals[i]; if (x == null) { out.push(null); continue; } if (e == null) { s += x; c++; if (c === n) e = s / n; out.push(e); } else { e = x * k + e * (1 - k); out.push(e); } } return out; }
  function calcularIndicadores() {
    var v = G.velas, cierres = v.map(function (c) { return c[4]; });
    CALC.ma7 = sma(PAR.ma1); CALC.ma25 = sma(PAR.ma2); CALC.ema20 = emaDe(cierres, PAR.ema);
    var nb = PAR.bb, m20 = sma(nb); CALC.bsup = []; CALC.binf = [];
    for (var i = 0; i < v.length; i++) {
      if (m20[i] == null) { CALC.bsup.push(null); CALC.binf.push(null); continue; }
      var d = 0; for (var j = i - nb + 1; j <= i; j++) d += Math.pow(v[j][4] - m20[i], 2);
      d = Math.sqrt(d / nb); CALC.bsup.push(m20[i] + PAR.bbk * d); CALC.binf.push(m20[i] - PAR.bbk * d);
    }
    CALC.bmed = m20;
    var rsi = [null], g = 0, p = 0;
    for (i = 1; i < v.length; i++) {
      var dif = v[i][4] - v[i - 1][4], ga = Math.max(dif, 0), pe = Math.max(-dif, 0);
      var nr = PAR.rsi;
      if (i <= nr) { g += ga; p += pe; rsi.push(i === nr ? (p === 0 ? 100 : 100 - 100 / (1 + (g / nr) / (p / nr))) : null); if (i === nr) { g /= nr; p /= nr; } }
      else { g = (g * (nr - 1) + ga) / nr; p = (p * (nr - 1) + pe) / nr; rsi.push(p === 0 ? 100 : 100 - 100 / (1 + g / p)); }
    }
    CALC.rsi = rsi;
    var e12 = emaDe(cierres, PAR.mf), e26 = emaDe(cierres, PAR.ms), macd = e12.map(function (x, k) { return x != null && e26[k] != null ? x - e26[k] : null; });
    CALC.macd = macd; CALC.senal = emaDe(macd, PAR.mg);
    CALC.hist = macd.map(function (x, k) { return x != null && CALC.senal[k] != null ? x - CALC.senal[k] : null; });
  }
  document.querySelectorAll(".indicadores-chips [data-ind]").forEach(function (b) {
    var k = b.getAttribute("data-ind"); b.setAttribute("aria-pressed", IND[k] ? "true" : "false");
    b.addEventListener("click", function () {
      IND[k] = !IND[k]; b.setAttribute("aria-pressed", IND[k] ? "true" : "false");
      try { localStorage.setItem("fc-indicadores", JSON.stringify(IND)); } catch (e) { /* sin almacenamiento */ }
      alturaPaneles(); medida();
    });
  });
  function alturaPaneles() {
    var n = (IND.rsi ? 1 : 0) + (IND.macd ? 1 : 0);
    lienzo.classList.toggle("subs-1", n === 1); lienzo.classList.toggle("subs-2", n === 2);
  }
  alturaPaneles();
  function media(arr, n, k) {
    if (k < n - 1) return null;
    var s = 0; for (var j = k - n + 1; j <= k; j++) s += arr[j][4];
    return s / n;
  }
  function etiquetaTiempo(ms) {
    var d = new Date(ms), hh = ("0" + d.getHours()).slice(-2), mm = ("0" + d.getMinutes()).slice(-2);
    if (G.i === "1m" || G.i === "15m" || G.i === "1h") return hh + ":" + mm;
    if (G.i === "4h") return d.getDate() + "/" + (d.getMonth() + 1) + " " + hh + "h";
    if (G.i === "1d") return d.getDate() + " " + MESES[d.getMonth()];
    return MESES[d.getMonth()] + " " + String(d.getFullYear()).slice(-2);
  }
  function visibles() {
    var plotW = G.w - 64, cabe = Math.max(10, Math.floor(plotW / G.ancho)), n = G.velas.length;
    G.desplaz = Math.max(0, Math.min(G.desplaz, Math.max(0, n - 10)));
    var fin = n - G.desplaz, ini = Math.max(0, fin - cabe);
    G.inicio = ini;
    return G.velas.slice(ini, fin);
  }
  function zoom(factor) {
    G.ancho = Math.max(3, Math.min(40, G.ancho * factor)); G.hover = -1; dibujar();
  }
  function linea(serie, base, paso, y, color, ancho) {
    ctx.strokeStyle = color; ctx.lineWidth = ancho || 1.3; ctx.beginPath();
    var empezo = false;
    for (var j = 0; j < paso.n; j++) {
      var val = serie[base + j]; if (val == null) continue;
      var mx = j * paso.w + paso.w / 2;
      if (empezo) ctx.lineTo(mx, y(val)); else { ctx.moveTo(mx, y(val)); empezo = true; }
    }
    ctx.stroke();
  }
  function dibujar() {
    var W = G.w, H = G.h, dpr = G.dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var v = visibles();
    if (!v.length) return;
    calcularIndicadores();
    var base = G.inicio;
    var ejeY = 64, ejeX = 22, plotW = W - ejeY, subH = 74, subs = (IND.rsi ? 1 : 0) + (IND.macd ? 1 : 0);
    var mainH = H - ejeX - subs * subH;
    var volH = IND.vol && G.vol ? Math.round(mainH * 0.18) : 0, plotH = mainH - 6;
    var hi = -Infinity, lo = Infinity, vmax = 0;
    v.forEach(function (c, j) {
      hi = Math.max(hi, c[2]); lo = Math.min(lo, c[3]); vmax = Math.max(vmax, c[5]);
      if (IND.boll && CALC.bsup[base + j] != null) { hi = Math.max(hi, CALC.bsup[base + j]); lo = Math.min(lo, CALC.binf[base + j]); }
    });
    if (hi === lo) { hi *= 1.001; lo *= 0.999; }
    var pad = (hi - lo) * 0.08; hi += pad; lo -= pad;
    var y = function (p) { return 8 + (hi - p) / (hi - lo) * (plotH - 8 - volH * 0.6); };
    var paso = { w: plotW / v.length, n: v.length }, cuerpo = Math.max(1, Math.min(14, paso.w * 0.68));
    var cUp = color("--up"), cDown = color("--down"), cLine = color("--line"), cMuted = color("--muted"), cInk = color("--ink");
    ctx.font = "11px " + color("--sans");
    ctx.lineWidth = 1;
    ctx.fillStyle = cMuted; ctx.textBaseline = "middle"; ctx.textAlign = "left";
    for (var k = 0; k <= 4; k++) {
      var py = 8 + k * (plotH - 8 - volH * 0.6) / 4, valor = hi - k * (hi - lo) / 4;
      ctx.strokeStyle = cLine; ctx.beginPath(); ctx.moveTo(0, Math.round(py) + 0.5); ctx.lineTo(plotW, Math.round(py) + 0.5); ctx.stroke();
      ctx.fillText(num(valor, D.dec), plotW + 6, py);
    }
    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    var cada = Math.max(1, Math.round(v.length / Math.max(2, Math.floor(plotW / 90))));
    for (var t = v.length - 1; t >= 0; t -= cada) {
      var tx = t * paso.w + paso.w / 2;
      if (tx < 24) break;
      ctx.fillText(etiquetaTiempo(v[t][0]), tx, H - 6);
    }
    if (IND.boll) {
      ctx.beginPath(); var emp = false;
      for (var b1 = 0; b1 < v.length; b1++) { var su = CALC.bsup[base + b1]; if (su == null) continue; var bx = b1 * paso.w + paso.w / 2; if (emp) ctx.lineTo(bx, y(su)); else { ctx.moveTo(bx, y(su)); emp = true; } }
      for (var b2 = v.length - 1; b2 >= 0; b2--) { var inf = CALC.binf[base + b2]; if (inf == null) continue; ctx.lineTo(b2 * paso.w + paso.w / 2, y(inf)); }
      ctx.closePath(); ctx.fillStyle = color("--accent") + "14"; ctx.fill();
      linea(CALC.bsup, base, paso, y, color("--accent") + "99", 1); linea(CALC.binf, base, paso, y, color("--accent") + "99", 1);
    }
    if (volH && vmax > 0) {
      v.forEach(function (c, j) {
        var vh = c[5] / vmax * volH, vx = j * paso.w + (paso.w - cuerpo) / 2;
        ctx.fillStyle = (c[4] >= c[1] ? cUp : cDown); ctx.globalAlpha = 0.25;
        ctx.fillRect(vx, mainH - vh, cuerpo, vh);
      });
      ctx.globalAlpha = 1;
    }
    v.forEach(function (c, j) {
      var cx = j * paso.w + paso.w / 2, sube = c[4] >= c[1];
      ctx.strokeStyle = ctx.fillStyle = sube ? cUp : cDown;
      ctx.beginPath(); ctx.moveTo(Math.round(cx) + 0.5, y(c[2])); ctx.lineTo(Math.round(cx) + 0.5, y(c[3])); ctx.stroke();
      var top = y(Math.max(c[1], c[4])), alto = Math.max(1, Math.abs(y(c[1]) - y(c[4])));
      ctx.fillRect(Math.round(cx - cuerpo / 2), top, Math.round(cuerpo), alto);
    });
    if (IND.ma) { linea(CALC.ma7, base, paso, y, color("--warn")); linea(CALC.ma25, base, paso, y, color("--accent")); }
    if (IND.ema) linea(CALC.ema20, base, paso, y, "#B67CFF", 1.5);
    ctx.lineWidth = 1;
    var ult = v[v.length - 1], uy = y(ult[4]), cUlt = ult[4] >= ult[1] ? cUp : cDown;
    ctx.setLineDash([3, 3]); ctx.strokeStyle = cUlt; ctx.beginPath(); ctx.moveTo(0, uy); ctx.lineTo(plotW, uy); ctx.stroke(); ctx.setLineDash([]);
    etiqueta(num(ult[4], D.dec), plotW, uy, cUlt, "#fff");
    // paneles inferiores
    var top0 = mainH;
    function panel(titulo, valores, minimo, maximo, dibujo) {
      ctx.strokeStyle = cLine; ctx.beginPath(); ctx.moveTo(0, top0 + 0.5); ctx.lineTo(W, top0 + 0.5); ctx.stroke();
      var yy = function (val) { return top0 + 14 + (maximo - val) / (maximo - minimo) * (subH - 22); };
      dibujo(yy);
      ctx.fillStyle = cMuted; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.font = "11px " + color("--sans");
      var idx = G.hover >= 0 ? base + G.hover : G.velas.length - 1, val = valores[idx];
      ctx.fillText(titulo + (val != null ? "  " + num(val, Math.abs(val) >= 100 ? 1 : (Math.abs(val) >= 1 ? 2 : D.dec)) : ""), 6, top0 + 3);
      top0 += subH;
    }
    if (IND.rsi) {
      panel("RSI " + PAR.rsi, CALC.rsi, 0, 100, function (yy) {
        ctx.fillStyle = color("--accent") + "10"; ctx.fillRect(0, yy(70), plotW, yy(30) - yy(70));
        ctx.setLineDash([2, 3]); ctx.strokeStyle = cMuted;
        [30, 70].forEach(function (l) { ctx.beginPath(); ctx.moveTo(0, yy(l)); ctx.lineTo(plotW, yy(l)); ctx.stroke(); ctx.fillStyle = cMuted; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(String(l), plotW + 6, yy(l)); });
        ctx.setLineDash([]);
        linea(CALC.rsi, base, paso, yy, color("--accent"), 1.4);
      });
    }
    if (IND.macd) {
      var mmax = 0;
      for (var q = 0; q < v.length; q++) [CALC.macd[base + q], CALC.senal[base + q], CALC.hist[base + q]].forEach(function (x) { if (x != null) mmax = Math.max(mmax, Math.abs(x)); });
      mmax = mmax || 1;
      panel("MACD " + PAR.mf + " " + PAR.ms + " " + PAR.mg, CALC.macd, -mmax, mmax, function (yy) {
        for (var h2 = 0; h2 < v.length; h2++) {
          var hv = CALC.hist[base + h2]; if (hv == null) continue;
          ctx.fillStyle = hv >= 0 ? cUp : cDown; ctx.globalAlpha = 0.55;
          var y0 = yy(0), y1 = yy(hv); ctx.fillRect(h2 * paso.w + (paso.w - cuerpo) / 2, Math.min(y0, y1), cuerpo, Math.max(1, Math.abs(y1 - y0)));
        }
        ctx.globalAlpha = 1;
        linea(CALC.macd, base, paso, yy, color("--accent"), 1.3); linea(CALC.senal, base, paso, yy, color("--warn"), 1.2);
      });
    }
    if (G.hover >= 0 && G.hover < v.length) {
      var hx = G.hover * paso.w + paso.w / 2;
      ctx.strokeStyle = cMuted; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(hx, 0); ctx.lineTo(hx, H - ejeX); ctx.stroke();
      if (G.mouseY != null && G.mouseY < plotH) {
        ctx.beginPath(); ctx.moveTo(0, G.mouseY); ctx.lineTo(plotW, G.mouseY); ctx.stroke();
        ctx.setLineDash([]);
        etiqueta(num(hi - (G.mouseY - 8) / (plotH - 8 - volH * 0.6) * (hi - lo), D.dec), plotW, G.mouseY, color("--surface-3"), cInk);
      }
      ctx.setLineDash([]);
      escribirLeyenda(v[G.hover], base + G.hover);
    } else {
      escribirLeyenda(ult, G.velas.length - 1);
    }
  }
  function etiqueta(texto, x, yy, fondo, tinta) {
    ctx.fillStyle = fondo; ctx.fillRect(x + 1, yy - 9, 62, 18);
    ctx.fillStyle = tinta; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(texto, x + 5, yy);
  }
  function escribirLeyenda(c, idx) {
    if (!c) { leyenda.textContent = ""; return; }
    var var_ = c[1] ? (c[4] / c[1] - 1) * 100 : 0, d = new Date(c[0]);
    leyenda.innerHTML = "";
    var partes = [["", d.toLocaleDateString("es-PY", { day: "numeric", month: "short" }) + " " + d.toLocaleTimeString("es-PY", { hour: "2-digit", minute: "2-digit", hour12: false })],
     ["A", num(c[1], D.dec)], ["M", num(c[2], D.dec)], ["m", num(c[3], D.dec)], ["C", num(c[4], D.dec)],
     ["", (var_ >= 0 ? "+" : "") + num(var_, 2) + " %"]];
    if (IND.ma && CALC.ma7 && CALC.ma7[idx] != null) partes.push(["MA" + PAR.ma1, num(CALC.ma7[idx], D.dec)]);
    if (IND.ma && CALC.ma25 && CALC.ma25[idx] != null) partes.push(["MA" + PAR.ma2, num(CALC.ma25[idx], D.dec)]);
    if (IND.ema && CALC.ema20 && CALC.ema20[idx] != null) partes.push(["EMA" + PAR.ema, num(CALC.ema20[idx], D.dec)]);
    partes.forEach(function (p, j) {
      var s = document.createElement("span");
      if (p[0]) { var b = document.createElement("b"); b.textContent = p[0] + " "; s.appendChild(b); }
      s.appendChild(document.createTextNode(p[1]));
      if (j === 5) s.className = var_ >= 0 ? "up" : "down";
      leyenda.appendChild(s);
    });
  }
  // Zoom y desplazamiento: rueda o +/− para acercar, arrastre horizontal para ir al pasado, pellizco en el celular,
  // doble toque o ⟲ para volver a las últimas velas.
  var punteros = {}, arrastre = null, pellizco = null;
  canvas.addEventListener("pointerdown", function (e) {
    punteros[e.pointerId] = e.clientX;
    var ids = Object.keys(punteros);
    if (ids.length === 2) {
      pellizco = { d: Math.abs(punteros[ids[0]] - punteros[ids[1]]) || 1, ancho: G.ancho }; arrastre = null;
    } else if (e.button === 0 || e.pointerType !== "mouse") {
      arrastre = { x: e.clientX, desplaz: G.desplaz, movio: false };
    }
  });
  function soltar(e) { delete punteros[e.pointerId]; if (Object.keys(punteros).length < 2) pellizco = null; arrastre = null; canvas.classList.remove("arrastrando"); }
  canvas.addEventListener("pointerup", soltar);
  canvas.addEventListener("pointercancel", soltar);
  canvas.addEventListener("pointermove", function (e) {
    var r = canvas.getBoundingClientRect();
    if (e.pointerId in punteros) punteros[e.pointerId] = e.clientX;
    if (pellizco) {
      var ids = Object.keys(punteros), d = Math.abs(punteros[ids[0]] - punteros[ids[1]]) || 1;
      G.ancho = Math.max(3, Math.min(40, pellizco.ancho * d / pellizco.d)); dibujar(); return;
    }
    if (arrastre) {
      var dx = e.clientX - arrastre.x;
      if (Math.abs(dx) > 4) { arrastre.movio = true; canvas.classList.add("arrastrando"); }
      if (arrastre.movio) { G.desplaz = arrastre.desplaz + Math.round(dx / G.ancho); G.hover = -1; dibujar(); return; }
    }
    var v = visibles(), paso = (G.w - 64) / Math.max(1, v.length);
    G.hover = Math.min(v.length - 1, Math.max(0, Math.floor((e.clientX - r.left) / paso)));
    G.mouseY = e.clientY - r.top; dibujar();
  });
  canvas.addEventListener("pointerleave", function (e) { soltar(e); G.hover = -1; G.mouseY = null; dibujar(); });
  canvas.addEventListener("wheel", function (e) { e.preventDefault(); zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15); }, { passive: false });
  canvas.addEventListener("dblclick", function () { G.ancho = 6; G.desplaz = 0; dibujar(); });
  document.querySelectorAll("[data-zoom]").forEach(function (b) {
    b.addEventListener("click", function () {
      var z = +b.getAttribute("data-zoom");
      if (z === 0) { G.ancho = 6; G.desplaz = 0; dibujar(); } else zoom(z > 0 ? 1.3 : 1 / 1.3);
    });
  });
  // Parámetros de los indicadores
  var dInd = document.getElementById("d-ind"), fInd = document.getElementById("f-ind");
  function pintarParametros() {
    document.querySelectorAll("[data-par-ind]").forEach(function (el) { el.textContent = PAR[el.getAttribute("data-par-ind")]; });
  }
  pintarParametros();
  if (dInd && fInd) {
    document.getElementById("ind-ajustes").addEventListener("click", function () {
      for (var k in PAR) if (fInd.elements[k]) fInd.elements[k].value = PAR[k];
      if (dInd.showModal) dInd.showModal();
    });
    document.getElementById("ind-reset").addEventListener("click", function () { for (var k in CLASICOS) if (fInd.elements[k]) fInd.elements[k].value = CLASICOS[k]; });
    fInd.addEventListener("submit", function () {
      for (var k in CLASICOS) {
        var x = parseFloat(String(fInd.elements[k].value).replace(",", "."));
        var mn = +fInd.elements[k].min, mx = +fInd.elements[k].max;
        PAR[k] = isFinite(x) ? Math.max(mn, Math.min(mx, x)) : CLASICOS[k];
      }
      if (PAR.ms <= PAR.mf) PAR.ms = PAR.mf + 1;
      try { localStorage.setItem("fc-ind-param", JSON.stringify(PAR)); } catch (e) { /* sin almacenamiento */ }
      pintarParametros(); dibujar();
    });
  }

  var pedido = 0;
  function cargarVelas(mostrarCarga) {
    var mio = ++pedido;
    if (mostrarCarga) { estado.hidden = false; estado.textContent = "Cargando velas…"; }
    fetch("/mercado/" + D.activo + "/velas.json?i=" + G.i, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (mio !== pedido) return;
        if (!j || !j.v.length) { estado.hidden = false; estado.textContent = "Todavía no hay datos para este período."; return; }
        G.velas = j.v; G.vol = j.vol; G.seg = j.seg; D.dec = j.dec; estado.hidden = true;
        var f = document.getElementById("graf-fuente");
        if (f) f.textContent = j.simulado ? "Velas armadas con el historial de precios" : "Velas de Binance";
        dibujar();
      })
      .catch(function () { if (mio === pedido) { estado.hidden = false; estado.textContent = "Sin conexión. Reintentando…"; } });
  }
  document.querySelectorAll(".intervalos [data-i]").forEach(function (b) {
    b.addEventListener("click", function () {
      G.i = b.getAttribute("data-i");
      document.querySelectorAll(".intervalos [data-i]").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      try { history.replaceState(null, "", location.pathname + "?i=" + G.i); } catch (e) { /* sin historial */ }
      var volver = document.querySelector("#f-orden [name=volver]"); if (volver) volver.value = location.pathname + "?i=" + G.i;
      cargarVelas(true);
    });
  });
  function precioEnVivo(p) {
    if (!G.velas.length || !p) return;
    var ult = G.velas[G.velas.length - 1], ahora = Date.now();
    if (ahora >= ult[0] + G.seg * 1000) {
      G.velas.push([Math.floor(ahora / (G.seg * 1000)) * G.seg * 1000, ult[4], Math.max(ult[4], p), Math.min(ult[4], p), p, 0]);
      if (G.velas.length > 400) G.velas.shift();
    } else {
      ult[4] = p; ult[2] = Math.max(ult[2], p); ult[3] = Math.min(ult[3], p);
    }
    dibujar();
  }
  if (window.ResizeObserver) new ResizeObserver(medida).observe(lienzo); else window.addEventListener("resize", medida);
  medida();
  cargarVelas(true);
  setInterval(function () { if (!document.hidden) cargarVelas(false); }, 30000);

  // ---------- libro de órdenes y operaciones del mercado ----------
  var ventasEl = document.getElementById("ventas"), comprasEl = document.getElementById("compras");
  var opsEl = document.getElementById("ops"), spreadEl = document.getElementById("spread");
  function filaLibro(p, q, max, lado) {
    var f = document.createElement("button");
    f.type = "button"; f.className = "lf " + lado;
    f.style.setProperty("--d", Math.min(100, q * p / max * 100).toFixed(1) + "%");
    [num(p, D.dec), cant(q), num(p * q, 2)].forEach(function (t) { var s = document.createElement("span"); s.textContent = t; f.appendChild(s); });
    f.addEventListener("click", function () { usarPrecio(p); });
    return f;
  }
  function pintarLibro(j) {
    var max = 0;
    j.ventas.concat(j.compras).forEach(function (x) { max = Math.max(max, x[0] * x[1]); });
    ventasEl.innerHTML = ""; comprasEl.innerHTML = "";
    j.ventas.slice(0, 10).reverse().forEach(function (x) { ventasEl.appendChild(filaLibro(x[0], x[1], max, "venta")); });
    j.compras.slice(0, 10).forEach(function (x) { comprasEl.appendChild(filaLibro(x[0], x[1], max, "compra")); });
    if (j.ventas.length && j.compras.length) {
      var s = j.ventas[0][0] - j.compras[0][0];
      spreadEl.textContent = "Diferencia " + num(s, D.dec) + " (" + num(s / j.ventas[0][0] * 100, 3) + " %)";
    }
    opsEl.innerHTML = "";
    j.ops.slice(0, 18).forEach(function (o) {
      var f = document.createElement("div"), d = new Date(o[0]);
      f.className = "lf " + (o[3] ? "compra" : "venta");
      [num(o[1], D.dec), cant(o[2]), d.toLocaleTimeString("es-PY", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })].forEach(function (t) {
        var s = document.createElement("span"); s.textContent = t; f.appendChild(s);
      });
      opsEl.appendChild(f);
    });
    ["libro-sim", "ops-sim"].forEach(function (id) { var e = document.getElementById(id); if (e) e.hidden = !j.simulado; });
    var liq = document.getElementById("liquidez");
    if (liq && j.ventas.length && j.compras.length) {
      var medio = (j.ventas[0][0] + j.compras[0][0]) / 2, dc = 0, dv = 0;
      j.compras.forEach(function (x) { if (x[0] >= medio * 0.99) dc += x[0] * x[1]; });
      j.ventas.forEach(function (x) { if (x[0] <= medio * 1.01) dv += x[0] * x[1]; });
      var tot = dc + dv || 1;
      liq.querySelector("[data-liq-compra]").textContent = usd(dc);
      liq.querySelector("[data-liq-venta]").textContent = usd(dv);
      liq.querySelector(".liq-barra i").style.width = (dc / tot * 100).toFixed(1) + "%";
    }
  }
  function cargarLibro() {
    if (document.hidden) return;
    fetch("/mercado/" + D.activo + "/libro.json", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j) pintarLibro(j); })
      .catch(function () { /* se reintenta */ });
  }
  cargarLibro();
  setInterval(cargarLibro, 3000);

  // ---------- panel de órdenes ----------
  var form = document.getElementById("f-orden");
  var calcular = function () {};
  var estadoOrden = { lado: "compra", tipo: "mercado" };
  var usarPrecio = function () {};
  if (form) {
    usarPrecio = function (p) {
      if (estadoOrden.tipo === "mercado") elegirTipo("limite");
      var actual = D.precio || p;
      if (estadoOrden.tipo === "limite") elegirLado(p < actual ? "compra" : "venta");
      form.precio.value = num(p, decPx(p));
      calcular();
      form.monto.focus();
    };
    var ayuda = document.getElementById("tipo-ayuda"), campoPrecio = document.getElementById("campo-precio");
    var btn = document.getElementById("o-enviar"), errorEl = document.getElementById("o-error");
    var dlg = document.getElementById("d-orden"), resumen = document.getElementById("d-resumen");
    var AYUDAS = {
      "mercado": "Se ejecuta ahora, al mejor precio disponible.",
      "limite-compra": "Queda abierta y compra cuando el precio baje al nivel que elijas.",
      "limite-venta": "Queda abierta y vende cuando el precio suba al nivel que elijas.",
      "stop-compra": "Compra si el precio sube hasta el nivel que elijas (para entrar cuando arranca una suba).",
      "stop-venta": "Vende si el precio baja hasta el nivel que elijas (para cortar una pérdida).",
      "oco-venta": "Dos ventas enlazadas: una toma la ganancia si sube y la otra corta la pérdida si baja. Al ejecutarse una, la otra se cancela.",
      "oco-compra": "Dos compras enlazadas: una compra si baja al precio límite y otra si sube al stop. Al ejecutarse una, la otra se cancela."
    };
    var campoStop = document.getElementById("campo-stop"), prot = document.getElementById("proteccion");
    function elegirLado(l) {
      estadoOrden.lado = l; form.lado.value = l;
      document.querySelectorAll(".lado-tabs [data-lado]").forEach(function (b) { b.setAttribute("aria-selected", b.getAttribute("data-lado") === l ? "true" : "false"); });
      btn.className = "btn block lado-btn " + l;
      btn.textContent = (l === "compra" ? "Comprar " : "Vender ") + D.activo;
      form.todo.value = "";
      if (estadoOrden.tipo === "oco") elegirTipo("oco"); else actualizarTextos();
    }
    function elegirTipo(t) {
      estadoOrden.tipo = t; form.tipo.value = t;
      document.querySelectorAll(".tipos [data-tipo]").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-tipo") === t ? "true" : "false"); });
      campoPrecio.hidden = t === "mercado";
      campoStop.hidden = t !== "oco";
      document.getElementById("campo-precio-txt").textContent = t === "oco" ? (estadoOrden.lado === "venta" ? "Toma de ganancia: precio límite (USD)" : "Precio límite (USD)") : "Precio de activación (USD)";
      document.getElementById("campo-stop-txt").textContent = estadoOrden.lado === "venta" ? "Corte de pérdida: precio stop (USD)" : "Precio stop (USD)";
      if (t === "oco" && D.precio) {
        var arriba = D.precio * 1.05, abajo = D.precio * 0.95;
        form.precio.value = num(estadoOrden.lado === "venta" ? arriba : abajo, D.dec);
        form.precio_stop.value = num(estadoOrden.lado === "venta" ? abajo : arriba, D.dec);
      } else if (t !== "mercado" && !form.precio.value && D.precio) form.precio.value = num(D.precio, D.dec);
      actualizarTextos();
    }
    function actualizarTextos() {
      ayuda.textContent = AYUDAS[estadoOrden.tipo === "mercado" ? "mercado" : estadoOrden.tipo + "-" + estadoOrden.lado];
      if (prot) prot.hidden = !(estadoOrden.tipo === "mercado" && estadoOrden.lado === "compra");
      document.getElementById("o-disp").textContent = estadoOrden.lado === "compra" ? usd(D.disp_usd / 100)
        : cant(D.disp_u / 1e8) + " " + D.activo + (D.precio ? " ≈ " + usd(D.disp_u / 1e8 * D.precio) : "");
      calcular();
    }
    function precioRef() {
      if (estadoOrden.tipo === "mercado") return D.precio;
      var p = leerNum(form.precio.value); return isFinite(p) && p > 0 ? p : D.precio;
    }
    calcular = function () {
      var m = leerNum(form.monto.value), p = precioRef();
      var okM = isFinite(m) && m > 0;
      document.getElementById("o-cant").textContent = okM && p ? "≈ " + cant(m / p) + " " + D.activo : "—";
      document.getElementById("o-com").textContent = !D.comision ? "Sin comisión" : (okM ? "≈ " + usd(m * D.comision / 100) : "—");
    };
    function validar() {
      var m = leerNum(form.monto.value), p = precioRef(), lado = estadoOrden.lado, tipo = estadoOrden.tipo;
      if (!(form.todo.value === "si") && !(isFinite(m) && m > 0)) return "Escribe el monto en dólares, por ejemplo 250 o 250,50.";
      if (tipo !== "mercado") {
        var lp = leerNum(form.precio.value);
        if (!(isFinite(lp) && lp > 0)) return "Escribe el precio de activación.";
        var actual = D.precio;
        if (tipo === "oco") {
          var sp = leerNum(form.precio_stop.value);
          if (!(isFinite(sp) && sp > 0)) return "Escribe el precio stop.";
          if (lado === "venta" && !(lp > actual && sp < actual)) return "En una OCO de venta, la toma de ganancia va por encima de " + px(actual) + " y el corte de pérdida por debajo.";
          if (lado === "compra" && !(lp < actual && sp > actual)) return "En una OCO de compra, el precio límite va por debajo de " + px(actual) + " y el stop por encima.";
        } else {
          if (tipo === "limite" && lado === "compra" && lp >= actual) return "Una compra límite se activa cuando el precio baja: elige un precio menor al actual (" + px(actual) + ").";
          if (tipo === "limite" && lado === "venta" && lp <= actual) return "Una venta límite se activa cuando el precio sube: elige un precio mayor al actual (" + px(actual) + ").";
          if (tipo === "stop" && lado === "compra" && lp <= actual) return "Una compra stop se activa cuando el precio sube: elige un precio mayor al actual (" + px(actual) + ").";
          if (tipo === "stop" && lado === "venta" && lp >= actual) return "Un stop de venta se activa cuando el precio baja: elige un precio menor al actual (" + px(actual) + ").";
        }
        if (form.todo.value !== "si" && m < 10) return "El mínimo de una orden límite, stop u OCO es de US$ 10.";
      }
      if (tipo === "mercado" && lado === "compra" && prot) {
        var tp = leerNum(form.tp.value), sl = leerNum(form.sl.value);
        if (form.tp.value.trim() && !(isFinite(tp) && tp > D.precio)) return "La toma de ganancia tiene que estar por encima del precio actual (" + px(D.precio) + ").";
        if (form.sl.value.trim() && !(isFinite(sl) && sl > 0 && sl < D.precio)) return "El corte de pérdida tiene que estar por debajo del precio actual (" + px(D.precio) + ").";
      }
      if (form.todo.value !== "si") {
        if (lado === "compra" && m * 100 > D.disp_usd) return "No tienes saldo disponible suficiente (" + usd(D.disp_usd / 100) + ").";
        if (lado === "venta" && p && m > D.disp_u / 1e8 * p * 1.0001) return "Tienes " + usd(D.disp_u / 1e8 * p) + " disponibles en " + D.activo + ".";
        if (m * 100 > D.maximo) return "El máximo por orden es de " + usd(D.maximo / 100) + ".";
      }
      return null;
    }
    document.querySelectorAll(".lado-tabs [data-lado]").forEach(function (b) { b.addEventListener("click", function () { elegirLado(b.getAttribute("data-lado")); }); });
    document.querySelectorAll(".tipos [data-tipo]").forEach(function (b) { b.addEventListener("click", function () { elegirTipo(b.getAttribute("data-tipo")); }); });
    form.monto.addEventListener("input", function () { form.todo.value = ""; errorEl.hidden = true; calcular(); });
    form.precio.addEventListener("input", function () { errorEl.hidden = true; calcular(); });
    document.querySelectorAll(".pcts [data-pct]").forEach(function (b) {
      b.addEventListener("click", function () {
        var pct = +b.getAttribute("data-pct"), p = precioRef(), m;
        if (estadoOrden.lado === "compra") m = D.disp_usd / 100 * pct / 100;
        else m = p ? D.disp_u / 1e8 * p * pct / 100 : 0;
        form.monto.value = num(Math.floor(m * 100) / 100, 2);
        form.todo.value = (pct === 100 && estadoOrden.lado === "venta") ? "si" : "";
        errorEl.hidden = true; calcular();
      });
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var err = validar();
      if (err) { errorEl.textContent = err; errorEl.hidden = false; return; }
      var m = leerNum(form.monto.value), p = precioRef(), tipo = estadoOrden.tipo, lado = estadoOrden.lado;
      var nombres = { mercado: "Mercado", limite: "Límite", stop: "Stop", oco: "OCO (dos órdenes enlazadas)" };
      var filas = [
        ["Par", D.activo + "/USD"],
        ["Operación", (lado === "compra" ? "Compra" : "Venta") + " · " + nombres[tipo]],
        [tipo === "mercado" ? "Precio de referencia" : (tipo === "oco" ? "Precio límite" : "Precio de activación"), "US$ " + px(tipo === "mercado" ? D.precio : leerNum(form.precio.value))],
        ["Monto", form.todo.value === "si" ? "Todo lo disponible (" + cant(D.disp_u / 1e8) + " " + D.activo + ")" : usd(m)],
        ["Cantidad estimada", form.todo.value === "si" ? cant(D.disp_u / 1e8) + " " + D.activo : "≈ " + cant(m / p) + " " + D.activo],
        ["Comisión estimada", (D.comision ? "≈ " + usd((form.todo.value === "si" ? D.disp_u / 1e8 * p : m) * D.comision / 100) : "Sin comisión") ]
      ];
      if (tipo === "oco") filas.splice(3, 0, ["Precio stop", "US$ " + px(leerNum(form.precio_stop.value))]);
      if (tipo === "mercado" && lado === "compra" && prot && (form.tp.value.trim() || form.sl.value.trim())) {
        if (form.tp.value.trim()) filas.push(["Toma de ganancia", "US$ " + px(leerNum(form.tp.value))]);
        if (form.sl.value.trim()) filas.push(["Corte de pérdida", "US$ " + px(leerNum(form.sl.value))]);
      }
      if (D.expo && D.expo.total > 0) {
        var monto = form.todo.value === "si" ? D.disp_u / 1e8 * p : m;
        var antes = D.expo.valor / D.expo.total * 100, despues = (D.expo.valor + (lado === "compra" ? 1 : -1) * monto * 100) / D.expo.total * 100;
        if (tipo === "mercado") filas.push(["Tu exposición a " + D.activo, num(antes, 1) + " % → " + num(Math.max(0, despues), 1) + " %"]);
      }
      resumen.innerHTML = "";
      filas.forEach(function (f) {
        var dt = document.createElement("dt"), dd = document.createElement("dd");
        dt.textContent = f[0]; dd.textContent = f[1]; resumen.appendChild(dt); resumen.appendChild(dd);
      });
      var nota = tipo === "mercado"
        ? "El precio final es el que se obtenga al ejecutar la orden y puede variar un poco respecto del de referencia."
        : "La orden queda abierta y reserva el saldo hasta que se ejecute o la canceles. Se ejecuta a precio de mercado cuando se alcance el nivel.";
      if (D.expo && D.expo.total > 0 && tipo === "mercado" && lado === "compra" && (D.expo.valor + m * 100) / D.expo.total > 0.5)
        nota += " Atención: con esta compra más de la mitad de tu cartera quedaría en " + D.activo + ".";
      if (D.simulador) nota += " Modo demostración: se ejecuta en el simulador, sin enviarse a ningún exchange.";
      document.getElementById("d-nota").textContent = nota;
      var ok = document.getElementById("d-ok");
      ok.className = "btn " + (lado === "compra" ? "primary compra" : "primary venta");
      ok.textContent = "Confirmar " + (lado === "compra" ? "compra" : "venta");
      if (dlg.showModal) dlg.showModal(); else enviar();
    });
    function enviar() {
      form.action = estadoOrden.tipo === "mercado" ? form.getAttribute("data-mercado") : form.getAttribute("data-prog");
      if (!(estadoOrden.tipo === "mercado" && estadoOrden.lado === "compra") && prot) { form.tp.value = ""; form.sl.value = ""; }
      if (estadoOrden.tipo !== "mercado" && form.todo.value === "si") form.monto.value = "";
      document.getElementById("d-ok").disabled = true;
      HTMLFormElement.prototype.submit.call(form);
    }
    document.getElementById("d-ok").addEventListener("click", enviar);
    dlg.querySelector("[data-cerrar]").addEventListener("click", function () { dlg.close(); });
    elegirLado("compra"); elegirTipo("mercado");
  }

  // ---------- pestañas de mis órdenes ----------
  var tabs = document.querySelectorAll(".tabs-sec [role=tab]");
  tabs.forEach(function (t) {
    t.addEventListener("click", function () {
      tabs.forEach(function (x) {
        var on = x === t; x.setAttribute("aria-selected", on ? "true" : "false");
        document.getElementById(x.getAttribute("aria-controls")).hidden = !on;
      });
    });
  });

  // ---------- precios en vivo ----------
  document.addEventListener("precios", function (e) {
    var x = e.detail.precios[D.activo]; if (!x) return;
    D.precio = x.valor;
    precioEnVivo(x.valor);
    if (form) calcular();
  });
})();
