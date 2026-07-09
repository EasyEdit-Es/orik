"""Tests de integración de las rutas Flask."""

from __future__ import annotations

import json

import pytest

from orik import config, search
from orik.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(config, "MEMORIA_FILE", tmp_path / "memoria.json")
    search.clear_cache()
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_healthz(client, monkeypatch):
    monkeypatch.setattr("orik.ollama_client.is_ollama_running", lambda *_: True)
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"


def test_chat_rechaza_mensaje_vacio(client):
    r = client.post("/chat", json={"mensaje": ""})
    assert r.status_code == 400


def test_chat_rechaza_mensaje_gigante(client):
    r = client.post("/chat", json={"mensaje": "x" * 10_000})
    assert r.status_code == 413


def test_chat_devuelve_json_cuando_no_hay_stream(client, monkeypatch):
    monkeypatch.setattr(
        "orik.routes.chat_completion",
        lambda **kw: "respuesta de prueba",
    )
    monkeypatch.setattr(
        "orik.routes.topic_detect.detectar_cambio_de_tema",
        lambda *a, **k: False,
    )
    monkeypatch.setattr("orik.routes.search.buscar_en_web", lambda *a, **k: "")

    r = client.post("/chat", json={"mensaje": "hola", "stream": False, "busqueda_web": False})
    assert r.status_code == 200
    body = r.get_json()
    assert body["respuesta"] == "respuesta de prueba"


def test_chat_streaming(client, monkeypatch):
    monkeypatch.setattr(
        "orik.routes.chat_stream",
        lambda **kw: iter(["hola", " mundo"]),
    )
    monkeypatch.setattr(
        "orik.routes.topic_detect.detectar_cambio_de_tema",
        lambda *a, **k: False,
    )
    monkeypatch.setattr("orik.routes.search.buscar_en_web", lambda *a, **k: "")

    r = client.post(
        "/chat",
        json={"mensaje": "hola", "stream": True, "busqueda_web": False},
    )
    assert r.status_code == 200
    assert r.mimetype == "text/event-stream"

    body = r.get_data(as_text=True)
    # Debe haber varios eventos SSE
    eventos = [
        json.loads(line[6:])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    tokens = [e["token"] for e in eventos if "token" in e]
    assert "".join(tokens) == "hola mundo"
    assert any(e.get("done") for e in eventos)


def test_ver_memoria(client):
    r = client.get("/memoria")
    assert r.status_code == 200
    assert r.get_json() == {}


def test_borrar_memoria(client, tmp_path):
    from orik import memoria
    memoria.guardar_memoria({"k": "v"})
    r = client.post("/memoria/borrar")
    assert r.status_code == 200
    assert memoria.cargar_memoria() == {}


def test_auth_token(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "API_TOKEN", "secreto123")

    r = client.post("/chat", json={"mensaje": "hola"})
    assert r.status_code == 401

    r = client.post(
        "/chat",
        json={"mensaje": "hola", "stream": False, "busqueda_web": False},
        headers={"Authorization": "Bearer secreto123"},
    )
    # Sin monkeypatch de chat_completion fallará conectando a Ollama;
    # nos basta con que NO sea 401
    assert r.status_code != 401
