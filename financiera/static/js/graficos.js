/* Gráfico de patrimonio: área con degradado, rangos, cruz y globo con fecha y valor. Sin librerías externas. */
(function () {
  "use strict";
  var caja = document.querySelector("[data-grafico='patrimonio']"), datosEl = document.getElementById("datos-patrimonio");
  if (!caja || !datosEl) return;
  var R = JSON.parse(datosEl.textContent), canvas = caja.querySelector("canvas"), tip = caja.querySelector(".graf-tip");
  var ctx = canvas.getContext("2d"), raiz = document.documentElement, rango = Object.keys(R)[0], hover = -1, W = 0, H = 0, dpr = 1;
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
      dibujar();
    });
  });
  if (window.ResizeObserver) new ResizeObserver(medir).observe(caja); else window.addEventListener("resize", medir);
  medir();
})();
