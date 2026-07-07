"""
Migrador del historial de precios: JSON → SQLite (Etapa 1 de webscraping2.0.md).

Uso (con el venv del proyecto):
  python mantenimiento/migrar_sqlite.py shopstar efe          # tiendas puntuales
  python mantenimiento/migrar_sqlite.py --todas
  python mantenimiento/migrar_sqlite.py shopstar --verificar  # + paridad de análisis

Qué hace por tienda:
  1. Carga su historial_precios.json (el último parseo gigante, fuera del ciclo).
  2. Crea tiendas/<t>/datos/historial.db (tablas productos + registros).
  3. Verifica conteos exactos y compara nodo a nodo (completo hasta 100K
     productos; muestra de 5,000 si es más grande).
  4. El JSON NO se toca: queda CONGELADO como respaldo. Desde ese momento la
     tienda opera en SQLite (historial_precios.cargar_historial despacha solo).

Revertir una tienda: borrar sus historial.db* (el JSON congelado retoma,
perdiendo los días registrados solo en la BD).
"""

import argparse
import glob
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analizador import almacen  # noqa: E402

MAX_COMPARACION_COMPLETA = 100_000
TAMANO_MUESTRA = 5_000


def _nodo_equivalente(nodo_json: dict, nodo_db: dict) -> bool:
    """Igualdad semántica entre el nodo del JSON y el reconstruido de la BD.

    Campo a campo con .get(): un campo ausente en el JSON viejo equivale a
    NULL en la BD. En registros, 'sospechoso' se compara como booleano porque
    en el JSON la clave solo existe cuando es True."""
    for campo in ("nombre", "marca", "url"):
        if nodo_json.get(campo) != nodo_db.get(campo):
            return False
    regs_j = nodo_json.get("registros") or []
    regs_d = nodo_db.get("registros") or []
    if len(regs_j) != len(regs_d):
        return False
    for rj, rd in zip(regs_j, regs_d):
        if (rj.get("fecha", "") != rd.get("fecha", "")
                or rj.get("precio_normal") != rd.get("precio_normal")
                or rj.get("precio_oferta") != rd.get("precio_oferta")
                or rj.get("precio_minimo") != rd.get("precio_minimo")
                or bool(rj.get("sospechoso")) != bool(rd.get("sospechoso"))):
            return False
    return True


def migrar(ruta_json: str, forzar: bool = False) -> dict:
    """Migra un historial JSON a SQLite y verifica la copia. Devuelve stats."""
    ruta_db = almacen.ruta_db(ruta_json)
    if os.path.exists(ruta_db):
        if not forzar:
            raise SystemExit(f"  ❌ Ya existe {ruta_db} — usa --forzar para recrearla")
        for sufijo in ("", "-wal", "-shm"):
            try:
                os.unlink(ruta_db + sufijo)
            except FileNotFoundError:
                pass

    if not os.path.exists(ruta_json):
        raise SystemExit(f"  ❌ No existe {ruta_json}")

    print(f"  📖 Cargando JSON ({os.path.getsize(ruta_json) / 1_048_576:.1f} MB)...")
    with open(ruta_json, encoding="utf-8") as f:
        historial = json.load(f)

    print(f"  🗄️  Escribiendo {len(historial):,} productos en {os.path.basename(ruta_db)}...")
    con = almacen.abrir(ruta_json)
    try:
        with con:  # una sola transacción
            total_regs = 0
            for pid, nodo in historial.items():
                regs = nodo.get("registros") or []
                # ultima_fecha = la del registro más reciente (semántica de poda
                # del JSON: _ultima_fecha); '' si el producto no tiene registros.
                ultima = max((r.get("fecha", "") for r in regs), default="")
                con.execute(
                    "INSERT INTO productos (id, nombre, marca, url, ultima_fecha)"
                    " VALUES (?,?,?,?,?)",
                    (str(pid), nodo.get("nombre"), nodo.get("marca"),
                     nodo.get("url"), ultima))
                con.executemany(
                    "INSERT INTO registros (producto_id, fecha, precio_normal,"
                    " precio_oferta, precio_minimo, sospechoso) VALUES (?,?,?,?,?,?)",
                    [(str(pid), r.get("fecha", ""), r.get("precio_normal"),
                      r.get("precio_oferta"), r.get("precio_minimo"),
                      1 if r.get("sospechoso") else 0) for r in regs])
                total_regs += len(regs)

        # ── Verificación ─────────────────────────────────────────────────────
        n_prod = con.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
        n_regs = con.execute("SELECT COUNT(*) FROM registros").fetchone()[0]
        if n_prod != len(historial) or n_regs != total_regs:
            raise SystemExit(f"  ❌ Conteos no cuadran: {n_prod}/{len(historial)} "
                             f"productos, {n_regs}/{total_regs} registros")

        pids = list(historial.keys())
        if len(pids) > MAX_COMPARACION_COMPLETA:
            pids = random.sample(pids, TAMANO_MUESTRA)
            modo = f"muestra de {TAMANO_MUESTRA:,}"
        else:
            modo = "comparación completa"
        for pid in pids:
            nodo_db = almacen._nodo(con, str(pid))
            if nodo_db is None or not _nodo_equivalente(historial[pid], nodo_db):
                raise SystemExit(f"  ❌ El producto {pid} no coincide entre JSON y BD")
    finally:
        con.close()

    mb_json = os.path.getsize(ruta_json) / 1_048_576
    mb_db = os.path.getsize(ruta_db) / 1_048_576
    print(f"  ✅ {n_prod:,} productos, {n_regs:,} registros verificados ({modo})")
    print(f"  💾 {mb_json:.1f} MB (JSON, queda congelado de respaldo) → {mb_db:.1f} MB (SQLite)")
    return {"productos": n_prod, "registros": n_regs,
            "mb_json": mb_json, "mb_db": mb_db}


