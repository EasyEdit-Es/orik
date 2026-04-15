# 🤖 Orik — Asistente IA Local

Orik es un asistente de inteligencia artificial que corre completamente en tu máquina, sin depender de servicios externos ni suscripciones. Tus conversaciones nunca salen de tu ordenador.

---

## ✨ Características

- 🔒 **100% local** — sin APIs externas, sin suscripciones, sin coste por uso
- 🌐 **Búsqueda web en tiempo real** — integración con DuckDuckGo y Wikipedia
- 🧠 **Dos modelos de IA** — uno rápido para búsquedas y otro más potente para conversación profunda
- 🔄 **Detección de cambio de tema automática** para respuestas más precisas
- 🎨 **Interfaz web limpia** — accesible desde cualquier navegador en tu red local
- 🖥️ **Panel de control** — lanza, detiene y monitoriza el servidor desde una interfaz gráfica

---

## 📋 Requisitos

| Componente | Mínimo recomendado |
|---|---|
| RAM | 16 GB (recomendado 32 GB) |
| Almacenamiento | 30 GB libres |
| Sistema operativo | Windows 10/11 |

> ⚠️ Sin GPU el modelo tardará más en responder. Con GPU compatible con CUDA la experiencia mejora notablemente.

---

## 🚀 Instalación paso a paso

### 1. Instala Ollama

Descarga e instala Ollama desde su web oficial:

👉 https://ollama.com/download

Una vez instalado, verifica que funciona abriendo PowerShell y ejecutando:

```
ollama --version
```

### 2. Descarga los modelos de IA

Abre PowerShell y ejecuta estos dos comandos. El primero descarga el modelo rápido (~7 GB) y el segundo el modelo inteligente (~13 GB):

```
ollama pull gemma4:e2b
ollama pull gpt-oss:20b
```

> ⏳ Dependiendo de tu conexión puede tardar unos minutos.

### 3. Descarga y ejecuta Orik

Descarga el archivo `Orik_launcher.exe` desde la sección [Releases](../../releases) de este repositorio y ejecútalo. No necesitas instalar Python ni ninguna dependencia adicional.

Se abrirá el panel de control de Orik.

### 4. Inicia el servidor

Pulsa el botón **Iniciar** en el panel. Cuando el indicador se ponga en verde y veas esto en los logs, el servidor está listo:

```
✅ Ollama ya estaba en ejecución.
🚀 Servidor corriendo - Modelo: gemma4:e2b
🌐 Búsqueda web en paralelo activada
```

### 5. Abre Orik en el navegador

Ve a tu navegador y entra en:

```
http://localhost:5000
```

O desde otro dispositivo en tu red local:

```
http://<tu-ip>:5000
```

¡Listo! Ya puedes hablar con Orik.

---

## 🎛️ Uso

### Toggle de búsqueda web 🌐

En la barra de escritura verás un botón con el icono 🌐.

- **Activado (azul)** → Orik busca en internet antes de responder. Ideal para preguntas sobre actualidad, noticias, precios, etc.
- **Desactivado (gris)** → Orik usa el modelo más potente (`gpt-oss:20b`) para razonar sin búsqueda. Ideal para conversaciones, análisis, redacción, código, etc.

---

## ⚙️ Configuración

Desde la pestaña **Configuración** del panel puedes ajustar el tema (claro/oscuro), el puerto, el tamaño de fuente de los logs y otras opciones. Los cambios se guardan automáticamente en `orik_config.json`.

---

## 🛠️ Solución de problemas

**Error conectando con Ollama**
Asegúrate de que Ollama está corriendo. Puedes iniciarlo manualmente abriendo PowerShell y ejecutando:
```
ollama serve
```

**La respuesta tarda mucho**
Es normal la primera vez que se carga un modelo. Si tienes solo CPU y el modelo es grande, puede tardar varios minutos. Considera usar un modelo más ligero.

**El servidor se cae inesperadamente**
El panel te avisará con una notificación. Revisa los logs para ver el error y pulsa **Iniciar** de nuevo.

---

## ⚖️ Licencia

© 2025 Orik — Todos los derechos reservados.

Se permite la descarga, instalación y uso de este software, incluido su uso con fines comerciales.

No está permitida la modificación, redistribución, sublicencia, venta ni creación de obras derivadas sin autorización expresa y por escrito del autor.

Se recomienda descargar el software únicamente desde la fuente oficial para garantizar su integridad y seguridad. El autor no se hace responsable de versiones modificadas o distribuidas por terceros.
