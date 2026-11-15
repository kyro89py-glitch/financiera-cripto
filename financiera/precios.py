"""Precios de los activos: carga manual o desde CoinGecko, historial y control de antigüedad."""
from decimal import Decimal

import click
import requests
from flask import current_app

from . import auditoria, db
from .dinero import fmt_precio
from .tiempo import ahora, leer, minutos_desde


class ErrorPrecio(Exception):
    pass


def activos(solo_habilitados=False):
    return db.todos("SELECT * FROM activos" + (" WHERE habilitado = 1" if solo_habilitados else "") + " ORDER BY orden")


def vigentes():
    out = {}
    for r in db.todos("SELECT * FROM precios"):
        out[r["activo"]] = {
            "precio": Decimal(r["precio"]),
            "cambio": Decimal(r["cambio_24h"]) if r["cambio_24h"] is not None else None,
            "fuente": r["fuente"],
            "ts": r["ts"],
            "volumen": r["volumen_24h"],
            "cap": r["cap_mercado"],
            "max": Decimal(r["max_24h"]) if r["max_24h"] else None,
            "min": Decimal(r["min_24h"]) if r["min_24h"] else None,
        }
    return out


CATEGORIAS = {"principal": "Principales", "estable": "Estables", "capa1": "Capa 1", "capa2": "Capa 2", "defi": "DeFi",
              "memes": "Memes"}


def registrar(activo, precio, cambio=None, fuente="manual", ts=None, historial_min=0, extra=None):
    """Guarda el precio vigente. historial_min > 0: solo agrega un punto al historial si el último tiene al menos esos
    minutos (para las actualizaciones en vivo, que llegan cada pocos segundos). extra: volumen, cap, max, min."""
    ts = ts or ahora()
    e = extra or {}
    with db.transaccion() as c:
        c.execute(
            "INSERT INTO precios (activo, precio, cambio_24h, fuente, ts, volumen_24h, cap_mercado, max_24h, min_24h)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(activo) DO UPDATE SET precio = excluded.precio, cambio_24h = excluded.cambio_24h,"
            " fuente = excluded.fuente, ts = excluded.ts, volumen_24h = COALESCE(excluded.volumen_24h, volumen_24h),"
            " cap_mercado = COALESCE(excluded.cap_mercado, cap_mercado), max_24h = COALESCE(excluded.max_24h, max_24h),"
            " min_24h = COALESCE(excluded.min_24h, min_24h)",
            (activo, _txt(precio), _txt(cambio) if cambio is not None else None, fuente, ts, e.get("volumen"), e.get("cap"),
             _txt(e["max"]) if e.get("max") is not None else None, _txt(e["min"]) if e.get("min") is not None else None),
        )
        if historial_min:
            ult = c.execute("SELECT MAX(ts) AS ts FROM precios_historial WHERE activo = ?", (activo,)).fetchone()["ts"]
            if ult and (leer(ts) - leer(ult)).total_seconds() < historial_min * 60 - 1:
                return
        c.execute("INSERT INTO precios_historial (activo, precio, ts) VALUES (?, ?, ?)", (activo, _txt(precio), ts))


def _txt(d):
    """Decimal a texto sin notación científica (las monedas de precio muy bajo la usarían)."""
    d = Decimal(d)
    return format(d, "f") if d.adjusted() < -6 else str(d)


def redondear(valor, cifras=6):
    """Redondea un precio a cifras significativas (sirve igual para 64.666 que para 0,0000039)."""
    d = Decimal(str(valor))
    if not d:
        return d
    return d.quantize(Decimal(1).scaleb(d.adjusted() - cifras + 1))


def actualizar_manual(activo, precio, usuario):
    if not db.uno("SELECT 1 FROM activos WHERE codigo = ?", (activo,)):
        raise ErrorPrecio("El activo no existe.")
    with db.transaccion():
        anterior = vigentes().get(activo)
        cambio = None
        if anterior and anterior["precio"] > 0:
            cambio = ((precio / anterior["precio"] - 1) * 100).quantize(Decimal("0.01"))
        registrar(activo, precio, cambio, "manual")
        auditoria.registrar("precio.manual", f"activo:{activo}",
                            {"texto": f"Cargó a mano el precio de {activo}: {fmt_precio(precio)}.", "precio": str(precio)},
                            usuario=usuario)
    _alertas()


