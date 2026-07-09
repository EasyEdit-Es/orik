# 🤖 Orik — Asistente IA Local

Orik es un asistente de IA que corre completamente en tu máquina, sin depender de servicios externos ni suscripciones. Tus conversaciones nunca salen de tu ordenador.

---

## ✨ Características

- 🔒 **100% local** — sin APIs externas, sin suscripciones, sin coste por uso
- 🌐 **Búsqueda web en tiempo real** — integración con DuckDuckGo, Wikipedia y Yahoo Finance
- ⚡ **Respuesta en streaming** — los tokens aparecen en tiempo real, sin esperas en blanco
- 🧠 **Dos modelos de IA** — uno rápido para búsquedas y otro más potente para conversación profunda
- 🔄 **Detección automática de cambio de tema** para respuestas más precisas
- 💾 **Cache de búsquedas** — evita repetir las mismas consultas
- 🎨 **Interfaz web limpia** — accesible desde cualquier navegador en tu red local
- 🖥️ **Launcher con interfaz gráfica** — panel de control con logs, estadísticas y configuración
- 🔐 **Autenticación opcional** — bloquea el acceso con un token Bearer si expones el servicio en tu LAN

---

## 📋 Requisitos

| Componente | Mínimo recomendado |
|---|---|
| RAM | 16 GB (recomendado 32 GB) |
| Almacenamiento | 30 GB libres |
| Sistema operativo | Windows 10/11, macOS, Linux |
| Python | 3.10 o superior |

> ⚠️ Sin GPU el modelo tarda más en responder. Con GPU compatible con CUDA la experiencia mejora notablemente.

---

## 🚀 Instalación paso a paso

### 1. Instala Ollama

Descarga e instala Ollama desde su web oficial: <https://ollama.com/download>

Verifica que funciona:

```bash
ollama --version
```

### 2. Descarga los modelos de IA

Elige los modelos que quieres usar. Por defecto Orik espera:

```bash
ollama pull gemma3n:e2b    # rápido para clasificación y búsqueda (~2 GB)
ollama pull gpt-oss:20b    # modelo potente para conversación sin web (~13 GB)
```

> Puedes cambiar los modelos en `.env` — cualquier modelo que aparezca en `ollama list` sirve.

### 3. Clona el repositorio

```bash
git clone https://github.com/jrxvex/orik.git
cd orik
```

