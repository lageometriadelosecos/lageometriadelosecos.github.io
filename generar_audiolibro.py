#!/usr/bin/env python3
"""
Script para convertir los 5 libros en un audiolibro
Extrae solo el contenido limpio sin metadatos
"""

import os
import re
from pathlib import Path

def limpiar_contenido(texto):
    """Limpia el contenido eliminando metadatos y formato markdown, y añade etiquetas de speaker"""
    lineas = texto.split('\n')
    contenido_limpio = []
    en_frontmatter = False
    
    for linea in lineas:
        # Detectar inicio/fin de frontmatter (entre +++)
        if linea.strip() == '+++':
            en_frontmatter = not en_frontmatter
            continue
        
        # Saltar líneas de frontmatter
        if en_frontmatter:
            continue
        
        # Saltar líneas vacías al inicio
        if not contenido_limpio and not linea.strip():
            continue
        
        # Limpiar formato markdown
        linea_limpia = linea
        
        # Eliminar encabezados markdown (# ## ###)
        linea_limpia = re.sub(r'^#{1,6}\s+', '', linea_limpia)
        
        # Eliminar negritas (**texto** o __texto__)
        linea_limpia = re.sub(r'\*\*(.+?)\*\*', r'\1', linea_limpia)
        linea_limpia = re.sub(r'__(.+?)__', r'\1', linea_limpia)
        
        # Eliminar cursivas (*texto* o _texto_)
        linea_limpia = re.sub(r'\*(.+?)\*', r'\1', linea_limpia)
        linea_limpia = re.sub(r'_(.+?)_', r'\1', linea_limpia)
        
        # Eliminar enlaces markdown [texto](url)
        linea_limpia = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', linea_limpia)
        
        # Eliminar separadores (---)
        if re.match(r'^-{3,}$', linea_limpia.strip()):
            continue
        
        # Detectar diálogos (líneas que empiezan con —)
        if linea_limpia.strip().startswith('—'):
            # Agregar etiqueta de personaje para diálogos
            linea_limpia = f"[Personaje]: {linea_limpia.strip()}"
        elif linea_limpia.strip().startswith('>'):
            # Citas o pensamientos - voz reflexiva
            linea_limpia = f"[Reflexión]: {linea_limpia.strip()}"
        elif linea_limpia.strip() and not linea_limpia.strip().startswith('['):
            # Narración normal
            linea_limpia = f"[Narrador]: {linea_limpia.strip()}"
        
        if linea_limpia.strip():
            contenido_limpio.append(linea_limpia)
    
    return '\n'.join(contenido_limpio).strip()

def extraer_titulo(contenido):
    """Extrae el título del capítulo desde el frontmatter"""
    lineas = contenido.split('\n')
    en_frontmatter = False
    
    for linea in lineas:
        if linea.strip() == '+++':
            en_frontmatter = not en_frontmatter
            continue
        
        if en_frontmatter and 'title' in linea:
            # Extraer título: title = "Título del Capítulo"
            match = re.search(r'title\s*=\s*["\'](.+?)["\']', linea)
            if match:
                return match.group(1)
    
    return "Capítulo sin título"

def procesar_libro(libro_dir, libro_num):
    """Procesa todos los capítulos de un libro"""
    print(f"Procesando Libro {libro_num}: {libro_dir.name}")
    
    contenido_libro = []
    
    # Encontrar todos los archivos de capítulos (capitulo*.md)
    capitulos = sorted(libro_dir.glob('capitulo*.md'))
    
    if not capitulos:
        print(f"  ⚠️  No se encontraron capítulos en {libro_dir.name}")
        return ""
    
    for capitulo_path in capitulos:
        try:
            with open(capitulo_path, 'r', encoding='utf-8') as f:
                contenido = f.read()
            
            titulo = extraer_titulo(contenido)
            texto_limpio = limpiar_contenido(contenido)
            
            if texto_limpio:
                # Añadir título del capítulo con etiqueta de speaker
                contenido_libro.append(f"\n\n[Narrador]: {titulo}\n")
                contenido_libro.append(texto_limpio)
                print(f"  ✓ {capitulo_path.name}: {titulo}")
        
        except Exception as e:
            print(f"  ✗ Error procesando {capitulo_path.name}: {e}")
    
    return '\n'.join(contenido_libro)

def main():
    # Directorio base del proyecto
    base_dir = Path(__file__).parent / 'content'
    
    # Lista de libros en orden
    libros = [
        'libro1-viernes-interior',
        'libro2-codigos-rotos',
        'libro3-aquarium',
        'libro4-lepeterno',
        'libro5-aventuras-de-kirlian'
    ]
    
    contenido_completo = []
    contenido_completo.append("[Narrador]: Geometría de los Ecos")
    contenido_completo.append("[Narrador]: La historia de Kirlian\n")
    
    for i, libro_nombre in enumerate(libros, 1):
        libro_dir = base_dir / libro_nombre
        
        if not libro_dir.exists():
            print(f"⚠️  Directorio no encontrado: {libro_dir}")
            continue
        
        # Agregar separador de libro
        contenido_completo.append(f"\n\n[Narrador]: {'='*60}")
        contenido_completo.append(f"[Narrador]: LIBRO {i}")
        contenido_completo.append(f"[Narrador]: {'='*60}\n")
        
        contenido_libro = procesar_libro(libro_dir, i)
        if contenido_libro:
            contenido_completo.append(contenido_libro)
    
    # Guardar el resultado
    output_file = Path(__file__).parent / 'audiolibro_completo.txt'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(contenido_completo))
    
    print(f"\n✅ Audiolibro generado: {output_file}")
    print(f"📊 Tamaño: {output_file.stat().st_size / 1024:.2f} KB")

if __name__ == '__main__':
    main()
