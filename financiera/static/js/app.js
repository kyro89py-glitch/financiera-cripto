/* Comportamiento general: confirmaciones, copiar al portapapeles y vista previa del aporte. */
(function () {
  "use strict";

  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute("data-confirmar");
    if (msg && !window.confirm(msg)) e.preventDefault();
  }, true);

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copiar]");
    if (!b || !navigator.clipboard) return;
    navigator.clipboard.writeText(b.getAttribute("data-copiar")).then(function () { b.textContent = "Copiado"; });
  });

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
    var s = document.createElement("div"); s.className = "d mono"; s.textContent = detalle;
    var a = document.createElement("div"); a.className = "amt mono"; a.textContent = valor;
    g.appendChild(t); g.appendChild(s); it.appendChild(dot); it.appendChild(g); it.appendChild(a);
    return it;
  }
  function render() {
    var m = leer(monto.value), sel = document.querySelector("input[name=modelo]:checked");
    document.querySelectorAll("[data-monto]").forEach(function (b) { b.setAttribute("aria-pressed", String(Math.round(+b.getAttribute("data-monto") * 100) === m)); });
    prev.textContent = "";
    if (!sel) return;
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