def actualizar_coingecko(usuario=None, auditar=True, historial_min=0):
    filas = [a for a in activos() if a["coingecko_id"]]
    ids = ",".join(a["coingecko_id"] for a in filas)
    cabeceras = {"accept": "application/json"}
    clave = current_app.config.get("COINGECKO_API_KEY")
    if clave:
        cabeceras["x-cg-demo-api-key"] = clave
    try:
        r = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                         params={"ids": ids, "vs_currency": "usd", "per_page": 250, "price_change_percentage": "24h"},
                         headers=cabeceras, timeout=10)
        r.raise_for_status()
        datos = {d["id"]: d for d in r.json()}
    except (requests.RequestException, ValueError) as e:
        raise ErrorPrecio(f"No se pudo consultar CoinGecko: {e.__class__.__name__}.") from None
    n, ts = 0, ahora()
    with db.transaccion():
        for a in filas:
            d = datos.get(a["coingecko_id"]) or {}
            if not d.get("current_price"):
                continue
            cambio = d.get("price_change_percentage_24h")
            registrar(a["codigo"], Decimal(str(d["current_price"])),
                      Decimal(str(round(cambio, 4))) if cambio is not None else None, "CoinGecko", ts, historial_min,
                      {"volumen": d.get("total_volume"), "cap": d.get("market_cap"),
                       "max": Decimal(str(d["high_24h"])) if d.get("high_24h") else None,
                       "min": Decimal(str(d["low_24h"])) if d.get("low_24h") else None})
            n += 1
        if not n:
            raise ErrorPrecio("CoinGecko no devolvió precios.")
        if auditar:
            auditoria.registrar("precio.coingecko", "precios",
                                {"texto": f"Actualizó {n} precios desde CoinGecko.", "activos": n}, usuario=usuario, ts=ts)
    _alertas()
    return n


def actualizar_binance(usuario=None, auditar=True, historial_min=0):
    """Último precio, variación, máximo, mínimo y volumen de 24 h de cada activo contra USDT (el USDT vale 1)."""
    from . import exchange
    cli = exchange.cliente_binance()
    try:
        datos = cli.mercado([a["codigo"] for a in activos()])
    except exchange.ErrorExchange as e:
        raise ErrorPrecio(f"No se pudo consultar Binance: {e}") from None
    if not datos:
        raise ErrorPrecio("Binance no devolvió precios.")
    ts = ahora()
    with db.transaccion():
        for a, d in datos.items():
            registrar(a, d["precio"], d["cambio"].quantize(Decimal("0.0001")), "Binance", ts, historial_min,
                      {"volumen": d.get("volumen"), "max": d.get("max"), "min": d.get("min")})
        if auditar:
            auditoria.registrar("precio.binance", "precios", {"texto": f"Actualizó {len(datos)} precios desde Binance.",
                                                               "activos": len(datos)}, usuario=usuario, ts=ts)
    _alertas()
    return len(datos)


def fuente():
    f = current_app.config.get("FUENTE_PRECIOS")
    return {"binance": "Binance", "simulada": "Simulado"}.get(f, "CoinGecko")


def actualizar(usuario=None, auditar=True, historial_min=0):
    """Actualiza desde la fuente configurada (FUENTE_PRECIOS)."""
    f = fuente()
    if f == "Binance":
        return actualizar_binance(usuario, auditar, historial_min)
    if f == "Simulado":
        return actualizar_simulado(historial_min=historial_min)
    return actualizar_coingecko(usuario, auditar, historial_min)


