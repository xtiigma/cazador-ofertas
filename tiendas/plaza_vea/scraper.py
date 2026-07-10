"""
Plaza Vea Scraper — Sub-subcategorias (hojas) · Concurrente · v4
Fecha: 2026-04-14

ESTRATEGIA:
  En lugar de scrapeaar categorias padre (limite VTEX 2500 prods/consulta),
  scrapeamos directamente las sub-subcategorias hoja del arbol de categorias.
  Cada hoja tiene pocos productos → nunca se toca el limite de 2500.
  Con 309 hojas independientes se cubre el catalogo real completo.

FUENTE DE CATEGORIAS:
  Carga automaticamente backup/categorias.json (generado desde el browser).
  Si no existe, cae back a las categorias raiz originales.

DEDUPLICACION:
  Se deduplicân los productos por productId al final.
  Un mismo producto puede aparecer en subcategoria tronco y hoja.

Dependencias: pip install requests
"""

import requests
import json
import os
import time
import random
import threading
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

TZ_PERU = timezone(timedelta(hours=-5))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

BASE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.plazavea.com.pe/",
    "Origin": "https://www.plazavea.com.pe",
    "Connection": "keep-alive",
}

CATEGORIAS_FALLBACK = {
    "Tecnologia":         "https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/678/&O=OrderByScoreDESC&_from={from}&_to={to}",
    "ElectroHogar":       "https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/679/&O=OrderByScoreDESC&_from={from}&_to={to}",
    "Muebles":            "https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/1098/&O=OrderByScoreDESC&_from={from}&_to={to}",
    "Dormitorio":         "https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/1409/&O=OrderByScoreDESC&_from={from}&_to={to}",
    "Deportes":           "https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/1105/&O=OrderByScoreDESC&_from={from}&_to={to}",
    "Moda-Hombre":        "https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/3174/&O=OrderByScoreDESC&_from={from}&_to={to}",
    "Zapatillas":         "https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/3072/&O=OrderByScoreDESC&_from={from}&_to={to}",
    "Belleza":            "https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/1138/&O=OrderByScoreDESC&_from={from}&_to={to}",
    "Mascotas":           "https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/620/&O=OrderByScoreDESC&_from={from}&_to={to}",
    "Libreria-y-oficina": "https://www.plazavea.com.pe/api/catalog_system/pub/products/search?fq=C:/666/&O=OrderByScoreDESC&_from={from}&_to={to}",
}

BATCH_SIZE      = 50
MAX_PAGINAS_CAT = 3      # tope global de 3 págs/hoja (decisión del usuario
                         # 2026-07-09, meta térmica): hasta 150 prods/hoja, los mejor
                         # rankeados. La mayoría de hojas son más chicas y no lo
                         # tocan; recorta solo las gigantes (antes llegaban a ~51
                         # págs contra el límite VTEX de 2500) → menos peticiones,
                         # menos 429 y ciclo más corto.
MAX_REINTENTOS  = 4
MAX_WORKERS     = 1      # MINIMO: una peticion a la vez. El catalogo completo tarda
                         # ~90-120 min; main.py le da timeout_min=150 a esta tienda.
TIMEOUT         = (5, 20)

_print_lock = threading.Lock()
_data_lock  = threading.Lock()


def log(msg):
    ts = datetime.now(TZ_PERU).strftime("%H:%M:%S")
    with _print_lock:
        print(f"[{ts}] {msg}")


# ── Carga y aplanamiento del arbol de categorias ─────────────────────────────
def construir_nodo(nombre_cat, nombre_sub, nombre_leaf, url_template):
    """Devuelve un dict con la informacion de un nodo hoja."""
    return {
        "categoria":      nombre_cat,
        "subcategoria":   nombre_sub,
        "leaf":           nombre_leaf,
        "label":          f"{nombre_cat} > {nombre_sub} > {nombre_leaf}" if nombre_leaf != nombre_sub else f"{nombre_cat} > {nombre_sub}",
        "url_template":   url_template,
    }


