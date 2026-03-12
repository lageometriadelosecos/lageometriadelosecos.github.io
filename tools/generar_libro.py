#!/usr/bin/env python3
"""Herramienta unificada para generar audiolibros desde `website/content`."""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BOOKS = [
    "libro1-viernes-interior",
    "libro2-codigos-rotos",
    "libro3-aquarium",
    "libro4-pandemonium",
    "libro5-aventuras-de-kirlian",
]

VOICE_CONFIG = {
    "languageCode": "es-ES",
    "name": "es-ES-Chirp3-HD-Fenrir",
}

AUDIO_CONFIG = {
    "audioEncoding": "MP3",
    "sampleRateHertz": 24000,
}

REQUEST_TIMEOUT = 90
MAX_SYNTHESIS_RETRIES = 3
RETRY_SLEEP_BASE = 5
INTER_CHUNK_SLEEP = 1.0
MAX_TEXT_CHUNK_SIZE = 4800

TOKEN_CACHE = {"token": None, "expiry": 0.0}


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
        "--output-dir",
        default=str(root / "tools" / "audiolibro"),
        help="Directorio donde se guardará el audio generado.",
    )
    parser.add_argument(
        "--text-output",
        default=str(root / "tools" / "audiolibro_completo.txt"),
        help="Ruta del texto consolidado para el audiolibro.",
    )
    parser.add_argument(
        "--credentials",
        default=str(root / "tools" / "credenciales.json"),
        help="Archivo JSON de credenciales de Google Cloud.",
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("GCLOUD_PROJECT_ID", "heroic-bird-459121-h1"),
        help="ID del proyecto de Google Cloud.",
    )
    parser.add_argument(
        "--book",
        action="append",
        dest="books",
        help="Libro a procesar. Se puede repetir. Por defecto se procesan todos los libros conocidos.",
    )
    parser.add_argument(
        "--mode",
        choices=["text", "audio", "all"],
        default="all",
        help="`text` genera solo el TXT, `audio` solo el audio, `all` hace ambas cosas.",
    )
    parser.add_argument(
        "--full-book",
        action="store_true",
        help="Además de los capítulos sueltos, genera un MP3 por libro.",
    )
    parser.add_argument(
        "--full-collection",
        action="store_true",
        help="Genera un MP3 con toda la colección procesada.",
    )
    parser.add_argument(
        "--speaker-labels",
        action="store_true",
        help="Añade etiquetas [Narrador]/[Personaje] al texto consolidado.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Activa trazas detalladas.",
    )
    return parser.parse_args()


def debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"DEBUG: {message}")


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\s.-]", "", name, flags=re.ASCII)
    name = re.sub(r"[-\s]+", "_", name).strip("_")
    return name or "sin_titulo"


def discover_books(content_dir: Path, selected_books: list[str] | None) -> list[Path]:
    if selected_books:
        books = [content_dir / slug for slug in selected_books]
    else:
        books = [content_dir / slug for slug in DEFAULT_BOOKS if (content_dir / slug).exists()]
        if not books:
            books = sorted(
                path for path in content_dir.glob("libro*") if path.is_dir()
            )
    return books


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
            chapters.append(
                Chapter(
                    book_slug=book_dir.name,
                    title=title,
                    source_path=chapter_path,
                    text=text,
                )
            )
            debug(debug_enabled, f"Cargado {chapter_path} ({len(text)} chars)")
    return chapters


def label_text(text: str) -> str:
    labeled_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("—"):
            labeled_lines.append(f"[Personaje]: {stripped}")
        elif stripped.startswith(">"):
            labeled_lines.append(f"[Reflexión]: {stripped}")
        else:
            labeled_lines.append(f"[Narrador]: {stripped}")
    return "\n".join(labeled_lines)


def build_text_output(chapters_by_book: list[tuple[Path, list[Chapter]]], speaker_labels: bool) -> str:
    blocks = ["Geometría de los Ecos", "La historia de Kirlian"]
    for index, (book_dir, chapters) in enumerate(chapters_by_book, start=1):
        blocks.append("")
        blocks.append("=" * 60)
        blocks.append(f"LIBRO {index}: {book_dir.name}")
        blocks.append("=" * 60)
        for chapter in chapters:
            blocks.append("")
            blocks.append(chapter.title)
            blocks.append("")
            blocks.append(label_text(chapter.text) if speaker_labels else chapter.text)
    return "\n".join(blocks).strip() + "\n"


