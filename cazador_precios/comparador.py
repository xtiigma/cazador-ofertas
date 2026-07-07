"""
Cazador de Precios - Comparador Entre Tiendas
=============================================

Detecta productos que aparecen en mas de una tienda y compara
el precio historico registrado por NUESTRO propio sistema.

La tienda puede inflar precios y llamarlo "descuento", pero nosotros
comparamos lo que realmente pagaste o viste: nuestros propios registros.

Ejemplo:
    TV Samsung 55"
      Saga Falabella : min historico S/1,189 | promedio S/1,380
      Plaza Vea      : min historico S/1,299 | promedio S/1,450
      -> SAGA es mas barata (S/110 menos en el minimo historico)
"""

import json
import os
import re
import unicodedata
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

# ── Configuracion ────────────────────────────────────────────────────────────

# Similitud minima de nombre para considerar que es el mismo producto (0-1)
UMBRAL_SIMILITUD: float = 0.70

# Diferencia minima en % de precio para reportar como "mas barato"
UMBRAL_DIFERENCIA_PORCENT: float = 5.0

# Minimo de registros historicos para incluir un producto en la comparacion
MIN_REGISTROS: int = 2

# Palabras irrelevantes que se ignoran al comparar nombres
PALABRAS_IGNORAR = {
    "de", "la", "el", "los", "las", "un", "una", "y", "con", "para",
    "x", "gr", "g", "ml", "lt", "kg", "mg", "un", "und", "unid",
    "pack", "paq", "caja", "bolsa", "frasco", "tubo", "bote",
}

# ────────────────────────────────────────────────────────────────────────────


def _normalizar_nombre(nombre: str) -> set:
    """
    Normaliza un nombre de producto para comparacion:
    - Quita tildes y caracteres especiales
    - Convierte a minusculas
    - Extrae solo las palabras significativas (>= 3 letras, no en lista de ignorar)

    Retorna un set de palabras clave.
    """
    # Quitar tildes
    texto = unicodedata.normalize("NFD", nombre)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")

    # Minusculas y solo alfanumerico
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)

    palabras = set(texto.split())
    # Filtrar palabras cortas y palabras de la lista de ignorar
    palabras_clave = {p for p in palabras if len(p) >= 3 and p not in PALABRAS_IGNORAR}
    return palabras_clave


def _similitud(palabras_a: set, palabras_b: set) -> float:
    """
    Calcula similitud entre dos sets de palabras clave.
    Usa el indice de Jaccard: interseccion / union.
    """
    if not palabras_a or not palabras_b:
        return 0.0
    interseccion = len(palabras_a & palabras_b)
    union = len(palabras_a | palabras_b)
    return interseccion / union if union > 0 else 0.0


def _precio_minimo_historico(historial_producto: dict) -> float | None:
    """Obtiene el precio minimo historico de un producto."""
    registros = historial_producto.get("registros", [])
    precios = []
    for r in registros:
        p = r.get("precio_minimo") or r.get("precio_oferta") or r.get("precio_normal")
        if p and p > 0:
            precios.append(p)
    return min(precios) if precios else None


def _precio_promedio_historico(historial_producto: dict) -> float | None:
    """Obtiene el precio promedio historico de un producto."""
    registros = historial_producto.get("registros", [])
    precios = []
    for r in registros:
        p = r.get("precio_minimo") or r.get("precio_oferta") or r.get("precio_normal")
        if p and p > 0:
            precios.append(p)
    if not precios:
        return None
    return round(sum(precios) / len(precios), 2)


def _precio_actual(historial_producto: dict) -> float | None:
    """Obtiene el precio del ultimo registro."""
    registros = historial_producto.get("registros", [])
    if not registros:
        return None
    ultimo = registros[-1]
    return (
        ultimo.get("precio_minimo")
        or ultimo.get("precio_oferta")
        or ultimo.get("precio_normal")
    )


