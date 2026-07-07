import os
import glob
import json
from datetime import datetime
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIENDAS_DIR = os.path.join(ROOT_DIR, "tiendas")
WEB_DIR = os.path.join(ROOT_DIR, "web")
PUBLIC_DIR = os.path.join(WEB_DIR, "public")

TIENDAS = [
    "inkafarma",
    "plaza_vea",
    "saga_falabella",
    "dermo",
    "efe",
    "shopstar",
    "sodimac",
    "tailoy",
    "promart"
]

def obtener_ultimo_json(tienda):
    """Busca el archivo JSON más reciente en la carpeta de datos de la tienda, ignorando historial_precios.json"""
    patron = os.path.join(TIENDAS_DIR, tienda, "datos", f"{tienda}_*.json")
    archivos = glob.glob(patron)
    if not archivos:
        return None
    # Ordenar por fecha de modificación (el más reciente al final)
    archivos.sort(key=os.path.getmtime)
    return archivos[-1]

def procesar_datos():
    datos_consolidados = {
        "metadata": {
            "ultima_actualizacion": datetime.now().isoformat(),
            "total_tiendas": 0,
            "total_productos": 0
        },
        "tiendas": {}
    }

    for tienda in TIENDAS:
        ultimo_archivo = obtener_ultimo_json(tienda)
        if not ultimo_archivo:
            print(f"⚠️ No se encontraron datos para {tienda}")
            continue

        print(f"✅ Procesando {tienda}: {os.path.basename(ultimo_archivo)}")
        
        # Leer el historial de precios general
        historial_file = os.path.join(TIENDAS_DIR, tienda, "datos", "historial_precios.json")
        historial_datos = {}
        if os.path.exists(historial_file):
            try:
                with open(historial_file, 'r', encoding='utf-8') as f:
                    historial_datos = json.load(f)
            except Exception as e:
                print(f"❌ Error leyendo historial de {tienda}: {e}")
        
        # Leer favoritos
        favoritos_file = os.path.join(TIENDAS_DIR, tienda, "datos", "favoritos.json")
        favoritos_ids = []
        if os.path.exists(favoritos_file):
            try:
                with open(favoritos_file, 'r', encoding='utf-8') as f:
                    favoritos_ids = json.load(f)
            except Exception as e:
                print(f"❌ Error leyendo favoritos de {tienda}: {e}")
        
        try:
            with open(ultimo_archivo, 'r', encoding='utf-8') as f:
                productos_recientes = json.load(f)
        except Exception as e:
            print(f"❌ Error leyendo recientes de {tienda}: {e}")
            continue

        if not productos_recientes:
            continue

        datos_consolidados["tiendas"][tienda] = {
            "nombre": tienda.replace('_', ' ').title(),
            "categorias": {}
        }
        
        datos_consolidados["metadata"]["total_tiendas"] += 1
        
        for p in productos_recientes:
            cat_nombre = p.get('categoria', 'Sin Categoría')
            if not cat_nombre:
                cat_nombre = 'Sin Categoría'
            
            # Normalizar nombre de categoría
            cat_nombre = cat_nombre.strip().title()

            if cat_nombre not in datos_consolidados["tiendas"][tienda]["categorias"]:
                datos_consolidados["tiendas"][tienda]["categorias"][cat_nombre] = []
            
            p_id = p.get('id', '')
            
            # Cruzar con historial
            registros = []
            if p_id in historial_datos:
                registros_historial = historial_datos[p_id].get('registros', [])
                total_registros = sum(1 for r in registros_historial if not r.get('sospechoso'))
                
                # Deduplicar: si hay múltiples scrapes en un mismo día,
                # mantener solo el último registro de cada fecha.
                # Los registros en cuarentena (precio atípico sin confirmar)
                # no llegan al dashboard: no deben definir mínimos ni medianas.
                por_fecha = {}
                for reg in registros_historial:
                    if reg.get('sospechoso'):
                        continue
                    fecha = reg.get('fecha', '')
                    if fecha:
                        por_fecha[fecha] = reg  # el último sobreescribe
                
                # Formato compacto: [fecha, precio_normal, precio_oferta]
                # Esto reduce el JSON enormemente (evita repetir claves 250K×N veces)
                registros = [
                    [f, por_fecha[f].get('precio_normal'), por_fecha[f].get('precio_oferta')]
                    for f in sorted(por_fecha.keys())
                ]
            else:
                total_registros = 1
                registros = [[
                    datetime.now().strftime("%Y-%m-%d"),
                    p.get('precio_normal'),
                    p.get('precio_oferta')
                ]]

            # Mantener imagen para tiendas que tienen imágenes confiables
            TIENDAS_CON_IMAGEN = {'saga_falabella', 'promart'}
            imagen_url = p.get('imagen', '') if tienda in TIENDAS_CON_IMAGEN else ''
            
            producto_obj = {
                "id": p_id,
                "nombre": p.get('nombre', 'Producto sin nombre'),
                "marca": p.get('marca', ''),
                "precio_normal": p.get('precio_normal'),
                "precio_oferta": p.get('precio_oferta'),
                "imagen": imagen_url,
                "url": p.get('url', ''),
                "total_registros": total_registros,
                "historial": registros,
                "es_favorito": p_id in favoritos_ids
            }
            
            datos_consolidados["tiendas"][tienda]["categorias"][cat_nombre].append(producto_obj)
            datos_consolidados["metadata"]["total_productos"] += 1
            
            # Si es favorito, también lo añadimos a la categoría especial "⭐ Favoritos"
            if p_id in favoritos_ids:
                if "⭐ Favoritos" not in datos_consolidados["tiendas"][tienda]["categorias"]:
                    datos_consolidados["tiendas"][tienda]["categorias"]["⭐ Favoritos"] = []
                datos_consolidados["tiendas"][tienda]["categorias"]["⭐ Favoritos"].append(producto_obj)

    # Asegurarnos de que el directorio public exista
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    
    output_path = os.path.join(PUBLIC_DIR, "data.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(datos_consolidados, f, ensure_ascii=False)
    
    print(f"\n🎉 ¡Datos consolidados con éxito en {output_path}!")
    print(f"📊 Total de productos procesados: {datos_consolidados['metadata']['total_productos']}")

if __name__ == "__main__":
    procesar_datos()
