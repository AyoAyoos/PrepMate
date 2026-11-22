"""Transport factory for this browser/WebRTC voice app.

Copied from the upstream Pipecat transport setup (BSD-2-Clause; see LICENSE).
The audio-mixer/workflow coupling has been removed; WebRTC uses a direct
``SmallWebRTCTransport`` with no ambient-noise mixer.
"""

from services.pipecat.audio_config import AudioConfig
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from services.pipecat.transport_params import realtime_param_overrides


async def create_webrtc_transport(
    webrtc_connection: SmallWebRTCConnection,
    audio_config: AudioConfig,
    is_realtime: bool = False,
):
    """Create a transport for WebRTC connections."""
    return SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=audio_config.transport_in_sample_rate,
            audio_out_sample_rate=audio_config.transport_out_sample_rate,
            **realtime_param_overrides(is_realtime),
        ),
    )
