"""
Saga Falabella Perú — Scraper vía JSON embebido (__NEXT_DATA__).
Migrado de Selenium a requests: 2026-07-04

Por qué el cambio:
  - El modo Selenium llevaba días agotando el timeout de 30 min con 0 productos
    y era la principal fuente de calor del ciclo (82 °C en la mini PC).
  - La página de categoría de falabella.com.pe es Next.js y devuelve TODO el
    listado (nombre, marca, precios, imagen, URL) en el <script id="__NEXT_DATA__">.
    Con un GET plano se obtiene lo mismo que renderizaba Chrome, en ~0.4 s/página.

Contrato de salida (idéntico al scraper Selenium anterior, para no romper
historial_precios ni el dashboard):
  {id, nombre, marca, categoria, precio_normal, precio_oferta, imagen, url}
  - id: último segmento de la URL (slug), igual que antes.
  - precio_normal: precio tachado (normalPrice crossed). None si no hay.
  - precio_oferta: precio vigente (eventPrice o internetPrice). Se ignora
    cmrPrice porque exige tarjeta CMR y no es comparable entre tiendas.

Secuencial a propósito: la prioridad en la mini PC es temperatura/RAM, no
velocidad. 16 categorías × 10 páginas ≈ 160 GET ≈ 2-3 min en total.
"""

import json
import os
import re
import time
from datetime import datetime, timezone, timedelta

import requests

TZ_PERU = timezone(timedelta(hours=-5))

# ── Config ─────────────────────────────────────────────────────────────────────
MAX_PAGINAS    = 3     # páginas por categoría
REINTENTOS_PAG = 2     # reintentos por página ante error de red/parseo
PAUSA_SEG      = 0.3   # pausa entre peticiones (no golpear el sitio)
HTTP_TIMEOUT   = 20    # segundos por petición

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-PE,es;q=0.9",
}

CATEGORIAS = {
    'Tecnologia':              'https://www.falabella.com.pe/falabella-pe/category/cat40793/Tecnologia',
    'Electrohogar':            'https://www.falabella.com.pe/falabella-pe/category/cat40584/Electrohogar',
    'Muebles':                 'https://www.falabella.com.pe/falabella-pe/category/CATG11951/Muebles-y-Organizacion',
    'Dormitorio':              'https://www.falabella.com.pe/falabella-pe/category/cat50684/Dormitorio',
    'Hombre':                  'https://www.falabella.com.pe/falabella-pe/category/CATG12022/Hombre',
    'Zapatos':                 'https://www.falabella.com.pe/falabella-pe/category/cat1470538/Zapatos',
    'Zapatillas':              'https://www.falabella.com.pe/falabella-pe/category/cat1470548/Zapatillas',
    'Moda-Hombre':             'https://www.falabella.com.pe/falabella-pe/category/cat4100481/Moda-Hombre',
    'Salud-Higiene':           'https://www.falabella.com.pe/falabella-pe/category/cat40498/Belleza--higiene-y-salud',
    'Menaje-Cocina':           'https://www.falabella.com.pe/falabella-pe/category/cat40685/Menaje-Cocina',
    'Construccion-Ferreteria': 'https://www.falabella.com.pe/falabella-pe/category/CATG11946/Construccion-y-ferreteria',
    'Bano':                    'https://www.falabella.com.pe/falabella-pe/category/CATG11988/Bano',
    'Mascotas':                'https://www.falabella.com.pe/falabella-pe/category/cat8050466/Mascotas',
    'Jardin-Terraza':          'https://www.falabella.com.pe/falabella-pe/category/CATG11948/Jardin-y-terraza',
    'Decoracion':              'https://www.falabella.com.pe/falabella-pe/category/cat40474/Decoracion',
    'Serums':                  'https://www.falabella.com.pe/falabella-pe/category/CATG19047/Serums',
}

_RE_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

# Orden de preferencia para el precio vigente (sin tarjeta CMR).
_TIPOS_PRECIO_VIGENTE = ("eventPrice", "internetPrice")


# ── Parseo ─────────────────────────────────────────────────────────────────────
def _precio_float(valor) -> float | None:
    """'1,019.90' → 1019.9. Los precios llegan como lista de strings."""
    if isinstance(valor, list):
        valor = valor[0] if valor else None
    if not valor:
        return None
    try:
        return float(str(valor).replace(",", "").strip())
    except ValueError:
        return None


def _extraer_precios(prices: list) -> tuple[float | None, float | None]:
    """(precio_normal, precio_oferta) desde la lista `prices` del pod."""
    por_tipo = {p.get("type"): p for p in prices if isinstance(p, dict)}

    normal = None
    p_normal = por_tipo.get("normalPrice")
    if p_normal:
        normal = _precio_float(p_normal.get("price"))

    oferta = None
    for tipo in _TIPOS_PRECIO_VIGENTE:
        if tipo in por_tipo:
            oferta = _precio_float(por_tipo[tipo].get("price"))
            break

    # Sin precio de evento/internet: el normal (no tachado) ES el precio vigente.
    if oferta is None and p_normal and not p_normal.get("crossed"):
        oferta, normal = normal, None

    return normal, oferta


