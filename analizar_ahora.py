"""
ANALIZAR AHORA - Analisis independiente sin scraping
=====================================================

Corre el analisis completo usando los datos JSON ya guardados.
NO hace ninguna peticion a las tiendas - solo analiza lo que tenemos.

Util para:
  - Verificar que el analisis y los mensajes de Telegram son correctos
  - Revisar los datos acumulados en cualquier momento
  - Probar el sistema sin esperar el scraping completo

Uso:
  python analizar_ahora.py

Genera:
  - Salida en consola con el analisis
  - Mensajes en Telegram con los resultados
  - Entrada en telegram_bot/registro/YYYY-MM-DD.json
  - Log en logger/logs/
"""

import sys
import os
import time
import traceback
from datetime import datetime, timezone, timedelta

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

# Logger (primero, para capturar toda la salida)
from logger.console_logger import configurar_logger, cerrar_logger
logger = configurar_logger()

# Modulos de analisis
from analizador.historial_precios import cargar_historial
from analizador.detector_descuentos import analizar_productos
from cazador_precios.cazador import analizar_minimos
from cazador_precios.comparador import comparar_desde_rutas

# Telegram
from telegram_bot.notificador import (
    enviar_alerta,
    enviar_minimos_historicos,
    enviar_comparacion,
    enviar_resumen_ciclo,
)

TZ_PERU = timezone(timedelta(hours=-5))

# -- Configuracion de tiendas (misma que main.py) ----------------------------
TIENDAS = [
    {
        "nombre": "Inkafarma",
        "historial": os.path.join(ROOT_DIR, "tiendas", "inkafarma", "datos", "historial_precios.json"),
    },
    {
        "nombre": "Plaza Vea",
        "historial": os.path.join(ROOT_DIR, "tiendas", "plaza_vea", "datos", "historial_precios.json"),
    },
    {
        "nombre": "Saga Falabella",
        "historial": os.path.join(ROOT_DIR, "tiendas", "saga_falabella", "datos", "historial_precios.json"),
    },
    {
        "nombre": "Dermo",
        "historial": os.path.join(ROOT_DIR, "tiendas", "dermo", "datos", "historial_precios.json"),
    },
    {
        "nombre": "EFE",
        "historial": os.path.join(ROOT_DIR, "tiendas", "efe", "datos", "historial_precios.json"),
    },
    {
        "nombre": "Shopstar",
        "historial": os.path.join(ROOT_DIR, "tiendas", "shopstar", "datos", "historial_precios.json"),
    },
    {
        "nombre": "Sodimac",
        "historial": os.path.join(ROOT_DIR, "tiendas", "sodimac", "datos", "historial_precios.json"),
    },
    {
        "nombre": "Tailoy",
        "historial": os.path.join(ROOT_DIR, "tiendas", "tailoy", "datos", "historial_precios.json"),
    },
    {
        "nombre": "Promart",
        "historial": os.path.join(ROOT_DIR, "tiendas", "promart", "datos", "historial_precios.json"),
    },
]


