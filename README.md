# 📚 La Geometría de los Ecos

"La Geometría de los Ecos" es un proyecto literario y tecnológico que narra la trilogía de crecimiento y autodescubrimiento de Kirlian. El proyecto integra un sitio web estático (Zola) para la publicación online y un sistema de generación de audiolibros mediante Python (Google Cloud TTS).

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

## 🌟 La Trilogía

La obra se divide en tres arcos narrativos principales:

1.  **Libro 1: El Viernes Interior** (Búsqueda del reflejo, idealismo).
2.  **Libro 2: Códigos Rotos** (Deconstrucción necesaria, cura de humildad).
3.  **Libro 3: La Búsqueda de un Timón** (Reconstrucción y autoaceptación).

> Para detalles literarios, consulte la documentación en `drafting/`.

---

## 🛠️ Flujo de Trabajo Técnico

### 🌐 Sitio Web (Zola)
La web vive en la carpeta `website/`.
- **Servir localmente**: `zola serve --root website`
- **Compilar**: `zola build --root website`
- **Despliegue**: Automático vía GitHub Actions al hacer push a `main`.

### 🎙️ Generación de Audio
Los scripts se encuentran en `tools/`. Utilizan Google Cloud TTS (modelo Chirp 3 HD) para procesar los capítulos.
- **Script principal**: `python tools/script.py`
- **Libro 1**: `python tools/script_libro1.py`
- **Salida**: Los archivos MP3 se generan en subcarpetas dentro de `tools/`.

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
