"""Tests para el cache de búsqueda web."""

from __future__ import annotations

import pytest

from orik import config, search


@pytest.fixture(autouse=True)
def limpiar_cache():
    search.clear_cache()
    yield
    search.clear_cache()


def test_cache_hit(monkeypatch):
    llamadas = {"n": 0}

    def fake_ddgs(q, n):
        llamadas["n"] += 1
        return ("DDGS", f"resultados de {q}")

    monkeypatch.setattr(search, "_FUENTES", {"ddgs": lambda q, n: fake_ddgs(q, n)})

    r1 = search.buscar_en_web("python")
    r2 = search.buscar_en_web("python")
    assert r1 == r2
    assert llamadas["n"] == 1  # solo se llama una vez, la segunda va por cache


def test_cache_ttl_expira(monkeypatch):
    llamadas = {"n": 0}

    def fake_ddgs(q, n):
        llamadas["n"] += 1
        return ("DDGS", f"resultados {llamadas['n']}")

    monkeypatch.setattr(search, "_FUENTES", {"ddgs": lambda q, n: fake_ddgs(q, n)})
    monkeypatch.setattr(config, "SEARCH_CACHE_TTL", 0)  # todo expira ya

    search.buscar_en_web("python")
    search.buscar_en_web("python")
    assert llamadas["n"] == 2


def test_query_vacia_devuelve_vacio():
    assert search.buscar_en_web("") == ""
    assert search.buscar_en_web("   ") == ""


def test_todas_las_fuentes_fallan(monkeypatch):
    monkeypatch.setattr(search, "_FUENTES", {"ddgs": lambda q, n: None})
    assert search.buscar_en_web("nada") == ""
