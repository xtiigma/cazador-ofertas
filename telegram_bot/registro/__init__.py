"""
telegram_bot/registro — Registro local de mensajes enviados por Telegram.
Guarda una copia de cada mensaje con fecha y hora para verificacion posterior.
"""

from telegram_bot.registro.registro_mensajes import registrar_mensaje

__all__ = ["registrar_mensaje"]
