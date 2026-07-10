"""
Adaptador de conexión al historial — SQLite local o réplica Turso (Etapa 5).

Objetivo: que `almacen.py` no tenga que saber si trabaja contra un archivo
SQLite local (mini PC, como hasta hoy) o contra una réplica embebida sincronizada
con Turso (cuando el ciclo corre en GitHub Actions). La lógica SQL es idéntica en
ambos casos porque libSQL habla SQLite.

MODO LOCAL (por defecto, sin config):
    con = conectar("tiendas/efe/datos/historial.db", "efe")
  → abre el archivo local igual que sqlite3. Cero cambios de comportamiento.

MODO TURSO (cuando hay variables de entorno):
    TURSO_URL_<TIENDA>  ó  TURSO_URL   (libsql://<db>-<org>.turso.io)
    TURSO_TOKEN         (token de auth)
  → abre una réplica embebida en `database` (archivo local efímero) sincronizada
    con Turso: sync() al abrir trae lo remoto; sync() al cerrar empuja los cambios.
    Las lecturas salen del archivo local (rápidas, sin cuota de red).

Elección deliberada: una base Turso POR TIENDA (espeja la estructura local actual),
así el nombre de la base es la tienda y el cambio de código es mínimo.
"""

import os
import sqlite3

try:
    import libsql
    _HAY_LIBSQL = True
except ImportError:                     # la mini PC puede no tener libsql instalado
    libsql = None
    _HAY_LIBSQL = False

# El objeto Connection de libsql no admite atributos ni weakref, así que
# registramos qué conexiones son réplicas Turso por su id() para no intentar
# .sync() sobre una BD local (fallaría con "Sync is not supported in File mode").
_IDS_TURSO: set[int] = set()


def _config_turso(tienda: str) -> tuple[str | None, str | None]:
    """(sync_url, token) para la tienda, o (None, None) si no hay config."""
    url = os.environ.get(f"TURSO_URL_{tienda.upper()}") or os.environ.get("TURSO_URL")
    token = os.environ.get("TURSO_TOKEN")
    return (url or None), (token or None)


def usa_turso(tienda: str) -> bool:
    """True si hay config Turso para esta tienda y el cliente está disponible."""
    url, _ = _config_turso(tienda)
    return bool(url) and _HAY_LIBSQL


def conectar(ruta_local: str, tienda: str):
    """Abre la BD de la tienda. Réplica Turso si hay config; SQLite local si no.

    En modo Turso, sincroniza ANTES de devolver la conexión, para que el ciclo
    lea el historial remoto ya actualizado. Recuerda llamar a `cerrar(con)` al
    terminar para empujar los cambios a Turso."""
    url, token = _config_turso(tienda)

    if url and _HAY_LIBSQL:
        # offline=True: las escrituras se acumulan en el archivo local (rápido) y
        # sync() las empuja a Turso en bloque. Sin esto, cada escritura hace un
        # round-trip al primario y el ciclo se cuelga con decenas de miles de filas.
        con = libsql.connect(ruta_local, sync_url=url, auth_token=token or "",
                             offline=True)
        _IDS_TURSO.add(id(con))
        con.sync()                      # descarga el estado remoto para leer local
        return con

    # Modo local: SQLite de siempre (sqlite3), para no cambiar en nada el
    # comportamiento ya probado de la mini PC. libsql solo entra con réplica Turso.
    return sqlite3.connect(ruta_local)


def sincronizar(con) -> bool:
    """Empuja los cambios locales a Turso. No-op (True) si la conexión es local."""
    if id(con) not in _IDS_TURSO:
        return True                     # BD local: nada que sincronizar
    try:
        con.sync()
        return True
    except Exception as e:
        print(f"  ⚠️  Falló el sync a Turso: {e}")
        return False


def cerrar(con):
    """Sincroniza (si es Turso) y cierra la conexión."""
    sincronizar(con)
    _IDS_TURSO.discard(id(con))
    try:
        con.close()
    except Exception:
        pass
