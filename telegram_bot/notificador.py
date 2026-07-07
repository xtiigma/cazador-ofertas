"""
Telegram - Notificador de Ofertas
==================================

Envia alertas de ofertas reales a Telegram via Bot API.
Cada mensaje enviado queda registrado localmente en telegram_bot/registro/

Uso desde main.py / analizar_ahora.py:
    from telegram_bot import enviar_alerta, enviar_resumen_ciclo
    from telegram_bot.notificador import enviar_comparacion

    enviar_alerta(ofertas, nombre_tienda="Inkafarma")
    enviar_minimos_historicos(minimos, nombre_tienda="Plaza Vea")
    enviar_comparacion(comparaciones)
    enviar_resumen_ciclo(resumen_total)
"""

import urllib.request
import urllib.parse
import urllib.error
import json
from datetime import datetime, timezone, timedelta

TZ_PERU = timezone(timedelta(hours=-5))

# -- Importar config ----------------------------------------------------------
try:
    from telegram_bot.config import (
        BOT_TOKEN,
        CHAT_ID,
        MIN_DESCUENTO_TELEGRAM,
        MAX_PRODUCTOS_POR_MENSAJE,
        CLASIFICACIONES_PERMITIDAS,
        INCLUIR_DUDOSOS,
    )
except ImportError:
    BOT_TOKEN = ""
    CHAT_ID = ""
    MIN_DESCUENTO_TELEGRAM = 15.0
    MAX_PRODUCTOS_POR_MENSAJE = 5
    CLASIFICACIONES_PERMITIDAS = ("GRAN_OFERTA", "REAL", "NUEVO")
    INCLUIR_DUDOSOS = False

# -- Importar registro local --------------------------------------------------
try:
    from telegram_bot.registro.registro_mensajes import registrar_mensaje
    _REGISTRO_DISPONIBLE = True
except ImportError:
    _REGISTRO_DISPONIBLE = False
    def registrar_mensaje(*args, **kwargs):
        pass


# ── Helpers internos ─────────────────────────────────────────────────────────

def _esta_configurado() -> bool:
    if not BOT_TOKEN or not BOT_TOKEN.strip():
        return False
    if not CHAT_ID or not CHAT_ID.strip():
        return False
    return True


