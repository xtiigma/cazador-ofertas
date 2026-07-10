"""
Sodimac Perú — Scraper Multi-categoría.
Adaptado al proyecto Cazador de Ofertas.

Tecnología: requests + BeautifulSoup (HTML estático)
Sitio:      https://www.sodimac.com.pe
"""

import json
import os
import time
import concurrent.futures
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

# ── Configuración ─────────────────────────────────────────────────────────────
CATEGORIAS_URLS = [
    ("Electrohogar",  "https://www.sodimac.com.pe/sodimac-pe/lista/cat40584/Electrohogar"),
    ("Muebles",       "https://www.sodimac.com.pe/sodimac-pe/lista/cat40700/Muebles"),
    ("Herramientas",  "https://www.sodimac.com.pe/sodimac-pe/lista/cat40024/Herramientas"),
    ("Iluminacion",   "https://www.sodimac.com.pe/sodimac-pe/lista/cat40025/Iluminacion"),
    ("Jardin",        "https://www.sodimac.com.pe/sodimac-pe/lista/cat40031/Jardin"),
]
PAGINAS_POR_CATEGORIA = 3
DOMINIO_BASE          = "https://www.sodimac.com.pe"
MAX_WORKERS           = 1   # MÍNIMO: una petición a la vez (Sodimac bloquea fácil)
DELAY_ENTRE_PAGINAS   = 1.0 # segundos de espera entre páginas (anti-ban)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'es-PE,es;q=0.9',
}
# ─────────────────────────────────────────────────────────────────────────────


def _precio_float(texto: str) -> float:
    if not texto or texto == "0":
        return 0.0
    try:
        return float(texto.replace(',', '').strip())
    except ValueError:
        return 0.0


def _procesar_pagina(tarea: tuple) -> list:
    """Descarga y parsea una página de listado de Sodimac. Retorna productos."""
    categoria, url_base, pagina = tarea
    url = f"{url_base}?currentpage={pagina}"

    time.sleep(DELAY_ENTRE_PAGINAS)

    print(f"  📡 [Sodimac/{categoria}] p{pagina}")

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        print(f"  ⚠️  [{categoria}] p{pagina} — Error de conexión: {e}")
        return []

    if r.status_code == 403:
        print(f"  🚫 [{categoria}] p{pagina} — Acceso bloqueado (403). Reintentando...")
        time.sleep(5)
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
        except Exception:
            return []

    if r.status_code != 200:
        if r.status_code != 404:
            print(f"  ❌ [{categoria}] p{pagina} — HTTP {r.status_code}")
        return []

    soup    = BeautifulSoup(r.text, 'html.parser')
    tarjetas = soup.select('a[class*="pod-link"]')

    if not tarjetas:
        return []

    productos = []
    for tarjeta in tarjetas:
        el_titulo = tarjeta.select_one('b[class*="pod-subTitle"]')
        if not el_titulo:
            continue
        nombre = el_titulo.text.strip()

        # ID y enlace
        data_key = tarjeta.get('data-key')
        href     = tarjeta.get('href', '')
        if data_key:
            enlace  = f"{DOMINIO_BASE}/sodimac-pe/articulo/{data_key}"
            prod_id = data_key
        elif href and len(href) > 2:
            enlace  = href if href.startswith('http') else DOMINIO_BASE + href.split('?')[0]
            prod_id = href.split('/')[-1].split('?')[0]
        else:
            enlace  = ""
            prod_id = ""

        # Precios (CMR = precio especial, Internet = precio regular)
        li_cmr      = tarjeta.select_one('li[data-cmr-price]')
        li_internet = tarjeta.select_one('li[data-internet-price]')

        precio_cmr_txt      = li_cmr['data-cmr-price']      if li_cmr      else "0"
        precio_internet_txt = li_internet['data-internet-price'] if li_internet else "0"

        if li_cmr:
            val_oferta   = _precio_float(precio_cmr_txt)
            val_habitual = _precio_float(precio_internet_txt)
        else:
            val_oferta   = _precio_float(precio_internet_txt)
            val_habitual = 0.0

        # Si no hay precio habitual (sin descuento), igualar
        if val_habitual == 0:
            val_habitual = val_oferta

        productos.append({
            'id':            prod_id,
            'nombre':        nombre,
            'marca':         "",
            'categoria':     categoria,
            'precio_normal': val_habitual if val_habitual > 0 else None,
            'precio_oferta': val_oferta   if val_oferta   > 0 else None,
            'url':           enlace,
        })

    print(f"  ✅ [Sodimac/{categoria}] p{pagina} → {len(productos)} productos")
    return productos


def main() -> list:
    """
    Ejecuta el scraping de Sodimac Perú y retorna la lista de productos.
    Guarda un JSON en tiendas/sodimac/datos/ con timestamp.
    """
    print("=" * 60)
    print("  SODIMAC PERÚ — Multi-categoría · Paralelo")
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
        json_path = os.path.join(datos_dir, f"sodimac_{fecha_tag}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(todos, f, ensure_ascii=False, indent=2)
        print(f"\n💾 JSON → {json_path}  ({len(todos)} productos)")
    else:
        print("\n⚠️  No se obtuvieron datos.")

    print(f"\n{'=' * 60}")
    print(f"  ✅ SODIMAC — {len(todos)} productos obtenidos en total.")
    print(f"{'=' * 60}")
    print("\n🎉 ¡Listo!")
    return todos


if __name__ == "__main__":
    main()
