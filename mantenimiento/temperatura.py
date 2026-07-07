"""
Monitor de temperatura del CPU durante el ciclo de scraping.

Muestrea /sys/class/thermal cada INTERVALO_SEG segundos en un hilo daemon
y acumula máxima/promedio. Al final, resumen() devuelve las estadísticas
listas para incluir en el aviso de Telegram.

Uso desde main.py:
    from mantenimiento.temperatura import MonitorTemperatura

    monitor = MonitorTemperatura()
    monitor.iniciar()
    ...ciclo de scraping...
    stats = monitor.detener()   # None si no hay sensores disponibles
"""

import glob
import threading
import time

INTERVALO_SEG = 30

# Umbrales de diagnóstico (°C) para el CPU del mini PC.
# Los Intel empiezan a hacer throttling cerca de 95-100 °C; sostener >85 °C
# durante los escaneos acorta la vida útil del equipo.
UMBRAL_BUENA = 70.0
UMBRAL_ALTA = 85.0

# Zona preferida: temperatura del paquete del CPU (la que sube con Chrome).
_ZONA_PREFERIDA = "x86_pkg_temp"


def _leer_zonas() -> dict:
    """Lee todas las zonas térmicas disponibles. {tipo: °C}"""
    zonas = {}
    for ruta in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            with open(f"{ruta}/type") as f:
                tipo = f.read().strip()
            with open(f"{ruta}/temp") as f:
                zonas[tipo] = int(f.read().strip()) / 1000.0
        except (OSError, ValueError):
            continue
    return zonas


def leer_temperatura_cpu() -> float | None:
    """Temperatura actual del CPU en °C, o None si no hay sensores."""
    zonas = _leer_zonas()
    if not zonas:
        return None
    return zonas.get(_ZONA_PREFERIDA, max(zonas.values()))


def diagnosticar(temp_max: float) -> tuple[str, str]:
    """(emoji, etiqueta) según la temperatura máxima alcanzada."""
    if temp_max < UMBRAL_BUENA:
        return "🟢", "Buena"
    if temp_max < UMBRAL_ALTA:
        return "🟡", "Alta"
    return "🔴", "Crítica"


class MonitorTemperatura:
    """Muestrea la temperatura del CPU en segundo plano durante el ciclo."""

    def __init__(self, intervalo_seg: float = INTERVALO_SEG):
        self._intervalo = intervalo_seg
        self._detener = threading.Event()
        self._hilo = None
        self._muestras = []
        self._lock = threading.Lock()
        self._max_temp = None       # máxima del ciclo y hora en que ocurrió
        self._max_hora = None
        self._segmentos = []        # [{"nombre", "muestras": [°C, ...], "max_temp", "max_hora"}]
        self._segmento_actual = None

    def _muestrear(self):
        temp = leer_temperatura_cpu()
        if temp is not None:
            hora = time.strftime("%H:%M:%S")
            with self._lock:
                self._muestras.append(temp)
                if self._max_temp is None or temp > self._max_temp:
                    self._max_temp, self._max_hora = temp, hora
                seg = self._segmento_actual
                if seg is not None:
                    seg["muestras"].append(temp)
                    if seg["max_temp"] is None or temp > seg["max_temp"]:
                        seg["max_temp"], seg["max_hora"] = temp, hora

    def iniciar_segmento(self, nombre: str):
        """Empieza a atribuir las muestras a un segmento (p. ej. una tienda).

        Toma una muestra inmediata para que hasta el segmento más corto tenga
        al menos una lectura. Abrir un segmento cierra el anterior."""
        with self._lock:
            self._segmento_actual = {"nombre": nombre, "muestras": [],
                                     "max_temp": None, "max_hora": None}
            self._segmentos.append(self._segmento_actual)
        self._muestrear()

    def cerrar_segmento(self):
        """Cierra el segmento actual (muestra final incluida). Las muestras
        posteriores solo cuentan para el total del ciclo."""
        self._muestrear()
        with self._lock:
            self._segmento_actual = None

    def resumen_segmentos(self) -> list:
        """[{nombre, max, max_hora, min, muestras}] de cada segmento con lecturas."""
        with self._lock:
            segmentos = [dict(s, muestras=list(s["muestras"])) for s in self._segmentos]
        resumen = []
        for s in segmentos:
            if not s["muestras"]:
                continue
            resumen.append({
                "nombre":   s["nombre"],
                "max":      round(max(s["muestras"]), 1),
                "max_hora": s["max_hora"],
                "min":      round(min(s["muestras"]), 1),
                "muestras": len(s["muestras"]),
            })
        return resumen

    def _bucle(self):
        while not self._detener.wait(self._intervalo):
            self._muestrear()

    def iniciar(self):
        self._muestrear()  # lectura inicial inmediata
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def detener(self) -> dict | None:
        """Detiene el muestreo y devuelve las estadísticas del ciclo.

        Devuelve None si no se pudo leer ningún sensor (p. ej. sin /sys)."""
        self._detener.set()
        if self._hilo is not None:
            self._hilo.join(timeout=5)
        self._muestrear()  # lectura final

        if not self._muestras:
            return None

        temp_max = max(self._muestras)
        emoji, etiqueta = diagnosticar(temp_max)
        return {
            "max": round(temp_max, 1),
            "max_hora": self._max_hora,
            "promedio": round(sum(self._muestras) / len(self._muestras), 1),
            "muestras": len(self._muestras),
            "emoji": emoji,
            "diagnostico": etiqueta,
            "tiendas": self.resumen_segmentos(),
        }
