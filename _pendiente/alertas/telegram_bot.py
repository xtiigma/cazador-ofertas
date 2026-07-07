"""
Bot de Telegram — Envía alertas de descuentos reales.
Fecha de creación: 2026-03-28

Requisitos:
  pip install requests

Configuración:
  Editar TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en config.py (raíz del proyecto)
  o directamente en este archivo.
"""

import requests
import sys
import os

# Agregar raíz del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID = ""


def enviar_mensaje(texto: str, parse_mode: str = "HTML") -> bool:
    """
    Envía un mensaje de texto a Telegram.
    
    Args:
        texto: Mensaje a enviar (soporta HTML)
        parse_mode: "HTML" o "Markdown"
    
    Returns:
        True si se envió correctamente.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  ⚠️  Telegram no configurado (falta TOKEN o CHAT_ID)")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False,
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print(f"  ✅ Mensaje enviado a Telegram")
        return True
    except Exception as e:
        print(f"  ❌ Error enviando a Telegram: {e}")
        return False


def formatear_alerta_oferta(oferta: dict, tienda: str = "Inkafarma") -> str:
    """
    Formatea una oferta como mensaje HTML para Telegram.
    
    Args:
        oferta: Dict con datos de la oferta (del detector de descuentos)
        tienda: Nombre de la tienda
    
    Returns:
        Mensaje formateado en HTML
    """
    emoji = oferta.get("emoji", "🏷️")
    clasificacion = oferta.get("clasificacion", "")
    
    # Encabezado según clasificación
    if clasificacion == "GRAN_OFERTA":
        header = "🔥🔥🔥 ¡GRAN OFERTA DETECTADA! 🔥🔥🔥"
    elif clasificacion == "REAL":
        header = "🟢 ¡OFERTA REAL DETECTADA!"
    elif clasificacion == "DUDOSO":
        header = "🟡 Oferta dudosa detectada"
    elif clasificacion == "NUEVO":
        header = "🆕 Nueva oferta detectada"
    else:
        header = "🏷️ Oferta detectada"

    precio_promedio = oferta.get("precio_promedio_30d")
    promedio_linea = f"\n📊 Promedio 30 días: <b>S/{precio_promedio}</b>" if precio_promedio else ""

    mensaje = (
        f"{header}\n"
        f"{'─' * 30}\n"
        f"🏪 Tienda: <b>{tienda}</b>\n"
        f"📦 <b>{oferta.get('nombre', '?')}</b>\n"
        f"🏷️ Marca: {oferta.get('marca', '?')}\n\n"
        f"💰 Precio normal: <s>S/{oferta.get('precio_normal', '?')}</s>\n"
        f"🏷️ Precio oferta: <b>S/{oferta.get('precio_actual', '?')}</b>\n"
        f"📉 Descuento: <b>-{oferta.get('descuento_porcent', '?')}%</b>\n"
        f"💵 Ahorras: <b>S/{oferta.get('ahorro', '?')}</b>"
        f"{promedio_linea}\n\n"
        f"📝 {oferta.get('razon', '')}\n\n"
        f"🔗 <a href=\"{oferta.get('url', '#')}\">Ver producto</a>"
    )

    return mensaje


def enviar_resumen(ofertas: list, tienda: str = "Inkafarma") -> bool:
    """
    Envía un resumen de las mejores ofertas encontradas.
    Solo envía ofertas REALES y GRAN_OFERTA.
    """
    # Filtrar solo ofertas reales
    ofertas_reales = [o for o in ofertas if o.get("clasificacion") in ("REAL", "GRAN_OFERTA")]

    if not ofertas_reales:
        return False

    # Enviar las top 10 mejores ofertas
    top = ofertas_reales[:10]
    
    # Mensaje resumen
    resumen = (
        f"📊 <b>RESUMEN DE OFERTAS — {tienda.upper()}</b>\n"
        f"{'─' * 30}\n"
        f"🟢 {len(ofertas_reales)} ofertas reales encontradas\n"
        f"📤 Mostrando top {len(top)}\n"
        f"{'─' * 30}\n"
    )
    enviar_mensaje(resumen)

    # Enviar cada oferta individualmente
    for oferta in top:
        msg = formatear_alerta_oferta(oferta, tienda)
        enviar_mensaje(msg)

    return True


def enviar_alerta_test() -> bool:
    """Envía un mensaje de prueba para verificar que Telegram funciona."""
    return enviar_mensaje(
        "🤖 <b>Cazador de Ofertas</b>\n\n"
        "✅ Bot de alertas conectado correctamente.\n"
        "Recibirás notificaciones cuando se detecten descuentos reales."
    )
