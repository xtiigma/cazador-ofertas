"""
telegram_bot — Módulo de notificaciones por Telegram.
Configura tu BOT_TOKEN y CHAT_ID en telegram_bot/config.py y listo.
"""

from telegram_bot.notificador import enviar_alerta, enviar_resumen_ciclo

__all__ = ["enviar_alerta", "enviar_resumen_ciclo"]
