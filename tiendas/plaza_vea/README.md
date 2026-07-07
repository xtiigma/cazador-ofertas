# 🛒 Plaza Vea — Scraper de Productos

## Descripción
Scraper para la tienda online [Plaza Vea](https://www.plazavea.com.pe).
Usa la API pública del catálogo (VTEX) para extraer productos por categoría.

## Categorías Monitoreadas
- 💻 Tecnología
- 🏠 ElectroHogar
- 🪑 Muebles
- 🛏️ Dormitorio
- ⚽ Deportes
- 👔 Moda Hombre
- 👟 Zapatillas
- 💄 Belleza
- 🐕 Mascotas
- 📚 Librería y Oficina

## Método de Scraping
- API REST pública de VTEX (`catalog_system/pub/products/search`)
- No requiere Playwright (solo `requests`)
- Paginación con batches de 20 productos
- Pausas aleatorias entre requests para evitar bloqueos

## Campos Extraídos
| Campo | Descripción |
|-------|-------------|
| `nombre` | Nombre del producto |
| `marca` | Marca |
| `precio_normal` | Precio de lista |
| `precio_oferta` | Precio final |
| `categoria` | Categoría de origen |
| `url` | URL directa al producto |

## Historial
- **2026-03-28**: Incorporado al proyecto desde `PLAZA_VEA.py`
