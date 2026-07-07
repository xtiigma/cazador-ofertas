# 🚀 WEBSCRAPING 2.0 — Plan de evolución del Cazador de Ofertas

> **Propósito:** Hoja de ruta estructurada para llevar el sistema de su nivel actual
> (≈83/100: scraping API-first sin navegadores, resiliente y educado con las tiendas)
> a nivel ≈92/100 (ingeniería de datos y mantenibilidad a la altura del scraping).
>
> **Cómo usar este documento:** las etapas son independientes y están ordenadas por
> retorno/esfuerzo. Para ejecutar una, pedirle a la IA: *"implementa la Etapa N de
> webscraping2.0.md"*. Cada etapa define su criterio de éxito y cómo revertirla.
> Al completar una etapa: marcarla aquí, registrar el detalle en `parche.md`.
>
> **Regla de oro heredada (NO negociable sin decisión explícita del usuario):**
> scraping mínimo — 1 petición a la vez, 10 min entre tiendas. La velocidad nunca
> es prioridad; la estabilidad térmica y la amabilidad con las tiendas sí.
>
> **🌡️ META PRINCIPAL (fijada por el usuario el 2026-07-07): BAJAR LA TEMPERATURA.**
> Toda etapa se evalúa primero por su impacto térmico. En software, la palanca más
> grande que queda es la Etapa 1 (SQLite: elimina el parseo del JSON gigante); en
> hardware, el ventilador USB. Validar cada mejora contra el desglose 🌡️ por tienda
> del aviso diario de Telegram.

---

## Estado de partida (2026-07-07)

Lo que ya está bien y NO hay que rehacer:

- ✅ **9/9 tiendas sin navegador** (API-first): VTEX, `__NEXT_DATA__`, Algolia + Lambda, etc.
- ✅ Aislamiento por subproceso + barrido del árbol de procesos (anti-OOM, anti-zombies).
- ✅ Freno térmico duro (85 °C mata la tienda) + suave (72 °C congela, 62 °C reanuda).
- ✅ Historial con cuarentena de outliers, mediana anti-Cyber-Wow, poda de 60 días.
- ✅ Gangas del día + temperatura por tienda en el aviso de Telegram.
- ✅ systemd timer diario 12:10, techo de RAM (`MemoryHigh=4G`), rotación de snapshots/logs.

Deudas que este plan ataca, por orden de gravedad:

1. Historial = JSON gigante (Plaza Vea 474 MB) cargado en RAM entera cada ciclo.
2. Proyecto sin control de versiones (ningún cambio es reversible).
3. Cero tests automatizados (los bugs se descubren en producción, ej. id `"p"` de Shopstar).
4. Sin alertas de calidad de datos (si una tienda cambia su API, se nota días después).
5. Cobertura parcial de catálogos (decisión de alcance, no defecto).

---

## Etapa 0 — Control de versiones con git 🏗️ — ✅ COMPLETADA (2026-07-07)

**Qué es:** `git init` crea un repositorio LOCAL (una carpeta oculta `.git/` dentro del
proyecto). Desde ahí, cada "commit" es una foto exacta del código en ese momento, con
fecha y descripción. **Nada sale de la máquina** salvo que un día se configure un
remoto (GitHub privado, opcional). Complementa a `parche.md`: la bitácora cuenta el
*porqué* de cada cambio; git guarda el *código exacto* para poder volver a él.

**Por qué primero:** es la red de seguridad de todas las etapas siguientes. Hoy, si
una migración sale mal, no hay vuelta atrás (la migración de Saga, el fix de Shopstar
y el freno térmico de hoy sobrescribieron el código anterior para siempre).

**Pasos:**
1. `git init` en la raíz del proyecto.
2. Crear `.gitignore` — el repo versiona CÓDIGO, no datos pesados ni volátiles:
   - `tiendas/*/datos/` (historiales de cientos de MB + snapshots diarios)
   - `logger/logs/`, `__pycache__/`, `*.pyc`
   - `mantenimiento/backups/`, `*.bak*`
   - `.ciclo_en_curso` (lockfile en runtime)
   - secretos si los hubiera (token del bot de Telegram: verificar dónde vive antes del primer commit)
3. Primer commit: todo el código + docs (`README.md`, `parche.md`, este archivo).
4. Costumbre nueva: un commit por cambio significativo (la IA lo hace al final de cada tarea).

**Criterio de éxito:** `git log` muestra el commit inicial; `git diff` tras editar
cualquier archivo muestra las líneas cambiadas; `git checkout -- archivo` lo restaura.

**Esfuerzo:** 15 minutos. **Riesgo:** cero (no toca el comportamiento de nada).
**Reversión:** borrar la carpeta `.git/` y el proyecto queda como hoy.

---

## Etapa 1 — Historial en SQLite 🗄️ *(= "Fase 2" del plan de optimización acordado)* — 🔄 EN CURSO

