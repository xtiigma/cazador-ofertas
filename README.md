# Cazador de Ofertas — Blueprint para LLMs

> **Última actualización:** 2026-05-17  
> **Propósito de este archivo:** Servir como fuente de verdad para que cualquier IA comprenda la arquitectura, flujo de datos y estilo del proyecto sin leer todo el código fuente.

---

## 1. Resumen Ejecutivo de Arquitectura

### Propósito
Sistema automatizado de **monitoreo de precios** en 9 tiendas online peruanas. Scrapea productos, registra historial de precios en JSON, detecta descuentos reales vs falsos, encuentra mínimos históricos, compara precios entre tiendas, y envía alertas por Telegram. Incluye un dashboard web (Vite) para visualización.

### Stack Tecnológico

| Componente | Tecnología | Versión / Notas |
|---|---|---|
| Lenguaje | Python 3.12+ | Type hints con `X | None` |
| HTTP estático | `requests` + `BeautifulSoup4` | TODAS las tiendas (desde 2026-07-07 ningún scraper usa navegador) |
| Concurrencia | `asyncio`, `ThreadPoolExecutor`, `threading` | Varía por scraper |
| Notificaciones | Telegram Bot API (via `urllib.request`) | Sin dependencia de `python-telegram-bot` |
| Dashboard | Vite + Vanilla JS + CSS | Carpeta `web/` |
| Almacenamiento | JSON plano en disco | Un historial por tienda + snapshots con timestamp |
| Zona horaria | `America/Lima` (UTC-5) | Constante `TZ_PERU` en todos los módulos |

### Diagrama de Flujo de Datos

```
main.py (orquestador)
  │
  ├─ POR CADA TIENDA ─────────────────────────────────────────────┐
  │   [1] ejecutar_scraper() ──► tiendas/<nombre>/scraper.py      │
  │        → importlib.import_module("scraper").main()             │
  │        → retorna: List[dict] con contrato estándar             │
  │                                                                │
  │   [2] registrar_precios() ──► analizador/historial_precios.py  │
  │        → lee/escribe: tiendas/<nombre>/datos/historial.json    │
  │                                                                │
  │   [3] analizar_productos() ──► analizador/detector_descuentos  │
  │        → clasifica: GRAN_OFERTA|REAL|DUDOSO|FALSO|POCOS_DATOS  │
  │                                                                │
  │   [4] analizar_minimos() ──► cazador_precios/cazador.py        │
  │        → detecta: MINIMO_HISTORICO | PRECIO_BAJO               │
  │                                                                │
  │   [5] enviar_alerta() + enviar_minimos_historicos()            │
  │        → telegram_bot/notificador.py → Telegram API            │
  │        → telegram_bot/registro/ → JSON local del día           │
  ├────────────────────────────────────────────────────────────────┘
  │
  ├─ [6] enviar_resumen_ciclo() → resumen global por Telegram
  │
  ├─ [7] subprocess: web/build_data.py → regenera web/public/data.json
  │
  └─ [8] cerrar_logger() → cierra archivo .log de la sesión
```

### Contrato de Datos Estándar (cada scraper retorna esto)

```python
{
    "id":             str,   # ID único del producto (varía por tienda)
    "nombre":         str,   # Nombre del producto
    "marca":          str,   # Marca (puede ser "")
    "categoria":      str,   # Categoría de origen
    "precio_normal":  float | None,  # Precio sin descuento (ListPrice)
    "precio_oferta":  float | None,  # Precio con descuento (Price/SellingPrice)
    "precio_minimo":  float | None,  # Solo Inkafarma (priceWithpaymentMethod)
    "url":            str,   # URL directa al producto
}
```

---

## 2. Mapa Técnico de Componentes

### Estructura de Carpetas