def split_long_sentences(text: str, max_sentence_length: int = 500) -> str:
    sentences = re.split(r"([.!?]+\s+)", text)
    rebuilt: list[str] = []
    for idx in range(0, len(sentences), 2):
        sentence = sentences[idx]
        punctuation = sentences[idx + 1] if idx + 1 < len(sentences) else ""
        if len(sentence) <= max_sentence_length:
            rebuilt.append(sentence + punctuation)
            continue
        parts = re.split(r"([,;:]+\s+)", sentence)
        current = ""
        for part_idx in range(0, len(parts), 2):
            chunk = parts[part_idx]
            separator = parts[part_idx + 1] if part_idx + 1 < len(parts) else ""
            if current and len(current) + len(chunk) > max_sentence_length:
                rebuilt.append(current.strip() + ". ")
                current = chunk + separator
            else:
                current += chunk + separator
        if current:
            rebuilt.append(current + punctuation)
    return "".join(rebuilt)


def split_text(text: str, max_length: int, debug_enabled: bool) -> list[str]:
    text = split_long_sentences(text)
    chunks: list[str] = []
    current = ""

    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            if current.strip():
                current += "\n"
            continue

        separator = "\n" if current and not current.endswith("\n") else ""
        if len(current) + len(separator) + len(paragraph) <= max_length:
            current += separator + paragraph
            continue

        if current.strip():
            chunks.append(current.strip())
        current = paragraph

        while len(current) > max_length:
            slice_text = current[:max_length]
            split_point = -1
            for sep in [". ", "! ", "? ", "; ", ": ", ", ", " - ", " — ", " "]:
                idx = slice_text.rfind(sep)
                if idx > max_length * 0.3:
                    split_point = idx + len(sep)
                    break
            if split_point == -1:
                split_point = max_length
            chunks.append(current[:split_point].strip())
            current = current[split_point:].lstrip()

    if current.strip():
        chunks.append(current.strip())

    debug(debug_enabled, f"Texto dividido en {len(chunks)} fragmentos")
    return chunks


def get_access_token(credentials_file: Path, debug_enabled: bool) -> str:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account

    now = time.time()
    if TOKEN_CACHE["token"] and now < TOKEN_CACHE["expiry"] - 120:
        return TOKEN_CACHE["token"]

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials = service_account.Credentials.from_service_account_file(
        str(credentials_file),
        scopes=scopes,
    )
    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest())

    TOKEN_CACHE["token"] = credentials.token
    TOKEN_CACHE["expiry"] = credentials.expiry.timestamp() if credentials.expiry else now + 3500
    debug(debug_enabled, "Token de Google Cloud actualizado")
    return TOKEN_CACHE["token"]


def synthesize_text_chunk(
    text_chunk: str,
    project_id: str,
    credentials_file: Path,
    debug_enabled: bool,
    chunk_label: str,
) -> bytes | None:
    import requests

    url = "https://texttospeech.googleapis.com/v1/text:synthesize"
    for attempt in range(MAX_SYNTHESIS_RETRIES):
        try:
            token = get_access_token(credentials_file, debug_enabled)
            headers = {
                "Content-Type": "application/json",
                "X-Goog-User-Project": project_id,
                "Authorization": f"Bearer {token}",
            }
            payload = {
                "input": {"text": text_chunk},
                "voice": VOICE_CONFIG,
                "audioConfig": AUDIO_CONFIG,
            }
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            if "audioContent" in data:
                return base64.b64decode(data["audioContent"])
            print(f"Respuesta sin audioContent en {chunk_label}: {data}")
            return None
        except requests.exceptions.HTTPError as exc:
            body = exc.response.text if exc.response is not None else ""
            print(f"HTTP error en {chunk_label}: {exc}")
            if "exceeds limit" in body or "Input text not set" in body:
                return None
            if exc.response is None or exc.response.status_code not in {401, 403, 429, 500, 502, 503, 504}:
                return None
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            print(f"Error de conexión en {chunk_label}: {exc}")
        except Exception as exc:
            print(f"Error inesperado en {chunk_label}: {exc}")
            traceback.print_exc()
            return None

        if attempt < MAX_SYNTHESIS_RETRIES - 1:
            wait_time = RETRY_SLEEP_BASE * (2**attempt)
            time.sleep(wait_time)
    return None


def export_combined_audio(audio_files: list[Path], destination: Path) -> None:
    from pydub import AudioSegment

    combined = AudioSegment.empty()
    for audio_file in audio_files:
        combined += AudioSegment.from_file(audio_file, format="mp3")
    destination.parent.mkdir(parents=True, exist_ok=True)
    combined.export(destination, format="mp3")


