"""
🛒 CAZADOR DE OFERTAS — Sistema Principal
Fecha de creación: 2026-03-28

Orquesta el ciclo completo:
  1. Ejecutar scrapers de cada tienda
  2. Registrar precios en el historial
  3. Analizar descuentos reales (analizador/)
  4. Detectar precios mínimos históricos (cazador_precios/)
  5. Enviar alertas por Telegram (telegram_bot/)
  6. Guardar log completo de la sesión (logger/)
  7. Regenerar el dashboard web (web/build_data.py)

Uso:
  python main.py          → Ejecutar un ciclo completo
"""

import sys
import os
import json
import signal
import tempfile
import traceback
import time
import subprocess
from datetime import datetime, timezone, timedelta

# Configurar path ANTES de cualquier otro import del proyecto
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

# ── Módulo 1: Logger (se inicializa PRIMERO — captura TODO lo que sigue) ─────
from logger.console_logger import configurar_logger, cerrar_logger
logger = configurar_logger()

# ── Módulos del proyecto ─────────────────────────────────────────────────────
from analizador.historial_precios import registrar_precios
from analizador.detector_descuentos import analizar_productos
from mantenimiento.limpieza import rotar_snapshots, rotar_logs
from mantenimiento.temperatura import MonitorTemperatura, leer_temperatura_cpu, UMBRAL_ALTA

# Al final del ciclo se avisa por Telegram que los datos están listos (SIEMPRE),
# independiente de TELEGRAM_HABILITADO (que controla las alertas de ofertas).
# El dashboard se enciende aparte con /startserver (ahorro de energía).
from telegram_bot.notificador import enviar_aviso_listo

# ── Módulo 2: Telegram (EN PAUSA — cambiar a True para reactivar) ────────────
TELEGRAM_HABILITADO = False

if TELEGRAM_HABILITADO:
    from telegram_bot.notificador import (
        enviar_alerta,
        enviar_minimos_historicos,
        enviar_resumen_ciclo,
    )

# ── Módulo 3: Cazador de precios mínimos ─────────────────────────────────────
from cazador_precios.cazador import analizar_minimos

TZ_PERU = timezone(timedelta(hours=-5))

# ── Tiendas registradas ──────────────────────────────────────────────────────
TIENDAS = [
    {
        "nombre": "Inkafarma",
        "scraper_dir": os.path.join(ROOT_DIR, "tiendas", "inkafarma"),
        "historial": os.path.join(ROOT_DIR, "tiendas", "inkafarma", "datos", "historial_precios.json"),
        "es_async": True,
    },
    {
        "nombre": "Plaza Vea",
        "scraper_dir": os.path.join(ROOT_DIR, "tiendas", "plaza_vea"),
        "historial": os.path.join(ROOT_DIR, "tiendas", "plaza_vea", "datos", "historial_precios.json"),
        "es_async": False,
        # Catálogo completo (~4300 peticiones) con 1 solo hilo: tarda ~90-120 min.
        "timeout_min": 150,
    },
    {
        "nombre": "Saga Falabella",
        "scraper_dir": os.path.join(ROOT_DIR, "tiendas", "saga_falabella"),
        "historial": os.path.join(ROOT_DIR, "tiendas", "saga_falabella", "datos", "historial_precios.json"),
        "es_async": False,
    },
    {
        "nombre": "Dermo",
        "scraper_dir": os.path.join(ROOT_DIR, "tiendas", "dermo"),
        "historial": os.path.join(ROOT_DIR, "tiendas", "dermo", "datos", "historial_precios.json"),
        "es_async": False,
    },
    {
        "nombre": "EFE",
        "scraper_dir": os.path.join(ROOT_DIR, "tiendas", "efe"),
        "historial": os.path.join(ROOT_DIR, "tiendas", "efe", "datos", "historial_precios.json"),
        "es_async": False,
    },
    {
        "nombre": "Shopstar",
        "scraper_dir": os.path.join(ROOT_DIR, "tiendas", "shopstar"),
        "historial": os.path.join(ROOT_DIR, "tiendas", "shopstar", "datos", "historial_precios.json"),
        "es_async": False,
    },
    {
        "nombre": "Sodimac",
        "scraper_dir": os.path.join(ROOT_DIR, "tiendas", "sodimac"),
        "historial": os.path.join(ROOT_DIR, "tiendas", "sodimac", "datos", "historial_precios.json"),
        "es_async": False,
    },
    {
        "nombre": "Tailoy",
        "scraper_dir": os.path.join(ROOT_DIR, "tiendas", "tailoy"),
        "historial": os.path.join(ROOT_DIR, "tiendas", "tailoy", "datos", "historial_precios.json"),
        "es_async": False,
    },
    {
        "nombre": "Promart",
        "scraper_dir": os.path.join(ROOT_DIR, "tiendas", "promart"),
        "historial": os.path.join(ROOT_DIR, "tiendas", "promart", "datos", "historial_precios.json"),
        "es_async": False,
    },
]


