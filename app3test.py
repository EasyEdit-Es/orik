from datetime import timedelta, datetime
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from urllib.parse import urlparse
from flask import Flask, request, jsonify, render_template, session

app = Flask(__name__, template_folder="templates")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

# ── Configuración ─────────────────────────────────────────────
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b")          # modelo principal (con web)
OLLAMA_MODEL_SMART = os.getenv("OLLAMA_MODEL_SMART", "gpt-oss:20b")  # modelo sin web (mas capaz)
OLLAMA_MODEL_FAST = os.getenv("OLLAMA_MODEL_FAST", "gemma4:e2b")  # modelo rápido para keywords
OLLAMA_START_COMMAND = os.getenv("OLLAMA_START_COMMAND", "ollama serve")
OLLAMA_START_TIMEOUT = int(os.getenv("OLLAMA_START_TIMEOUT", "30"))

MEMORIA_FILE = os.path.join(os.path.dirname(__file__), "memoria.json")
_MEMORIA_LOCK = threading.Lock()


# ── Ollama helpers ────────────────────────────────────────────
def is_ollama_running(host: str) -> bool:
    for endpoint in ["/api/tags", "/api/models", "/"]:
        try:
            resp = requests.get(f"{host}{endpoint}", timeout=5)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            continue
    return False


def is_port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


def get_pids_by_port(port: int) -> list[int]:
    pids = []
    if os.name == "nt":
        cmd = ["netstat", "-ano"]
        try:
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            return []
        for line in output.splitlines():
            if not line.strip().startswith("TCP"):
                continue
            parts = re.split(r"\s+", line.strip())
            if len(parts) < 5:
                continue
            local_address = parts[1]
            pid = parts[4]
            if local_address.endswith(f":{port}"):
                try:
                    pids.append(int(pid))
                except ValueError:
                    continue
    else:
        try:
            output = subprocess.check_output(
                ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"],
                text=True, stderr=subprocess.DEVNULL
            )
            for line in output.strip().splitlines():
                try:
                    pids.append(int(line.strip()))
                except ValueError:
                    continue
        except Exception:
            return []
    return sorted(set(pids))


def kill_process(pid: int) -> None:
    if pid == os.getpid():
        raise RuntimeError("El proceso actual no puede cerrarse a sí mismo.")
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return


def start_ollama_server():
    if is_ollama_running(OLLAMA_HOST):
        return None

    parsed = urlparse(OLLAMA_HOST)
    host_netloc = parsed.hostname or parsed.path
    port = parsed.port or 11434

    if is_port_in_use(host_netloc, port):
        print(f"⚠️ Puerto {port} en uso. Esperando a que Ollama responda...")
        deadline = time.time() + 10
        while time.time() < deadline:
            if is_ollama_running(OLLAMA_HOST):
                print("✅ Ollama respondió. Usando instancia existente.")
                return None
            time.sleep(1)
        raise RuntimeError(
            f"El puerto {port} está ocupado pero Ollama no responde. "
            "Asegúrate de que esté corriendo correctamente."
        )

    if "localhost" not in OLLAMA_HOST and "127.0.0.1" not in OLLAMA_HOST:
        raise RuntimeError("OLLAMA_HOST no apunta a localhost; no se puede iniciar Ollama localmente.")

    try:
        args = shlex.split(OLLAMA_START_COMMAND, posix=os.name != "nt")
    except Exception:
        args = OLLAMA_START_COMMAND.split()

    print(f"⌛ Intentando iniciar Ollama con: {OLLAMA_START_COMMAND}")
    proc = subprocess.Popen(args, stdout=None, stderr=None)

    deadline = time.time() + OLLAMA_START_TIMEOUT
    while time.time() < deadline:
        if is_ollama_running(OLLAMA_HOST):
            print("✅ Ollama está listo.")
            return proc
        time.sleep(1)

    proc.terminate()
    raise RuntimeError(f"No se pudo iniciar Ollama en {OLLAMA_HOST} en {OLLAMA_START_TIMEOUT}s.")


