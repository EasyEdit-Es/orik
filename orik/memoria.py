"""Memoria persistente del asistente en JSON, con escritura atómica."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path

from . import config
from .logging_setup import get_logger

log = get_logger(__name__)

_LOCK = threading.Lock()

_MAX_VALUE_LEN = 500  # límite prudente para el prompt


def cargar_memoria() -> dict[str, str]:
    with _LOCK:
        if not config.MEMORIA_FILE.exists():
            return {}
        try:
            with config.MEMORIA_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                log.warning("memoria.json no es un objeto; ignorando")
                return {}
            return {str(k): str(v)[:_MAX_VALUE_LEN] for k, v in data.items()}
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("No se pudo leer memoria.json: %s", exc)
            return {}


def guardar_memoria(memoria: dict[str, str]) -> None:
    """Escritura atómica: escribir en temp y hacer os.replace."""
    if not isinstance(memoria, dict):
        raise TypeError("memoria debe ser un dict")

    payload = {str(k): str(v)[:_MAX_VALUE_LEN] for k, v in memoria.items()}

    with _LOCK:
        path: Path = config.MEMORIA_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".memoria.", suffix=".json", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except OSError as exc:
            log.warning("No se pudo guardar memoria: %s", exc)
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def memoria_a_texto(memoria: dict[str, str]) -> str:
    if not memoria:
        return ""
    lineas = "\n".join(f"- {k}: {v}" for k, v in memoria.items())
    return f"Información sobre el usuario:\n{lineas}"
