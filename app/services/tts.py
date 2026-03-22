"""Text-to-Speech service — edge-tts (free, default) + OpenAI TTS (optional).

Generates MP3 audio for listening exercises with multi-voice support.
Uses raw MP3 byte concatenation (no pydub/audioop dependency).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("fce_trainer")

# Edge-TTS British English voices — use multilingual voices where possible
# for more natural-sounding speech
EDGE_VOICES = {
    "narrator": "en-GB-SoniaNeural",        # Female narrator / exam instructions
    "male1":    "en-GB-RyanNeural",          # Male speaker
    "female1":  "en-GB-MaisieNeural",        # Female speaker 1 (younger, natural)
    "female2":  "en-GB-LibbyNeural",         # Female speaker 2
    "male2":    "en-GB-ThomasNeural",        # Male speaker 2
}

# SSML prosody settings per voice role — makes speech less robotic
_VOICE_STYLES = {
    "narrator": {"rate": "-5%",  "pitch": "+0Hz"},    # calm, measured
    "male1":    {"rate": "+3%",  "pitch": "-2Hz"},     # slightly faster, natural
    "female1":  {"rate": "+0%",  "pitch": "+1Hz"},     # default, slight lilt
    "female2":  {"rate": "+5%",  "pitch": "+2Hz"},     # a bit more animated
    "male2":    {"rate": "-3%",  "pitch": "-3Hz"},     # slower, deeper
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
_SILENCE_PATH: Path | None = None  # cached silence MP3


def _ensure_dir():
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)


def _use_openai_tts() -> bool:
    return os.environ.get("OPENAI_TTS", "").lower() in ("1", "true", "yes")


# ── Silence generation (no pydub) ───────────────────────────────────────────

async def _generate_silence_edge(duration_ms: int = 1500) -> Path:
    """Generate a short silence MP3 using edge-tts SSML <break> tag."""
    import edge_tts
    _ensure_dir()
    silence_file = _STATIC_DIR / "_silence.mp3"
    if silence_file.exists() and silence_file.stat().st_size > 0:
        return silence_file
    ssml = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-GB"><break time="{duration_ms}ms"/></speak>'
    communicate = edge_tts.Communicate(ssml, EDGE_VOICES["narrator"])
    await communicate.save(str(silence_file))
    return silence_file


def _concat_mp3_files(file_paths: list[Path], output_path: Path, silence_path: Path | None = None) -> bool:
    """Concatenate MP3 files by appending raw bytes (MP3 is frame-based)."""
    with open(output_path, "wb") as out:
        for i, fp in enumerate(file_paths):
            if i > 0 and silence_path and silence_path.exists():
                out.write(silence_path.read_bytes())
            out.write(fp.read_bytes())
    return output_path.stat().st_size > 0


def _build_ssml(text: str, voice_name: str, role: str) -> str:
    """Wrap text in SSML with prosody for more natural delivery."""
    style = _VOICE_STYLES.get(role, {})
    rate = style.get("rate", "+0%")
    pitch = style.get("pitch", "+0Hz")
    # Escape XML entities in the text
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-GB">'
        f'<voice name="{voice_name}">'
        f'<prosody rate="{rate}" pitch="{pitch}">'
        f'{safe}'
        f'</prosody></voice></speak>'
    )


# ── Edge-TTS (free) ─────────────────────────────────────────────────────────

async def _edge_tts_multi(segments: list[dict], output_path: Path):
    """Generate multi-voice audio: list of {voice, text} dicts → single MP3."""
    import edge_tts
    _ensure_dir()
    temp_files = []

    for i, seg in enumerate(segments):
        role = seg.get("voice", "narrator")
        voice = EDGE_VOICES.get(role, EDGE_VOICES["narrator"])
        text = seg.get("text", "").strip()
        if not text:
            continue

        tmp = output_path.parent / f"_tmp_seg_{output_path.stem}_{i}.mp3"
        ssml = _build_ssml(text, voice, role)
        communicate = edge_tts.Communicate(ssml, voice)
        await communicate.save(str(tmp))
        temp_files.append(tmp)

    if not temp_files:
        return False

    # Generate silence segment for gaps between speakers
    silence_path = await _generate_silence_edge(1500)

    try:
        return _concat_mp3_files(temp_files, output_path, silence_path)
    finally:
        for tmp in temp_files:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


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

        _ensure_dir()
        temp_files = []
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
            temp_files.append(tmp)

        if not temp_files:
            return False

        # Generate a tiny silence via edge-tts if available, else just concat without gaps
        silence_path = None
        try:
            loop = asyncio.new_event_loop()
            silence_path = loop.run_until_complete(_generate_silence_edge(1500))
            loop.close()
        except Exception:
            pass  # edge-tts not available — concat without silence

        try:
            return _concat_mp3_files(temp_files, output_path, silence_path)
        finally:
            for tmp in temp_files:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
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
