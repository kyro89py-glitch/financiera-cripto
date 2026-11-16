/* Gráfico de patrimonio: área con degradado, rangos, cruz y globo con fecha y valor. Sin librerías externas. */
(function () {
  "use strict";
  var caja = document.querySelector("[data-grafico='patrimonio']"), datosEl = document.getElementById("datos-patrimonio");
  if (!caja || !datosEl) return;
  var R = JSON.parse(datosEl.textContent), canvas = caja.querySelector("canvas"), tip = caja.querySelector(".graf-tip");
  var ctx = canvas.getContext("2d"), raiz = document.documentElement, hover = -1, W = 0, H = 0, dpr = 1;
  // El rango inicial es el del botón marcado (las claves del JSON llegan ordenadas alfabéticamente).
  var marcado = document.querySelector("[data-rango][aria-pressed='true']");
  var rango = marcado && R[marcado.getAttribute("data-rango")] ? marcado.getAttribute("data-rango") : Object.keys(R)[0];
  var MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  function col(v) { return getComputedStyle(raiz).getPropertyValue(v).trim(); }
  function usd(c) {
    var p = (Math.abs(c) / 100).toFixed(2).split(".");
    return (c < 0 ? "−" : "") + "US$ " + p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".") + "," + p[1];
  }
  function fecha(ms, conHora) {
    var d = new Date(ms), s = d.getDate() + " " + MESES[d.getMonth()];
    if (conHora) s += " " + ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
    return s;
  }
  function medir() {
    var r = caja.getBoundingClientRect(); dpr = window.devicePixelRatio || 1;
    W = Math.max(200, r.width); H = Math.max(160, r.height);
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
    dibujar();
  }
  var resumenEl = document.querySelector("[data-graf-resumen]");
  function resumir() {
    var s = R[rango] || [];
    if (!resumenEl || s.length < 2) return;
    var dif = s[s.length - 1][1] - s[0][1], pct = s[0][1] ? dif / s[0][1] * 100 : 0;
    resumenEl.className = "graf-resumen num small " + (dif >= 0 ? "up" : "down");
    resumenEl.textContent = (dif >= 0 ? "+" : "") + usd(dif) + (s[0][1] > 0 ? " (" + (pct >= 0 ? "+" : "") + pct.toFixed(2).replace(".", ",") + " %)" : "") + " en " +
      ({ "7D": "7 días", "1M": "1 mes", "3M": "3 meses", "1A": "1 año", "Todo": "todo el período" }[rango] || rango) + ", con depósitos y retiros";
  }
  function dibujar() {
    var s = R[rango] || [];
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
    if (s.length < 2) return;
    var min = Infinity, max = -Infinity;
    s.forEach(function (p) { min = Math.min(min, p[1]); max = Math.max(max, p[1]); });
    if (max === min) { max += 1; min -= 1; }
    var pad = (max - min) * 0.12, y0 = 10, y1 = H - 26;
    min -= pad; max += pad;
    var x = function (i) { return i / (s.length - 1) * (W - 2) + 1; };
    var y = function (v) { return y0 + (max - v) / (max - min) * (y1 - y0); };
    var sube = s[s.length - 1][1] >= s[0][1], linea = sube ? col("--up") : col("--down");
    var grad = ctx.createLinearGradient(0, y0, 0, y1);
    grad.addColorStop(0, linea + "38"); grad.addColorStop(1, linea + "00");
    ctx.beginPath(); ctx.moveTo(x(0), y(s[0][1]));
    for (var i = 1; i < s.length; i++) ctx.lineTo(x(i), y(s[i][1]));
    ctx.lineTo(x(s.length - 1), y1); ctx.lineTo(x(0), y1); ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath(); ctx.moveTo(x(0), y(s[0][1]));
    for (i = 1; i < s.length; i++) ctx.lineTo(x(i), y(s[i][1]));
    ctx.strokeStyle = linea; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.stroke();
    // fechas de los extremos
    ctx.fillStyle = col("--muted"); ctx.font = "11.5px " + col("--sans"); ctx.textBaseline = "alphabetic";
    ctx.textAlign = "left"; ctx.fillText(fecha(s[0][0], rango === "7D"), 2, H - 6);
    ctx.textAlign = "right"; ctx.fillText("Ahora", W - 2, H - 6);
    if (hover >= 0) {
      var hx = x(hover), hy = y(s[hover][1]);
      ctx.strokeStyle = col("--line-strong"); ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(hx, y0); ctx.lineTo(hx, y1); ctx.stroke(); ctx.setLineDash([]);
      ctx.beginPath(); ctx.arc(hx, hy, 4.5, 0, Math.PI * 2); ctx.fillStyle = linea; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = col("--surface"); ctx.stroke();
      tip.hidden = false;
      tip.innerHTML = "";
      var b = document.createElement("b"); b.textContent = usd(s[hover][1]); tip.appendChild(b);
      var dif = s[hover][1] - s[0][1], ch = document.createElement("span");
      ch.className = dif >= 0 ? "up" : "down"; ch.textContent = (dif >= 0 ? "+" : "") + usd(dif) + (s[0][1] ? " (" + (dif >= 0 ? "+" : "") + (dif / s[0][1] * 100).toFixed(2).replace(".", ",") + " %)" : "");
      tip.appendChild(ch);
      var sp = document.createElement("span"); sp.textContent = fecha(s[hover][0], rango === "7D" || rango === "1M"); tip.appendChild(sp);
      var tw = tip.offsetWidth; tip.style.left = Math.min(Math.max(hx - tw / 2, 0), W - tw) + "px";
    } else { tip.hidden = true; }
  }
  canvas.addEventListener("pointermove", function (e) {
    var s = R[rango] || [], r = canvas.getBoundingClientRect();
    hover = Math.round((e.clientX - r.left) / W * (s.length - 1)); hover = Math.max(0, Math.min(s.length - 1, hover)); dibujar();
  });
  canvas.addEventListener("pointerleave", function () { hover = -1; dibujar(); });
  document.querySelectorAll("[data-rango]").forEach(function (b) {
    b.addEventListener("click", function () {
      rango = b.getAttribute("data-rango"); hover = -1;
      document.querySelectorAll("[data-rango]").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      resumir(); dibujar();
    });
  });
  if (window.ResizeObserver) new ResizeObserver(medir).observe(caja); else window.addEventListener("resize", medir);
  resumir(); medir();
})();

