#!/usr/bin/env python3
"""
Generate FCE listening-style audio from text using OpenAI Text-to-Speech.

Usage:
  # From a text file (e.g. your listening script):
  python generate_listening_audio.py script.txt -o listening_part1.mp3

  # From stdin:
  cat script.txt | python generate_listening_audio.py - -o output.mp3

  # Short text as argument (first non-option arg):
  python generate_listening_audio.py "Your text here." -o out.mp3

Requires OPENAI_API_KEY in .env or environment.
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Default voice: clear, neutral British-style for exam listening (try "onyx" or "echo" for male, "nova" or "shimmer" for female)
DEFAULT_VOICE = "onyx"
# tts-1 = faster/cheaper, tts-1-hd = higher quality
DEFAULT_MODEL = "tts-1-hd"


def get_text(input_source: str) -> str:
    if input_source == "-":
        return sys.stdin.read()
    p = Path(input_source)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return input_source


def main():
    parser = argparse.ArgumentParser(description="Generate listening audio from text (OpenAI TTS)")
    parser.add_argument("input", nargs="?", default="-", help="Text file path, or '-' for stdin, or the text itself")
    parser.add_argument("-o", "--output", required=True, help="Output audio file (e.g. listening.mp3)")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help=f"Voice: alloy, echo, fable, onyx, nova, shimmer (default: {DEFAULT_VOICE})")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model: tts-1 or tts-1-hd (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    text = get_text(args.input).strip()
    if not text:
        print("No text to convert.", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY in .env or environment.", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    client = OpenAI(api_key=api_key)
    max_chars = 4096  # OpenAI TTS limit per request
    try:
        if len(text) <= max_chars:
            with client.audio.speech.with_streaming_response.create(
                model=args.model,
                voice=args.voice,
                input=text,
            ) as response:
                response.stream_to_file(out_path)
            print(f"Saved: {out_path.resolve()}")
        else:
            # Split at sentence boundaries and generate one segment per chunk, then concatenate
            chunks = []
            rest = text
            while rest:
                if len(rest) <= max_chars:
                    chunk = rest
                elif ". " in rest[:max_chars]:
                    chunk = rest[:max_chars].rsplit(". ", 1)[0] + ". "
                else:
                    chunk = rest[:max_chars]
                chunks.append(chunk.strip())
                rest = rest[len(chunk):].strip()
            print(f"Long text: generating {len(chunks)} segment(s)...", file=sys.stderr)
            temp_files = []
            for i, chunk in enumerate(chunks):
                seg_path = out_path.parent / f"{out_path.stem}_part{i+1}{out_path.suffix}"
                with client.audio.speech.with_streaming_response.create(
                    model=args.model,
                    voice=args.voice,
                    input=chunk,
                ) as response:
                    response.stream_to_file(seg_path)
                temp_files.append(seg_path)
            # Concatenate with ffmpeg if available, else leave parts and tell user
            try:
                import subprocess
                list_path = out_path.parent / "_concat_list.txt"
                list_path.write_text("\n".join(f"file '{f.absolute()}'" for f in temp_files), encoding="utf-8")
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(out_path)],
                    check=True,
                    capture_output=True,
                )
                list_path.unlink(missing_ok=True)
                for f in temp_files:
                    f.unlink(missing_ok=True)
                print(f"Saved: {out_path.resolve()}")
            except (FileNotFoundError, subprocess.CalledProcessError):
                print(f"Generated {len(temp_files)} files (merge with ffmpeg or Audacity):", [str(f) for f in temp_files], file=sys.stderr)
                print("Install ffmpeg to get a single merged file automatically.", file=sys.stderr)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
