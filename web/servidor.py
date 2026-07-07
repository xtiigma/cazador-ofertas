"""
🌐 SERVIDOR DEL DASHBOARD — reemplazo de Vite (sin Node)
Fecha de creación: 2026-06-28

Sirve el dashboard estático (`web/`) + el consolidado (`public/data.json`) y
replica la API de favoritos que antes vivía en `vite.config.js`. Así el dashboard
funciona con solo Python, sin Node ni node_modules.

Además, si `cloudflared` está disponible, abre un túnel público para poder abrir
el dashboard desde internet y escribe la URL en `web/.tunnel_url` (de ahí la lee
`main.py` para mandarla por Telegram al final del ciclo diario).

Uso:
  python web/servidor.py                 # sirve en localhost:8080 + túnel cloudflared
  python web/servidor.py --puerto 8080   # cambiar puerto
  python web/servidor.py --sin-tunel     # solo local (sin cloudflared)
"""

import os
import sys
import json
import time
import signal
import argparse
import threading
import subprocess
from email.utils import formatdate, parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(WEB_DIR)
PUBLIC_DIR = os.path.join(WEB_DIR, "public")
TIENDAS_DIR = os.path.join(ROOT_DIR, "tiendas")
TUNNEL_URL_FILE = os.path.join(WEB_DIR, ".tunnel_url")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
}


def _ruta_segura(url_path: str) -> str | None:
    """Convierte la ruta URL a un archivo real dentro de web/ o web/public/.
    Devuelve None si no existe o intenta salir del directorio (path traversal)."""
    rel = url_path.lstrip("/").split("?", 1)[0]
    if rel == "":
        rel = "index.html"
    for base in (WEB_DIR, PUBLIC_DIR):
        candidato = os.path.normpath(os.path.join(base, rel))
        if candidato.startswith(base) and os.path.isfile(candidato):
            return candidato
    return None


class Handler(BaseHTTPRequestHandler):
    # Silencia el log por request (demasiado ruido para data.json de 169 MB)
    def log_message(self, *args):
        pass

    # ── Favoritos ────────────────────────────────────────────────────────────
    def _favoritos_get(self):
        todos = {}
        if os.path.isdir(TIENDAS_DIR):
            for tienda in os.listdir(TIENDAS_DIR):
                fav = os.path.join(TIENDAS_DIR, tienda, "datos", "favoritos.json")
                if os.path.isfile(fav):
                    try:
                        with open(fav, encoding="utf-8") as f:
                            ids = json.load(f)
                        if ids:
                            todos[tienda] = ids
                    except (OSError, json.JSONDecodeError):
                        pass
        self._responder_json({"success": True, "data": todos})

    def _favoritos_post(self):
        largo = int(self.headers.get("Content-Length", 0))
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except json.JSONDecodeError:
            return self._responder_json({"error": "JSON inválido"}, 400)

        store, pid, accion = cuerpo.get("store"), cuerpo.get("id"), cuerpo.get("action")
        if not store or not pid or not accion:
            return self._responder_json({"error": "Faltan parámetros"}, 400)

        fav_path = os.path.join(TIENDAS_DIR, store, "datos", "favoritos.json")
        os.makedirs(os.path.dirname(fav_path), exist_ok=True)

        favoritos = []
        if os.path.isfile(fav_path):
            try:
                with open(fav_path, encoding="utf-8") as f:
                    favoritos = json.load(f)
            except (OSError, json.JSONDecodeError):
                favoritos = []

        if accion == "add" and pid not in favoritos:
            favoritos.append(pid)
        elif accion == "remove":
            favoritos = [x for x in favoritos if x != pid]

        with open(fav_path, "w", encoding="utf-8") as f:
            json.dump(favoritos, f, ensure_ascii=False, indent=2)
        self._responder_json({"success": True, "favorites": favoritos})

    # ── Helpers de respuesta ──────────────────────────────────────────────────
    def _responder_json(self, obj, status=200):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _servir_archivo(self, ruta, solo_cabecera=False):
        ext = os.path.splitext(ruta)[1].lower()
        mtime = os.path.getmtime(ruta)

        # Revalidación de caché: si el navegador ya tiene la versión actual
        # (If-Modified-Since >= mtime del archivo), responder 304 sin reenviar.
        # Así el CSS/JS reflejan cambios al instante y el data.json de 169 MB
        # solo se re-descarga cuando de verdad cambia (cada ciclo diario).
        ims = self.headers.get("If-Modified-Since")
        if ims:
            try:
                ims_ts = parsedate_to_datetime(ims).timestamp()
                if int(mtime) <= int(ims_ts):
                    self.send_response(304)
                    self.end_headers()
                    return
            except (TypeError, ValueError):
                pass

        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(os.path.getsize(ruta)))
        self.send_header("Last-Modified", formatdate(mtime, usegmt=True))
        self.send_header("Cache-Control", "no-cache")  # cachear pero revalidar siempre
        self.end_headers()
        if solo_cabecera:
            return
        with open(ruta, "rb") as f:
            # Envío por bloques: data.json puede pesar cientos de MB.
            while chunk := f.read(64 * 1024):
                self.wfile.write(chunk)

    # ── Rutas ──────────────────────────────────────────────────────────────────
    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/favorites":
            return self._favoritos_get()
        ruta = _ruta_segura(self.path)
        if ruta:
            return self._servir_archivo(ruta)
        self._responder_json({"error": "No encontrado"}, 404)

    def do_HEAD(self):
        ruta = _ruta_segura(self.path)
        if ruta:
            return self._servir_archivo(ruta, solo_cabecera=True)
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path.split("?", 1)[0] == "/api/favorites":
            return self._favoritos_post()
        self._responder_json({"error": "No encontrado"}, 404)


