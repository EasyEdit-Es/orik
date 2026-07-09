"""Limpieza de mensajes, extracción de keywords y detección de intención.

Todo puro y sin efectos secundarios — fácil de testear. El LLM no
interviene aquí; ver `topic_detect.py` para eso.
"""

from __future__ import annotations

import re
from datetime import datetime

# ── Patrones compilados una sola vez ──────────────────────────

_RELLENO_PATTERNS = [
    # Peticiones explícitas de búsqueda
    r"\bnecesito que me busques\b", r"\bquiero que me busques\b",
    r"\bque me busques\b", r"\bme busques\b",
    r"\bme puedes buscar\b", r"\bbúscame\b", r"\bbuscame\b",
    r"\bme puedes decir\b", r"\bpuedes decirme\b", r"\bme puedes\b",
    # Verbos de petición
    r"\bpodrías\b", r"\bdime\b", r"\bcuéntame\b", r"\bsabes\b",
    r"\bquiero saber\b", r"\bnecesito saber\b", r"\bquiero\b", r"\bnecesito\b",
    r"\bpor favor\b", r"\bporfavor\b", r"\bporfa\b", r"\boye\b", r"\bhey\b",
    r"\bme dices\b", r"\bhay algún\b", r"\bhay alguna\b",
    # Frases de verificación
    r"\bes cierto que\b", r"\bes verdad que\b",
    # Frases sobre información
    r"\binformación sobre\b", r"\binfo sobre\b", r"\balgo sobre\b",
    r"\bhablar de\b", r"\bhablar sobre\b",
    # Interrogativas compuestas
    r"\bcuál es el\b", r"\bcuál es la\b", r"\bcuáles son\b",
    r"\bqué está\b", r"\bqué ha\b", r"\bpara qué sirve\b",
    r"\bqué pasó en\b", r"\bqué ocurrió\b", r"\bqué es\b", r"\bqué son\b",
    r"\bcuánto vale\b", r"\bcuánto cuesta\b", r"\bcuánto es\b",
    r"\bcuándo es\b", r"\bcuándo fue\b", r"\bcuándo juega\b", r"\bcuándo sale\b",
    r"\bdónde está\b", r"\bdónde queda\b",
    r"\bcontra quién\b", r"\bcontra quien\b",
    r"\bque dia es\b", r"\bque día es\b", r"\bdia es el\b", r"\bdía es el\b",
    r"\blleva el\b", r"\blleva la\b", r"\bllevan los\b",
    r"\bes el\b", r"\bes la\b", r"\bson los\b", r"\bson las\b",
    r"\bjuega el\b", r"\bjuega la\b", r"\bjuegan los\b",
    # Coletillas conversacionales
    r"\bnada nada\b", r"\bsolo con que\b",
    r"\bpor cierto\b", r"\bvale pues\b", r"\ba ver\b", r"\bpero\b",
    r"\bsi hay\b", r"\bsi existe\b", r"\bsi tiene\b",
]

_RELLENO_RE = [re.compile(p, re.IGNORECASE) for p in _RELLENO_PATTERNS]

_PUNTUACION_RE = re.compile(r"[¿¡?!.,;:]+")
_ESPACIOS_RE = re.compile(r"\s+")
_ARTICULOS_INIT_RE = re.compile(
    r"^\s*(el|la|los|las|un|una|de|del|en|con|por|a|que)\s+", re.IGNORECASE
)

_PALABRAS_ACTUALES_RE = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\búltimo\b", r"\búltima\b", r"\bnuevo\b", r"\bnueva\b",
        r"\breciente\b", r"\bactual\b", r"\bhoy\b", r"\bahora\b",
        r"\bnovedades\b", r"\blanzamiento\b", r"\bmejor\b", r"\besta semana\b",
        r"\beste mes\b", r"\besta temporada\b",
    ]
]

