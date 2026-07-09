"""Almacén de historial por sesión en disco.

Flask guarda la sesión en una cookie firmada, con límite ~4 KB. Con 30 turnos
de chat se satura fácilmente, así que persistimos el historial fuera y en la
cookie solo llevamos un session_id opaco.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

from . import config
from .logging_setup import get_logger

log = get_logger(__name__)

_LOCK = threading.Lock()
_MEMO_TTL_DAYS = 30  # limpiar sesiones más antiguas que esto


def _ensure_dir() -> Path:
    config.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return config.SESSIONS_DIR


def _path_for(sid: str) -> Path:
    return _ensure_dir() / f"{sid}.json"


def new_session_id() -> str:
    return secrets.token_urlsafe(24)


def load_history(sid: str) -> list[dict]:
    if not sid:
        return []
    path = _path_for(sid)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict)]
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("No se pudo leer sesión %s: %s", sid, exc)
    return []


def save_history(sid: str, history: list[dict]) -> None:
    if not sid:
        return
    path = _path_for(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sess.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("No se pudo guardar sesión %s: %s", sid, exc)
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def clear_history(sid: str) -> None:
    if not sid:
        return
    path = _path_for(sid)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("No se pudo borrar sesión %s: %s", sid, exc)


def cleanup_old_sessions() -> int:
    """Elimina archivos de sesión antiguos. Devuelve cuántos borró."""
    cutoff = time.time() - _MEMO_TTL_DAYS * 86400
    borrados = 0
    try:
        for f in _ensure_dir().iterdir():
            if not f.is_file():
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    borrados += 1
            except OSError:
                continue
    except OSError:
        pass
    return borrados
