"""Tests para la limpieza de mensajes y la extracción de queries."""

from __future__ import annotations

import pytest

from orik import nlp


class TestLimpiarMensaje:
    def test_elimina_relleno_simple(self):
        assert nlp.limpiar_mensaje("por favor dime qué es Python") == "Python"

    def test_elimina_puntuacion(self):
        assert "?" not in nlp.limpiar_mensaje("¿qué es Python?")

    def test_conserva_contenido_util(self):
        limpio = nlp.limpiar_mensaje("me busques el filtro de aire de skoda octavia")
        assert "skoda" in limpio.lower()
        assert "octavia" in limpio.lower()

    def test_mensaje_vacio(self):
        assert nlp.limpiar_mensaje("") == ""

    def test_solo_puntuacion(self):
        assert nlp.limpiar_mensaje("¿???!!!") == ""


class TestReferenciaVaga:
    @pytest.mark.parametrize("msg", [
        "y quién metió el gol",
        "dime las estadísticas",
        "más info",
        "y el resultado",
        "qué pasó",
    ])
    def test_detecta_referencias_vagas(self, msg):
        assert nlp.es_referencia_vaga(msg.lower())

    def test_mensaje_largo_no_es_vago(self):
        msg = "explícame en detalle cómo funciona la fotosíntesis en las plantas".lower()
        assert not nlp.es_referencia_vaga(msg)


class TestConstruirQuery:
    def test_query_sin_historial(self):
        q = nlp.construir_query("¿qué es la fotosíntesis?")
        assert "fotosíntesis" in q.lower() or "fotosintesis" in q.lower()

    def test_referencia_vaga_resuelve_desde_historial(self):
        historial = [
            {"role": "user", "content": "cómo va el atlético"},
            {"role": "assistant", "content": "va bien"},
        ]
        q = nlp.construir_query("y el resultado", historial)
        assert "atlético" in q.lower() or "atletico" in q.lower()

    def test_cambio_de_tema_ignora_historial(self):
        historial = [
            {"role": "user", "content": "cómo va el atlético"},
        ]
        q = nlp.construir_query("¿cuál es la capital de Francia?", historial, hay_cambio=True)
        assert "atlético" not in q.lower() and "atletico" not in q.lower()

    def test_recorta_a_max_8_palabras(self):
        larga = " ".join(["palabra"] * 20)
        q = nlp.construir_query(larga)
        assert len(q.split()) <= 8

    def test_anade_anio_si_pregunta_actual(self):
        q = nlp.construir_query("¿cuál es el último iPhone?", anio=2026)
        assert "2026" in q


class TestDecidirBusqueda:
    @pytest.mark.parametrize("saludo", ["hola", "buenos días", "gracias", "ok"])
    def test_saludos_no_buscan(self, saludo):
        buscar, _ = nlp.decidir_busqueda(saludo)
        assert buscar is False

    @pytest.mark.parametrize("op", ["cuánto es 2+2", "calcula la derivada", "resuelve x=5"])
    def test_operaciones_matematicas_no_buscan(self, op):
        buscar, _ = nlp.decidir_busqueda(op)
        assert buscar is False

    def test_pregunta_real_busca(self):
        buscar, query = nlp.decidir_busqueda("¿cuál es el resultado del real madrid ayer?")
        assert buscar is True
        assert query


class TestIntent:
    @pytest.mark.parametrize("msg,expected", [
        ("quién metió gol", "goleadores"),
        ("dame las estadísticas", "estadísticas"),
        ("cuál fue el resultado", "resultado"),
        ("cuántas tarjetas amarillas", "tarjetas"),
        ("cuál es el clima hoy", ""),
    ])
    def test_intent(self, msg, expected):
        assert nlp.intent_del_mensaje(msg) == expected
