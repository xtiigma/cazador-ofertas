"""
Plaza Vea Scraper — Multi-categoría con reintentos.
Adaptado al proyecto Cazador de Ofertas: 2026-03-28

Instalar dependencias:
  pip install requests
"""

import requests
import json
import os
import time
import random
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

# ── Headers que simulan un navegador real ──────────────────────────────────────
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/123.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'es-PE,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.plazavea.com.pe/',
    'Origin': 'https://www.plazavea.com.pe',
    'Connection': 'keep-alive',
}

# ── URLs por categoría ─────────────────────────────────────────────────────────
CATEGORIAS_URLS = {
    'Tecnologia':         'https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/678/&O=OrderByScoreDESC&_from={}&_to={}',
    'ElectroHogar':       'https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/679/&O=OrderByScoreDESC&_from={}&_to={}',
    'Muebles':            'https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/1098/&O=OrderByScoreDESC&_from={}&_to={}',
    'Dormitorio':         'https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/1409/&O=OrderByScoreDESC&_from={}&_to={}',
    'Deportes':           'https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/1105/&O=OrderByScoreDESC&_from={}&_to={}',
    'Moda-Hombre':        'https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/3174/&O=OrderByScoreDESC&_from={}&_to={}',
    'Zapatillas':         'https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/3072/&O=OrderByScoreDESC&_from={}&_to={}',
    'Belleza':            'https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/1138/&O=OrderByScoreDESC&_from={}&_to={}',
    'Mascotas':           'https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/620/&O=OrderByScoreDESC&_from={}&_to={}',
    'Libreria-y-oficina': 'https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/666/&O=OrderByScoreDESC&_from={}&_to={}',
}

BATCH_SIZE     = 20   # productos por petición (máximo que acepta la API)
NUM_PAGINAS    = 20   # páginas por categoría
MAX_REINTENTOS = 3    # reintentos ante errores de red


# ── Función con reintentos ─────────────────────────────────────────────────────
def obtener_pagina(session, base_url, desde, hasta, categoria):
    url = base_url.format(desde, hasta)
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)

            if resp.status_code == 403:
                print(f'  [403] Acceso bloqueado en {categoria} (página {desde//BATCH_SIZE + 1}).')
                return None
            if resp.status_code == 429:
                wait = 30 * intento
                print(f'  [429] Rate limit. Esperando {wait}s antes de reintentar...')
                time.sleep(wait)
                continue
            if resp.status_code == 404:
                print(f'  [404] Endpoint no encontrado: {url}')
                return None

            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict):
                print(f'  Respuesta inesperada (dict): {str(data)[:200]}')
                return None

            return data

        except requests.exceptions.Timeout:
            print(f'  Timeout en intento {intento}/{MAX_REINTENTOS} — {url}')
        except requests.exceptions.ConnectionError as e:
            print(f'  Error de conexión en intento {intento}/{MAX_REINTENTOS}: {e}')
        except ValueError:
            print(f'  La respuesta no es JSON válido: {resp.text[:200]}')
            return None
        except Exception as e:
            print(f'  Error inesperado: {e}')
            return None

        time.sleep(2 * intento)

    print(f'  Máximos reintentos alcanzados para {url}')
    return None


# ── Extracción segura de precio ────────────────────────────────────────────────
def extraer_precio(producto, campo):
    try:
        return float(producto['items'][0]['sellers'][0]['commertialOffer'][campo])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    """Ejecuta el scraping de Plaza Vea y retorna la lista de productos."""
    print("=" * 60)
    print("  PLAZA VEA SCRAPER — Multi-categoría · Reintentos")
    print("=" * 60)

    registros = []

    with requests.Session() as session:
        for i, (categoria, base_url) in enumerate(CATEGORIAS_URLS.items(), 1):
            print(f'\n[{i}/{len(CATEGORIAS_URLS)}] ── {categoria.upper()} ──')
            productos_encontrados = 0

            for pagina in range(NUM_PAGINAS):
                desde = pagina * BATCH_SIZE
                hasta = desde + BATCH_SIZE - 1

                productos = obtener_pagina(session, base_url, desde, hasta, categoria)

                if productos is None:
                    print(f'  Deteniendo {categoria} por error.')
                    break
                if len(productos) == 0:
                    print(f'  Sin más productos en {categoria} (página {pagina + 1}).')
                    break

                for prod in productos:
                    try:
                        nombre       = prod.get('productName', 'Sin nombre')
                        enlace       = prod.get('link', '')
                        marca        = prod.get('brand', '')
                        producto_id  = prod.get('productId', '')
                        precio_lista = extraer_precio(prod, 'ListPrice')
                        precio_final = extraer_precio(prod, 'Price')

                        registros.append({
                            'id':             producto_id,
                            'nombre':         nombre,
                            'marca':          marca,
                            'categoria':      categoria,
                            'precio_normal':  precio_lista,
                            'precio_oferta':  precio_final,
                            'url':            enlace,
                        })
                        
                        if precio_lista and precio_final and precio_lista > precio_final:
                            productos_encontrados += 1

                    except Exception as e:
                        print(f'  Error al procesar producto: {e}')

                time.sleep(random.uniform(0.5, 1.5))

            print(f'  ✔ {productos_encontrados} productos con descuento encontrados.')

    # Guardar JSON con fecha y hora
    if registros:
        ahora = datetime.now(TZ_PERU)
        fecha_hora = ahora.strftime("%Y-%m-%d_%H%M%S")

        datos_dir = os.path.join(os.path.dirname(__file__), "datos")
        os.makedirs(datos_dir, exist_ok=True)

        json_path = os.path.join(datos_dir, f"plaza_vea_{fecha_hora}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(registros, f, ensure_ascii=False, indent=2)

        print(f'\n💾 JSON → {json_path}  ({len(registros)} productos)')
    else:
        print('\n⚠️  No se obtuvieron datos.')

    print("\n🎉 ¡Listo!")
    return registros


if __name__ == "__main__":
    main()
