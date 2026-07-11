#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Baja el data.json que generó el ciclo en la nube (GitHub Actions) y lo deja
# para el dashboard local. La mini PC ya NO scrapea: solo consume lo de Azure.
#
# El ciclo publica web/public/data.json como asset del release de tag fijo
# `datos-nube`, así que existe una URL estable que bajamos con curl (repo público
# → sin autenticación). Lo corre a diario `cazador-web.timer` tras el ciclo.
#
# Reversible: deshabilita el timer con `systemctl --user disable --now cazador-web.timer`.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

DEST="/home/diego/Documentos/WEBSCRAPING/web/public/data.json"
URL="https://github.com/xtiigma/cazador-ofertas/releases/download/datos-nube/data.json"

log() { echo "[$(date '+%F %T')] $*"; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

log "Bajando data.json desde la nube…"
# -f: falla en 404 (release aún no listo) · -L: sigue el redirect al objeto
# --retry: aguanta cortes de red pasajeros de la mini PC
curl -fL --retry 3 --retry-delay 10 -o "$TMP" "$URL"

# Sanidad mínima sin cargar los ~169 MB en memoria: tamaño razonable + arranca
# como JSON. Si el asset fuera una página de error, no pasaría esto.
tam=$(stat -c%s "$TMP")
if [ "$tam" -lt 1000000 ]; then
  log "ERROR: el archivo bajado pesa $tam bytes (<1 MB); no lo aplico."
  exit 1
fi
primer=$(head -c1 "$TMP")
if [ "$primer" != "{" ] && [ "$primer" != "[" ]; then
  log "ERROR: el contenido no parece JSON (empieza con '$primer'); no lo aplico."
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
mv "$TMP" "$DEST"
trap - EXIT
log "Dashboard actualizado: $(du -h "$DEST" | cut -f1)"
