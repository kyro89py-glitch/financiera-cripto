"""Fechas: todo se guarda en UTC con formato ISO fijo, que se puede comparar como texto."""
from datetime import datetime, timedelta, timezone

FORMATO = "%Y-%m-%dT%H:%M:%SZ"


def ahora_dt():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime(FORMATO)


def ahora():
    return iso(ahora_dt())


def leer(texto):
    return datetime.strptime(texto, FORMATO).replace(tzinfo=timezone.utc)


def hace(**kwargs):
    return iso(ahora_dt() - timedelta(**kwargs))


def minutos_desde(texto):
    return (ahora_dt() - leer(texto)).total_seconds() / 60
