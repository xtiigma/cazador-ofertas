# Registro de Cambios e Impacto en Contexto

> **Propósito:** Registro incremental de cambios para que cualquier IA futura sepa qué ha cambiado desde la última vez que leyó el README.md, sin necesidad de releer todo el código fuente.
>
> **Uso:** Cada vez que se haga un cambio significativo al proyecto, agregar una entrada nueva AL INICIO (orden cronológico inverso). La IA debe leer este archivo ANTES que el README.md para saber si hay actualizaciones pendientes.

---

## 2026-07-07 — Temperatura: freno suave + Inkafarma sin Chromium + historial 1 sola vez

- **Descripción corta:** Los avisos del 05 y 06/07 mostraban Plaza Vea a 73 °C e Inkafarma a 70 °C (resto: 43–64 °C). Tres medidas: (1) freno térmico SUAVE que congela el scraper a ≥72 °C y lo reanuda al enfriar (además del freno duro de 85 °C que mata la tienda); (2) Inkafarma ya no lanza Chromium — los IDs salen del índice Algolia público con `requests`; (3) el historial (474 MB en Plaza Vea) se parsea 1 vez por tienda en lugar de 3.
- **Módulos Afectados:** `main.py`, `tiendas/inkafarma/scraper.py`, `analizador/detector_descuentos.py`, `cazador_precios/cazador.py`, `requirements.txt`, READMEs.
- **Detalle Técnico del Cambio:**
  - **Freno suave (`main.py`):** el bucle de vigilancia de `ejecutar_scraper` llama a `_enfriar_scraper()` cuando el CPU alcanza `TEMP_PAUSAR_TIENDA` (72 °C): `SIGSTOP` a todo el grupo de procesos, espera hasta `TEMP_REANUDAR_TIENDA` (62 °C, histéresis) y `SIGCONT`. Tope de congelación `PAUSA_FRIA_MAX_SEG` (15 min) por si algo externo calienta; el tiempo congelado NO cuenta para el timeout de la tienda (`seg_pausado`). Mensajes 🧊/▶️ en el log. Probado con scraper dummy y temperaturas simuladas: congela, enfría, reanuda y los productos llegan.
  - **Inkafarma (`tiendas/inkafarma/scraper.py`):** eliminado Playwright (lanzaba 1 Chromium POR CATEGORÍA = 10 por ciclo; causa del pico de 70 °C en ~3 min). La web obtiene los IDs de su índice Algolia: `POST https://15w622laq4-dsn.algolia.net/1/indexes/*/queries` con la API key pública de solo-búsqueda (headers en `ALGOLIA_HEADERS`; si rota → DevTools). `resolver_departments()` lee el facet `department` (1 request) y mapea los slugs de URL por normalización (maneja tildes y el sufijo `-1`); `capture_product_ids(department)` pide `length=250&offset=0` con `attributesToRetrieve=["objectID"]` (~6 KB de respuesta) — los mismos 250 IDs mejor rankeados que capturaba el navegador. `filtered-products` intacto → mismos `id` de siempre. **Prueba real: 1,817 productos, 99.7% de IDs ya presentes en el historial (continuidad verificada), ~6-10 s por categoría.** Ya NINGUNA tienda usa navegador; `requirements.txt` ya no lista playwright/selenium (siguen en el venv por si hay que revertir).
  - **Historial 1 sola vez:** `analizar_productos()` y `analizar_minimos()` aceptan `historial: dict | None` opcional (None = cargan de la ruta, como antes — `analizar_ahora.py` no cambia). `main.py` conserva el dict que devuelve `registrar_precios()` en `historial_cargado`, lo pasa a ambos y lo suelta (`= None`) al terminar la tienda para liberar RAM antes de la pausa. En Plaza Vea eran 3 parseos de un JSON de 474 MB dentro del segmento térmico de la tienda. Verificado con Shopstar: resultados idénticos con dict pasado vs cargado del disco.
