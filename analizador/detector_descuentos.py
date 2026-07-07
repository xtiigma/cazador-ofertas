"""
Detector de Descuentos Reales
Fecha de creacion: 2026-03-28
Revision: 2026-04-12 — correccion de 5 incoherencias detectadas

Diferencia descuentos REALES de descuentos falsos/inflados comparando
el precio de oferta de la tienda contra NUESTRO historial acumulado.

Clasificacion:
  GRAN_OFERTA  — Baja real >= 30% confirmada con historial solido
  REAL         — Descuento real >= 15% con historial solido
  DUDOSO       — Precio sube y baja frecuentemente (patron yo-yo)
  FALSO        — Precio "normal" inflado justo antes de la "oferta"
  POCOS_DATOS  — Descuento aparente pero historial insuficiente (< 5 registros)
  NUEVO        — Primer registro, sin historial
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analizador.historial_precios import (
    cargar_historial,
    obtener_precio_promedio,
    contar_cambios_precio,
    _registros_confiables,
)


# == Configuracion de umbrales ================================================

DESCUENTO_MINIMO_PORCENT = 15      # % minimo para considerar "descuento"
DESCUENTO_GRAN_OFERTA    = 30      # % para clasificar como "gran oferta"

# CORRECCION BUG 5: se sube de 2 a 5 registros minimos para considerar
# que tenemos suficiente historia para validar un descuento
MIN_REGISTROS_VALIDAR    = 5

# CORRECCION BUG 4: minimo de registros en los ultimos 7 dias para
# afirmar que "el precio estuvo estable". Con 0-1 registro = sin datos.
MIN_REGISTROS_ESTABILIDAD = 2

MAX_CAMBIOS_YOYO         = 3       # cambios en 7 dias = patron yo-yo
DIAS_ESTABILIDAD         = 7

# =============================================================================


def calcular_descuento(precio_normal: float, precio_actual: float) -> float | None:
    """Calcula el % de descuento entre precio normal y actual."""
    if not precio_normal or not precio_actual or precio_normal <= 0:
        return None
    return round(((precio_normal - precio_actual) / precio_normal) * 100, 2)


def _label_referencia(num_registros: int, dias_cubiertos: int) -> str:
    """
    CORRECCION BUG 1: en lugar de decir siempre 'promedio 30 dias'
    muestra los datos reales que tenemos.
    La referencia es la MEDIANA (precio tipico): una tienda que infla precios
    unos dias antes de un evento (Cyber Wow) arrastra el promedio hacia arriba,
    pero no mueve la mediana.
    """
    return f"precio tipico historico ({num_registros} registros en ~{dias_cubiertos} dias)"


def _dias_cubiertos(historial: dict, pid: str) -> int:
    """Calcula cuantos dias reales hay entre el primer y ultimo registro."""
    from datetime import datetime
    regs = historial.get(pid, {}).get("registros", [])
    fechas = sorted(set(r.get("fecha", "") for r in regs if r.get("fecha")))
    if len(fechas) < 2:
        return 0
    try:
        d0 = datetime.strptime(fechas[0],  "%Y-%m-%d")
        d1 = datetime.strptime(fechas[-1], "%Y-%m-%d")
        return (d1 - d0).days
    except Exception:
        return 0


def _precio_normal_siempre_igual(historial: dict, pid: str) -> bool:
    """
    CORRECCION BUG 2: detecta si la tienda nunca cambio su precio_normal.
    En ese caso, el 'promedio historico' == precio_normal actual, y la
    deteccion de inflacion nunca se activa => clasificamos con cautela.
    """
    regs = _registros_confiables(historial.get(pid, {}).get("registros", []))
    pns  = [r.get("precio_normal") for r in regs if r.get("precio_normal")]
    if len(pns) < 2:
        return True
    return len(set(pns)) == 1


def clasificar_descuento(producto: dict, historial: dict) -> dict | None:
    """
    Analiza un producto y clasifica su descuento.

    Devuelve None si no hay descuento significativo.
    De lo contrario devuelve un dict con toda la informacion.
    """
    pid           = str(producto.get("id", ""))
    precio_normal = producto.get("precio_normal")
    precio_oferta = producto.get("precio_oferta")
    precio_minimo = producto.get("precio_minimo")

    # Usar el precio mas bajo disponible como "precio actual"
    precio_actual = precio_minimo or precio_oferta or precio_normal

    if not precio_normal or not precio_actual:
        return None

    descuento = calcular_descuento(precio_normal, precio_actual)
    if descuento is None or descuento < DESCUENTO_MINIMO_PORCENT:
        return None

    resultado = {
        "id":               pid,
        "nombre":           producto.get("nombre", ""),
        "marca":            producto.get("marca", ""),
        "precio_normal":    precio_normal,
        "precio_actual":    precio_actual,
        "descuento_porcent": descuento,
        "ahorro":           round(precio_normal - precio_actual, 2),
        "url":              producto.get("url", ""),
        "num_registros":    0,
        "dias_cubiertos":   0,
    }

    # -- Sin historial => NUEVO -----------------------------------------------
    promedio_data = obtener_precio_promedio(historial, pid, dias=90)  # ventana amplia

    if not promedio_data or promedio_data["num_registros"] < 1:
        resultado.update({
            "clasificacion":    "NUEVO",
            "emoji":            "[NUEVO]",
            "razon":            "Primer registro en el historial. Sin datos previos para validar.",
            "precio_tipico": None,
        })
        return resultado

    num_reg      = promedio_data["num_registros"]
    # Mediana como precio de referencia (con fallback al promedio por si acaso)
    precio_ref   = promedio_data.get("precio_normal_mediana") or promedio_data.get("precio_normal_promedio")
    dias_cub     = _dias_cubiertos(historial, pid)

    resultado["num_registros"]  = num_reg
    resultado["dias_cubiertos"] = dias_cub
    resultado["precio_tipico"] = round(precio_ref, 2) if precio_ref else None

    # CORRECCION BUG 5: si no tenemos suficientes registros, no podemos
    # afirmar que es un descuento real — clasificar como POCOS_DATOS
    if num_reg < MIN_REGISTROS_VALIDAR:
        resultado.update({
            "clasificacion": "POCOS_DATOS",
            "emoji":         "[?]",
            "razon": (
                f"Solo {num_reg} registros en {dias_cub} dias. "
                f"Se necesitan al menos {MIN_REGISTROS_VALIDAR} para validar. "
                f"El descuento declarado es {descuento}% segun precio de la tienda."
            ),
        })
        return resultado

    # -- Con historial suficiente: analisis completo --------------------------

    # CORRECCION BUG 4: verificar que haya registros reales en 7 dias
    cambios_semana = contar_cambios_precio(historial, pid, dias=DIAS_ESTABILIDAD)

    # Cuantos registros hay en los ultimos 7 dias?
    from datetime import datetime, timezone, timedelta
    TZ = timezone(timedelta(hours=-5))
    hace_7 = (datetime.now(TZ) - timedelta(days=DIAS_ESTABILIDAD)).strftime("%Y-%m-%d")
    regs_7d = [
        r for r in _registros_confiables(historial.get(pid, {}).get("registros", []))
        if r.get("fecha", "") >= hace_7
    ]
    tiene_estabilidad_real = len(regs_7d) >= MIN_REGISTROS_ESTABILIDAD

    # Detectar patron yo-yo
    if cambios_semana >= MAX_CAMBIOS_YOYO:
        resultado.update({
            "clasificacion": "DUDOSO",
            "emoji":         "[~]",
            "razon": (
                f"Precio cambio {cambios_semana} veces en los ultimos {DIAS_ESTABILIDAD} dias "
                f"(patron yo-yo). {_label_referencia(num_reg, dias_cub)}."
            ),
        })
        return resultado

    # CORRECCION BUG 2: detectar inflacion, considerando si precio_normal
    # siempre fue igual (en ese caso la inflacion es indetectable y avisamos)
    pn_invariante = _precio_normal_siempre_igual(historial, pid)

    if precio_ref and precio_normal > precio_ref * 1.10:
        # precio_normal actual es 10%+ mayor que la mediana => posible inflacion
        # (patron Cyber Wow: subir el precio "normal" dias antes del evento)
        desc_vs_ref = calcular_descuento(precio_ref, precio_actual)
        if desc_vs_ref is not None and desc_vs_ref < DESCUENTO_MINIMO_PORCENT:
            resultado.update({
                "clasificacion": "FALSO",
                "emoji":         "[FALSO]",
                "razon": (
                    f"Precio 'normal' de la tienda (S/{precio_normal}) es "
                    f"{round((precio_normal/precio_ref - 1)*100, 1)}% mayor "
                    f"que nuestro {_label_referencia(num_reg, dias_cub)} "
                    f"(S/{round(precio_ref, 2)}). "
                    f"El descuento real vs nuestro precio tipico es solo {desc_vs_ref}%."
                ),
            })
            return resultado

    # -- Clasificar descuento final -------------------------------------------
    # Aviso de precio_normal invariante: no podemos saber si es inflado
    nota_invariante = ""
    if pn_invariante:
        nota_invariante = (
            f" OJO: el precio 'normal' de S/{precio_normal} "
            f"nunca vario en nuestro historial — no podemos "
            f"confirmar si ese precio base es real o inflado."
        )

    # Nota de estabilidad honesta
    if tiene_estabilidad_real:
        nota_estabilidad = f"precio estable los ultimos {DIAS_ESTABILIDAD} dias ({len(regs_7d)} registros)."
    else:
        nota_estabilidad = f"pocos datos en los ultimos {DIAS_ESTABILIDAD} dias para confirmar estabilidad."

    label_ref = _label_referencia(num_reg, dias_cub)

    if descuento >= DESCUENTO_GRAN_OFERTA:
        resultado.update({
            "clasificacion": "GRAN_OFERTA",
            "emoji":         "[OFERTA]",
            "razon": (
                f"Gran descuento de {descuento}% segun precio de la tienda. "
                f"Nuestro {label_ref}: S/{round(precio_ref, 2) if precio_ref else '?'}. "
                f"{nota_estabilidad}{nota_invariante}"
            ),
        })
    else:
        resultado.update({
            "clasificacion": "REAL",
            "emoji":         "[OK]",
            "razon": (
                f"Descuento de {descuento}% confirmado vs nuestro {label_ref} "
                f"(S/{round(precio_ref, 2) if precio_ref else '?'}). "
                f"{nota_estabilidad}{nota_invariante}"
            ),
        })

    return resultado


def analizar_productos(productos: list, ruta_historial: str, historial: dict | None = None) -> list:
    """
    Analiza toda la lista de productos y retorna los que tienen
    descuentos relevantes, clasificados y ordenados.

    Si el llamador ya tiene el historial cargado (main.py lo recibe de
    registrar_precios), pasarlo en `historial` evita re-parsear el JSON —
    el de Plaza Vea pesa cientos de MB y cada parseo es un pico de CPU.
    """
    if historial is None:
        historial = cargar_historial(ruta_historial)
    ofertas = []

    for producto in productos:
        resultado = clasificar_descuento(producto, historial)
        if resultado:
            ofertas.append(resultado)

    # Orden: primero los mas confiables, luego por % descuento
    prioridad = {
        "GRAN_OFERTA":  0,
        "REAL":         1,
        "DUDOSO":       2,
        "FALSO":        3,
        "POCOS_DATOS":  4,
        "NUEVO":        5,
    }
    ofertas.sort(key=lambda x: (
        prioridad.get(x.get("clasificacion", "NUEVO"), 9),
        -x.get("descuento_porcent", 0),
    ))

    # Resumen compacto en consola
    if ofertas:
        gran    = sum(1 for o in ofertas if o["clasificacion"] == "GRAN_OFERTA")
        reales  = sum(1 for o in ofertas if o["clasificacion"] == "REAL")
        falsos  = sum(1 for o in ofertas if o["clasificacion"] == "FALSO")

        print(f"    📊 Descuentos: {gran} ofertas, {reales} reales, {falsos} falsos ({len(ofertas)} total)")

    return ofertas
