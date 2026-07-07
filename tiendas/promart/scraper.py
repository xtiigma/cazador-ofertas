"""
Promart Scraper — Categorías raíz · Rápido con progreso en vivo
Estrategia: OrderByScoreDESC ya pone los mejores/descuentos primero.
Solo tomamos las primeras PAGINAS_POR_CAT páginas de cada categoría raíz.
"""

import requests
import requests.adapters
import json
import os
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/147.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

BASE_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "es-US,es-419;q=0.9,es;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Referer": "https://www.promart.pe/",
    "Origin": "https://www.promart.pe",
    "Connection": "keep-alive",
}

# ── Categorías raíz — solo estas, ya ordenadas por relevancia/descuento ───────
CATEGORIAS = [
    ("Tecnologia",   "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=C:/804/&O=OrderByScoreDESC&_from={from}&_to={to}"),
    ("Muebles",      "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=C:/890/&O=OrderByScoreDESC&_from={from}&_to={to}"),
    ("Electrohogar", "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=C:/599/&O=OrderByScoreDESC&_from={from}&_to={to}"),
    ("Limpieza",     "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=C:/20/&O=OrderByScoreDESC&_from={from}&_to={to}"),
    ("Baño",         "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=C:/687/&O=OrderByScoreDESC&_from={from}&_to={to}"),
    ("Decoracion",   "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=H:2458&O=OrderByScoreDESC&_from={from}&_to={to}"),
    ("Electricidad", "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=C:/653/&O=OrderByScoreDESC&_from={from}&_to={to}"),
    ("Salud",        "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=H:2705&O=OrderByScoreDESC&_from={from}&_to={to}"),
    ("Oficina",      "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=C:/1286/&O=OrderByScoreDESC&_from={from}&_to={to}"),
    ("Cocina",       "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=C:/688/&O=OrderByScoreDESC&_from={from}&_to={to}"),
    ("Dormitorio",   "https://www.promart.pe/api/catalog_system/pub/products/search/?isAvailablePerSalesChannel_2:1&sc=2&fq=C:/1075/&O=OrderByScoreDESC&_from={from}&_to={to}"),
]

# ── Parámetros ajustables ─────────────────────────────────────────────────────
BATCH_SIZE        = 48   # ítems por página VTEX
PAGINAS_POR_CAT   = 54   # páginas por categoría → hasta 2592 prods/cat (límite VTEX ~2500)
MAX_WORKERS       = 1    # MÍNIMO: una petición a la vez (amable con el API y la mini PC)
MAX_REINTENTOS    = 3
TIMEOUT           = (5, 20)
# ─────────────────────────────────────────────────────────────────────────────

_print_lock  = threading.Lock()
_data_lock   = threading.Lock()
_progress    = {"completadas": 0, "total": 0, "prods": 0, "actual": ""}


def _barra(n: int, total: int, ancho: int = 28) -> str:
    pct   = n / total if total else 0
    lleno = int(ancho * pct)
    return f"[{'█' * lleno}{'░' * (ancho - lleno)}] {pct*100:5.1f}%"


def _mostrar_progreso(inicio: float) -> None:
    """Imprime la línea de progreso en vivo (sobreescribe con \\r)."""
    p   = _progress
    n   = p["completadas"]
    tot = p["total"]
    elapsed = time.time() - inicio
    eta = (elapsed / n * (tot - n)) if n > 0 else 0
    mm, ss = divmod(int(eta), 60)
    linea = (
        f"  {_barra(n, tot)}  "
        f"{n}/{tot} cat  │  {p['prods']:,} prods  │  "
        f"ETA {mm:02d}:{ss:02d}  │  {p['actual']:<14}"
    )
    with _print_lock:
        print(f"\r{linea}", end="", flush=True)


def get_headers() -> dict:
    h = BASE_HEADERS.copy()
    h["User-Agent"] = random.choice(USER_AGENTS)
    return h


def obtener_pagina(session: requests.Session, url: str, nombre: str, desde: int):
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            resp = session.get(url, headers=get_headers(), timeout=TIMEOUT)
            if resp.status_code == 400:
                return []
            if resp.status_code == 403:
                return None
            if resp.status_code == 429:
                time.sleep(min(60, 10 * intento) + random.uniform(0, 3))
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code >= 500:
                time.sleep(4 * intento)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else None
        except requests.exceptions.Timeout:
            time.sleep(3 * intento)
        except requests.exceptions.ConnectionError:
            time.sleep(4 * intento)
        except Exception:
            return None
    return []