def verificar_analisis(nombre_tienda: str, ruta_json: str):
    """Paridad de punta a punta: ofertas y mínimos del snapshot más reciente
    calculados contra el JSON congelado y contra la BD deben ser idénticos."""
    from analizador.detector_descuentos import analizar_productos
    from cazador_precios.cazador import analizar_minimos

    patron = os.path.join(os.path.dirname(ruta_json), f"{nombre_tienda}_*.json")
    snapshots = sorted(glob.glob(patron), key=os.path.getmtime)
    if not snapshots:
        print("  ⚠️  Sin snapshot para verificar análisis — omitido")
        return
    with open(snapshots[-1], encoding="utf-8") as f:
        productos = json.load(f)

    with open(ruta_json, encoding="utf-8") as f:
        historial_json = json.load(f)
    vista_db = almacen.HistorialSQLite(ruta_json)

    o_json = analizar_productos(productos, ruta_json, historial=historial_json)
    o_db = analizar_productos(productos, ruta_json, historial=vista_db)
    m_json = analizar_minimos(productos, ruta_json, historial=historial_json)
    m_db = analizar_minimos(productos, ruta_json, historial=vista_db)
    vista_db.close()

    if o_json != o_db or m_json != m_db:
        raise SystemExit("  ❌ El análisis difiere entre JSON y SQLite — revisar antes de usar")
    print(f"  ✅ Análisis idéntico JSON vs SQLite "
          f"({len(o_json)} ofertas, {len(m_json)} mínimos, snapshot {os.path.basename(snapshots[-1])})")


def main():
    parser = argparse.ArgumentParser(description="Migra historiales JSON a SQLite")
    parser.add_argument("tiendas", nargs="*", help="Nombres de carpeta en tiendas/")
    parser.add_argument("--todas", action="store_true")
    parser.add_argument("--forzar", action="store_true",
                        help="Recrear la BD si ya existe")
    parser.add_argument("--verificar", action="store_true",
                        help="Además, exigir paridad del análisis con el último snapshot")
    args = parser.parse_args()

    tiendas_dir = os.path.join(ROOT, "tiendas")
    if args.todas:
        nombres = sorted(d for d in os.listdir(tiendas_dir)
                         if os.path.isdir(os.path.join(tiendas_dir, d, "datos")))
    else:
        nombres = args.tiendas
    if not nombres:
        parser.error("Indica tiendas o usa --todas")

    for nombre in nombres:
        ruta_json = os.path.join(tiendas_dir, nombre, "datos", "historial_precios.json")
        print(f"\n🏪 {nombre}")
        migrar(ruta_json, forzar=args.forzar)
        if args.verificar:
            verificar_analisis(nombre, ruta_json)


if __name__ == "__main__":
    main()
