# 🏥 Inkafarma — Scraper de Productos

## Descripción
Scraper especializado para la tienda online [Inkafarma](https://inkafarma.pe).
Extrae productos de múltiples categorías usando la API interna de la tienda.

## Categorías Monitoreadas
- 💊 Salud → `https://inkafarma.pe/categoria/salud`
- 🏥 Farmacia → `https://inkafarma.pe/categoria/farmacia`
- 🧴 Dermatología Cosmética → `https://inkafarma.pe/categoria/dermatologia-cosmetica`
- 💄 Belleza → `https://inkafarma.pe/categoria/belleza` *(deshabilitada por ahora)*

## Método de Scraping
1. **Requests → Algolia**: los IDs de producto de cada categoría se piden al índice
   público de Algolia de la tienda (la misma consulta que hace la web). Hasta
   2026-07-07 esto se hacía lanzando un Chromium por categoría (Playwright);
   se eliminó porque disparaba la temperatura de la mini PC.
2. **Requests** consulta la API interna (`filtered-products`) con esos IDs
3. Los datos se guardan en JSON, organizados por fecha

Si la API key pública de Algolia rotara (error 403 en el paso 1): abrir
`https://inkafarma.pe/categoria/salud` con las DevTools y copiar los headers
`x-algolia-*` de la petición a `*.algolia.net` en `scraper.py`.

## Campos Extraídos
| Campo | Descripción |
|-------|-------------|
| `nombre` | Nombre del producto |
| `marca` | Marca del producto |
| `precio_normal` | Precio sin descuento |
| `precio_oferta` | Precio con descuento (todos los medios de pago) |
| `precio_minimo` | Precio mínimo (con medio de pago específico) |
| `stock` | Disponibilidad |
| `presentacion` | Presentación del producto |
| `url` | URL directa al producto |

## Estructura de Archivos
```
inkafarma/
├── README.md          # Esta documentación
├── scraper.py         # Scraper principal (migrado de Inkfarma.py)
├── config.py          # Configuración específica de Inkafarma
├── datos/             # Datos organizados por fecha
│   └── YYYY-MM-DD/
│       ├── productos_inkafarma.csv
│       └── productos_inkafarma.json
└── logs/              # Logs de ejecución
```

## Historial
- **2026-03-28**: Migración y restructuración desde `Inkfarma.py`
