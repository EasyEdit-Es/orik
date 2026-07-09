"""Entrypoint para desarrollo: `python app.py`.

En producción usa gunicorn/uwsgi apuntando a `wsgi:application`.
"""

from __future__ import annotations

from orik import config
from orik.app import create_app
from orik.logging_setup import get_logger
from orik.ollama_client import ensure_ollama_running
from orik.session_store import cleanup_old_sessions

log = get_logger(__name__)
app = create_app()


def main() -> None:
    ensure_ollama_running()
    borrados = cleanup_old_sessions()
    if borrados:
        log.info("Limpieza de sesiones: %d borradas", borrados)

    log.info("🚀 Servidor arrancando en %s:%s", config.FLASK_HOST, config.FLASK_PORT)
    log.info("   Modelo principal:      %s", config.OLLAMA_MODEL)
    log.info("   Modelo sin web:        %s", config.OLLAMA_MODEL_SMART)
    log.info("   Modelo rápido:         %s", config.OLLAMA_MODEL_FAST)
    log.info("   Debug:                 %s", config.FLASK_DEBUG)
    log.info("   Auth (Bearer token):   %s", "ON" if config.API_TOKEN else "off")

    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
        use_reloader=config.FLASK_DEBUG,
    )


if __name__ == "__main__":
    main()