```
WEBSCRAPING/
├── main.py                    # Orquestador principal (ciclo completo)
├── analizar_ahora.py          # Análisis sin scraping (usa JSONs existentes)
├── analizador/                # Módulo de análisis de precios
│   ├── historial_precios.py   #   CRUD del historial JSON
│   └── detector_descuentos.py #   Clasificación de descuentos reales vs falsos
├── cazador_precios/           # Módulo de detección de mínimos
│   ├── cazador.py             #   Mínimos históricos por tienda
│   └── comparador.py          #   Comparador cross-store (Jaccard similarity)
├── telegram_bot/              # Módulo de notificaciones
│   ├── config.py              #   BOT_TOKEN, CHAT_ID, umbrales
│   ├── notificador.py         #   Funciones de envío y formateo
│   └── registro/              #   Log local de mensajes enviados (JSON/día)
│       └── registro_mensajes.py
├── logger/                    # Módulo de logging por sesión
│   ├── console_logger.py      #   TeeStream: captura stdout+stderr → .log
│   └── logs/                  #   Archivos YYYY-MM-DD_HH-MM-SS.log
├── tiendas/                   # Scrapers individuales
│   ├── inkafarma/scraper.py   #   Algolia (IDs) + API REST (async, sin navegador)
│   ├── plaza_vea/scraper.py   #   VTEX Catalog API (ThreadPool, hojas)
│   ├── saga_falabella/scraper.py # Selenium + DriverPool (headless Chrome)
│   ├── dermo/scraper.py       #   requests + BeautifulSoup (Shopify)
│   ├── efe/scraper.py         #   requests + BeautifulSoup (Magento)
│   ├── shopstar/scraper.py    #   VTEX Intelligent Search API
│   ├── sodimac/scraper.py     #   requests + BeautifulSoup (HTML)
│   ├── tailoy/scraper.py      #   requests + BeautifulSoup (Magento)
│   └── promart/scraper.py     #   VTEX Catalog API (ThreadPool)
├── web/                       # Dashboard web
│   ├── build_data.py          #   Consolida JSONs → public/data.json
│   ├── index.html, main.js, style.css
│   ├── vite.config.js         #   Incluye API de favoritos (dev server)
│   └── public/data.json       #   Datos consolidados para el frontend
├── _pendiente/                # Código no integrado aún
│   ├── config.py              #   Config global draft (no se usa)
│   └── alertas/telegram_bot.py
├── docs/changelog.md          # Changelog manual antiguo
└── logs/                      # (vacío, los logs reales están en logger/logs/)
```

### Módulos Principales

---

#### **`main.py`** — Orquestador del ciclo completo

| Función | Firma | Descripción |
|---|---|---|
| `ejecutar_scraper` | `(tienda: dict) -> list` | Importa dinámicamente `scraper.py` de la tienda vía `importlib`, ejecuta `main()` (sync o async según `es_async`). Cambia `cwd` al directorio del scraper y limpia `sys.modules["scraper"]` para evitar colisiones. |
| `ciclo_completo` | `() -> None` | Itera `TIENDAS`, ejecuta los 4 pasos por tienda (scrape → historial → análisis → cazador), envía alertas Telegram, al final envía resumen global y regenera dashboard vía `subprocess`. |

**`TIENDAS`**: Lista de 9 dicts con `nombre`, `scraper_dir`, `historial` (ruta al JSON), `es_async` (bool).

---

#### **`analizar_ahora.py`** — Análisis offline (sin scraping)

Carga los historiales JSON existentes, reconstruye `productos_actuales` desde el último registro de cada producto, y ejecuta el mismo pipeline de análisis + Telegram. Además ejecuta el **comparador entre tiendas** (`comparar_desde_rutas`), que `main.py` NO ejecuta.

---

#### **`analizador/historial_precios.py`** — CRUD del historial

| Función | Firma | Descripción |
|---|---|---|
| `cargar_historial` | `(ruta: str) -> dict` | Lee JSON, retorna `{}` si no existe. |
| `guardar_historial` | `(historial: dict, ruta: str) -> None` | Escribe JSON con `ensure_ascii=False, indent=2`. Crea directorios. |
| `registrar_precios` | `(productos: list, ruta: str) -> dict` | Agrega registro solo si el precio cambió o es nueva fecha. Retorna historial actualizado. |
| `obtener_precio_promedio` | `(historial: dict, pid: str, dias: int=30) -> dict|None` | Promedio de `precio_normal` y `precio_oferta` en ventana de N días. |
| `contar_cambios_precio` | `(historial: dict, pid: str, dias: int=7) -> int` | Cuenta cambios de precio en N días (detector yo-yo). |

**Formato del historial** (`tiendas/<tienda>/datos/historial_precios.json`):
```json
{
  "product_id": {
    "nombre": "...", "marca": "...", "url": "...",
    "registros": [
      {"fecha": "2026-03-28", "precio_normal": 50.0, "precio_oferta": 35.0, "precio_minimo": null}
    ]
  }
}
```

---

#### **`analizador/detector_descuentos.py`** — Clasificador de descuentos

| Función | Firma | Descripción |
|---|---|---|
| `calcular_descuento` | `(normal: float, actual: float) -> float|None` | `((normal - actual) / normal) * 100` |
| `clasificar_descuento` | `(producto: dict, historial: dict) -> dict|None` | Retorna `None` si descuento < 15%. Clasifica según historial. |
| `analizar_productos` | `(productos: list, ruta_historial: str) -> list` | Wrapper: carga historial, clasifica todos, ordena por prioridad+descuento. |

