"""
Shopstar (shopstar.pe) — Scraper Multi-categoría.
Adaptado al proyecto Cazador de Ofertas.

Tecnología: requests + VTEX Intelligent Search API (sin JS)
Sitio:      https://www.shopstar.pe
"""

import json
import os
import concurrent.futures
import requests
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

# ── Configuración ─────────────────────────────────────────────────────────────
CATEGORIAS_URLS = [
    "https://www.shopstar.pe/tecnologia",
    "https://www.shopstar.pe/electrohogar",
    "https://www.shopstar.pe/belleza-y-cuidado-personal",
    "https://www.shopstar.pe/hogar",
    "https://www.shopstar.pe/accesorios-de-moda",
    "https://www.shopstar.pe/calzado",
    "https://www.shopstar.pe/deportes-y-aire-libre",
    "https://www.shopstar.pe/infantil",
    "https://www.shopstar.pe/mascotas",
    "https://www.shopstar.pe/muebles",
    "https://www.shopstar.pe/moda",
    "https://www.shopstar.pe/salud-y-bienestar",
]
PAGINAS_POR_CATEGORIA = 5
PRODUCTOS_POR_PAGINA  = 24
DOMINIO_BASE          = "https://www.shopstar.pe"
MAX_WORKERS           = 1   # MÍNIMO: una petición a la vez

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}
# ─────────────────────────────────────────────────────────────────────────────


def _url_a_categoria(url: str) -> str:
    """Extrae solo el path sin dominio ni query params."""
    return urlparse(url).path.strip('/')


def _id_desde_url(enlace: str) -> str:
    """Id único del producto desde la URL VTEX.

    Las URLs de Shopstar terminan en '/p' (p. ej. .../colchon-paraiso-288921/p),
    así que el último segmento NO sirve como id: todos los productos daban 'p' y
    el historial de precios entero colapsaba en un solo registro (bug 2026-07-04).
    Se usa el slug (segmento anterior al '/p'), que incluye el código numérico."""
    if not enlace:
        return ""
    segmentos = [s for s in urlparse(enlace).path.split('/') if s]
    if not segmentos:
        return ""
    slug = segmentos[-2] if segmentos[-1] == 'p' and len(segmentos) > 1 else segmentos[-1]
    return slug


def _armar_producto(nombre: str, categoria: str,
                    val_regular: float, val_online: float, enlace: str) -> dict:
    if val_regular == 0:
        val_regular = val_online
    return {
        'id':            _id_desde_url(enlace),
        'nombre':        nombre,
        'marca':         "",
        'categoria':     categoria,
        'precio_normal': val_regular if val_regular > 0 else None,
        'precio_oferta': val_online  if val_online  > 0 else None,
        'url':           enlace,
    }


