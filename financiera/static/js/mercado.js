// Mapa de calor de Mercados: detalle de cada moneda al pasar el cursor, enfocar con el teclado o tocar.
// En pantallas táctiles el primer toque muestra el detalle y el segundo abre el gráfico.
(function () {
  "use strict";
  var det = document.getElementById("mapa-det");
  if (!det) return;
  var armado = null, tactil = false;
  function linea(et, valor, clase) {
    var d = document.createElement("div"), dt = document.createElement("span"), dd = document.createElement("b");
    dt.textContent = et; dd.textContent = valor; dd.className = "num" + (clase ? " " + clase : "");
    d.appendChild(dt); d.appendChild(dd); return d;
  }
  function mostrar(tile) {
    var m;
    try { m = JSON.parse(tile.getAttribute("data-det")); } catch (e) { return; }
    document.querySelectorAll(".tile.sel").forEach(function (t) { t.classList.remove("sel"); });
    tile.classList.add("sel");
    det.innerHTML = "";
    var cab = document.createElement("div"); cab.className = "md-cab";
    var n = document.createElement("b"); n.textContent = m.codigo; cab.appendChild(n);
    var s = document.createElement("span"); s.className = "muted small"; s.textContent = m.nombre; cab.appendChild(s);
    det.appendChild(cab);
    var g = document.createElement("div"); g.className = "md-datos";
    g.appendChild(linea("Precio", m.precio));
    g.appendChild(linea("24 h", m.d24, m.s24 ? "up" : "down"));
    g.appendChild(linea("7 días", m.d7, m.s7 ? "up" : "down"));
    g.appendChild(linea("Capitalización", m.cap));
    g.appendChild(linea("Volumen 24 h", m.vol));
    det.appendChild(g);
    var acc = document.createElement("div"); acc.className = "md-acc";
    [["Ver gráfico", tile.getAttribute("href"), "btn sm primary"], ["Ficha", m.ficha, "btn sm"]].forEach(function (x) {
      var a = document.createElement("a"); a.textContent = x[0]; a.href = x[1]; a.className = x[2]; acc.appendChild(a);
    });
    det.appendChild(acc);
  }
  document.querySelectorAll(".mapa .tile[data-det]").forEach(function (t) {
    t.addEventListener("pointerdown", function (e) { tactil = e.pointerType === "touch" || e.pointerType === "pen"; });
    t.addEventListener("pointerenter", function (e) { if (e.pointerType === "mouse") mostrar(t); });
    t.addEventListener("focus", function () { mostrar(t); });
    t.addEventListener("click", function (e) {
      // al tocar, el foco ya mostró el detalle: el primer toque solo "arma" la moneda y el segundo navega
      if (tactil && armado !== t) { e.preventDefault(); armado = t; mostrar(t); }
    });
  });
})();
