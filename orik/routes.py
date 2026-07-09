"""Rutas HTTP de la app Flask (chat, memoria, salud)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from functools import wraps

from flask import Blueprint, Response, jsonify, render_template, request, session, stream_with_context

from . import config, memoria, nlp, query_rewrite, search, session_store, topic_detect
from .logging_setup import get_logger
from .ollama_client import OllamaError, chat_completion, chat_stream

log = get_logger(__name__)

bp = Blueprint("orik", __name__)


def _require_auth(fn):
    """Si ORIK_API_TOKEN está configurado, exige Authorization: Bearer <token>."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = config.API_TOKEN
        if not expected:
            return fn(*args, **kwargs)
        got = request.headers.get("Authorization", "")
        if got.startswith("Bearer ") and got[7:] == expected:
            return fn(*args, **kwargs)
        return jsonify({"error": "No autorizado"}), 401

    return wrapper


def _get_sid() -> str:
    sid = session.get("sid")
    if not sid:
        sid = session_store.new_session_id()
        session["sid"] = sid
        session.permanent = True
    return sid


def _build_system_prompt(memoria_txt: str) -> str:
    fecha = datetime.now().strftime("%d/%m/%Y")
    memoria_bloque = f"\n{memoria_txt}" if memoria_txt else ""
    return (
        "Eres Orik, un asistente IA útil, inteligente y amable. Respondes siempre en español.\n"
        "Si alguien pregunta por quién te creó, di que fuiste creado por Jorge Sánchez Villanueva.\n"
        f"Hoy es {fecha}.\n\n"
        "REGLA CRÍTICA SOBRE DATOS DE INTERNET:\n"
        "Cuando en el mensaje del usuario aparezca un bloque \"DATOS REALES OBTENIDOS DE INTERNET\",\n"
        "esos datos son información actual y verificada que acabas de buscar en la web. "
        "Cada resultado va numerado y lleva su fuente y URL. DEBES basar tu respuesta en esos datos "
        "y, si citas algo concreto, referencia la fuente entre paréntesis como (fuente: dominio) o "
        "con el número entre corchetes [1], [2]. NO digas que no tienes acceso a información en "
        "tiempo real. Si los datos no contienen exactamente lo que se pregunta, dilo brevemente "
        "y extrae lo más relevante. No inventes cifras ni fechas que no aparezcan en los datos."
        f"{memoria_bloque}"
    )


def _prepare_messages(
    mensaje_usuario: str,
    history: list[dict],
    busqueda_permitida: bool,
) -> tuple[list[dict], bool, bool]:
    """Devuelve (messages, cambio_de_tema, debe_buscar)."""
    memoria_txt = memoria.memoria_a_texto(memoria.cargar_memoria())
    sistema = _build_system_prompt(memoria_txt)

    if not busqueda_permitida:
        log.info("Modo sin web → llamada directa al modelo inteligente")
        return (
            [{"role": "system", "content": sistema},
             {"role": "user", "content": mensaje_usuario}],
            False,
            False,
        )

    historial_previo = history[:-1]  # excluye el mensaje recién añadido
    cambio_de_tema = topic_detect.detectar_cambio_de_tema(mensaje_usuario, historial_previo)
    if cambio_de_tema:
        log.info("Historial previo omitido (cambio de tema)")

    debe_buscar, query = nlp.decidir_busqueda(
        mensaje_usuario, historial_previo, hay_cambio=cambio_de_tema
    )

    # Si la regex-only produjo algo pobre, delegar en el LLM rápido para
    # reescribir la query. Solo cuando merece la pena: pregunta larga o
    # query resultante corta/floja.
    if debe_buscar and (len(mensaje_usuario.split()) >= 5 or len(query.split()) < 3):
        mejorada = query_rewrite.rewrite_query_with_llm(
            mensaje_usuario,
            historial_previo if not cambio_de_tema else None,
        )
        if mejorada:
            query = mejorada

    log.info("Buscar en web=%s | query=%r", debe_buscar, query)

    contexto_web = ""
    if debe_buscar:
        contexto_web = search.buscar_en_web(query)
        if contexto_web and len(contexto_web.strip()) > 30:
            log.info("Contexto web %d chars", len(contexto_web))
        else:
            log.info("Sin resultados útiles de búsqueda")
            contexto_web = ""

    messages: list[dict] = [{"role": "system", "content": sistema}]
    if contexto_web:
        mensaje_con_contexto = (
            f"{mensaje_usuario}\n\n"
            f"DATOS REALES OBTENIDOS DE INTERNET AHORA MISMO (úsalos como hechos verificados, "
            f"no los atribuyas al usuario ni dudes de ellos):\n{contexto_web}"
        )
        if not cambio_de_tema:
            messages += historial_previo
        messages.append({"role": "user", "content": mensaje_con_contexto})
    else:
        if cambio_de_tema:
            messages.append({"role": "user", "content": mensaje_usuario})
        else:
            messages += history[:]

    return messages, cambio_de_tema, debe_buscar


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/healthz", methods=["GET"])
def healthz():
    from .ollama_client import is_ollama_running
    return jsonify({
        "status": "ok",
        "ollama": is_ollama_running(),
        "model": config.OLLAMA_MODEL,
    })


