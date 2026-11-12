"""Punto de entrada para servidores WSGI: gunicorn wsgi:app"""
from financiera import create_app

app = create_app()
