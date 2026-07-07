"""
Historial de Precios — Almacena y consulta precios históricos.
Fecha de creación: 2026-03-28

Cada tienda tiene su propio archivo de historial en:
  tiendas/<tienda>/datos/historial_precios.json

Formato del historial:
{
    "product_id": {
        "nombre": "...",
        "registros": [
            {"fecha": "2026-03-28", "precio_normal": 50.0, "precio_oferta": 35.0},
            {"fecha": "2026-03-29", "precio_normal": 50.0, "precio_oferta": 30.0},
        ]
    }
}
"""

import json
import os
from datetime import datetime, timezone, timedelta

from analizador import almacen

TZ_PERU = timezone(timedelta(hours=-5))

# Un producto cuyo último registro tenga más de estos días sin actualizarse se
# considera "muerto" (descatalogado, o un ID efímero que ya no reaparece) y se poda
# del historial. Los productos vistos recientemente se conservan SIEMPRE, aunque
# tengan un solo registro. El cazador de mínimos solo analiza productos del scrape
# del día, así que podar los muertos no afecta ningún análisis.
DIAS_RETENER_PRODUCTO = 60

# ── Cuarentena de precios sospechosos ────────────────────────────────────────
# El historial es el activo del proyecto: un precio corrupto (error de scraping,
# decimal perdido) envenena mínimos/medianas para siempre. Un precio nuevo que se
# desvía drásticamente de la mediana reciente se marca "sospechoso": True y se
# excluye de todos los cálculos. Si al día siguiente el precio persiste (±15%),
# era real y se confirma (se quita la marca); si fue un pico de un día, queda
# en cuarentena permanente. Los umbrales son deliberadamente holgados: una
# inflación pre-Cyber-Wow (~20-40%) NO se cuarentena — de esa se encarga la
# mediana en el analizador/cazador; aquí solo se atrapan valores absurdos.
RATIO_SOSPECHOSO_ALTO = 2.0    # precio > 2× la mediana reciente
RATIO_SOSPECHOSO_BAJO = 0.4    # precio < 40% de la mediana reciente
TOLERANCIA_CONFIRMACION = 0.15 # ±15% vs el día anterior = "persiste, era real"
MIN_CONFIABLES_PARA_JUZGAR = 3 # sin al menos 3 registros confiables, no se juzga
VENTANA_MEDIANA_RECIENTE = 30  # últimos N registros confiables para la mediana


def _precio_efectivo(registro: dict) -> float | None:
    """Precio más bajo disponible de un registro (lo que pagaría el comprador)."""
    return (
        registro.get("precio_minimo")
        or registro.get("precio_oferta")
        or registro.get("precio_normal")
    )


def mediana(valores: list) -> float | None:
    """Mediana de una lista de números (None si está vacía)."""
    if not valores:
        return None
    orden = sorted(valores)
    n = len(orden)
    mitad = n // 2
    if n % 2 == 1:
        return orden[mitad]
    return (orden[mitad - 1] + orden[mitad]) / 2


def _registros_confiables(registros: list) -> list:
    """Registros que no están en cuarentena."""
    return [r for r in registros if not r.get("sospechoso")]


