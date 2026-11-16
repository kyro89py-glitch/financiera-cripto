/* Financiera Cripto: service worker. Guarda solo archivos públicos (estilos, scripts, íconos) y la página sin conexión.
   Nunca guarda páginas con datos de la cuenta: la navegación siempre va a la red. */
var VERSION = "fc-v2";
var ESTATICOS = ["/sin-conexion", "/static/css/app.css", "/static/js/app.js", "/static/js/escena3d.js", "/static/js/graficos.js",
                 "/static/fonts/inter-400.woff", "/static/fonts/inter-600.woff", "/static/fonts/inter-display-700.woff", "/static/img/marca.svg",
                 "/static/img/icono-192.png", "/static/manifest.webmanifest"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(VERSION).then(function (c) { return c.addAll(ESTATICOS); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k !== VERSION; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (e) {
  var r = e.request;
  if (r.method !== "GET") return;
  var url = new URL(r.url);
  if (url.origin !== location.origin) return;
  if (r.mode === "navigate") {
    e.respondWith(fetch(r).catch(function () { return caches.match("/sin-conexion"); }));
    return;
  }
  if (url.pathname.indexOf("/static/") === 0) {
    // primero la red (los archivos llevan ?v=versión); sin conexión, lo guardado
    e.respondWith(fetch(r).then(function (resp) {
      var copia = resp.clone();
      if (resp.ok) caches.open(VERSION).then(function (c) { c.put(r, copia); });
      return resp;
    }).catch(function () { return caches.match(r, { ignoreSearch: true }); }));
  }
});
