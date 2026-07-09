"""Cliente HTTP para Ollama y gestión del servidor local."""

from __future__ import annotations

import json
import os
import shlex
import signal
import socket
import subprocess
import time
from collections.abc import Iterator
from urllib.parse import urlparse

import requests

from . import config
from .logging_setup import get_logger

log = get_logger(__name__)


class OllamaError(RuntimeError):
    """Fallo al hablar con el backend Ollama."""


def is_ollama_running(host: str = config.OLLAMA_HOST) -> bool:
    for endpoint in ("/api/tags", "/api/models", "/"):
        try:
            resp = requests.get(f"{host}{endpoint}", timeout=5)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            continue
    return False


def _is_port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


def start_ollama_server() -> subprocess.Popen | None:
    """Arrancar Ollama si no está corriendo. Devuelve el proceso o None."""
    if is_ollama_running():
        return None

    parsed = urlparse(config.OLLAMA_HOST)
    host_netloc = parsed.hostname or parsed.path
    port = parsed.port or 11434

    if _is_port_in_use(host_netloc, port):
        log.warning("Puerto %s en uso. Esperando a que Ollama responda…", port)
        deadline = time.time() + 10
        while time.time() < deadline:
            if is_ollama_running():
                log.info("Ollama respondió. Usando instancia existente.")
                return None
            time.sleep(1)
        raise OllamaError(
            f"Puerto {port} ocupado pero Ollama no responde."
        )

    if not any(h in config.OLLAMA_HOST for h in ("localhost", "127.0.0.1")):
        raise OllamaError(
            "OLLAMA_HOST no apunta a localhost; no puedo arrancarlo aquí."
        )

    try:
        args = shlex.split(config.OLLAMA_START_COMMAND, posix=os.name != "nt")
    except ValueError:
        args = config.OLLAMA_START_COMMAND.split()

    log.info("Arrancando Ollama: %s", config.OLLAMA_START_COMMAND)
    try:
        proc = subprocess.Popen(args)
    except FileNotFoundError as exc:
        raise OllamaError(
            f"No se encontró el ejecutable de Ollama ({args[0]!r}). Instálalo desde https://ollama.com/download"
        ) from exc

    deadline = time.time() + config.OLLAMA_START_TIMEOUT
    while time.time() < deadline:
        if is_ollama_running():
            log.info("Ollama listo.")
            return proc
        time.sleep(1)

    proc.terminate()
    raise OllamaError(
        f"No se pudo iniciar Ollama en {config.OLLAMA_START_TIMEOUT}s."
    )


def ensure_ollama_running() -> None:
    if is_ollama_running():
        log.info("Ollama ya estaba en ejecución.")
        return
    try:
        start_ollama_server()
    except OllamaError as exc:
        log.warning("No se pudo iniciar Ollama automáticamente: %s", exc)
        log.warning("Continuando; las peticiones fallarán hasta que arranques Ollama.")
    except Exception as exc:  # noqa: BLE001 — no queremos abortar el arranque
        log.warning("Fallo inesperado arrancando Ollama: %s", exc)


def chat_completion(
    model: str,
    messages: list[dict],
    *,
    max_tokens: int = config.OLLAMA_MAX_TOKENS,
    temperature: float = config.OLLAMA_TEMPERATURE,
    timeout: int = config.OLLAMA_REQUEST_TIMEOUT,
) -> str:
    """Llamada bloqueante que devuelve la respuesta completa."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": temperature},
    }
    try:
        resp = requests.post(
            f"{config.OLLAMA_HOST}/api/chat", json=payload, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "") or ""
    except requests.RequestException as exc:
        raise OllamaError(f"Error conectando con Ollama: {exc}") from exc


def chat_stream(
    model: str,
    messages: list[dict],
    *,
    max_tokens: int = config.OLLAMA_MAX_TOKENS,
    temperature: float = config.OLLAMA_TEMPERATURE,
    timeout: int = config.OLLAMA_REQUEST_TIMEOUT,
) -> Iterator[str]:
    """Streaming token-a-token. Yields fragmentos de texto (no eventos SSE)."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"num_predict": max_tokens, "temperature": temperature},
    }
    try:
        with requests.post(
            f"{config.OLLAMA_HOST}/api/chat",
            json=payload,
            timeout=timeout,
            stream=True,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
                if chunk.get("done"):
                    return
    except requests.RequestException as exc:
        raise OllamaError(f"Error en streaming con Ollama: {exc}") from exc


# ── Utilidades para limpieza de procesos (usadas por el launcher) ──

def get_pids_by_port(port: int) -> list[int]:
    pids: list[int] = []
    if os.name == "nt":
        try:
            output = subprocess.check_output(
                ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            return []
        import re
        for line in output.splitlines():
            if not line.strip().startswith("TCP"):
                continue
            parts = re.split(r"\s+", line.strip())
            if len(parts) < 5:
                continue
            if parts[1].endswith(f":{port}"):
                try:
                    pids.append(int(parts[4]))
                except ValueError:
                    continue
    else:
        try:
            output = subprocess.check_output(
                ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in output.strip().splitlines():
                try:
                    pids.append(int(line.strip()))
                except ValueError:
                    continue
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []
    return sorted(set(pids))


def kill_process(pid: int) -> None:
    if pid == os.getpid():
        raise RuntimeError("El proceso actual no puede cerrarse a sí mismo.")
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
