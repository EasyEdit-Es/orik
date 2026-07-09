"""Búsqueda web con varias fuentes en paralelo.

Cachea resultados con TTL para no repetir las mismas queries en poco tiempo.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from . import config
from .logging_setup import get_logger

log = get_logger(__name__)


# ── Cache TTL sencilla (thread-safe) ──────────────────────────

_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str) -> str | None:
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if now - ts > config.SEARCH_CACHE_TTL:
            _cache.pop(key, None)
            return None
        return value


def _cache_put(key: str, value: str) -> None:
    with _cache_lock:
        if len(_cache) >= config.SEARCH_CACHE_SIZE:
            # Expulsar la entrada más antigua
            oldest_key = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest_key, None)
        _cache[key] = (time.time(), value)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ── Fuentes de búsqueda ───────────────────────────────────────

def _buscar_ddgs(query: str, max_results: int) -> tuple[str, str] | None:
    try:
        from ddgs import DDGS  # type: ignore
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # type: ignore
        except ImportError:
            log.warning("ddgs/duckduckgo-search no instalado")
            return None
    try:
        ddgs = DDGS(timeout=8)
        resultados = list(
            ddgs.text(query, region="es-es", safesearch="moderate", max_results=max_results)
        )
    except Exception as exc:
        log.warning("Error DDGS: %s", exc)
        return None
    if not resultados:
        return None
    lineas = ["📡 DuckDuckGo:", ""]
    for i, r in enumerate(resultados[:max_results], 1):
        titulo = r.get("title", "Sin título")
        url = r.get("href", "")
        snippet = (r.get("body") or "")[:400]
        lineas.append(f"{i}. {titulo}")
        if url:
            lineas.append(f"   Fuente: {url}")
        lineas.append(f"   {snippet}")
        lineas.append("")
    return ("DuckDuckGo (DDGS)", "\n".join(lineas).strip())


def _buscar_ddg_instant(query: str) -> tuple[str, str] | None:
    try:
        resp = requests.get(
            "https://api.duckduckgo.com",
            params={"q": query, "format": "json", "kl": "es-es", "no_html": 1, "skip_disambig": 1},
            timeout=6,
        )
    except requests.RequestException as exc:
        log.warning("Error DDG Instant: %s", exc)
        return None
    if not resp.ok:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None

    abstract = data.get("AbstractText", "")
    related = data.get("RelatedTopics", [])
    lineas: list[str] = []
    if abstract:
        lineas.append(f"💡 Resumen: {abstract}")
        lineas.append("")
    count = 0
    for t in related:
        if isinstance(t, dict) and t.get("Text"):
            lineas.append(f"- {t['Text']}")
            count += 1
            if count >= 4:
                break
    if not lineas:
        return None
    return ("DuckDuckGo Instant", "\n".join(lineas).strip())


def _buscar_wikipedia(query: str) -> tuple[str, str] | None:
    try:
        sresp = requests.get(
            "https://es.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": query,
                    "format": "json", "srlimit": 2},
            timeout=6,
        )
    except requests.RequestException as exc:
        log.warning("Error Wikipedia: %s", exc)
        return None
    if not sresp.ok:
        return None
    try:
        hits = sresp.json().get("query", {}).get("search", [])
    except ValueError:
        return None
    if not hits:
        return None

    def get_extract(hit: dict) -> str:
        pid = hit.get("pageid")
        title = hit.get("title", "")
        try:
            eres = requests.get(
                "https://es.wikipedia.org/w/api.php",
                params={"action": "query", "prop": "extracts", "explaintext": 1,
                        "pageids": pid, "format": "json", "exintro": 1},
                timeout=5,
            )
            if eres.ok:
                pages = eres.json().get("query", {}).get("pages", {})
                extract = (pages.get(str(pid), {}).get("extract") or "")[:300]
                return f"- {title}: {extract}\n"
        except requests.RequestException:
            pass
        return f"- {title}\n"

    with ThreadPoolExecutor(max_workers=2) as ex:
        extractos = list(ex.map(get_extract, hits))

    texto = "📚 Wikipedia:\n\n" + "\n".join(extractos)
    return ("Wikipedia (es)", texto.strip())


_FINANCE_KEYWORDS = (
    "barril", "petróleo", "petroleo", "crudo", "oil",
    "bitcoin", "ethereum", "crypto", "bolsa",
)


def _buscar_yahoo_finance(query: str) -> tuple[str, str] | None:
    if not any(k in query.lower() for k in _FINANCE_KEYWORDS):
        return None
    try:
        yf = requests.get(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": "CL=F,BZ=F,BTC-USD,ETH-USD"},
            timeout=6,
        )
    except requests.RequestException as exc:
        log.warning("Error Yahoo Finance: %s", exc)
        return None
    if not yf.ok:
        return None
    try:
        qdata = yf.json().get("quoteResponse", {}).get("result", [])
    except ValueError:
        return None
    if not qdata:
        return None
    lineas = ["🛢️ Precios (Yahoo Finance):", ""]
    for q in qdata:
        sym = q.get("symbol")
        name = q.get("shortName") or q.get("longName") or sym
        price = q.get("regularMarketPrice")
        change = q.get("regularMarketChange", 0) or 0
        change_pct = q.get("regularMarketChangePercent", 0) or 0
        lineas.append(f"{name} ({sym}): {price} USD ({change:+.2f}, {change_pct:+.2f}%)")
    return ("Yahoo Finance", "\n".join(lineas).strip())


# ── Orquestación ──────────────────────────────────────────────

_FUENTES: dict[str, Callable[[str, int], tuple[str, str] | None]] = {
    "ddgs": lambda q, n: _buscar_ddgs(q, n),
    "instant": lambda q, _n: _buscar_ddg_instant(q),
    "wiki": lambda q, _n: _buscar_wikipedia(q),
    "finance": lambda q, _n: _buscar_yahoo_finance(q),
}

_ORDEN_SALIDA = ("finance", "ddgs", "instant", "wiki")


def buscar_en_web(query: str, max_results: int | None = None) -> str:
    """Devuelve resultados combinados de las fuentes, cacheados por TTL."""
    if not query.strip():
        return ""
    max_results = max_results or config.SEARCH_MAX_RESULTS

    cache_key = f"{query.lower()}|{max_results}"
    cached = _cache_get(cache_key)
    if cached is not None:
        log.info("Búsqueda cacheada: '%s'", query)
        return cached

    resultados: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=len(_FUENTES)) as executor:
        futuros = {
            executor.submit(fn, query, max_results): nombre
            for nombre, fn in _FUENTES.items()
        }
        try:
            for futuro in as_completed(futuros, timeout=config.SEARCH_TIMEOUT):
                nombre = futuros[futuro]
                try:
                    resultado = futuro.result()
                    if resultado:
                        resultados[nombre] = resultado
                        log.info("Fuente completada: %s", nombre)
                except Exception as exc:
                    log.warning("Fuente %s falló: %s", nombre, exc)
        except TimeoutError:
            log.warning("Timeout global de búsqueda; usando lo que llegó")

    if not resultados:
        return ""

    partes = []
    for clave in _ORDEN_SALIDA:
        if clave in resultados:
            src, txt = resultados[clave]
            partes.append(f"--- {src} ---\n{txt}\n")

    combined = "\n".join(partes).strip()
    _cache_put(cache_key, combined)
    return combined
