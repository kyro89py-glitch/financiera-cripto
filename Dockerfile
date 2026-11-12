FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FINANCIERA_ENTORNO=produccion \
    DATABASE=/datos/financiera.db \
    TRAS_PROXY=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY financiera ./financiera
COPY wsgi.py .
RUN useradd --create-home --uid 10001 app && mkdir -p /datos && chown app /datos
USER app

VOLUME ["/datos"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ingresar', timeout=4)"
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--forwarded-allow-ips", "*", "wsgi:app"]
