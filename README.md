# 🤖 Orik — Asistente IA Local

**Orik** es un asistente de inteligencia artificial que corre completamente en tu máquina, sin depender de servicios externos ni suscripciones. Tus conversaciones nunca salen de tu ordenador.

---

## ✨ Características

- 🔒 **100% local** — sin APIs externas, sin suscripciones, sin coste por uso
- 🌐 **Búsqueda web en tiempo real** — integración con DuckDuckGo y Wikipedia
- 🧠 **Dos modelos de IA** — uno rápido para búsquedas y otro más potente para conversación profunda
- 🔄 **Detección de cambio de tema** automática para respuestas más precisas
- 🎨 **Interfaz web limpia** — accesible desde cualquier navegador en tu red local

---

## 📋 Requisitos

| Componente | Mínimo recomendado |
|---|---|
| RAM | 16 GB (recomendado 32 GB) |
| Almacenamiento | 30 GB libres |
| Sistema operativo | Windows 10/11, macOS, Linux |
| Python | 3.10 o superior |

> ⚠️ Sin GPU el modelo tardará más en responder. Con GPU compatible con CUDA la experiencia mejora notablemente.

---

## 🚀 Instalación paso a paso

### 1. Instala Ollama

Descarga e instala Ollama desde su web oficial:

👉 [https://ollama.com/download](https://ollama.com/download)

Una vez instalado, verifica que funciona abriendo una terminal y ejecutando:

```bash
ollama --version
```

---

### 2. Descarga los modelos de IA

Abre una terminal en powershell (como admin es opcional) y ejecuta estos dos comandos. El primero descarga el modelo rápido (~7 GB) y el segundo el modelo inteligente (~13 GB):

```bash
ollama pull gemma4:e2b
ollama pull gpt-oss:20b
```

> ⏳ Dependiendo de tu conexión puede tardar unos minutos.

---

### 3. Descarga Orik

Clona el repositorio o descarga el ZIP desde el botón verde de GitHub:

```bash
git clone https://github.com/tu-usuario/orik.git
cd orik
```

---

### 4. Instala las dependencias de Python

Asegúrate de tener Python 3.10+ instalado. Luego ejecuta:

```bash
pip install -r requirements.txt
```
Si no te funciona prueba con:
```bash
python3 -m pip install -r requirements.txt
```
O:
```bash
py -m pip install -r requirements.txt
```

---

### 5. Inicia el servidor

```bash
python app2test.py
```

Deberías ver algo así en la terminal:

```
✅ Ollama ya estaba en ejecución.
🚀 Servidor corriendo - Modelo: gemma4:e2b
⚡ Modelo rápido para keywords: gemma4:e2b
🌐 Búsqueda web en paralelo activada
```

---

### 6. Abre Orik en el navegador

Ve a tu navegador y entra en:

```
http://localhost:5000
```
O tu y ip del ordenador:
```bash
http://tuip:5000
```

¡Listo! Ya puedes hablar con Orik.

---

## 🎛️ Uso

### Toggle de búsqueda web 🌐
En la barra de escritura verás un botón con el icono 🌐.

- **Activado (azul)** → Orik busca en internet antes de responder. Ideal para preguntas sobre actualidad, noticias, precios, etc.
- **Desactivado (gris)** → Orik usa el modelo más potente (`gpt-oss:20b`) para razonar sin búsqueda. Ideal para conversaciones, análisis, redacción, código, etc.

---

## ⚙️ Configuración avanzada (opcional)

Puedes crear un archivo `.env` en la carpeta del proyecto para personalizar los modelos:

```env
OLLAMA_MODEL=gemma4:e2b
OLLAMA_MODEL_SMART=gpt-oss:20b
OLLAMA_MODEL_FAST=gemma4:e2b
FLASK_SECRET_KEY=tu_clave_secreta_aqui
```

---

## 🛠️ Solución de problemas

**`Error conectando con Ollama`**
Asegúrate de que Ollama está corriendo. Puedes iniciarlo manualmente con:
```bash
ollama serve
```

**La respuesta tarda mucho**
Es normal la primera vez que se carga un modelo. Si tienes solo CPU y el modelo es grande, puede tardar varios minutos. Considera usar un modelo más ligero.

**`ModuleNotFoundError`**
Ejecuta de nuevo `pip install -r requirements.txt` y asegúrate de estar usando Python 3.10+.

---

## 📁 Estructura del proyecto

```
orik/
├── app2test.py        # Servidor principal Flask
├── wsgi.py            # Punto de entrada para despliegue en producción
├── requirements.txt   # Dependencias Python
└── templates/
    └── index.html     # Interfaz web
```
## ⚖️ Licencia
---

© 2025 Orik — Todos los derechos reservados.

Se permite la descarga, instalación y uso de este software, incluido su uso con fines comerciales.

No está permitida la modificación, redistribución, sublicencia, venta ni creación de obras derivadas sin autorización expresa y por escrito del autor.

Se recomienda descargar el software únicamente desde la fuente oficial para garantizar su integridad y seguridad. El autor no se hace responsable de versiones modificadas o distribuidas por terceros.