**Clasificaciones** (en orden de prioridad):
1. `GRAN_OFERTA` — Descuento real ≥ 30%, historial sólido (≥5 registros)
2. `REAL` — Descuento real ≥ 15%, historial sólido
3. `DUDOSO` — Patrón yo-yo (≥3 cambios en 7 días)
4. `FALSO` — Precio "normal" inflado >10% vs promedio histórico
5. `POCOS_DATOS` — <5 registros en historial
6. `NUEVO` — Sin historial previo

**Umbrales clave**: `DESCUENTO_MINIMO_PORCENT=15`, `DESCUENTO_GRAN_OFERTA=30`, `MIN_REGISTROS_VALIDAR=5`, `MAX_CAMBIOS_YOYO=3`, `DIAS_ESTABILIDAD=7`.

---

#### **`cazador_precios/cazador.py`** — Detector de mínimos históricos

| Función | Firma | Descripción |
|---|---|---|
| `analizar_producto_historico` | `(pid: str, precio_hoy: float, historial_prod: dict) -> dict|None` | Compara precio de hoy vs todo el historial propio. Excluye registros de hoy para comparación justa. |
| `analizar_minimos` | `(productos: list, ruta: str) -> list` | Wrapper: analiza todos los productos, retorna los notables ordenados. |

**Clasificaciones**: `MINIMO_HISTORICO` (precio actual < mínimo anterior -1%), `PRECIO_BAJO` (>10% bajo el promedio).  
**Umbrales**: `MIN_REGISTROS_REQUERIDOS=3`, `UMBRAL_BAJO_VS_PROMEDIO=10.0`, `UMBRAL_NUEVO_MINIMO=1.0`.

---

#### **`cazador_precios/comparador.py`** — Comparador cross-store

| Función | Firma | Descripción |
|---|---|---|
| `_normalizar_nombre` | `(nombre: str) -> set` | Quita tildes, minúsculas, filtra palabras <3 chars y stop-words. Retorna set de keywords. |
| `_similitud` | `(a: set, b: set) -> float` | Índice de Jaccard: `|A∩B| / |A∪B|` |
| `comparar_entre_tiendas` | `(historiales: dict) -> list` | Compara todos los productos entre todas las tiendas por pares. |
| `comparar_desde_rutas` | `(tiendas_config: list) -> list` | Carga historiales y llama a `comparar_entre_tiendas`. |

**Umbrales**: `UMBRAL_SIMILITUD=0.70`, `UMBRAL_DIFERENCIA_PORCENT=5.0`, `MIN_REGISTROS=2`.

---

#### **`telegram_bot/notificador.py`** — Notificaciones Telegram

| Función | Firma | Descripción |
|---|---|---|
| `enviar_alerta` | `(ofertas: list, nombre_tienda: str) -> bool` | Filtra por clasificación permitida + umbral mínimo, formatea top N, envía y registra. |
| `enviar_minimos_historicos` | `(minimos: list, nombre_tienda: str) -> bool` | Envía mínimos históricos del cazador. |
| `enviar_comparacion` | `(comparaciones: list) -> bool` | Envía comparación cross-store. |
| `enviar_resumen_ciclo` | `(resumen: dict) -> bool` | Envía resumen final del ciclo. |
| `_enviar_mensaje` | `(texto: str) -> bool` | HTTP POST a Telegram API con `urllib.request`. Markdown parse mode. |

**Config** (`telegram_bot/config.py`): `MIN_DESCUENTO_TELEGRAM=15.0`, `MAX_PRODUCTOS_POR_MENSAJE=5`, `CLASIFICACIONES_PERMITIDAS=("GRAN_OFERTA", "REAL", "POCOS_DATOS")`.

---

#### **`logger/console_logger.py`** — Sistema de Logging

Usa un `_TeeStream` que intercepta `sys.stdout` y `sys.stderr` para escribir simultáneamente a consola y a archivo `.log` (UTF-8). Cada ejecución genera un archivo en `logger/logs/YYYY-MM-DD_HH-MM-SS.log`.

| Función | Firma | Descripción |
|---|---|---|
| `configurar_logger` | `(nombre_sesion: str|None) -> Logger` | Singleton. Redirige stdout/stderr, crea FileHandler UTF-8. |
| `cerrar_logger` | `() -> None` | Restaura streams originales, cierra handlers. Llamar al final. |

---

#### **`web/build_data.py`** — Generador de datos para dashboard

Lee el último JSON snapshot de cada tienda + su historial, y genera `web/public/data.json` consolidado. Incluye los últimos 5 registros de historial por producto y soporte de favoritos (`favoritos.json`). Solo incluye imágenes de `saga_falabella` y `promart`.

---

## 3. Estrategia y Patrón de Web Scraping

### Métodos de Extracción por Tienda