def cargar_hojas():
    """
    Lee backup/categorias.json y extrae los nodos hoja del arbol.
    Un nodo es hoja si no tiene sub-subcategorias, o si sus hijos son las
    sub-subcategorias (nivel 3).
    Devuelve lista de dicts con {categoria, subcategoria, leaf, label, url_template}.
    """
    json_path = os.path.join(os.path.dirname(__file__), "backup", "categorias.json")

    if not os.path.exists(json_path):
        log("  AVISO: backup/categorias.json no encontrado. Usando categorias raiz.")
        return [
            construir_nodo(nombre, nombre, nombre, url)
            for nombre, url in CATEGORIAS_FALLBACK.items()
        ]

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    hojas = []
    # Filtrar nombres de categorias que claramente no se deben usar
    skip_keywords = ["NO USAR", "no usar"]

    for cat in data.get("categorias", []):
        nombre_cat = cat["nombre"]

        for sub in cat.get("subcategorias", []):
            nombre_sub = sub["nombre"]

            # Saltar subcategorias marcadas como no usar
            if any(kw in nombre_sub for kw in skip_keywords):
                continue

            sub_subs = sub.get("subcategorias", [])

            if sub_subs:
                # Tiene sub-subcategorias → scrapeamos cada una (nivel hoja)
                for leaf in sub_subs:
                    nombre_leaf = leaf["nombre"]
                    if any(kw in nombre_leaf for kw in skip_keywords):
                        continue
                    hojas.append(construir_nodo(nombre_cat, nombre_sub, nombre_leaf, leaf["url"]))
            else:
                # Subcategoria sin hijos → ella misma es hoja
                hojas.append(construir_nodo(nombre_cat, nombre_sub, nombre_sub, sub["url"]))

    log(f"  Arbol cargado: {len(hojas)} nodos hoja para scrapeaar.")
    return hojas


def get_headers():
    h = BASE_HEADERS.copy()
    h["User-Agent"] = random.choice(USER_AGENTS)
    return h


# ── Fetch con backoff ─────────────────────────────────────────────────────────
def obtener_pagina(session, url, label, desde):
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            resp = session.get(url, headers=get_headers(), timeout=TIMEOUT)

            if resp.status_code == 400:
                log(f"  [400] Limite VTEX en {label} (desde={desde}). Fin de catalogo.")
                return []

            if resp.status_code == 403:
                log(f"  [403] Bloqueado en {label}. Abortando.")
                return None

            if resp.status_code == 429:
                wait = min(90, 15 * (2 ** (intento - 1))) + random.uniform(0, 5)
                log(f"  [429] Rate limit en {label}. Esperando {wait:.1f}s...")
                time.sleep(wait)
                continue

            if resp.status_code == 404:
                log(f"  [404] No encontrado: {label}.")
                return None

            if resp.status_code >= 500:
                time.sleep(5 * intento)
                continue

            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict):
                return None

            return data

        except requests.exceptions.Timeout:
            time.sleep(3 * intento + random.uniform(0, 2))
        except requests.exceptions.ConnectionError:
            time.sleep(4 * intento)
        except ValueError:
            return None
        except Exception as e:
            log(f"  Error inesperado en {label}: {e}")
            return None

    return []


def extraer_precio(prod, campo):
    try:
        return float(prod["items"][0]["sellers"][0]["commertialOffer"][campo])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