def ensure_ollama_running():
    if is_ollama_running(OLLAMA_HOST):
        print("✅ Ollama ya estaba en ejecución.")
        return
    try:
        start_ollama_server()
    except RuntimeError as e:
        print(f"⚠️ Advertencia al iniciar Ollama: {e}")
        print("   Continuando de todos modos.")


# ── Detección de cambio de tema ───────────────────────────────

def detectar_cambio_de_tema(mensaje_nuevo: str, historial: list) -> bool:
    """
    Usa el LLM rápido para decidir si el mensaje nuevo es continuación
    del tema anterior o un tema completamente nuevo.

    Ejemplos de CONTINUA: "¿contra quién?", "¿a qué hora?", "¿y el marcador?",
                           "dime más", "¿quién ganó?", "¿cuánto costaba?"
    Ejemplos de NUEVO:     pasar de fútbol a Fortnite, de crypto a una receta,
                           de política a una película.

    Si el historial está vacío o el LLM falla → False (no limpia, más seguro).
    """
    if not historial or len(historial) < 2:
        return False

    # Resumen de los últimos 3 turnos (max 200 chars por mensaje)
    ultimos = historial[-6:]
    resumen = []
    for m in ultimos:
        rol = "U" if m.get("role") == "user" else "A"
        contenido = m.get("content", "").strip()[:200]
        resumen.append(f"{rol}: {contenido}")
    contexto = "\n".join(resumen)

    try:
        payload = {
            "model": OLLAMA_MODEL_FAST,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Eres un clasificador de conversaciones. "
                        "Se te da el historial reciente y un mensaje nuevo. "
                        "Decide si el mensaje nuevo es:\n"
                        "- CONTINUA: es seguimiento del tema anterior, aunque no lo mencione "
                        "explícitamente (ej: '¿contra quién?', '¿a qué hora?', 'y el resultado?', "
                        "'dime más', '¿quién ganó?').\n"
                        "- NUEVO: tema completamente distinto sin relación con lo anterior.\n\n"
                        "Responde ÚNICAMENTE con una palabra: CONTINUA o NUEVO. Nada más."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Historial:\n{contexto}\n\n"
                        f"Mensaje nuevo: {mensaje_nuevo}\n\n"
                        f"¿CONTINUA o NUEVO?"
                    )
                }
            ],
            "stream": False,
            "options": {"num_predict": 5, "temperature": 0.0},
        }
        resp = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=8)
        if resp.ok:
            decision = resp.json().get("message", {}).get("content", "").strip().upper()
            decision = re.sub(r"[^A-Z]", "", decision)
            es_nuevo = decision.startswith("NUEVO")
            if es_nuevo:
                print(f"🔄 LLM detectó cambio de tema → limpiando contexto previo")
            else:
                print(f"↩️  LLM detectó continuación de tema → manteniendo historial")
            return es_nuevo
    except Exception as e:
        print(f"⚠️ Error en detectar_cambio_de_tema: {e}")

    return False  # Por defecto no limpiar


# ── Extracción de keywords ───────────────────────────────────