@bp.route("/chat", methods=["POST"])
@_require_auth
def chat():
    datos = request.get_json(silent=True) or {}
    mensaje_usuario = (datos.get("mensaje") or "").strip()
    busqueda_permitida = bool(datos.get("busqueda_web", True))
    quiere_stream = bool(datos.get("stream", True))

    if not mensaje_usuario:
        return jsonify({"error": "Mensaje vacío"}), 400
    if len(mensaje_usuario) > 8000:
        return jsonify({"error": "Mensaje demasiado largo (max 8000 caracteres)"}), 413

    log.info("Mensaje: %r", mensaje_usuario[:60])

    sid = _get_sid()
    history = session_store.load_history(sid)
    history.append({"role": "user", "content": mensaje_usuario})
    history = history[-config.HISTORY_MAX_TURNS:]

    modelo_activo = config.OLLAMA_MODEL if busqueda_permitida else config.OLLAMA_MODEL_SMART

    try:
        messages, cambio_de_tema, debe_buscar = _prepare_messages(
            mensaje_usuario, history, busqueda_permitida
        )
    except Exception as exc:
        log.exception("Fallo preparando mensajes: %s", exc)
        return jsonify({"error": "Fallo interno preparando el prompt"}), 500

    backend_label = f"Orik + {modelo_activo}" + (" + DuckDuckGo" if debe_buscar else "")

    if quiere_stream:
        return _stream_response(
            sid, history, messages, modelo_activo,
            backend_label, cambio_de_tema, debe_buscar,
        )

    # Respuesta bloqueante (compatibilidad con clientes viejos)
    try:
        respuesta = chat_completion(model=modelo_activo, messages=messages)
    except OllamaError as exc:
        log.warning("Fallo Ollama: %s", exc)
        return jsonify({"error": "Error conectando con Ollama"}), 502

    if not respuesta:
        respuesta = "Disculpa, no pude procesar tu solicitud. Intenta de nuevo."

    history.append({"role": "assistant", "content": respuesta})
    session_store.save_history(sid, history[-config.HISTORY_MAX_TURNS:])

    return jsonify({
        "respuesta": respuesta,
        "backend": backend_label,
        "busqueda_web": debe_buscar,
        "cambio_de_tema": cambio_de_tema,
    })


def _stream_response(
    sid: str,
    history: list[dict],
    messages: list[dict],
    modelo_activo: str,
    backend_label: str,
    cambio_de_tema: bool,
    debe_buscar: bool,
) -> Response:
    def sse(event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    def generate() -> Iterator[str]:
        acumulado: list[str] = []
        # Anuncio inicial de metadatos para que el frontend pinte el estado
        yield sse({
            "meta": {
                "backend": backend_label,
                "busqueda_web": debe_buscar,
                "cambio_de_tema": cambio_de_tema,
                "model": modelo_activo,
            }
        })
        try:
            for token in chat_stream(model=modelo_activo, messages=messages):
                acumulado.append(token)
                yield sse({"token": token})
        except OllamaError as exc:
            log.warning("Fallo streaming Ollama: %s", exc)
            yield sse({"error": "Error conectando con Ollama"})
            return

        respuesta = "".join(acumulado).strip()
        if not respuesta:
            respuesta = "Disculpa, no pude procesar tu solicitud. Intenta de nuevo."
            yield sse({"token": respuesta})

        history.append({"role": "assistant", "content": respuesta})
        session_store.save_history(sid, history[-config.HISTORY_MAX_TURNS:])
        yield sse({"done": True})

    resp = Response(stream_with_context(generate()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@bp.route("/memoria", methods=["GET"])
def ver_memoria():
    return jsonify(memoria.cargar_memoria())


@bp.route("/memoria/borrar", methods=["POST"])
@_require_auth
def borrar_memoria():
    memoria.guardar_memoria({})
    return jsonify({"ok": True})


@bp.route("/historial/borrar", methods=["POST"])
@_require_auth
def borrar_historial():
    sid = session.get("sid")
    if sid:
        session_store.clear_history(sid)
    session.pop("sid", None)
    return jsonify({"ok": True})