def cargar_historial(ruta_historial: str) -> dict:
    """Carga el historial de una tienda. Retorna algo con forma de dict.

    Si la tienda ya migró a SQLite (existe historial.db junto al JSON),
    devuelve una vista de solo lectura sobre la BD (misma interfaz de dict,
    RAM mínima). Si no, el JSON legado de siempre; vacío si no existe."""
    if almacen.usa_sqlite(ruta_historial):
        return almacen.HistorialSQLite(ruta_historial)
    if os.path.exists(ruta_historial):
        with open(ruta_historial, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def guardar_historial(historial: dict, ruta_historial: str):
    """Guarda el historial en archivo JSON (formato compacto, sin indentación).

    Antes se guardaba con indent=2, lo que en archivos de millones de registros
    inflaba el tamaño ~40% solo en espacios y saltos de línea. El historial no se
    lee a mano, así que se guarda compacto: menos disco, menos I/O y parseo más
    rápido. Los datos son idénticos.
    """
    os.makedirs(os.path.dirname(ruta_historial), exist_ok=True)
    with open(ruta_historial, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, separators=(",", ":"))


def _ultima_fecha(nodo: dict) -> str:
    """Fecha del registro más reciente de un producto ('' si no tiene registros)."""
    return max((r.get("fecha", "") for r in nodo.get("registros") or []), default="")


def podar_historial(historial: dict, dias: int = DIAS_RETENER_PRODUCTO, hoy=None) -> int:
    """Elimina in-place los productos no vistos en los últimos `dias` días.

    Retorna cuántos productos se eliminaron. Conserva intactos los productos vivos
    y todos sus registros.
    """
    if hoy is None:
        hoy = datetime.now(TZ_PERU).date()
    limite = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")

    muertos = [pid for pid, nodo in historial.items() if _ultima_fecha(nodo) < limite]
    for pid in muertos:
        del historial[pid]
    return len(muertos)


def _imprimir_resumen_registro(nuevos, actualizados, cuarentenados, confirmados, podados):
    msg = f"+{nuevos} nuevos, {actualizados} actualizados"
    if cuarentenados:
        msg += f", {cuarentenados} en cuarentena (precio atípico)"
    if confirmados:
        msg += f", {confirmados} confirmados (salen de cuarentena)"
    if podados:
        msg += f", -{podados} muertos podados"
    print(f"    📊 Historial: {msg}")


def registrar_precios(productos: list, ruta_historial: str):
    """
    Registra los precios actuales de una lista de productos en el historial.
    Solo agrega un registro si el precio cambió respecto al último registro.

    Args:
        productos: Lista de dicts con campos: id, nombre, precio_normal, precio_oferta, precio_minimo
        ruta_historial: Ruta al archivo JSON del historial

    Devuelve el historial listo para consultar (dict en modo JSON; vista
    SQLite con interfaz de dict si la tienda ya migró).
    """
    if almacen.usa_sqlite(ruta_historial):
        vista, s = almacen.registrar_precios(productos, ruta_historial)
        _imprimir_resumen_registro(s["nuevos"], s["actualizados"],
                                   s["cuarentenados"], s["confirmados"], s["podados"])
        return vista

    historial = cargar_historial(ruta_historial)
    hoy = datetime.now(TZ_PERU).strftime("%Y-%m-%d")
    nuevos = 0
    actualizados = 0
    cuarentenados = 0
    confirmados = 0

    for prod in productos:
        pid = str(prod.get("id", ""))
        if not pid:
            continue

        precio_normal = prod.get("precio_normal")
        precio_oferta = prod.get("precio_oferta")
        precio_minimo = prod.get("precio_minimo")

        if pid not in historial:
            historial[pid] = {
                "nombre": prod.get("nombre", ""),
                "marca": prod.get("marca", ""),
                "url": prod.get("url", ""),
                "registros": []
            }
            nuevos += 1

        registros = historial[pid]["registros"]

        # Actualizar nombre/marca/url si cambiaron
        historial[pid]["nombre"] = prod.get("nombre", historial[pid]["nombre"])
        historial[pid]["marca"] = prod.get("marca", historial[pid]["marca"])
        historial[pid]["url"] = prod.get("url", historial[pid]["url"])

        # Solo agregar si el precio cambió o es el primer registro del día
        nuevo_registro = {
            "fecha": hoy,
            "precio_normal": precio_normal,
            "precio_oferta": precio_oferta,
            "precio_minimo": precio_minimo,
        }

        if not registros:
            registros.append(nuevo_registro)
            actualizados += 1
        else:
            ultimo = registros[-1]
            precio_cambio = (
                ultimo.get("precio_normal") != precio_normal or
                ultimo.get("precio_oferta") != precio_oferta or
                ultimo.get("precio_minimo") != precio_minimo
            )
            fecha_nueva = ultimo.get("fecha") != hoy

            if precio_cambio or fecha_nueva:
                # ── Cuarentena ────────────────────────────────────────────────
                precio_nuevo = _precio_efectivo(nuevo_registro)
                precio_ultimo = _precio_efectivo(ultimo)

                # Confirmación: si ayer quedó en cuarentena y hoy el precio
                # persiste (±15%), era un cambio real — se levanta la marca.
                persiste = (
                    precio_nuevo and precio_ultimo
                    and abs(precio_nuevo / precio_ultimo - 1) <= TOLERANCIA_CONFIRMACION
                )
                if persiste and ultimo.get("sospechoso"):
                    ultimo.pop("sospechoso", None)
                    confirmados += 1

                # Juicio: outlier vs la mediana reciente de registros confiables,
                # salvo que persista el precio de un día anterior ya confiable.
                confiables = _registros_confiables(registros)[-VENTANA_MEDIANA_RECIENTE:]
                if precio_nuevo and len(confiables) >= MIN_CONFIABLES_PARA_JUZGAR:
                    med = mediana([p for r in confiables if (p := _precio_efectivo(r))])
                    es_outlier = med and (
                        precio_nuevo > med * RATIO_SOSPECHOSO_ALTO
                        or precio_nuevo < med * RATIO_SOSPECHOSO_BAJO
                    )
                    ultimo_confiable = not ultimo.get("sospechoso")
                    if es_outlier and not (persiste and ultimo_confiable):
                        nuevo_registro["sospechoso"] = True
                        cuarentenados += 1

                registros.append(nuevo_registro)
                actualizados += 1

    # Podar productos muertos antes de guardar (reusa el dict ya cargado: gratis).
    podados = podar_historial(historial)

    guardar_historial(historial, ruta_historial)
    _imprimir_resumen_registro(nuevos, actualizados, cuarentenados, confirmados, podados)
    return historial


def obtener_precio_promedio(historial: dict, product_id: str, dias: int = 30) -> dict | None:
    """
    Calcula el precio promedio de un producto en los últimos N días.
    
    Returns:
        Dict con precio_normal_promedio, precio_oferta_promedio, num_registros
        o None si no hay datos.
    """
    if product_id not in historial:
        return None

    registros = historial[product_id]["registros"]
    if not registros:
        return None

    hoy = datetime.now(TZ_PERU)
    fecha_limite = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")

    registros_periodo = [
        r for r in _registros_confiables(registros) if r["fecha"] >= fecha_limite
    ]

    if not registros_periodo:
        return None

    precios_normal = [r["precio_normal"] for r in registros_periodo if r.get("precio_normal")]
    precios_oferta = [r["precio_oferta"] for r in registros_periodo if r.get("precio_oferta")]

    return {
        "precio_normal_promedio": sum(precios_normal) / len(precios_normal) if precios_normal else None,
        "precio_oferta_promedio": sum(precios_oferta) / len(precios_oferta) if precios_oferta else None,
        # Mediana = "precio típico": inmune a picos y a inflaciones pre-evento
        # (Cyber Wow), que sí arrastran el promedio hacia arriba.
        "precio_normal_mediana": mediana(precios_normal),
        "precio_oferta_mediana": mediana(precios_oferta),
        "num_registros": len(registros_periodo),
        "dias_analizados": dias,
    }


def obtener_precio_anterior(historial: dict, product_id: str) -> dict | None:
    """
    Obtiene el registro de precio anterior al actual (no el de hoy).
    Útil para detectar cambios recientes.
    """
    if product_id not in historial:
        return None

    registros = historial[product_id]["registros"]
    if len(registros) < 2:
        return None

    return registros[-2]


def contar_cambios_precio(historial: dict, product_id: str, dias: int = 7) -> int:
    """
    Cuenta cuántas veces cambió el precio en los últimos N días.
    Sirve para detectar patrón yo-yo (sube y baja constantemente).
    """
    if product_id not in historial:
        return 0

    registros = historial[product_id]["registros"]
    if len(registros) < 2:
        return 0

    hoy = datetime.now(TZ_PERU)
    fecha_limite = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")

    # Los registros en cuarentena no cuentan: un glitch de scraping no es yo-yo.
    registros_periodo = [
        r for r in _registros_confiables(registros) if r["fecha"] >= fecha_limite
    ]

    cambios = 0
    for i in range(1, len(registros_periodo)):
        if (registros_periodo[i].get("precio_oferta") != registros_periodo[i-1].get("precio_oferta") or
            registros_periodo[i].get("precio_normal") != registros_periodo[i-1].get("precio_normal")):
            cambios += 1

    return cambios