- **Actualización de Contexto para IA:** Si el log muestra 🧊/▶️ es el freno suave actuando (normal en Plaza Vea), no un bug; el ciclo se alarga lo que dure el enfriamiento. Si Inkafarma sale "❌ Ningún department de Algolia coincide" la tienda renombró la categoría (ver mapeo en `resolver_departments`); si da 403 en Algolia, rotó la API key pública (instrucciones en `tiendas/inkafarma/README.md`). Pendiente de validar en el ciclo del 07/07 12:10: temperaturas máximas de Plaza Vea e Inkafarma claramente por debajo de 70 °C.

## 2026-07-04 — Freno térmico por tienda + /startserver bloqueado durante el ciclo

- **Descripción corta:** (1) Si el CPU se mantiene ≥85 °C, se mata el scraper de la tienda actual y el ciclo sigue con la siguiente (la pausa de 10 min enfría). (2) El bot rechaza /startserver mientras el ciclo diario corre.
- **Módulos Afectados:** `main.py` (`ejecutar_scraper`, bloque `__main__`), `telegram_bot/bot_comandos.py`.
- **Detalle Técnico del Cambio:**
  - `ejecutar_scraper()` ya NO usa `proc.communicate(timeout=...)`: la salida del subproceso va a un archivo temporal (evita bloqueo por tubería llena) y un bucle vigila cada 10 s (`VIGILANCIA_INTERVALO_SEG`) tanto el timeout como la temperatura. Con **2 lecturas seguidas ≥ `TEMP_ABORTAR_TIENDA` (= `UMBRAL_ALTA`, 85 °C)** se aborta: mensaje 🔥 en el log, `return []`, y el `finally` mata el grupo de procesos como siempre. Probado con scraper falso y umbral forzado a 40 °C: abortó en 10 s.
  - Lockfile `.ciclo_en_curso` (raíz del proyecto): `main.py` escribe su PID al arrancar y lo borra en `finally`. `bot_comandos.ciclo_en_curso()` lo lee y verifica `/proc/<pid>` (ignora locks huérfanos). `cmd_start` responde "el escaneo sigue corriendo, te aviso cuando termine" en vez de encender el dashboard. Bot reiniciado con el código nuevo.
- **Actualización de Contexto para IA:** El aborto por temperatura devuelve lista vacía → la tienda queda como "Sin productos" ese día (el historial conserva lo anterior). Si el usuario reporta tiendas sin datos + mensaje 🔥 en el log, es el freno actuando, no un bug.

---

## 2026-07-04 — BUG CRÍTICO: gangas falsas por id corrupto en Shopstar (todos los productos eran "p")

- **Descripción corta:** El aviso de hoy dio gangas de Shopstar con precios que no existían al abrir el enlace. Causa raíz: las URLs VTEX de Shopstar terminan en `/p`, y el scraper tomaba el último segmento como id → los 1,440 productos compartían el id `"p"` y TODO el historial de la tienda colapsaba en un solo registro con precios de productos distintos mezclados (el "colchón a S/9.50" era el precio de otro producto; el real es S/579, verificado contra el API).
- **Módulos Afectados:** `tiendas/shopstar/scraper.py`, `tiendas/tailoy/scraper.py`, `main.py` (gangas), `tiendas/shopstar/datos/historial_precios.json` (reseteado, backup `.bak-2026-07-04`).
- **Detalle Técnico del Cambio:**
  - **Shopstar:** nuevo `_id_desde_url()` — usa el slug (segmento anterior al `/p`), único por producto. Además dedup por id en `main()` (el mismo producto aparecía en las ~12 categorías: 1440 → 120 únicos). Historial reseteado a `{}` porque era irrecuperable (una sola clave `"p"`); se reconstruye desde el ciclo del 05/07 (los mínimos/medianas de Shopstar necesitarán unos días).
  - **Tailoy:** productos sin enlace (50) quedaban con id `""` → ahora se descartan con aviso; dedup por id agregado.
  - **Sodimac:** auditado — ids repetidos eran el MISMO producto en varias categorías (0 colisiones reales); no requiere fix.
  - **Gangas (`main.py`):** (a) filtro de verosimilitud `MAX_AHORRO_CREIBLE = 90%` — ahorros mayores casi siempre son datos malos (ej. cartuchera Promart: la tienda publicó S/9,899 placeholder del 28/06 al 02/07 y la mediana sigue envenenada; se autocorrige en días y la cuarentena ya evita repeticiones); (b) dedup del top por (tienda, url) — hoy salió el mismo colchón 4 veces.
