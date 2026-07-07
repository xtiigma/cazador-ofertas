"""
Control del ventilador USB externo por temperatura (encendido/apagado).

La mini PC no puede regular la velocidad de un ventilador USB simple (solo
recibe 5V del puerto), pero SÍ puede cortar/restaurar la energía del puerto
con `uhubctl`, siempre que el hub soporte conmutación de energía por puerto.

CONFIGURACIÓN PENDIENTE (al llegar el ventilador):
  1. sudo apt install uhubctl
  2. Conectar el ventilador y ejecutar:
       python3 -m mantenimiento.ventilador --detectar
     (muestra los hubs/puertos; el del ventilador es el que aparece/desaparece
      al conectarlo y desconectarlo)
  3. Rellenar HUB_LOCATION y PUERTO aquí abajo.
  4. Probar de verdad:
       python3 -m mantenimiento.ventilador --off   ← ¿se detuvo el ventilador?
       python3 -m mantenimiento.ventilador --on
     ⚠️ Muchos hubs raíz Intel dicen soportar el corte pero NO cortan el VBUS
     físico. Si el ventilador no se detiene con --off, el puerto no es
     controlable: opciones = enchufarlo a un hub USB externo con conmutación
     real (ver lista de hubs compatibles en el README de uhubctl) o dejarlo
     siempre encendido (consume ~0.5 W, no pasa nada).
  5. Permisos sin root (una vez):
       sudo cp mantenimiento/52-usb-ventilador.rules /etc/udev/rules.d/
       sudo udevadm control --reload-rules && sudo udevadm trigger
       sudo usermod -aG dialout diego   (cerrar sesión y volver a entrar)
  6. Servicio automático:
       cp mantenimiento/cazador-ventilador.service ~/.config/systemd/user/
       systemctl --user daemon-reload
       systemctl --user enable --now cazador-ventilador.service

Lógica del daemon (histéresis para no encender/apagar en ráfagas):
  - CPU ≥ TEMP_ENCENDER → ventilador ON
  - CPU ≤ TEMP_APAGAR   → ventilador OFF
  - entre ambos umbrales → mantiene el estado actual
  - si el daemon muere/termina → deja el ventilador ENCENDIDO (fail-safe:
    ante la duda, enfriar)
"""

import argparse
import signal
import subprocess
import sys
import time

try:
    from mantenimiento.temperatura import leer_temperatura_cpu
except ImportError:  # ejecutado como script suelto desde mantenimiento/
    from temperatura import leer_temperatura_cpu

# ── CONFIG (rellenar al llegar el ventilador; ver instrucciones arriba) ───────
HUB_LOCATION = ""   # ej. "1-1" — salida de --detectar. Vacío = sin configurar.
PUERTO       = 0    # ej. 2 — puerto del hub donde está el ventilador.

TEMP_ENCENDER = 70.0   # °C — coincide con UMBRAL_BUENA del monitor
TEMP_APAGAR   = 58.0   # °C — margen amplio para no ciclar el ventilador
INTERVALO_SEG = 30     # mismo ritmo de muestreo que el monitor del ciclo


def _uhubctl(accion: str) -> bool:
    """accion: 'on' | 'off'. Devuelve True si uhubctl terminó bien."""
    if not HUB_LOCATION or not PUERTO:
        print("⚠️  Ventilador sin configurar: rellena HUB_LOCATION y PUERTO en "
              "mantenimiento/ventilador.py (ver instrucciones en el docstring).")
        return False
    try:
        res = subprocess.run(
            ["uhubctl", "-l", HUB_LOCATION, "-p", str(PUERTO), "-a", accion],
            capture_output=True, text=True, timeout=15,
        )
        if res.returncode != 0:
            print(f"❌ uhubctl falló: {res.stderr.strip() or res.stdout.strip()}")
            return False
        return True
    except FileNotFoundError:
        print("❌ uhubctl no está instalado: sudo apt install uhubctl")
        return False
    except subprocess.TimeoutExpired:
        print("❌ uhubctl no respondió (timeout)")
        return False


def encender() -> bool:
    ok = _uhubctl("on")
    if ok:
        print("🌀 Ventilador ENCENDIDO")
    return ok


def apagar() -> bool:
    ok = _uhubctl("off")
    if ok:
        print("💤 Ventilador apagado")
    return ok


def detectar():
    """Lista los hubs/puertos que uhubctl puede ver, para identificar el del ventilador."""
    try:
        res = subprocess.run(["uhubctl"], capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        print("❌ uhubctl no está instalado: sudo apt install uhubctl")
        return
    print(res.stdout or res.stderr)
    print("→ Conecta y desconecta el ventilador y vuelve a ejecutar --detectar:")
    print("  el puerto del ventilador es el que cambia entre ambas salidas.")
    print("  Luego rellena HUB_LOCATION (ej. '1-1') y PUERTO (ej. 2) en este archivo.")


def daemon():
    """Bucle infinito: enciende/apaga el ventilador según la temperatura del CPU."""
    encendido = None  # desconocido al arrancar

    def _salir(signum, frame):
        # Fail-safe: al terminar el daemon, dejar el ventilador encendido.
        print("Señal recibida — dejando el ventilador encendido (fail-safe) y saliendo.")
        _uhubctl("on")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _salir)
    signal.signal(signal.SIGINT, _salir)

    print(f"Daemon ventilador: ON ≥ {TEMP_ENCENDER}°C · OFF ≤ {TEMP_APAGAR}°C "
          f"· muestreo cada {INTERVALO_SEG}s")

    while True:
        temp = leer_temperatura_cpu()
        if temp is not None:
            if temp >= TEMP_ENCENDER and encendido is not True:
                print(f"🌡️ {temp:.1f}°C ≥ {TEMP_ENCENDER}°C")
                if encender():
                    encendido = True
            elif temp <= TEMP_APAGAR and encendido is not False:
                print(f"🌡️ {temp:.1f}°C ≤ {TEMP_APAGAR}°C")
                if apagar():
                    encendido = False
        time.sleep(INTERVALO_SEG)


def main():
    parser = argparse.ArgumentParser(description="Control del ventilador USB por temperatura")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--daemon", action="store_true", help="bucle automático por temperatura")
    grupo.add_argument("--on", action="store_true", help="encender el ventilador")
    grupo.add_argument("--off", action="store_true", help="apagar el ventilador")
    grupo.add_argument("--detectar", action="store_true", help="listar hubs/puertos para configurar")
    grupo.add_argument("--estado", action="store_true", help="temperatura actual del CPU")
    args = parser.parse_args()

    if args.daemon:
        daemon()
    elif args.on:
        sys.exit(0 if encender() else 1)
    elif args.off:
        sys.exit(0 if apagar() else 1)
    elif args.detectar:
        detectar()
    elif args.estado:
        temp = leer_temperatura_cpu()
        print(f"🌡️ CPU: {temp:.1f}°C" if temp is not None else "Sin sensores disponibles")


if __name__ == "__main__":
    main()