/* Patrimonio animado: cuenta hasta el valor al abrir y se actualiza suave con cada precio en vivo. */
(function () {
  "use strict";
  var el = document.querySelector("[data-patrimonio]"), datos = document.getElementById("datos-vivo");
  if (!el || !datos) return;
  var V = JSON.parse(datos.textContent), actual = +el.getAttribute("data-patrimonio") || 0, mostrado = 0, anim = null;
  var quieto = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function usd(c) {
    var p = (Math.abs(c) / 100).toFixed(2).split(".");
    return (c < 0 ? "−" : "") + "US$ " + p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".") + "," + p[1];
  }
  function ir(destino, ms) {
    if (anim) cancelAnimationFrame(anim);
    if (quieto) { mostrado = destino; el.textContent = usd(destino); return; }
    var desde = mostrado, t0 = performance.now();
    (function paso(t) {
      var k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      mostrado = Math.round(desde + (destino - desde) * e); el.textContent = usd(mostrado);
      if (k < 1) anim = requestAnimationFrame(paso);
    })(t0);
  }
  ir(actual, 900);
  document.addEventListener("precios", function (e) {
    var P = e.detail.precios, total = 0;
    for (var a in V.ten) {
      if (a === "USD") { total += V.ten[a]; continue; }
      var px = P[a] ? P[a].valor : V.precios[a];
      if (px) total += Math.round(V.ten[a] / 1e8 * px * 100);
    }
    if (Math.abs(total - actual) >= 1) {
      el.classList.remove("tick-up", "tick-down"); void el.offsetWidth;
      el.classList.add(total > actual ? "tick-up" : "tick-down");
      actual = total; ir(total, 600);
    }
  });
})();

/* Personalizar el inicio: subir y bajar módulos con botones accesibles. */
(function () {
  "use strict";
  var lista = document.getElementById("orden-mods"), form = document.getElementById("f-panel");
  if (!lista || !form) return;
  lista.addEventListener("click", function (e) {
    var b = e.target.closest("[data-mover]"); if (!b) return;
    var li = b.closest("li"), dir = +b.getAttribute("data-mover");
    if (dir < 0 && li.previousElementSibling) lista.insertBefore(li, li.previousElementSibling);
    else if (dir > 0 && li.nextElementSibling) lista.insertBefore(li.nextElementSibling, li);
    b.focus();
  });
  form.addEventListener("submit", function () {
    form.orden.value = Array.prototype.map.call(lista.children, function (li) { return li.getAttribute("data-mod"); }).join(",");
  });
})();
