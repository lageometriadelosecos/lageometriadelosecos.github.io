# 📚La Geometría de los Ecos

<img src="drafting/novela/portada.png" width="200" height="600">

📥 **Descarga EPUB**: [novela_editorial.epub](drafting/tools/novela_editorial.epub)

---

## 🏗️ Estructura del Proyecto

El proyecto está organizado en cuatro áreas lógicas para facilitar el flujo de trabajo:

```text
.
├── website/     # Sitio web (Zola): contenido público, temas y plantillas.
├── drafting/    # Espacio de escritura: borradores, arquitectura y diario.
├── research/    # Investigación: world-building (filosofía, religión, wiki).
└── tools/       # Herramientas: scripts de audiolibro y utilidades.
```

---

## 🛠️ Flujo de Trabajo Técnico

### 🌐 Sitio Web (Zola)
La web vive en la carpeta `website/`.
- **Servir localmente**: `zola serve --root website`
- **Compilar**: `zola build --root website`
- **Despliegue**: Automático vía GitHub Actions al hacer push a `main`.

### 🎙️ Generación de Audio
La generación de audiolibro se divide en dos pasos:
- **Generar texto consolidado**: `python tools/generar_libro.py --output tools/audiolibro_completo.txt`
- **Generar audio desde ese texto**: `python tools/text_to_speech.py --input tools/audiolibro_completo.txt --output tools/audiolibro/audiolibro_completo.mp3`
- **Salida**: `generar_libro.py` escribe el fichero de texto y `text_to_speech.py` produce el MP3 a partir de ese fichero.

### 📄 Exportación a PDF/EPUB
Utilizamos Pandoc y XeLaTeX para maquetación profesional.
- Los archivos fuente están en `drafting/novela/`.
- El script de maquetación se encuentra en `tools/` (o directamente ejecutable desde `drafting/`).

---

## 📝 Guía de Escritura

1.  **Investigación**: Los datos de world-building se mantienen en `research/`.
2.  **Borradores**: Escribe y refina en `drafting/`.
3.  **Publicación**: Copia los capítulos terminados a `website/content/` con su correspondiente frontmatter TOML.
4.  **Git**: Cada commit debe ser atómico (ej: `writing: capitulo 5`, `research: notas de psiquiatría`).

---

## 🚀 Despliegue CI/CD
El archivo `.github/workflows/main.yml` gestiona la compilación automática. Se ha configurado para buscar el proyecto Zola en la ruta `website/`.

---

*Transformando la narrativa en una experiencia estructurada y multicanal.*