> **Estado 2026-07-07 (tarde):** capa de acceso (`analizador/almacen.py`), migrador
> (`mantenimiento/migrar_sqlite.py`) y despacho dual LISTOS y probados (paridad
> total contra Promart: 46,921 productos / 413,775 registros, cuarentena y
> confirmación incluidas). **Shopstar, EFE y PLAZA VEA ya operan en SQLite.**
> Plaza Vea (el foco térmico: su `json.dump` de 481 MB causaba el pico de 72 °C,
> verificado por experimento) migró el 07/07 15:07 con `--verificar` OK:
> 269,107 productos / 5,137,931 registros, análisis idéntico, 481 MB → 397 MB.
> Falta: tras validar el ciclo del 08/07, migrar las 6 restantes
> (sodimac, dermo, tailoy, inkafarma, saga_falabella, promart) con
> `python mantenimiento/migrar_sqlite.py <tienda> --verificar`.

**Problema:** cada ciclo carga, actualiza y reescribe el JSON entero de cada tienda.
Plaza Vea: 474 MB de disco ≈ ~2 GB en RAM, minutos de CPU al 100% (uno de los focos
de temperatura que mitigamos el 07/07 — la mitigación redujo 3 parseos a 1, pero el
parseo gigante sigue existiendo). SQLite lo elimina de raíz: se consulta y escribe
solo lo del día, indexado, sin cargar nada entero.

**Diseño propuesto:**
- Un archivo `historial.db` por tienda (mismo directorio que el JSON actual).
- Tablas: `productos(id TEXT PK, nombre, marca, url)` y
  `registros(producto_id, fecha, precio_normal, precio_oferta, precio_minimo, sospechoso INT)`
  con índice `(producto_id, fecha)`.
- Capa de acceso nueva (`analizador/almacen.py` o similar) con las MISMAS operaciones
  que hoy usan `historial_precios.py`, `detector_descuentos.py`, `cazador.py` y
  `web/build_data.py`: registrar del día, mediana reciente, mínimo histórico, precio
  anterior, poda de 60 días.

**Pasos:**
1. Escribir la capa de acceso + script migrador JSON → SQLite (por tienda, con backup).
2. Migrar primero UNA tienda pequeña (Shopstar o EFE) y correr en paralelo unos días:
   registrar en ambos formatos y comparar salidas (ofertas, mínimos, gangas idénticos).
3. Migrar el resto, Plaza Vea al final (con su backup `.bak` fuera del repo).
4. Retirar la ruta JSON del código cuando haya paridad validada; conservar los `.bak`
   un par de semanas.

**Criterio de éxito:** mismo aviso de Telegram (ofertas/mínimos/gangas) que produciría
el JSON; RAM del paso "historial" de Plaza Vea de ~2 GB → <100 MB; segmento térmico
de Plaza Vea visiblemente más frío en el desglose 🌡️ del aviso.

**Esfuerzo:** 1-2 sesiones. **Riesgo:** medio (es EL activo del proyecto: meses de
precios). Mitigación: migración tienda por tienda, validación de paridad, backups.
**Nota:** hecho sobre libSQL/SQLite, la Etapa 5 (Turso) reutiliza este mismo trabajo.

---

## Etapa 2 — Tests automatizados mínimos 🧪

**Qué cubrir (lo que ya nos mordió o es crítico):**
1. Extracción de IDs por tienda con fixtures GRABADAS (respuestas JSON/HTML reales
   guardadas en `tests/fixtures/`) — sin red. Habría atrapado el bug del id `"p"`.
2. Cuarentena de precios: outlier entra sospechoso, se confirma al persistir ±15%.
3. Mediana y poda de `historial_precios.py`.
4. Gangas: umbral 20%, filtro `MAX_AHORRO_CREIBLE=90%`, dedup por (tienda, url), favoritos.
5. `_normalizar_slug`/`resolver_departments` de Inkafarma (tildes, sufijo `-1`).

**Pasos:** `pip install pytest` en el venv → carpeta `tests/` → fixtures → casos.
Correr a mano antes de cada cambio grande (`~/.venvs/cazador-ofertas/bin/pytest`);
la IA los corre siempre tras tocar código.

**Criterio de éxito:** suite completa en <30 s en la mini PC, sin tocar la red.
**Esfuerzo:** 1 sesión. **Riesgo:** cero (no toca código de producción).

---

## Etapa 3 — Alertas de calidad de datos (detección de deriva) 📉

**Problema:** si una tienda cambia su API o HTML, hoy se nota como "Sin productos" o,
peor, con datos degradados silenciosos (precios en 0, campos vacíos) que envenenan
el historial hasta que alguien mira.

