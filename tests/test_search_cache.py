"""Tests para el cache y la orquestación de búsqueda web."""

from __future__ import annotations

import pytest

from orik import config, search
from orik.search import SearchHit


@pytest.fixture(autouse=True)
def limpiar_cache():
    search.clear_cache()
    yield
    search.clear_cache()


def _fake_fuente(nombre: str, url: str, snippet: str = "res"):
    def _fn(_q, _n):
        return [SearchHit(title=nombre, url=url, snippet=snippet, source=nombre)]
    return _fn


def test_cache_hit(monkeypatch):
    llamadas = {"n": 0}

    def fake(_q, _n):
        llamadas["n"] += 1
        return [SearchHit(title="t", url="https://a.example/1", snippet="s", source="X")]

    monkeypatch.setattr(search, "_FUENTES", {"ddgs": fake})
    monkeypatch.setattr(search, "_enriquecer_con_contenido", lambda *a, **k: None)

    r1 = search.buscar_en_web("python")
    r2 = search.buscar_en_web("python")
    assert r1 == r2
    assert llamadas["n"] == 1  # segunda llamada la sirve el cache


def test_cache_ttl_expira(monkeypatch):
    llamadas = {"n": 0}

    def fake(_q, _n):
        llamadas["n"] += 1
        return [SearchHit(title=f"t{llamadas['n']}", url=f"https://a.example/{llamadas['n']}",
                          snippet="s", source="X")]

    monkeypatch.setattr(search, "_FUENTES", {"ddgs": fake})
    monkeypatch.setattr(search, "_enriquecer_con_contenido", lambda *a, **k: None)
    monkeypatch.setattr(config, "SEARCH_CACHE_TTL", 0)

    search.buscar_en_web("python")
    search.buscar_en_web("python")
    assert llamadas["n"] == 2


def test_query_vacia_devuelve_vacio():
    assert search.buscar_en_web("") == ""
    assert search.buscar_en_web("   ") == ""


def test_todas_las_fuentes_fallan(monkeypatch):
    monkeypatch.setattr(search, "_FUENTES", {"ddgs": lambda _q, _n: []})
    monkeypatch.setattr(search, "_enriquecer_con_contenido", lambda *a, **k: None)
    assert search.buscar_en_web("nada") == ""


def test_dedupe_por_dominio_mantiene_uno_por_host():
    hits = [
        SearchHit(title="A", url="https://foo.com/1", snippet="", source="X"),
        SearchHit(title="A2", url="https://foo.com/2", snippet="", source="X"),
        SearchHit(title="B", url="https://bar.com/1", snippet="", source="X"),
    ]
    filtrados = search._dedupe_por_dominio(hits, max_por_dominio=1)
    dominios = [h.domain for h in filtrados]
    assert dominios == ["foo.com", "bar.com"]


def test_pregunta_de_noticias():
    assert search.es_pregunta_de_noticias("últimas noticias del gobierno")
    assert search.es_pregunta_de_noticias("resultado del partido hoy")
    assert not search.es_pregunta_de_noticias("qué es la fotosíntesis")


def test_orden_final_prioriza_noticias(monkeypatch):
    """Cuando hay noticias y web, las noticias van primero en el output."""
    def fake_web(_q, _n):
        return [SearchHit(title="Web result", url="https://web.example/",
                          snippet="s", source="Web")]

    def fake_news(_q, _n):
        return [SearchHit(title="News result", url="https://news.example/",
                          snippet="s", source="News", published="2026-07-09")]

    monkeypatch.setattr(search, "_FUENTES", {"ddgs": fake_web})
    monkeypatch.setattr(search, "_buscar_ddgs_news", fake_news)
    monkeypatch.setattr(search, "es_pregunta_de_noticias", lambda _q: True)
    monkeypatch.setattr(search, "_enriquecer_con_contenido", lambda *a, **k: None)

    salida = search.buscar_en_web("noticias hoy")
    # La noticia aparece antes que el resultado web
    assert salida.index("News result") < salida.index("Web result")


def test_hit_extrae_dominio_correctamente():
    h = SearchHit(title="x", url="https://www.example.com/path?q=1",
                  snippet="", source="X")
    assert h.domain == "example.com"