def _enviar_mensaje(texto: str) -> bool:
    """Envia un mensaje de texto plano/Markdown a Telegram."""
    if not _esta_configurado():
        print("  [!] [Telegram] No configurado - edita telegram_bot/config.py con tu BOT_TOKEN y CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    datos = {
        "chat_id": CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        datos_encoded = urllib.parse.urlencode(datos).encode("utf-8")
        req = urllib.request.Request(url, data=datos_encoded, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with urllib.request.urlopen(req, timeout=10) as resp:
            respuesta = json.loads(resp.read().decode("utf-8"))
            if respuesta.get("ok"):
                return True
            else:
                print(f"  [ERROR] [Telegram] Error API: {respuesta.get('description', 'Desconocido')}")
                return False

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"  [ERROR] [Telegram] HTTP {e.code}: {body[:200]}")
        return False
    except urllib.error.URLError as e:
        print(f"  [ERROR] [Telegram] Error de red: {e.reason}")
        return False
    except Exception as e:
        print(f"  [ERROR] [Telegram] Error inesperado: {e}")
        return False


# ── Formateadores de mensajes ─────────────────────────────────────────────────

def _fmt_oferta(oferta: dict, numero: int) -> str:
    emoji      = oferta.get("emoji", "[*]")
    nombre     = oferta.get("nombre", "Producto desconocido")[:60]
    precio_n   = oferta.get("precio_normal", 0)
    precio_a   = oferta.get("precio_actual", 0)
    descuento  = oferta.get("descuento_porcent", 0)
    ahorro     = oferta.get("ahorro", 0)
    url        = oferta.get("url", "")
    razon      = oferta.get("razon", "")

    lineas = [
        f"*{numero}. {emoji} {nombre}*",
        f"   ~~S/{precio_n:.2f}~~ -> *S/{precio_a:.2f}* (-{descuento:.1f}%)",
        f"   Ahorro: S/{ahorro:.2f}",
    ]
    if razon:
        lineas.append(f"   _{razon[:80]}_")
    if url:
        lineas.append(f"   [Ver producto]({url})")
    return "\n".join(lineas)


def _fmt_minimo(producto: dict, numero: int) -> str:
    nombre         = producto.get("nombre", "Producto")[:60]
    precio_hoy     = producto.get("precio_hoy", 0)
    precio_min_ant = producto.get("precio_minimo_anterior", 0)
    # Mediana = precio típico (con fallback al promedio para datos antiguos)
    precio_tipico  = producto.get("precio_mediana") or producto.get("precio_promedio", 0)
    ahorro_pct     = producto.get("ahorro_vs_mediana") or producto.get("ahorro_vs_promedio", 0)
    num_reg        = producto.get("num_registros", 0)
    url            = producto.get("url", "")
    clasificacion  = producto.get("clasificacion", "")
    tag = "[NUEVO MINIMO]" if clasificacion == "MINIMO_HISTORICO" else "[PRECIO BAJO]"

    lineas = [
        f"*{numero}. {tag} {nombre}*",
        f"   Hoy: *S/{precio_hoy:.2f}*  |  Min anterior: S/{precio_min_ant:.2f}",
        f"   Precio tipico historico: S/{precio_tipico:.2f}  ({ahorro_pct:.1f}% menos)",
        f"   Basado en {num_reg} registros propios",
    ]
    if url:
        lineas.append(f"   [Ver producto]({url})")
    return "\n".join(lineas)


def _fmt_comparacion(comp: dict, numero: int) -> str:
    nombre    = comp.get("nombre_referencia", "Producto")[:60]
    barata    = comp.get("tienda_mas_barata", "?")
    min_p     = comp.get("precio_min_mas_barato", 0)
    dif_pct   = comp.get("diferencia_porcent", 0)
    ahorro    = comp.get("ahorro_absoluto", 0)
    tiendas   = comp.get("tiendas", [])

    lineas = [f"*{numero}. {nombre}*"]
    for t in tiendas:
        prefijo = "->" if t["nombre_tienda"] == barata else "  "
        pmin    = t.get("precio_minimo", 0)
        pprom   = t.get("precio_promedio") or 0
        nreg    = t.get("num_registros", 0)
        lineas.append(
            f"   {prefijo} *{t['nombre_tienda']}*: min S/{pmin:.2f} | prom S/{pprom:.2f} ({nreg} reg)"
        )

    lineas.append(f"   [MAS BARATO EN {barata.upper()}] S/{ahorro:.2f} menos ({dif_pct:.1f}%)")
    return "\n".join(lineas)


# ── Funciones publicas de envio ───────────────────────────────────────────────

def enviar_alerta(ofertas: list, nombre_tienda: str) -> bool:
    """Envia el top de ofertas de una tienda y registra el mensaje localmente."""
    if not _esta_configurado():
        print("  [!] [Telegram] No configurado - edita telegram_bot/config.py")
        return False

    if not ofertas:
        return True

    # Filtrar
    ofertas_filtradas = [
        o for o in ofertas
        if o.get("clasificacion") in CLASIFICACIONES_PERMITIDAS
        and o.get("descuento_porcent", 0) >= MIN_DESCUENTO_TELEGRAM
    ]

    if not ofertas_filtradas:
        print(f"  [i] [Telegram] Sin ofertas calificadas de {nombre_tienda}")
        registrar_mensaje("OFERTA", nombre_tienda, [], False, 0)
        return True

    ahora = datetime.now(TZ_PERU).strftime("%d/%m/%Y %H:%M")
    top   = ofertas_filtradas[:MAX_PRODUCTOS_POR_MENSAJE]

    lineas = [
        f"CAZADOR DE OFERTAS - {nombre_tienda.upper()}",
        f"Fecha: {ahora} (Peru)",
        "",
        f"Top {len(top)} ofertas detectadas:",
        "",
    ]
    for i, o in enumerate(top, 1):
        lineas.append(_fmt_oferta(o, i))
        lineas.append("")

    texto = "\n".join(lineas)
    exito = _enviar_mensaje(texto)

    registrar_mensaje(
        tipo="OFERTA",
        tienda=nombre_tienda,
        contenido=[{
            "nombre": o.get("nombre"),
            "clasificacion": o.get("clasificacion"),
            "precio_normal": o.get("precio_normal"),
            "precio_actual": o.get("precio_actual"),
            "descuento_porcent": o.get("descuento_porcent"),
            "ahorro": o.get("ahorro"),
            "razon": o.get("razon"),
            "url": o.get("url"),
        } for o in top],
        enviado_ok=exito,
        num_items=len(top),
    )

    if exito:
        print(f"  [OK] [Telegram] Alerta enviada: {len(top)} ofertas de {nombre_tienda}")
    return exito


def enviar_minimos_historicos(minimos: list, nombre_tienda: str) -> bool:
    """Envia los precios minimos historicos del cazador y registra localmente."""
    if not _esta_configurado():
        return False
    if not minimos:
        return True

    ahora = datetime.now(TZ_PERU).strftime("%d/%m/%Y %H:%M")
    top   = minimos[:MAX_PRODUCTOS_POR_MENSAJE]

    lineas = [
        f"PRECIOS MINIMOS HISTORICOS - {nombre_tienda.upper()}",
        f"Fecha: {ahora} (Peru)",
        "",
        f"Precios mas bajos segun NUESTRO historial ({len(top)} encontrados):",
        "",
    ]
    for i, m in enumerate(top, 1):
        lineas.append(_fmt_minimo(m, i))
        lineas.append("")

    texto = "\n".join(lineas)
    exito = _enviar_mensaje(texto)

    registrar_mensaje(
        tipo="MINIMO_HISTORICO",
        tienda=nombre_tienda,
        contenido=[{
            "nombre":               m.get("nombre"),
            "clasificacion":        m.get("clasificacion"),
            "precio_hoy":           m.get("precio_hoy"),
            "precio_minimo_anterior": m.get("precio_minimo_anterior"),
            "precio_promedio":      m.get("precio_promedio"),
            "precio_mediana":       m.get("precio_mediana"),
            "ahorro_vs_promedio":   m.get("ahorro_vs_promedio"),
            "ahorro_vs_mediana":    m.get("ahorro_vs_mediana"),
            "es_nuevo_minimo":      m.get("es_nuevo_minimo"),
            "num_registros":        m.get("num_registros"),
            "url":                  m.get("url"),
        } for m in top],
        enviado_ok=exito,
        num_items=len(top),
    )

    if exito:
        print(f"  [OK] [Telegram] Minimos historicos enviados: {len(top)} de {nombre_tienda}")
    return exito


def enviar_comparacion(comparaciones: list) -> bool:
    """
    Envia el comparador entre tiendas a Telegram.
    Muestra que tienda tiene historicamente precios mas bajos.
    """
    if not _esta_configurado():
        return False
    if not comparaciones:
        return True

    ahora = datetime.now(TZ_PERU).strftime("%d/%m/%Y %H:%M")
    top   = comparaciones[:MAX_PRODUCTOS_POR_MENSAJE]

    lineas = [
        f"COMPARADOR ENTRE TIENDAS",
        f"Fecha: {ahora} (Peru)",
        "",
        f"Productos mas baratos segun nuestros datos ({len(top)} encontrados):",
        f"(Basado en historial propio, no en precios de la pagina)",
        "",
    ]
    for i, c in enumerate(top, 1):
        lineas.append(_fmt_comparacion(c, i))
        lineas.append("")

    texto = "\n".join(lineas)
    exito = _enviar_mensaje(texto)

    registrar_mensaje(
        tipo="COMPARACION",
        tienda="GLOBAL",
        contenido=[{
            "nombre_referencia":      c.get("nombre_referencia"),
            "tienda_mas_barata":      c.get("tienda_mas_barata"),
            "precio_min_mas_barato":  c.get("precio_min_mas_barato"),
            "diferencia_porcent":     c.get("diferencia_porcent"),
            "ahorro_absoluto":        c.get("ahorro_absoluto"),
            "similitud":              c.get("similitud"),
            "tiendas":                c.get("tiendas"),
        } for c in top],
        enviado_ok=exito,
        num_items=len(top),
    )

    if exito:
        print(f"  [OK] [Telegram] Comparacion entre tiendas enviada: {len(top)} productos")
    return exito


def enviar_resumen_ciclo(resumen: dict) -> bool:
    """Envia un resumen final del ciclo completo y lo registra localmente."""
    if not _esta_configurado():
        return False

    tiendas  = resumen.get("tiendas_procesadas", 0)
    productos = resumen.get("total_productos", 0)
    reales   = resumen.get("total_ofertas_reales", 0)
    minimos  = resumen.get("total_minimos", 0)
    comp     = resumen.get("total_comparaciones", 0)
    duracion = resumen.get("duracion_seg", 0)
    fecha    = resumen.get("fecha", datetime.now(TZ_PERU).strftime("%d/%m/%Y %H:%M"))
    modo     = resumen.get("modo", "CICLO COMPLETO")

    texto = (
        f"CAZADOR DE OFERTAS - {modo}\n"
        f"Fecha: {fecha} (Peru)\n\n"
        f"Resumen:\n"
        f"  Tiendas analizadas:         {tiendas}\n"
        f"  Productos escaneados:       {productos}\n"
        f"  Ofertas reales:             {reales}\n"
        f"  Precios minimos historicos: {minimos}\n"
        f"  Comparaciones entre tiendas:{comp}\n"
        f"  Duracion: {duracion:.1f} seg\n"
    )

    exito = _enviar_mensaje(texto)

    registrar_mensaje(
        tipo="RESUMEN",
        tienda="GLOBAL",
        contenido=resumen,
        enviado_ok=exito,
        num_items=tiendas,
    )

    if exito:
        print(f"  [OK] [Telegram] Resumen del ciclo enviado")
    return exito


def enviar_link_dashboard(url: str, resumen: dict | None = None) -> bool:
    """Envia el link al dashboard web para explorar los resultados del ciclo.

    `url` es la URL pública del túnel (la escribe web/servidor.py en .tunnel_url).
    Si se pasa `resumen`, incluye un mini-resumen del ciclo junto al link.
    """
    if not url:
        print("  [!] [Telegram] Sin URL de dashboard (¿túnel cloudflared no listo?)")
        return False

    lineas = ["🛒 *Cazador de Ofertas* — dashboard listo\n"]
    if resumen:
        lineas.append(
            f"📦 {resumen.get('total_productos', 0)} productos  ·  "
            f"🟢 {resumen.get('total_ofertas_reales', 0)} ofertas  ·  "
            f"🎯 {resumen.get('total_minimos', 0)} mínimos\n"
        )
    lineas.append(f"👉 Explora aquí:\n{url}")
    texto = "\n".join(lineas)

    exito = _enviar_mensaje(texto)

    registrar_mensaje(
        tipo="DASHBOARD",
        tienda="GLOBAL",
        contenido={"url": url},
        enviado_ok=exito,
        num_items=1,
    )

    if exito:
        print(f"  [OK] [Telegram] Link del dashboard enviado: {url}")
    return exito


def _escapar_md(texto: str) -> str:
    """Neutraliza caracteres de Markdown en texto ajeno (nombres de productos):
    un '*' o '[' sin cerrar en un nombre rompería el parseo de TODO el mensaje
    y el aviso se perdería."""
    for c in ("*", "_", "[", "]", "`"):
        texto = texto.replace(c, " ")
    return texto


def _fmt_ganga(g: dict) -> str:
    fav    = "⭐ " if g.get("es_favorito") else ""
    emoji  = g.get("emoji", "📉")
    nombre = _escapar_md((g.get("nombre") or "Producto"))[:45].strip()
    tienda = g.get("tienda", "")
    hoy    = g.get("precio_hoy") or 0
    tipico = g.get("precio_mediana") or 0
    ahorro = g.get("ahorro_vs_mediana") or 0
    tag    = "mínimo histórico" if g.get("es_nuevo_minimo") else "bajo el típico"

    linea = (
        f"{fav}{emoji} *{nombre}* — {tienda}\n"
        f"      S/{hoy:.2f} (típico S/{tipico:.2f}, *-{ahorro:.0f}%*, {tag})"
    )
    if g.get("url"):
        linea += f" · [Ver]({g['url']})"
    return linea


def enviar_aviso_listo(resumen: dict | None = None) -> bool:
    """Avisa que el scraping del día terminó y que se puede encender el dashboard.
    Incluye el top de gangas del ciclo (caídas fuertes validadas contra nuestro
    propio historial; los favoritos entran con prioridad).
    No incluye link directo porque el dashboard está apagado (ahorro de energía):
    el usuario lo enciende con /startserver cuando quiera explorar."""
    lineas = ["🛒 *Cazador de Ofertas* — datos actualizados ✅\n"]
    if resumen:
        lineas.append(
            f"📦 {resumen.get('total_productos', 0)} productos  ·  "
            f"🟢 {resumen.get('total_ofertas_reales', 0)} ofertas  ·  "
            f"🎯 {resumen.get('total_minimos', 0)} mínimos\n"
        )
        temp = resumen.get("temperatura")
        if temp:
            lineas.append(
                f"🌡️ CPU: máx *{temp.get('max')}°C* · prom {temp.get('promedio')}°C  "
                f"—  {temp.get('emoji', '')} {temp.get('diagnostico', '')}"
            )
            for seg in temp.get("tiendas", []):
                lineas.append(f"    · {seg['nombre']}: {seg['min']}–{seg['max']}°C")
            lineas.append("")
        gangas = resumen.get("gangas") or []
        if gangas:
            lineas.append("🔥 *Gangas del día* (vs tu propio historial):")
            for g in gangas:
                lineas.append(_fmt_ganga(g))
            lineas.append("")
    lineas.append("Manda /startserver para abrir el dashboard y explorar.")
    texto = "\n".join(lineas)

    exito = _enviar_mensaje(texto)
    registrar_mensaje(tipo="AVISO", tienda="GLOBAL", contenido=resumen or {},
                      enviado_ok=exito, num_items=1)
    if exito:
        print(f"  [OK] [Telegram] Aviso de scraping listo enviado")
    return exito