# ── Scraping de un nodo hoja ──────────────────────────────────────────────────
def scrape_hoja(nodo, stats):
    """
    Pagina una subcategoria hoja hasta agotar su catalogo.
    Como son hojas pequeñas, rara vez toca el limite de 2500.
    """
    label        = nodo["label"]
    url_template = nodo["url_template"]
    registros    = []
    errores      = 0
    pagina       = 0

    with requests.Session() as session:
        while pagina < MAX_PAGINAS_CAT:
            desde = pagina * BATCH_SIZE
            hasta = desde + BATCH_SIZE - 1

            url      = url_template.replace("{from}", str(desde)).replace("{to}", str(hasta))
            productos = obtener_pagina(session, url, label, desde)

            if productos is None:
                errores += 1
                break

            if len(productos) == 0:
                break

            for prod in productos:
                try:
                    registros.append({
                        "id":            prod.get("productId", ""),
                        "nombre":        prod.get("productName", "Sin nombre"),
                        "marca":         prod.get("brand", ""),
                        "categoria":     nodo["categoria"],
                        "subcategoria":  nodo["subcategoria"],
                        "leaf":          nodo["leaf"],
                        "precio_normal": extraer_precio(prod, "ListPrice"),
                        "precio_oferta": extraer_precio(prod, "Price"),
                        "url":           prod.get("link", ""),
                    })
                except Exception as e:
                    errores += 1

            if len(productos) < BATCH_SIZE:
                break

            pagina += 1
            time.sleep(random.uniform(0.25, 0.6))

    con_descuento = sum(
        1 for r in registros
        if r["precio_normal"] and r["precio_oferta"] and r["precio_normal"] > r["precio_oferta"]
    )

    with _data_lock:
        stats[label] = {
            "paginas":       pagina + (1 if registros else 0),
            "total":         len(registros),
            "con_descuento": con_descuento,
            "errores":       errores,
        }

    if registros:
        log(f"  OK {label}: {len(registros)} prods, {con_descuento} desc")

    return registros


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "=" * 70)
    print("  PLAZA VEA SCRAPER — Hojas de subcategoria · Concurrente · v4")
    print(f"  Batch={BATCH_SIZE} · Workers={MAX_WORKERS}")
    print("=" * 70 + "\n")

    inicio = time.perf_counter()

    # Cargar arbol de categorias
    hojas = cargar_hojas()
    print(f"  Hojas a scrapeaar: {len(hojas)}\n")

    todos  = {}   # productId -> registro (deduplicacion global)
    stats  = {}

    datos_dir = os.path.join(os.path.dirname(__file__), "datos")
    os.makedirs(datos_dir, exist_ok=True)

    # Scrapeaar en paralelo
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = {
            executor.submit(scrape_hoja, nodo, stats): nodo["label"]
            for nodo in hojas
        }
        completados = 0
        for futuro in as_completed(futuros):
            label = futuros[futuro]
            completados += 1
            try:
                registros = futuro.result()
                with _data_lock:
                    for r in registros:
                        pid = r.get("id", "")
                        if pid and pid not in todos:
                            todos[pid] = r
                        elif not pid:
                            # Sin ID: guardar igual (no deduplicar)
                            todos[f"_noid_{len(todos)}"] = r

                with _print_lock:
                    print(f"  [{completados:>3}/{len(hojas)}] {label}", end="\r")

            except Exception as e:
                log(f"  Error critico en {label}: {e}")

    print()  # salto de linea tras el \r

    registros_finales = list(todos.values())

    # Guardar JSON unico con el formato exacto del proyecto
    ahora      = datetime.now(TZ_PERU)
    fecha_hora = ahora.strftime("%Y-%m-%d_%H%M%S")
    json_path  = os.path.join(datos_dir, f"plaza_vea_{fecha_hora}.json")

    if registros_finales:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(registros_finales, f, ensure_ascii=False, indent=2)

    # Resumen por categoria principal (agrupado)
    por_cat = {}
    for s_label, s in stats.items():
        cat = s_label.split(" > ")[0]
        if cat not in por_cat:
            por_cat[cat] = {"hojas": 0, "total": 0, "con_descuento": 0, "errores": 0}
        por_cat[cat]["hojas"]         += 1
        por_cat[cat]["total"]         += s["total"]
        por_cat[cat]["con_descuento"] += s["con_descuento"]
        por_cat[cat]["errores"]       += s["errores"]

    duracion = time.perf_counter() - inicio
    print("\n" + "-" * 75)
    print(f"  RESUMEN FINAL — {duracion:.1f}s totales · {len(hojas)} hojas")
    print("-" * 75)
    print(f"  {'Categoria':<22} {'Hojas':>6} {'Productos':>10} {'Desc.':>7} {'Errores':>8}")
    print(f"  {'-'*22} {'-'*6} {'-'*10} {'-'*7} {'-'*8}")

    for cat, s in sorted(por_cat.items(), key=lambda x: x[1]["total"], reverse=True):
        print(f"  {cat:<22} {s['hojas']:>6} {s['total']:>10} {s['con_descuento']:>7} {s['errores']:>8}")

    print("-" * 75)
    tt = sum(s["total"]         for s in por_cat.values())
    td = sum(s["con_descuento"] for s in por_cat.values())
    te = sum(s["errores"]       for s in por_cat.values())
    th = sum(s["hojas"]         for s in por_cat.values())
    print(f"  {'TOTAL (sin dedup)':<22} {th:>6} {tt:>10} {td:>7} {te:>8}")
    print(f"  {'UNICOS (dedup ID)':<22} {'':>6} {len(registros_finales):>10}")
    print("-" * 75)

    if registros_finales:
        print(f"\n  JSON -> {os.path.basename(json_path)}  ({len(registros_finales)} productos unicos)")
    else:
        print("\n  No se obtuvieron datos.")

    print("\n  Listo!\n")
    return registros_finales


if __name__ == "__main__":
    main()