"""
🧹 MANTENIMIENTO — Rotación de snapshots y limpieza de disco
Fecha de creación: 2026-06-28

Cada scraper guarda un snapshot con timestamp (`<tienda>_AAAA-MM-DD_HHMMSS.json`)
en su carpeta `datos/`. Esos snapshots NUNCA se borraban y crecían sin límite
(plaza_vea llegó a ocupar ~2 GB). `web/build_data.py` solo usa el snapshot más
reciente de cada tienda; todo el resto es redundante porque los precios ya quedan
guardados en `historial_precios.json`.

Este módulo ofrece:
  - rotar_snapshots(): conserva solo los N snapshots más recientes de una tienda.
  - rotar_logs():      conserva solo los N logs de sesión más recientes.
  - main():            limpieza global de las 9 tiendas + logs (uso manual/CLI).

Uso manual:
  python mantenimiento/limpieza.py            # rota dejando 1 snapshot por tienda
  python mantenimiento/limpieza.py --conservar 3
  python mantenimiento/limpieza.py --dry-run  # muestra qué borraría, sin borrar
"""

import os
import sys
import glob
import argparse

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Nombres de carpeta de cada tienda (== prefijo de sus snapshots)
TIENDAS = [
    "inkafarma", "plaza_vea", "saga_falabella", "dermo", "efe",
    "shopstar", "sodimac", "tailoy", "promart",
]

# Snapshots a conservar por tienda por defecto (build_data.py solo usa 1)
CONSERVAR_POR_DEFECTO = 1
# Logs de sesión a conservar
CONSERVAR_LOGS = 30


def _mb(bytes_: int) -> float:
    return bytes_ / 1_048_576


def rotar_snapshots(datos_dir: str, prefijo: str, conservar: int = CONSERVAR_POR_DEFECTO,
                    dry_run: bool = False) -> tuple[int, int]:
    """Conserva solo los `conservar` snapshots más recientes de una tienda.

    Borra `<datos_dir>/<prefijo>_*.json` antiguos (no toca historial_precios.json
    ni favoritos.json porque no empiezan con `<prefijo>_`).

    Retorna (archivos_borrados, bytes_liberados).
    """
    if conservar < 1:
        conservar = 1  # nunca dejar la tienda sin su último snapshot

    patron = os.path.join(datos_dir, f"{prefijo}_*.json")
    archivos = glob.glob(patron)
    if len(archivos) <= conservar:
        return 0, 0

    # Más reciente al final (mismo criterio que web/build_data.py)
    archivos.sort(key=os.path.getmtime)
    a_borrar = archivos[:-conservar]

    borrados = 0
    liberado = 0
    for ruta in a_borrar:
        try:
            tam = os.path.getsize(ruta)
            if not dry_run:
                os.remove(ruta)
            borrados += 1
            liberado += tam
        except OSError as e:
            print(f"    ⚠️  No se pudo borrar {os.path.basename(ruta)}: {e}")

    return borrados, liberado


def rotar_logs(conservar: int = CONSERVAR_LOGS, dry_run: bool = False) -> tuple[int, int]:
    """Conserva solo los `conservar` archivos .log de sesión más recientes."""
    logs_dir = os.path.join(ROOT_DIR, "logger", "logs")
    archivos = glob.glob(os.path.join(logs_dir, "*.log"))
    if len(archivos) <= conservar:
        return 0, 0

    archivos.sort(key=os.path.getmtime)
    a_borrar = archivos[:-conservar] if conservar > 0 else archivos

    borrados = 0
    liberado = 0
    for ruta in a_borrar:
        try:
            tam = os.path.getsize(ruta)
            if not dry_run:
                os.remove(ruta)
            borrados += 1
            liberado += tam
        except OSError as e:
            print(f"    ⚠️  No se pudo borrar {os.path.basename(ruta)}: {e}")

    return borrados, liberado


