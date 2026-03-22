"""Text-to-Speech service — edge-tts (free, default) + OpenAI TTS (optional).

Generates MP3 audio for listening exercises with multi-voice support.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("fce_trainer")

# Edge-TTS British English voices
EDGE_VOICES = {
    "narrator": "en-GB-SoniaNeural",   # Female narrator / exam instructions
    "male1":    "en-GB-RyanNeural",     # Male speaker
    "female1":  "en-GB-SoniaNeural",    # Female speaker 1
    "female2":  "en-GB-LibbyNeural",    # Female speaker 2
    "male2":    "en-GB-ThomasNeural",   # Male speaker 2
}

# OpenAI TTS voices
OPENAI_VOICES = {
    "narrator": "alloy",
    "male1":    "onyx",
    "female1":  "nova",
    "female2":  "shimmer",
    "male2":    "echo",
}

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "listening"


def _ensure_dir():
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)


def _use_openai_tts() -> bool:
    return os.environ.get("OPENAI_TTS", "").lower() in ("1", "true", "yes")


# ── Edge-TTS (free) ─────────────────────────────────────────────────────────

async def _edge_tts_segment(text: str, voice: str, output_path: Path):
    """Generate a single audio segment with edge-tts."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))


async def _edge_tts_multi(segments: list[dict], output_path: Path):
    """Generate multi-voice audio: list of {voice, text} dicts → single MP3."""
    import edge_tts
    _ensure_dir()
    temp_files = []

    for i, seg in enumerate(segments):
        voice = EDGE_VOICES.get(seg.get("voice", "narrator"), EDGE_VOICES["narrator"])
        text = seg.get("text", "").strip()
        if not text:
            continue

        tmp = output_path.parent / f"_tmp_seg_{output_path.stem}_{i}.mp3"
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(tmp))
        temp_files.append(tmp)

    if not temp_files:
        return False

    # Concatenate segments with pydub
    try:
        from pydub import AudioSegment
        combined = AudioSegment.empty()
        # 1.5s silence between segments
        silence = AudioSegment.silent(duration=1500)
        for j, tmp in enumerate(temp_files):
            seg_audio = AudioSegment.from_file(str(tmp), format="mp3")
            if j > 0:
                combined += silence
            combined += seg_audio
        combined.export(str(output_path), format="mp3")
    finally:
        for tmp in temp_files:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    return True


def generate_audio_edge(segments: list[dict], output_path: Path) -> bool:
    """Generate multi-voice audio using edge-tts. Returns True on success."""
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_edge_tts_multi(segments, output_path))
        loop.close()
        return result
    except Exception:
        logger.exception("edge-tts audio generation failed")
        return False


# ── OpenAI TTS ───────────────────────────────────────────────────────────────

def generate_audio_openai(segments: list[dict], output_path: Path) -> bool:
    """Generate multi-voice audio using OpenAI TTS. Returns True on success."""
    try:
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return False
        client = OpenAI(api_key=api_key)
        model = os.environ.get("OPENAI_TTS_MODEL", "tts-1-hd")

        from pydub import AudioSegment
        combined = AudioSegment.empty()
        silence = AudioSegment.silent(duration=1500)

        _ensure_dir()
        for i, seg in enumerate(segments):
            voice = OPENAI_VOICES.get(seg.get("voice", "narrator"), OPENAI_VOICES["narrator"])
            text = seg.get("text", "").strip()
            if not text:
                continue
            tmp = output_path.parent / f"_tmp_oai_{output_path.stem}_{i}.mp3"
            with client.audio.speech.with_streaming_response.create(
                model=model, voice=voice, input=text[:4096],
            ) as response:
                response.stream_to_file(str(tmp))
            seg_audio = AudioSegment.from_file(str(tmp), format="mp3")
            if i > 0:
                combined += silence
            combined += seg_audio
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

        if len(combined) == 0:
            return False
        combined.export(str(output_path), format="mp3")
        return True
    except Exception:
        logger.exception("OpenAI TTS audio generation failed")
        return False


# ── Public API ───────────────────────────────────────────────────────────────

def generate_listening_audio(segments: list[dict], filename: str) -> str | None:
    """Generate listening audio from segments. Returns relative URL path or None.

    Each segment: {"voice": "narrator"|"male1"|"female1"|..., "text": "..."}
    """
    _ensure_dir()
    # Sanitise filename
    safe_name = re.sub(r'[^\w\-.]', '_', filename)
    if not safe_name.endswith('.mp3'):
        safe_name += '.mp3'
    output_path = _STATIC_DIR / safe_name

    if _use_openai_tts():
        ok = generate_audio_openai(segments, output_path)
    else:
        ok = generate_audio_edge(segments, output_path)

    if ok and output_path.exists():
        return f"/listening/{safe_name}"
    return None