def actualizar_simulado(ts=None, historial_min=0, semilla=None):
    """Precios de demostración que se mueven solos: un paso de recorrido aleatorio desde el precio vigente. Solo para
    desarrollo y demostraciones (FUENTE_PRECIOS=simulada); se marcan con la fuente «Simulado»."""
    import random
    from datetime import timedelta
    if current_app.config["ENTORNO"] == "produccion":
        raise ErrorPrecio("Los precios simulados no se usan en producción.")
    from .mercado_demo import MERCADO, SERIES, VOLATILIDAD
    azar = random.Random(semilla)
    ts = ts or ahora()
    vig0 = vigentes()
    for a in activos():  # una base de demostración anterior puede no tener precio de las monedas nuevas
        if a["codigo"] not in vig0 and a["codigo"] in SERIES:
            cap, volumen, cambio = MERCADO[a["codigo"]]
            registrar(a["codigo"], redondear(SERIES[a["codigo"]][-1]), Decimal(cambio), "Simulado", ts,
                      extra={"volumen": volumen, "cap": cap})
    from .tiempo import iso
    ts = ts or ahora()
    vig = vigentes()
    hace24 = iso(leer(ts) - timedelta(hours=24))
    n = 0
    with db.transaccion():
        for a in activos():
            p = vig.get(a["codigo"])
            if not p:
                continue
            # paso pequeño por actualización; cada pocos segundos se nota el movimiento sin saltos irreales
            paso = azar.gauss(0, VOLATILIDAD.get(a["codigo"], 0.035) / 120)
            nuevo = redondear(p["precio"] * Decimal(str(1 + paso)))
            if a["estable"]:
                nuevo = redondear(min(max(nuevo, Decimal("0.9985")), Decimal("1.0015")))
            ref = db.uno("SELECT precio FROM precios_historial WHERE activo = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                         (a["codigo"], hace24))
            cambio = ((nuevo / Decimal(ref["precio"]) - 1) * 100).quantize(Decimal("0.0001")) if ref else p["cambio"]
            r = db.uno("SELECT MAX(CAST(precio AS REAL)) AS hi, MIN(CAST(precio AS REAL)) AS lo FROM precios_historial"
                       " WHERE activo = ? AND ts > ?", (a["codigo"], hace24))
            alto = max(nuevo, redondear(r["hi"])) if r["hi"] else nuevo
            bajo = min(nuevo, redondear(r["lo"])) if r["lo"] else nuevo
            registrar(a["codigo"], nuevo, cambio, "Simulado", ts, historial_min, {"max": alto, "min": bajo})
            n += 1
    return n


def vivo():
    """Estado de la actualización en vivo: (en_vivo, segundos desde el último precio, fuente)."""
    f = db.uno("SELECT MAX(ts) AS ts, fuente FROM precios")
    if not f or not f["ts"]:
        return False, None, None
    seg = minutos_desde(f["ts"]) * 60
    return seg <= current_app.config["VIVO_SEGUNDOS"] * 4, seg, f["fuente"]


def podar_historial(ts=None):
    """Reduce la resolución del historial viejo: 1 minuto hasta 1 día, 5 minutos hasta 3 días, 1 hora hasta 60 días y
    1 punto por día después. Devuelve cuántos puntos borró."""
    from datetime import timedelta
    from .tiempo import iso
    ahora_ = leer(ts or ahora())
    tramos = [(1, "strftime('%Y%m%d%H', ts) || '-' || (CAST(strftime('%M', ts) AS INTEGER) / 5)"),
              (3, "strftime('%Y%m%d%H', ts)"), (60, "strftime('%Y%m%d', ts)")]
    n = 0
    with db.transaccion() as c:
        for dias, cubo in tramos:  # en cada tramo queda el primer punto de cada intervalo
            limite = iso(ahora_ - timedelta(days=dias))
            n += c.execute(f"DELETE FROM precios_historial WHERE ts < ? AND id NOT IN (SELECT MIN(id) FROM precios_historial"
                           f" WHERE ts < ? GROUP BY activo, {cubo})", (limite, limite)).rowcount
    return n


def _alertas():
    from . import alertas, programadas
    try:
        v = vigentes()
        programadas.revisar(v)
        alertas.revisar(v)
    except Exception:  # una alerta rota no puede impedir que se actualicen los precios
        current_app.logger.exception("No se pudieron revisar las alertas de precio")


def antiguos(codigos=None):
    """Lista de (activo, minutos o None) cuyo precio falta o supera la antigüedad permitida."""
    maximo = current_app.config["PRECIO_MAX_MINUTOS"]
    vig = vigentes()
    out = []
    for a in codigos if codigos is not None else [x["codigo"] for x in activos()]:
        p = vig.get(a)
        if not p:
            out.append((a, None))
        elif maximo > 0 and minutos_desde(p["ts"]) > maximo:
            out.append((a, int(minutos_desde(p["ts"]))))
    return out


def exigir_frescura(codigos):
    viejos = antiguos(codigos)
    if viejos:
        a, m = viejos[0]
        if m is None:
            raise ErrorPrecio(f"No hay precio cargado para {a}. Actualiza los precios antes de aprobar.")
        raise ErrorPrecio(f"El precio de {a} tiene {m} minutos de antigüedad. Actualiza los precios antes de aprobar.")


def historial(codigos, desde):
    """Precios desde una fecha, incluido el último anterior a ella, por activo."""
    out = {}
    for a in codigos:
        previo = db.uno("SELECT precio, ts FROM precios_historial WHERE activo = ? AND ts < ? ORDER BY ts DESC LIMIT 1",
                        (a, desde))
        filas = db.todos("SELECT precio, ts FROM precios_historial WHERE activo = ? AND ts >= ? ORDER BY ts, id",
                         (a, desde))
        serie = ([(previo["ts"], Decimal(previo["precio"]))] if previo else []) + [(f["ts"], Decimal(f["precio"])) for f in filas]
        out[a] = serie
    return out


def mercado(dias=7):
    """Cada activo con su precio vigente, la variación de 24 h y la serie de los últimos días."""
    from datetime import timedelta
    from .tiempo import ahora_dt, iso
    vig = vigentes()
    acts = activos()
    hist = historial([a["codigo"] for a in acts], iso(ahora_dt() - timedelta(days=dias)))
    out = []
    for a in acts:
        p = vig.get(a["codigo"])
        serie = [float(x) for _, x in hist.get(a["codigo"], [])]
        if p:
            serie.append(float(p["precio"]))
        var = (serie[-1] / serie[0] - 1) * 100 if len(serie) > 1 and serie[0] else None
        out.append({"codigo": a["codigo"], "nombre": a["nombre"], "color": a["color"], "precio": p["precio"] if p else None,
                    "cambio": p["cambio"] if p else None, "ts": p["ts"] if p else None, "serie": serie, "var": var,
                    "categoria": a["categoria"], "habilitado": a["habilitado"], "estable": a["estable"],
                    "volumen": p["volumen"] if p else None, "cap": p["cap"] if p else None,
                    "max": p["max"] if p else None, "min": p["min"] if p else None,
                    "nuevo": bool(a["alta"]) and minutos_desde(a["alta"] + "T00:00:00Z") < 60 * 24 * 45})
    return out


@click.command("precios-en-vivo")
@click.option("--cada", type=float, default=None, help="Segundos entre actualizaciones (por defecto VIVO_SEGUNDOS).")
@click.option("--veces", type=int, default=0, help="Cantidad de vueltas (0 = sin fin).")
def cmd_vivo(cada, veces):
    """Mantiene los precios actualizados en tiempo real. Pensado para correr como servicio aparte del sitio."""
    import time as _t
    cada = cada or current_app.config["VIVO_SEGUNDOS"]
    if fuente() == "CoinGecko" and cada < 20:
        cada = 20  # el plan gratuito de CoinGecko admite unas 30 consultas por minuto
    click.echo(f"Precios en vivo desde {fuente()} cada {cada:g} s. Ctrl+C para detener.")
    vuelta, espera, ult_poda = 0, cada, 0.0
    while True:
        inicio = _t.time()
        try:
            actualizar(auditar=False, historial_min=1)
            _alertas()
            espera = cada
        except ErrorPrecio as e:
            espera = min(espera * 2, 120)  # sin conexión: espera cada vez más, hasta 2 minutos
            click.echo(f"{ahora()}  {e} Reintento en {espera:g} s.", err=True)
        if inicio - ult_poda > 3600:
            podar_historial()
            ult_poda = inicio
        vuelta += 1
        if veces and vuelta >= veces:
            break
        _t.sleep(max(0.0, espera - (_t.time() - inicio)))


@click.command("actualizar-precios")
def cmd_actualizar():
    """Trae los precios de la fuente configurada (Binance o CoinGecko); pensado para ejecutarse cada pocos minutos."""
    try:
        n = actualizar()
    except ErrorPrecio as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"{n} precios actualizados.")
