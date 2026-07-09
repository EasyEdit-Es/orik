"""Reescritura de la query de búsqueda con el LLM rápido.

La regex-only construye queries pobres cuando el mensaje es ambiguo o largo.
Usamos el modelo rápido para producir una query densa de keywords cuando
detectamos que va a merecer la pena.
"""

from __future__ import annotations

import re
from datetime import datetime

from . import config
from .logging_setup import get_logger
from .ollama_client import OllamaError, chat_completion

log = get_logger(__name__)


_SYSTEM_PROMPT = (
    "Eres un generador de queries de búsqueda para DuckDuckGo. "
    "Recibes una pregunta del usuario y (opcionalmente) el historial reciente. "
    "Devuelves ÚNICAMENTE la query óptima: 3-8 palabras clave separadas por espacios, "
    "sin comillas, sin puntuación, sin explicaciones, sin verbos de petición. "
    "Si la pregunta pide algo actual, incluye el año actual. "
    "Si es una referencia vaga (\"¿y contra quién?\", \"dime más\"), resuelve "
    "el tema con el historial. Si te falta contexto, devuelve la pregunta "
    "reducida a keywords."
)


_CLEAN_RE = re.compile(r'^[\s"\'`\[\](){}«»]+|[\s"\'`\[\](){}«»]+$')
_ARTICULOS_INICIALES = frozenset({
    "el", "la", "los", "las", "un", "una", "de", "del",
    "que", "en", "con", "por",
})


def _resumir_historial(historial: list[dict], max_msgs: int = 4, max_chars: int = 200) -> str:
    ultimos = historial[-max_msgs:] if historial else []
    partes: list[str] = []
    for m in ultimos:
        rol = "U" if m.get("role") == "user" else "A"
        contenido = (m.get("content") or "").strip()[:max_chars]
        partes.append(f"{rol}: {contenido}")
    return "\n".join(partes)


def _limpiar_query(raw: str) -> str:
    raw = _CLEAN_RE.sub("", raw)
    # El modelo a veces devuelve "Query: xxx" o "Búsqueda: xxx"
    raw = re.sub(r"^(query|búsqueda|busqueda|search)\s*[:\-]\s*", "", raw, flags=re.IGNORECASE)
    # Colapsa saltos de línea y espacios múltiples
    raw = re.sub(r"\s+", " ", raw).strip()
    # Quita signos de puntuación excepto letras/números/espacios/acentos
    raw = re.sub(r"[¿¡?!.,;:]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    # Elimina artículos iniciales redundantes
    palabras = raw.split()
    while palabras and palabras[0].lower() in _ARTICULOS_INICIALES:
        palabras = palabras[1:]
    # Máx 10 palabras
    return " ".join(palabras[:10])


def rewrite_query_with_llm(
    mensaje: str,
    historial: list[dict] | None = None,
    timeout: int = 6,
) -> str | None:
    """Devuelve una query o None si el LLM falla / se salta el timeout."""
    contexto = _resumir_historial(historial or [])
    anio = datetime.now().year

    user_content = (
        f"Fecha actual: {datetime.now().strftime('%d/%m/%Y')} (año {anio}).\n\n"
    )
    if contexto:
        user_content += f"Historial reciente:\n{contexto}\n\n"
    user_content += f"Pregunta: {mensaje}\n\nQuery:"

    try:
        respuesta = chat_completion(
            model=config.OLLAMA_MODEL_FAST,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=30,
            temperature=0.0,
            timeout=timeout,
        )
    except OllamaError as exc:
        log.info("query rewrite falló (%s); usaré fallback regex", exc)
        return None

    if not respuesta:
        return None

    query = _limpiar_query(respuesta)
    if len(query) < 2 or len(query.split()) < 1:
        return None
    log.info("query reescrita por LLM: %r", query)
    return query
