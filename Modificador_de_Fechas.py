"""
Modificador de Fechas — Eliminar dias de scraping del proyecto
================================================================

Al ejecutar este script:
  1. Escanea todos los historiales de precios de cada tienda
  2. Muestra las fechas en las que se hizo scraping
  3. Permite seleccionar fechas para eliminar
  4. Elimina los registros de esas fechas del historial
  5. Elimina los archivos JSON de scraping de esas fechas
  6. Regenera el dashboard web con los datos actualizados

Uso:
  python Modificador_de_Fechas.py
"""

import json
import os
import glob
import sys
import subprocess
from datetime import datetime
from collections import defaultdict

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Tiendas registradas ──────────────────────────────────────────────────────
TIENDAS = [
    {"nombre": "Inkafarma",      "dir": "inkafarma"},
    {"nombre": "Plaza Vea",      "dir": "plaza_vea"},
    {"nombre": "Saga Falabella",  "dir": "saga_falabella"},
    {"nombre": "Dermo",          "dir": "dermo"},
    {"nombre": "EFE",            "dir": "efe"},
    {"nombre": "Shopstar",       "dir": "shopstar"},
    {"nombre": "Sodimac",        "dir": "sodimac"},
    {"nombre": "Tailoy",         "dir": "tailoy"},
    {"nombre": "Promart",        "dir": "promart"},
]


def obtener_fechas_globales() -> dict:
    """
    Escanea todos los historiales y retorna un dict:
    {
        "2026-03-28": {"tiendas": ["Inkafarma", "Plaza Vea"], "registros": 5000, "archivos": [...]},
        ...
    }
    """
    fechas = defaultdict(lambda: {"tiendas": set(), "registros": 0, "archivos": []})

    for tienda in TIENDAS:
        datos_dir = os.path.join(ROOT_DIR, "tiendas", tienda["dir"], "datos")
        historial_path = os.path.join(datos_dir, "historial_precios.json")

        # 1. Extraer fechas del historial
        if os.path.exists(historial_path):
            try:
                with open(historial_path, "r", encoding="utf-8") as f:
                    historial = json.load(f)
                for pid, data in historial.items():
                    for reg in data.get("registros", []):
                        fecha = reg.get("fecha", "")
                        if fecha:
                            fechas[fecha]["tiendas"].add(tienda["nombre"])
                            fechas[fecha]["registros"] += 1
            except Exception:
                pass

        # 2. Buscar archivos JSON de scraping (tienda_YYYY-MM-DD_HHMMSS.json)
        patron = os.path.join(datos_dir, f"{tienda['dir']}_*.json")
        for archivo in glob.glob(patron):
            basename = os.path.basename(archivo)
            # Extraer fecha del nombre: tienda_YYYY-MM-DD_HHMMSS.json
            partes = basename.replace(".json", "").split("_")
            # La fecha está después del nombre de la tienda
            # Formato: tienda_2026-03-28_085951.json o plaza_vea_2026-03-28_085951.json
            for i, parte in enumerate(partes):
                try:
                    datetime.strptime(parte, "%Y-%m-%d")
                    fecha_archivo = parte
                    fechas[fecha_archivo]["archivos"].append(archivo)
                    break
                except ValueError:
                    continue

    # Convertir sets a listas para mostrar
    return dict(sorted(fechas.items()))


def mostrar_fechas(fechas: dict):
    """Muestra las fechas de scraping en formato de tabla."""
    print("\n" + "═" * 70)
    print("  📅 FECHAS DE SCRAPING REGISTRADAS")
    print("═" * 70)
    print(f"  {'#':<4} {'Fecha':<14} {'Registros':>10} {'Archivos':>9} {'Tiendas'}")
    print(f"  {'─'*4} {'─'*14} {'─'*10} {'─'*9} {'─'*30}")

    for i, (fecha, info) in enumerate(fechas.items(), 1):
        tiendas_str = ", ".join(sorted(info["tiendas"]))
        if len(tiendas_str) > 40:
            tiendas_str = tiendas_str[:37] + "..."
        print(f"  {i:<4} {fecha:<14} {info['registros']:>10,} {len(info['archivos']):>9} {tiendas_str}")

    print(f"\n  Total: {len(fechas)} fechas")
    print("═" * 70)


def solicitar_fechas_a_eliminar(fechas: dict) -> list:
    """Solicita al usuario las fechas que quiere eliminar."""
    fechas_lista = list(fechas.keys())

    print("\n  Ingresa las fechas a eliminar.")
    print("  Puedes usar:")
    print("    - Números separados por comas:  1,3,5")
    print("    - Rangos:                        1-5")
    print("    - Fechas directas:               2026-05-01")
    print("    - Combinaciones:                 1,3-5,2026-05-01")
    print()

    entrada = input("  👉 Fechas a eliminar: ").strip()
    if not entrada:
        return []

    fechas_seleccionadas = set()

    for parte in entrada.split(","):
        parte = parte.strip()

        # Rango numérico: 1-5
        if "-" in parte and parte[0].isdigit():
            # Verificar si es un rango (1-5) o una fecha (2026-05-01)
            try:
                datetime.strptime(parte, "%Y-%m-%d")
                # Es una fecha
                if parte in fechas:
                    fechas_seleccionadas.add(parte)
                else:
                    print(f"  ⚠️  Fecha '{parte}' no encontrada, ignorada.")
                continue
            except ValueError:
                pass

            try:
                inicio, fin = parte.split("-")
                inicio, fin = int(inicio), int(fin)
                for j in range(inicio, fin + 1):
                    if 1 <= j <= len(fechas_lista):
                        fechas_seleccionadas.add(fechas_lista[j - 1])
                continue
            except (ValueError, IndexError):
                print(f"  ⚠️  Rango inválido: '{parte}'")
                continue

        # Número simple
        if parte.isdigit():
            idx = int(parte)
            if 1 <= idx <= len(fechas_lista):
                fechas_seleccionadas.add(fechas_lista[idx - 1])
            else:
                print(f"  ⚠️  Número {idx} fuera de rango (1-{len(fechas_lista)})")
            continue

        # Fecha directa: 2026-05-01
        try:
            datetime.strptime(parte, "%Y-%m-%d")
            if parte in fechas:
                fechas_seleccionadas.add(parte)
            else:
                print(f"  ⚠️  Fecha '{parte}' no encontrada, ignorada.")
        except ValueError:
            print(f"  ⚠️  Entrada no reconocida: '{parte}'")

    return sorted(fechas_seleccionadas)