- **Actualización de Contexto para IA:** Los ids de Shopstar cambiaron de formato (slug). El `.bak-2026-07-04` del historial viejo se puede borrar tras validar unos ciclos. Auditoría de unicidad de ids ejecutada en las 9 tiendas: el resto está sano.

---

## 2026-07-04 — Temperatura por tienda (máx/mín) en el log y en el aviso de Telegram

- **Descripción corta:** El aviso diario de Telegram (y el resumen del log) ahora desglosa la temperatura del CPU por tienda: mínima y máxima durante el scraping+análisis de cada una, además del máx/prom global del ciclo.
- **Módulos Afectados:** `mantenimiento/temperatura.py`, `main.py`, `telegram_bot/notificador.py`.
- **Detalle Técnico del Cambio:**
  - `temperatura.py`: `MonitorTemperatura` ahora soporta **segmentos**: `iniciar_segmento(nombre)` / `cerrar_segmento()` atribuyen las muestras del hilo de fondo a la tienda activa (con lock; muestra inmediata al abrir y al cerrar, así hasta la tienda más rápida tiene ≥2 lecturas). `detener()` incluye la clave nueva `"tiendas"`: `[{nombre, max, min, muestras}]`.
  - `main.py`: abre el segmento al iniciar cada tienda y lo cierra ANTES de la pausa de 10 min (el enfriamiento de la pausa no cuenta como "mínimo" de la tienda). El resumen final imprime una línea `· Tienda: min–max°C` por tienda.
  - `notificador.py` (`enviar_aviso_listo`): bajo la línea 🌡️ global agrega `    · Tienda: min–max°C` por cada tienda.
- **Actualización de Contexto para IA:** El dict de `MonitorTemperatura.detener()` tiene una clave más (`tiendas`). Si se agrega una fase nueva al ciclo que deba medirse por separado, usar `iniciar_segmento()/cerrar_segmento()`.

---

## 2026-07-04 — Preparado el control del ventilador USB externo (hardware aún no llega)

- **Descripción corta:** El usuario compró un ventilador USB para poner debajo de la mini PC. Se dejó TODO listo para que el OS lo encienda/apague según la temperatura del CPU; solo falta el paso final de configuración cuando llegue el hardware.
- **Módulos Afectados:** `mantenimiento/ventilador.py` (nuevo), `mantenimiento/cazador-ventilador.service` (nuevo), `mantenimiento/52-usb-ventilador.rules` (nuevo), `docs/changelog.md`.
- **Detalle Técnico del Cambio:**
  - Un ventilador USB simple no tiene control de velocidad: el OS solo puede cortar/restaurar los 5V del puerto con `uhubctl` (si el hub soporta conmutación por puerto — los hubs raíz Intel a veces NO cortan el VBUS real; hay que probarlo con el ventilador puesto).
  - `ventilador.py`: histéresis ON ≥70 °C / OFF ≤58 °C (mismos umbrales del monitor de temperatura), muestreo cada 30 s, fail-safe (si el daemon muere deja el ventilador encendido). CLI: `--daemon | --on | --off | --detectar | --estado`. Probado sin hardware: `--estado` funciona, `--on` avisa que falta configurar.
  - **CHECKLIST al llegar el ventilador** (también en el docstring de `ventilador.py`):
    1. `sudo apt install uhubctl`
    2. conectar ventilador → `python3 -m mantenimiento.ventilador --detectar` (2 veces: con y sin ventilador, el puerto que cambia es el suyo)
    3. rellenar `HUB_LOCATION` y `PUERTO` en `ventilador.py`
    4. probar `--off`/`--on` y CONFIRMAR que el ventilador físicamente se detiene/arranca
    5. `sudo cp mantenimiento/52-usb-ventilador.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger && sudo usermod -aG dialout diego` (re-login)
    6. `cp mantenimiento/cazador-ventilador.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now cazador-ventilador.service`
  - Si el paso 4 falla (el puerto no corta energía de verdad): usar un hub USB externo compatible con uhubctl o dejar el ventilador siempre enchufado (consume ~0.5 W; igual enfría, solo que sin control).