| Tienda | Método | API/Tecnología | Concurrencia |
|---|---|---|---|
| **Inkafarma** | Algolia + API REST oculta | `requests` pide los IDs al índice Algolia público de la web y pagina la AWS Lambda API (`filtered-products`) | `asyncio` + `Semaphore(1)` + `run_in_executor` |
| **Plaza Vea** | VTEX Catalog API (hojas) | Scrapea sub-subcategorías hoja para evitar límite VTEX de 2500 | `ThreadPoolExecutor(8)` |
| **Saga Falabella** | Selenium headless | Pool de 4 Chrome drivers, CSS selectors con fallbacks | `ThreadPoolExecutor(4)` + `DriverPool` |
| **Dermo** | HTML estático (Shopify) | `requests` + `BeautifulSoup`, selectores CSS `product-card` | `ThreadPoolExecutor(8)` |
| **EFE** | HTML estático (Magento) | `requests` + `BeautifulSoup`, selectores `li.product-item` | `ThreadPoolExecutor(6)` |
| **Shopstar** | VTEX Intelligent Search API | JSON API con fallback a catálogo clásico | `ThreadPoolExecutor(6)` |
| **Sodimac** | HTML estático | `requests` + `BeautifulSoup`, selectores `a.pod-link` | `ThreadPoolExecutor(4)` + delay anti-ban |
| **Tailoy** | HTML estático (Magento) | `requests` + `BeautifulSoup`, selectores `li.product-item` | `ThreadPoolExecutor(5)` |
| **Promart** | VTEX Catalog API | Categorías raíz con paginación, progreso en vivo | `ThreadPoolExecutor(11)` + barra de progreso |

### Resiliencia

- **Reintentos con backoff**: Todas las tiendas implementan reintentos (3-4 intentos). Backoff exponencial en Inkafarma (`1s, 2s, 4s, 8s`), Plaza Vea y Promart.
- **Rate limiting**: Plaza Vea maneja HTTP 429 con espera exponencial (hasta 90s). Sodimac tiene `DELAY_ENTRE_PAGINAS=0.5s`. Promart espera `10*intento` segundos en 429.
- **User-Agent rotation**: Plaza Vea y Promart rotan entre múltiples User-Agents.
- **Deduplicación**: Plaza Vea deduplica por `productId`. Saga Falabella por URL base. Promart por `productId`.
- **Errores HTTP manejados**: 400 (fin catálogo VTEX), 403 (bloqueado), 404 (no encontrado), 429 (rate limit), 5xx (error servidor).
- **Selenium recovery**: Saga Falabella recrea el driver Chrome si `WebDriverException` ocurre.

---

## 4. Convenciones de Estilo, Estado y Configuración

### Estilo de Código
- **Paradigma**: Procedimental/funcional. No hay clases (excepto `DriverPool` en Saga y `_TeeStream` en logger).
- **Convención**: PEP 8 relajado. Snake_case. Docstrings en español. Emojis en prints de consola.
- **Type hints**: Usados en firmas principales (`float | None`, `dict | None`).
- **Imports**: `sys.path.insert(0, ROOT_DIR)` al inicio de cada entry point para resolver imports del proyecto.

### Gestión de Configuración
- **Sin `.env`**: Toda la configuración está hardcodeada en constantes al inicio de cada módulo.
- **Telegram**: `telegram_bot/config.py` contiene `BOT_TOKEN` y `CHAT_ID` en texto plano.
- **Umbrales**: Cada módulo define sus propios umbrales como constantes globales (no centralizados).
- **`_pendiente/config.py`**: Config global draft que **no se usa** actualmente.

### Formato de Logs
- **Archivo**: `logger/logs/YYYY-MM-DD_HH-MM-SS.log`
- **Formato por línea**: `[HH:MM:SS] mensaje`
- **Registro Telegram**: `telegram_bot/registro/YYYY-MM-DD.json` — array de objetos con `tipo`, `tienda`, `contenido`, `enviado_ok`.

### Almacenamiento de Datos
- **Snapshots**: `tiendas/<nombre>/datos/<nombre>_YYYY-MM-DD_HHMMSS.json` — array de productos del último scrape.
- **Historial**: `tiendas/<nombre>/datos/historial_precios.json` — dict indexado por product_id.
- **Dashboard**: `web/public/data.json` — consolidado de todas las tiendas para el frontend.
- **Favoritos**: `tiendas/<nombre>/datos/favoritos.json` — array de IDs favoritos (gestionados desde el dashboard via Vite dev server API).

### Puntos de Entrada
```bash
python main.py           # Ciclo completo: scrape + análisis + telegram + dashboard
python analizar_ahora.py # Solo análisis (sin scraping, usa JSONs existentes)
cd web && npm run dev    # Dashboard web local (Vite dev server)
```
