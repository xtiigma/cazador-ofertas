"""
Cazador de Precios Mínimos Históricos
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A diferencia del analizador (que lee el descuento que *la tienda dice tener*),
este módulo detecta precios bajos comparando el precio de HOY vs TODO
el historial acumulado por NUESTRO propio proyecto de scraping.

Ejemplo de lo que detecta:
    TV Samsung — Historial propio:
        2026-03-28: S/500   ← primer registro
        2026-03-29: S/650
        2026-04-01: S/650
        2026-04-05: S/650
        2026-04-12: S/300   ← HOY → ¡MÍNIMO HISTÓRICO! 🎯

La tienda puede no tener ningún "descuento" marcado, pero NOSOTROS sabemos
que S/300 es el precio más bajo que hemos registrado. Eso es una oportunidad.
"""

import json
import os
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))


# ── Configuración de umbrales ────────────────────────────────────────────────

# Mínimo de registros históricos para que el análisis sea confiable
MIN_REGISTROS_REQUERIDOS: int = 3

# % por debajo de la MEDIANA histórica para reportar como "precio bajo".
# Se usa la mediana (precio típico) y no el promedio: los días de precios
# inflados pre-evento (Cyber Wow) arrastran el promedio pero no la mediana.
UMBRAL_BAJO_VS_MEDIANA: float = 10.0    # Si está 10% o más bajo del típico → reportar

# % por debajo del mínimo histórico anterior para reportar como "nuevo mínimo"
UMBRAL_NUEVO_MINIMO: float = 1.0        # Si supera el mínimo anterior aunque sea 1% → reportar

# Días máximos de historial a considerar (0 = todos los días)
DIAS_HISTORIAL: int = 0

# ────────────────────────────────────────────────────────────────────────────


def _cargar_historial(ruta_historial: str) -> dict:
    """Carga el historial de la tienda (JSON legado o SQLite, según migración)."""
    try:
        from analizador.historial_precios import cargar_historial
        return cargar_historial(ruta_historial)
    except (json.JSONDecodeError, IOError):
        return {}


def _obtener_precio_efectivo(registro: dict) -> float | None:
    """
    Obtiene el precio más bajo de un registro histórico.
    Prioridad: precio_minimo → precio_oferta → precio_normal
    """
    return (
        registro.get("precio_minimo")
        or registro.get("precio_oferta")
        or registro.get("precio_normal")
    )


def _mediana(valores: list) -> float | None:
    """Mediana de una lista de números (None si está vacía)."""
    if not valores:
        return None
    orden = sorted(valores)
    n = len(orden)
    mitad = n // 2
    if n % 2 == 1:
        return orden[mitad]
    return (orden[mitad - 1] + orden[mitad]) / 2


def _filtrar_registros_por_periodo(registros: list, dias: int) -> list:
    """Filtra registros por período de días (0 = todos)."""
    if dias <= 0 or not registros:
        return registros

    hoy = datetime.now(TZ_PERU)
    fecha_limite = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")
    return [r for r in registros if r.get("fecha", "") >= fecha_limite]