- **Actualización de Contexto para IA:** Nuevo módulo en `mantenimiento/`; el servicio NO está instalado aún — está pendiente de hardware. Si el usuario dice que ya llegó el ventilador, ejecutar el checklist de arriba.

---

## 2026-07-04 — Modo "amigable" TOTAL: 1 hilo en todos los scrapers + 10 min entre tiendas

- **Descripción corta:** Tras la alerta térmica de 82 °C, y a pedido del usuario ("lo mínimo para que funcione"), TODO el ciclo pasó a mínima agresividad: 1 sola petición simultánea por scraper y 10 minutos de pausa entre tienda y tienda. El ciclo diario ahora tarda ~3.5-4 h (arranca 12:00, termina ~15:30-16:00) — no importa, nadie lo espera.
- **Módulos Afectados:** `main.py`, `tiendas/{inkafarma,plaza_vea,promart,dermo,efe,shopstar,tailoy,sodimac}/scraper.py`, `~/.config/systemd/user/cazador.service`.
- **Detalle Técnico del Cambio:**
  - `MAX_WORKERS = 1` en plaza_vea, promart, dermo, efe, shopstar, tailoy y sodimac (sodimac además `DELAY_ENTRE_PAGINAS = 1.0 s`). Inkafarma `MAX_CONCURRENT = 1`. Saga ya era secuencial con pausa de 0.3 s.
  - `main.py`: `PAUSA_ENTRE_TIENDAS_SEG = 10 * 60` (sleep al inicio de cada iteración salvo la primera; 8 pausas = 80 min del ciclo). Nuevo soporte de **timeout por tienda**: clave opcional `"timeout_min"` en `TIENDAS`; `ejecutar_scraper()` usa `tienda.get("timeout_min", 30) * 60`. Plaza Vea tiene `timeout_min: 150` porque su catálogo completo (~4300 peticiones, 213K productos) con 1 hilo tarda ~90-120 min. El resto sigue con 30 min.
  - systemd: `TimeoutStartSec` de `cazador.service` ampliado de 2h a **6h** (+ `daemon-reload`), porque el ciclo completo ya no cabe en 2h.
- **Actualización de Contexto para IA:** Los valores de workers de entradas anteriores quedan obsoletos; la fuente de verdad son las constantes al inicio de cada `scraper.py`. `TIMEOUT_TIENDA_SEG` ya no es el único timeout: mirar `timeout_min` por tienda. Validar en el ciclo del 05/07: que Plaza Vea termine dentro de 150 min y la línea 🌡️ del log.

---

## 2026-07-04 — Saga Falabella migrado de Selenium a requests (__NEXT_DATA__) + fix EFE

- **Descripción corta:** Saga Falabella llevaba días (desde ~01/07) agotando el timeout de 30 min con 0 productos y era la principal fuente de calor del ciclo (82 °C máx en la mini PC). Se reescribió el scraper para leer el JSON embebido `__NEXT_DATA__` de las páginas de categoría con `requests`, sin Chrome/Selenium. Además se corrigió un `ValueError` en EFE.
- **Módulos Afectados:** `tiendas/saga_falabella/scraper.py` (reescrito completo), `tiendas/efe/scraper.py` (línea ~106).
- **Detalle Técnico del Cambio:**
  - **Saga:** la página de categoría de falabella.com.pe es Next.js; un GET plano devuelve `<script id="__NEXT_DATA__">` con `props.pageProps.results` (lista de pods con `displayName`, `brand`, `skuId`, `prices`, `mediaUrls`, `url`) y `pagination`. El scraper itera las mismas 16 categorías × 10 páginas de forma SECUENCIAL (prioridad térmica) con pausa de 0.3 s, reintentos y corte anticipado cuando `pagination.currentPage` no coincide con la página pedida (fin del catálogo). Precios: `precio_oferta` = `eventPrice` o `internetPrice`; `precio_normal` = `normalPrice` tachado; `cmrPrice` se ignora (exige tarjeta). **`id` = `skuId`** — es el mismo último segmento del href que usaba Selenium, verificado contra `historial_precios.json` (68/108 ids de muestra coinciden; el contrato de salida es idéntico). Resultado real: 7,137 productos únicos en ~5 min y CPU máx 58 °C (antes: 0 productos, 30 min, 82 °C). Ya no depende de selenium/webdriver-manager (siguen en requirements.txt por si acaso).
  - **EFE:** `data-price-amount` puede venir como cadena vacía y `float('')` tumbaba la categoría entera vía `executor.map`. Cambiado a `float(el.get('data-price-amount') or 0)`. Verificado: 237 productos.
