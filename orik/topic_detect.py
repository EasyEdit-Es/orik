"""Detección de cambio de tema usando el LLM rápido."""

from __future__ import annotations

import re

from . import config
from .logging_setup import get_logger
from .ollama_client import OllamaError, chat_completion

log = get_logger(__name__)


_SYSTEM_PROMPT = (
    "Eres un clasificador de conversaciones. "
    "Se te da el historial reciente y un mensaje nuevo. "
    "Decide si el mensaje nuevo es:\n"
    "- CONTINUA: es seguimiento del tema anterior, aunque no lo mencione "
    "explícitamente (ej: '¿contra quién?', '¿a qué hora?', 'y el resultado?', "
    "'dime más', '¿quién ganó?').\n"
    "- NUEVO: tema completamente distinto sin relación con lo anterior.\n\n"
    "Responde ÚNICAMENTE con una palabra: CONTINUA o NUEVO. Nada más."
)


def _resumir_historial(historial: list[dict], max_msgs: int = 6, max_chars: int = 200) -> str:
    ultimos = historial[-max_msgs:]
    partes = []
    for m in ultimos:
        rol = "U" if m.get("role") == "user" else "A"
        contenido = (m.get("content") or "").strip()[:max_chars]
        partes.append(f"{rol}: {contenido}")
    return "\n".join(partes)


def detectar_cambio_de_tema(mensaje_nuevo: str, historial: list[dict]) -> bool:
    """Devuelve True si el mensaje inicia un tema nuevo, False si continúa el anterior.

    Ante error o historial insuficiente devuelve False (más seguro: no borra contexto).
    Se salta la llamada al LLM si el mensaje es largo (probablemente autocontenido).
    """
    if not historial or len(historial) < 2:
        return False

    # Heurística: mensajes largos suelen ser autocontenidos → asumir NUEVO
    # sin gastar un round-trip al LLM.
    palabras = mensaje_nuevo.split()
    if len(palabras) >= 15:
        log.info("Mensaje largo (%d palabras) → asumiendo tema nuevo sin llamar al LLM", len(palabras))
        return True

    contexto = _resumir_historial(historial)
    try:
        respuesta = chat_completion(
            model=config.OLLAMA_MODEL_FAST,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Historial:\n{contexto}\n\n"
                        f"Mensaje nuevo: {mensaje_nuevo}\n\n"
                        f"¿CONTINUA o NUEVO?"
                    ),
                },
            ],
            max_tokens=5,
            temperature=0.0,
            timeout=8,
        )
    except OllamaError as exc:
        log.warning("Fallo detectando cambio de tema: %s", exc)
        return False

    decision = re.sub(r"[^A-Z]", "", (respuesta or "").upper())
    es_nuevo = decision.startswith("NUEVO")
    if es_nuevo:
        log.info("LLM detectó cambio de tema → limpiando contexto previo")
    else:
        log.info("LLM detectó continuación de tema → manteniendo historial")
    return es_nuevo
