"""
cazador_precios - Detector de precios minimos historicos y comparador entre tiendas.

Analiza precios basandose en NUESTRO propio historial acumulado
de scraping, no en los descuentos que las tiendas declaran.
"""

from cazador_precios.cazador import analizar_minimos
from cazador_precios.comparador import comparar_desde_rutas, comparar_entre_tiendas

__all__ = ["analizar_minimos", "comparar_desde_rutas", "comparar_entre_tiendas"]