- **Actualización de Contexto para IA:** Sección README/parche > Tiendas Registradas: Saga Falabella ya NO usa "Selenium headless", ahora es "requests + __NEXT_DATA__ (Next.js)". El comentario del despliegue sobre "Saga usa Selenium + google-chrome del sistema" queda obsoleto.

---

## 2026-05-21 — Corrección "Mejor Precio Hoy" + Filtros en Búsqueda Global

- **Descripción corta:** Dos bugs corregidos: (1) "Mejor precio hoy" ahora solo muestra productos cuyo precio realmente bajó respecto a días anteriores, no productos con precio constante. (2) Los filtros "Descuento real" y "Mejor precio hoy" ahora funcionan durante búsqueda global (cuando no hay tienda seleccionada).
- **Módulos Afectados:** `web/main.js` — funciones `isBestPriceToday()`, event listeners de `realDiscountToggle`, `bestPriceToggle` y `sortSelect`.
- **Detalle Técnico del Cambio:**
  - **Bug 1 — `isBestPriceToday()` falso positivo:** La función anterior comparaba `precioActual <= minPrecioHistorico` usando TODOS los registros del historial (incluyendo el registro de hoy). Si un producto tuvo siempre el mismo precio (ej: S/ 32.90 en los 5 escaneos), el mínimo histórico era S/ 32.90 y el precio actual también era S/ 32.90, por lo que `<=` retornaba `true` incorrectamente. **Corrección:** Ahora se excluye el último registro del historial (que es el precio actual) con `historial.slice(0, -1)`, y se usa comparación estricta `<` en vez de `<=`. Así solo pasan productos cuyo precio HOY es menor que todos los precios anteriores.
  - **Bug 2 — Filtros inactivos en búsqueda global:** Los event listeners de `realDiscountToggle`, `bestPriceToggle` y `sortSelect` solo llamaban a `applyFiltersAndSort()` cuando `currentStore` era truthy. En búsqueda global (`globalSearch()`), `currentStore` se setea a `null`, por lo que los filtros no hacían nada. **Corrección:** Condición cambiada de `if (currentStore)` a `if (currentStore || currentProducts.length > 0)` en los 3 listeners.
- **Actualización de Contexto para IA:** Sección README > Dashboard Web: `isBestPriceToday()` ya NO usa `<=` contra todo el historial; ahora excluye el último registro y usa `<`. Los toggles de filtro ahora funcionan en cualquier contexto donde haya productos cargados.

---

## 2026-05-17 — Búsqueda Global + Botón Inicio en Dashboard Web

- **Descripción corta:** Implementada búsqueda global que funciona sin tener una tienda seleccionada, y agregado botón "Inicio" para volver a la vista principal.
- **Módulos Afectados:** `web/index.html`, `web/main.js`, `web/style.css`.
- **Detalle Técnico del Cambio:**
  - `main.js`: Nueva función `globalSearch(query)` que recopila productos de TODAS las tiendas y los muestra con un tag `_storeName`/`_storeId`. El `searchInput` listener ahora llama a `globalSearch()` cuando `currentStore === null` (con debounce de 300ms). Nueva función `goHome()` que resetea todo el estado (búsqueda, filtros, selección sidebar) y muestra la Vista General. Productos en búsqueda global incluyen `p._storeId` para que favoritos funcionen correctamente.
  - `index.html`: Agregado `<div class="sidebar-inicio">` con botón `#inicioBtn` entre el search box y el store-nav.
  - `style.css`: Estilos para `.sidebar-inicio`, `.inicio-btn` (con hover a primary), y `.product-store-tag` (badge con nombre de tienda en resultados globales).
