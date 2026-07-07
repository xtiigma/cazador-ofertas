"""
Almacén SQLite del historial de precios — Etapa 1 de webscraping2.0.md.
Fecha de creación: 2026-07-07

POR QUÉ EXISTE (meta principal: temperatura):
El historial JSON obligaba a cargar y reescribir el archivo ENTERO cada ciclo
(Plaza Vea: ~474 MB ≈ ~2 GB de RAM y minutos de CPU al 100% — foco térmico de
la mini PC). Con SQLite solo se consulta y escribe lo del día, indexado, con
RAM y CPU mínimas.

MODO DUAL durante la migración (tienda por tienda):
- Si junto al historial_precios.json de una tienda existe `historial.db`,
  la tienda opera 100% en SQLite (su JSON queda CONGELADO como respaldo).
- Si no existe, la tienda sigue en JSON legado, sin ningún cambio.

Migrar una tienda:  python mantenimiento/migrar_sqlite.py <tienda> [--verificar]
Revertir:           borrar tiendas/<t>/datos/historial.db* → el JSON congelado
                    retoma (perdiendo los días registrados solo en la BD).

La lógica de cuarentena/mediana/poda replica EXACTAMENTE la del JSON
(analizador/historial_precios.py); las constantes se importan de ahí para que
haya una sola fuente de verdad.
"""

import os
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

