// Mi cuenta: recorte de fotografía antes de subirla y disponibilidad del nombre de usuario.
// La validación real (tipo, tamaño, contenido) la hace el servidor; acá solo se evita un viaje inútil.
(function () {
  "use strict";
  var MAX = 6 * 1024 * 1024, TIPOS = ["image/jpeg", "image/png", "image/webp"];
  var form = document.getElementById("f-foto"), dlg = document.getElementById("d-foto"), cv = document.getElementById("recorte");
  var err = document.getElementById("foto-error");
  if (form && dlg && cv && window.createImageBitmap && dlg.showModal) {
    var ctx = cv.getContext("2d"), img = null, zoom = 1, giro = 0, dx = 0, dy = 0, L = cv.width;
    var rz = document.getElementById("recorte-zoom");
    var lados = function () { return giro % 2 ? [img.height, img.width] : [img.width, img.height]; };
    var base = function () { var l = lados(); return L / Math.min(l[0], l[1]); };
    var limitar = function () {
      var l = lados(), e = base() * zoom, mx = Math.max(0, (l[0] * e - L) / 2), my = Math.max(0, (l[1] * e - L) / 2);
      dx = Math.min(mx, Math.max(-mx, dx)); dy = Math.min(my, Math.max(-my, dy));
    };
    var pintar = function (c, lado) {
      var k = lado / L, e = base() * zoom * k;
      c.save(); c.fillStyle = "#fff"; c.fillRect(0, 0, lado, lado);
      c.translate(lado / 2 + dx * k, lado / 2 + dy * k); c.rotate(giro * Math.PI / 2); c.scale(e, e);
      c.imageSmoothingQuality = "high"; c.drawImage(img, -img.width / 2, -img.height / 2); c.restore();
    };
    var dibujar = function () { if (img) { limitar(); pintar(ctx, L); } };
    var decir = function (t) { if (err) err.textContent = t; };
    form.addEventListener("change", function (e) {
      var inp = e.target.closest("[data-foto]"), f = inp && inp.files && inp.files[0];
      if (!f) return;
      decir("");
      if (TIPOS.indexOf(f.type) < 0) { inp.value = ""; return decir("Ese archivo no es una imagen JPG, PNG o WebP."); }
      if (f.size > MAX) { inp.value = ""; return decir("La imagen pesa más de 6 MB. Elige una más liviana."); }
      createImageBitmap(f).then(function (b) {
        img = b; zoom = 1; giro = 0; dx = dy = 0; rz.value = 1; dibujar(); dlg.showModal();
      }).catch(function () { inp.value = ""; decir("No pudimos abrir esa imagen. Prueba con otra."); });
      inp.value = "";
    });
    rz.addEventListener("input", function () { zoom = parseFloat(rz.value) || 1; dibujar(); });
    document.getElementById("recorte-girar").addEventListener("click", function () { giro = (giro + 1) % 4; dx = dy = 0; dibujar(); });
    var p0 = null;
    cv.addEventListener("pointerdown", function (e) { p0 = [e.clientX, e.clientY, dx, dy]; cv.setPointerCapture(e.pointerId); });
    cv.addEventListener("pointermove", function (e) {
      if (!p0) return;
      var k = L / cv.getBoundingClientRect().width; dx = p0[2] + (e.clientX - p0[0]) * k; dy = p0[3] + (e.clientY - p0[1]) * k; dibujar();
    });
    ["pointerup", "pointercancel"].forEach(function (n) { cv.addEventListener(n, function () { p0 = null; }); });
    cv.addEventListener("wheel", function (e) {
      e.preventDefault(); zoom = Math.min(4, Math.max(1, zoom - e.deltaY * 0.002)); rz.value = zoom; dibujar();
    }, { passive: false });
    document.getElementById("recorte-ok").addEventListener("click", function () {
      if (!img) return;
      var btn = this, fin = document.createElement("canvas"); fin.width = fin.height = 512; pintar(fin.getContext("2d"), 512);
      btn.disabled = true;
      fin.toBlob(function (blob) {
        var d = new FormData(); d.append("csrf", form.querySelector("[name=csrf]").value); d.append("foto", blob, "foto.jpg");
        fetch(form.action, { method: "POST", body: d, credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
          .then(function () { location.href = location.pathname + "#foto"; location.reload(); })
          .catch(function () { btn.disabled = false; dlg.close(); decir("No se pudo subir la foto. Revisa tu conexión e inténtalo de nuevo."); });
      }, "image/jpeg", 0.9);
    });
  }

  var campo = document.querySelector("[data-usuario-disp]"), est = document.getElementById("usuario-estado");
  if (campo && est) {
    var t = null, n = 0, inicial = campo.value;
    campo.addEventListener("input", function () {
      clearTimeout(t); est.className = "xs"; est.textContent = "";
      var v = campo.value.trim();
      if (!v || v === inicial) return;
      t = setTimeout(function () {
        var mio = ++n;
        fetch(campo.getAttribute("data-usuario-disp") + "?u=" + encodeURIComponent(v), { credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            if (mio !== n) return;
            est.className = "xs " + (j.ok ? "ok" : "bad"); est.textContent = j.texto || (j.ok ? "Disponible" : "No disponible");
          }).catch(function () {});
      }, 350);
    });
  }
})();