- **Actualización de Contexto para IA:** El dashboard web ahora soporta búsqueda cross-store sin selección previa. El formato de historial en `data.json` cambió (ver entrada siguiente). El botón Inicio es el punto de reset de toda la UI.

---

## 2026-05-17 — Historial Web: Todas las Fechas + Formato Compacto + Deduplicación

- **Descripción corta:** Corregido que la web solo mostraba 5 fechas de historial. Ahora muestra TODAS las fechas, deduplicadas (1 por día), en formato compacto para reducir tamaño.
- **Módulos Afectados:** `web/build_data.py`, `web/main.js`.
- **Detalle Técnico del Cambio:**
  - `build_data.py`: Eliminado el límite `registros_historial[-5:]`. Ahora se envían TODOS los registros. Implementada deduplicación por fecha: si hay múltiples scrapes en un mismo día (precio cambió entre scrapes), solo se mantiene el último registro de cada fecha. Formato cambiado de objetos `{"fecha": "...", "precio_normal": X, "precio_oferta": Y}` a arrays compactos `[fecha, precio_normal, precio_oferta]` para reducir tamaño del JSON (de ~319MB a ~155MB con 250K productos).
  - `main.js`: Actualizado todo el código que leía `h.precio_oferta`/`h.precio_normal`/`h.fecha` a `h[2]`/`h[1]`/`h[0]`. Funciones afectadas: `hasRealDiscount()`, `isBestPriceToday()`, `calculateRealDiscount()`, y el render de `historyHtml`. Helper global `hPrecio(h)` añadido. Label cambiado de "Escaneado N veces" a "Historial: N días".
- **Actualización de Contexto para IA:** Sección README > Dashboard Web: el formato de `data.json` ya NO usa objetos para historial, usa arrays `[fecha, pn, po]`. Cualquier código futuro que lea el historial del frontend debe usar índices, no keys.

---

## 2026-05-17 — Telegram en Pausa + Log de Consola Reducido + Modificador de Fechas

- **Descripción corta:** Pausadas las notificaciones de Telegram con un flag. Reducida la verbosidad del log de consola a solo errores y resúmenes compactos. Creado script `Modificador_de_Fechas.py` para eliminar días de scraping del proyecto.
- **Módulos Afectados:** `main.py`, `analizador/detector_descuentos.py`, `analizador/historial_precios.py`, `cazador_precios/cazador.py`, `Modificador_de_Fechas.py` (nuevo).
- **Detalle Técnico del Cambio:**
  - `main.py`: Agregado `TELEGRAM_HABILITADO = False` (línea 40). Imports de Telegram condicionados a este flag con `if TELEGRAM_HABILITADO:`. Todas las llamadas a `enviar_alerta()`, `enviar_minimos_historicos()`, `enviar_resumen_ciclo()` protegidas con el mismo flag. Consola reducida: eliminados los headers `[1/4]`-`[4/4]`, Top 5 ofertas, separadores visuales. Ahora muestra `[1/9] 🏪 Inkafarma` → `✅ 27000 productos` + resúmenes de 1 línea. Resumen final condensado en una sola línea.
  - `detector_descuentos.py`: Resumen de 8 líneas reemplazado por una: `📊 Descuentos: X ofertas, Y reales, Z falsos (N total)`.
  - `historial_precios.py`: Print cambiado a: `📊 Historial: +N nuevos, M actualizados`.
  - `cazador.py`: Resumen de 7 líneas + Top 5 reemplazado por una: `🎯 Mínimos: X nuevos, Y bajo promedio (N total)`.
  - `Modificador_de_Fechas.py` (NUEVO): Script interactivo que: (1) escanea todos los `historial_precios.json` de las 9 tiendas, (2) muestra tabla con fechas, registros, archivos y tiendas, (3) acepta selección flexible (números, rangos, fechas directas), (4) confirma con Y/N, (5) elimina registros de esas fechas de cada historial, (6) elimina archivos JSON de scraping correspondientes, (7) regenera el dashboard web.
