"""Audio configuration for pipeline components.

This module provides centralized audio configuration to ensure consistent
sample rates across all pipeline components and proper coordination between
transport serializers, VAD, and audio buffers.
"""

from dataclasses import dataclass
from typing import Optional

from loguru import logger


@dataclass
class AudioConfig:
    """Centralized audio configuration for the pipeline.

    Note: Pipeline is limited to 16kHz maximum to support VAD.
    Transports handle resampling from/to higher rates (24kHz, 48kHz).

    Attributes:
        transport_in_sample_rate: Sample rate of incoming audio from transport (after resampling)
        transport_out_sample_rate: Sample rate of outgoing audio to transport (before resampling)
        vad_sample_rate: Sample rate for VAD processing (8000 or 16000)
        pipeline_sample_rate: Internal pipeline processing sample rate (max 16000)
        buffer_size_seconds: Audio buffer size in seconds
    """

    transport_in_sample_rate: int
    transport_out_sample_rate: int
    vad_sample_rate: int = 16000  # VAD typically resamples internally
    pipeline_sample_rate: Optional[int] = None  # If None, uses transport rates
    buffer_size_seconds: float = 5.0  # This is how frequenly we will call merge_auido
    max_recording_duration_seconds: float = 300.0  # 5 minutes max recording duration

    def __post_init__(self):
        # Validate VAD sample rate
        if self.vad_sample_rate not in [8000, 16000]:
            raise ValueError(
                f"VAD sample rate must be 8000 or 16000, got {self.vad_sample_rate}"
            )

        # Set pipeline sample rate to transport out rate if not specified
        if self.pipeline_sample_rate is None:
            self.pipeline_sample_rate = min(self.transport_out_sample_rate, 16000)

        # Ensure pipeline sample rate doesn't exceed 16kHz (VAD limitation)
        if self.pipeline_sample_rate > 16000:
            logger.warning(
                f"Pipeline sample rate {self.pipeline_sample_rate} exceeds 16kHz limit, "
                f"capping at 16kHz. Transport will handle resampling."
            )
            self.pipeline_sample_rate = 16000

    @property
    def buffer_size_bytes(self) -> int:
        """Calculate buffer size in bytes based on pipeline sample rate."""
        # 2 bytes per sample (16-bit PCM)
        return int(self.pipeline_sample_rate * 2 * self.buffer_size_seconds)

    @property
    def buffer_size_samples(self) -> int:
        """Calculate buffer size in samples based on pipeline sample rate."""
        return int(self.pipeline_sample_rate * self.buffer_size_seconds)

    @property
    def max_recording_bytes(self) -> int:
        """Calculate max recording size in bytes based on pipeline sample rate and duration."""
        # 2 bytes per sample (16-bit PCM)
        return int(self.pipeline_sample_rate * 2 * self.max_recording_duration_seconds)