### 4. Instala las dependencias

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install -r requirements.txt
```

### 5. Configura las variables de entorno (opcional)

Copia el archivo de ejemplo y ajústalo:

```bash
cp .env.example .env
```

Todo lo importante está documentado dentro. Si no editas nada, Orik usa valores razonables por defecto.

### 6. Arranca Orik

**Desarrollo:**

```bash
python app.py
```

**Con el launcher gráfico:**

```bash
python orik_launcher.py
```

**Producción (recomendado si lo expones a tu red):**

```bash
gunicorn -w 1 -k gthread --threads 4 --timeout 300 -b 0.0.0.0:5000 wsgi:application
```

### 7. Abre Orik en el navegador

```
http://localhost:5000
```

O desde otro dispositivo en tu red (si arrancaste con `FLASK_HOST=0.0.0.0`):

```
http://<tu-ip>:5000
```

¡Listo! Ya puedes hablar con Orik.

---

## 🎛️ Uso

### Toggle de búsqueda web 🌐

En la barra de escritura verás un botón con el icono 🌐.

- **Activado (azul)** → Orik busca en internet antes de responder. Ideal para actualidad, noticias, precios, deportes.
- **Desactivado (gris)** → Orik usa el modelo más potente (`gpt-oss:20b`) para razonar sin búsqueda. Ideal para conversaciones, análisis, redacción, código.

### Nueva conversación

Debajo del cuadro de texto tienes un enlace **Nueva conversación** que borra el contexto y empieza de cero. Útil cuando cambias de tema.

---

## ⚙️ Configuración

Todas las opciones se controlan por variables de entorno (o el archivo `.env`). Ver `.env.example` para la lista completa. Las más importantes:

| Variable | Por defecto | Descripción |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Dónde escucha Ollama |
| `OLLAMA_MODEL` | `gemma3n:e2b` | Modelo rápido (con búsqueda web) |
| `OLLAMA_MODEL_SMART` | `gpt-oss:20b` | Modelo potente (sin búsqueda) |
| `OLLAMA_MODEL_FAST` | `gemma3n:e2b` | Modelo para clasificación de temas |
| `FLASK_HOST` | `127.0.0.1` | Cambia a `0.0.0.0` para exponerlo a la LAN |
| `FLASK_PORT` | `5000` | Puerto de Flask |
| `FLASK_DEBUG` | `false` | **Nunca lo actives en producción** |
| `ORIK_API_TOKEN` | (vacío) | Si lo defines, el endpoint `/chat` exige `Authorization: Bearer <token>` |
| `HISTORY_MAX_TURNS` | `30` | Turnos de historial por sesión |
| `SEARCH_CACHE_TTL` | `600` | Segundos que se cachean los resultados de búsqueda |

También puedes editar `orik_config.json` desde la pestaña **Configuración** del launcher (afecta solo al launcher, no al servidor Flask).

---

## 🛠️ Solución de problemas

**Error conectando con Ollama**
Asegúrate de que Ollama está corriendo:
```bash
ollama serve
```

**La respuesta tarda mucho**
Es normal la primera vez que se carga un modelo. Considera usar un modelo más ligero si sólo tienes CPU. Los tiempos posteriores mejoran cuando el modelo queda en caché.

**ModuleNotFoundError**
Comprueba que el entorno virtual está activo y ejecuta de nuevo `pip install -r requirements.txt`.

**El chat responde con "No tengo acceso a información en tiempo real"**
El modelo puede estar ignorando el bloque de búsqueda. Comprueba en los logs que aparece `Contexto web N chars`. Si no, ajusta `OLLAMA_MODEL` a uno mejor (por ejemplo `llama3.1:8b`).

**`pyinstaller` no se reconoce en PowerShell**
```powershell
python -m pip install pyinstaller
python -m PyInstaller orik_launcher.py --onefile --noconsole
```

---

## 📁 Estructura del proyecto

```
orik/
├── app.py                  # Entrypoint de desarrollo
├── wsgi.py                 # Entrypoint para gunicorn / uwsgi
├── orik/
│   ├── __init__.py
│   ├── app.py              # Factoría Flask
│   ├── config.py           # Config y variables de entorno
│   ├── logging_setup.py    # Logging con formato legible
│   ├── memoria.py          # Memoria persistente (escritura atómica)
│   ├── nlp.py              # Extracción de keywords, clasificación
│   ├── ollama_client.py    # Cliente HTTP + gestión del proceso Ollama
│   ├── routes.py           # Rutas HTTP (/chat, /memoria, /healthz…)
│   ├── search.py           # Búsqueda web en paralelo con cache TTL
│   ├── session_store.py    # Historial de conversación en disco
│   └── topic_detect.py     # Detección de cambio de tema con LLM
├── templates/
│   └── index.html          # Interfaz web
├── tests/                  # Suite pytest
├── orik_launcher.py        # Panel de control Tkinter
├── orik_config.json        # Config del launcher
├── memoria.json            # Memoria persistente del asistente
├── requirements.txt        # Dependencias runtime
├── requirements-dev.txt    # Dependencias desarrollo (tests, lint)
├── pyproject.toml          # Config de pytest / ruff / coverage
├── .env.example            # Plantilla de variables de entorno
└── .github/workflows/ci.yml
```

---

## 🧪 Desarrollo

Instala las dependencias de desarrollo:

```bash
pip install -r requirements-dev.txt
```

Ejecuta los tests:

```bash
pytest
```

Comprueba el estilo:

```bash
ruff check .
```

Todo se ejecuta también en GitHub Actions en cada push.

---

## 🌐 Endpoints HTTP

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Interfaz web del chat |
| `GET` | `/healthz` | Ping; devuelve estado de Ollama |
| `POST` | `/chat` | Enviar mensaje. Body: `{"mensaje": str, "busqueda_web": bool, "stream": bool}` |
| `GET` | `/memoria` | Ver memoria persistente |
| `POST` | `/memoria/borrar` | Limpiar la memoria |
| `POST` | `/historial/borrar` | Empezar una conversación nueva |

Cuando `stream: true` (por defecto) `/chat` devuelve `text/event-stream` con eventos JSON:

```
data: {"meta": {"backend": "…", "busqueda_web": true, "model": "gemma3n:e2b"}}
data: {"token": "Hola"}
data: {"token": ", ¿en qué puedo ayudarte?"}
data: {"done": true}
```

---

## ⚖️ Licencia

© 2025 Orik — Todos los derechos reservados.

Se permite la descarga, instalación y uso de este software, incluido su uso con fines comerciales.

No está permitida la modificación, redistribución, sublicencia, venta ni creación de obras derivadas sin autorización expresa y por escrito del autor.

Se recomienda descargar el software únicamente desde la fuente oficial para garantizar su integridad y seguridad. El autor no se hace responsable de versiones modificadas o distribuidas por terceros.
