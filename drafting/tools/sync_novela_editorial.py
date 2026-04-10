#!/usr/bin/env python3
"""Sincroniza `website/content` desde `novela_editorial.md` y regenera el EPUB."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Chapter:
    heading: str
    number: int
    title: str
    body: str
    slug: str = ""


@dataclass
class Book:
    heading: str
    number: int
    title: str
    slug: str = ""
    chapters: list[Chapter] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--editorial",
        default=str(root / "drafting" / "tools" / "novela_editorial.md"),
        help="Markdown editorial fuente.",
    )
    parser.add_argument(
        "--content-dir",
        default=str(root / "website" / "content"),
        help="Directorio content de Zola.",
    )
    parser.add_argument(
        "--chapter-nav",
        default=str(root / "website" / "data" / "chapter_navigation.json"),
        help="JSON de navegacion entre capitulos.",
    )
    parser.add_argument(
        "--epub",
        default=str(root / "drafting" / "tools" / "novela_editorial.epub"),
        help="EPUB de salida.",
    )
    parser.add_argument(
        "--cover",
        default=str(root / "drafting" / "novela" / "portada.png"),
        help="Portada para el EPUB.",
    )
    parser.add_argument(
        "--title",
        default="La Geometría de los Ecos",
        help="Titulo del EPUB.",
    )
    parser.add_argument(
        "--author",
        default="Ricardo Ruiz",
        help="Autor del EPUB.",
    )
    parser.add_argument(
        "--lang",
        default="es",
        help="Idioma del EPUB.",
    )
    return parser.parse_args()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "-", ascii_value)
    return ascii_value.strip("-")


def parse_numbered_heading(line: str, prefix: str) -> tuple[int, str]:
    pattern = rf"^{re.escape(prefix)}\s+(\d+):\s+(.+?)\s*$"
    match = re.match(pattern, line)
    if not match:
        raise ValueError(f"Cabecera invalida: {line!r}")
    return int(match.group(1)), match.group(2).strip()


def parse_editorial(editorial_path: Path) -> tuple[str, list[Book]]:
    lines = editorial_path.read_text(encoding="utf-8").splitlines()
    title = ""
    books: list[Book] = []
    current_book: Book | None = None
    current_chapter: Chapter | None = None
    buffer: list[str] = []

    def flush_chapter() -> None:
        nonlocal buffer, current_chapter, current_book
        if current_chapter is None or current_book is None:
            buffer = []
            return
        body_lines = list(buffer)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        while body_lines and body_lines[-1].strip() == "---":
            body_lines.pop()
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()
        current_chapter.body = "\n".join(body_lines).strip()
        current_book.chapters.append(current_chapter)
        current_chapter = None
        buffer = []

    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            flush_chapter()
            number, book_title = parse_numbered_heading(line[3:].strip(), "Libro")
            current_book = Book(heading=line[3:].strip(), number=number, title=book_title)
            books.append(current_book)
            continue
        if line.startswith("### "):
            flush_chapter()
            if current_book is None:
                raise ValueError("Capitulo encontrado antes de un libro")
            number, chapter_title = parse_numbered_heading(line[4:].strip(), "Capítulo")
            current_chapter = Chapter(heading=line[4:].strip(), number=number, title=chapter_title, body="")
            continue
        if current_chapter is not None:
            buffer.append(line)

    flush_chapter()

    if not title:
        raise ValueError("No se encontro el titulo principal de la novela editorial")
    if not books:
        raise ValueError("No se encontraron libros en la novela editorial")
    return title, books


def assign_slugs(books: list[Book]) -> None:
    for book in books:
        book.slug = f"libro{book.number}-{slugify(book.title)}"
        for chapter in book.chapters:
            chapter.slug = f"capitulo{chapter.number}-{slugify(chapter.title)}"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def render_book_index(book: Book, prev_book: Book | None, next_book: Book | None) -> str:
    lines = [
        "+++",
        f'title = "{book.heading}"',
        f"weight = {book.number}",
        'template = "section.html"',
        "[extra]",
        "hide_title = true",
        "hide_pages = true",
        "hide_subsections = true",
        "+++",
        "",
        f"# {book.heading}",
        "",
        "## Capítulos",
        "",
    ]

    for chapter in book.chapters:
        lines.append(f"- [{chapter.heading}](@/{book.slug}/{chapter.slug}.md)")

    nav_parts: list[str] = []
    if prev_book is not None:
        nav_parts.append(f"**[← Libro Anterior](@/{prev_book.slug}/_index.md)**")
    else:
        nav_parts.append("**[← Inicio](../)**")
    nav_parts.append("**[Inicio](../)**")
    if next_book is not None:
        nav_parts.append(f"**[Siguiente Libro →](@/{next_book.slug}/_index.md)**")

    lines.extend(["", "---", "", "## Navegación", "", " | ".join(nav_parts)])
    return "\n".join(lines)


def render_chapter(book: Book, chapter: Chapter) -> str:
    taxonomy = f"libro{book.number}-{slugify(book.title).replace('-', ' ').title().replace(' ', '-')}"
    lines = [
        "+++",
        f'title = "{chapter.heading}"',
        f"weight = {chapter.number}",
        f'novela = ["{taxonomy}"]',
        "+++",
        "",
        chapter.body.strip(),
    ]
    return "\n".join(lines)


def build_navigation(books: list[Book]) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    navigation: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    for book in books:
        book_nav: dict[str, dict[str, dict[str, str]]] = {}
        for index, chapter in enumerate(book.chapters):
            entry: dict[str, dict[str, str]] = {}
            if index > 0:
                previous = book.chapters[index - 1]
                entry["previous"] = {
                    "title": previous.heading,
                    "url": f"/{book.slug}/{previous.slug}/",
                }
            if index + 1 < len(book.chapters):
                nxt = book.chapters[index + 1]
                entry["next"] = {
                    "title": nxt.heading,
                    "url": f"/{book.slug}/{nxt.slug}/",
                }
            book_nav[f"{chapter.slug}.md"] = entry
        navigation[book.slug] = book_nav
    return navigation


def render_root_index(books: list[Book]) -> str:
    lines = [
        "+++",
        'title = "La Geometría de los Ecos"',
        'sort_by = "weight"',
        "[extra]",
        "hide_subsections = true",
        "hide_pages = true",
        "+++",
        "",
        "Una mente obsesionada con la lógica tropieza con el caos de la intimidad y el cuerpo. "
        "Kirlian intenta programar su propia vida mientras amigos, amores y crisis lo obligan a reescribir el código. "
        "Tres libros narran ese proceso de depuración: del resplandor juvenil a la arquitectura final de sí mismo.",
        "",
        "## Explora los Libros",
        "",
    ]
    for book in books:
        lines.append(f"- **[{book.heading}](@/{book.slug}/_index.md)**")
    lines.extend(["", "---", "", "*Cada momento aparentemente oscuro se revela como un paso necesario hacia la autenticidad y la conexión genuina.*"])
    return "\n".join(lines)


def update_auxiliary_pages(content_dir: Path) -> None:
    author_path = content_dir / "autor" / "index.md"
    if author_path.exists():
        text = author_path.read_text(encoding="utf-8").replace("seis libros", "tres libros")
        author_path.write_text(text, encoding="utf-8")

    personajes_path = content_dir / "wiki" / "personajes" / "_index.md"
    if personajes_path.exists():
        text = personajes_path.read_text(encoding="utf-8").replace("saga de seis libros", "trilogía")
        personajes_path.write_text(text, encoding="utf-8")


def sync_content(title: str, books: list[Book], content_dir: Path, chapter_nav_path: Path) -> None:
    del title  # El titulo global se usa en portada y EPUB, no en carpetas.
    for book_dir in sorted(content_dir.glob("libro*")):
        shutil.rmtree(book_dir)

    for index, book in enumerate(books):
        prev_book = books[index - 1] if index > 0 else None
        next_book = books[index + 1] if index + 1 < len(books) else None
        book_dir = content_dir / book.slug
        write_text(book_dir / "_index.md", render_book_index(book, prev_book, next_book))
        for chapter in book.chapters:
            write_text(book_dir / f"{chapter.slug}.md", render_chapter(book, chapter))

    write_text(content_dir / "_index.md", render_root_index(books))
    update_auxiliary_pages(content_dir)
    write_text(chapter_nav_path, json.dumps(build_navigation(books), ensure_ascii=False, indent=2))


def build_epub(editorial_path: Path, epub_path: Path, cover_path: Path, title: str, author: str, lang: str) -> None:
    epub_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "pandoc",
        str(editorial_path),
        "--from=markdown",
        "--to=epub3",
        "--standalone",
        "--toc",
        "--metadata",
        f"title={title}",
        "--metadata",
        f"author={author}",
        "--metadata",
        f"lang={lang}",
        "-o",
        str(epub_path),
    ]
    if cover_path.exists():
        cmd.insert(-2, f"--epub-cover-image={cover_path}")
    subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    editorial_path = Path(args.editorial).resolve()
    content_dir = Path(args.content_dir).resolve()
    chapter_nav_path = Path(args.chapter_nav).resolve()
    epub_path = Path(args.epub).resolve()
    cover_path = Path(args.cover).resolve()

    title, books = parse_editorial(editorial_path)
    assign_slugs(books)
    sync_content(title, books, content_dir, chapter_nav_path)
    build_epub(editorial_path, epub_path, cover_path, args.title or title, args.author, args.lang)
    print(f"Content sincronizado desde {editorial_path}")
    print(f"EPUB regenerado en {epub_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
