// Herramientas: conversor y calculadoras que se recalculan al escribir, y simulador con precios históricos (servidor).
(function () {
  "use strict";
  var nodo = document.getElementById("datos-herramientas");
  if (!nodo) return;
  var D = JSON.parse(nodo.textContent);
  function $(k) { return document.querySelector('[data-h="' + k + '"]'); }
  function leerNum(t) {
    t = String(t || "").trim().replace(/\s|US\$|₲|%/g, "");
    if (!t) return NaN;
    if (t.indexOf(",") >= 0) t = t.replace(/\./g, "").replace(",", ".");
    else if ((t.match(/\./g) || []).length > 1) t = t.replace(/\./g, "");
    return parseFloat(t);
  }
  function num(n, dec) {
    if (n == null || !isFinite(n)) return "—";
    var neg = n < 0, p = Math.abs(n).toFixed(dec).split(".");
    return (neg ? "−" : "") + p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".") + (dec ? "," + p[1] : "");
  }
  function decPx(p) { p = Math.abs(p); if (p >= 1 || p === 0) return 2; if (p >= 0.01) return 4; return Math.min(10, Math.ceil(-Math.log10(p)) + 3); }
  function usd(n) { return "US$ " + num(n, 2); }
  function signo(n, txt) { return (n > 0 ? "+" : "") + txt; }
  function cant(q, cod) { return num(q, q >= 1000 ? 2 : (q >= 1 ? 4 : 8)) + " " + cod; }
  function pintar(dl, filas) {
    dl.innerHTML = "";
    filas.forEach(function (f) {
      var d = document.createElement("div"), dt = document.createElement("dt"), dd = document.createElement("dd");
      dt.textContent = f[0]; dd.textContent = f[1]; dd.className = "num" + (f[2] ? " " + f[2] : ""); if (f[3]) d.className = "dest";
      d.appendChild(dt); d.appendChild(dd); dl.appendChild(d);
    });
  }
  function precioUsd(cod) { return cod === "USD" ? 1 : (cod === "PYG" ? (D.pyg ? 1 / D.pyg : NaN) : D.precios[cod]); }
  function enlazar(claves, fn) { claves.forEach(function (k) { var e = $(k); if (e) { e.addEventListener("input", fn); e.addEventListener("change", fn); } }); fn(); }

  // ---- conversor ----
  enlazar(["cv-monto", "cv-de", "cv-a"], function () {
    var m = leerNum($("cv-monto").value), de = $("cv-de").value, a = $("cv-a").value;
    var pd = precioUsd(de), pa = precioUsd(a), res = m * pd / pa;
    if (!isFinite(res)) { $("cv-res").textContent = "—"; $("cv-tasa").textContent = ""; return; }
    var dec = a === "USD" ? 2 : (a === "PYG" ? 0 : (res >= 1 ? 6 : 8));
    $("cv-res").textContent = num(res, dec) + " " + a;
    $("cv-tasa").textContent = "1 " + de + " = " + num(pd / pa, a === "PYG" ? 0 : decPx(pd / pa) + 2) + " " + a;
  });
  $("cv-invertir").addEventListener("click", function () {
    var de = $("cv-de"), a = $("cv-a"), t = de.value; de.value = a.value; a.value = t; de.dispatchEvent(new Event("change"));
  });

  // ---- comisiones ----
  enlazar(["co-monto", "co-tipo"], function () {
    var m = leerNum($("co-monto").value), t = $("co-tipo").value, dl = $("co-res");
    if (!(m > 0)) { pintar(dl, [["Comisión", "—"]]); return; }
    var c = D.comision_op / 100;
    if (t === "compra") pintar(dl, [["Comisión (" + num(D.comision_op, 2) + " %)", usd(m * c)], ["Recibes en la moneda", usd(m * (1 - c)), "", true]]);
    else if (t === "conversion") { var neto = m * (1 - c) * (1 - c); pintar(dl, [["Se cobra al vender y al comprar", num(D.comision_op, 2) + " % + " + num(D.comision_op, 2) + " %"], ["Comisión total", usd(m - neto)], ["Recibes en la otra moneda", usd(neto), "", true]]); }
    else if (t === "envio") pintar(dl, [["Comisión", "Sin comisión"], ["Recibe la otra persona", usd(m), "", true]]);
    else pintar(dl, [["Comisión anual (" + num(D.comision_anual, 2) + " %)", usd(m * D.comision_anual / 100)], ["Equivale por mes a", usd(m * D.comision_anual / 100 / 12)], ["Se aplica", "solo a carteras administradas, sobre el saldo promedio"]]);
  });

  // ---- rentabilidad ----
  function precioInicial(campo, sel) { var e = $(campo), p = D.precios[$(sel).value]; if (p && !e.dataset.tocado) e.value = num(p, decPx(p)); }
  ["re-pc", "re-pv", "ri-entrada", "ri-stop", "ri-obj"].forEach(function (k) { $(k).addEventListener("input", function () { $(k).dataset.tocado = "1"; }); });
  function rentab() {
    var m = leerNum($("re-monto").value), pc = leerNum($("re-pc").value), pv = leerNum($("re-pv").value), c = leerNum($("re-com").value) / 100 || 0, cod = $("re-activo").value;
    if (!(m > 0 && pc > 0 && pv > 0)) { pintar($("re-res"), [["Resultado", "—"]]); return; }
    var u = m * (1 - c) / pc, bruto = u * pv, neto = bruto * (1 - c), r = neto - m, eq = pc / ((1 - c) * (1 - c));
    pintar($("re-res"), [["Compras", cant(u, cod)], ["Al vender recibes", usd(neto)], ["Comisiones pagadas", usd(m * c + bruto * c)],
      ["Resultado", signo(r, usd(r)), r >= 0 ? "up" : "down", true], ["Rentabilidad", signo(r, num(r / m * 100, 2) + " %"), r >= 0 ? "up" : "down"],
      ["Precio para no perder", "US$ " + num(eq, decPx(eq))]]);
  }
  $("re-activo").addEventListener("change", function () { delete $("re-pc").dataset.tocado; delete $("re-pv").dataset.tocado; precioInicial("re-pc", "re-activo"); precioInicial("re-pv", "re-activo"); rentab(); });
  precioInicial("re-pc", "re-activo"); precioInicial("re-pv", "re-activo");
  enlazar(["re-monto", "re-pc", "re-pv", "re-com"], rentab);

  // ---- riesgo ----
  function riesgo() {
    var cap = leerNum($("ri-capital").value), pct = leerNum($("ri-pct").value), e = leerNum($("ri-entrada").value), s = leerNum($("ri-stop").value), o = leerNum($("ri-obj").value), cod = $("ri-activo").value;
    if (!(cap > 0 && pct > 0 && e > 0 && s > 0) || s === e) { pintar($("ri-res"), [["Tamaño de posición", "Completa capital, riesgo, entrada y stop"]]); return; }
    var porU = Math.abs(e - s), maxP = cap * pct / 100, u = maxP / porU, pos = u * e, filas = [];
    filas.push(["Pérdida máxima aceptada", usd(maxP)]);
    filas.push(["Distancia al stop", num(porU / e * 100, 2) + " %"]);
    filas.push(["Puedes comprar hasta", cant(u, cod), "", true]);
    filas.push(["Tamaño de la posición", usd(pos) + " (" + num(pos / cap * 100, 1) + " % del capital)", pos > cap ? "down" : ""]);
    if (pos > cap) filas.push(["Atención", "Necesitarías más capital del que tienes: aleja el stop o baja el riesgo"]);
    if (o > 0) { var g = Math.abs(o - e) * u; filas.push(["Ganancia si llega al objetivo", usd(g), "up"]); filas.push(["Relación riesgo / beneficio", "1 : " + num(Math.abs(o - e) / porU, 2)]); }
    pintar($("ri-res"), filas);
  }
  $("ri-activo").addEventListener("change", function () {
    ["ri-entrada", "ri-stop", "ri-obj"].forEach(function (k) { delete $(k).dataset.tocado; });
    var p = D.precios[$("ri-activo").value]; if (p) { $("ri-entrada").value = num(p, decPx(p)); $("ri-stop").value = num(p * 0.95, decPx(p)); $("ri-obj").value = num(p * 1.1, decPx(p)); }
    riesgo();
  });
  (function () { var p = D.precios[$("ri-activo").value]; if (p) { $("ri-entrada").value = num(p, decPx(p)); $("ri-stop").value = num(p * 0.95, decPx(p)); $("ri-obj").value = num(p * 1.1, decPx(p)); } })();
  enlazar(["ri-capital", "ri-pct", "ri-entrada", "ri-stop", "ri-obj"], riesgo);

  // ---- simulador ----
  var fSim = $("si-form"), res = $("si-res"), cv = $("si-graf");
  function grafico(serie) {
    var W = cv.clientWidth, H = cv.clientHeight, dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr;
    var c = cv.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, H);
    var max = 0; serie.forEach(function (p) { max = Math.max(max, p[1], p[2]); }); max = max * 1.08 || 1;
    var cs = getComputedStyle(document.documentElement), col = function (v) { return cs.getPropertyValue(v).trim(); };
    var X = function (i) { return 8 + i / Math.max(1, serie.length - 1) * (W - 16); }, Y = function (v) { return H - 18 - v / max * (H - 30); };
    c.strokeStyle = col("--line"); c.lineWidth = 1; [0.25, 0.5, 0.75, 1].forEach(function (f) { c.beginPath(); c.moveTo(0, Y(max * f / 1.08)); c.lineTo(W, Y(max * f / 1.08)); c.stroke(); });
    [[1, col("--muted"), [5, 4]], [2, col("--accent"), []]].forEach(function (s) {
      c.strokeStyle = s[1]; c.lineWidth = 2; c.setLineDash(s[2]); c.beginPath();
      serie.forEach(function (p, i) { if (i) c.lineTo(X(i), Y(p[s[0]])); else c.moveTo(X(i), Y(p[s[0]])); }); c.stroke();
    });
    c.setLineDash([]); c.fillStyle = col("--muted"); c.font = "11px " + col("--sans");
    var f = function (t) { var d = new Date(t); return d.toLocaleDateString("es-PY", { month: "short", year: "2-digit" }); };
    c.textAlign = "left"; c.fillText(f(serie[0][0]), 8, H - 4); c.textAlign = "right"; c.fillText(f(serie[serie.length - 1][0]), W - 8, H - 4);
  }
  fSim.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = new URLSearchParams(new FormData(fSim)).toString(), btn = fSim.querySelector("button");
    btn.disabled = true; res.innerHTML = '<p class="small muted">Calculando…</p>';
    fetch("/herramientas/simular.json?" + q, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        btn.disabled = false; res.innerHTML = "";
        if (j.error) { var p = document.createElement("p"); p.className = "small error-txt"; p.textContent = j.error; res.appendChild(p); cv.hidden = true; return; }
        var dl = document.createElement("dl"); dl.className = "herr-dl si-dl"; res.appendChild(dl);
        pintar(dl, [["Compras", j.compras + " de " + usd(j.invertido / 100 / j.compras)], ["Invertido", usd(j.invertido / 100)],
          ["Valdría hoy", usd(j.valor / 100), j.resultado >= 0 ? "up" : "down", true],
          ["Resultado", signo(j.resultado, usd(j.resultado / 100) + " (" + num(j.pct, 1) + " %)"), j.resultado >= 0 ? "up" : "down"],
          ["Precio promedio de compra", "US$ " + num(j.precio_medio, decPx(j.precio_medio))], ["Precio hoy", "US$ " + num(j.precio_actual, decPx(j.precio_actual))],
          ["Si hubieras invertido todo el primer día", usd(j.unico_valor / 100) + " (" + signo(j.unico_pct, num(j.unico_pct, 1)) + " %)"]]);
        var n = document.createElement("p"); n.className = "xs muted";
        n.textContent = "Desde " + new Date(j.desde).toLocaleDateString("es-PY") + ". Precios de " + j.fuente + ". Línea punteada: lo invertido; línea llena: lo que valía.";
        res.appendChild(n); cv.hidden = false; grafico(j.serie);
      })
      .catch(function () { btn.disabled = false; res.innerHTML = '<p class="small error-txt">No se pudo calcular. Revisa tu conexión.</p>'; });
  });
})();