def _cargar_historial(ruta: str) -> dict:
    """Carga un historial JSON de forma segura."""
    if not os.path.exists(ruta):
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def comparar_entre_tiendas(historiales_por_tienda: dict) -> list:
    """
    Compara precios de productos entre todas las tiendas usando NUESTRO historial.

    Args:
        historiales_por_tienda: Dict con formato:
            {
                "Inkafarma": {pid: {nombre, registros, ...}, ...},
                "Plaza Vea":  {pid: {nombre, registros, ...}, ...},
                ...
            }

    Returns:
        Lista de dicts con productos que aparecen en mas de una tienda,
        ordenados por mayor diferencia de precio.
        [
            {
                "nombre_referencia": "TV Samsung 55 pulgadas",
                "tienda_mas_barata": "Saga Falabella",
                "precio_min_mas_barato": 1189.0,
                "tiendas": [
                    {
                        "nombre_tienda": "Saga Falabella",
                        "nombre_producto": "TV Samsung 55 IQ ...",
                        "precio_minimo": 1189.0,
                        "precio_promedio": 1380.0,
                        "precio_actual": 1250.0,
                        "num_registros": 3,
                        "url": "..."
                    },
                    ...
                ],
                "diferencia_porcent": 8.5,
                "ahorro_absoluto": 110.0,
            }
        ]
    """
    tiendas_nombres = list(historiales_por_tienda.keys())
    if len(tiendas_nombres) < 2:
        return []

    # ── Paso 1: Indexar todos los productos con sus palabras clave ───────────
    # { "Tienda": [(pid, palabras_clave, historial_prod), ...] }
    indice = {}
    for tienda, historial in historiales_por_tienda.items():
        productos_tienda = []
        for pid, data in historial.items():
            nombre = data.get("nombre", "")
            if not nombre:
                continue
            num_reg = len(data.get("registros", []))
            if num_reg < MIN_REGISTROS:
                continue
            palabras = _normalizar_nombre(nombre)
            if len(palabras) < 2:
                continue
            productos_tienda.append((pid, palabras, data))
        indice[tienda] = productos_tienda

    # ── Paso 2: Comparar cada producto de cada tienda contra las demas ───────
    comparaciones = []
    ya_procesados = set()  # Evitar duplicados

    for i, tienda_a in enumerate(tiendas_nombres):
        for tienda_b in tiendas_nombres[i + 1:]:
            prods_a = indice.get(tienda_a, [])
            prods_b = indice.get(tienda_b, [])

            for pid_a, palabras_a, data_a in prods_a:
                mejor_match = None
                mejor_similitud = 0.0

                for pid_b, palabras_b, data_b in prods_b:
                    sim = _similitud(palabras_a, palabras_b)
                    if sim > mejor_similitud:
                        mejor_similitud = sim
                        mejor_match = (pid_b, palabras_b, data_b, tienda_b)

                if mejor_similitud < UMBRAL_SIMILITUD or mejor_match is None:
                    continue

                pid_b, palabras_b, data_b, _ = mejor_match

                # Clave unica para evitar reportar el mismo par dos veces
                clave = tuple(sorted([f"{tienda_a}:{pid_a}", f"{tienda_b}:{pid_b}"]))
                if clave in ya_procesados:
                    continue
                ya_procesados.add(clave)

                # Calcular precios de ambos
                min_a = _precio_minimo_historico(data_a)
                min_b = _precio_minimo_historico(data_b)
                prom_a = _precio_promedio_historico(data_a)
                prom_b = _precio_promedio_historico(data_b)
                actual_a = _precio_actual(data_a)
                actual_b = _precio_actual(data_b)

                if not min_a or not min_b:
                    continue

                # Calcular diferencia %
                precio_mayor = max(min_a, min_b)
                precio_menor = min(min_a, min_b)
                diferencia_porcent = ((precio_mayor - precio_menor) / precio_mayor) * 100

                if diferencia_porcent < UMBRAL_DIFERENCIA_PORCENT:
                    continue  # Diferencia no es significativa

                # Determinar quien es mas barato
                if min_a <= min_b:
                    tienda_barata, tienda_cara = tienda_a, tienda_b
                    data_barata, data_cara = data_a, data_b
                    min_barata, min_cara = min_a, min_b
                    prom_barata, prom_cara = prom_a, prom_b
                    actual_barata, actual_cara = actual_a, actual_b
                else:
                    tienda_barata, tienda_cara = tienda_b, tienda_a
                    data_barata, data_cara = data_b, data_a
                    min_barata, min_cara = min_b, min_a
                    prom_barata, prom_cara = prom_b, prom_a
                    actual_barata, actual_cara = actual_b, actual_a

                # Usar el nombre mas corto como referencia
                nombre_ref = (
                    data_a.get("nombre", "")
                    if len(data_a.get("nombre", "")) <= len(data_b.get("nombre", ""))
                    else data_b.get("nombre", "")
                )

                comparaciones.append({
                    "nombre_referencia": nombre_ref,
                    "similitud": round(mejor_similitud, 2),
                    "tienda_mas_barata": tienda_barata,
                    "precio_min_mas_barato": round(min_barata, 2),
                    "diferencia_porcent": round(diferencia_porcent, 1),
                    "ahorro_absoluto": round(precio_mayor - precio_menor, 2),
                    "tiendas": [
                        {
                            "nombre_tienda": tienda_barata,
                            "nombre_producto": data_barata.get("nombre", "")[:70],
                            "precio_minimo": round(min_barata, 2),
                            "precio_promedio": round(prom_barata, 2) if prom_barata else None,
                            "precio_actual": round(actual_barata, 2) if actual_barata else None,
                            "num_registros": len(data_barata.get("registros", [])),
                            "url": data_barata.get("url", ""),
                        },
                        {
                            "nombre_tienda": tienda_cara,
                            "nombre_producto": data_cara.get("nombre", "")[:70],
                            "precio_minimo": round(min_cara, 2),
                            "precio_promedio": round(prom_cara, 2) if prom_cara else None,
                            "precio_actual": round(actual_cara, 2) if actual_cara else None,
                            "num_registros": len(data_cara.get("registros", [])),
                            "url": data_cara.get("url", ""),
                        },
                    ],
                })

    # Ordenar por mayor diferencia de precio
    comparaciones.sort(key=lambda x: x["diferencia_porcent"], reverse=True)

    # Resumen en consola
    if comparaciones:
        print(f"\n  [Comparador] Productos encontrados en mas de una tienda: {len(comparaciones)}")
        print(f"\n  [TOP] Top {min(5, len(comparaciones))} comparaciones mas relevantes:")
        for i, c in enumerate(comparaciones[:5], 1):
            print(f"     {i}. {c['nombre_referencia'][:55]}")
            print(f"        Mas barato en {c['tienda_mas_barata']}: S/{c['precio_min_mas_barato']} ({c['diferencia_porcent']}% menos)")
    else:
        print(f"\n  [i] [Comparador] Sin coincidencias entre tiendas con diferencia significativa")

    return comparaciones


def comparar_desde_rutas(tiendas_config: list) -> list:
    """
    Carga los historiales y ejecuta la comparacion.
    Funcion de conveniencia para usar desde main.py / analizar_ahora.py.

    Args:
        tiendas_config: Lista de dicts con claves "nombre" y "historial" (ruta JSON).
    """
    historiales = {}
    for tienda in tiendas_config:
        nombre = tienda["nombre"]
        ruta = tienda["historial"]
        historial = _cargar_historial(ruta)
        if historial:
            historiales[nombre] = historial
            print(f"  [i] [Comparador] {nombre}: {len(historial)} productos cargados")
        else:
            print(f"  [!] [Comparador] {nombre}: sin historial disponible")

    if len(historiales) < 2:
        print("  [!] [Comparador] Se necesitan al menos 2 tiendas con historial")
        return []

    return comparar_entre_tiendas(historiales)