def synthesize_chapters(
    chapters_by_book: list[tuple[Path, list[Chapter]]],
    output_dir: Path,
    credentials_file: Path,
    project_id: str,
    full_book: bool,
    full_collection: bool,
    debug_enabled: bool,
) -> None:
    collection_audio: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for book_dir, chapters in chapters_by_book:
        book_output_dir = output_dir / book_dir.name
        book_output_dir.mkdir(parents=True, exist_ok=True)
        book_audio: list[Path] = []

        for chapter_index, chapter in enumerate(chapters, start=1):
            chapter_stem = f"{chapter_index:02d}_{sanitize_filename(chapter.title)}"
            chapter_file = book_output_dir / f"{chapter_stem}.mp3"
            chapter_chunks_dir = book_output_dir / chapter_stem
            if chapter_file.exists() and chapter_file.stat().st_size > 100:
                print(f"INFO: capítulo ya existente, se omite: {chapter_file}")
                book_audio.append(chapter_file)
                continue

            chapter_chunks_dir.mkdir(parents=True, exist_ok=True)
            chunks = split_text(chapter.text, MAX_TEXT_CHUNK_SIZE, debug_enabled)
            chunk_files: list[Path] = []

            for chunk_index, chunk in enumerate(chunks, start=1):
                chunk_file = chapter_chunks_dir / f"chunk_{chunk_index:03d}.mp3"
                if chunk_file.exists() and chunk_file.stat().st_size > 100:
                    chunk_files.append(chunk_file)
                    continue
                audio_data = synthesize_text_chunk(
                    chunk,
                    project_id=project_id,
                    credentials_file=credentials_file,
                    debug_enabled=debug_enabled,
                    chunk_label=f"{chapter.title} chunk {chunk_index}",
                )
                if audio_data is None:
                    failed_file = chapter_chunks_dir / f"failed_chunk_{chunk_index:03d}.txt"
                    failed_file.write_text(chunk, encoding="utf-8")
                    print(f"FALLO: no se pudo sintetizar {chapter.title} chunk {chunk_index}")
                    continue
                chunk_file.write_bytes(audio_data)
                chunk_files.append(chunk_file)
                time.sleep(INTER_CHUNK_SLEEP)

            valid_chunk_files = [path for path in chunk_files if path.exists() and path.stat().st_size > 100]
            if not valid_chunk_files:
                print(f"ADVERTENCIA: no se generó audio válido para {chapter.title}")
                continue

            export_combined_audio(valid_chunk_files, chapter_file)
            print(f"ÉXITO: capítulo exportado a {chapter_file}")
            book_audio.append(chapter_file)

        collection_audio.extend(book_audio)
        if full_book and book_audio:
            destination = output_dir / f"{book_dir.name}.mp3"
            export_combined_audio(book_audio, destination)
            print(f"ÉXITO: libro completo exportado a {destination}")

    if full_collection and collection_audio:
        destination = output_dir / "coleccion_completa.mp3"
        export_combined_audio(collection_audio, destination)
        print(f"ÉXITO: colección completa exportada a {destination}")


def main() -> int:
    args = parse_args()
    content_dir = Path(args.content_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    text_output = Path(args.text_output).resolve()
    credentials_file = Path(args.credentials).resolve()

    books = discover_books(content_dir, args.books)
    if not books:
        print(f"No se encontraron libros en {content_dir}")
        return 1

    chapters_by_book = [(book_dir, load_chapters(book_dir, args.debug)) for book_dir in books]
    chapters_by_book = [(book_dir, chapters) for book_dir, chapters in chapters_by_book if chapters]
    if not chapters_by_book:
        print("No se encontraron capítulos procesables.")
        return 1

    if args.mode in {"text", "all"}:
        text_output.parent.mkdir(parents=True, exist_ok=True)
        text = build_text_output(chapters_by_book, speaker_labels=args.speaker_labels)
        text_output.write_text(text, encoding="utf-8")
        print(f"Texto consolidado generado en {text_output}")

    if args.mode in {"audio", "all"}:
        if not credentials_file.exists():
            print(f"No existe el archivo de credenciales: {credentials_file}")
            return 1
        if not args.project_id:
            print("Debes indicar --project-id o definir GCLOUD_PROJECT_ID")
            return 1
        synthesize_chapters(
            chapters_by_book=chapters_by_book,
            output_dir=output_dir,
            credentials_file=credentials_file,
            project_id=args.project_id,
            full_book=args.full_book,
            full_collection=args.full_collection,
            debug_enabled=args.debug,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