def extraer_precio(prod: dict, campo: str):
    try:
        return float(prod["items"][0]["sellers"][0]["commertialOffer"][campo])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def scrape_categoria(nombre: str, url_tpl: str, session: requests.Session) -> list:
    """Scrapea todas las páginas (hasta PAGINAS_POR_CAT) de una categoría."""
    registros = []

    for pagina in range(PAGINAS_POR_CAT):
        desde = pagina * BATCH_SIZE
        hasta = desde + BATCH_SIZE - 1
        url   = url_tpl.replace("{from}", str(desde)).replace("{to}", str(hasta))

        productos = obtener_pagina(session, url, nombre, desde)

        if not productos:
            break

        for prod in productos:
            try:
                pid = prod.get("productId", "")
                if not pid:
                    continue

                p_normal = extraer_precio(prod, "ListPrice")
                p_oferta = extraer_precio(prod, "Price")
                if p_oferta == 0:
                    p_oferta = None
                if p_normal == 0:
                    p_normal = p_oferta

                img = ""
                try:
                    img = prod["items"][0]["images"][0]["imageUrl"]
                except (KeyError, IndexError):
                    pass

                registros.append({
                    "id":            pid,
                    "nombre":        prod.get("productName", "Sin nombre"),
                    "marca":         prod.get("brand", ""),
                    "categoria":     nombre,
                    "subcategoria":  nombre,
                    "leaf":          nombre,
                    "precio_normal": p_normal,
                    "precio_oferta": p_oferta,
                    "imagen":        img,
                    "url":           prod.get("link", ""),
                })
            except Exception:
                pass

        if len(productos) < BATCH_SIZE:
            break  # Última página

    return registros


def _worker_categoria(args):
    """Wrapper para ThreadPoolExecutor: scrapea una categoría y actualiza progreso."""
    nombre, url_tpl, adapter, inicio = args

    with _data_lock:
        _progress["actual"] = nombre

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://",  adapter)

    t0 = time.time()
    try:
        registros = scrape_categoria(nombre, url_tpl, session)
    finally:
        session.close()

    con_desc = sum(
        1 for r in registros
        if r["precio_normal"] and r["precio_oferta"] and r["precio_normal"] > r["precio_oferta"]
    )
    dur = time.time() - t0

    with _data_lock:
        _progress["completadas"] += 1
        _progress["prods"]       += len(registros)

    _mostrar_progreso(inicio)

    with _print_lock:
        pct_desc = f"{con_desc/len(registros)*100:.0f}%" if registros else "0%"
        print(f"\n  ✓  {nombre:<14} {len(registros):>4} prods  ·  {con_desc:>4} con desc ({pct_desc})  ·  {dur:.1f}s")

    return nombre, registros


def main() -> list:
    total_cat   = len(CATEGORIAS)
    total_pages = total_cat * PAGINAS_POR_CAT

    print("\n" + "═" * 68, flush=True)
    print("  PROMART SCRAPER — Categorías raíz · Progreso en vivo", flush=True)
    print(f"  {total_cat} categorías  ·  hasta {PAGINAS_POR_CAT} págs/cat  ·  "
          f"{MAX_WORKERS} workers  ·  ~{PAGINAS_POR_CAT * BATCH_SIZE} prods/cat", flush=True)
    print("═" * 68 + "\n", flush=True)

    _progress["total"]       = total_cat
    _progress["completadas"] = 0
    _progress["prods"]       = 0
    _progress["actual"]      = ""

    inicio = time.time()

    # Pool HTTP compartido entre todos los workers
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=MAX_WORKERS,
        pool_maxsize=MAX_WORKERS * 2,
        max_retries=0,
    )

    args_list = [(nombre, url, adapter, inicio) for nombre, url in CATEGORIAS]

    todos: dict = {}
    resumen: list = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = {executor.submit(_worker_categoria, a): a[0] for a in args_list}
        for futuro in as_completed(futuros):
            try:
                nombre, registros = futuro.result()
                resumen.append((nombre, len(registros)))
                with _data_lock:
                    for r in registros:
                        pid = r["id"]
                        if pid and pid not in todos:
                            todos[pid] = r
            except Exception as e:
                with _print_lock:
                    print(f"\n  ✗  Error en {futuros[futuro]}: {e}")

    print()
    registros_finales = list(todos.values())

    # Guardar JSON
    datos_dir = os.path.join(os.path.dirname(__file__), "datos")
    os.makedirs(datos_dir, exist_ok=True)
    ahora     = datetime.now(TZ_PERU)
    json_path = os.path.join(datos_dir, f"promart_{ahora.strftime('%Y-%m-%d_%H%M%S')}.json")

    if registros_finales:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(registros_finales, f, ensure_ascii=False)

    duracion = time.time() - inicio
    mm, ss   = divmod(int(duracion), 60)
    con_desc_total = sum(
        1 for r in registros_finales
        if r["precio_normal"] and r["precio_oferta"] and r["precio_normal"] > r["precio_oferta"]
    )

    print("═" * 68)
    print(f"  ✅ Completado en {mm:02d}:{ss:02d}  ·  {len(registros_finales):,} productos únicos  ·  {con_desc_total:,} con descuento")
    print(f"  📁 JSON → {os.path.basename(json_path)}")
    print("═" * 68 + "\n")

    return registros_finales


if __name__ == "__main__":
    main()
