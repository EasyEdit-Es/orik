"""Descarga páginas web y extrae contenido principal legible.

No es un readability perfecto — es una heurística "buena para LLM":
1. Descarga con User-Agent realista y timeout corto.
2. Elimina script/style/nav/footer/aside.
3. Prefiere <article> o <main>; si no hay, coge el bloque con más texto útil.
4. Colapsa espacios y recorta a un límite razonable.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

from .logging_setup import get_logger

log = get_logger(__name__)


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Dominios que rechazamos por: paywall, requieren JS pesado, o son ruido conocido
_BLOCKED_DOMAINS = frozenset({
    "twitter.com", "x.com", "facebook.com", "instagram.com",
    "linkedin.com", "reddit.com", "youtube.com", "youtu.be",
    "tiktok.com", "pinterest.com",
})

# Etiquetas HTML a descartar por completo
_STRIP_TAGS = (
    "script", "style", "noscript", "iframe", "svg", "form", "button",
    "nav", "footer", "aside", "header", "menu", "figure",
)

# Selectores por clase/id típicos de basura
_STRIP_CLASS_HINTS = (
    "cookie", "banner", "advert", "promo", "newsletter", "subscribe",
    "sidebar", "related", "comments", "share", "social", "breadcrumb",
    "menu", "navigation",
)

_WHITESPACE_RE = re.compile(r"[ \t ]+")
_NEWLINES_RE = re.compile(r"\n{3,}")


def is_blocked_domain(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return True
    return any(host == d or host.endswith("." + d) for d in _BLOCKED_DOMAINS)


def fetch_url(url: str, timeout: int = 8, max_bytes: int = 512_000) -> str | None:
    """Descarga la URL y devuelve el HTML como texto. None si falla."""
    if is_blocked_domain(url):
        return None
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
            },
            stream=True,
            allow_redirects=True,
        )
        ctype = resp.headers.get("Content-Type", "").lower()
        if "html" not in ctype and "text" not in ctype:
            return None
        # Limita el tamaño para no atragantarnos con páginas gigantes
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=16_384):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                break
        raw = b"".join(chunks)
        # Detección de encoding: usa el declarado por HTTP; si no, latin-1 seguro para bytes
        encoding = resp.encoding or "utf-8"
        try:
            return raw.decode(encoding, errors="replace")
        except LookupError:
            return raw.decode("utf-8", errors="replace")
    except requests.RequestException as exc:
        log.debug("fetch_url falló para %s: %s", url, exc)
        return None


def _has_junk_class(node) -> bool:
    """Detecta divs de menú/anuncio/etc por su class o id."""
    for attr in ("class", "id"):
        val = node.get(attr)
        if not val:
            continue
        if isinstance(val, list):
            val = " ".join(val)
        val = str(val).lower()
        if any(hint in val for hint in _STRIP_CLASS_HINTS):
            return True
    return False


def extract_main_text(html: str, max_chars: int = 3000) -> str:
    """Extrae el texto principal de un HTML. Devuelve string limpio o vacío."""
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        log.warning("beautifulsoup4 no está instalado; fallback a regex")
        return _fallback_extract(html, max_chars)

    soup = BeautifulSoup(html, "html.parser")

    # Extraer título antes de podar
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Poda ruido estructural
    for tag_name in _STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Poda nodos con clases de basura
    for node in soup.find_all(True):
        if _has_junk_class(node):
            node.decompose()

    # Preferir <article>, <main>, o el <div> con más texto útil
    candidato = soup.find("article") or soup.find("main")
    if candidato is None:
        # Buscar el bloque con más texto (heurística de densidad)
        mejor = None
        mejor_len = 0
        for div in soup.find_all(["div", "section"]):
            texto = div.get_text(" ", strip=True)
            n = len(texto)
            if n > mejor_len:
                mejor = div
                mejor_len = n
        candidato = mejor or soup.body or soup

    texto = candidato.get_text("\n", strip=True) if candidato else ""
    if title and title not in texto[:200]:
        texto = f"{title}\n\n{texto}"

    texto = _WHITESPACE_RE.sub(" ", texto)
    texto = _NEWLINES_RE.sub("\n\n", texto)
    texto = texto.strip()

    if len(texto) > max_chars:
        # Recortar en el último punto para no dejar frases a medias
        cut = texto.rfind(".", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        texto = texto[: cut + 1].strip() + " […]"

    return texto


def _fallback_extract(html: str, max_chars: int) -> str:
    """Extractor de emergencia sin BeautifulSoup: quita tags con regex."""
    # No es robusto, pero mejor que nada si bs4 no está disponible
    html = re.sub(r"<(script|style|nav|footer|aside|header)[^>]*>.*?</\1>",
                  " ", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = _WHITESPACE_RE.sub(" ", html)
    html = re.sub(r"\s{2,}", " ", html).strip()
    if len(html) > max_chars:
        html = html[:max_chars].rsplit(".", 1)[0] + "."
    return html