# Palabras de relleno a eliminar antes de buscar
_RELLENO = [
    # Peticiones explícitas de búsqueda
    r"\bnecesito que me busques\b", r"\bquiero que me busques\b", r"\bque me busques\b", r"\bme busques\b",
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

_PALABRAS_ACTUALES = [
    r"\búltimo\b", r"\búltima\b", r"\bnuevo\b", r"\bnueva\b",
    r"\breciente\b", r"\bactual\b", r"\bhoy\b", r"\bahora\b",
    r"\bnovedades\b", r"\blanzamiento\b", r"\bmejor\b", r"\besta semana\b",
    r"\beste mes\b", r"\besta temporada\b",
]

_REFERENCIAS_VAGAS = [
    r"^(y\s+)?(quién|quien)\s+(metió|metio|marcó|marco|hizo|anotó|anoto)",
    r"^(dame|dime|muéstrame|muestrame)\s+(las?\s+)?(estadísticas|estadisticas|goles?|datos?|info|detalles?)",
    r"^(más|mas)\s+(info|información|informacion|detalles?|datos?)",
    r"^(y\s+)?(el\s+)?(resultado|marcador|score)",
    r"^(qué|que)\s+(pasó|paso|ocurrió|ocurrio)",
]

_STOPWORDS = {
    "que", "con", "una", "uno", "los", "las", "del", "por", "para", "como",
    "este", "esta", "pero", "más", "muy", "fue", "son", "hay", "han", "ser",
    "sus", "les", "sin", "sobre", "entre", "también", "puede", "todo",
    "cuando", "donde", "según", "información", "busca", "dame", "dime",
    "muéstrame", "estadísticas", "estadisticas", "porfa", "favor", "partido",
}

_DEPORTES = ["atlético", "atletico", "barça", "barca", "barcelona", "madrid",
             "champions", "liga", "fútbol", "futbol", "copa", "real", "sevilla"]


def _limpiar_mensaje(mensaje: str) -> str:
    """Limpia el mensaje de relleno conversacional y devuelve solo el contenido útil."""
    texto = mensaje.strip()
    texto = re.sub(r"[¿¡?!.,;:]+", " ", texto)
    for p in _RELLENO:
        texto = re.sub(p, " ", texto, flags=re.IGNORECASE)
    # Eliminar artículos iniciales sobrantes
    texto = re.sub(r"^\s*(el|la|los|las|un|una|de|del|en|con|por|a|que)\s+", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _es_referencia_vaga(msg_lower: str) -> bool:
    """Detecta si el mensaje es una referencia al contexto anterior sin tema explícito."""
    if any(re.search(p, msg_lower) for p in _REFERENCIAS_VAGAS):
        return True
    palabras_reales = [p for p in msg_lower.split() if len(p) > 2]
    return len(palabras_reales) <= 3


def _tema_del_historial(historial: list) -> str:
    """Extrae las palabras clave del último tema del historial."""
    candidatos = []
    for msg in reversed(historial[-4:]):
        if msg.get("role") == "user":
            texto = msg.get("content", "").lower()
            texto = _limpiar_mensaje(texto)
            palabras = [p for p in texto.split() if len(p) > 3 and p not in _STOPWORDS]
            candidatos.extend(palabras[:6])
            if len(candidatos) >= 4:
                break
    vistos, unicos = set(), []
    for p in candidatos:
        if p not in vistos:
            vistos.add(p)
            unicos.append(p)
    tema = " ".join(unicos[:5])
    año = datetime.now().year
    if any(d in tema for d in _DEPORTES) and str(año) not in tema:
        tema += f" {año}"
    return tema


def _intent_del_mensaje(msg: str) -> str:
    if re.search(r"(quién|quien)\s*(metió|metio|marcó|marco|anotó|anoto|hizo)", msg):
        return "goleadores"
    if re.search(r"estadísticas|estadisticas", msg):
        return "estadísticas"
    if re.search(r"tarjetas?", msg):
        return "tarjetas"
    if re.search(r"posesión|posesion", msg):
        return "estadísticas posesión"
    if re.search(r"resultado|marcador|score", msg):
        return "resultado"
    return ""


def construir_query(mensaje: str, historial: list | None = None, hay_cambio: bool = False) -> str:
    """
    Construye la query de búsqueda en dos pasos:
    1. Limpia el mensaje con regex (rápido, fiable, sin LLM)
    2. Si el resultado es una referencia vaga, resuelve el tema con el historial

    El LLM NO interviene aquí. Era la fuente del problema: devolvía
    la frase sin limpiar o añadía preámbulos que arruinaban la query.
    """
    año = datetime.now().year
    msg_lower = mensaje.lower().strip()

    # Paso 1: limpiar relleno conversacional
    texto_limpio = _limpiar_mensaje(mensaje)

    # Paso 2: si el resultado es muy corto o es una referencia vaga,
    # resolver el tema desde el historial (excepto si hay cambio de tema)
    if not hay_cambio and historial and _es_referencia_vaga(msg_lower):
        tema = _tema_del_historial(historial)
        if tema:
            intent = _intent_del_mensaje(msg_lower)
            query = f"{intent} {tema}".strip() if intent else tema
            print(f"🔑 Query (referencia resuelta): \'{query}\'")
            return query

    # Paso 3: si el texto limpio quedó demasiado corto, usar el mensaje original recortado
    palabras = texto_limpio.split()
    if len(palabras) < 2:
        texto_limpio = re.sub(r"[¿¡?!.,;:]+", " ", mensaje).strip()[:80]
        palabras = texto_limpio.split()

    # Paso 4: añadir año si la pregunta es sobre actualidad
    for p in _PALABRAS_ACTUALES:
        if re.search(p, mensaje, re.IGNORECASE):
            if str(año) not in texto_limpio:
                texto_limpio = f"{texto_limpio} {año}"
            break

    # Paso 5: recortar a máximo 8 palabras
    # Importante: tomamos las ÚLTIMAS 8 palabras, no las primeras,
    # porque tras limpiar el relleno inicial el sujeto real suele quedar al final
    # Ej: "me busques el filtro de aire de skoda octavia" → "filtro aire skoda octavia"
    palabras_final = texto_limpio.split()
    if len(palabras_final) > 8:
        # Intentar tomar desde donde empieza el contenido real (quitar artículos iniciales)
        while palabras_final and palabras_final[0].lower() in {"el","la","los","las","un","una","de","del","que","en","con","me","te","le","se"}:
            palabras_final = palabras_final[1:]
    query = " ".join(palabras_final[:8])
    print(f"🔑 Query (regex): \'{query}\'")
    return query


# ── Detección de necesidad de búsqueda web ────────────────────
def decidir_busqueda(mensaje: str, historial: list | None = None, hay_cambio: bool = False) -> tuple[bool, str]:
    """
    Decide si hay que buscar en web y extrae la query óptima usando LLM.
    Solo omite la búsqueda para saludos puros y operaciones matemáticas.
    """
    msg = mensaje.lower().strip()

    # Casos donde buscar no tiene ningún sentido
    SIN_BUSQUEDA = [
        r"^(hola|holaa|holi|hey|buenas|buenos días|buenas tardes|buenas noches|ey|hi|hello)[\s!.]*$",
        r"^(cómo estás|como estas|qué tal|que tal|cómo te va|todo bien)[\s?!.]*$",
        r"^(gracias|de nada|ok|vale|entendido|perfecto|genial|bien|claro)[\s!.]*$",
        r"^(jaja|jeje|xd|😂|👍|👌)[\s!.]*$",
    ]
    for patron in SIN_BUSQUEDA:
        if re.match(patron, msg, re.IGNORECASE):
            print("ℹ️ Saludo/charla detectado → sin búsqueda")
            return False, ""

    # Operaciones matemáticas puras
    SIN_BUSQUEDA_TEMAS = [
        r"\bcuánto es \d",
        r"\bcalcula\b",
        r"\bresuelve\b",
        r"\bderiva\b",
        r"\bintegra\b",
        r"^\d[\d\s\+\-\*\/\(\)\.]+$",
    ]
    for patron in SIN_BUSQUEDA_TEMAS:
        if re.search(patron, msg, re.IGNORECASE):
            print("ℹ️ Operación matemática → sin búsqueda")
            return False, ""

    # Extraer keywords con LLM (con fallback a regex), pasando historial para contexto
    query = construir_query(mensaje, historial or [], hay_cambio=hay_cambio)
    return True, query


# ── Búsqueda web en paralelo ──────────────────────────────────
def _buscar_ddgs(query: str, max_results: int) -> tuple[str, str] | None:
    try:
        from ddgs import DDGS
        ddgs = DDGS(timeout=8)
        resultados = list(ddgs.text(query, region='es-es', safesearch='moderate', max_results=max_results))
        if not resultados:
            return None
        texto = "📡 DuckDuckGo:\n\n"
        for i, r in enumerate(resultados[:max_results], 1):
            titulo = r.get("title", "Sin título")
            url = r.get("href", "")
            snippet = r.get("body", "")[:400]
            texto += f"{i}. {titulo}\n"
            if url:
                texto += f"   Fuente: {url}\n"
            texto += f"   {snippet}\n\n"
        return ("DuckDuckGo (DDGS)", texto.strip())
    except ImportError:
        print("⚠️ ddgs no instalado")
        return None
    except Exception as e:
        print(f"❌ Error DDGS: {e}")
        return None


def _buscar_ddg_instant(query: str) -> tuple[str, str] | None:
    try:
        resp = requests.get(
            "https://api.duckduckgo.com",
            params={"q": query, "format": "json", "kl": "es-es", "no_html": 1, "skip_disambig": 1},
            timeout=6,
        )
        if not resp.ok:
            return None
        data = resp.json()
        abstract = data.get("AbstractText", "")
        related = data.get("RelatedTopics", [])
        texto = ""
        if abstract:
            texto += f"💡 Resumen: {abstract}\n\n"
        count = 0
        for t in related:
            if isinstance(t, dict) and t.get("Text"):
                texto += f"- {t['Text']}\n"
                count += 1
                if count >= 4:
                    break
        if not texto.strip():
            return None
        return ("DuckDuckGo Instant", texto.strip())
    except Exception as e:
        print(f"❌ Error DDG Instant: {e}")
        return None


def _buscar_wikipedia(query: str) -> tuple[str, str] | None:
    try:
        sresp = requests.get(
            "https://es.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": query,
                    "format": "json", "srlimit": 2},
            timeout=6,
        )
        if not sresp.ok:
            return None
        hits = sresp.json().get("query", {}).get("search", [])
        if not hits:
            return None

        wiki_text = "📚 Wikipedia:\n\n"

        def get_extract(hit):
            pid = hit.get("pageid")
            title = hit.get("title", "")
            try:
                eres = requests.get(
                    "https://es.wikipedia.org/w/api.php",
                    params={"action": "query", "prop": "extracts", "explaintext": 1,
                            "pageids": pid, "format": "json", "exintro": 1},
                    timeout=5,
                )
                if eres.ok:
                    pages = eres.json().get("query", {}).get("pages", {})
                    extract = pages.get(str(pid), {}).get("extract", "")[:300]
                    return f"- {title}: {extract}\n\n"
            except Exception:
                pass
            return f"- {title}\n\n"

        with ThreadPoolExecutor(max_workers=2) as ex:
            extractos = list(ex.map(get_extract, hits))

        wiki_text += "".join(extractos)
        return ("Wikipedia (es)", wiki_text.strip())
    except Exception as e:
        print(f"❌ Error Wikipedia: {e}")
        return None


def _buscar_yahoo_finance(query: str) -> tuple[str, str] | None:
    if not any(k in query.lower() for k in ["barril", "petróleo", "petroleo", "crudo", "oil",
                                              "bitcoin", "ethereum", "crypto", "bolsa"]):
        return None
    try:
        symbols = "CL=F,BZ=F,BTC-USD,ETH-USD"
        yf = requests.get(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": symbols},
            timeout=6,
        )
        if not yf.ok:
            return None
        qdata = yf.json().get("quoteResponse", {}).get("result", [])
        if not qdata:
            return None
        texto = "🛢️ Precios (Yahoo Finance):\n\n"
        for q in qdata:
            sym = q.get("symbol")
            name = q.get("shortName") or q.get("longName") or sym
            price = q.get("regularMarketPrice")
            change = q.get("regularMarketChange", 0)
            change_pct = q.get("regularMarketChangePercent", 0)
            texto += f"{name} ({sym}): {price} USD ({change:+.2f}, {change_pct:+.2f}%)\n"
        return ("Yahoo Finance", texto.strip())
    except Exception as e:
        print(f"❌ Error Yahoo Finance: {e}")
        return None


def buscar_en_web(query: str, max_results: int = 8) -> str:
    """
    Lanza todas las fuentes en paralelo y devuelve los mejores resultados combinados.
    Tiempo máximo total: ~12 segundos.
    """
    tareas = {
        "ddgs": lambda: _buscar_ddgs(query, max_results),
        "instant": lambda: _buscar_ddg_instant(query),
        "wiki": lambda: _buscar_wikipedia(query),
        "finance": lambda: _buscar_yahoo_finance(query),
    }

    resultados = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futuros = {executor.submit(fn): nombre for nombre, fn in tareas.items()}
        for futuro in as_completed(futuros, timeout=12):
            nombre = futuros[futuro]
            try:
                resultado = futuro.result(timeout=0)
                if resultado:
                    resultados[nombre] = resultado
                    print(f"✅ {nombre} completado")
            except Exception as e:
                print(f"⚠️ {nombre} falló: {e}")

    ORDEN = ["finance", "ddgs", "instant", "wiki"]
    ordenados = []
    for clave in ORDEN:
        if clave in resultados:
            ordenados.append(resultados[clave])

    if not ordenados:
        return ""

    combined = ""
    for src, txt in ordenados[:4]:
        combined += f"--- {src} ---\n{txt}\n\n"

    return combined.strip()


# ── Cliente Ollama ────────────────────────────────────────────
class OllamaBackend:
    def __init__(self, host, model):
        self.host = host
        self.model = model

    def chat_completion(self, model, messages, max_tokens=4096):
        url = f"{self.host}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.75},
        }
        try:
            resp = requests.post(url, json=payload, timeout=300)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content")
        except Exception as e:
            raise RuntimeError(f"Error conectando con Ollama: {e}")


