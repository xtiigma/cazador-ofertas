"""
logger — Módulo de registro de logs por ejecución.
Cada vez que corre main.py se genera un archivo .log con fecha y hora.
"""

from logger.console_logger import configurar_logger, obtener_logger

__all__ = ["configurar_logger", "obtener_logger"]
