"""Text-to-Speech service — edge-tts (free) / OpenAI / ElevenLabs.

Select engine via TTS_ENGINE env var: "edge" (default), "openai", "elevenlabs".
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

# ── Voice maps per engine ────────────────────────────────────────────────────

EDGE_VOICES = {
    "narrator": "en-GB-SoniaNeural",
    "male1":    "en-GB-RyanNeural",
    "female1":  "en-GB-MaisieNeural",
    "female2":  "en-GB-LibbyNeural",
    "male2":    "en-GB-ThomasNeural",
}

_VOICE_STYLES = {
    "narrator": {"rate": "-5%",  "pitch": "+0Hz"},
    "male1":    {"rate": "+3%",  "pitch": "-2Hz"},
    "female1":  {"rate": "+0%",  "pitch": "+1Hz"},
    "female2":  {"rate": "+5%",  "pitch": "+2Hz"},
    "male2":    {"rate": "-3%",  "pitch": "-3Hz"},
}

OPENAI_VOICES = {
    "narrator": "alloy",
    "male1":    "onyx",
    "female1":  "nova",
    "female2":  "shimmer",
    "male2":    "echo",
}

# ElevenLabs voice IDs — these are built-in voices available on all accounts
# You can replace with your own cloned/custom voice IDs
ELEVENLABS_VOICES = {
    "narrator": "EXAVITQu4vr4xnSDxMaL",  # Sarah — calm, clear (narration)
    "male1":    "TX3LPaxmHKxFdv7VOQHJ",   # Liam — young British male
    "female1":  "XB0fDUnXU5powFXDhCwa",    # Charlotte — British female
    "female2":  "Xb7hH8MSUJpSbSDYk0k2",   # Alice — warm, friendly
    "male2":    "iP95p4xoKVk53GoZ742B",    # Chris — mature male
}

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "listening"


def _ensure_dir():
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)


def _get_engine() -> str:
    """Return the TTS engine to use: 'edge', 'openai', or 'elevenlabs'."""
    engine = os.environ.get("TTS_ENGINE", "").strip().lower()
    if engine in ("openai", "elevenlabs", "edge"):
        return engine
    # Legacy env var support — only if TTS_ENGINE is not set at all
    if os.environ.get("OPENAI_TTS", "").lower() in ("1", "true", "yes"):
        return "openai"
    return "edge"


# ── Silence & concat ────────────────────────────────────────────────────────

_SILENCE_BYTES: bytes | None = None


def _get_silence_bytes() -> bytes:
    """Return raw bytes of a short silence MP3 (cached)."""
    global _SILENCE_BYTES
    if _SILENCE_BYTES:
        return _SILENCE_BYTES

    _ensure_dir()
    silence_file = _STATIC_DIR / "_silence.mp3"
    if silence_file.exists() and silence_file.stat().st_size > 100:
        _SILENCE_BYTES = silence_file.read_bytes()
        return _SILENCE_BYTES

    # Try generating silence with edge-tts
    try:
        import edge_tts
        loop = asyncio.new_event_loop()
        ssml = '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-GB"><break time="1500ms"/></speak>'
        communicate = edge_tts.Communicate(ssml, EDGE_VOICES["narrator"])
        loop.run_until_complete(communicate.save(str(silence_file)))
        loop.close()
        _SILENCE_BYTES = silence_file.read_bytes()
        return _SILENCE_BYTES
    except Exception:
        # Fallback: a minimal valid MP3 frame of ~100ms silence
        # This is a single MPEG-1 Layer 3 frame at 128kbps with zero audio
        _SILENCE_BYTES = b'\xff\xfb\x90\x00' + b'\x00' * 413
        return _SILENCE_BYTES


def _concat_mp3_files(file_paths: list[Path], output_path: Path) -> bool:
    """Concatenate MP3 files with silence gaps by appending raw bytes."""
    silence = _get_silence_bytes()
    with open(output_path, "wb") as out:
        for i, fp in enumerate(file_paths):
            if i > 0:
                out.write(silence)
            out.write(fp.read_bytes())
    return output_path.stat().st_size > 0


def _build_ssml(text: str, voice_name: str, role: str) -> str:
    """Wrap text in SSML with prosody for more natural edge-tts delivery."""
    style = _VOICE_STYLES.get(role, {})
    rate = style.get("rate", "+0%")
    pitch = style.get("pitch", "+0Hz")
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-GB">'
        f'<voice name="{voice_name}">'
        f'<prosody rate="{rate}" pitch="{pitch}">{safe}</prosody>'
        f'</voice></speak>'
    )


def _save_tts_input(segments: list[dict], output_path: Path, engine: str) -> None:
    """Save the exact text sent to TTS as a debug file next to the audio."""
    try:
        txt_path = output_path.with_suffix(".tts_input.txt")
        lines = [f"TTS Engine: {engine}\n"]
        for i, seg in enumerate(segments):
            role = seg.get("voice", "narrator")
            text = seg.get("text", "").strip()
            lines.append(f"[{i:03d}] [{role}] {text}")
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        logger.debug("TTS input saved: %s", txt_path)
    except Exception:
        pass


# ── Edge-TTS (free) ─────────────────────────────────────────────────────────

async def _edge_tts_multi(segments: list[dict], output_path: Path):
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
        # Send plain text — edge-tts Communicate() treats first arg as plain text
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(tmp))
        temp_files.append(tmp)
    if not temp_files:
        return False
    try:
        return _concat_mp3_files(temp_files, output_path)
    finally:
        for tmp in temp_files:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


def generate_audio_edge(segments: list[dict], output_path: Path) -> bool:
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
        try:
            return _concat_mp3_files(temp_files, output_path)
        finally:
            for tmp in temp_files:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        logger.exception("OpenAI TTS audio generation failed")
        return False


# ── ElevenLabs TTS ───────────────────────────────────────────────────────────

def _merge_segments(segments: list[dict]) -> list[dict]:
    """Merge consecutive segments that share the same voice into one.

    This reduces the number of API calls (avoids rate-limiting) and produces
    more natural-sounding speech.
    """
    if not segments:
        return []
    merged: list[dict] = []
    for seg in segments:
        role = seg.get("voice", "narrator")
        text = seg.get("text", "").strip()
        if not text:
            continue
        if merged and merged[-1]["voice"] == role:
            merged[-1]["text"] += " " + text
        else:
            merged.append({"voice": role, "text": text})
    return merged


def generate_audio_elevenlabs(segments: list[dict], output_path: Path) -> bool:
    """Generate multi-voice audio using ElevenLabs API. Returns True on success."""
    import time

    try:
        import requests as _requests

        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            logger.error("ELEVENLABS_API_KEY not set")
            return False

        model_id = os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")

        # Merge consecutive same-voice segments to reduce API calls
        merged = _merge_segments(segments)
        logger.info("ElevenLabs: %d raw segments → %d merged chunks", len(segments), len(merged))

        _ensure_dir()
        temp_files = []
        errors = 0
        for i, seg in enumerate(merged):
            role = seg["voice"]
            voice_id = ELEVENLABS_VOICES.get(role, ELEVENLABS_VOICES["narrator"])
            text = seg["text"]

            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }
            payload = {
                "text": text[:5000],
                "model_id": model_id,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.4,
                    "use_speaker_boost": True,
                },
            }

            # Respect rate limits — pause between requests
            if i > 0:
                time.sleep(1.0)

            resp = _requests.post(url, json=payload, headers=headers, timeout=120)
            if resp.status_code != 200:
                errors += 1
                logger.error(
                    "ElevenLabs API error on chunk %d/%d (voice=%s, %d chars): HTTP %d — %s",
                    i + 1, len(merged), role, len(text), resp.status_code, resp.text[:500],
                )
                # On rate limit (429), wait longer and retry once
                if resp.status_code == 429:
                    wait = 5.0
                    logger.info("Rate limited — waiting %.0fs and retrying chunk %d", wait, i + 1)
                    time.sleep(wait)
                    resp = _requests.post(url, json=payload, headers=headers, timeout=120)
                    if resp.status_code == 200:
                        errors -= 1  # recovered
                    else:
                        logger.error("Retry failed for chunk %d: HTTP %d", i + 1, resp.status_code)
                        continue
                else:
                    continue

            tmp = output_path.parent / f"_tmp_el_{output_path.stem}_{i}.mp3"
            tmp.write_bytes(resp.content)
            temp_files.append(tmp)

        logger.info("ElevenLabs: %d/%d chunks succeeded", len(temp_files), len(merged))
        if not temp_files:
            return False
        try:
            return _concat_mp3_files(temp_files, output_path)
        finally:
            for tmp in temp_files:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        logger.exception("ElevenLabs TTS audio generation failed")
        return False


# ── Public API ───────────────────────────────────────────────────────────────

def generate_listening_audio(segments: list[dict], filename: str) -> str | None:
    """Generate listening audio from segments. Returns relative URL path or None.

    Each segment: {"voice": "narrator"|"male1"|"female1"|..., "text": "..."}
    Engine selected via TTS_ENGINE env var: "edge" (default), "openai", "elevenlabs".
    """
    _ensure_dir()
    safe_name = re.sub(r'[^\w\-.]', '_', filename)
    if not safe_name.endswith('.mp3'):
        safe_name += '.mp3'
    output_path = _STATIC_DIR / safe_name

    engine = _get_engine()
    logger.info("TTS engine: %s, segments: %d, file: %s", engine, len(segments), safe_name)

    # Save the exact text being sent to TTS for debugging
    _save_tts_input(segments, output_path, engine)

    if engine == "elevenlabs":
        ok = generate_audio_elevenlabs(segments, output_path)
    elif engine == "openai":
        ok = generate_audio_openai(segments, output_path)
    else:
        ok = generate_audio_edge(segments, output_path)

    if ok and output_path.exists():
        return f"/listening/{safe_name}"
    return None
