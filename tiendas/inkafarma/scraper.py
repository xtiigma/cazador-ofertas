"""
Inkafarma Scraper — Multi-categoría, con reintentos. 100% requests (sin navegador).

Los IDs de producto de cada categoría se obtienen del índice público de Algolia
(la misma consulta que hace la web); los datos/precios salen del API
filtered-products, igual que siempre. Hasta 2026-07-07 los IDs se capturaban
lanzando un Chromium por categoría (Playwright), lo que disparaba la
temperatura de la mini PC; ya no se usa ningún navegador.

Instalar dependencias:
  pip install requests
"""

import asyncio
import json
import os
import re
import time
import unicodedata
import requests
from urllib.parse import quote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Categorías a scrapear ─────────────────────────────────────────────────────
CATEGORIES = [
    "https://inkafarma.pe/categoria/salud",
    "https://inkafarma.pe/categoria/farmacia",
    "https://inkafarma.pe/categoria/dermatologia-cosmetica",
    "https://inkafarma.pe/categoria/inka-packs",
    "https://inkafarma.pe/categoria/promociones-especiales",
    "https://inkafarma.pe/categoria/cuidado-personal",
    "https://inkafarma.pe/categoria/belleza",
    "https://inkafarma.pe/categoria/limpieza-y-cuidado-para-el-hogar",
    "https://inkafarma.pe/categoria/cuidado-del-cabello-1",
    "https://inkafarma.pe/categoria/productos-naturales-1",
]

# ── Configuración de paginación ───────────────────────────────────────────────
# Cada categoría captura dinámicamente sus IDs de producto vía Playwright.
# Luego se dividen en páginas de ROWS_PER_PAGE elementos y se consultan en paralelo.
# MAX_PAGINAS_POR_CATEGORIA = None → sin límite (scrapea todo lo que tenga la categoría)
# MAX_PAGINAS_POR_CATEGORIA = 50  → máximo 50 páginas × 8 productos = 400 productos por categoría
ROWS_PER_PAGE             = 21    # productos por página (valor fijo del API de Inkafarma)
MAX_PAGINAS_POR_CATEGORIA = None  # None = sin límite | Ejemplo: 50 = máx 400 productos

# ── Paralelismo y reintentos ──────────────────────────────────────────────────
MAX_CONCURRENT  = 1   # requests simultáneas. MÍNIMO: una a la vez; la prioridad es no
                      # estresar la mini PC ni la tienda, no la velocidad.
MAX_RETRIES     = 4   # reintentos por página en caso de error
RETRY_DELAY     = 3   # segundos entre reintentos
REQUEST_TIMEOUT = 30  # segundos por request

# ── Endpoints y cabeceras ─────────────────────────────────────────────────────
API_URL = "https://5doa19p9r7.execute-api.us-east-1.amazonaws.com/MMPROD/filtered-products"

QUERY_PARAMS = {
    "companyCode":      "IKF",
    "saleChannel":      "WEB",
    "saleChannelType":  "DIGITAL",
    "sourceDevice":     "null",
    "userCallCenterId": "undefined",
}