- **Actualización de Contexto para IA:** Sección README > Flujo Orquestado (`main.py`): Telegram ahora está pausado — los pasos 5 y 6 (envío de alertas y resumen) se saltan. Para reactivar: cambiar `TELEGRAM_HABILITADO = True`. La consola ya no muestra Top 5 ni resúmenes detallados por módulo. Nuevo archivo raíz `Modificador_de_Fechas.py` no documentado en README — es una herramienta de mantenimiento independiente.

---

## 2026-05-17 — Creación del Blueprint y Registro de Cambios

- **Descripción corta:** Se generó el README.md como "Blueprint para LLMs" y este archivo parche.md como registro incremental de cambios.
- **Módulos Afectados:** `README.md` (reescrito completo), `parche.md` (nuevo).
- **Detalle Técnico del Cambio:** El README.md anterior era un resumen básico de 3.5KB. Fue reemplazado por un documento hiperdetallado (~10KB) que documenta: arquitectura completa, diagrama de flujo, contrato de datos, mapa de funciones con firmas y descripciones, estrategia de scraping por tienda, resiliencia, convenciones y configuración.
- **Actualización de Contexto para IA:** Este es el estado base. Todas las secciones del README.md reflejan el estado actual del código al 2026-05-17.

---

## Estado Actual del Proyecto (Snapshot Inicial)

### Tiendas Registradas (9)
| # | Tienda | Scraper | Async | Estado |
|---|--------|---------|-------|--------|
| 1 | Inkafarma | Playwright + API REST | ✅ Sí | Operativo |
| 2 | Plaza Vea | VTEX Catalog API (hojas) | ❌ No | Operativo |
| 3 | Saga Falabella | Selenium headless | ❌ No | Operativo |
| 4 | Dermo | requests + BS4 (Shopify) | ❌ No | Operativo |
| 5 | EFE | requests + BS4 (Magento) | ❌ No | Operativo |
| 6 | Shopstar | VTEX IS API + fallback | ❌ No | Operativo |
| 7 | Sodimac | requests + BS4 | ❌ No | Operativo |
| 8 | Tailoy | requests + BS4 (Magento) | ❌ No | Operativo |
| 9 | Promart | VTEX Catalog API | ❌ No | Operativo |

### Módulos del Sistema
- ✅ `analizador/` — Historial + Detector de descuentos (5 clasificaciones)
- ✅ `cazador_precios/` — Mínimos históricos + Comparador cross-store
- ✅ `telegram_bot/` — Notificaciones + Registro local
- ✅ `logger/` — TeeStream a archivo .log
- ✅ `web/` — Dashboard Vite con favoritos

### Bugs Conocidos / Notas
- `shopstar/scraper.py` tiene un typo: función `_armar_produto` (portugués) que es alias de `_armar_producto`. Funciona pero es inconsistente.
- `_pendiente/config.py` existe pero **no se usa**. La configuración está distribuida en cada módulo.
- El comparador cross-store (`comparar_desde_rutas`) solo se ejecuta desde `analizar_ahora.py`, **no** desde `main.py`.
- Telegram `BOT_TOKEN` está hardcodeado en `telegram_bot/config.py` (no usa variables de entorno).

---

## Plantilla para Futuros Cambios

<!--
Copiar este bloque y rellenarlo para cada cambio futuro.
Insertar ANTES de las entradas anteriores (orden cronológico inverso).

## YYYY-MM-DD — Título del Cambio

- **Descripción corta:** Qué se cambió y por qué.
- **Módulos Afectados:** Lista de archivos y funciones específicas modificadas.
- **Detalle Técnico del Cambio:** Explicación a nivel de código de la modificación.
- **Actualización de Contexto para IA:** Qué parte del README.md queda obsoleta o se modifica con este cambio. Indicar la sección exacta (ej: "Sección 2 > cazador_precios/cazador.py > analizar_minimos: cambió el umbral de 3 a 5 registros mínimos").
-->