# Tiempo máximo por tienda. Si un scraper se cuelga, se mata su proceso (y todos
# sus Chrome) y el ciclo continúa con la siguiente tienda. Con 9 tiendas, el total
# queda holgadamente por debajo del TimeoutStartSec=2h del systemd service.
TIMEOUT_TIENDA_SEG = 30 * 60

# Respiro entre tiendas: deja enfriar el CPU de la mini PC entre picos de trabajo
# y separa claramente las peticiones de una tienda de las de la siguiente.
PAUSA_ENTRE_TIENDAS_SEG = 10 * 60

# Freno de emergencia térmico: si el CPU se mantiene en zona crítica (dos
# lecturas seguidas, para ignorar picos sueltos), se mata el scraper de la
# tienda actual y el ciclo continúa con la siguiente — la pausa entre tiendas
# se encarga de enfriar. UMBRAL_ALTA (85 °C) es la zona 🔴 del monitor.
TEMP_ABORTAR_TIENDA      = UMBRAL_ALTA
VIGILANCIA_INTERVALO_SEG = 10

# Freno térmico SUAVE: mucho antes de la zona crítica, si el CPU alcanza la
# zona 🟡 se congela el scraper (SIGSTOP a todo su grupo de procesos) y se
# reanuda (SIGCONT) cuando enfría. Con histéresis: pausar a 72 °C y reanudar
# recién a 62 °C evita oscilar pausa/reanuda cada pocos segundos. El tiempo
# congelado NO cuenta para el timeout de la tienda. Si tras PAUSA_FRIA_MAX_SEG
# el CPU no bajó (algo externo lo calienta), se reanuda igual: el freno duro
# de 85 °C sigue vigilando detrás.
TEMP_PAUSAR_TIENDA   = 72.0
TEMP_REANUDAR_TIENDA = 62.0
PAUSA_FRIA_MAX_SEG   = 15 * 60

# El ciclo deja este lockfile mientras corre; el bot de Telegram lo consulta
# para rechazar /startserver hasta que terminen todas las tiendas.
CICLO_LOCK = os.path.join(ROOT_DIR, ".ciclo_en_curso")

RUNNER = os.path.join(ROOT_DIR, "runner_tienda.py")


