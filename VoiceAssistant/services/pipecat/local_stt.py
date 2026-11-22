"""Local speech-to-text using faster-whisper.

Used only by the offline fallback pipeline. faster-whisper runs entirely on the
machine (CPU by default), so no API key or network access is needed.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncGenerator
from typing import Any

import numpy as np
from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.services.settings import STTSettings
from pipecat.services.stt_latency import WHISPER_TTFS_P99
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.utils.time import time_now_iso8601


# Reuse one Whisper model per configuration across calls. Loading a ~500 MB
# model on every call is slow and, on memory-constrained machines, repeatedly
# allocating/freeing it can fail with mkl_malloc. Caching also keeps the first
# call's load time off every subsequent call's critical path.
_WHISPER_CACHE: dict[tuple[str, str, str], Any] = {}


def _shared_whisper_model(model_name: str, device: str, compute_type: str) -> Any:
    key = (model_name, device, compute_type)
    model = _WHISPER_CACHE.get(key)
    if model is None:
        # CTranslate2/MKL allocates a workspace per CPU thread. Limit threads
        # before the native library loads to avoid mkl_malloc failures on
        # memory-constrained machines. Configurable via LOCAL_STT_NUM_THREADS.
        threads = os.getenv("LOCAL_STT_NUM_THREADS", "2")
        os.environ.setdefault("OMP_NUM_THREADS", threads)
        os.environ.setdefault("MKL_NUM_THREADS", threads)
        from faster_whisper import WhisperModel

        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        _WHISPER_CACHE[key] = model
    return model


class FasterWhisperSTTService(SegmentedSTTService):
    """Segmented Whisper STT that consumes raw 16 kHz 16-bit mono PCM."""

    def __init__(
        self,
        *,
        model: str = "small.en",
        language: str | None = "en",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 5,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            sample_rate=16000,
            ttfs_p99_latency=WHISPER_TTFS_P99,
            settings=STTSettings(model=model, language=language),
            **kwargs,
        )
        self._model_name = model
        self._language = language
        self._device = device
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._model: Any = None

    @property
    def wants_wav_segments(self) -> bool:
        """faster-whisper reads raw PCM; a WAV header would be misread as audio."""
        return False

    def _load_model(self) -> None:
        if self._model is not None:
            return
        self._model = _shared_whisper_model(
            self._model_name, self._device, self._compute_type
        )

    async def start(self, frame) -> None:
        await super().start(frame)
        started = time.perf_counter()
        try:
            await asyncio.to_thread(self._load_model)
            logger.info(
                f"faster-whisper '{self._model_name}' loaded in "
                f"{(time.perf_counter() - started) * 1000:.0f}ms"
            )
        except Exception as exc:
            logger.error(f"Could not load faster-whisper '{self._model_name}': {exc}")

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        if self._model is None:
            return
        try:
            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _info = await asyncio.to_thread(
                self._model.transcribe,
                samples,
                language=self._language,
                beam_size=self._beam_size,
                vad_filter=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if text:
                logger.debug(f"Local STT: [{text}]")
                yield TranscriptionFrame(text, self._user_id, time_now_iso8601())
        except Exception as exc:
            logger.error(f"Local STT failed: {exc}")