def _consultar_vtex(tarea: tuple) -> list:
    """
    Consulta la VTEX Intelligent Search API de Shopstar.
    Tiene fallback al endpoint de catálogo clásico.
    """
    categoria, pagina = tarea
    desde = (pagina - 1) * PRODUCTOS_POR_PAGINA
    hasta = desde + PRODUCTOS_POR_PAGINA - 1

    url_is = (
        f"{DOMINIO_BASE}/api/io/_v/api/intelligent-search/product_search/{categoria}"
        f"?page={pagina}&count={PRODUCTOS_POR_PAGINA}&query=&sort=&map=category-1"
    )
    url_cl = (
        f"{DOMINIO_BASE}/api/catalog_system/pub/products/search"
        f"?fq=C:/{categoria}/&_from={desde}&_to={hasta}"
    )

    print(f"  📡 [Shopstar/{categoria}] p{pagina}")
    productos = []

    try:
        r = requests.get(url_is, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"  ↩️  Fallback API clásica ({categoria} p{pagina})")
            r = requests.get(url_cl, headers=HEADERS, timeout=15)

        if r.status_code != 200:
            print(f"  ❌ [{categoria}] p{pagina} — HTTP {r.status_code}")
            return []

        datos = r.json()

        # ── VTEX Intelligent Search ──
        if isinstance(datos, dict) and 'products' in datos:
            items = datos['products']
            if not items:
                return []
            for item in items:
                nombre = item.get('productName', 'Sin nombre')
                enlace = DOMINIO_BASE + item.get('link', '')
                pr     = item.get('priceRange', {})
                lista  = pr.get('listPrice', {})
                venta  = pr.get('sellingPrice', {})

                val_regular = lista.get('highPrice') or lista.get('lowPrice') or 0
                val_online  = venta.get('lowPrice')  or venta.get('highPrice') or 0

                # Fallback a SKU-level si no hay precio en priceRange
                if val_online == 0:
                    for sku in item.get('items', []):
                        for seller in sku.get('sellers', []):
                            oferta      = seller.get('commertialOffer', {})
                            val_online  = oferta.get('Price', 0)
                            val_regular = oferta.get('ListPrice', val_online)
                            if val_online > 0:
                                break
                        if val_online > 0:
                            break

                productos.append(_armar_produto(nombre, categoria, val_regular, val_online, enlace))

        # ── API Catálogo clásica ──
        elif isinstance(datos, list):
            for item in datos:
                nombre = item.get('productName', 'Sin nombre')
                enlace = DOMINIO_BASE + item.get('link', '')
                val_regular = val_online = 0
                for sku in item.get('items', []):
                    for seller in sku.get('sellers', []):
                        oferta      = seller.get('commertialOffer', {})
                        val_online  = oferta.get('Price', 0)
                        val_regular = oferta.get('ListPrice', val_online)
                        if val_online > 0:
                            break
                    if val_online > 0:
                        break
                productos.append(_armar_produto(nombre, categoria, val_regular, val_online, enlace))

    except Exception as e:
        print(f"  ❌ [{categoria}] p{pagina} — Error: {e}")

    print(f"  ✅ [Shopstar/{categoria}] p{pagina} → {len(productos)} productos")
    return productos


# Alias con nombre correcto (typo original en shopstar.py)
def _armar_produto(nombre, categoria, val_regular, val_online, enlace):
    return _armar_producto(nombre, categoria, val_regular, val_online, enlace)


def main() -> list:
    """
    Ejecuta el scraping de Shopstar y retorna la lista de productos.
    Guarda un JSON en tiendas/shopstar/datos/ con timestamp.
    """
    print("=" * 60)
    print("  SHOPSTAR SCRAPER — Multi-categoría · VTEX API")
    print("=" * 60)

    cats   = [_url_a_categoria(u) for u in CATEGORIAS_URLS]
    tareas = [
        (cat, pag)
        for cat in cats
        for pag in range(1, PAGINAS_POR_CATEGORIA + 1)
    ]
    print(f"  Categorías: {len(cats)} | "
          f"Páginas/cat: {PAGINAS_POR_CATEGORIA} | "
          f"Total consultas: {len(tareas)}\n")

    todos = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for resultado in executor.map(_consultar_vtex, tareas):
            todos.extend(resultado)

    # Deduplicar: el mismo producto aparece en varias categorías de Shopstar.
    vistos, unicos = set(), []
    for p in todos:
        clave = p.get('id') or p.get('url')
        if clave and clave in vistos:
            continue
        if clave:
            vistos.add(clave)
        unicos.append(p)
    if len(unicos) < len(todos):
        print(f"  🔁 {len(todos) - len(unicos)} duplicados removidos (multi-categoría)")
    todos = unicos

    # Guardar JSON
    if todos:
        ahora     = datetime.now(TZ_PERU)
        fecha_tag = ahora.strftime("%Y-%m-%d_%H%M%S")
        datos_dir = os.path.join(os.path.dirname(__file__), "datos")
        os.makedirs(datos_dir, exist_ok=True)
        json_path = os.path.join(datos_dir, f"shopstar_{fecha_tag}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(todos, f, ensure_ascii=False, indent=2)
        print(f"\n💾 JSON → {json_path}  ({len(todos)} productos)")
    else:
        print("\n⚠️  No se obtuvieron datos.")

    print(f"\n{'=' * 60}")
    print(f"  ✅ SHOPSTAR — {len(todos)} productos obtenidos en total.")
    print(f"{'=' * 60}")
    print("\n🎉 ¡Listo!")
    return todos


if __name__ == "__main__":
    main()