NOMBRE_DB = "historial.db"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS productos (
    id           TEXT PRIMARY KEY,
    nombre       TEXT,
    marca        TEXT,
    url          TEXT,
    ultima_fecha TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS registros (
    id            INTEGER PRIMARY KEY,
    producto_id   TEXT NOT NULL,
    fecha         TEXT NOT NULL,
    precio_normal REAL,
    precio_oferta REAL,
    precio_minimo REAL,
    sospechoso    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_registros_pid   ON registros (producto_id, id);
CREATE INDEX IF NOT EXISTS idx_productos_fecha ON productos (ultima_fecha);
"""


def ruta_db(ruta_historial_json: str) -> str:
    """Ruta del historial.db de la tienda, derivada de la ruta de su JSON."""
    return os.path.join(os.path.dirname(ruta_historial_json), NOMBRE_DB)


def usa_sqlite(ruta_historial_json: str) -> bool:
    """True si la tienda ya fue migrada (existe su historial.db)."""
    return os.path.exists(ruta_db(ruta_historial_json))


def abrir(ruta_historial_json: str) -> sqlite3.Connection:
    """Abre (o crea) la BD de la tienda con el esquema y PRAGMAs listos."""
    con = sqlite3.connect(ruta_db(ruta_historial_json))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(_ESQUEMA)
    return con


def _nodo(con: sqlite3.Connection, pid: str) -> dict | None:
    """Reconstruye el nodo {nombre, marca, url, registros} de un producto,
    con la MISMA forma que tenía en el JSON (la clave 'sospechoso' solo
    existe en los registros en cuarentena, igual que antes)."""
    fila = con.execute(
        "SELECT nombre, marca, url FROM productos WHERE id=?", (pid,)
    ).fetchone()
    if fila is None:
        return None
    registros = []
    for fecha, pn, po, pm, sosp in con.execute(
        "SELECT fecha, precio_normal, precio_oferta, precio_minimo, sospechoso"
        "  FROM registros WHERE producto_id=? ORDER BY id", (pid,)
    ):
        r = {"fecha": fecha, "precio_normal": pn,
             "precio_oferta": po, "precio_minimo": pm}
        if sosp:
            r["sospechoso"] = True
        registros.append(r)
    return {"nombre": fila[0], "marca": fila[1], "url": fila[2],
            "registros": registros}


class HistorialSQLite(Mapping):
    """Vista de SOLO LECTURA con forma de dict {pid: nodo} sobre la BD.

    Los consumidores (detector, cazador, dashboard, analizar_ahora) acceden al
    historial como diccionario; esta vista materializa UN producto a la vez,
    así la RAM es mínima aunque la tienda tenga cientos de miles de productos.
    Cachea el último nodo leído porque el patrón de acceso es varias consultas
    seguidas sobre el mismo producto.
    """

    def __init__(self, ruta_historial_json: str):
        self._con = abrir(ruta_historial_json)
        self._cache_pid = None
        self._cache_nodo = None

    def __getitem__(self, pid):
        if pid == self._cache_pid:
            return self._cache_nodo
        nodo = _nodo(self._con, pid)
        if nodo is None:
            raise KeyError(pid)
        self._cache_pid, self._cache_nodo = pid, nodo
        return nodo

    def __contains__(self, pid):
        if pid == self._cache_pid:
            return True
        return self._con.execute(
            "SELECT 1 FROM productos WHERE id=?", (pid,)
        ).fetchone() is not None

    def __iter__(self):
        for (pid,) in self._con.execute("SELECT id FROM productos"):
            yield pid

    def __len__(self):
        return self._con.execute("SELECT COUNT(*) FROM productos").fetchone()[0]

    def close(self):
        try:
            self._con.close()
        except sqlite3.Error:
            pass


def registrar_precios(productos: list, ruta_historial_json: str, hoy=None) -> tuple:
    """Versión SQLite de historial_precios.registrar_precios: misma lógica de
    cuarentena/confirmación/poda, pero solo toca las filas del día.

    Devuelve (HistorialSQLite, stats) — la vista reemplaza al dict que devolvía
    la versión JSON y sirve para que el analizador y el cazador no relean nada.
    """
    # Import diferido: historial_precios importa este módulo (evita el ciclo).
    from analizador.historial_precios import (
        mediana,
        RATIO_SOSPECHOSO_ALTO, RATIO_SOSPECHOSO_BAJO, TOLERANCIA_CONFIRMACION,
        MIN_CONFIABLES_PARA_JUZGAR, VENTANA_MEDIANA_RECIENTE,
    )

    if hoy is None:
        hoy = datetime.now(TZ_PERU).strftime("%Y-%m-%d")
    stats = {"nuevos": 0, "actualizados": 0, "cuarentenados": 0,
             "confirmados": 0, "podados": 0}

    con = abrir(ruta_historial_json)
    try:
        cur = con.cursor()
        for prod in productos:
            pid = str(prod.get("id", ""))
            if not pid:
                continue

            precio_normal = prod.get("precio_normal")
            precio_oferta = prod.get("precio_oferta")
            precio_minimo = prod.get("precio_minimo")

            fila = cur.execute(
                "SELECT nombre, marca, url FROM productos WHERE id=?", (pid,)
            ).fetchone()
            if fila is None:
                cur.execute(
                    "INSERT INTO productos (id, nombre, marca, url) VALUES (?,?,?,?)",
                    (pid, prod.get("nombre", ""), prod.get("marca", ""),
                     prod.get("url", "")))
                stats["nuevos"] += 1
                fila = (prod.get("nombre", ""), prod.get("marca", ""),
                        prod.get("url", ""))

            # Actualizar nombre/marca/url si cambiaron (semántica JSON exacta:
            # el valor del scrape manda; si falta la clave, se conserva el viejo)
            cur.execute(
                "UPDATE productos SET nombre=?, marca=?, url=? WHERE id=?",
                (prod.get("nombre", fila[0]), prod.get("marca", fila[1]),
                 prod.get("url", fila[2]), pid))

            ultimo = cur.execute(
                "SELECT id, fecha, precio_normal, precio_oferta, precio_minimo,"
                " sospechoso FROM registros WHERE producto_id=?"
                " ORDER BY id DESC LIMIT 1", (pid,)
            ).fetchone()

            if ultimo is None:
                cur.execute(
                    "INSERT INTO registros (producto_id, fecha, precio_normal,"
                    " precio_oferta, precio_minimo) VALUES (?,?,?,?,?)",
                    (pid, hoy, precio_normal, precio_oferta, precio_minimo))
                cur.execute("UPDATE productos SET ultima_fecha=? WHERE id=?",
                            (hoy, pid))
                stats["actualizados"] += 1
                continue

            uid, ufecha, upn, upo, upm, usosp = ultimo
            precio_cambio = (upn != precio_normal or upo != precio_oferta
                             or upm != precio_minimo)
            fecha_nueva = ufecha != hoy
            if not (precio_cambio or fecha_nueva):
                continue

            # ── Cuarentena (réplica de historial_precios.registrar_precios) ──
            precio_nuevo = precio_minimo or precio_oferta or precio_normal
            precio_ultimo = upm or upo or upn

            persiste = (
                precio_nuevo and precio_ultimo
                and abs(precio_nuevo / precio_ultimo - 1) <= TOLERANCIA_CONFIRMACION
            )
            if persiste and usosp:
                cur.execute("UPDATE registros SET sospechoso=0 WHERE id=?", (uid,))
                usosp = 0
                stats["confirmados"] += 1

            sospechoso_nuevo = 0
            if precio_nuevo:
                confiables = cur.execute(
                    "SELECT precio_normal, precio_oferta, precio_minimo"
                    "  FROM registros WHERE producto_id=? AND sospechoso=0"
                    " ORDER BY id DESC LIMIT ?",
                    (pid, VENTANA_MEDIANA_RECIENTE)).fetchall()
                if len(confiables) >= MIN_CONFIABLES_PARA_JUZGAR:
                    med = mediana([p for pn, po, pm in confiables
                                   if (p := (pm or po or pn))])
                    es_outlier = med and (
                        precio_nuevo > med * RATIO_SOSPECHOSO_ALTO
                        or precio_nuevo < med * RATIO_SOSPECHOSO_BAJO
                    )
                    ultimo_confiable = not usosp
                    if es_outlier and not (persiste and ultimo_confiable):
                        sospechoso_nuevo = 1
                        stats["cuarentenados"] += 1

            cur.execute(
                "INSERT INTO registros (producto_id, fecha, precio_normal,"
                " precio_oferta, precio_minimo, sospechoso) VALUES (?,?,?,?,?,?)",
                (pid, hoy, precio_normal, precio_oferta, precio_minimo,
                 sospechoso_nuevo))
            cur.execute("UPDATE productos SET ultima_fecha=? WHERE id=?",
                        (hoy, pid))
            stats["actualizados"] += 1

        stats["podados"] = _podar(con)
        con.commit()
    finally:
        con.close()

    return HistorialSQLite(ruta_historial_json), stats


def _podar(con: sqlite3.Connection, dias: int | None = None, hoy=None) -> int:
    """Elimina productos no vistos en los últimos `dias` días (réplica de
    podar_historial). Se llama dentro de la transacción de registrar_precios."""
    from analizador.historial_precios import DIAS_RETENER_PRODUCTO
    if dias is None:
        dias = DIAS_RETENER_PRODUCTO
    if hoy is None:
        hoy = datetime.now(TZ_PERU).date()
    limite = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")

    n = con.execute("SELECT COUNT(*) FROM productos WHERE ultima_fecha < ?",
                    (limite,)).fetchone()[0]
    if n:
        con.execute("DELETE FROM registros WHERE producto_id IN"
                    " (SELECT id FROM productos WHERE ultima_fecha < ?)", (limite,))
        con.execute("DELETE FROM productos WHERE ultima_fecha < ?", (limite,))
    return n
