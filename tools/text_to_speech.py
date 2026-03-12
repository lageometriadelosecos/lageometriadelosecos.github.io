#!/usr/bin/env python3
"""Genera un audio a partir de un fichero de texto consolidado."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default=str(root / "tools" / "audiolibro_completo.txt"),
        help="Fichero de texto de entrada, normalmente generado por generar_libro.py.",
    )
    parser.add_argument(
        "--output",
        default=str(root / "tools" / "audiolibro" / "audiolibro_completo.mp3"),
        help="Fichero MP3 de salida.",
    )
    parser.add_argument(
        "--lang",
        default="es",
        help="Idioma de síntesis para gTTS.",
    )
    parser.add_argument(
        "--slow",
        action="store_true",
        help="Genera el audio a velocidad lenta.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()

    if not input_path.exists():
        print(f"No existe el fichero de entrada: {input_path}")
        return 1

    text = input_path.read_text(encoding="utf-8").strip()
    if not text:
        print(f"El fichero de entrada está vacío: {input_path}")
        return 1

    from gtts import gTTS

    formatted_text = text.replace("\n", " ")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tts = gTTS(text=formatted_text, lang=args.lang, slow=args.slow)
    tts.save(str(output_path))
    print(f"Audio generado en {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
