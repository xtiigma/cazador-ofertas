"""
EFE (efe.com.pe) — Scraper Multi-categoría.
Adaptado al proyecto Cazador de Ofertas.

Tecnología: requests + BeautifulSoup (Magento HTML estático)
Sitio:      https://www.efe.com.pe
"""

import json
import os
import concurrent.futures
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

# ── Configuración ─────────────────────────────────────────────────────────────
CATEGORIAS_URLS = [
    ("Tecnologia",   "https://www.efe.com.pe/tecnologia.html"),
    ("Electrohogar", "https://www.efe.com.pe/electrohogar.html"),
    ("Celulares",    "https://www.efe.com.pe/celulares-y-smartphones.html"),
    ("Tablets",      "https://www.efe.com.pe/tablets.html"),
    ("Computadoras", "https://www.efe.com.pe/computadoras.html"),
]
PAGINAS_POR_CATEGORIA = 5
MAX_WORKERS           = 1   # MÍNIMO: una petición a la vez

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}
# ─────────────────────────────────────────────────────────────────────────────


def _armar_producto(nombre: str, marca: str, categoria: str,
                    val_regular: float, val_online: float, enlace: str) -> dict:
    """Construye el dict del producto con el contrato del proyecto."""
    if val_regular == 0:
        val_regular = val_online
    return {
        'id':            enlace.split('/')[-1].split('.')[0] if enlace else "",
        'nombre':        nombre,
        'marca':         marca,
        'categoria':     categoria,
        'precio_normal': val_regular if val_regular > 0 else None,
        'precio_oferta': val_online  if val_online  > 0 else None,
        'url':           enlace,
    }


def _procesar_pagina(tarea: tuple) -> list:
    """Descarga y parsea una página Magento de EFE. Retorna lista de productos."""
    categoria, url_base, pagina = tarea
    parsed     = urlparse(url_base)
    url_pagina = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?p={pagina}"

    print(f"  📡 [EFE/{categoria}] p{pagina}")

    try:
        r = requests.get(url_pagina, headers=HEADERS, timeout=15)
    except Exception as e:
        print(f"  ⚠️  [{categoria}] p{pagina} — Error de conexión: {e}")
        return []

    if r.status_code != 200:
        if r.status_code != 404:
            print(f"  ❌ [{categoria}] p{pagina} — HTTP {r.status_code}")
        return []

    soup  = BeautifulSoup(r.text, 'html.parser')
    items = soup.select('li.product-item')

    if not items:
        return []

    productos = []
    for item in items:
        el_link = item.select_one('a.product-item-link')
        if not el_link:
            continue

        nombre = el_link.text.strip()
        enlace = el_link.get('href', '')

        # Marca (puede estar en 'strong.product-item-brand' o similar)
        el_marca = item.select_one('.product-item-brand, .brand, strong.brand')
        marca = el_marca.text.strip() if el_marca else ""

        # Precio con descuento (special-price) o precio normal
        el_oferta   = item.select_one(
            'span.special-price span.price-wrapper[data-price-type="finalPrice"]'
        )
        el_regular  = item.select_one(
            'span.old-price span.price-wrapper[data-price-type="oldPrice"]'
        )
        if not el_oferta:
            el_oferta = item.select_one(
                'span.price-wrapper[data-price-type="finalPrice"]'
            )

        # data-price-amount puede venir vacío (''): `or 0` evita float('') → ValueError
        val_online  = float(el_oferta.get('data-price-amount')  or 0) if el_oferta  else 0.0
        val_regular = float(el_regular.get('data-price-amount') or 0) if el_regular else 0.0

        productos.append(_armar_producto(nombre, marca, categoria, val_regular, val_online, enlace))

    print(f"  ✅ [EFE/{categoria}] p{pagina} → {len(productos)} productos")
    return productos


def main() -> list:
    """
    Ejecuta el scraping de EFE y retorna la lista de productos.
    Guarda un JSON en tiendas/efe/datos/ con timestamp.
    """
    print("=" * 60)
    print("  EFE SCRAPER — Multi-categoría · Paralelo · Magento")
    print("=" * 60)

    tareas = [
        (cat, url, pag)
        for cat, url in CATEGORIAS_URLS
        for pag in range(1, PAGINAS_POR_CATEGORIA + 1)
    ]
    print(f"  Categorías: {len(CATEGORIAS_URLS)} | "
          f"Páginas/cat: {PAGINAS_POR_CATEGORIA} | "
          f"Total consultas: {len(tareas)}\n")

    todos = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for resultado in executor.map(_procesar_pagina, tareas):
            todos.extend(resultado)

    # Guardar JSON
    if todos:
        ahora     = datetime.now(TZ_PERU)
        fecha_tag = ahora.strftime("%Y-%m-%d_%H%M%S")
        datos_dir = os.path.join(os.path.dirname(__file__), "datos")
        os.makedirs(datos_dir, exist_ok=True)
        json_path = os.path.join(datos_dir, f"efe_{fecha_tag}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(todos, f, ensure_ascii=False, indent=2)
        print(f"\n💾 JSON → {json_path}  ({len(todos)} productos)")
    else:
        print("\n⚠️  No se obtuvieron datos.")

    print(f"\n{'=' * 60}")
    print(f"  ✅ EFE — {len(todos)} productos obtenidos en total.")
    print(f"{'=' * 60}")
    print("\n🎉 ¡Listo!")
    return todos


if __name__ == "__main__":
    main()
