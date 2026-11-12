"""Cálculos y formatos de dinero.

Los dólares se manejan en centavos (enteros) y las criptomonedas en unidades de 1e-8 (enteros).
Los precios son Decimal. Nunca se usan números de coma flotante para montos.
"""
import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

CRIPTO = 10 ** 8


def escala(activo):
    return 100 if activo == "USD" else CRIPTO


def valor_cent(activo, unidades, precio):
    """Valor en centavos de una cantidad de un activo al precio dado."""
    if activo == "USD":
        return int(unidades)
    return int((Decimal(unidades) * Decimal(precio) * 100 / CRIPTO).to_integral_value(ROUND_HALF_UP))


def unidades_por(cent, precio):
    """Unidades que se pueden comprar con un monto en centavos (se redondea hacia abajo)."""
    return int((Decimal(cent) / 100 / Decimal(precio) * CRIPTO).to_integral_value(ROUND_DOWN))


def _normalizar(texto):
    s = str(texto or "").strip()
    for quitar in ("US$", "USD", "$", " ", " "):
        s = s.replace(quitar, "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    return s


def leer_monto(texto):
    """Convierte un monto escrito por una persona (1.500 · 1500,50 · US$ 2.000) a centavos."""
    s = _normalizar(texto)
    if not s:
        raise ValueError("Escribe un monto.")
    if not re.fullmatch(r"\d{1,12}(\.\d{1,2})?", s):
        raise ValueError("El monto no es válido. Escríbelo como 1.500 o 1500,50.")
    return int((Decimal(s) * 100).to_integral_value())


def leer_precio(texto):
    s = _normalizar(texto)
    try:
        if not re.fullmatch(r"\d{1,12}(\.\d{1,8})?", s):
            raise InvalidOperation
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError("El precio no es válido. Escríbelo como 73.761,25.") from None
    if d <= 0:
        raise ValueError("El precio tiene que ser mayor que cero.")
    return d


def fmt_num(valor, decimales=2):
    d = Decimal(valor).quantize(Decimal(1).scaleb(-decimales), ROUND_HALF_UP)
    texto = f"{abs(d):,.{decimales}f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return ("−" if d < 0 else "") + texto


def fmt_usd(cent, decimales=2):
    return ("−" if cent < 0 else "") + "US$ " + fmt_num(Decimal(abs(int(cent))) / 100, decimales)


def fmt_precio(precio):
    p = Decimal(precio)
    return "US$ " + fmt_num(p, 2 if p >= 1 else 4)


def fmt_unidades(unidades, activo):
    if activo == "USD":
        return fmt_usd(unidades)
    d = Decimal(int(unidades)) / CRIPTO
    texto = fmt_num(d, 8).rstrip("0").rstrip(",")
    return f"{texto} {activo}"