def _armar_producto(pod: dict, categoria: str) -> dict | None:
    nombre = (pod.get("displayName") or "").strip()
    url = pod.get("url") or ""
    if not nombre:
        return None

    precio_normal, precio_oferta = _extraer_precios(pod.get("prices") or [])
    medias = pod.get("mediaUrls") or []

    # id = skuId numérico: es el último segmento del href que usaba el scraper
    # Selenium, así el historial de precios existente sigue reconociéndolos.
    return {
        "id":            str(pod.get("skuId") or pod.get("productId") or ""),
        "nombre":        nombre,
        "marca":         pod.get("brand") or "",
        "categoria":     categoria,
        "precio_normal": precio_normal,
        "precio_oferta": precio_oferta,
        "imagen":        medias[0] if medias else "",
        "url":           url,
    }


# ── Scraping de una página ─────────────────────────────────────────────────────
def scrapear_pagina(session, categoria, url_base, pagina) -> tuple[list, bool]:
    """Devuelve (productos, hay_mas_paginas)."""
    url = url_base if pagina == 1 else f"{url_base}?page={pagina}"

    for intento in range(1, REINTENTOS_PAG + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()

            m = _RE_NEXT_DATA.search(resp.text)
            if not m:
                raise ValueError("sin __NEXT_DATA__ en el HTML")

            props = json.loads(m.group(1))["props"]["pageProps"]
            resultados = props.get("results") or []
            paginacion = props.get("pagination") or {}

            # Si pedimos una página más allá del final, el sitio devuelve otra
            # página (p. ej. la 1): cortar aquí evita duplicados e requests inútiles.
            pagina_real = paginacion.get("currentPage")
            if pagina_real is not None and int(pagina_real) != pagina:
                return [], False

            filas = []
            for pod in resultados:
                prod = _armar_producto(pod, categoria)
                if prod:
                    filas.append(prod)

            return filas, bool(filas)

        except Exception as e:
            if intento < REINTENTOS_PAG:
                print(f"  ⚠️  {categoria} pág {pagina}: {e} — reintentando...")
                time.sleep(2)
            else:
                print(f"  ❌ {categoria} pág {pagina}: {e}")
    return [], False


# ── Deduplicar por URL base ───────────────────────────────────────────────────
def deduplicar(productos: list) -> list:
    """Elimina duplicados basándose en la URL base (sin query params)."""
    vistos = set()
    unicos = []
    for p in productos:
        url_base = p.get('url', '').split('?')[0]
        if url_base and url_base not in vistos:
            vistos.add(url_base)
            unicos.append(p)
        elif not url_base:
            unicos.append(p)
    return unicos


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    t_inicio = time.time()
    print("=" * 60)
    print("  SAGA FALABELLA SCRAPER — __NEXT_DATA__ · requests · sin Chrome")
    print("=" * 60)
    print(f"  Categorías: {len(CATEGORIAS)} | Máx páginas/cat: {MAX_PAGINAS}")

    session = requests.Session()
    todas_filas = []

    for categoria, url_base in CATEGORIAS.items():
        filas_cat = 0
        for pagina in range(1, MAX_PAGINAS + 1):
            filas, hay_mas = scrapear_pagina(session, categoria, url_base, pagina)
            todas_filas.extend(filas)
            filas_cat += len(filas)
            if not hay_mas:
                break
            time.sleep(PAUSA_SEG)
        print(f"  ✅ {categoria}: {filas_cat} productos")

    if not todas_filas:
        print('\n⚠️  No se obtuvieron datos.')
        return []

    # Deduplicar
    antes = len(todas_filas)
    productos = deduplicar(todas_filas)
    despues = len(productos)

    # Ordenar por descuento (mayor primero)
    productos.sort(
        key=lambda x: (
            round(((x.get('precio_normal') or 0) - (x.get('precio_oferta') or 0))
                  / (x.get('precio_normal') or 1) * 100, 2)
            if x.get('precio_normal') and x.get('precio_oferta')
               and x['precio_normal'] > x['precio_oferta']
            else 0
        ),
        reverse=True
    )

    # Guardar JSON con fecha y hora
    ahora = datetime.now(TZ_PERU)
    fecha_hora = ahora.strftime("%Y-%m-%d_%H%M%S")

    datos_dir = os.path.join(os.path.dirname(__file__), "datos")
    os.makedirs(datos_dir, exist_ok=True)

    json_path = os.path.join(datos_dir, f"saga_falabella_{fecha_hora}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(productos, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t_inicio
    print(f"""
╔════════════════════════════════════════╗
║   REPORTE FINAL                        ║
╠════════════════════════════════════════╣
║ Tiempo total:        {elapsed:>8.0f}s        ║
║ Productos extraídos: {antes:>8}         ║
║ Duplicados removidos:{antes - despues:>8}         ║
║ Productos únicos:    {despues:>8}         ║
╚════════════════════════════════════════╝
    """)
    print(f'💾 JSON → {json_path}  ({despues} productos)')
    print("\n🎉 ¡Listo!")

    return productos


if __name__ == '__main__':
    main()
