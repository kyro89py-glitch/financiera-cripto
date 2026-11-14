"""Datos de demostración: equipo, clientes, siete días de precios y operaciones de ejemplo.

Se generan con las mismas funciones que usa el sistema, así que la bitácora y el libro quedan
coherentes. No se puede ejecutar en producción.
"""
import math
from datetime import timedelta
from decimal import Decimal

import click
from flask import current_app

from . import comisiones, conciliacion, cuentas, db, documentos, operaciones, precios
from .tiempo import ahora_dt, iso

CLAVE_DEMO = "Demo-2026!"

# Precios de referencia de los últimos 7 días (corte de CoinGecko del 11 de noviembre de 2026), 17 puntos por activo.
SERIES = {
    "BTC": ([76199, 78288, 80443, 80222, 75773, 75538, 75724, 75962, 75689, 75695, 75850, 74740, 74094, 74945, 74775, 73416, 73761], "-1.26"),
    "ETH": ([2245.3, 2317.3, 2423.1, 2416.5, 2227.8, 2226.7, 2229.0, 2246.8, 2235.1, 2232.9, 2234.2, 2124.4, 2106.4, 2127.4, 2114.4, 2042.3, 2064.41], "-2.55"),
    "USDT": ([0.9989, 0.9990, 0.9992, 0.9993, 0.9991, 0.9990, 0.9991, 0.9992, 0.9992, 0.9991, 0.9990, 0.9991, 0.9992, 0.9991, 0.9991, 0.9992, 0.999127], "0.01"),
    "SOL": ([90.96, 92.86, 95.51, 96.51, 89.85, 89.59, 90.17, 90.20, 89.46, 89.00, 89.15, 86.41, 85.87, 86.38, 86.01, 82.90, 83.59], "-2.86"),
    "BNB": ([685.8, 700.1, 719.4, 715.8, 687.7, 689.5, 694.1, 694.6, 693.3, 694.3, 696.2, 683.9, 680.7, 689.7, 690.4, 674.7, 683.43], "-0.68"),
    "XRP": ([1.2501, 1.2812, 1.3043, 1.3179, 1.2214, 1.1851, 1.1851, 1.1611, 1.1575, 1.1576, 1.1595, 1.1125, 1.0843, 1.0948, 1.0954, 1.0707, 1.063], "-2.76"),
    "LINK": ([10.732, 11.148, 11.441, 11.536, 10.691, 10.736, 10.869, 10.862, 10.840, 10.765, 10.706, 10.400, 10.409, 10.662, 10.632, 10.282, 10.42], "-1.47"),
}

EQUIPO = [("admin@demo.local", "Valeria Ortiz", "admin"),
          ("operaciones@demo.local", "Natalia Giménez", "operador"),
          ("cumplimiento@demo.local", "Andrés Villalba", "cumplimiento")]

CLIENTES = [
    # clave, nombre, documento, tipo, correo, perfil, modelo, verificado, origen de fondos
    ("lucia", "Lucía Ferreira", "CI 3.812.445", "persona", "lucia@demo.local", "moderado", "equilibrio", True, None),
    ("diego", "Diego Rolón", "CI 4.207.118", "persona", "diego@demo.local", "arriesgado", "impulso", True,
     "Venta de inmueble en Luque. Presentó escritura y extracto bancario."),
    ("carmen", "Carmen Ayala", "CI 2.650.973", "persona", "carmen@demo.local", "conservador", "reserva", True,
     "Ahorros por jubilación. Presentó certificado del IPS y extractos de 12 meses."),
    ("patricia", "Patricia Duarte", "CI 3.398.204", "persona", "patricia@demo.local", "moderado", "equilibrio", True,
     "Honorarios profesionales. Presentó declaraciones juradas de IRP de dos años."),
    ("ruben", "Rubén Cáceres", "CI 4.774.390", "persona", "ruben@demo.local", "arriesgado", "impulso", True, None),
    ("sofia", "Sofía Martínez", "CI 3.115.827", "persona", "sofia@demo.local", "conservador", "reserva", True,
     "Sueldo en relación de dependencia. Presentó recibos de salario."),
    ("agro", "Agroservicios del Este S.A.", "RUC 80104417-3", "empresa", "agro@demo.local", "moderado", "equilibrio", True,
     "Excedentes de la zafra 2025/26. Presentó balance auditado y extracto bancario."),
]


def _texto_cantidad(unidades, activo):
    escala = 100 if activo == "USD" else 10 ** 8
    entero, resto = divmod(unidades, escala)
    return f"{entero},{resto:0{2 if activo == 'USD' else 8}d}"


def _interp(serie, f):
    x = f * (len(serie) - 1)
    i = min(len(serie) - 2, int(x))
    return serie[i] + (serie[i + 1] - serie[i]) * (x - i)