def ejecutar_scraper(tienda: dict) -> list:
    """Ejecuta el scraper de una tienda EN UN SUBPROCESO AISLADO y retorna sus productos.

    Cada tienda corre en su propio proceso Python (runner_tienda.py). Al terminar,
    el sistema operativo recupera el 100% de su memoria —incluidos todos los Chrome
    que haya levantado— de forma garantizada. Así el pico de RAM es "una tienda a la
    vez" en vez de irse acumulando las 9 en un mismo proceso (lo que provocaba que el
    kernel matara el ciclo entero por OOM en la mini PC de 8 GB).
    """
    es_async = "1" if tienda.get("es_async") else "0"
    scraper_dir = tienda["scraper_dir"]
    timeout_seg = tienda.get("timeout_min", TIMEOUT_TIENDA_SEG // 60) * 60

    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="cazador_")
    os.close(fd)

    # La salida del scraper va a un archivo temporal (no a un PIPE): así el bucle
    # de vigilancia puede dormir sin que el hijo se bloquee por tubería llena.
    fd_log, log_path = tempfile.mkstemp(suffix=".out", prefix="cazador_")
    salida_f = os.fdopen(fd_log, "w", encoding="utf-8", errors="replace")

    # start_new_session=True coloca al runner (y a sus Chrome) en su propio grupo de
    # procesos, para poder matar TODO el árbol de una sola vez si hay que abortar.
    proc = subprocess.Popen(
        [sys.executable, RUNNER, scraper_dir, es_async, out_path],
        stdout=salida_f,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    try:
        # ── Vigilancia: timeout + freno de emergencia térmico ────────────────
        inicio = time.monotonic()
        seg_pausado = 0.0          # tiempo con el scraper congelado (no cuenta para el timeout)
        lecturas_criticas = 0
        motivo_aborto = None
        while proc.poll() is None:
            if time.monotonic() - inicio - seg_pausado >= timeout_seg:
                motivo_aborto = f"⏱️  Timeout ({timeout_seg // 60} min)"
                break
            temp = leer_temperatura_cpu()
            if temp is not None and temp >= TEMP_ABORTAR_TIENDA:
                lecturas_criticas += 1
                if lecturas_criticas >= 2:
                    motivo_aborto = (f"🔥 Temperatura crítica sostenida "
                                     f"({temp:.0f}°C ≥ {TEMP_ABORTAR_TIENDA:.0f}°C)")
                    break
            else:
                lecturas_criticas = 0

            # ── Freno suave: congelar el scraper hasta que el CPU enfríe ─────
            if temp is not None and temp >= TEMP_PAUSAR_TIENDA:
                seg_pausado += _enfriar_scraper(proc, temp)
                continue  # re-evaluar timeout/temperatura ya mismo, sin dormir extra

            time.sleep(VIGILANCIA_INTERVALO_SEG)

        # Reemitir la salida del subproceso para que el logger (Tee de stdout) la guarde.
        salida_f.flush()
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                salida = f.read()
            if salida:
                print(salida, end="" if salida.endswith("\n") else "\n")
        except OSError:
            pass

        if motivo_aborto:
            print(f"    {motivo_aborto} — scraper terminado, se continúa con la siguiente tienda")
            return []
        if proc.returncode != 0:
            print(f"    ⚠️  El scraper terminó con código {proc.returncode}")

        try:
            with open(out_path, "r", encoding="utf-8") as f:
                productos = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            productos = []
        return productos if productos else []
    finally:
        # Barrer SIEMPRE el árbol de procesos del runner. start_new_session=True hizo
        # que el runner sea líder de su grupo (PGID == su PID), así que esto mata de un
        # golpe cualquier Chrome/chromedriver que el scraper dejara abierto —Playwright y
        # Selenium no siempre cierran todo—. Sin esto, esos navegadores quedan huérfanos,
        # vivos y consumiendo RAM tienda tras tienda (la causa de los Chrome zombie).
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        try:
            salida_f.close()
        except OSError:
            pass
        _borrar_silencioso(out_path)
        _borrar_silencioso(log_path)


def _borrar_silencioso(ruta: str):
    try:
        os.unlink(ruta)
    except OSError:
        pass


def _enfriar_scraper(proc, temp_actual: float) -> float:
    """Congela el grupo de procesos del scraper (SIGSTOP) hasta que el CPU baje
    a TEMP_REANUDAR_TIENDA, y lo reanuda (SIGCONT). Devuelve los segundos que
    estuvo congelado, para descontarlos del timeout de la tienda.

    Un proceso congelado no ejecuta nada, así que el CPU enfría igual que en la
    pausa entre tiendas; las conexiones que se caigan durante la congelación
    las absorben los reintentos que ya tiene cada scraper."""
    print(f"    🧊 CPU {temp_actual:.0f}°C ≥ {TEMP_PAUSAR_TIENDA:.0f}°C — scraper en pausa "
          f"hasta enfriar a ≤{TEMP_REANUDAR_TIENDA:.0f}°C", flush=True)
    try:
        os.killpg(proc.pid, signal.SIGSTOP)
    except (ProcessLookupError, PermissionError):
        return 0.0

    inicio_pausa = time.monotonic()
    try:
        while time.monotonic() - inicio_pausa < PAUSA_FRIA_MAX_SEG:
            time.sleep(VIGILANCIA_INTERVALO_SEG)
            temp = leer_temperatura_cpu()
            if temp is None or temp <= TEMP_REANUDAR_TIENDA:
                break
    finally:
        # Reanudar SIEMPRE, pase lo que pase: un scraper congelado para
        # siempre sería peor que el calor.
        try:
            os.killpg(proc.pid, signal.SIGCONT)
        except (ProcessLookupError, PermissionError):
            pass

    pausado = time.monotonic() - inicio_pausa
    temp = leer_temperatura_cpu()
    temp_txt = f"{temp:.0f}°C" if temp is not None else "s/d"
    print(f"    ▶️  Scraper reanudado tras {pausado / 60:.1f} min de enfriamiento "
          f"(CPU {temp_txt})", flush=True)
    return pausado


# ── Gangas del día para el aviso de Telegram ─────────────────────────────────
# Del cazador de mínimos (caídas validadas contra NUESTRO historial, no contra
# lo que declara la tienda) se seleccionan las mejores del ciclo para incluirlas
# en el aviso diario. Los favoritos entran con barra más baja y con prioridad.
MAX_GANGAS_AVISO = 5
UMBRAL_GANGA_AVISO = 20.0  # % mínimo bajo el precio típico para no-favoritos
MAX_AHORRO_CREIBLE = 90.0  # % — por encima casi siempre es un error de datos
                           # (precio placeholder de la tienda, id corrupto, etc.),
                           # no una ganga real. Mejor no publicarla en Telegram.


def _cargar_favoritos(tienda: dict) -> set:
    """IDs favoritos de una tienda (tiendas/<t>/datos/favoritos.json)."""
    ruta = os.path.join(os.path.dirname(tienda["historial"]), "favoritos.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return {str(x) for x in json.load(f)}
    except (OSError, json.JSONDecodeError):
        return set()


def _gangas_de_tienda(minimos: list, favoritos: set, nombre_tienda: str) -> list:
    """Filtra los mínimos del cazador que califican como ganga para el aviso.

    Califican: nuevos mínimos históricos, caídas >= UMBRAL_GANGA_AVISO vs el
    precio típico, y cualquier favorito que el cazador haya reportado."""
    gangas = []
    for m in minimos:
        es_favorito = str(m.get("id")) in favoritos
        ahorro = m.get("ahorro_vs_mediana") or 0
        if not (m.get("es_nuevo_minimo") or ahorro >= UMBRAL_GANGA_AVISO or es_favorito):
            continue
        if ahorro > MAX_AHORRO_CREIBLE:
            print(f"    🚫 Ganga descartada por inverosímil (-{ahorro:.0f}%): "
                  f"{(m.get('nombre') or '')[:50]}")
            continue
        gangas.append({
            "nombre":            m.get("nombre", ""),
            "tienda":            nombre_tienda,
            "precio_hoy":        m.get("precio_hoy"),
            "precio_mediana":    m.get("precio_mediana"),
            "ahorro_vs_mediana": ahorro,
            "es_nuevo_minimo":   m.get("es_nuevo_minimo", False),
            "es_favorito":       es_favorito,
            "emoji":             m.get("emoji", "📉"),
            "url":               m.get("url", ""),
        })
    return gangas


def ciclo_completo():
    """Ejecuta un ciclo completo: scrape → historial → análisis → cazador → telegram."""
    inicio_ciclo = time.time()
    ahora = datetime.now(TZ_PERU)

    print(f"\n{'═' * 60}")
    print(f"  🛒 CAZADOR DE OFERTAS — {ahora.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 60}")

    # Contadores globales del ciclo (para el resumen Telegram)
    resumen_total = {
        "tiendas_procesadas": 0,
        "total_productos": 0,
        "total_ofertas_reales": 0,
        "total_minimos": 0,
        "duracion_seg": 0,
        "fecha": ahora.strftime("%d/%m/%Y %H:%M"),
    }

    # Monitorear temperatura del CPU durante todo el ciclo (muestreo cada 30 s)
    monitor_temp = MonitorTemperatura()
    monitor_temp.iniciar()

    # Gangas acumuladas de todas las tiendas (para el aviso de Telegram)
    gangas_ciclo = []

    total_tiendas = len(TIENDAS)

    for idx, tienda in enumerate(TIENDAS, 1):
        nombre = tienda["nombre"]

        if idx > 1:
            # Cerrar el segmento térmico ANTES de la pausa: el enfriamiento de
            # los 10 min no debe contar como "mínimo" de la tienda anterior.
            monitor_temp.cerrar_segmento()
            time.sleep(PAUSA_ENTRE_TIENDAS_SEG)

        print(f"\n  [{idx}/{total_tiendas}] 🏪 {nombre}")
        monitor_temp.iniciar_segmento(nombre)

        # ── 1. Scraping ──────────────────────────────────────────────────────
        try:
            productos = ejecutar_scraper(tienda)

            if not productos:
                print(f"    ❌ Sin productos")
                continue

            print(f"    ✅ {len(productos)} productos")
            resumen_total["total_productos"] += len(productos)
        except Exception as e:
            print(f"    ❌ Error scraping: {e}")
            traceback.print_exc()
            continue

        # ── 2. Registrar en historial ────────────────────────────────────────
        # Nos quedamos con el dict que devuelve registrar_precios: el analizador
        # y el cazador lo reciben ya cargado, en vez de re-parsear cada uno el
        # JSON desde disco (el de Plaza Vea pesa ~475 MB; parsearlo 3 veces por
        # ciclo era uno de los picos de temperatura de la mini PC).
        historial_cargado = None
        try:
            historial_cargado = registrar_precios(productos, tienda["historial"])
        except Exception as e:
            print(f"    ❌ Error historial: {e}")
            traceback.print_exc()

        # ── 2b. Rotar snapshots: conservar solo el último de esta tienda ─────
        #   build_data.py solo usa el snapshot más reciente; los precios ya
        #   quedaron guardados en el historial. Evita que el disco crezca sin
        #   límite (antes plaza_vea sola acumulaba ~2 GB de snapshots viejos).
        try:
            datos_dir = os.path.dirname(tienda["historial"])
            prefijo = os.path.basename(tienda["scraper_dir"])
            borrados, liberado = rotar_snapshots(datos_dir, prefijo, conservar=1)
            if borrados:
                print(f"    🧹 {borrados} snapshot(s) antiguo(s) eliminado(s) ({liberado/1_048_576:.1f} MB)")
        except Exception as e:
            print(f"    ⚠️  Error rotando snapshots: {e}")

        # ── 3. Analizar descuentos de la tienda ──────────────────────────────
        ofertas = []
        try:
            ofertas = analizar_productos(productos, tienda["historial"],
                                         historial=historial_cargado)

            if ofertas:
                reales = sum(1 for o in ofertas if o["clasificacion"] in ("REAL", "GRAN_OFERTA"))
                resumen_total["total_ofertas_reales"] += reales
        except Exception as e:
            print(f"    ❌ Error análisis: {e}")
            traceback.print_exc()

        # ── 4. Cazador de precios mínimos históricos ─────────────────────────
        minimos = []
        try:
            minimos = analizar_minimos(productos, tienda["historial"],
                                       historial=historial_cargado)
            resumen_total["total_minimos"] += len(minimos)
        except Exception as e:
            print(f"    ❌ Error cazador: {e}")
            traceback.print_exc()

        # Soltar el historial ya: que la RAM (hasta ~2 GB con Plaza Vea) no
        # quede retenida durante la pausa de 10 min ni la siguiente tienda.
        historial_cargado = None

        # ── 4b. Acumular gangas del día para el aviso de Telegram ────────────
        try:
            gangas_ciclo.extend(_gangas_de_tienda(minimos, _cargar_favoritos(tienda), nombre))
        except Exception as e:
            print(f"    ⚠️  Error acumulando gangas: {e}")

        # ── Telegram: alertas de esta tienda (EN PAUSA) ──────────────────────
        if TELEGRAM_HABILITADO:
            try:
                if ofertas:
                    enviar_alerta(ofertas, nombre)
                if minimos:
                    enviar_minimos_historicos(minimos, nombre)
            except Exception as e:
                print(f"    ❌ Error Telegram: {e}")
                traceback.print_exc()

        resumen_total["tiendas_procesadas"] += 1

    # ── Resumen final del ciclo ───────────────────────────────────────────────
    resumen_total["duracion_seg"] = round(time.time() - inicio_ciclo, 1)

    try:
        stats_temp = monitor_temp.detener()
    except Exception as e:
        stats_temp = None
        print(f"  ⚠️  Error midiendo temperatura: {e}")
    if stats_temp:
        resumen_total["temperatura"] = stats_temp

    # Top gangas del ciclo: favoritos primero, luego por caída vs precio típico.
    # Deduplicado por producto (el mismo puede llegar varias veces si aparece en
    # más de una categoría de la tienda).
    gangas_ciclo.sort(key=lambda g: (not g["es_favorito"], -g["ahorro_vs_mediana"]))
    vistos_ganga = set()
    top_gangas = []
    for g in gangas_ciclo:
        clave = (g.get("tienda"), g.get("url") or g.get("nombre"))
        if clave in vistos_ganga:
            continue
        vistos_ganga.add(clave)
        top_gangas.append(g)
        if len(top_gangas) == MAX_GANGAS_AVISO:
            break
    resumen_total["gangas"] = top_gangas

    print(f"\n{'═' * 60}")
    print(f"  ✅ Ciclo completado — {datetime.now(TZ_PERU).strftime('%H:%M:%S')}")
    print(f"  🏪 {resumen_total['tiendas_procesadas']} tiendas | 📦 {resumen_total['total_productos']} prods | 🟢 {resumen_total['total_ofertas_reales']} ofertas | 🎯 {resumen_total['total_minimos']} mínimos | ⏱️ {resumen_total['duracion_seg']}s")
    if stats_temp:
        hora_pico = f" a las {stats_temp['max_hora']}" if stats_temp.get("max_hora") else ""
        print(f"  🌡️ CPU: máx {stats_temp['max']}°C{hora_pico} | prom {stats_temp['promedio']}°C | {stats_temp['emoji']} {stats_temp['diagnostico']} ({stats_temp['muestras']} muestras)")
        for seg in stats_temp.get("tiendas", []):
            pico_seg = f", pico {seg['max_hora']}" if seg.get("max_hora") else ""
            print(f"      · {seg['nombre']}: {seg['min']}–{seg['max']}°C ({seg['muestras']} muestras{pico_seg})")
    print(f"{'═' * 60}")

    # Enviar resumen global por Telegram (EN PAUSA)
    if TELEGRAM_HABILITADO:
        try:
            enviar_resumen_ciclo(resumen_total)
        except Exception as e:
            print(f"  ❌ Error enviando resumen Telegram: {e}")

    # ── Paso 7: Regenerar dashboard web ──────────────────────────────────────
    print(f"\n{'─' * 50}")
    print(f"  🌐 Actualizando dashboard web...")
    try:
        build_script = os.path.join(ROOT_DIR, "web", "build_data.py")
        result = subprocess.run(
            [sys.executable, build_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode == 0:
            print(f"  ✅ Dashboard web actualizado correctamente")
        else:
            print(f"  ❌ Error al actualizar el dashboard web:")
            print(result.stderr)
    except Exception as e:
        print(f"  ❌ Error ejecutando build_data.py: {e}")
        traceback.print_exc()

    # ── Paso 8: Avisar por Telegram que los datos están listos ───────────────
    #   No se enciende el dashboard (ahorro de energía): el usuario lo abre
    #   cuando quiera con /startserver (lo maneja telegram_bot/bot_comandos.py).
    print(f"\n{'─' * 50}")
    print(f"  📲 Avisando por Telegram que los datos están listos...")
    try:
        enviar_aviso_listo(resumen_total)
    except Exception as e:
        print(f"  ❌ Error enviando aviso por Telegram: {e}")
        traceback.print_exc()

    # ── Rotar logs de sesión: conservar solo los más recientes ───────────────
    try:
        b_logs, _ = rotar_logs()
        if b_logs:
            print(f"  🧹 {b_logs} log(s) de sesión antiguo(s) eliminado(s)")
    except Exception as e:
        print(f"  ⚠️  Error rotando logs: {e}")

    # Cerrar el logger al final (escribe pie del log y cierra el archivo)
    cerrar_logger()


if __name__ == "__main__":
    # Lockfile con el PID del ciclo: el bot de Telegram lo usa para rechazar
    # /startserver mientras las tiendas siguen scrapeando (y para detectar
    # locks huérfanos si el ciclo murió sin limpiar).
    try:
        with open(CICLO_LOCK, "w") as _f:
            _f.write(str(os.getpid()))
    except OSError:
        pass
    try:
        ciclo_completo()
    finally:
        _borrar_silencioso(CICLO_LOCK)
