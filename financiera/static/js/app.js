/* Comportamiento general: confirmaciones, copiar al portapapeles y vista previa del aporte. */
(function () {
  "use strict";

  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute("data-confirmar");
    if (msg && !window.confirm(msg)) e.preventDefault();
  }, true);

  document.addEventListener("click", function (e) {
    var imp = e.target.closest("[data-imprimir]");
    if (imp) { window.print(); return; }
    var b = e.target.closest("[data-copiar]");
    if (!b || !navigator.clipboard) return;
    navigator.clipboard.writeText(b.getAttribute("data-copiar")).then(function () {
      var antes = b.textContent; b.textContent = "Copiado";
      setTimeout(function () { b.textContent = antes; }, 1600);
    });
  });

  // ---- precios en vivo: actualiza cada elemento con data-px / data-cambio ----
  var vivos = document.querySelector("[data-px]");
  function refrescar() {
    if (document.hidden) return;
    fetch("/mercado/precios.json", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        document.querySelectorAll("[data-px]").forEach(function (el) {
          var x = j[el.getAttribute("data-px")]; if (!x || el.textContent === x.precio) return;
          el.textContent = x.precio; el.classList.remove("pulso"); void el.offsetWidth; el.classList.add("pulso");
        });
        document.querySelectorAll("[data-cambio]").forEach(function (el) {
          var x = j[el.getAttribute("data-cambio")]; if (!x || !x.cambio) return;
          el.textContent = x.cambio; var t = el.classList.contains("up") || el.classList.contains("down") ? el : el.parentNode;
          t.classList.toggle("up", x.sube); t.classList.toggle("down", !x.sube);
        });
        var panel = document.getElementById("operar");
        if (panel && j[panel.getAttribute("data-activo")]) { panel.setAttribute("data-precio", j[panel.getAttribute("data-activo")].valor); panel.dispatchEvent(new Event("precio")); }
      }).catch(function () { /* sin conexión: se reintenta en el próximo ciclo */ });
  }
  if (vivos) setInterval(refrescar, 20000);

  // ---- panel de compra y venta ----
  (function () {
    var panel = document.getElementById("operar"); if (!panel) return;
    var form = panel.querySelector("form"), monto = form.querySelector("[name=monto]"), lado = form.querySelector("[name=lado]"), todo = form.querySelector("[name=todo]");
    var boton = form.querySelector("button[type=submit]"), est = form.querySelector("[data-estimado]"), disp = form.querySelector("[data-disponible]"), rot = form.querySelector("[data-rotulo]");
    var activo = panel.getAttribute("data-activo"), bloqueado = boton.disabled;
    function n2(n, dec) { var p = n.toFixed(dec).split("."); return p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".") + (p[1] ? "," + p[1] : ""); }
    function leerUsd(t) { var x = String(t || "").replace(/[^0-9.,]/g, ""); if (x.indexOf(",") >= 0) x = x.replace(/\./g, "").replace(",", "."); return parseFloat(x); }
    function tope() { return +panel.getAttribute(lado.value === "compra" ? "data-caja" : "data-tengo") / 100; }
    function pintar() {
      var compra = lado.value === "compra", precio = +panel.getAttribute("data-precio"), m = leerUsd(monto.value);
      rot.textContent = compra ? "Saldo disponible" : "Tienes en " + activo;
      disp.textContent = "US$ " + n2(tope(), 2);
      boton.textContent = (compra ? "Comprar " : "Vender ") + activo;
      boton.className = "btn primary block " + (compra ? "compra" : "venta");
      form.querySelector(".resumen-op .muted").textContent = compra ? "Recibes aprox." : "Recibes aprox. (en dólares)";
      if (!(m > 0) || !(precio > 0)) est.textContent = "—";
      else est.textContent = compra ? n2(m / precio, 8).replace(/,?0+$/, "") + " " + activo : "US$ " + n2(m, 2);
      var excede = m > tope() + 0.005;
      monto.setCustomValidity(excede ? (compra ? "No tienes saldo suficiente." : "No tienes tanto " + activo + ".") : "");
      boton.disabled = bloqueado;
    }
    function elegir(l) {
      lado.value = l; todo.value = ""; monto.value = "";
      panel.querySelectorAll(".lados button").forEach(function (b) { b.setAttribute("aria-selected", String(b.getAttribute("data-lado") === l)); });
      pintar();
    }
    panel.querySelectorAll(".lados button").forEach(function (b) { b.addEventListener("click", function () { if (!b.disabled) elegir(b.getAttribute("data-lado")); }); });
    form.querySelectorAll("[data-pct]").forEach(function (b) {
      b.addEventListener("click", function () {
        var p = +b.getAttribute("data-pct"), v = Math.floor(tope() * p) / 100;
        monto.value = n2(v, 2); todo.value = p === 100 && lado.value === "venta" ? "si" : ""; pintar();
      });
    });
    monto.addEventListener("input", function () { todo.value = ""; pintar(); });
    panel.addEventListener("precio", pintar);
    document.querySelectorAll('a[data-lado="venta"]').forEach(function (x) { x.addEventListener("click", function () { elegir("venta"); }); });
    if (/[?&]lado=venta/.test(location.search)) elegir("venta"); else pintar();
  })();

  var fuente = document.getElementById("datos-invertir");
  if (!fuente) return;
  var d = JSON.parse(fuente.textContent);
  var monto = document.getElementById("monto"), prev = document.getElementById("previa");

  function num(n, dec) { var s = Math.abs(n).toFixed(dec).split("."), i = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, "."); return (n < 0 ? "−" : "") + i + (s[1] ? "," + s[1] : ""); }
  function usd(cent) { return "US$ " + num(cent / 100, 2); }
  function leer(t) {
    var s = String(t || "").replace(/US\$|USD|\$|\s/g, "");
    if (s.indexOf(",") >= 0 && s.indexOf(".") >= 0) s = s.replace(/\./g, "").replace(",", ".");
    else if (s.indexOf(",") >= 0) s = s.replace(",", ".");
    else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, "");
    if (!/^\d{1,12}(\.\d{1,2})?$/.test(s)) return NaN;
    return Math.round(parseFloat(s) * 100);
  }
  function fila(color, titulo, detalle, valor) {
    var it = document.createElement("div"); it.className = "item";
    var dot = document.createElement("i"); dot.className = "dot"; dot.style.background = color;
    var g = document.createElement("div"); g.className = "grow";
    var t = document.createElement("div"); t.className = "t"; t.textContent = titulo;
    var s = document.createElement("div"); s.className = "d num"; s.textContent = detalle;
    var a = document.createElement("div"); a.className = "amt num"; a.textContent = valor;
    g.appendChild(t); g.appendChild(s); it.appendChild(dot); it.appendChild(g); it.appendChild(a);
    return it;
  }
  var riesgo = document.getElementById("confirmar-riesgo");
  function render() {
    var m = leer(monto.value), sel = document.querySelector("input[name=modelo]:checked");
    if (riesgo) {
      var fuera = !!sel && (d.fuera || []).indexOf(sel.value) >= 0;
      riesgo.hidden = !fuera;
      var cb = riesgo.querySelector("input");
      cb.required = fuera;
      if (!fuera) cb.checked = false;
    }
    document.querySelectorAll("[data-monto]").forEach(function (b) { b.setAttribute("aria-pressed", String(Math.round(+b.getAttribute("data-monto") * 100) === m)); });
    prev.textContent = "";
    if (!sel) return;
    if (sel.value === "saldo") {
      var ps = document.createElement("p"); ps.className = "small muted";
      ps.textContent = m >= d.minimo ? usd(m) + " quedan en tu saldo en dólares, listos para comprar monedas en Mercado." : "Escribe un monto desde " + usd(d.minimo) + ".";
      prev.appendChild(ps); return;
    }
    if (!(m >= d.minimo)) {
      var p = document.createElement("p"); p.className = "small muted"; p.textContent = "Escribe un monto desde " + usd(d.minimo) + " para ver qué se compraría a los precios de ahora.";
      prev.appendChild(p); return;
    }
    var caja = document.createElement("div"); caja.className = "prev"; var lista = document.createElement("div"); lista.className = "list";
    d.modelos[sel.value].forEach(function (par) {
      var a = par[0], pb = par[1], cent = Math.floor(m * pb / 10000), precio = parseFloat(d.precios[a] || "0"), info = d.activos[a] || { color: "#94A3B8" };
      var cant = precio > 0 ? (cent / 100 / precio) : 0;
      lista.appendChild(fila(info.color, a + " · " + num(pb / 100, 0) + "%", precio > 0 ? "≈ " + num(cant, cant >= 100 ? 2 : 6) + " " + a + " a US$ " + num(precio, precio >= 1 ? 2 : 4) : "sin precio cargado", usd(cent)));
    });
    caja.appendChild(lista); prev.appendChild(caja);
  }
  monto.addEventListener("input", render);
  document.querySelectorAll("input[name=modelo]").forEach(function (r) { r.addEventListener("change", render); });
  document.querySelectorAll("[data-monto]").forEach(function (b) { b.addEventListener("click", function () { monto.value = num(+b.getAttribute("data-monto"), 0); render(); }); });
  render();
})();