@click.command("sembrar-demo")
def cmd_sembrar():
    """Carga datos de demostración en una base vacía."""
    if current_app.config["ENTORNO"] == "produccion":
        raise click.ClickException("Los datos de demostración no se cargan en producción.")
    if db.uno("SELECT COUNT(*) AS n FROM usuarios")["n"]:
        raise click.ClickException("La base ya tiene usuarios. Usa una base nueva para la demostración.")

    fin = ahora_dt()
    ini = fin - timedelta(days=7)

    def t(dias=0, horas=0, minutos=0):
        return iso(fin - timedelta(days=dias, hours=horas, minutes=minutos))

    def precio_en(activo, momento):
        f = max(0.0, min(1.0, (momento - ini).total_seconds() / (fin - ini).total_seconds()))
        return _interp(SERIES[activo][0], f)

    def precios_en(ts_txt):
        from .tiempo import leer
        m = leer(ts_txt)
        return {a: {"precio": Decimal(str(round(precio_en(a, m), 6)))} for a in SERIES}

    # Historial de precios cada 3 horas, con una oscilación pequeña entre los puntos de referencia.
    c = db.conexion()
    with db.transaccion():
        for a, (serie, cambio) in SERIES.items():
            for k in range(56):
                m = ini + timedelta(hours=3 * k)
                ruido = 0 if a == "USDT" else 0.0035 * math.sin(k * 1.7 + len(a))
                p = precio_en(a, m) * (1 + ruido)
                c.execute("INSERT INTO precios_historial (activo, precio, ts) VALUES (?, ?, ?)", (a, str(round(p, 6)), iso(m)))
            precios.registrar(a, Decimal(str(serie[-1])), Decimal(cambio), "Datos de ejemplo", iso(fin))

    equipo = {}
    for email, nombre, rol in EQUIPO:
        uid = cuentas.crear_usuario(email, nombre, rol, CLAVE_DEMO, debe_cambiar=False, ts=t(30))
        equipo[rol] = db.uno("SELECT * FROM usuarios WHERE id = ?", (uid,))
    op_u, cu_u = equipo["operador"], equipo["cumplimiento"]

    def legajo(cid, ts_subida, ts_revision, tipos=None, aceptar=True):
        c0 = db.uno("SELECT * FROM clientes WHERE id = ?", (cid,))
        dueno = db.uno("SELECT * FROM usuarios WHERE id = ?", (c0["usuario_id"],))
        for tipo in tipos or documentos.REQUERIDOS[c0["tipo"]]:
            did = documentos.guardar(c0, tipo, f"{tipo}.pdf", documentos.pdf_ejemplo(f"{tipo.capitalize()} - {c0['documento']}"),
                                     dueno, ts=ts_subida)
            if aceptar:
                documentos.revisar(did, "aceptado", None, cu_u, ts=ts_revision)

    cli = {}
    for i, (clave, nombre, doc, tipo, email, perfil, modelo, verificado, origen) in enumerate(CLIENTES):
        cid, _ = cuentas.crear_cliente({"nombre": nombre, "documento": doc, "tipo": tipo, "email": email,
                                        "perfil_riesgo": perfil, "modelo": modelo, "clave": CLAVE_DEMO,
                                        "telefono": f"0981 {400 + i * 37:03d} {120 + i * 53:03d}"},
                                       creador=op_u, ts=t(25, minutos=i * 7))
        if verificado:
            legajo(cid, t(24, minutos=i * 5 - 30), t(24, minutos=i * 5 - 10))
            cuentas.marcar_kyc(cid, "verificado", "Documento y prueba de vida revisados.", cu_u, ts=t(24, minutos=i * 5))
        if origen:
            cuentas.registrar_origen(cid, origen, cu_u, ts=t(24, minutos=i * 5 + 2))
        cli[clave] = cid

    def fila(clave):
        return db.uno("SELECT * FROM clientes WHERE id = ?", (cli[clave],))

    def usuario_de(clave):
        return db.uno("SELECT * FROM usuarios WHERE id = ?", (fila(clave)["usuario_id"],))

    def aporte(clave, monto_usd, dias, horas=0, modelo=None):
        ts0 = t(dias, horas)
        c0 = fila(clave)
        opid = operaciones.solicitar_aporte(c0, monto_usd * 100, modelo or c0["modelo"], f"TRF-{551000 + int(monto_usd) % 997}",
                                            usuario_de(clave), ts=ts0)
        ts1 = t(dias, horas, -25)
        r = operaciones.aprobar(opid, op_u, ts=ts1, precios_usar=precios_en(ts1))
        if r == "primera_firma":
            ts2 = t(dias, horas, -70)
            operaciones.aprobar(opid, cu_u, ts=ts2, precios_usar=precios_en(ts2))
        return opid

    def retiro(clave, monto_usd, dias, rechazo=None):
        ts0 = t(dias)
        opid = operaciones.solicitar_retiro(fila(clave), monto_usd * 100, usuario_de(clave), ts=ts0)
        ts1 = t(dias, 0, -40)
        if rechazo:
            operaciones.rechazar(opid, op_u, rechazo, ts=ts1)
        else:
            operaciones.aprobar(opid, op_u, ts=ts1, precios_usar=precios_en(ts1))

    aporte("carmen", 132000, 6, 20)
    aporte("agro", 540000, 6, 14)
    aporte("lucia", 5000, 6, 12)
    aporte("diego", 48900, 6, 2)
    aporte("sofia", 31200, 5, 22)
    aporte("ruben", 9750, 5, 12)
    aporte("patricia", 76300, 5, 1)
    retiro("lucia", 600, 4.8, "La cuenta de destino no coincide con la registrada a nombre de la clienta.")
    aporte("lucia", 4400, 4, 2)
    aporte("carmen", 20000, 3, 5)
    retiro("diego", 2500, 2)
    aporte("lucia", 3000, 1, 12)
    cuentas.marcar_kyc(cli["sofia"], "observado", "Falta comprobante de ingresos actualizado.", cu_u, ts=t(1, 3))

    hugo, _ = cuentas.crear_cliente({"nombre": "Hugo Benítez", "documento": "CI 5.031.662", "tipo": "persona",
                                     "email": "hugo@demo.local", "perfil_riesgo": "moderado", "modelo": "equilibrio",
                                     "clave": CLAVE_DEMO, "telefono": "0972 515 208"}, creador=op_u, ts=t(2, 4))
    itapua, _ = cuentas.crear_cliente({"nombre": "Comercial Itapúa S.R.L.", "documento": "RUC 80098812-1", "tipo": "empresa",
                                       "email": "itapua@demo.local", "perfil_riesgo": "conservador", "modelo": "reserva",
                                       "clave": CLAVE_DEMO, "telefono": "071 204 330"}, creador=op_u, ts=t(3, 2))
    legajo(itapua, t(2, 23), t(2, 21))
    cuentas.marcar_kyc(itapua, "verificado", "Estatutos, RUC y documentos del representante revisados.", cu_u, ts=t(2, 20))
    legajo(hugo, t(0, 9), None, tipos=["identidad"], aceptar=False)
    cli.update(hugo=hugo, itapua=itapua)
    for clave in cli:
        if clave != "hugo":
            u = usuario_de(clave)
            cuentas.aceptar_terminos(u, ts=db.uno("SELECT creado FROM clientes WHERE id = ?", (cli[clave],))["creado"])

    operaciones.solicitar_aporte(fila("hugo"), 200000, "equilibrio", "TRF-552019", usuario_de("hugo"), ts=t(0, 7))
    operaciones.solicitar_retiro(fila("ruben"), 150000, usuario_de("ruben"), ts=t(0, 5))
    operaciones.solicitar_aporte(fila("patricia"), 500000, "impulso", "TRF-552311", usuario_de("patricia"), ts=t(0, 3),
                                 acepta_riesgo=True)
    agro_op = operaciones.solicitar_aporte(fila("agro"), 3000000, "equilibrio", "TRF-552408", usuario_de("agro"), ts=t(0, 2))
    operaciones.aprobar(agro_op, op_u, ts=t(0, 1))
    operaciones.solicitar_aporte(fila("itapua"), 6000000, "reserva", "TRF-552517", usuario_de("itapua"), ts=t(0, 0, 40))
    # Lucía también opera por su cuenta: deposita en su saldo y compra y vende monedas sueltas.
    dep = operaciones.solicitar_aporte(fila("lucia"), 150000, "saldo", "TRF-552600", usuario_de("lucia"), ts=t(0, 9))
    operaciones.aprobar(dep, op_u, ts=t(0, 8, 30), precios_usar=precios_en(t(0, 8, 30)))
    for activo, lado, usd, horas in (("SOL", "compra", 400, 8), ("LINK", "compra", 250, 7), ("XRP", "compra", 200, 6),
                                     ("SOL", "venta", 150, 3)):
        operaciones.operar(fila("lucia"), activo, lado, usd * 100, usuario_de("lucia"), ts=t(0, horas),
                           precios_usar=precios_en(t(0, horas)))
    for activo in ("BTC", "SOL", "LINK"):
        db.ejecutar("INSERT OR IGNORE INTO favoritos (usuario_id, activo, creado) VALUES (?, ?, ?)",
                    (usuario_de("lucia")["id"], activo, t(0, 9)))
    try:  # comisión del mes anterior (proporcional para quien invirtió durante el mes)
        comisiones.cobrar(comisiones.periodo_anterior(), equipo["admin"], ts=t(0, 11))
    except comisiones.ErrorComision:
        pass
    saldos = conciliacion.saldos_libro()
    conciliacion.registrar({a: _texto_cantidad(saldos.get(a, 0), a) for a in conciliacion.activos_a_conciliar()},
                           "Saldos del custodio y del banco al cierre de ayer.", cu_u, ts=t(0, 10))

    click.echo("Datos de demostración cargados. Contraseña de todas las cuentas: " + CLAVE_DEMO)
    for email, nombre, rol in EQUIPO:
        click.echo(f"  {rol:13} {email}  ({nombre})")
    click.echo("  cliente       lucia@demo.local  (y diego, carmen, patricia, ruben, sofia, agro, hugo, itapua @demo.local)")