_REFERENCIAS_VAGAS_RE = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^(y\s+)?(quién|quien)\s+(metió|metio|marcó|marco|hizo|anotó|anoto)",
        r"^(dame|dime|muéstrame|muestrame)\s+(las?\s+)?(estadísticas|estadisticas|goles?|datos?|info|detalles?)",
        r"^(más|mas)\s+(info|información|informacion|detalles?|datos?)",
        r"^(y\s+)?(el\s+)?(resultado|marcador|score)",
        r"^(qué|que)\s+(pasó|paso|ocurrió|ocurrio)",
    ]
]

_STOPWORDS = frozenset({
    "que", "con", "una", "uno", "los", "las", "del", "por", "para", "como",
    "este", "esta", "pero", "más", "muy", "fue", "son", "hay", "han", "ser",
    "sus", "les", "sin", "sobre", "entre", "también", "puede", "todo",
    "cuando", "donde", "según", "información", "busca", "dame", "dime",
    "muéstrame", "estadísticas", "estadisticas", "porfa", "favor", "partido",
})

_DEPORTES = frozenset({
    "atlético", "atletico", "barça", "barca", "barcelona", "madrid",
    "champions", "liga", "fútbol", "futbol", "copa", "real", "sevilla",
})

_ARTICULOS_LARGA = frozenset({
    "el", "la", "los", "las", "un", "una", "de", "del", "que",
    "en", "con", "me", "te", "le", "se",
})

_SIN_BUSQUEDA_RE = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^(hola|holaa|holi|hey|buenas|buenos días|buenas tardes|buenas noches|ey|hi|hello)[\s!.]*$",
        r"^(cómo estás|como estas|qué tal|que tal|cómo te va|todo bien)[\s?!.]*$",
        r"^(gracias|de nada|ok|vale|entendido|perfecto|genial|bien|claro)[\s!.]*$",
        r"^(jaja|jeje|xd|😂|👍|👌)[\s!.]*$",
    ]
]

_SIN_BUSQUEDA_TEMAS_RE = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bcuánto es \d",
        r"\bcalcula\b",
        r"\bresuelve\b",
        r"\bderiva\b",
        # Preguntas de fecha/hora: el modelo ya tiene la fecha en el system prompt.
        # Se excluyen si mencionan un evento concreto (partido, vuelo, apertura...) → sí buscar.
        r"^\s*¿?\s*(qué|que)\s+(día|dia|fecha|mes)\s+(es|son|estamos)\b(?!.*\b(partido|vuelo|concierto|evento|abre|abren|cierra|cierran|estrena|estreno)\b)",
        r"^\s*¿?\s*(qué|que)\s+(día|dia)\s+es\s+(hoy|mañana|manana|ayer)\s*[¿?!.]*\s*$",
        r"^\s*¿?\s*(a\s+)?(qué|que)\s+hora\s+(es|son)\b(?!.*\b(partido|vuelo|concierto|evento|abre|abren|cierra|cierran|estrena|estreno)\b)",
        r"^\s*¿?\s*(cuál|cual)\s+es\s+(la\s+|el\s+)?(fecha|hora|día|dia)\b(?!.*\b(partido|vuelo|concierto|evento|abre|abren|cierra|cierran|estrena|estreno)\b)",
        r"^\s*¿?\s*(en\s+)?(qué|que)\s+año\s+estamos\b",
        r"^\s*¿?\s*dime\s+(la\s+|el\s+)?(hora|fecha|día|dia)\s*[¿?!.]*\s*$",
        r"\bintegra\b",
        r"^\d[\d\s\+\-\*\/\(\)\.]+$",
    ]
]


# ── API pública ──────────────────────────────────────────────

def limpiar_mensaje(mensaje: str) -> str:
    """Elimina relleno conversacional y devuelve el contenido útil."""
    texto = mensaje.strip()
    texto = _PUNTUACION_RE.sub(" ", texto)
    for pat in _RELLENO_RE:
        texto = pat.sub(" ", texto)
    texto = _ARTICULOS_INIT_RE.sub("", texto)
    texto = _ESPACIOS_RE.sub(" ", texto).strip()
    return texto


