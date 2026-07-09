"""Configuración centralizada.

Carga variables de entorno (opcionalmente desde .env) y expone constantes
tipadas. Cargar `.env` es opcional: si python-dotenv no está instalado,
las variables se leen directamente del entorno del proceso.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ── Ollama ────────────────────────────────────────────────────
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3n:e2b")
OLLAMA_MODEL_SMART = os.getenv("OLLAMA_MODEL_SMART", "gpt-oss:20b")
OLLAMA_MODEL_FAST = os.getenv("OLLAMA_MODEL_FAST", "gemma3n:e2b")
OLLAMA_START_COMMAND = os.getenv("OLLAMA_START_COMMAND", "ollama serve")
OLLAMA_START_TIMEOUT = _env_int("OLLAMA_START_TIMEOUT", 30)
OLLAMA_REQUEST_TIMEOUT = _env_int("OLLAMA_REQUEST_TIMEOUT", 300)
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.75"))
OLLAMA_MAX_TOKENS = _env_int("OLLAMA_MAX_TOKENS", 4096)


# ── Servidor Flask ────────────────────────────────────────────
FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
FLASK_PORT = _env_int("FLASK_PORT", 5000)
FLASK_DEBUG = _env_bool("FLASK_DEBUG", False)


def _resolve_secret_key() -> str:
    """Persistir la secret key en disco para no invalidar sesiones al reiniciar.

    Prioridad: FLASK_SECRET_KEY env > archivo .secret_key > generar y guardar.
    """
    key = os.getenv("FLASK_SECRET_KEY")
    if key:
        return key
    secret_file = BASE_DIR / ".secret_key"
    if secret_file.exists():
        try:
            return secret_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    new_key = secrets.token_hex(32)
    with contextlib.suppress(OSError):
        secret_file.write_text(new_key, encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(secret_file, 0o600)
    return new_key


FLASK_SECRET_KEY = _resolve_secret_key()

SESSION_LIFETIME_DAYS = _env_int("SESSION_LIFETIME_DAYS", 7)


# ── Archivos ──────────────────────────────────────────────────
MEMORIA_FILE = BASE_DIR / "memoria.json"
SESSIONS_DIR = BASE_DIR / ".sessions"


# ── Búsqueda ──────────────────────────────────────────────────
SEARCH_MAX_RESULTS = _env_int("SEARCH_MAX_RESULTS", 8)
SEARCH_TIMEOUT = _env_int("SEARCH_TIMEOUT", 12)
SEARCH_CACHE_SIZE = _env_int("SEARCH_CACHE_SIZE", 64)
SEARCH_CACHE_TTL = _env_int("SEARCH_CACHE_TTL", 600)  # 10 min


# ── Historial ─────────────────────────────────────────────────
HISTORY_MAX_TURNS = _env_int("HISTORY_MAX_TURNS", 30)


# ── Autenticación opcional ────────────────────────────────────
API_TOKEN = os.getenv("ORIK_API_TOKEN", "").strip()  # vacío = sin auth