def limpieza_global(conservar: int = CONSERVAR_POR_DEFECTO, dry_run: bool = False) -> None:
    """Recorre las 9 tiendas + logs y rota todo. Pensado para uso manual/CLI."""
    etiqueta = "🔎 SIMULACIÓN (no se borra nada)" if dry_run else "🧹 LIMPIEZA"
    print(f"\n{'═' * 60}")
    print(f"  {etiqueta} — conservando {conservar} snapshot(s) por tienda")
    print(f"{'═' * 60}")

    total_borrados = 0
    total_liberado = 0

    for tienda in TIENDAS:
        datos_dir = os.path.join(ROOT_DIR, "tiendas", tienda, "datos")
        if not os.path.isdir(datos_dir):
            continue
        borrados, liberado = rotar_snapshots(datos_dir, tienda, conservar, dry_run)
        total_borrados += borrados
        total_liberado += liberado
        if borrados:
            print(f"  {tienda:<16} {borrados:>3} snapshot(s) → {_mb(liberado):>8.1f} MB")

    # Logs de sesión
    b_logs, l_logs = rotar_logs(dry_run=dry_run)
    if b_logs:
        print(f"  {'logs sesión':<16} {b_logs:>3} archivo(s) → {_mb(l_logs):>8.1f} MB")
    total_borrados += b_logs
    total_liberado += l_logs

    verbo = "se borrarían" if dry_run else "borrados"
    print(f"{'─' * 60}")
    print(f"  ✅ {total_borrados} archivos {verbo} — {_mb(total_liberado):.1f} MB ({_mb(total_liberado)/1024:.2f} GB)")
    print(f"{'═' * 60}\n")


def podar_historiales_global(dias: int = 60, dry_run: bool = False) -> None:
    """Poda los productos muertos (>`dias` sin verse) de los 9 historiales y los
    reescribe en formato compacto. Procesa una tienda a la vez y libera la RAM entre
    tiendas (clave: plaza_vea ocupa ~2,5 GB en memoria al cargarse)."""
    import gc
    sys.path.insert(0, ROOT_DIR)
    from analizador.historial_precios import (
        cargar_historial, guardar_historial, podar_historial, _ultima_fecha,
    )
    from datetime import datetime, timezone, timedelta

    tz = timezone(timedelta(hours=-5))
    limite = (datetime.now(tz).date() - timedelta(days=dias)).strftime("%Y-%m-%d")

    etiqueta = "🔎 SIMULACIÓN (no se escribe nada)" if dry_run else "🧹 PODA DE HISTORIALES"
    print(f"\n{'═' * 64}")
    print(f"  {etiqueta} — eliminando productos no vistos en {dias} días")
    print(f"{'═' * 64}")
    print(f"  {'Tienda':<16} {'Productos':>12} {'Muertos':>10} {'Tamaño':>20}")
    print(f"  {'-' * 60}")

    tot_prod = tot_muertos = tot_antes = tot_despues = 0

    for tienda in TIENDAS:
        ruta = os.path.join(ROOT_DIR, "tiendas", tienda, "datos", "historial_precios.json")
        if not os.path.exists(ruta):
            continue

        tam_antes = os.path.getsize(ruta)
        hist = cargar_historial(ruta)
        n_prod = len(hist)

        if dry_run:
            muertos = sum(1 for nodo in hist.values() if _ultima_fecha(nodo) < limite)
            tam_despues = tam_antes
        else:
            muertos = podar_historial(hist, dias)
            guardar_historial(hist, ruta)  # compacto
            tam_despues = os.path.getsize(ruta)

        tot_prod += n_prod
        tot_muertos += muertos
        tot_antes += tam_antes
        tot_despues += tam_despues

        tam_txt = f"{_mb(tam_antes):.1f} MB" if dry_run else f"{_mb(tam_antes):.0f}→{_mb(tam_despues):.0f} MB"
        print(f"  {tienda:<16} {n_prod:>12,} {muertos:>10,} {tam_txt:>20}")
        del hist
        gc.collect()

    print(f"  {'-' * 60}")
    verbo = "se eliminarían" if dry_run else "eliminados"
    print(f"  {tot_muertos:,} productos muertos {verbo} de {tot_prod:,} totales")
    if not dry_run:
        ahorro = tot_antes - tot_despues
        print(f"  Disco: {_mb(tot_antes):.0f} MB → {_mb(tot_despues):.0f} MB  "
              f"(liberado {_mb(ahorro):.0f} MB, {100*ahorro/tot_antes:.0f}%)")
    print(f"{'═' * 64}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rotación de snapshots, logs y poda de historiales.")
    parser.add_argument("--conservar", type=int, default=CONSERVAR_POR_DEFECTO,
                        help="Snapshots a conservar por tienda (mínimo 1).")
    parser.add_argument("--podar", action="store_true",
                        help="Poda productos muertos de los historiales y los compacta.")
    parser.add_argument("--dias", type=int, default=60,
                        help="Días sin verse para considerar un producto muerto (con --podar).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Muestra qué haría sin escribir nada.")
    args = parser.parse_args()

    if args.podar:
        podar_historiales_global(dias=args.dias, dry_run=args.dry_run)
    else:
        limpieza_global(conservar=args.conservar, dry_run=args.dry_run)
