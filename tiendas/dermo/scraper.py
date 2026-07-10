"""
Dermo Tienda Shopping — Scraper Multi-categoría.
Adaptado al proyecto Cazador de Ofertas.

Tecnología: requests + BeautifulSoup (HTML estático)
Sitio:      https://dermotiendashopping.com  (Shopify)
"""

import json
import os
import hashlib
import concurrent.futures
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

# ── Configuración ─────────────────────────────────────────────────────────────
SECCIONES_A_ANALIZAR = [
    ("Bloqueadores", "https://dermotiendashopping.com/collections/bloqueadores"),
    ("Antiedad",     "https://dermotiendashopping.com/collections/antiedad"),
    ("Hidratantes",  "https://dermotiendashopping.com/collections/hidratantes"),
    ("Acne",         "https://dermotiendashopping.com/collections/acne"),
    ("Contorno-Ojos","https://dermotiendashopping.com/collections/contorno-ojos"),
]
PAGINAS_POR_SECCION = 3
DOMINIO_BASE        = "https://dermotiendashopping.com"
MAX_WORKERS         = 1   # MÍNIMO: una petición a la vez

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    )
}
# ─────────────────────────────────────────────────────────────────────────────


def _precio_float(texto: str) -> float:
    """Convierte 'S/.149.90' o '149.90' a float."""
    if not texto:
        return 0.0
    try:
        return float(texto.replace('S/.', '').replace('S/', '').replace(',', '').strip())
    except ValueError:
        return 0.0


def _hacer_id(nombre: str, enlace: str) -> str:
    """Genera un ID reproducible a partir del nombre + enlace."""
    raw = (nombre + enlace).encode()
    return hashlib.md5(raw).hexdigest()[:12]


def _procesar_pagina(tarea: tuple) -> list:
    """Descarga y parsea una página de colección. Retorna lista de productos."""
    categoria, url_base, pagina = tarea
    url = f"{url_base}?page={pagina}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        print(f"  ⚠️  [{categoria}] p{pagina} — Error de conexión: {e}")
        return []

    if resp.status_code == 404:
        return []          # página vacía, ignorar silenciosamente
    if resp.status_code != 200:
        print(f"  ❌ [{categoria}] p{pagina} — HTTP {resp.status_code}")
        return []

    soup = BeautifulSoup(resp.text, 'html.parser')
    tarjetas = soup.select('product-card.product-card')

    if not tarjetas:
        return []          # sin productos en esta página

    productos = []
    for tarjeta in tarjetas:
        # Título
        el_titulo = tarjeta.select_one('div[class*="product_title"] h2')
        if not el_titulo:
            continue
        nombre = el_titulo.text.strip()

        # Enlace
        el_enlace = tarjeta.select_one('a.product-card__link')
        enlace    = DOMINIO_BASE + el_enlace['href'] if el_enlace else ""

        # Precios
        span_oferta   = tarjeta.select_one('product-price span.price')
        span_habitual = tarjeta.select_one('product-price span.compare-at-price')

        val_oferta   = _precio_float(span_oferta.text   if span_oferta   else "0")
        val_habitual = _precio_float(span_habitual.text if span_habitual else "0")

        # Si no hay precio tachado, precio_normal = precio_oferta (sin descuento)
        if val_habitual == 0:
            val_habitual = val_oferta

        # Marca (Shopify no la suele mostrar en tarjeta; dejamos vacío)
        marca = ""

        # ID único
        prod_id = _hacer_id(nombre, enlace)

        productos.append({
            'id':            prod_id,
            'nombre':        nombre,
            'marca':         marca,
            'categoria':     categoria,
            'precio_normal': val_habitual if val_habitual > 0 else None,
            'precio_oferta': val_oferta   if val_oferta   > 0 else None,
            'url':           enlace,
        })

    print(f"  ✅ [{categoria}] p{pagina} → {len(productos)} productos")
    return productos


def main() -> list:
    """
    Ejecuta el scraping de Dermo Tienda Shopping y retorna la lista de productos.
    Guarda un JSON en tiendas/dermo/datos/ con timestamp.
    """
    print("=" * 60)
    print("  DERMO TIENDA SHOPPING — Multi-categoría · Paralelo")
    print("=" * 60)

    tareas = [
        (cat, url, pag)
        for cat, url in SECCIONES_A_ANALIZAR
        for pag in range(1, PAGINAS_POR_SECCION + 1)
    ]
    print(f"  Categorías: {len(SECCIONES_A_ANALIZAR)} | "
          f"Páginas/cat: {PAGINAS_POR_SECCION} | "
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
        json_path = os.path.join(datos_dir, f"dermo_{fecha_tag}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(todos, f, ensure_ascii=False, indent=2)
        print(f"\n💾 JSON → {json_path}  ({len(todos)} productos)")
    else:
        print("\n⚠️  No se obtuvieron datos.")

    print(f"\n{'=' * 60}")
    print(f"  ✅ DERMO — {len(todos)} productos obtenidos en total.")
    print(f"{'=' * 60}")
    print("\n🎉 ¡Listo!")
    return todos


if __name__ == "__main__":
    main()
