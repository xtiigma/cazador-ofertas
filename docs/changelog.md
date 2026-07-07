# 📝 Changelog — Cazador de Ofertas

Registro cronológico de todos los cambios del proyecto.

---

## 2026-03-28

### 🏗️ Restructuración inicial del proyecto
- **Creado**: Estructura de carpetas modular organizada por tiendas
- **Creado**: `README.md` con misión del proyecto
- **Creado**: `docs/changelog.md` (este archivo)

### 🏥 Inkafarma
- **Migrado**: `Inkfarma.py` → `tiendas/inkafarma/scraper.py` (código original)
- **Modificado**: Guardar solo JSON (eliminado CSV), nombre con fecha+hora (`inkafarma_YYYY-MM-DD_HHMMSS.json`)
- **Agregado**: `return all_products` para integración con orquestador
- **Probado**: ✅ 735 productos scrapeados exitosamente

### 🛒 Plaza Vea
- **Migrado**: `PLAZA_VEA.py` → `tiendas/plaza_vea/scraper.py`
- **Adaptado**: Sin pandas/Excel → JSON con fecha+hora
- **Adaptado**: Retorna lista de productos para el orquestador
- **Probado**: ✅ Productos scrapeados exitosamente

### 🏬 Saga Falabella
- **Migrado**: `SAGA.py` → `tiendas/saga_falabella/scraper.py`
- **Adaptado**: Sin pandas/Excel → JSON con fecha+hora
- **Adaptado**: Deduplicación sin pandas (por URL base)
- **Adaptado**: Retorna lista de productos para el orquestador
- **Creado**: README con documentación de categorías y método

### 🧠 Analizador de descuentos
- **Creado**: `analizador/historial_precios.py` — almacena precios, detecta cambios, promedios
- **Creado**: `analizador/detector_descuentos.py` — clasifica: 🔥GRAN_OFERTA / 🟢REAL / 🟡DUDOSO / 🔴FALSO / 🆕NUEVO
- **Probado**: ✅ 68 productos con descuento detectados en primer scan de Inkafarma

### 🚀 Orquestador
- **Creado**: `main.py` — ciclo completo (scrape → historial → análisis)
- **Soporta**: Scrapers sync (Plaza Vea, Saga) y async (Inkafarma)
- 3 tiendas registradas

### 🧹 Limpieza
- Archivos originales eliminados de la raíz (`Inkfarma.py`, `PLAZA_VEA.py`, `SAGA.py`)
- Módulo de Telegram movido a `_pendiente/` (se implementará al final)

---

## 2026-07-04

### 🌀 Preparación para ventilador USB externo (pendiente de que llegue el hardware)
- **Creado**: `mantenimiento/ventilador.py` — control ON/OFF del ventilador por temperatura del CPU (histéresis: enciende ≥70 °C, apaga ≤58 °C) cortando la energía del puerto USB con `uhubctl`. Subcomandos: `--daemon`, `--on`, `--off`, `--detectar`, `--estado`.
- **Creado**: `mantenimiento/cazador-ventilador.service` — servicio systemd de usuario listo para instalar (daemon automático).
- **Creado**: `mantenimiento/52-usb-ventilador.rules` — regla udev para controlar los puertos sin sudo.
- **Pasos al llegar el ventilador**: ver docstring de `mantenimiento/ventilador.py` (instalar uhubctl, detectar puerto, configurar, probar corte real de energía, instalar regla udev y servicio).
- **Nota**: si el hub de la mini PC no corta físicamente el VBUS (común en hubs raíz Intel), el ventilador quedará siempre encendido (~0.5 W) o se necesitará un hub USB externo compatible con uhubctl.
