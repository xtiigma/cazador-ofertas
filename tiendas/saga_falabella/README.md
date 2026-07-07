# 🏬 Saga Falabella — Scraper de Productos

## Descripción
Scraper para [Saga Falabella Perú](https://www.falabella.com.pe) usando Selenium
con pool de navegadores en paralelo para máxima velocidad.

## Categorías Monitoreadas
- 💻 Tecnología
- 🏠 Electrohogar
- 🪑 Muebles y Organización
- 🛏️ Dormitorio
- 👔 Hombre / Moda Hombre
- 👟 Zapatos / Zapatillas
- 💊 Salud, Higiene y Belleza
- 🍳 Menaje Cocina
- 🔨 Construcción y Ferretería
- 🚿 Baño
- 🐕 Mascotas
- 🌿 Jardín y Terraza
- 🖼️ Decoración

## Método de Scraping
- **Selenium** con Chrome headless (pool de 4 drivers)
- Scroll automático para carga lazy de productos
- Selectores CSS con fallbacks múltiples
- Deduplicación por URL
- Reintentos automáticos

## Dependencias Adicionales
```bash
pip install selenium webdriver-manager
```

## Historial
- **2026-03-28**: Incorporado al proyecto desde `SAGA.py`
