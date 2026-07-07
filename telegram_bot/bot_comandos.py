"""
🤖 BOT DE COMANDOS — control del dashboard por Telegram
Fecha de creación: 2026-06-28

Proceso liviano que escucha Telegram (long-polling) y permite encender/apagar
el servidor del dashboard bajo demanda, para ahorrar energía en la mini PC.

Comandos (solo responde al CHAT_ID autorizado):
  /startserver  → enciende el dashboard + túnel y manda el link
  /stopserver   → apaga el dashboard (ahorra energía)
  /status       → dice si el dashboard está encendido o apagado
  /help, /start → ayuda

Corre como servicio systemd de usuario (cazador-bot.service), siempre activo.
No necesita dependencias externas (usa urllib, igual que el resto del proyecto).
"""

import os
import sys
import json
import time
import subprocess
import urllib.parse
import urllib.request
import urllib.error

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from telegram_bot.config import BOT_TOKEN, CHAT_ID

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
SERVICIO = "cazador-dashboard.service"
DASHBOARD_URL = "https://ofertas.entsanjeronimo.lat"
PUERTO_LOCAL = 8080

# Lockfile que main.py mantiene mientras el ciclo diario está corriendo.
CICLO_LOCK = os.path.join(ROOT_DIR, ".ciclo_en_curso")


# ── Telegram ──────────────────────────────────────────────────────────────────
def enviar(texto: str):
    datos = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        urllib.request.urlopen(f"{API}/sendMessage", data=datos, timeout=15)
    except urllib.error.URLError as e:
        print(f"  [ERROR] enviar: {e}", flush=True)


def obtener_updates(offset: int) -> list:
    """Long-poll de getUpdates. Devuelve la lista de updates nuevos."""
    url = f"{API}/getUpdates?timeout=30&offset={offset}"
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            return json.load(r).get("result", [])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []


# ── Control del servicio del dashboard ──────────────────────────────────────────
def _systemctl(accion: str) -> bool:
    r = subprocess.run(["systemctl", "--user", accion, SERVICIO],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [ERROR] systemctl {accion}: {r.stderr.strip()}", flush=True)
    return r.returncode == 0


def dashboard_activo() -> bool:
    r = subprocess.run(["systemctl", "--user", "is-active", SERVICIO],
                       capture_output=True, text=True)
    return r.stdout.strip() == "active"


def _tunel_responde(timeout: int = 4) -> bool:
    try:
        req = urllib.request.Request(DASHBOARD_URL + "/", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def ciclo_en_curso() -> bool:
    """True si el ciclo diario de scraping sigue corriendo.

    main.py escribe su PID en CICLO_LOCK al arrancar y lo borra al terminar.
    Si el proceso del PID ya no existe (ciclo muerto sin limpiar), el lock es
    huérfano y se ignora."""
    try:
        with open(CICLO_LOCK) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    return os.path.exists(f"/proc/{pid}")


# ── Comandos ────────────────────────────────────────────────────────────────────
def cmd_start():
    if ciclo_en_curso():
        return enviar(
            "⏳ El escaneo diario de tiendas todavía está corriendo — el dashboard "
            "mostraría datos a medias y encenderlo ahora calentaría más la mini PC.\n\n"
            "Te aviso con el mensaje de *datos actualizados* cuando termine; "
            "ahí ya puedes usar /startserver."
        )
    if dashboard_activo() and _tunel_responde():
        return enviar(f"✅ El dashboard ya está encendido:\n{DASHBOARD_URL}")
    enviar("🟢 Encendiendo el dashboard... (puede tardar hasta ~1 min la primera vez)")
    if not _systemctl("start"):
        return enviar("❌ No pude encender el dashboard. Revisa los logs.")
    # Esperar a que el túnel público responda (hasta ~60s: el edge de Cloudflare
    # tarda en propagar el routing cuando el túnel reconecta tras estar apagado).
    for _ in range(30):
        time.sleep(2)
        if _tunel_responde():
            return enviar(f"✅ Dashboard listo:\n{DASHBOARD_URL}\n\nCuando termines, manda /stopserver para ahorrar energía.")
    # La URL es fija: aunque el edge aún no responda, funcionará en segundos.
    enviar(f"✅ Dashboard encendido. Abre aquí (si no carga, reintenta en unos segundos):\n{DASHBOARD_URL}\n\nLuego manda /stopserver para ahorrar energía.")


def cmd_stop():
    if not dashboard_activo():
        return enviar("💤 El dashboard ya estaba apagado.")
    if _systemctl("stop"):
        enviar("🔴 Dashboard apagado. Energía ahorrada. Usa /startserver cuando quieras volver a verlo.")
    else:
        enviar("❌ No pude apagar el dashboard. Revisa los logs.")


def cmd_status():
    if dashboard_activo():
        responde = "y responde ✅" if _tunel_responde() else "(el túnel aún no responde) ⏳"
        enviar(f"🟢 Dashboard ENCENDIDO {responde}\n{DASHBOARD_URL}")
    else:
        enviar("🔴 Dashboard APAGADO. Manda /startserver para encenderlo.")


def cmd_help():
    enviar(
        "🤖 *Cazador de Ofertas — comandos*\n\n"
        "/startserver — encender el dashboard y recibir el link\n"
        "/stopserver — apagar el dashboard (ahorra energía)\n"
        "/status — ver si está encendido o apagado\n"
        "/help — esta ayuda"
    )


COMANDOS = {
    "/startserver": cmd_start,
    "/stopserver": cmd_stop,
    "/status": cmd_status,
    "/help": cmd_help,
    "/start": cmd_help,
}


def procesar(mensaje: dict):
    chat_id = str(mensaje.get("chat", {}).get("id", ""))
    texto = (mensaje.get("text") or "").strip().lower().split("@")[0]  # quita @bot
    # Seguridad: solo el chat autorizado puede dar órdenes.
    if chat_id != str(CHAT_ID):
        print(f"  [!] mensaje de chat no autorizado: {chat_id}", flush=True)
        return
    accion = COMANDOS.get(texto)
    if accion:
        print(f"  → comando: {texto}", flush=True)
        accion()
    elif texto.startswith("/"):
        enviar("🤔 No conozco ese comando. Usa /help.")


def main():
    print("  🤖 Bot de comandos escuchando...", flush=True)
    # Descartar mensajes viejos al arrancar: empezar desde el último update.
    offset = 0
    updates_iniciales = obtener_updates(0)
    if updates_iniciales:
        offset = updates_iniciales[-1]["update_id"] + 1
    while True:
        for upd in obtener_updates(offset):
            offset = upd["update_id"] + 1
            if "message" in upd:
                try:
                    procesar(upd["message"])
                except Exception as e:
                    print(f"  [ERROR] procesar: {e}", flush=True)


if __name__ == "__main__":
    main()
