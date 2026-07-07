#!/usr/bin/env bash
# 🛒 Cazador de Ofertas — arranque diario
# Ejecuta un ciclo completo usando el venv aislado. Lo invoca el systemd timer
# (cazador.timer) una vez al día, o puedes lanzarlo a mano:  ./run_diario.sh
set -euo pipefail

PROYECTO="/home/diego/Documentos/WEBSCRAPING"
VENV="$HOME/.venvs/cazador-ofertas"

cd "$PROYECTO"

# Para que Selenium (Saga Falabella) y Playwright funcionen sin entorno gráfico,
# corremos los navegadores en modo headless (ya configurado en los scrapers).
exec "$VENV/bin/python" main.py
