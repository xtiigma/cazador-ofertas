"""
Console Logger - Captura toda la salida de consola y la guarda en un archivo .log.

Uso:
    from logger.console_logger import configurar_logger, obtener_logger

    logger = configurar_logger()   # Llamar UNA sola vez al inicio de main.py

Cada ejecucion genera un archivo en:
    logger/logs/YYYY-MM-DD_HH-MM-SS.log   (hora Peru)
"""

import logging
import os
import sys
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

_logger_global: logging.Logger | None = None
_stdout_original = None
_stderr_original = None


def _safe_write(stream, text: str):
    """
    Escribe texto en un stream de forma segura.
    Si hay error de encoding (cp1252 en Windows), hace fallback con reemplazo.
    """
    try:
        stream.write(text)
    except UnicodeEncodeError:
        # Convertir emojis y caracteres especiales a ? o equivalente ASCII
        safe = text.encode(getattr(stream, "encoding", "utf-8") or "utf-8", errors="replace").decode(
            getattr(stream, "encoding", "utf-8") or "utf-8", errors="replace"
        )
        try:
            stream.write(safe)
        except Exception:
            pass
    except (ValueError, OSError):
        # Stream cerrado u otro error de I/O — ignorar silenciosamente
        pass


class _TeeStream:
    """
    Stream que escribe en la consola original Y en el archivo de log.
    Captura todos los print() sin necesidad de cambiarlos.
    """

    def __init__(self, original_stream, logger: logging.Logger, level: int):
        self.original = original_stream
        self.logger = logger
        self.level = level
        self.encoding = getattr(original_stream, "encoding", "utf-8") or "utf-8"
        self.errors = "replace"

    def write(self, mensaje: str):
        # Escribir a consola con manejo de encoding
        _safe_write(self.original, mensaje)

        # Escribir al log (solo lineas no vacias)
        msg_limpio = mensaje.rstrip("\n")
        if msg_limpio.strip():
            try:
                self.logger.log(self.level, msg_limpio)
            except Exception:
                pass

    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass

    def isatty(self):
        return getattr(self.original, "isatty", lambda: False)()


def configurar_logger(nombre_sesion: str | None = None) -> logging.Logger:
    """
    Configura el sistema de logging para esta ejecucion.

    Crea el archivo .log en logger/logs/ y redirige sys.stdout/sys.stderr
    para que todo lo que se imprime tambien quede guardado.

    Args:
        nombre_sesion: Sufijo opcional para el nombre del archivo.
    Returns:
        logging.Logger listo para usar.
    """
    global _logger_global, _stdout_original, _stderr_original

    if _logger_global is not None:
        return _logger_global

    os.makedirs(LOGS_DIR, exist_ok=True)

    ahora = datetime.now(TZ_PERU)
    timestamp = ahora.strftime("%Y-%m-%d_%H-%M-%S")
    nombre_archivo = f"{timestamp}_{nombre_sesion}.log" if nombre_sesion else f"{timestamp}.log"
    ruta_log = os.path.join(LOGS_DIR, nombre_archivo)

    # Configurar logger
    logger = logging.getLogger("cazador_ofertas")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Handler: archivo (UTF-8, soporta emojis)
    fh = logging.FileHandler(ruta_log, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt="[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(fh)

    # Guardar referencias originales ANTES de redirigir
    _stdout_original = sys.stdout
    _stderr_original = sys.stderr

    # Redirigir usando los streams YA existentes (sin crear nuevos wrappers de buffer)
    sys.stdout = _TeeStream(sys.stdout, logger, logging.INFO)
    sys.stderr = _TeeStream(sys.stderr, logger, logging.ERROR)

    _logger_global = logger

    # Cabecera (solo al archivo)
    logger.info("=" * 60)
    logger.info(f"  CAZADOR DE OFERTAS - Sesion iniciada")
    logger.info(f"  Fecha/Hora (Peru): {ahora.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  Archivo de log: {nombre_archivo}")
    logger.info("=" * 60)

    # Informar por consola (este print ya queda en el log tambien)
    print(f"  [LOG] Sesion guardada en: logger/logs/{nombre_archivo}")

    return logger


def obtener_logger() -> logging.Logger:
    """Retorna el logger ya configurado (o lo inicializa si no existe)."""
    if _logger_global is None:
        return configurar_logger()
    return _logger_global


def cerrar_logger():
    """
    Cierra el logger y restaura stdout/stderr originales.
    Llamar al final de main.py.
    """
    global _logger_global, _stdout_original, _stderr_original

    if _logger_global is None:
        return

    # Pie del log
    try:
        ahora = datetime.now(TZ_PERU)
        _logger_global.info("")
        _logger_global.info("=" * 60)
        _logger_global.info(f"  Sesion finalizada - {ahora.strftime('%H:%M:%S')} (Peru)")
        _logger_global.info("=" * 60)
    except Exception:
        pass

    # Restaurar streams ANTES de cerrar handlers (para evitar 'lost sys.stderr')
    if _stdout_original is not None:
        sys.stdout = _stdout_original
        _stdout_original = None
    if _stderr_original is not None:
        sys.stderr = _stderr_original
        _stderr_original = None

    # Cerrar handlers de archivo
    for handler in _logger_global.handlers[:]:
        try:
            handler.flush()
            handler.close()
        except Exception:
            pass
        try:
            _logger_global.removeHandler(handler)
        except Exception:
            pass

    _logger_global = None
