#!/usr/bin/env python3
"""Genera un fichero de texto consolidado a partir de `website/content`."""

from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BOOKS = [
    "libro1-viernes-interior",
    "libro2-codigos-rotos",
    "libro3-aquarium",
    "libro4-pandemonium",
    "libro5-aventuras-de-kirlian",
]


@dataclass
class Chapter:
    book_slug: str
    title: str
    source_path: Path
    text: str


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--content-dir",
        default=str(root / "website" / "content"),
        help="Directorio con los libros en markdown.",
    )
    parser.add_argument(
        "--output",
        default=str(root / "tools" / "audiolibro_completo.txt"),
        help="Fichero de salida con el texto consolidado.",
    )
    parser.add_argument(
        "--book",
        action="append",
        dest="books",
        help="Libro a incluir. Se puede repetir. Por defecto se usan todos los libros conocidos.",
    )
    parser.add_argument(
        "--speaker-labels",
        action="store_true",
        help="Añade etiquetas [Narrador]/[Personaje] al texto exportado.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Activa trazas de depuración.",
    )
    return parser.parse_args()


def debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"DEBUG: {message}")


def discover_books(content_dir: Path, selected_books: list[str] | None) -> list[Path]:
    if selected_books:
        return [content_dir / slug for slug in selected_books]

    books = [content_dir / slug for slug in DEFAULT_BOOKS if (content_dir / slug).exists()]
    if books:
        return books

    return sorted(path for path in content_dir.glob("libro*") if path.is_dir())


def extract_title_and_body(content: str, fallback_title: str) -> tuple[str, str]:
    title = fallback_title
    if content.startswith("+++"):
        parts = content.split("+++", 2)
        if len(parts) == 3:
            frontmatter = parts[1]
            body = parts[2]
            match = re.search(r'^title\s*=\s*["\'](.+?)["\']', frontmatter, re.MULTILINE)
            if match:
                title = match.group(1).strip()
            return title, body
    return title, content


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"~~~.*?~~~", "", text, flags=re.DOTALL)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\^[^\]]+\]", "", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|.*\|.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"_(.*?)_", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    return text


def clean_chapter_text(raw_text: str) -> str:
    if not raw_text:
        return ""

    text = strip_markdown(raw_text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text).strip()

    placeholder = "##NEWLINE_PLACEHOLDER##"
    text = re.sub(r"([.!?])\n", rf"\1{placeholder}", text)
    text = re.sub(r"\n(\s*\n)+", placeholder, text)
    text = text.replace("\n", " ")
    text = text.replace(placeholder, "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def load_chapters(book_dir: Path, debug_enabled: bool) -> list[Chapter]:
    chapters: list[Chapter] = []
    for chapter_path in sorted(book_dir.glob("capitulo*.md")):
        content = chapter_path.read_text(encoding="utf-8")
        title, body = extract_title_and_body(content, chapter_path.stem)
        text = clean_chapter_text(body)
        if text:
            chapters.append(Chapter(book_slug=book_dir.name, title=title, source_path=chapter_path, text=text))
            debug(debug_enabled, f"Cargado {chapter_path} ({len(text)} chars)")
    return chapters


def label_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("—"):
            lines.append(f"[Personaje]: {stripped}")
        elif stripped.startswith(">"):
            lines.append(f"[Reflexión]: {stripped}")
        else:
            lines.append(f"[Narrador]: {stripped}")
    return "\n".join(lines)


def build_text_output(chapters_by_book: list[tuple[Path, list[Chapter]]], speaker_labels: bool) -> str:
    blocks = ["Geometría de los Ecos", "La historia de Kirlian"]
    for index, (book_dir, chapters) in enumerate(chapters_by_book, start=1):
        blocks.extend(["", "=" * 60, f"LIBRO {index}: {book_dir.name}", "=" * 60])
        for chapter in chapters:
            blocks.extend(["", chapter.title, "", label_text(chapter.text) if speaker_labels else chapter.text])
    return "\n".join(blocks).strip() + "\n"


def main() -> int:
    args = parse_args()
    content_dir = Path(args.content_dir).resolve()
    output_path = Path(args.output).resolve()

    books = discover_books(content_dir, args.books)
    if not books:
        print(f"No se encontraron libros en {content_dir}")
        return 1

    chapters_by_book = [(book_dir, load_chapters(book_dir, args.debug)) for book_dir in books]
    chapters_by_book = [(book_dir, chapters) for book_dir, chapters in chapters_by_book if chapters]
    if not chapters_by_book:
        print("No se encontraron capítulos procesables.")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = build_text_output(chapters_by_book, speaker_labels=args.speaker_labels)
    output_path.write_text(text, encoding="utf-8")
    print(f"Texto consolidado generado en {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