# Túnel NAMED dedicado: URL fija y estable (no cambia nunca).
CLOUDFLARED_CONFIG = os.path.expanduser("~/.cloudflared/ofertas.yml")
DASHBOARD_URL = "https://ofertas.entsanjeronimo.lat"
_tunel_proc = None  # proceso cloudflared activo (para cerrarlo al apagar)


def _log(msg: str):
    """print con flush para que se vea en journalctl en tiempo real."""
    print(msg, flush=True)


def supervisar_tunel(puerto: int):
    """Mantiene vivo el túnel NAMED dedicado (config ofertas.yml → URL fija).
    Si cloudflared se cae, lo reinicia con backoff. La URL es estable, así que
    se escribe en .tunnel_url de entrada. Corre en un hilo daemon de por vida."""
    global _tunel_proc
    # URL fija: disponible desde ya (no hay que parsear nada de cloudflared).
    with open(TUNNEL_URL_FILE, "w") as f:
        f.write(DASHBOARD_URL)

    espera = 10  # backoff inicial (s)
    while True:
        try:
            proc = subprocess.Popen(
                ["cloudflared", "--config", CLOUDFLARED_CONFIG, "tunnel", "run"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
        except FileNotFoundError:
            _log("  ⚠️  cloudflared no está instalado; el dashboard solo será accesible en la red local.")
            return
        _tunel_proc = proc

        for linea in proc.stdout:
            if "Registered tunnel connection" in linea:
                _log(f"  🌐 Túnel público activo: {DASHBOARD_URL}")
                espera = 10  # reset backoff: conectó bien

        # Si llegamos aquí, cloudflared terminó (cayó). Reintentar con backoff.
        proc.wait()
        espera = min(espera * 2, 300)
        _log(f"  ⚠️  El túnel cloudflared se cerró. Reintentando en {espera}s...")
        time.sleep(espera)


def main():
    parser = argparse.ArgumentParser(description="Servidor del dashboard del Cazador de Ofertas.")
    parser.add_argument("--puerto", type=int, default=8080)
    parser.add_argument("--sin-tunel", action="store_true", help="No abrir túnel cloudflared.")
    args = parser.parse_args()

    # URL anterior obsoleta: se borra hasta que cloudflared publique una nueva.
    if os.path.exists(TUNNEL_URL_FILE):
        os.remove(TUNNEL_URL_FILE)

    servidor = ThreadingHTTPServer(("0.0.0.0", args.puerto), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    _log(f"  ✅ Dashboard sirviendo en http://127.0.0.1:{args.puerto}  (LAN: http://0.0.0.0:{args.puerto})")

    if not args.sin_tunel:
        threading.Thread(target=supervisar_tunel, args=(args.puerto,), daemon=True).start()

    def apagar(*_):
        _log("  🛑 Apagando servidor del dashboard...")
        servidor.shutdown()
        if _tunel_proc and _tunel_proc.poll() is None:
            _tunel_proc.terminate()  # cierra cloudflared (evita procesos zombie)
        os._exit(0)

    signal.signal(signal.SIGINT, apagar)
    signal.signal(signal.SIGTERM, apagar)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