**Chequeos post-scrape por tienda (en `main.py`, antes de registrar):**
1. Volumen: productos de hoy < 50% de la mediana de los últimos 7 ciclos → ⚠️ en el aviso.
2. Precios: >20% de productos sin ningún precio → ⚠️ (hoy eso entra igual al historial).
3. Los ⚠️ se acumulan y salen en el aviso diario de Telegram (sección "salud de datos").

**Criterio de éxito:** simular una degradación (fixture con precios vacíos) y ver la
alerta en el resumen; cero falsos positivos en una semana de ciclos normales.
**Esfuerzo:** media sesión. **Riesgo:** bajo (solo observa y avisa, no bloquea).

---

## Etapa 4 — Cobertura de catálogo ampliada 🔭 *(OPCIONAL — decisión de producto)*

No es deuda técnica: es elegir cuánto catálogo queremos. Requiere decisión explícita
del usuario porque alarga el ciclo y aumenta las peticiones (va contra la regla de oro,
así que se decide caso por caso).

- **4a. Inkafarma completo:** hoy trae los 250 mejor rankeados por categoría (~1.8K de
  45K). Algolia pagina con `offset`: se puede subir gradualmente (500, 1000/categoría).
  Costo: más páginas de `filtered-products` (el paso lento), ciclo más largo.
- **4b. Plaza Vea — hojas que topan el límite VTEX (2500):** subdividir esas hojas con
  filtros extra (marca/precio). Solo ~4 hojas lo tocan; ganancia moderada.
- **4c. Plaza Vea — recortar (dirección contraria):** PV es el 83% del volumen total y
  el foco térmico/de datos. Limitarla a categorías con productos que realmente
  interesan aliviaría TODO el sistema (ciclo, RAM, disco, temperatura). Idea anotada
  desde junio; sigue pendiente de decisión.
  - *2026-07-07:* primer paso dado — **tope global de 10 páginas por categoría/hoja**
    en todos los scrapers (decisión del usuario, meta térmica): Plaza Vea 200→10,
    Promart 54→10, Inkafarma ∞→10; el resto ya estaba en ≤10.

**Esfuerzo:** 4a/4b media sesión cada una; 4c depende de definir qué categorías importan.

---

## Etapa 5 — Nube: Turso + dashboard remoto ☁️ *(= "Fase 3" del plan de optimización)*

Réplica del historial (ya en SQLite por la Etapa 1 — mismo motor) en Turso free tier:
dashboard consultable sin encender la mini PC, respaldo externo de los datos, cola
offline si no hay red, retención dinámica según cuota, y escribir solo cambios reales
(~0.7M writes/mes, dentro del free tier). Detalle ya acordado en el plan de
optimización. **Prerequisito:** Etapa 1 terminada y estable.

**Esfuerzo:** 1-2 sesiones. **Riesgo:** bajo (la nube es réplica; la verdad local).

---

## Paralelo — Hardware 🌀

- **Ventilador USB 120 mm** (en camino): al llegar, seguir el CHECKLIST de la entrada
  correspondiente en `parche.md` (`uhubctl`, detectar hub/puerto, verificar corte real
  de VBUS, regla udev, `cazador-ventilador.service`). `mantenimiento/ventilador.py`
  ya está listo con histéresis 70/58 °C. Con él, el freno suave debería activarse
  rara vez y el ciclo no se alargará.

---

## Resumen ejecutivo

| Orden | Etapa | Esfuerzo | Riesgo | Puntaje estimado |
|---|---|---|---|---|
| 1º | 0 — Git | 15 min | Cero | 83 → 85 |
| 2º | 1 — SQLite | 1-2 sesiones | Medio (mitigado) | 85 → 90 |
| 3º | 2 — Tests | 1 sesión | Cero | 90 → 92 |
| 4º | 3 — Alertas de deriva | ½ sesión | Bajo | 92 → 93 |
| Decisión | 4 — Cobertura | variable | Bajo | según alcance |
| Futuro | 5 — Turso | 1-2 sesiones | Bajo | +respaldo y acceso remoto |

## Anti-metas (decidido: NO hacer)

- ❌ Frameworks de scraping (Scrapy, etc.): reescritura sin ganancia; lo actual es más simple y ya es API-first.
- ❌ Proxies rotativos / evasión anti-bot: innecesario (las tiendas responden bien) y cambia el perfil ético del proyecto.
- ❌ Subir concurrencia o bajar pausas: regla de oro. Solo con decisión explícita del usuario.
- ❌ Visor JSON / gzip del historial: la Etapa 1 lo vuelve obsoleto.

---

*Creado el 2026-07-07 tras las mejoras anti-temperatura (ver entrada de esa fecha en
`parche.md`). Antes de arrancar cualquier etapa: validar que el ciclo del 07/07 12:10
salió bien (temperaturas <70 °C en Plaza Vea e Inkafarma, 🧊/▶️ actuando con normalidad).*
