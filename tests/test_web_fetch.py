"""Tests para la extracción de contenido de páginas web."""

from __future__ import annotations

from orik import web_fetch

HTML_SIMPLE = """
<html>
<head><title>Título de prueba</title></head>
<body>
  <nav>menú superior</nav>
  <script>alert('x')</script>
  <article>
    <h1>Encabezado del artículo</h1>
    <p>Este es un párrafo importante con contenido útil sobre el tema.</p>
    <p>Otro párrafo con más información relevante que el modelo debería leer.</p>
  </article>
  <footer>© 2026</footer>
</body>
</html>
"""

HTML_SIN_ARTICLE = """
<html><head><title>T</title></head><body>
  <div class="menu">navegación</div>
  <div class="cookie-banner">acepta cookies</div>
  <div class="content">
    <p>Este es el contenido principal del post con muchísimo texto útil aquí dentro
    para que el algoritmo de densidad lo prefiera sobre los otros divs.</p>
    <p>Segundo párrafo con más contexto y datos útiles para el usuario final.</p>
  </div>
  <div class="sidebar">enlaces relacionados</div>
</body></html>
"""


def test_extract_main_text_basico():
    texto = web_fetch.extract_main_text(HTML_SIMPLE)
    assert "párrafo importante" in texto
    assert "menú superior" not in texto
    assert "alert" not in texto
    assert "© 2026" not in texto


def test_extract_main_text_titulo_al_principio():
    texto = web_fetch.extract_main_text(HTML_SIMPLE)
    assert texto.startswith("Título de prueba") or "Título de prueba" in texto[:200]


def test_extract_main_text_sin_article():
    """Sin <article> ni <main>, debe caer en el bloque más denso."""
    texto = web_fetch.extract_main_text(HTML_SIN_ARTICLE)
    assert "contenido principal" in texto
    assert "acepta cookies" not in texto
    assert "enlaces relacionados" not in texto


def test_extract_main_text_recorta_por_max_chars():
    texto = web_fetch.extract_main_text(HTML_SIMPLE, max_chars=50)
    assert len(texto) <= 100  # margen para el "[…]" y ajuste al último punto


def test_extract_main_text_html_vacio():
    assert web_fetch.extract_main_text("") == ""


def test_is_blocked_domain():
    assert web_fetch.is_blocked_domain("https://twitter.com/user")
    assert web_fetch.is_blocked_domain("https://www.youtube.com/watch?v=x")
    assert web_fetch.is_blocked_domain("https://x.com/foo")
    assert not web_fetch.is_blocked_domain("https://es.wikipedia.org/wiki/Python")
    assert not web_fetch.is_blocked_domain("https://elpais.com/")


def test_fallback_extract_sin_bs4():
    """El fallback regex funciona aunque bs4 no esté."""
    salida = web_fetch._fallback_extract(HTML_SIMPLE, max_chars=1000)
    assert "párrafo importante" in salida
    assert "<p>" not in salida
    assert "alert" not in salida
