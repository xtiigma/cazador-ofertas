"""
Telegram Bot — Configuración (PLANTILLA)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Copia este archivo como `config.py` y rellena BOT_TOKEN y CHAT_ID.
`config.py` está en .gitignore: el token real NUNCA debe entrar al repo.

DOS formas de dar el token (config.py las soporta ambas):
  · Local (mini PC): pega el token/chat_id en las líneas de abajo.
  · Nube (GitHub Actions): déjalos vacíos y define las variables de entorno
    TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID (los Secrets del repo). El workflow
    copia esta plantilla a config.py y los valores salen del entorno.

PASO 1: Crear tu bot en Telegram
  1. Abre Telegram y busca @BotFather
  2. Envía /newbot y sigue los pasos
  3. Copia el token que te da (ej: 123456789:AAFx...)

PASO 2: Obtener tu Chat ID
  Opción A (personal): busca @userinfobot en Telegram, tu ID aparece ahí.
  Opción B (grupo): agrega tu bot al grupo, ve a:
    https://api.telegram.org/bot<TU_TOKEN>/getUpdates
    y busca el campo "chat" > "id"
"""

import os

# Pega el valor entre las comillas (mini PC), o déjalo vacío y usa la variable
# de entorno del mismo nombre en mayúsculas con prefijo TELEGRAM_ (GitHub Actions).
BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")   # ← token de tu bot
CHAT_ID: str   = os.environ.get("TELEGRAM_CHAT_ID", "")     # ← tu Chat ID

# ─────────────────────────────────────────────────────────────────────────────

# Umbrales para decidir qué enviar por Telegram
MIN_DESCUENTO_TELEGRAM: float = 15.0    # Solo alertas con >= este % de descuento
MAX_PRODUCTOS_POR_MENSAJE: int = 5      # Productos máximos por mensaje
INCLUIR_DUDOSOS: bool = False           # True = incluye también descuentos dudosos
INCLUIR_FALSOS: bool = False            # True = incluye también descuentos falsos

# Clasificaciones que SÍ se envían por defecto
CLASIFICACIONES_PERMITIDAS: tuple = ("GRAN_OFERTA", "REAL", "POCOS_DATOS")
