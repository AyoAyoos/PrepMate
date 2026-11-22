"""Local text-to-speech using Piper.

Used only by the offline fallback pipeline. Piper is a small local neural TTS
engine; voices are ONNX files downloaded once during setup.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from loguru import logger
from pipecat.frames.frames import Frame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService


# Voices are immutable ONNX files, so share one loaded voice per path across
# calls. Loading a voice takes several seconds; caching keeps that cost off the
# first-call critical path and avoids repeated memory allocation.
_VOICE_CACHE: dict[str, Any] = {}


def _shared_voice(path: Path) -> Any:
    key = str(path)
    voice = _VOICE_CACHE.get(key)
    if voice is None:
        from piper import PiperVoice

        voice = PiperVoice.load(key)
        _VOICE_CACHE[key] = voice
    return voice


def _resolve_voice_path(voice: str, models_dir: Path) -> Path:
    """Resolve a Piper voice name or path to its .onnx model file."""
    candidate = Path(voice).expanduser()
    if candidate.suffix == ".onnx" and candidate.exists():
        return candidate
    if candidate.is_absolute() or candidate.parent != Path("."):
        if candidate.exists():
            return candidate

    for path in (
        models_dir / voice / f"{voice}.onnx",
        models_dir / f"{voice}.onnx",
        models_dir / voice,
    ):
        if path.exists():
            return path
    return models_dir / f"{voice}.onnx"


class PiperTTSService(TTSService):
    """Piper TTS that resamples generated audio to the pipeline output rate."""

    def __init__(
        self,
        *,
        voice: str = "en_US-lessac-medium",
        models_dir: str | None = None,
        sample_rate: int = 24000,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            sample_rate=sample_rate,
            push_start_frame=True,
            push_stop_frames=True,
            stop_frame_timeout_s=0.6,
            settings=TTSSettings(model="piper", voice=voice, language=None),
            **kwargs,
        )
        configured = models_dir or os.getenv("PIPER_MODELS_DIR", "")
        self._models_dir = Path(configured).expanduser() if configured else Path.home() / ".cache" / "piper"
        self._voice_name = voice
        self._voice_path = _resolve_voice_path(voice, self._models_dir)
        self._voice: Any = None

    def _load_voice(self) -> None:
        if self._voice is not None:
            return
        self._voice = _shared_voice(self._voice_path)

    async def start(self, frame) -> None:
        await super().start(frame)
        started = time.perf_counter()
        try:
            await asyncio.to_thread(self._load_voice)
            logger.info(
                f"Piper voice '{self._voice_name}' loaded in "
                f"{(time.perf_counter() - started) * 1000:.0f}ms"
            )
        except Exception as exc:
            logger.error(
                f"Could not load Piper voice '{self._voice_name}' "
                f"from {self._voice_path}: {exc}"
            )

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        if self._voice is None:
            return
        try:
            chunks = await asyncio.to_thread(lambda: list(self._voice.synthesize(text)))
            if not chunks:
                return
            source_rate = int(chunks[0].sample_rate)

            async def audio_bytes() -> AsyncGenerator[bytes, None]:
                for chunk in chunks:
                    data = chunk.audio_int16_bytes
                    if data:
                        yield data

            async for frame in self._stream_audio_frames_from_iterator(
                audio_bytes(), in_sample_rate=source_rate, context_id=context_id
            ):
                yield frame
        except Exception as exc:
            logger.error(f"Local TTS failed: {exc}")
