"""WSGI entrypoint para producción (gunicorn/uwsgi/waitress)."""

from orik.app import create_app

application = create_app()
app = application  # alias
