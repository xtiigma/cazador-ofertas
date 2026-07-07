"""
Configuración Global — Cazador de Ofertas
Fecha de creación: 2026-03-28

Variables que aplican a todo el proyecto (Telegram, intervalos, etc.)
"""

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = ""       # TODO: Obtener de @BotFather
TELEGRAM_CHAT_ID   = ""       # TODO: Chat ID del usuario/grupo

# ── Análisis de descuentos ────────────────────────────────────────────────────
DESCUENTO_MINIMO_PORCENTAJE = 15    # Mínimo % de descuento para alertar
DIAS_PRECIO_ESTABLE         = 7     # Días que el precio debe haber sido estable
CAMBIOS_MAX_SEMANA_YOYO     = 3     # Máx cambios/semana para detectar patrón yo-yo

# ── Sistema 24/7 ─────────────────────────────────────────────────────────────
INTERVALO_GLOBAL_MINUTOS = 60       # Intervalo entre ciclos completos de scraping
HORARIO_ACTIVO = {
    "inicio": "06:00",              # Hora inicio monitoreo (Perú)
    "fin":    "23:00",              # Hora fin monitoreo
}

# ── Zona horaria ─────────────────────────────────────────────────────────────
TIMEZONE = "America/Lima"