# ── Memoria ───────────────────────────────────────────────────
def cargar_memoria():
    with _MEMORIA_LOCK:
        if os.path.exists(MEMORIA_FILE):
            try:
                with open(MEMORIA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
    return {}


def guardar_memoria(memoria):
    with _MEMORIA_LOCK:
        try:
            with open(MEMORIA_FILE, "w", encoding="utf-8") as f:
                json.dump(memoria, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def memoria_a_texto(memoria):
    if not memoria:
        return ""
    return "Información sobre el usuario:\n" + "\n".join([f"- {k}: {v}" for k, v in memoria.items()])


# ── Ruta del Chat ─────────────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    try:
        datos = request.get_json(silent=True) or {}
        mensaje_usuario = datos.get("mensaje", "").strip()
        busqueda_permitida = datos.get("busqueda_web", True)  # True por defecto

        if not mensaje_usuario:
            return jsonify({"error": "Mensaje vacío"}), 400

        print(f"📝 Mensaje recibido: {mensaje_usuario[:60]}...")

        memoria = cargar_memoria()
        memoria_texto = memoria_a_texto(memoria)

        sistema = f"""Eres Orik, un asistente IA útil, inteligente y amable. Respondes siempre en español.
Si alguien pregunta por quién te creó, di que fuiste creado por Jorge Sánchez Villanueva.
Hoy es {datetime.now().strftime('%d/%m/%Y')}.

REGLA CRÍTICA SOBRE DATOS DE INTERNET:
Cuando en el mensaje del usuario aparezca un bloque "DATOS REALES OBTENIDOS DE INTERNET",
esos datos son información actual y verificada que acabas de buscar. DEBES usarlos para responder.
NO digas que no tienes acceso a información en tiempo real. NO digas que no puedes acceder a horarios.
Si los datos están ahí, úsalos directamente y responde con confianza.
Si los datos no contienen exactamente lo que se pregunta, dilo pero extrae lo más relevante.{chr(10) + memoria_texto if memoria_texto else ""}"""

        history = session.get("history", [])
        history.append({"role": "user", "content": mensaje_usuario})
        history = history[-35:]

        # Elegir modelo según si hay búsqueda web activa
        modelo_activo = OLLAMA_MODEL if busqueda_permitida else OLLAMA_MODEL_SMART
        print(f"🤖 Modelo: {modelo_activo}")
        client = OllamaBackend(OLLAMA_HOST, modelo_activo)

        # ── Modo sin web: directo al LLM con historial completo ──
        if not busqueda_permitida:
            print("🚫 Modo sin web → llamada directa a gpt-oss")
            messages = [{"role": "system", "content": sistema}, {"role": "user", "content": mensaje_usuario}]
            debe_buscar = False
            cambio_de_tema = False

        else:
            # ── Detectar cambio de tema ANTES de decidir búsqueda ────
            cambio_de_tema = detectar_cambio_de_tema(mensaje_usuario, history[:-1])

            historial_para_llm = (
                [{"role": "user", "content": mensaje_usuario}]
                if cambio_de_tema
                else history[:]
            )
            if cambio_de_tema:
                print("🔄 Historial previo omitido del contexto del LLM (cambio de tema)")

            # ── Decidir búsqueda con extracción de keywords por LLM ──
            debe_buscar, query_busqueda = decidir_busqueda(mensaje_usuario, history[:-1], hay_cambio=cambio_de_tema)
            print(f"🔍 ¿Buscar en web? {debe_buscar} | Query: '{query_busqueda}'")

            contexto_web = ""
            if debe_buscar:
                print(f"🔎 Buscando: '{query_busqueda}'")
                busqueda = buscar_en_web(query_busqueda, max_results=8)
                if busqueda and len(busqueda.strip()) > 30:
                    contexto_web = busqueda
                    print(f"✅ Búsqueda con {len(busqueda)} chars")
                else:
                    print("⚠️ Sin resultados útiles de búsqueda")

            # ── Llamada al LLM con contexto web enriquecido ──
            messages = [{"role": "system", "content": sistema}]

            if contexto_web:
                mensaje_con_contexto = (
                    f"{mensaje_usuario}\n\n"
                    f"DATOS REALES OBTENIDOS DE INTERNET AHORA MISMO (úsalos como hechos verificados, "
                    f"no los atribuyas al usuario ni dudes de ellos):\n"
                    f"{contexto_web}"
                )
                if cambio_de_tema:
                    messages.append({"role": "user", "content": mensaje_con_contexto})
                else:
                    messages += history[:-1]
                    messages.append({"role": "user", "content": mensaje_con_contexto})
            else:
                messages += historial_para_llm



        # ── Debug: mostrar prompt completo antes de llamar a Ollama ──
        if app.debug:
            print("\n" + "═"*60)
            print("📋 PROMPT COMPLETO ENVIADO A OLLAMA:")
            print("═"*60)
            for i, msg in enumerate(messages):
                rol = msg["role"].upper()
                contenido = msg["content"]
                print(f"\n[{i}] {rol}:")
                print(contenido[:2000] + ("…(recortado)" if len(contenido) > 2000 else ""))
                print("─"*60)
            print()
        print("⌛ Llamando a Ollama...")
        try:
            respuesta = client.chat_completion(model=modelo_activo, messages=messages)
        except RuntimeError as e:
            if "500" in str(e):
                print("❌ Error 500 de Ollama")
                respuesta = "Lo siento, hay un problema con el servidor de IA. Intenta de nuevo en unos momentos."
            else:
                respuesta = f"Error de conexión: {str(e)}"

        if not respuesta:
            respuesta = "Disculpa, no pude procesar tu solicitud. Intenta de nuevo."
            print("⚠️ Respuesta vacía de Ollama")

        print(f"✅ Respuesta recibida ({len(respuesta)} chars)")

        history.append({"role": "assistant", "content": respuesta})
        session["history"] = history
        session.modified = True

        return jsonify({
            "respuesta": respuesta,
            "backend": f"Orik + {modelo_activo}" + (" + DuckDuckGo" if busqueda_permitida else ""),
            "busqueda_web": debe_buscar,
            "cambio_de_tema": cambio_de_tema,
        })

    except Exception as e:
        print(f"❌ Error en /chat: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Error del servidor: {str(e)}"}), 500


# ── Rutas auxiliares ──────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/memoria", methods=["GET"])
def ver_memoria():
    return jsonify(cargar_memoria())

@app.route("/memoria/borrar", methods=["POST"])
def borrar_memoria():
    guardar_memoria({})
    return jsonify({"ok": True})


if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        ensure_ollama_running()

    print(f"🚀 Servidor corriendo - Modelo: {OLLAMA_MODEL}")
    print(f"⚡ Modelo rápido para keywords: {OLLAMA_MODEL_FAST}")
    print("🌐 Búsqueda web en paralelo activada")
    app.run(host="0.0.0.0", port=5000, debug=True)
