"""
Registro de Mensajes Telegram
==============================

Guarda una copia local de cada mensaje enviado por el bot a Telegram.
Util para verificar que los datos enviados son correctos.

Formato del archivo (un JSON por dia):
  telegram_bot/registro/2026-04-12.json

Cada entrada:
  {
    "fecha": "2026-04-12",
    "hora": "03:48:57",
    "fecha_hora": "2026-04-12 03:48:57",
    "tipo": "OFERTA | MINIMO_HISTORICO | COMPARACION | RESUMEN",
    "tienda": "Inkafarma",
    "enviado_ok": true,
    "num_items": 3,
    "contenido": { ... datos completos ... }
  }
"""

import json
import os
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

REGISTRO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))


def _ruta_archivo_hoy() -> str:
    """Retorna la ruta del archivo de registro del dia actual."""
    hoy = datetime.now(TZ_PERU).strftime("%Y-%m-%d")
    return os.path.join(REGISTRO_DIR, f"{hoy}.json")


def _cargar_registro_hoy() -> list:
    """Carga el registro del dia actual. Retorna lista vacia si no existe."""
    ruta = _ruta_archivo_hoy()
    if not os.path.exists(ruta):
        return []
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _guardar_registro(registros: list):
    """Guarda la lista de registros en el archivo del dia."""
    ruta = _ruta_archivo_hoy()
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)


def registrar_mensaje(
    tipo: str,
    tienda: str,
    contenido: dict | list,
    enviado_ok: bool,
    num_items: int = 0,
):
    """
    Registra un mensaje enviado (o intentado) por Telegram.

    Args:
        tipo: Tipo de mensaje - "OFERTA", "MINIMO_HISTORICO", "COMPARACION", "RESUMEN"
        tienda: Nombre de la tienda relacionada (o "GLOBAL" para resumenes)
        contenido: Los datos exactos que se enviaron
        enviado_ok: True si el envio fue exitoso
        num_items: Cantidad de productos/items en el mensaje
    """
    ahora = datetime.now(TZ_PERU)

    entrada = {
        "fecha":       ahora.strftime("%Y-%m-%d"),
        "hora":        ahora.strftime("%H:%M:%S"),
        "fecha_hora":  ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "tipo":        tipo,
        "tienda":      tienda,
        "enviado_ok":  enviado_ok,
        "num_items":   num_items,
        "contenido":   contenido,
    }

    try:
        registros = _cargar_registro_hoy()
        registros.append(entrada)
        _guardar_registro(registros)
    except Exception as e:
        print(f"  [!] [Registro] No se pudo guardar entrada: {e}")