def analizar_producto_historico(
    product_id: str,
    precio_hoy: float,
    historial_producto: dict,
) -> dict | None:
    """
    Analiza si el precio de hoy es un mínimo histórico para un producto.

    Args:
        product_id: ID del producto.
        precio_hoy: Precio actual del producto (el más bajo disponible hoy).
        historial_producto: Dict del historial de ese producto (registros, nombre, url...).

    Returns:
        Dict con análisis si el precio es notable, None si no lo es.
        {
            "id": "...",
            "nombre": "...",
            "precio_hoy": 300.0,
            "precio_minimo_anterior": 500.0,  ← mínimo histórico SIN contar hoy
            "precio_promedio": 612.5,
            "precio_maximo": 650.0,
            "diferencia_vs_minimo": -40.0,    ← % vs mínimo anterior (negativo = nuevo mínimo)
            "ahorro_vs_promedio": 51.0,       ← % que se ahorra vs el promedio
            "num_registros": 5,
            "es_nuevo_minimo": True,
            "es_bajo_vs_mediana": True,
            "clasificacion": "MINIMO_HISTORICO" | "PRECIO_BAJO" | "NORMAL",
            "emoji": "🎯" | "📉" | "📊",
            "url": "..."
        }
    """
    registros = historial_producto.get("registros", [])
    # Los registros en cuarentena (precio atípico sin confirmar) no cuentan:
    # un glitch de scraping no puede definir el mínimo histórico.
    registros = [r for r in registros if not r.get("sospechoso")]
    registros_periodo = _filtrar_registros_por_periodo(registros, DIAS_HISTORIAL)

    if len(registros_periodo) < MIN_REGISTROS_REQUERIDOS:
        return None  # No hay suficiente historial para analizar

    # Fecha de hoy para excluir registros de hoy al calcular el mínimo anterior
    hoy_str = datetime.now(TZ_PERU).strftime("%Y-%m-%d")

    # Registros ANTERIORES a hoy (para comparación justa)
    registros_anteriores = [r for r in registros_periodo if r.get("fecha", "") < hoy_str]

    if len(registros_anteriores) < MIN_REGISTROS_REQUERIDOS - 1:
        # No hay suficientes datos anteriores a hoy
        return None

    # ── Calcular estadísticas del historial anterior ─────────────────────────
    precios_anteriores = [
        p for r in registros_anteriores
        if (p := _obtener_precio_efectivo(r)) is not None and p > 0
    ]

    if not precios_anteriores:
        return None

    precio_minimo_anterior = min(precios_anteriores)
    precio_maximo_anterior = max(precios_anteriores)
    precio_promedio_anterior = sum(precios_anteriores) / len(precios_anteriores)
    precio_mediana_anterior = _mediana(precios_anteriores)

    if precio_mediana_anterior is None or precio_mediana_anterior <= 0:
        return None

    # ── Comparar precio de hoy ────────────────────────────────────────────────
    diferencia_vs_minimo = ((precio_hoy - precio_minimo_anterior) / precio_minimo_anterior) * 100
    ahorro_vs_promedio = ((precio_promedio_anterior - precio_hoy) / precio_promedio_anterior) * 100
    ahorro_vs_mediana = ((precio_mediana_anterior - precio_hoy) / precio_mediana_anterior) * 100

    es_nuevo_minimo = diferencia_vs_minimo <= -UMBRAL_NUEVO_MINIMO
    es_bajo_vs_mediana = ahorro_vs_mediana >= UMBRAL_BAJO_VS_MEDIANA

    # Solo reportar si es notable
    if not es_nuevo_minimo and not es_bajo_vs_mediana:
        return None

    # ── Clasificar ────────────────────────────────────────────────────────────
    if es_nuevo_minimo:
        clasificacion = "MINIMO_HISTORICO"
        emoji = "🎯"
        if ahorro_vs_mediana >= 30:
            emoji = "🔥"
    else:
        clasificacion = "PRECIO_BAJO"
        emoji = "📉"

    return {
        "id": product_id,
        "nombre": historial_producto.get("nombre", "Producto desconocido"),
        "marca": historial_producto.get("marca", ""),
        "precio_hoy": round(precio_hoy, 2),
        "precio_minimo_anterior": round(precio_minimo_anterior, 2),
        "precio_maximo": round(precio_maximo_anterior, 2),
        "precio_promedio": round(precio_promedio_anterior, 2),
        "precio_mediana": round(precio_mediana_anterior, 2),
        "diferencia_vs_minimo": round(diferencia_vs_minimo, 2),
        "ahorro_vs_promedio": round(ahorro_vs_promedio, 2),
        "ahorro_vs_mediana": round(ahorro_vs_mediana, 2),
        "num_registros": len(registros_periodo),
        "num_registros_anteriores": len(registros_anteriores),
        "es_nuevo_minimo": es_nuevo_minimo,
        "es_bajo_vs_mediana": es_bajo_vs_mediana,
        "clasificacion": clasificacion,
        "emoji": emoji,
        "url": historial_producto.get("url", ""),
    }


def analizar_minimos(productos: list, ruta_historial: str, historial: dict | None = None) -> list:
    """
    Analiza toda la lista de productos buscando precios mínimos históricos.

    Compara el precio de hoy de cada producto contra TODO el historial
    que hemos acumulado nosotros mismos durante el proyecto.

    Args:
        productos: Lista de dicts con los productos scrapeados hoy.
        ruta_historial: Ruta al archivo historial_precios.json de la tienda.
        historial: Historial ya cargado en memoria (opcional). Evita
            re-parsear el JSON — el de Plaza Vea pesa cientos de MB y cada
            parseo es un pico de CPU en la mini PC.

    Returns:
        Lista de dicts con productos en mínimo histórico o precio notable,
        ordenados por ahorro vs promedio (mayor primero).
    """
    if historial is None:
        historial = _cargar_historial(ruta_historial)

    if not historial:
        print("  [i] [Cazador] Sin historial acumulado todavia - se necesitan mas ejecuciones")
        return []

    minimos_detectados = []

    for producto in productos:
        pid = str(producto.get("id", ""))
        if not pid or pid not in historial:
            continue

        # Precio efectivo de hoy
        precio_hoy = (
            producto.get("precio_minimo")
            or producto.get("precio_oferta")
            or producto.get("precio_normal")
        )

        if not precio_hoy or precio_hoy <= 0:
            continue

        resultado = analizar_producto_historico(
            product_id=pid,
            precio_hoy=precio_hoy,
            historial_producto=historial[pid],
        )

        if resultado:
            minimos_detectados.append(resultado)

    # Ordenar: primero los mínimos históricos reales, luego por ahorro vs mediana
    minimos_detectados.sort(
        key=lambda x: (
            0 if x["clasificacion"] == "MINIMO_HISTORICO" else 1,
            -x["ahorro_vs_mediana"],
        )
    )

    # ── Resumen compacto ──────────────────────────────────────────────────────
    if minimos_detectados:
        nuevos_minimos = sum(1 for m in minimos_detectados if m["es_nuevo_minimo"])
        precios_bajos = sum(1 for m in minimos_detectados if not m["es_nuevo_minimo"])

        print(f"    🎯 Mínimos: {nuevos_minimos} nuevos, {precios_bajos} bajo el precio típico ({len(minimos_detectados)} total)")

    return minimos_detectados
