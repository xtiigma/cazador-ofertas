# Cazador de Precios Mínimos Históricos

## ¿Qué hace este módulo?

A diferencia del `analizador/`, que detecta descuentos **según lo que la tienda dice**,
este módulo detecta precios bajos comparando el precio de **hoy** vs el **historial
que nosotros mismos hemos acumulado** con el proyecto.

## El concepto clave

```
TV Samsung — Nuestro historial:
  Día 1 (2026-03-28): S/500   ← primer registro
  Día 2 (2026-03-29): S/650
  Día 3 (2026-04-01): S/650
  Día 4 (2026-04-05): S/650
  Día 5 (2026-04-12): S/300   ← HOY → ¡MÍNIMO HISTÓRICO! 🎯
```

La tienda puede NO tener marcada ninguna oferta, pero **nosotros sabemos** que S/300
es el precio más bajo que hemos visto. Eso es una oportunidad que solo nuestro
sistema puede detectar.

## Clasificaciones

| Emoji | Clasificación         | Condición                                           |
|-------|-----------------------|-----------------------------------------------------|
| 🎯    | `MINIMO_HISTORICO`    | Precio de hoy ≤ mínimo histórico anterior (1%+)    |
| 🔥    | `MINIMO_HISTORICO`    | Igual pero con ahorro ≥ 30% vs promedio             |
| 📉    | `PRECIO_BAJO`         | Precio 10%+ por debajo del promedio histórico       |

## Configuración (`cazador.py`)

```python
MIN_REGISTROS_REQUERIDOS  = 3     # Mínimo de días con datos para confiar
UMBRAL_BAJO_VS_PROMEDIO   = 10.0  # % bajo el promedio para reportar
UMBRAL_NUEVO_MINIMO       = 1.0   # % para considerar "nuevo mínimo"
DIAS_HISTORIAL            = 0     # 0 = usar TODO el historial acumulado
```

## Uso desde main.py

```python
from cazador_precios import analizar_minimos

minimos = analizar_minimos(productos, ruta_historial="tiendas/inkafarma/datos/historial_precios.json")
```

## Output de ejemplo

```
🎯 Análisis de precios históricos:
   🎯 Nuevos mínimos históricos: 2
   📉 Precios bajo el promedio:  3
   ────────────────────────────────
   📊 Total notable:             5

🏆 Top 5 precios más interesantes:
   1. 🔥 [NUEVO MÍNIMO] TV Samsung 55"
      Hoy: S/300 | Promedio: S/637 | Mín. anterior: S/500
      Ahorro vs promedio: 52.9% | Registros: 5
```

## Nota importante

El módulo necesita **al menos 3 ejecuciones previas** (en días diferentes)
para tener suficiente historial y comenzar a detectar mínimos.
Mientras más días de datos, más preciso será el análisis.