HEADERS = {
    "Content-Type": "application/json",
    "Accept":       "application/json, text/plain, */*",
    "Origin":       "https://inkafarma.pe",
    "User-Agent":   (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


# ── Session HTTP con reintentos automáticos ───────────────────────────────────
def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,          # espera 1s, 2s, 4s, 8s entre reintentos
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = make_session()


# ── PASO 1: Capturar IDs desde Algolia (sin navegador) ───────────────────────
# La web de Inkafarma consulta su índice "products" de Algolia para saber qué
# productos mostrar en una categoría, y con esos IDs llama a filtered-products.
# Replicamos esa primera consulta con requests. La API key es la de SOLO
# BÚSQUEDA que la web expone a cualquier navegador; si algún día rota, abrir
# https://inkafarma.pe/categoria/salud con las DevTools y copiar los headers
# x-algolia-* de la petición a *.algolia.net.
ALGOLIA_URL = "https://15w622laq4-dsn.algolia.net/1/indexes/*/queries"

ALGOLIA_HEADERS = {
    "x-algolia-application-id": "15W622LAQ4",
    "x-algolia-api-key":        "ccd8cbda203928003f7fe6f44ddbfc3a",
    "Content-Type":             "application/json",
    "Referer":                  "https://inkafarma.pe/",
    "User-Agent":               HEADERS["User-Agent"],
}

# La página de categoría carga los 250 productos mejor rankeados: pedimos lo
# mismo para mantener paridad exacta con lo que el navegador capturaba.
IDS_POR_CATEGORIA = 250


def _consultar_algolia(params: str) -> dict:
    """Ejecuta una consulta al índice products y devuelve su resultado."""
    payload = {"requests": [{"indexName": "products", "params": params}]}
    r = SESSION.post(ALGOLIA_URL, headers=ALGOLIA_HEADERS, json=payload,
                     timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["results"][0]


def _normalizar_slug(texto: str) -> str:
    """'Dermatología Cosmética' → 'dermatologia-cosmetica' (formato de URL)."""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")


def resolver_departments() -> dict:
    """{slug: nombre real del department} leyendo el facet desde Algolia.

    Se resuelve dinámicamente (1 request) para que un renombre de categoría en
    la tienda no rompa el mapeo mientras el slug siga siendo reconocible."""
    params = ("query=&facets=" + quote('["department"]')
              + "&facetFilters=" + quote('[["channels:WEB"]]')
              + "&length=1&offset=0&maxValuesPerFacet=100")
    resultado = _consultar_algolia(params)
    departments = (resultado.get("facets") or {}).get("department", {})
    return {_normalizar_slug(nombre): nombre for nombre in departments}


def capture_product_ids(department: str) -> list:
    """IDs de producto (objectID) de un department, los mismos que la web
    manda después a filtered-products."""
    filtros = json.dumps([f"department:{department}", ["channels:WEB"]])
    params = ("query=&facetFilters=" + quote(filtros)
              + f"&length={IDS_POR_CATEGORIA}&offset=0"
              + "&attributesToRetrieve=" + quote('["objectID"]')
              + "&attributesToHighlight=" + quote("[]"))
    resultado = _consultar_algolia(params)
    ids = [h["objectID"] for h in resultado.get("hits", []) if h.get("objectID")]
    if ids:
        print(f"    ✔ {len(ids)} IDs capturados (Algolia, {resultado.get('nbHits')} en catálogo)")
    return ids


# ── PASO 2: Fetch de una página con reintentos manuales ──────────────────────
def fetch_page_sync(product_ids: list, page: int, category_url: str) -> tuple[int, list]:
    """Retorna (page, rows). Reintenta hasta MAX_RETRIES veces."""
    payload = {
        "departmentsFilter":   [],
        "categoriesFilter":    [],
        "subcategoriesFilter": [],
        "brandsFilter":        [],
        "ranking":             None,
        "order":               None,
        "page":                page,
        "productsFilter":      product_ids,
        "rows":                ROWS_PER_PAGE,
        "sort":                "",
    }
    headers = {**HEADERS, "Referer": category_url}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = SESSION.post(
                API_URL, params=QUERY_PARAMS,
                headers=headers, json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            return page, r.json().get("rows", [])
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
            else:
                return page, []   # página fallida tras todos los reintentos


# ── PASO 2 async: wrapper para ejecutar en threadpool ────────────────────────
async def fetch_page_async(semaphore, product_ids, page, category_url):
    async with semaphore:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, fetch_page_sync, product_ids, page, category_url
        )


# ── Utilidades de extracción ──────────────────────────────────────────────────
def strip_html(text: str) -> str:
    """Elimina etiquetas HTML y normaliza espacios."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def extract_detail(details: list, key: str) -> str:
    """Extrae el contenido limpio de un detalle por su clave (ej. COMPOSITION)."""
    for item in details or []:
        if item.get("key") == key:
            return strip_html(item.get("content", ""))
    return ""


# ── Extracción de campos ──────────────────────────────────────────────────────
def extract_fields(p: dict, categoria_origen: str) -> dict:
    """
    Campos guardados en el JSON final.
    Solo lo estrictamente necesario para análisis de precios y producto.
    """
    details    = p.get("details") or []
    categories = ", ".join(c.get("name", "") for c in (p.get("categoryList") or []))

    return {
        # ── Identificación ────────────────────────────────────────────────
        "categoria_origen": categoria_origen,
        "id":               p.get("id"),
        "nombre":           p.get("name"),
        "marca":            p.get("brand"),
        "categorias":       categories,
        # ── Precios ───────────────────────────────────────────────────────
        "precio_normal":    p.get("price"),
        "precio_oferta":    p.get("priceAllPaymentMethod"),
        "precio_minimo":    p.get("priceWithpaymentMethod"),
        # ── Presentación ──────────────────────────────────────────────────
        "presentacion":     p.get("presentation"),
        "tamaño":           p.get("size"),
        "unidad":           p.get("unitMeasure"),
        # ── Disponibilidad ────────────────────────────────────────────────
        "stock":            p.get("stock"),
        # ── Contenido del producto ────────────────────────────────────────
        "composicion":      extract_detail(details, "COMPOSITION"),
        # ── Enlace ────────────────────────────────────────────────────────
        "url":              f"https://inkafarma.pe/producto/{p.get('slug')}/{p.get('id')}",
    }


# ── Scraper paralelo de una categoría ────────────────────────────────────────
async def scrape_category(product_ids: list, category_url: str) -> list:
    total     = len(product_ids)
    num_pages = -(-total // ROWS_PER_PAGE)   # ceil division

    # Aplicar límite de páginas si está configurado
    if MAX_PAGINAS_POR_CATEGORIA is not None:
        num_pages = min(num_pages, MAX_PAGINAS_POR_CATEGORIA)
        ids_a_procesar = product_ids[: num_pages * ROWS_PER_PAGE]
        print(f"  📦 {total} IDs disponibles → limitado a {num_pages} páginas "
              f"({len(ids_a_procesar)} productos)  (MAX_PAGINAS_POR_CATEGORIA={MAX_PAGINAS_POR_CATEGORIA})")
    else:
        ids_a_procesar = product_ids
        print(f"  📦 {total} productos → {num_pages} páginas  "
              f"(hasta {MAX_CONCURRENT} requests en paralelo) [sin límite de páginas]")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    # Lanzar todas las páginas en paralelo
    tasks = [
        fetch_page_async(semaphore, ids_a_procesar, page, category_url)
        for page in range(num_pages)
    ]

    # Recolectar resultados conforme van llegando
    results = {}
    failed  = []

    for coro in asyncio.as_completed(tasks):
        page_num, rows = await coro
        start = page_num * ROWS_PER_PAGE + 1
        end   = min((page_num + 1) * ROWS_PER_PAGE, len(ids_a_procesar))

        if rows:
            results[page_num] = rows
            done = len(results)
            print(f"    ✔ Pág {page_num+1:>3}/{num_pages}  ({start}–{end})  "
                  f"→ {len(rows)} productos  [{done}/{num_pages} listas]")
        else:
            failed.append(page_num)
            print(f"    ✗ Pág {page_num+1:>3}/{num_pages}  ({start}–{end})  "
                  f"→ FALLÓ tras {MAX_RETRIES} reintentos")

    # Reconstruir en orden correcto
    slug         = category_url.rstrip("/").split("/")[-1]
    all_products = []
    for page_num in sorted(results):
        all_products.extend([extract_fields(p, slug) for p in results[page_num]])

    if failed:
        print(f"\n  ⚠️  {len(failed)} páginas fallidas: {[p+1 for p in sorted(failed)]}")

    return all_products


# ── Guardar ───────────────────────────────────────────────────────────────────
def save(products: list):
    if not products:
        print("⚠️  Sin productos.")
        return

    from datetime import datetime, timezone, timedelta
    ahora      = datetime.now(timezone(timedelta(hours=-5)))
    fecha_hora = ahora.strftime("%Y-%m-%d_%H%M%S")

    datos_dir = os.path.join(os.path.dirname(__file__), "datos")
    os.makedirs(datos_dir, exist_ok=True)

    json_path = os.path.join(datos_dir, f"inkafarma_{fecha_hora}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON → {json_path}  ({len(products)} productos)")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("  INKAFARMA SCRAPER — Multi-categoría · Paralelo · Reintentos")
    print("=" * 60)

    limite_info = (
        f"MAX_PAGINAS_POR_CATEGORIA = {MAX_PAGINAS_POR_CATEGORIA} "
        f"(máx {MAX_PAGINAS_POR_CATEGORIA * ROWS_PER_PAGE} productos/categoría)"
        if MAX_PAGINAS_POR_CATEGORIA else
        "MAX_PAGINAS_POR_CATEGORIA = None (sin límite)"
    )
    print(f"  {limite_info}")
    print(f"  Categorías: {len(CATEGORIES)}")
    print("=" * 60)

    try:
        departments = resolver_departments()
        print(f"  Departments en Algolia: {len(departments)}")
    except Exception as e:
        print(f"❌ No se pudo consultar Algolia: {e}")
        return []

    all_products = []
    seen_ids     = set()

    for i, url in enumerate(CATEGORIES, 1):
        slug = url.rstrip("/").split("/")[-1]
        print(f"\n[{i}/{len(CATEGORIES)}] ── {slug.upper()} ──")
        print(f"  🌐 {url}")

        # 'cuidado-del-cabello-1' → 'cuidado-del-cabello' (sufijo numérico de la URL)
        slug_limpio = re.sub(r"-\d+$", "", slug)
        department  = departments.get(slug_limpio)
        if not department:
            print(f"  ❌ Ningún department de Algolia coincide con '{slug}', saltando...")
            continue

        try:
            product_ids = capture_product_ids(department)
        except Exception as e:
            print(f"  ❌ Error consultando Algolia para '{slug}': {e}")
            product_ids = []

        if not product_ids:
            print(f"  ❌ Sin IDs para '{slug}', saltando...")
            continue

        new_ids    = [pid for pid in product_ids if pid not in seen_ids]
        duplicados = len(product_ids) - len(new_ids)
        seen_ids.update(product_ids)

        if duplicados:
            print(f"  ℹ️  {duplicados} duplicados omitidos → procesando {len(new_ids)} nuevos")

        t0       = time.time()
        products = await scrape_category(new_ids, url)
        elapsed  = time.time() - t0

        all_products.extend(products)
        print(f"\n  ✅ '{slug}': {len(products)} productos en {elapsed:.1f}s")

        if i < len(CATEGORIES):
            await asyncio.sleep(2)

    print(f"\n{'=' * 60}")
    print(f"  Total: {len(all_products)} productos de {len(CATEGORIES)} categorías")
    print(f"{'=' * 60}")
    save(all_products)
    print("\n🎉 ¡Listo!")

    return all_products


if __name__ == "__main__":
    asyncio.run(main())