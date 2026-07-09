"""Búsqueda web multi-fuente con extracción de contenido.

Diseño:
1. Consulta varias fuentes en paralelo (DDG web, DDG news, Wikipedia, Yahoo).
2. Deduplica resultados por dominio (evita 5 resultados del mismo sitio).
3. Descarga las 2-3 mejores páginas y extrae texto principal.
4. Combina snippets + contenido real y lo pasa al LLM en formato compacto.
5. Cachea el resultado final con TTL.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

from . import config
from .logging_setup import get_logger
from .web_fetch import extract_main_text, fetch_url, is_blocked_domain

log = get_logger(__name__)


# ── Modelo de resultado ──────────────────────────────────────

@dataclass
class SearchHit:
    """Un resultado unificado de cualquier fuente."""
    title: str
    url: str
    snippet: str
    source: str
    published: str = ""  # fecha ISO si es noticia
    content: str = ""  # texto extraído tras fetch
    domain: str = field(init=False)

    def __post_init__(self):
        try:
            host = urlparse(self.url).netloc.lower()
            self.domain = host.removeprefix("www.")
        except ValueError:
            self.domain = ""


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
            oldest_key = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest_key, None)
        _cache[key] = (time.time(), value)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ── Detección de intención "noticias" ─────────────────────────

_NEWS_KEYWORDS = (
    "noticia", "noticias", "última hora", "ultima hora", "hoy",
    "esta semana", "este mes", "ayer", "reciente", "recientes",
    "anuncia", "anunció", "anuncio", "presenta", "presentó",
    "resultado", "gana", "ganó", "pierde", "perdió", "marcó",
    "elecciones", "gobierno", "crisis",
)


def es_pregunta_de_noticias(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in _NEWS_KEYWORDS)


# ── Fuentes ──────────────────────────────────────────────────

def _importar_ddgs():
    try:
        from ddgs import DDGS  # type: ignore
        return DDGS
    except ImportError:
        pass
    try:
        from duckduckgo_search import DDGS  # type: ignore
        return DDGS
    except ImportError:
        return None


def _buscar_ddgs_web(query: str, max_results: int) -> list[SearchHit]:
    DDGS = _importar_ddgs()
    if DDGS is None:
        log.warning("ddgs/duckduckgo-search no instalado")
        return []
    try:
        with DDGS(timeout=8) as ddgs:
            resultados = list(
                ddgs.text(query, region="es-es", safesearch="moderate",
                          max_results=max_results)
            )
    except Exception as exc:  # ddgs lanza sus propios errores
        log.warning("Error DDGS web: %s", exc)
        return []
    hits: list[SearchHit] = []
    for r in resultados:
        url = r.get("href") or r.get("url", "")
        if not url or is_blocked_domain(url):
            continue
        hits.append(SearchHit(
            title=(r.get("title") or "Sin título").strip(),
            url=url,
            snippet=(r.get("body") or "").strip(),
            source="DuckDuckGo",
        ))
    return hits


def _buscar_ddgs_news(query: str, max_results: int) -> list[SearchHit]:
    DDGS = _importar_ddgs()
    if DDGS is None:
        return []
    try:
        with DDGS(timeout=8) as ddgs:
            if not hasattr(ddgs, "news"):
                return []
            resultados = list(
                ddgs.news(query, region="es-es", safesearch="moderate",
                          max_results=max_results, timelimit="w")
            )
    except Exception as exc:
        log.info("DDGS news no disponible: %s", exc)
        return []
    hits: list[SearchHit] = []
    for r in resultados:
        url = r.get("url") or r.get("href", "")
        if not url or is_blocked_domain(url):
            continue
        hits.append(SearchHit(
            title=(r.get("title") or "Sin título").strip(),
            url=url,
            snippet=(r.get("body") or r.get("excerpt") or "").strip(),
            source=(r.get("source") or "DuckDuckGo News").strip(),
            published=(r.get("date") or "").strip(),
        ))
    return hits


def _buscar_ddg_instant(query: str, _max_results: int) -> list[SearchHit]:
    """DuckDuckGo Instant Answers: definiciones y resúmenes cortos."""
    try:
        resp = requests.get(
            "https://api.duckduckgo.com",
            params={"q": query, "format": "json", "kl": "es-es",
                    "no_html": 1, "skip_disambig": 1},
            timeout=6,
        )
    except requests.RequestException as exc:
        log.info("DDG Instant falló: %s", exc)
        return []
    if not resp.ok:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    hits: list[SearchHit] = []
    abstract = (data.get("AbstractText") or "").strip()
    abstract_url = data.get("AbstractURL") or ""
    if abstract:
        hits.append(SearchHit(
            title=data.get("Heading") or query,
            url=abstract_url,
            snippet=abstract,
            source="DuckDuckGo Instant",
        ))
    for t in data.get("RelatedTopics", [])[:4]:
        if not isinstance(t, dict):
            continue
        texto = (t.get("Text") or "").strip()
        first_url = (t.get("FirstURL") or "").strip()
        if texto and first_url:
            hits.append(SearchHit(
                title=texto.split(" - ")[0][:120],
                url=first_url,
                snippet=texto,
                source="DuckDuckGo Instant",
            ))
    return hits


def _buscar_wikipedia(query: str, _max_results: int) -> list[SearchHit]:
    try:
        sresp = requests.get(
            "https://es.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": query,
                    "format": "json", "srlimit": 2},
            timeout=6,
        )
    except requests.RequestException as exc:
        log.info("Wikipedia (search) falló: %s", exc)
        return []
    if not sresp.ok:
        return []
    try:
        raw = sresp.json().get("query", {}).get("search", [])
    except ValueError:
        return []
    if not raw:
        return []

    def get_extract(hit: dict) -> SearchHit | None:
        pid = hit.get("pageid")
        title = hit.get("title", "").strip()
        if not pid or not title:
            return None
        extract = ""
        try:
            eres = requests.get(
                "https://es.wikipedia.org/w/api.php",
                params={"action": "query", "prop": "extracts",
                        "explaintext": 1, "pageids": pid,
                        "format": "json", "exintro": 1},
                timeout=5,
            )
            if eres.ok:
                pages = eres.json().get("query", {}).get("pages", {})
                extract = (pages.get(str(pid), {}).get("extract") or "").strip()
        except requests.RequestException:
            pass
        # snippet ya viene con <span> — quita las etiquetas
        snippet = re.sub(r"<[^>]+>", "", hit.get("snippet", "")).strip()
        url = f"https://es.wikipedia.org/?curid={pid}"
        return SearchHit(
            title=title,
            url=url,
            snippet=(extract or snippet)[:800],
            source="Wikipedia",
            content=extract[:2500] if extract else "",
        )

    with ThreadPoolExecutor(max_workers=2) as ex:
        hits = [h for h in ex.map(get_extract, raw) if h]
    return hits


_FINANCE_KEYWORDS = (
    "barril", "petróleo", "petroleo", "crudo", "oil",
    "bitcoin", "ethereum", "crypto", "bolsa",
)


def _buscar_yahoo_finance(query: str, _max_results: int) -> list[SearchHit]:
    if not any(k in query.lower() for k in _FINANCE_KEYWORDS):
        return []
    try:
        yf = requests.get(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": "CL=F,BZ=F,BTC-USD,ETH-USD"},
            timeout=6,
        )
    except requests.RequestException as exc:
        log.info("Yahoo Finance falló: %s", exc)
        return []
    if not yf.ok:
        return []
    try:
        qdata = yf.json().get("quoteResponse", {}).get("result", [])
    except ValueError:
        return []
    if not qdata:
        return []
    lineas: list[str] = []
    for q in qdata:
        sym = q.get("symbol")
        name = q.get("shortName") or q.get("longName") or sym
        price = q.get("regularMarketPrice")
        change = q.get("regularMarketChange", 0) or 0
        change_pct = q.get("regularMarketChangePercent", 0) or 0
        lineas.append(
            f"{name} ({sym}): {price} USD ({change:+.2f}, {change_pct:+.2f}%)"
        )
    return [SearchHit(
        title="Cotizaciones actuales",
        url="https://finance.yahoo.com/",
        snippet="\n".join(lineas),
        source="Yahoo Finance",
    )]


# ── Orquestación ─────────────────────────────────────────────

_FuenteFn = Callable[[str, int], list[SearchHit]]

_FUENTES: dict[str, _FuenteFn] = {
    "ddgs": _buscar_ddgs_web,
    "instant": _buscar_ddg_instant,
    "wiki": _buscar_wikipedia,
    "finance": _buscar_yahoo_finance,
}


def _dedupe_por_dominio(hits: list[SearchHit], max_por_dominio: int = 1) -> list[SearchHit]:
    """Deja como mucho `max_por_dominio` resultados por dominio, conservando orden."""
    contados: dict[str, int] = {}
    salida: list[SearchHit] = []
    for h in hits:
        key = h.domain or h.url
        if contados.get(key, 0) >= max_por_dominio:
            continue
        contados[key] = contados.get(key, 0) + 1
        salida.append(h)
    return salida


def _enriquecer_con_contenido(hits: list[SearchHit], k: int = 2) -> None:
    """Descarga las `k` primeras páginas y les rellena `.content`. Modifica in-place."""
    candidatos = [h for h in hits if not h.content and h.url and not h.url.startswith("https://es.wikipedia.org")]
    if not candidatos:
        return
    candidatos = candidatos[:k]

    def worker(hit: SearchHit) -> None:
        html = fetch_url(hit.url, timeout=6)
        if html:
            texto = extract_main_text(html, max_chars=2500)
            if len(texto) > 200:
                hit.content = texto

    with ThreadPoolExecutor(max_workers=len(candidatos)) as ex:
        list(ex.map(worker, candidatos))


def _formatear_para_llm(hits: list[SearchHit], query: str) -> str:
    """Compone el contexto que se pasa al LLM. Denso, con fuentes claras."""
    if not hits:
        return ""

    bloques: list[str] = [f"Búsqueda: {query}", ""]
    for i, h in enumerate(hits, 1):
        cabecera = f"[{i}] {h.title}"
        if h.published:
            cabecera += f"  ·  {h.published}"
        bloques.append(cabecera)
        bloques.append(f"    Fuente: {h.source} — {h.url}")
        cuerpo = (h.content or h.snippet).strip()
        if cuerpo:
            # Sangrar el cuerpo para que se lea como cita en el prompt
            sangrado = "\n".join("    " + linea for linea in cuerpo.splitlines())
            bloques.append(sangrado)
        bloques.append("")
    return "\n".join(bloques).strip()


def buscar_en_web(query: str, max_results: int | None = None) -> str:
    """Devuelve un bloque de texto listo para inyectar en el prompt del LLM."""
    if not query.strip():
        return ""
    max_results = max_results or config.SEARCH_MAX_RESULTS

    cache_key = f"{query.lower()}|{max_results}"
    cached = _cache_get(cache_key)
    if cached is not None:
        log.info("Búsqueda cacheada: '%s'", query)
        return cached

    fuentes = dict(_FUENTES)
    if es_pregunta_de_noticias(query):
        fuentes["news"] = _buscar_ddgs_news

    hits_por_fuente: dict[str, list[SearchHit]] = {}
    with ThreadPoolExecutor(max_workers=len(fuentes)) as executor:
        futuros = {
            executor.submit(fn, query, max_results): nombre
            for nombre, fn in fuentes.items()
        }
        try:
            for futuro in as_completed(futuros, timeout=config.SEARCH_TIMEOUT):
                nombre = futuros[futuro]
                try:
                    resultados = futuro.result()
                except Exception as exc:  # noqa: BLE001
                    log.warning("Fuente %s falló: %s", nombre, exc)
                    continue
                if resultados:
                    hits_por_fuente[nombre] = resultados
                    log.info("Fuente %s → %d resultados", nombre, len(resultados))
        except TimeoutError:
            log.warning("Timeout global de búsqueda; usando lo que llegó")

    # Componer lista final: noticias primero (más frescas), luego DDG, wiki, instant, finance
    orden = ("news", "ddgs", "wiki", "instant", "finance")
    combinados: list[SearchHit] = []
    for clave in orden:
        combinados.extend(hits_por_fuente.get(clave, []))

    if not combinados:
        return ""

    # Dedupe por dominio y recorte
    combinados = _dedupe_por_dominio(combinados, max_por_dominio=1)
    combinados = combinados[: max(3, min(max_results, 6))]

    # Enriquecer con contenido real de páginas top
    _enriquecer_con_contenido(combinados, k=2)

    salida = _formatear_para_llm(combinados, query)
    _cache_put(cache_key, salida)
    return salida
