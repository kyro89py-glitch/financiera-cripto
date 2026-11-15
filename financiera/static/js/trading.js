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
  var G = { velas: [], vol: false, seg: 900, i: D.intervalo, hover: -1, mouseY: null, w: 0, h: 0, dpr: 1 };
  var MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

  function medida() {
    var r = lienzo.getBoundingClientRect();
    G.dpr = window.devicePixelRatio || 1;
    G.w = Math.max(200, r.width); G.h = Math.max(220, r.height);
    canvas.width = Math.round(G.w * G.dpr); canvas.height = Math.round(G.h * G.dpr);
    canvas.style.width = G.w + "px"; canvas.style.height = G.h + "px";
    dibujar();
  }
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
    var ejeX = 64, ancho = G.w - ejeX, cabe = Math.max(10, Math.floor(ancho / 6));
    return G.velas.slice(-cabe);
  }
  function dibujar() {
    var W = G.w, H = G.h, dpr = G.dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var v = visibles();
    if (!v.length) return;
    var ejeY = 64, ejeX = 22, plotW = W - ejeY, volH = G.vol ? Math.round((H - ejeX) * 0.18) : 0, plotH = H - ejeX - volH - 6;
    var hi = -Infinity, lo = Infinity, vmax = 0;
    v.forEach(function (c) { hi = Math.max(hi, c[2]); lo = Math.min(lo, c[3]); vmax = Math.max(vmax, c[5]); });
    if (hi === lo) { hi *= 1.001; lo *= 0.999; }
    var pad = (hi - lo) * 0.08; hi += pad; lo -= pad;
    var y = function (p) { return 8 + (hi - p) / (hi - lo) * (plotH - 8); };
    var paso = plotW / v.length, cuerpo = Math.max(1, Math.min(14, paso * 0.68));
    var cUp = color("--up"), cDown = color("--down"), cLine = color("--line"), cMuted = color("--muted"), cInk = color("--ink");
    ctx.font = "11px " + color("--mono");
    ctx.lineWidth = 1;
    // cuadrícula y eje de precios
    ctx.fillStyle = cMuted; ctx.textBaseline = "middle"; ctx.textAlign = "left";
    for (var k = 0; k <= 4; k++) {
      var py = 8 + k * (plotH - 8) / 4, valor = hi - k * (hi - lo) / 4;
      ctx.strokeStyle = cLine; ctx.beginPath(); ctx.moveTo(0, Math.round(py) + 0.5); ctx.lineTo(plotW, Math.round(py) + 0.5); ctx.stroke();
      ctx.fillText(num(valor, D.dec), plotW + 6, py);
    }
    // eje de tiempo
    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    var cada = Math.max(1, Math.round(v.length / Math.max(2, Math.floor(plotW / 90))));
    for (var t = v.length - 1; t >= 0; t -= cada) {
      var tx = t * paso + paso / 2;
      if (tx < 24) break;
      ctx.fillText(etiquetaTiempo(v[t][0]), tx, H - 6);
    }
    // volumen
    if (G.vol && vmax > 0) {
      v.forEach(function (c, j) {
        var vh = c[5] / vmax * volH, vx = j * paso + (paso - cuerpo) / 2;
        ctx.fillStyle = (c[4] >= c[1] ? cUp : cDown); ctx.globalAlpha = 0.28;
        ctx.fillRect(vx, H - ejeX - vh, cuerpo, vh);
      });
      ctx.globalAlpha = 1;
    }
    // velas
    v.forEach(function (c, j) {
      var cx = j * paso + paso / 2, sube = c[4] >= c[1];
      ctx.strokeStyle = ctx.fillStyle = sube ? cUp : cDown;
      ctx.beginPath(); ctx.moveTo(Math.round(cx) + 0.5, y(c[2])); ctx.lineTo(Math.round(cx) + 0.5, y(c[3])); ctx.stroke();
      var top = y(Math.max(c[1], c[4])), alto = Math.max(1, Math.abs(y(c[1]) - y(c[4])));
      ctx.fillRect(Math.round(cx - cuerpo / 2), top, Math.round(cuerpo), alto);
    });
    // medias móviles sobre la serie completa
    var base = G.velas.length - v.length;
    [[7, color("--warn")], [25, color("--accent")]].forEach(function (m) {
      ctx.strokeStyle = m[1]; ctx.lineWidth = 1.4; ctx.beginPath();
      var empezo = false;
      v.forEach(function (c, j) {
        var mv = media(G.velas, m[0], base + j); if (mv == null) return;
        var mx = j * paso + paso / 2;
        if (empezo) ctx.lineTo(mx, y(mv)); else { ctx.moveTo(mx, y(mv)); empezo = true; }
      });
      ctx.stroke();
    });
    ctx.lineWidth = 1;
    // último precio
    var ult = v[v.length - 1], uy = y(ult[4]), cUlt = ult[4] >= ult[1] ? cUp : cDown;
    ctx.setLineDash([3, 3]); ctx.strokeStyle = cUlt; ctx.beginPath(); ctx.moveTo(0, uy); ctx.lineTo(plotW, uy); ctx.stroke(); ctx.setLineDash([]);
    etiqueta(num(ult[4], D.dec), plotW, uy, cUlt, "#fff");
    // cruz
    if (G.hover >= 0 && G.hover < v.length) {
      var hx = G.hover * paso + paso / 2;
      ctx.strokeStyle = cMuted; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(hx, 0); ctx.lineTo(hx, H - ejeX); ctx.stroke();
      if (G.mouseY != null && G.mouseY < plotH) {
        ctx.beginPath(); ctx.moveTo(0, G.mouseY); ctx.lineTo(plotW, G.mouseY); ctx.stroke();
        ctx.setLineDash([]);
        etiqueta(num(hi - (G.mouseY - 8) / (plotH - 8) * (hi - lo), D.dec), plotW, G.mouseY, color("--surface-3"), cInk);
      }
      ctx.setLineDash([]);
      escribirLeyenda(v[G.hover]);
    } else {
      escribirLeyenda(ult);
    }
  }
  function etiqueta(texto, x, yy, fondo, tinta) {
    ctx.fillStyle = fondo; ctx.fillRect(x + 1, yy - 9, 62, 18);
    ctx.fillStyle = tinta; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(texto, x + 5, yy);
  }
  function escribirLeyenda(c) {
    if (!c) { leyenda.textContent = ""; return; }
    var var_ = c[1] ? (c[4] / c[1] - 1) * 100 : 0, d = new Date(c[0]);
    leyenda.innerHTML = "";
    [["", d.toLocaleDateString("es-PY", { day: "numeric", month: "short" }) + " " + d.toLocaleTimeString("es-PY", { hour: "2-digit", minute: "2-digit", hour12: false })],
     ["A", num(c[1], D.dec)], ["M", num(c[2], D.dec)], ["m", num(c[3], D.dec)], ["C", num(c[4], D.dec)],
     ["", (var_ >= 0 ? "+" : "") + num(var_, 2) + " %"]].forEach(function (p, j) {
      var s = document.createElement("span");
      if (p[0]) { var b = document.createElement("b"); b.textContent = p[0] + " "; s.appendChild(b); }
      s.appendChild(document.createTextNode(p[1]));
      if (j === 5) s.className = var_ >= 0 ? "up" : "down";
      leyenda.appendChild(s);
    });
  }
  canvas.addEventListener("pointermove", function (e) {
    var r = canvas.getBoundingClientRect(), v = visibles(), paso = (G.w - 64) / Math.max(1, v.length);
    G.hover = Math.min(v.length - 1, Math.max(0, Math.floor((e.clientX - r.left) / paso)));
    G.mouseY = e.clientY - r.top; dibujar();
  });
  canvas.addEventListener("pointerleave", function () { G.hover = -1; G.mouseY = null; dibujar(); });

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
      "stop-venta": "Vende si el precio baja hasta el nivel que elijas (para cortar una pérdida)."
    };
    function elegirLado(l) {
      estadoOrden.lado = l; form.lado.value = l;
      document.querySelectorAll(".lado-tabs [data-lado]").forEach(function (b) { b.setAttribute("aria-selected", b.getAttribute("data-lado") === l ? "true" : "false"); });
      btn.className = "btn block lado-btn " + l;
      btn.textContent = (l === "compra" ? "Comprar " : "Vender ") + D.activo;
      form.todo.value = ""; actualizarTextos();
    }
    function elegirTipo(t) {
      estadoOrden.tipo = t; form.tipo.value = t;
      document.querySelectorAll(".tipos [data-tipo]").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-tipo") === t ? "true" : "false"); });
      campoPrecio.hidden = t === "mercado";
      if (t !== "mercado" && !form.precio.value && D.precio) form.precio.value = num(D.precio, D.dec);
      actualizarTextos();
    }
    function actualizarTextos() {
      ayuda.textContent = AYUDAS[estadoOrden.tipo === "mercado" ? "mercado" : estadoOrden.tipo + "-" + estadoOrden.lado];
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
        if (tipo === "limite" && lado === "compra" && lp >= actual) return "Una compra límite se activa cuando el precio baja: elige un precio menor al actual (" + px(actual) + ").";
        if (tipo === "limite" && lado === "venta" && lp <= actual) return "Una venta límite se activa cuando el precio sube: elige un precio mayor al actual (" + px(actual) + ").";
        if (tipo === "stop" && lado === "compra" && lp <= actual) return "Una compra stop se activa cuando el precio sube: elige un precio mayor al actual (" + px(actual) + ").";
        if (tipo === "stop" && lado === "venta" && lp >= actual) return "Un stop de venta se activa cuando el precio baja: elige un precio menor al actual (" + px(actual) + ").";
        if (form.todo.value !== "si" && m < 10) return "El mínimo de una orden límite o stop es de US$ 10.";
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
      var nombres = { mercado: "Mercado", limite: "Límite", stop: "Stop" };
      var filas = [
        ["Par", D.activo + "/USD"],
        ["Operación", (lado === "compra" ? "Compra" : "Venta") + " · " + nombres[tipo]],
        [tipo === "mercado" ? "Precio de referencia" : "Precio de activación", "US$ " + px(tipo === "mercado" ? D.precio : leerNum(form.precio.value))],
        ["Monto", form.todo.value === "si" ? "Todo lo disponible (" + cant(D.disp_u / 1e8) + " " + D.activo + ")" : usd(m)],
        ["Cantidad estimada", form.todo.value === "si" ? cant(D.disp_u / 1e8) + " " + D.activo : "≈ " + cant(m / p) + " " + D.activo],
        ["Comisión estimada", (D.comision ? "≈ " + usd((form.todo.value === "si" ? D.disp_u / 1e8 * p : m) * D.comision / 100) : "Sin comisión") ]
      ];
      resumen.innerHTML = "";
      filas.forEach(function (f) {
        var dt = document.createElement("dt"), dd = document.createElement("dd");
        dt.textContent = f[0]; dd.textContent = f[1]; resumen.appendChild(dt); resumen.appendChild(dd);
      });
      document.getElementById("d-nota").textContent = tipo === "mercado"
        ? "El precio final es el que se obtenga al ejecutar la orden y puede variar un poco respecto del de referencia."
        : "La orden queda abierta y reserva el saldo hasta que se ejecute o la canceles. Se ejecuta a precio de mercado cuando se alcance el nivel.";
      var ok = document.getElementById("d-ok");
      ok.className = "btn " + (lado === "compra" ? "primary compra" : "primary venta");
      ok.textContent = "Confirmar " + (lado === "compra" ? "compra" : "venta");
      if (dlg.showModal) dlg.showModal(); else enviar();
    });
    function enviar() {
      form.action = estadoOrden.tipo === "mercado" ? form.getAttribute("data-mercado") : form.getAttribute("data-prog");
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