def analizar_ahora():
    """
    Carga los historiales JSON existentes y ejecuta todo el analisis
    sin hacer scraping. Envia resultados por Telegram.
    """
    inicio = time.time()
    ahora = datetime.now(TZ_PERU)

    print("\n" + "=" * 60)
    print(f"  CAZADOR DE OFERTAS - Solo analisis (sin scraping)")
    print(f"  Fecha/Hora: {ahora.strftime('%Y-%m-%d %H:%M:%S')} (Peru)")
    print(f"  Datos de: archivos JSON locales")
    print("=" * 60)

    resumen = {
        "modo": "SOLO ANALISIS",
        "tiendas_procesadas": 0,
        "total_productos": 0,
        "total_ofertas_reales": 0,
        "total_minimos": 0,
        "total_comparaciones": 0,
        "duracion_seg": 0,
        "fecha": ahora.strftime("%d/%m/%Y %H:%M"),
    }

    for tienda in TIENDAS:
        nombre  = tienda["nombre"]
        ruta_h  = tienda["historial"]

        print(f"\n{'─' * 50}")
        print(f"  Analizando: {nombre}")
        print(f"{'─' * 50}")

        # -- Cargar historial -------------------------------------------------
        if not os.path.exists(ruta_h):
            print(f"  [!] Sin historial para {nombre} - omitiendo")
            continue

        historial = cargar_historial(ruta_h)
        if not historial:
            print(f"  [!] Historial de {nombre} vacio - omitiendo")
            continue

        print(f"  [OK] {len(historial)} productos en historial de {nombre}")

        # Reconstruir lista de "productos actuales" desde el ultimo registro
        # del historial (es lo que analizar_productos y analizar_minimos esperan)
        productos_actuales = []
        for pid, data in historial.items():
            registros = data.get("registros", [])
            if not registros:
                continue
            ultimo = registros[-1]
            productos_actuales.append({
                "id":            pid,
                "nombre":        data.get("nombre", ""),
                "marca":         data.get("marca", ""),
                "precio_normal": ultimo.get("precio_normal"),
                "precio_oferta": ultimo.get("precio_oferta"),
                "precio_minimo": ultimo.get("precio_minimo"),
                "url":           data.get("url", ""),
            })

        resumen["total_productos"] += len(productos_actuales)

        # -- Analizar descuentos declarados -----------------------------------
        print(f"\n  [1/2] Analizando descuentos declarados...")
        ofertas = []
        try:
            ofertas = analizar_productos(productos_actuales, ruta_h)
            if ofertas:
                reales = sum(1 for o in ofertas if o["clasificacion"] in ("REAL", "GRAN_OFERTA"))
                resumen["total_ofertas_reales"] += reales
                print(f"\n  Top 5 ofertas de {nombre}:")
                for i, o in enumerate(ofertas[:5], 1):
                    print(f"     {i}. {o['emoji']} {o['nombre'][:50]}")
                    print(f"        S/{o['precio_normal']} -> S/{o['precio_actual']} (-{o['descuento_porcent']}%)")
        except Exception as e:
            print(f"  [ERROR] Analisis de descuentos: {e}")
            traceback.print_exc()

        # -- Cazador de minimos historicos ------------------------------------
        print(f"\n  [2/2] Cazando precios minimos historicos...")
        minimos = []
        try:
            minimos = analizar_minimos(productos_actuales, ruta_h)
            resumen["total_minimos"] += len(minimos)
        except Exception as e:
            print(f"  [ERROR] Cazador de precios: {e}")
            traceback.print_exc()

        # -- Telegram ---------------------------------------------------------
        print(f"\n  Enviando a Telegram...")
        try:
            if ofertas:
                enviar_alerta(ofertas, nombre)
            if minimos:
                enviar_minimos_historicos(minimos, nombre)
        except Exception as e:
            print(f"  [ERROR] Telegram: {e}")
            traceback.print_exc()

        resumen["tiendas_procesadas"] += 1

    # -- Comparador entre tiendas ---------------------------------------------
    print(f"\n{'─' * 50}")
    print(f"  Comparando precios entre tiendas...")
    print(f"{'─' * 50}")
    try:
        comparaciones = comparar_desde_rutas(TIENDAS)
        resumen["total_comparaciones"] = len(comparaciones)
        if comparaciones:
            enviar_comparacion(comparaciones)
    except Exception as e:
        print(f"  [ERROR] Comparador: {e}")
        traceback.print_exc()

    # -- Resumen final --------------------------------------------------------
    resumen["duracion_seg"] = round(time.time() - inicio, 1)

    print(f"\n{'=' * 60}")
    print(f"  Analisis completado - {datetime.now(TZ_PERU).strftime('%H:%M:%S')}")
    print(f"  Tiendas analizadas:       {resumen['tiendas_procesadas']}")
    print(f"  Productos procesados:     {resumen['total_productos']}")
    print(f"  Ofertas reales:           {resumen['total_ofertas_reales']}")
    print(f"  Minimos historicos:       {resumen['total_minimos']}")
    print(f"  Comparaciones tiendas:    {resumen['total_comparaciones']}")
    print(f"  Duracion:                 {resumen['duracion_seg']}s")
    print(f"{'=' * 60}")

    try:
        enviar_resumen_ciclo(resumen)
    except Exception as e:
        print(f"  [ERROR] Resumen Telegram: {e}")

    cerrar_logger()


if __name__ == "__main__":
    analizar_ahora()
