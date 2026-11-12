from decimal import Decimal

import pytest

from financiera import dinero


@pytest.mark.parametrize("texto,cent", [
    ("1500", 150000), ("1.500", 150000), ("1.500,50", 150050), ("1500,5", 150050), ("US$ 2.000", 200000),
    ("12.345.678", 1234567800), ("1.5", 150), ("0,01", 1),
])
def test_leer_monto(texto, cent):
    assert dinero.leer_monto(texto) == cent


@pytest.mark.parametrize("texto", ["", "abc", "1,2,3", "-5", "1.500,555", "1e3"])
def test_leer_monto_invalido(texto):
    with pytest.raises(ValueError):
        dinero.leer_monto(texto)


def test_formatos():
    assert dinero.fmt_usd(123456789) == "US$ 1.234.567,89"
    assert dinero.fmt_usd(-50) == "−US$ 0,50"
    assert dinero.fmt_usd(150000, 0) == "US$ 1.500"
    assert dinero.fmt_unidades(12345678, "BTC") == "0,12345678 BTC"
    assert dinero.fmt_unidades(100000000, "ETH") == "1 ETH"


def test_valor_y_unidades_sin_perder_centavos():
    precio = Decimal("73761.25")
    u = dinero.unidades_por(500000, precio)            # US$ 5.000 en BTC
    assert u == 6778626                                 # 0,06778626 BTC: se redondea hacia abajo
    assert dinero.valor_cent("BTC", u, precio) <= 500000
    assert dinero.valor_cent("USD", 1234, None) == 1234
