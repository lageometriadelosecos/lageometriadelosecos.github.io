#!/usr/bin/env python3
"""Genera un audiolibro por bloques con limpieza de markdown y marcado de dialogos."""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default=str(root / "tools" / "audiolibro_completo.txt"),
        help="Fichero de entrada (.txt o .md).",
    )
    parser.add_argument(
        "--output",
        default=str(root / "tools" / "audiolibro" / "audiolibro_completo.mp3"),
        help="Fichero MP3 de salida.",
    )
    parser.add_argument("--lang", default="es", help="Idioma para gTTS.")
    parser.add_argument("--slow", action="store_true", help="Velocidad lenta.")
    parser.add_argument(
        "--provider",
        choices=("edge", "gtts"),
        default="edge",
        help="Motor de sintesis a usar.",
    )
    parser.add_argument(
        "--voice",
        default="es-ES-AlvaroNeural",
        help="Voz para edge-tts.",
    )
    parser.add_argument(
        "--rate",
        default="-2%",
        help="Velocidad para edge-tts (ej: -5%%, +0%%, +10%%).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=2200,
        help="Tamano maximo por bloque para la sintesis.",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=4,
        help="Reintentos por bloque en caso de error de red/API.",
    )
    parser.add_argument(
        "--sleep-between",
        type=float,
        default=0.8,
        help="Pausa entre bloques para evitar limite de peticiones.",
    )
    parser.add_argument(
        "--edge-timeout",
        type=float,
        default=45.0,
        help="Timeout por bloque (segundos) para edge-tts.",
    )
    return parser.parse_args()


def _cleanup_line(line: str) -> tuple[str, bool]:
    dialogue = False
    s = line.strip()
    if not s:
        return "", dialogue

    # Markdown basico
    s = re.sub(r"^#{1,6}\s*", "", s)
    if re.fullmatch(r"[-*_]{3,}", s):
        return "", dialogue
    s = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^\s*[-*+]\s+", "", s)
    s = s.replace("`", "").replace("*", "")
    # Evita una pronunciacion rara de la secuencia literal "El niño" en el TTS.
    s = re.sub(r'\bEl niño\b', "La figura del niño", s)
    s = re.sub(r'\bel niño\b', "la figura del niño", s)
    # Ajustes foneticos puntuales para nombres propios.
    s = re.sub(r'\bAlice\b', "Álizz", s)
    s = re.sub(r'\balice\b', "álizz", s)

    # Deteccion de dialogo de novela
    if s.startswith("—"):
        dialogue = True
        s = s.lstrip("—").strip()
    elif re.match(r'^[\"“].+[\"”]$', s):
        dialogue = True

    # Quitar guiones para que no se locuten como simbolo
    s = s.replace("—", ", ")
    s = re.sub(r"\s-\s", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s, dialogue


def preprocess_text(raw: str) -> str:
    out_lines: list[str] = []
    for line in raw.splitlines():
        clean, is_dialogue = _cleanup_line(line)
        if not clean:
            out_lines.append("")
            continue
        if is_dialogue:
            clean = f"Dialogo. {clean}"
        if clean[-1] not in ".!?":
            clean += "."
        out_lines.append(clean)

    # Compacta saltos repetidos y mantiene parrafos para pausas
    normalized = "\n".join(out_lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized


def split_into_chunks(text: str, chunk_size: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for p in paragraphs:
        candidate = p if not current else f"{current}\n\n{p}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(p) <= chunk_size:
            current = p
            continue
        sentences = re.split(r"(?<=[.!?])\s+", p)
        sentence_block = ""
        for sentence in sentences:
            test = sentence if not sentence_block else f"{sentence_block} {sentence}"
            if len(test) <= chunk_size:
                sentence_block = test
            else:
                if sentence_block:
                    chunks.append(sentence_block)
                sentence_block = sentence
        if sentence_block:
            chunks.append(sentence_block)
    if current:
        chunks.append(current)
    return chunks


def synthesize_chunks_gtts(
    chunks: list[str],
    lang: str,
    slow: bool,
    retries: int,
    sleep_between: float,
    tmpdir: Path,
) -> list[Path]:
    from gtts import gTTS

    mp3_paths: list[Path] = []
    for i, chunk in enumerate(chunks, start=1):
        chunk_path = tmpdir / f"chunk_{i:04d}.mp3"
        error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                gTTS(text=chunk, lang=lang, slow=slow).save(str(chunk_path))
                error = None
                break
            except Exception as exc:  # noqa: BLE001
                error = exc
                backoff = min(8.0, 1.3 * attempt)
                time.sleep(backoff)
        if error is not None:
            raise error
        mp3_paths.append(chunk_path)
        time.sleep(max(0.0, sleep_between))
    return mp3_paths


def synthesize_chunks_edge(
    chunks: list[str],
    voice: str,
    rate: str,
    retries: int,
    sleep_between: float,
    timeout: float,
    tmpdir: Path,
) -> list[Path]:
    import asyncio
    import edge_tts

    async def _save(chunk_text: str, chunk_file: Path) -> None:
        communicate = edge_tts.Communicate(text=chunk_text, voice=voice, rate=rate)
        await communicate.save(str(chunk_file))

    mp3_paths: list[Path] = []
    for i, chunk in enumerate(chunks, start=1):
        chunk_path = tmpdir / f"chunk_{i:04d}.mp3"
        error: Exception | None = None
        print(f"Sintetizando bloque {i}/{len(chunks)} con edge-tts...")
        for attempt in range(1, retries + 1):
            try:
                asyncio.run(asyncio.wait_for(_save(chunk, chunk_path), timeout=timeout))
                error = None
                break
            except Exception as exc:  # noqa: BLE001
                error = exc
                backoff = min(8.0, 1.3 * attempt)
                time.sleep(backoff)
        if error is not None:
            raise error
        mp3_paths.append(chunk_path)
        time.sleep(max(0.0, sleep_between))
    return mp3_paths


def concat_mp3(mp3_paths: list[Path], output_path: Path, tmpdir: Path) -> None:
    list_file = tmpdir / "concat.txt"
    lines = [f"file '{p.as_posix()}'" for p in mp3_paths]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()

    if not input_path.exists():
        print(f"No existe el fichero de entrada: {input_path}")
        return 1

    raw = input_path.read_text(encoding="utf-8")
    if not raw.strip():
        print(f"El fichero de entrada esta vacio: {input_path}")
        return 1

    preprocessed = preprocess_text(raw)
    chunks = split_into_chunks(preprocessed, args.chunk_size)
    if not chunks:
        print("No se pudo generar contenido para sintetizar.")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tts_chunks_") as tmp:
        tmpdir = Path(tmp)
        if args.provider == "edge":
            mp3_paths = synthesize_chunks_edge(
                chunks=chunks,
                voice=args.voice,
                rate=args.rate,
                retries=args.retry,
                sleep_between=args.sleep_between,
                timeout=args.edge_timeout,
                tmpdir=tmpdir,
            )
        else:
            mp3_paths = synthesize_chunks_gtts(
                chunks=chunks,
                lang=args.lang,
                slow=args.slow,
                retries=args.retry,
                sleep_between=args.sleep_between,
                tmpdir=tmpdir,
            )
        concat_mp3(mp3_paths, output_path, tmpdir)

    print(f"Audio generado en {output_path} ({len(chunks)} bloques, provider={args.provider})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
