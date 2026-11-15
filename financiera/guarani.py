"""Guaraníes: tipo de cambio de la casa para depósitos y retiros, y equivalencias para mostrar."""
from flask import current_app

from . import auditoria, db
from .tiempo import ahora

CLAVES = {"deposito": "pyg_deposito", "retiro": "pyg_retiro"}


class ErrorCambio(Exception):
    pass


def cambios():
    """{'deposito': ₲ que paga el cliente por cada dólar al depositar, 'retiro': ₲ que recibe por dólar al retirar,
    'ts': última actualización}. Cada valor es None hasta que Administración lo cargue."""
    out = {"deposito": None, "retiro": None, "ts": None}
    for f in db.todos("SELECT clave, valor, ts FROM ajustes WHERE clave IN (?, ?)", tuple(CLAVES.values())):
        k = "deposito" if f["clave"] == CLAVES["deposito"] else "retiro"
        out[k] = int(f["valor"]) or None
        out["ts"] = max(out["ts"] or "", f["ts"])
    return out


def referencia():
    """Guaraníes por dólar para mostrar equivalencias (promedio de los dos tipos de cambio), o None."""
    c = cambios()
    if c["deposito"] and c["retiro"]:
        return (c["deposito"] + c["retiro"]) // 2
    return c["deposito"] or c["retiro"]


def fijar(deposito, retiro, usuario):
    if not (1000 <= retiro <= deposito <= 100000):
        raise ErrorCambio("Revisa los valores: el cambio de depósito tiene que ser igual o mayor que el de retiro, "
                          "y ambos estar entre ₲ 1.000 y ₲ 100.000 por dólar.")
    maximo = current_app.config.get("PYG_MARGEN_MAX_PCT", 5)
    if (deposito - retiro) * 100 > retiro * maximo:
        raise ErrorCambio(f"La diferencia entre los dos tipos de cambio no puede superar el {maximo} %.")
    ts = ahora()
    with db.transaccion() as c:
        for clave, valor in ((CLAVES["deposito"], deposito), (CLAVES["retiro"], retiro)):
            c.execute("INSERT INTO ajustes (clave, valor, ts, por) VALUES (?, ?, ?, ?) ON CONFLICT(clave) DO UPDATE SET"
                      " valor = excluded.valor, ts = excluded.ts, por = excluded.por", (clave, str(valor), ts, usuario["id"]))
        auditoria.registrar("cambio.guarani", "guarani", {"texto": f"Fijó el tipo de cambio: depósitos a {fmt(deposito)} y retiros a "
                                                                   f"{fmt(retiro)} por dólar.", "deposito": deposito, "retiro": retiro},
                            usuario=usuario, ts=ts)


def fmt(gs):
    return "₲ " + f"{int(gs):,}".replace(",", ".")


def a_usd_cent(gs, cambio):
    """Centavos de dólar que se acreditan por un depósito en guaraníes (redondeo hacia abajo)."""
    return int(gs) * 100 // int(cambio)


def de_usd_cent(cent, cambio):
    """Guaraníes que corresponden a un importe en dólares (redondeo hacia abajo)."""
    return int(cent) * int(cambio) // 100


def leer(texto):
    s = str(texto or "").replace("₲", "").replace("Gs.", "").replace("Gs", "").replace("G.", "").replace(".", "").replace(" ", "").strip()
    if not s.isdigit() or len(s) > 13:
        raise ValueError("Escribe el monto en guaraníes sin decimales, por ejemplo 1.500.000.")
    return int(s)
