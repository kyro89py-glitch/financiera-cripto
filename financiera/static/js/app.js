/* Comportamiento general: confirmaciones, copiar al portapapeles y vista previa del aporte. */
(function () {
  "use strict";

  // Confirmaciones con un diálogo propio (no el del navegador): accesible, con foco atrapado y cierre con Escape.
  var dlgConf = null, pendiente = null;
  function dialogoConfirmar() {
    if (dlgConf) return dlgConf;
    dlgConf = document.createElement("dialog");
    dlgConf.className = "confirmar"; dlgConf.setAttribute("aria-labelledby", "conf-t");
    var h = document.createElement("h3"); h.id = "conf-t"; h.textContent = "Confirmar";
    var p = document.createElement("p"); p.className = "small"; p.id = "conf-msg";
    var fila = document.createElement("div"); fila.className = "row"; fila.style.justifyContent = "flex-end";
    var no = document.createElement("button"); no.type = "button"; no.className = "btn"; no.textContent = "Cancelar";
    var si = document.createElement("button"); si.type = "button"; si.className = "btn primary"; si.textContent = "Confirmar";
    no.addEventListener("click", function () { dlgConf.close(); });
    si.addEventListener("click", function () {
      var x = pendiente; dlgConf.close();
      if (!x) return;
      x.form.setAttribute("data-confirmado", "1");
      if (x.form.requestSubmit) x.form.requestSubmit(x.boton || undefined); else x.form.submit();
    });
    dlgConf.addEventListener("close", function () { pendiente = null; });
    fila.appendChild(no); fila.appendChild(si); dlgConf.appendChild(h); dlgConf.appendChild(p); dlgConf.appendChild(fila);
    document.body.appendChild(dlgConf);
    return dlgConf;
  }
  document.addEventListener("submit", function (e) {
    var f = e.target, msg = f.getAttribute("data-confirmar");
    if (!msg) return;
    if (f.getAttribute("data-confirmado")) { f.removeAttribute("data-confirmado"); return; }
    e.preventDefault(); e.stopPropagation();
    var d = dialogoConfirmar();
    if (!d.showModal) { if (window.confirm(msg)) { f.setAttribute("data-confirmado", "1"); f.submit(); } return; }
    pendiente = { form: f, boton: e.submitter };
    d.querySelector("#conf-msg").textContent = msg;
    d.showModal();
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
  var vivos = document.querySelector("[data-px], [data-vivo], [data-mapa]");
  var anterior = {};
  function refrescar() {
    if (document.hidden) return;
    fetch("/mercado/precios.json", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.precios) return;
        var P = j.precios;
        document.querySelectorAll("[data-px]").forEach(function (el) {
          var c = el.getAttribute("data-px"), x = P[c]; if (!x || el.textContent === x.precio) return;
          var prev = anterior[c];
          el.textContent = x.precio;
          el.classList.remove("tick-up", "tick-down", "pulso"); void el.offsetWidth;
          el.classList.add(prev == null ? "pulso" : (x.valor >= prev ? "tick-up" : "tick-down"));
          if (el.hasAttribute("data-tick")) { el.classList.toggle("up", x.sube); el.classList.toggle("down", !x.sube); }
        });
        document.querySelectorAll("[data-cambio]").forEach(function (el) {
          var x = P[el.getAttribute("data-cambio")]; if (!x || !x.cambio) return;
          el.textContent = x.cambio; var t = el.classList.contains("up") || el.classList.contains("down") ? el : el.parentNode;
          t.classList.toggle("up", x.sube); t.classList.toggle("down", !x.sube);
        });
        [["data-max", "max"], ["data-min", "min"], ["data-vol", "vol"]].forEach(function (k) {
          document.querySelectorAll("[" + k[0] + "]").forEach(function (el) { var x = P[el.getAttribute(k[0])]; if (x && x[k[1]]) el.textContent = x[k[1]]; });
        });
        document.querySelectorAll("[data-mapa]").forEach(function (el) {
          var x = P[el.getAttribute("data-mapa")]; if (!x) return;
          el.classList.toggle("up", x.c >= 0); el.classList.toggle("down", x.c < 0);
          el.style.setProperty("--a", Math.min(1, 0.25 + Math.abs(x.c) / 6).toFixed(2));
          var t = el.querySelector(".pc"); if (t) t.textContent = x.cambio;
        });
        document.querySelectorAll("[data-vivo]").forEach(function (el) {
          el.classList.toggle("on", !!j.vivo);
          el.lastElementChild.textContent = j.vivo ? "En vivo · " + (j.fuente || "") : "Última actualización hace " + (j.seg >= 120 ? Math.round(j.seg / 60) + " min" : j.seg + " s");
        });
        for (var c in P) anterior[c] = P[c].valor;
        var panel = document.getElementById("operar");
        if (panel && panel.hasAttribute("data-activo") && P[panel.getAttribute("data-activo")]) { panel.setAttribute("data-precio", P[panel.getAttribute("data-activo")].valor); panel.dispatchEvent(new Event("precio")); }
        try { document.dispatchEvent(new CustomEvent("precios", { detail: j })); } catch (e) { /* navegador antiguo */ }
      }).catch(function () { /* sin conexión: se reintenta en el próximo ciclo */ });
  }
  if (vivos) { refrescar(); setInterval(refrescar, 3000); }

  // ---- buscador en vivo de tablas y selects que se envían solos ----
  document.querySelectorAll("[data-filtro-tabla]").forEach(function (inp) {
    var tabla = document.getElementById(inp.getAttribute("data-filtro-tabla")); if (!tabla) return;
    var aviso = document.getElementById("sin-resultados");
    inp.addEventListener("input", function () {
      var q = inp.value.trim().toLowerCase(), n = 0;
      tabla.querySelectorAll("tbody tr[data-buscar]").forEach(function (tr) {
        var ok = !q || tr.getAttribute("data-buscar").indexOf(q) >= 0; tr.hidden = !ok; if (ok) n++;
      });
      if (aviso) aviso.hidden = n > 0;
    });
  });
  document.querySelectorAll("select[data-autoenvio]").forEach(function (sel) {
    sel.addEventListener("change", function () { sel.form.submit(); });
  });

  // ---- método de depósito: muestra las instrucciones del elegido ----
  document.querySelectorAll("input[name=metodo]").forEach(function (r) {
    function pintar() {
      if (!r.checked) return;
      document.querySelectorAll("[data-metodo-info]").forEach(function (b) { b.hidden = b.getAttribute("data-metodo-info") !== r.value; });
      var pyg = document.querySelector("input[name=moneda][value=PYG]");
      if (pyg) { pyg.disabled = r.value === "usdt"; if (pyg.disabled && pyg.checked) { document.querySelector("input[name=moneda][value=USD]").checked = true; } }
    }
    r.addEventListener("change", pintar); pintar();
  });

  // ---- pestañas simples (Inicio: mercados destacados) ----
  document.querySelectorAll(".tabs-sec").forEach(function (barra) {
    if (document.getElementById("datos-trading")) return;  // la pantalla de trading maneja las suyas
    var tabs = barra.querySelectorAll("[role=tab]");
    tabs.forEach(function (t) {
      t.addEventListener("click", function () {
        tabs.forEach(function (x) { var on = x === t; x.setAttribute("aria-selected", on ? "true" : "false"); document.getElementById(x.getAttribute("aria-controls")).hidden = !on; });
      });
    });
  });

  // ---- app instalable ----
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js").catch(function () {}); });
  }

  // ---- enviar a otro cliente ----
  (function () {
    var f = document.getElementById("datos-enviar"); if (!f) return;
    var d = JSON.parse(f.textContent), form = document.querySelector("form.enviar");
    var activo = form.querySelector("[name=activo]"), monto = form.querySelector("[name=monto]"), todo = form.querySelector("[name=todo]");
    var tengo = form.querySelector("[data-tengo]"), destino = form.querySelector("[name=destino]"), info = document.getElementById("destino-info");
    function n2(n) { var p = n.toFixed(2).split("."); return p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".") + "," + p[1]; }
    function pintar() { tengo.textContent = "US$ " + n2((d.tengo[activo.value] || 0) / 100); }
    activo.addEventListener("change", function () { todo.value = ""; pintar(); });
    monto.addEventListener("input", function () { todo.value = ""; });
    form.querySelector("[data-todo]").addEventListener("click", function () { monto.value = n2((d.tengo[activo.value] || 0) / 100); todo.value = "si"; });
    var reloj, ultimo = "";
    function consultar() {
      var q = destino.value.trim(); if (q === ultimo) return; ultimo = q;
      if (q.length < 5) { info.textContent = ""; info.className = "small"; return; }
      fetch("/cliente/enviar/destinatario?q=" + encodeURIComponent(q), { credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return (r.ok || r.status === 429) ? r.json() : null; })
        .then(function (j) { if (!j || destino.value.trim() !== q) return; info.textContent = j.texto; info.className = "small " + (j.ok ? "up" : "down"); })
        .catch(function () {});
    }
    destino.addEventListener("input", function () { clearTimeout(reloj); reloj = setTimeout(consultar, 450); });
    destino.addEventListener("blur", consultar);
    pintar(); if (destino.value) consultar();
  })();

  // ---- convertir ----
  (function () {
    var f = document.getElementById("datos-convertir"); if (!f) return;
    var d = JSON.parse(f.textContent), form = document.querySelector("form.convertir"), monto = form.querySelector("[name=monto]");
    var de = form.querySelector("[name=de]"), a = form.querySelector("[name=a]"), todo = form.querySelector("[name=todo]");
    var tengo = form.querySelector("[data-tengo]"), recibe = form.querySelector("[data-recibe]");
    function n2(n, dec) { var p = n.toFixed(dec).split("."); return p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".") + (p[1] ? "," + p[1] : ""); }
    function leerUsd(t) { var x = String(t || "").replace(/[^0-9.,]/g, ""); if (x.indexOf(",") >= 0) x = x.replace(/\./g, "").replace(",", "."); return parseFloat(x); }
    function tope() { return (d.tengo[de.value] || 0) / 100; }
    function pintar() {
      var m = leerUsd(monto.value), p = d.precios[a.value];
      tengo.textContent = "US$ " + n2(tope(), 2);
      if (de.value === a.value) { recibe.textContent = "Elige otra moneda"; monto.setCustomValidity("Elige dos monedas distintas."); return; }
      monto.setCustomValidity(m > tope() + 0.005 ? "No tienes tanto " + de.value + "." : "");
      if (!(m > 0)) recibe.textContent = "—";
      else recibe.textContent = a.value === "USD" ? "US$ " + n2(m, 2) : (p ? n2(m / p, 8).replace(/,?0+$/, "") + " " + a.value : "—");
    }
    form.querySelectorAll("[data-pct]").forEach(function (b) {
      b.addEventListener("click", function () { var pc = +b.getAttribute("data-pct"); monto.value = n2(Math.floor(tope() * pc) / 100, 2); todo.value = pc === 100 && de.value !== "USD" ? "si" : ""; pintar(); });
    });
    monto.addEventListener("input", function () { todo.value = ""; pintar(); });
    de.addEventListener("change", function () { todo.value = ""; monto.value = ""; pintar(); });
    a.addEventListener("change", pintar);
    pintar();
  })();

  // ---- panel de compra y venta ----
  (function () {
    var panel = document.getElementById("operar"); if (!panel || !panel.hasAttribute("data-activo")) return;
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

  // ---- diálogos genéricos: [data-abrir="id"] abre, [data-cerrar] cierra ----
  document.addEventListener("click", function (e) {
    var a = e.target.closest("[data-abrir]");
    if (a) { var d = document.getElementById(a.getAttribute("data-abrir")); if (d && d.showModal && !d.open) d.showModal(); return; }
    var c = e.target.closest("dialog [data-cerrar]");
    if (c) { var dl = c.closest("dialog"); if (dl.open) dl.close(); }
  });

  // ---- estado de carga: al enviar un formulario, el botón muestra un giro y no se puede tocar dos veces ----
  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented) return;
    var f = e.target, b = e.submitter || f.querySelector("button[type=submit], button:not([type])");
    if (!b || f.method === "dialog" || f.getAttribute("method") === "get" || !f.getAttribute("method")) return;
    setTimeout(function () { b.setAttribute("data-cargando", ""); }, 0);
  });
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("[data-cargando]").forEach(function (b) { b.removeAttribute("data-cargando"); });
  });
  // ---- la pestaña activa de las barras con desplazamiento queda a la vista ----
  document.querySelectorAll(".subnav [aria-current='page'], .chips [aria-current='true']").forEach(function (el) {
    var c = el.parentElement;
    if (c.scrollWidth > c.clientWidth) c.scrollLeft = el.offsetLeft - c.clientWidth / 2 + el.clientWidth / 2;
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
    var s = document.createElement("div"); s.className = "d num"; s.textContent = detalle;
    var a = document.createElement("div"); a.className = "amt num"; a.textContent = valor;
    g.appendChild(t); g.appendChild(s); it.appendChild(dot); it.appendChild(g); it.appendChild(a);
    return it;
  }
  var riesgo = document.getElementById("confirmar-riesgo");
  function render() {
    var gs = document.querySelector("input[name=moneda][value=PYG]"), enGs = !!gs && gs.checked, cd = document.getElementById("cambio-dep");
    var rot = document.getElementById("rotulo-monto");
    if (rot) rot.textContent = enGs ? "Monto en guaraníes" : "Monto en dólares";
    monto.setAttribute("inputmode", enGs ? "numeric" : "decimal");
    var m = enGs ? Math.floor(parseInt(String(monto.value).replace(/[^0-9]/g, "") || "0", 10) * 100 / +cd.getAttribute("data-cambio")) : leer(monto.value);
    var sel = document.querySelector("input[name=modelo]:checked");
    if (riesgo) {
      var fuera = !!sel && (d.fuera || []).indexOf(sel.value) >= 0;
      riesgo.hidden = !fuera;
      var cb = riesgo.querySelector("input");
      cb.required = fuera;
      if (!fuera) cb.checked = false;
    }
    document.querySelectorAll("[data-monto]").forEach(function (b) { b.setAttribute("aria-pressed", String(Math.round(+b.getAttribute("data-monto") * 100) === m)); });
    prev.textContent = "";
    if (enGs && m > 0) { var pg = document.createElement("p"); pg.className = "small"; pg.textContent = "Se acreditan " + usd(m) + "."; prev.appendChild(pg); }
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
  document.querySelectorAll("input[name=moneda]").forEach(function (r) { r.addEventListener("change", render); });
  document.querySelectorAll("input[name=modelo]").forEach(function (r) { r.addEventListener("change", render); });
  document.querySelectorAll("[data-monto]").forEach(function (b) { b.addEventListener("click", function () { monto.value = num(+b.getAttribute("data-monto"), 0); render(); }); });
  render();

})();
