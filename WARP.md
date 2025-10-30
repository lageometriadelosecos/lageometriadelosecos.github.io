# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.



## Project Overview

"Geometría de los Ecos" is a philosophical trilogy about Kirlian's journey of growth and self-discovery. The project combines a Zola-based static website for publishing the novel with Python scripts for text-to-speech audio generation using Google Cloud TTS.

## Common Commands

### Zola (Static Site)

```bash
# Build the site locally
zola build

# Serve the site locally with live reload (default: http://127.0.0.1:1111)
zola serve

# Check for errors without building
zola check
```

### Python Audio Generation

```bash
# Activate virtual environment
source .venv/bin/activate

# Generate audio for etica.md
python script.py

# Generate audio for Libro 1 chapters
python script_libro1.py
```

### Novel PDF Generation

```bash
# Generate PDF from novela.md using pandoc
cd novela
./maquetar.sh

# After running, compile the maquetada markdown to PDF:
# pandoc novela_maquetada.md -o output.pdf --from markdown --template=plantilla.tex --pdf-engine=xelatex
```

### Deployment

Deployment is automated via GitHub Actions (`.github/workflows/main.yml`). On push to `main`, the site is built with Zola and deployed to GitHub Pages on the `master` branch.

## Repository Architecture

### Content Structure

The trilogy is organized into three distinct books within `content/`:

- **`content/libro1-viernes-interior/`** (Chapters 0-11): "El Viernes Interior" - The search for connection and intellectual identity
- **`content/libro2-codigos-rotos/`** (Chapters 12-39): "Códigos Rotos" - Deconstruction and learning through crisis  
- **`content/libro3-busqueda-timon/`** (Chapters 40-44): "La Búsqueda de un Timón" - Reconstruction and self-acceptance

Each book contains individual markdown files per chapter following the pattern `capitulo[N]-[title].md` with TOML front matter (`+++` delimiters).

### Text-to-Speech System

Two main scripts handle audio generation:

- **`script.py`**: Processes single markdown files (like `etica.md`) into audio
- **`script_libro1.py`**: Processes all chapters in `content/libro1-viernes-interior/`

**Key Architecture:**
1. **Authentication**: Uses Google Cloud service account credentials (`credenciales.json`) with automatic token refresh
2. **Text Processing Pipeline**:
   - Parse markdown with TOML front matter (regex-based extraction)
   - Clean text with `clean_chapter_text()`: removes markdown syntax, normalizes whitespace, preserves sentence boundaries
   - Split into chunks with `split_text()`: max 4800 chars, intelligent splitting at sentence boundaries to avoid mid-sentence cuts
3. **API Integration**: Google Cloud Text-to-Speech API with voice `es-ES-Chirp3-HD-Fenrir`, 24kHz MP3 output
4. **Resilience**: Exponential backoff retry logic (3 attempts), handles rate limiting and transient errors
5. **Audio Assembly**: Uses `pydub` to concatenate MP3 chunks into chapter-level audio files

Output directories: `etica/` (for script.py) and `audio_libro1/` (for script_libro1.py)

### Static Site Generation (Zola)

- **Theme**: `after-dark` (as git submodule in `themes/`)
- **Configuration**: `config.toml` - base URL set to `https://lageometriadelosecos.github.io`
- **Taxonomies**: Custom `novela` taxonomy with weight-based ordering for chapter navigation
- **Content**: All novel content in `content/` directory with TOML front matter

### Narrative Documents

The `novela/` directory contains compiled versions and supplementary materials:
- `novela.md` / `novela_maquetada.md`: Full concatenated novel for PDF generation
- `trilogia.md`, `resumen.md`, `introduccion.md`: Structural and thematic documentation
- `maquetar.sh`: Bash script that converts `novela.md` to pandoc-ready format with LaTeX template

### Credentials and Secrets

**IMPORTANT**: `credenciales.json` contains Google Cloud service account credentials. This file MUST be kept secure and never committed to version control if it contains real credentials.

## Development Patterns

### Adding New Chapters

1. Create markdown file in appropriate `libro[N]-*/` directory following naming convention
2. Include TOML front matter with `title` and `weight` (determines order)
3. Test locally with `zola serve`
4. Commit and push - GitHub Actions handles deployment

### Audio Generation Workflow

1. Ensure `.venv` is activated and dependencies installed (`google-oauth2`, `pydub`, `beautifulsoup4`, `requests`)
2. Update `INPUT_MARKDOWN_FILE` in script if needed
3. Run script - it will automatically handle chunking, API calls, and concatenation
4. Check `DEBUG_MODE = True` in scripts for verbose logging during troubleshooting

### Text Processing Considerations

The `clean_chapter_text()` function is critical for TTS quality:
- Removes markdown formatting (bold, italic, links, headers, lists, code blocks)
- Preserves sentence boundaries (periods, exclamation marks, question marks followed by newlines)
- Converts mid-sentence line breaks to spaces
- Maintains paragraph separation with single newlines

When editing this function, test with sample chapters to ensure natural-sounding audio output.

## Key Dependencies

- **Zola**: v0.20.0 (static site generator)
- **Python**: 3.x with venv at `.venv/`
- **Python Packages**: google-auth, google-oauth2, pydub, beautifulsoup4, requests
- **Pandoc + XeLaTeX**: For PDF generation (not in venv, system-level)
- **Git Submodules**: `themes/after-dark` theme

## Content Philosophy

The trilogy follows a transformative narrative arc:
- **Libro 1**: Youthful brilliance and idealism
- **Libro 2**: Necessary deconstruction and learning through pain  
- **Libro 3**: Mature reconstruction and finding one's center

The reframing is from "dark story of failures" to "luminous journey of authentic growth" - this thematic lens should inform any editorial decisions.