def es_referencia_vaga(msg_lower: str) -> bool:
    """Detecta si el mensaje refiere al contexto anterior sin tema explícito."""
    if any(pat.search(msg_lower) for pat in _REFERENCIAS_VAGAS_RE):
        return True
    palabras_reales = [p for p in msg_lower.split() if len(p) > 2]
    return len(palabras_reales) <= 3


def tema_del_historial(historial: list[dict], anio: int | None = None) -> str:
    """Extrae palabras clave del último tema del historial."""
    candidatos: list[str] = []
    for msg in reversed(historial[-4:]):
        if msg.get("role") != "user":
            continue
        texto = limpiar_mensaje(msg.get("content", "").lower())
        palabras = [p for p in texto.split() if len(p) > 3 and p not in _STOPWORDS]
        candidatos.extend(palabras[:6])
        if len(candidatos) >= 4:
            break

    vistos: set[str] = set()
    unicos: list[str] = []
    for p in candidatos:
        if p not in vistos:
            vistos.add(p)
            unicos.append(p)

    tema = " ".join(unicos[:5])
    anio = anio or datetime.now().year
    if any(d in tema for d in _DEPORTES) and str(anio) not in tema:
        tema = f"{tema} {anio}"
    return tema


def intent_del_mensaje(msg: str) -> str:
    msg = msg.lower()
    if re.search(r"(quién|quien)\s*(metió|metio|marcó|marco|anotó|anoto|hizo)", msg):
        return "goleadores"
    if "estadísticas" in msg or "estadisticas" in msg:
        return "estadísticas"
    if "tarjeta" in msg:
        return "tarjetas"
    if "posesión" in msg or "posesion" in msg:
        return "estadísticas posesión"
    if any(w in msg for w in ("resultado", "marcador", "score")):
        return "resultado"
    return ""


def construir_query(
    mensaje: str,
    historial: list[dict] | None = None,
    hay_cambio: bool = False,
    anio: int | None = None,
) -> str:
    """Construye la query de búsqueda a partir del mensaje y el historial.

    1. Limpia relleno conversacional con regex.
    2. Si el resultado es una referencia vaga, resuelve el tema con el historial.
    3. Añade el año si la pregunta es sobre actualidad.
    4. Recorta a máximo 8 palabras.
    """
    anio = anio or datetime.now().year
    msg_lower = mensaje.lower().strip()

    texto_limpio = limpiar_mensaje(mensaje)

    if not hay_cambio and historial and es_referencia_vaga(msg_lower):
        tema = tema_del_historial(historial, anio)
        if tema:
            intent = intent_del_mensaje(msg_lower)
            return (f"{intent} {tema}".strip() if intent else tema)

    palabras = texto_limpio.split()
    if len(palabras) < 2:
        texto_limpio = _PUNTUACION_RE.sub(" ", mensaje).strip()[:80]
        palabras = texto_limpio.split()

    for pat in _PALABRAS_ACTUALES_RE:
        if pat.search(mensaje):
            if str(anio) not in texto_limpio:
                texto_limpio = f"{texto_limpio} {anio}"
            break

    palabras_final = texto_limpio.split()
    if len(palabras_final) > 8:
        while palabras_final and palabras_final[0].lower() in _ARTICULOS_LARGA:
            palabras_final = palabras_final[1:]
    return " ".join(palabras_final[:8])


def es_saludo_o_charla(msg: str) -> bool:
    return any(pat.match(msg) for pat in _SIN_BUSQUEDA_RE)


def es_operacion_matematica(msg: str) -> bool:
    return any(pat.search(msg) for pat in _SIN_BUSQUEDA_TEMAS_RE)


def decidir_busqueda(
    mensaje: str,
    historial: list[dict] | None = None,
    hay_cambio: bool = False,
) -> tuple[bool, str]:
    """¿Hay que buscar en web? Devuelve (buscar, query)."""
    msg = mensaje.lower().strip()

    if es_saludo_o_charla(msg):
        return False, ""
    if es_operacion_matematica(msg):
        return False, ""

    query = construir_query(mensaje, historial or [], hay_cambio=hay_cambio)
    return True, query