def confirmar_eliminacion(fechas_a_eliminar: list, fechas_info: dict) -> bool:
    """Muestra un resumen y pide confirmación."""
    total_registros = sum(fechas_info[f]["registros"] for f in fechas_a_eliminar)
    total_archivos = sum(len(fechas_info[f]["archivos"]) for f in fechas_a_eliminar)

    print(f"\n  ⚠️  Se eliminarán las siguientes fechas:")
    print(f"  {'─' * 50}")
    for fecha in fechas_a_eliminar:
        info = fechas_info[fecha]
        print(f"    ❌ {fecha} — {info['registros']:,} registros, {len(info['archivos'])} archivos")
    print(f"  {'─' * 50}")
    print(f"  Total: {total_registros:,} registros y {total_archivos} archivos JSON")
    print()

    respuesta = input("  ¿Estás seguro? (Y/N): ").strip().upper()
    return respuesta == "Y"


def eliminar_fechas(fechas_a_eliminar: list, fechas_info: dict):
    """Elimina los registros de las fechas seleccionadas de todos los historiales."""
    fechas_set = set(fechas_a_eliminar)

    print(f"\n  🔄 Procesando eliminación...")

    # 1. Limpiar historiales de precios
    for tienda in TIENDAS:
        historial_path = os.path.join(
            ROOT_DIR, "tiendas", tienda["dir"], "datos", "historial_precios.json"
        )

        if not os.path.exists(historial_path):
            continue

        try:
            with open(historial_path, "r", encoding="utf-8") as f:
                historial = json.load(f)
        except Exception as e:
            print(f"    ❌ Error leyendo historial de {tienda['nombre']}: {e}")
            continue

        registros_antes = sum(len(d.get("registros", [])) for d in historial.values())

        # Filtrar registros por fecha
        productos_vacios = []
        for pid, data in historial.items():
            registros_originales = data.get("registros", [])
            data["registros"] = [
                r for r in registros_originales
                if r.get("fecha", "") not in fechas_set
            ]
            if not data["registros"]:
                productos_vacios.append(pid)

        # Eliminar productos que quedaron sin registros
        for pid in productos_vacios:
            del historial[pid]

        registros_despues = sum(len(d.get("registros", [])) for d in historial.values())
        eliminados = registros_antes - registros_despues

        if eliminados > 0:
            with open(historial_path, "w", encoding="utf-8") as f:
                json.dump(historial, f, ensure_ascii=False, indent=2)
            print(f"    ✅ {tienda['nombre']}: {eliminados:,} registros eliminados, {len(productos_vacios)} productos vaciados")
        else:
            print(f"    ⏭️  {tienda['nombre']}: sin cambios")

    # 2. Eliminar archivos JSON de scraping
    archivos_eliminados = 0
    for fecha in fechas_a_eliminar:
        for archivo in fechas_info[fecha].get("archivos", []):
            try:
                os.remove(archivo)
                archivos_eliminados += 1
            except Exception as e:
                print(f"    ❌ Error eliminando {os.path.basename(archivo)}: {e}")

    if archivos_eliminados:
        print(f"\n    🗑️  {archivos_eliminados} archivos JSON eliminados")


def regenerar_dashboard():
    """Regenera el dashboard web con los datos actualizados."""
    print(f"\n  🌐 Regenerando dashboard web...")
    try:
        build_script = os.path.join(ROOT_DIR, "web", "build_data.py")
        result = subprocess.run(
            [sys.executable, build_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode == 0:
            print(f"  ✅ Dashboard actualizado correctamente")
        else:
            print(f"  ❌ Error actualizando dashboard:")
            print(result.stderr)
    except Exception as e:
        print(f"  ❌ Error ejecutando build_data.py: {e}")


def main():
    print("\n" + "═" * 70)
    print("  🛠️  MODIFICADOR DE FECHAS — Eliminar días de scraping")
    print("═" * 70)

    # 1. Obtener todas las fechas
    print("\n  Escaneando historiales de precios...")
    fechas = obtener_fechas_globales()

    if not fechas:
        print("  ❌ No se encontraron fechas de scraping.")
        return

    # 2. Mostrar fechas
    mostrar_fechas(fechas)

    # 3. Solicitar fechas a eliminar
    fechas_a_eliminar = solicitar_fechas_a_eliminar(fechas)

    if not fechas_a_eliminar:
        print("\n  ℹ️  No se seleccionaron fechas. Saliendo.")
        return

    # 4. Confirmar
    if not confirmar_eliminacion(fechas_a_eliminar, fechas):
        print("\n  ℹ️  Operación cancelada.")
        return

    # 5. Ejecutar eliminación
    eliminar_fechas(fechas_a_eliminar, fechas)

    # 6. Regenerar dashboard
    regenerar_dashboard()

    print(f"\n  ✅ Proceso completado. Las fechas seleccionadas fueron eliminadas.")
    print("═" * 70)


if __name__ == "__main__":
    main()
