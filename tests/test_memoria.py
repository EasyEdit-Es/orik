"""Tests para la persistencia de memoria."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orik import config, memoria


@pytest.fixture
def tmp_memoria(tmp_path: Path, monkeypatch):
    fake = tmp_path / "memoria.json"
    monkeypatch.setattr(config, "MEMORIA_FILE", fake)
    return fake


def test_cargar_memoria_inexistente(tmp_memoria):
    assert memoria.cargar_memoria() == {}


def test_guardar_y_cargar(tmp_memoria):
    memoria.guardar_memoria({"ciudad": "Madrid", "idioma": "español"})
    assert memoria.cargar_memoria() == {"ciudad": "Madrid", "idioma": "español"}


def test_escritura_atomica(tmp_memoria):
    memoria.guardar_memoria({"k": "v"})
    # Verificar que no quedan archivos temporales huérfanos
    tmps = list(tmp_memoria.parent.glob(".memoria.*"))
    assert tmps == []


def test_valores_no_string_se_coercionan(tmp_memoria):
    memoria.guardar_memoria({"n": 42, "b": True})  # type: ignore[dict-item]
    data = json.loads(tmp_memoria.read_text(encoding="utf-8"))
    assert data == {"n": "42", "b": "True"}


def test_json_corrupto_devuelve_vacio(tmp_memoria):
    tmp_memoria.write_text("no soy json", encoding="utf-8")
    assert memoria.cargar_memoria() == {}


def test_memoria_a_texto_vacio():
    assert memoria.memoria_a_texto({}) == ""


def test_memoria_a_texto_con_datos():
    txt = memoria.memoria_a_texto({"ciudad": "Madrid"})
    assert "Madrid" in txt
    assert "ciudad" in txt


def test_valor_muy_largo_se_recorta(tmp_memoria):
    memoria.guardar_memoria({"k": "x" * 10000})
    cargado = memoria.cargar_memoria()
    assert len(cargado["k"]) <= 500
