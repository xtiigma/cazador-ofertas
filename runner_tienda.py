"""
🧩 Runner aislado de una sola tienda.

Lo invoca main.py como SUBPROCESO independiente (uno por tienda). La razón es la
memoria: scrapers como Saga Falabella levantan varios Chrome y, corriendo todos
dentro del mismo proceso de main.py, la RAM se iba acumulando tienda tras tienda
hasta que el kernel mataba el ciclo entero por OOM (mini PC de 8 GB).

Al ejecutar cada tienda en su propio proceso, cuando este termina el sistema
operativo recupera el 100% de su memoria —incluidos todos los Chrome hijos— de
forma garantizada. Así el pico de RAM es "una tienda a la vez", no la suma de 9.

Uso interno (no se llama a mano):
    python runner_tienda.py <scraper_dir> <es_async:0|1> <out_path.json>

Escribe la lista de productos como JSON en <out_path.json>. Si algo falla,
escribe una lista vacía y sale con código != 0 para que el padre lo registre.
"""

import asyncio
import importlib
import json
import os
import sys
import traceback


def main() -> int:
    if len(sys.argv) != 4:
        print(f"Uso: {sys.argv[0]} <scraper_dir> <es_async:0|1> <out_path>", file=sys.stderr)
        return 2

    scraper_dir, es_async, out_path = sys.argv[1], sys.argv[2] == "1", sys.argv[3]
    scraper_dir = os.path.abspath(scraper_dir)  # robusto ante rutas relativas

    productos: list = []
    codigo = 0
    try:
        sys.path.insert(0, scraper_dir)
        os.chdir(scraper_dir)
        scraper = importlib.import_module("scraper")

        if es_async:
            productos = asyncio.run(scraper.main())
        else:
            productos = scraper.main()

        productos = productos if productos else []
    except Exception:
        traceback.print_exc()
        productos = []
        codigo = 1

    # Escribir el resultado SIEMPRE (aunque sea []), para que el padre lo lea.
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(productos, f, ensure_ascii=False)
    except Exception:
        traceback.print_exc()
        codigo = 1

    return codigo


if __name__ == "__main__":
    sys.exit(main())
