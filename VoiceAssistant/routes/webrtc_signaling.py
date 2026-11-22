"""WebSocket-based WebRTC signaling endpoint with ICE trickling support.

Adapted from the upstream WebRTC signaling route (BSD-2-Clause; see LICENSE).
Auth, organization/workspace, quota, call concurrency, TURN, embed-session and
pipeline-orchestration coupling have been removed. The SmallWebRTC contract and
the JSON message schema are unchanged:

- ``SmallWebRTCConnection`` for peer connection management
- ``candidate_from_sdp()`` / ``add_ice_candidate()`` for ICE trickling
"""

import bootstrap  # noqa: F401  (puts the vendored Pipecat package on sys.path)

import asyncio
from typing import Dict, List, Optional, Set

from aiortc import RTCIceServer
from aiortc.sdp import candidate_from_sdp
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from starlette.websockets import WebSocketState

from pipeline import start_pipeline
from services.pipecat.ws_sender_registry import (
    register_ws_sender,
    unregister_ws_sender,
)
from storage.duckdb_store import store

router = APIRouter(prefix="/ws")


async def _record_signaling_error(message: str, exc: Exception | None = None) -> None:
    """Log signaling failures to stderr, the ERROR file and the error table."""
    if exc is not None:
        logger.opt(exception=exc).error(message)
    else:
        logger.error(message)
    await store.log_error(
        source="signaling",
        level="ERROR",
        message=message,
        stack=str(exc) if exc is not None else None,
        context={"component": "webrtc_signaling"},
    )


def _log_pipeline_task_result(task: asyncio.Task) -> None:
    """Retrieve task exceptions so they are never silently unhandled."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        asyncio.create_task(
            _record_signaling_error(f"Voice pipeline task failed: {exc}", exc)
        )


def get_ice_servers() -> List[RTCIceServer]:
    """Build the STUN-only ICE server list (no TURN credentials needed)."""
    return [RTCIceServer(urls="stun:stun.l.google.com:19302")]


def filter_outbound_sdp(sdp: str) -> str:
    """Keep the original answer SDP; no outbound candidate filtering is applied."""
    return sdp


class SignalingManager:
    """Manages WebSocket connections and WebRTC peer connections."""

    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}
        self._peer_connections: Dict[str, SmallWebRTCConnection] = {}
        self._connection_peer_ids: Dict[str, Set[str]] = {}
        self._peer_connection_owners: Dict[str, str] = {}

    def _track_peer_connection(
        self, connection_id: str, pc_id: str, pc: SmallWebRTCConnection
    ) -> None:
        self._peer_connections[pc_id] = pc
        self._peer_connection_owners[pc_id] = connection_id
        self._connection_peer_ids.setdefault(connection_id, set()).add(pc_id)

    def _forget_peer_connection(self, pc_id: str) -> Optional[str]:
        connection_id = self._peer_connection_owners.pop(pc_id, None)
        self._peer_connections.pop(pc_id, None)

        if connection_id:
            peer_ids = self._connection_peer_ids.get(connection_id)
            if peer_ids is not None:
                peer_ids.discard(pc_id)
                if not peer_ids:
                    self._connection_peer_ids.pop(connection_id, None)

        return connection_id

    async def _send_json_if_connected(
        self, websocket: WebSocket, message: dict
    ) -> bool:
        if websocket.application_state != WebSocketState.CONNECTED:
            return False

        try:
            await websocket.send_json(message)
            return True
        except Exception as e:
            logger.debug(f"Failed to send signaling WebSocket message: {e}")
            return False

    async def _close_websocket_if_connected(
        self, websocket: WebSocket, code: int = 1000, reason: str = ""
    ) -> None:
        if websocket.application_state != WebSocketState.CONNECTED:
            return

        try:
            await websocket.close(code=code, reason=reason)
        except Exception as e:
            logger.debug(f"Failed to close signaling WebSocket: {e}")

    async def _notify_call_ended_and_close_websocket(
        self,
        websocket: WebSocket,
        session_id: int,
        pc_id: str,
        reason: str,
    ) -> None:
        await self._send_json_if_connected(
            websocket,
            {
                "type": "call-ended",
                "payload": {
                    "session_id": session_id,
                    "pc_id": pc_id,
                    "reason": reason,
                },
            },
        )
        await self._close_websocket_if_connected(
            websocket, code=1000, reason="call ended"
        )

    async def handle_websocket(self, websocket: WebSocket, session_id: int):
        """Handle a signaling WebSocket connection for one voice session."""
        await websocket.accept()
        connection_id = f"session:{session_id}"
        connection_key = f"{connection_id}:{id(websocket)}"
        self._connections[connection_key] = websocket

        try:
            while True:
                message = await websocket.receive_json()
                await self._handle_message(
                    websocket, message, session_id, connection_key
                )
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for {connection_id}")
        except Exception as e:
            if websocket.application_state == WebSocketState.DISCONNECTED:
                logger.info(f"WebSocket disconnected for {connection_id}")
            else:
                await _record_signaling_error(
                    f"WebSocket error for {connection_id}: {e}", e
                )
        finally:
            self._connections.pop(connection_key, None)
            peer_ids = list(self._connection_peer_ids.pop(connection_key, set()))

            unregister_ws_sender(session_id)

            for pc_id in peer_ids:
                self._peer_connection_owners.pop(pc_id, None)
                pc = self._peer_connections.pop(pc_id, None)
                if pc:
                    try:
                        await pc.disconnect()
                        logger.debug(f"Disconnected peer connection: {pc_id}")
                    except Exception as e:
                        logger.debug(f"Failed to disconnect peer connection: {e}")

    async def _handle_message(
        self,
        ws: WebSocket,
        message: dict,
        session_id: int,
        connection_key: str,
    ):
        """Handle incoming WebSocket messages."""
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type == "offer":
            await self._handle_offer(ws, payload, session_id, connection_key)
        elif msg_type == "ice-candidate":
            await self._handle_ice_candidate(payload, connection_key)
        elif msg_type == "renegotiate":
            await self._handle_renegotiation(ws, payload, connection_key)

    async def _handle_offer(
        self,
        ws: WebSocket,
        payload: dict,
        session_id: int,
        connection_key: str,
    ):
        """Handle offer message and create answer with ICE trickling."""
        pc_id = payload.get("pc_id")
        sdp = payload.get("sdp")
        type_ = payload.get("type")
        call_context_vars = payload.get("call_context_vars", {})

        if not pc_id or not sdp or not type_:
            await ws.send_json(
                {
                    "type": "error",
                    "payload": {"message": "Missing offer fields"},
                }
            )
            return

        if pc_id in self._peer_connections:
            if self._peer_connection_owners.get(pc_id) != connection_key:
                await ws.send_json(
                    {
                        "type": "error",
                        "payload": {"message": "Peer connection already owned"},
                    }
                )
                return

            logger.info(f"Reusing existing connection for pc_id: {pc_id}")
            pc = self._peer_connections[pc_id]
            await pc.renegotiate(sdp=sdp, type=type_, restart_pc=False)

            answer = pc.get_answer()
            await ws.send_json(
                {
                    "type": "answer",
                    "payload": {
                        "sdp": filter_outbound_sdp(answer["sdp"]),
                        "type": "answer",
                        "pc_id": pc_id,
                    },
                }
            )
        else:
            pc = None
            try:
                pc = SmallWebRTCConnection(
                    ice_servers=get_ice_servers(), connection_timeout_secs=60
                )
                pc._pc_id = pc_id
                await pc.initialize(sdp=sdp, type=type_)
                self._track_peer_connection(connection_key, pc_id, pc)

                async def ws_sender(message: dict):
                    if ws.application_state == WebSocketState.CONNECTED:
                        await ws.send_json(message)

                register_ws_sender(session_id, ws_sender)

                @pc.event_handler("closed")
                async def handle_disconnected(
                    webrtc_connection: SmallWebRTCConnection,
                ):
                    logger.info(f"PeerConnection closed: {webrtc_connection.pc_id}")
                    owner_connection_id = self._forget_peer_connection(
                        webrtc_connection.pc_id
                    )
                    if owner_connection_id == connection_key:
                        await self._notify_call_ended_and_close_websocket(
                            ws,
                            session_id,
                            webrtc_connection.pc_id,
                            reason="peer_connection_closed",
                        )

                pipeline_task = asyncio.create_task(
                    start_pipeline(pc, session_id, call_context_vars)
                )
                pipeline_task.add_done_callback(_log_pipeline_task_result)

                answer = pc.get_answer()
                await ws.send_json(
                    {
                        "type": "answer",
                        "payload": {
                            "sdp": filter_outbound_sdp(answer["sdp"]),
                            "type": answer["type"],
                            "pc_id": answer["pc_id"],
                        },
                    }
                )
            except Exception:
                if pc is not None:
                    try:
                        await pc.disconnect()
                    except Exception as e:
                        logger.debug(f"Failed to disconnect failed offer pc: {e}")
                raise

    async def _handle_ice_candidate(self, payload: dict, connection_key: str):
        """Handle an incoming ICE candidate from the client."""
        pc_id = payload.get("pc_id")
        candidate_data = payload.get("candidate")

        if not pc_id:
            logger.warning("Received ICE candidate without pc_id")
            return

        pc = self._peer_connections.get(pc_id)
        if not pc:
            logger.warning(f"No peer connection found for pc_id: {pc_id}")
            return
        if self._peer_connection_owners.get(pc_id) != connection_key:
            logger.warning(f"Ignoring ICE candidate for unowned pc_id: {pc_id}")
            return

        if candidate_data:
            candidate_str = candidate_data.get("candidate", "")
            try:
                candidate = candidate_from_sdp(candidate_str)
                candidate.sdpMid = candidate_data.get("sdpMid")
                candidate.sdpMLineIndex = candidate_data.get("sdpMLineIndex")
                await pc.add_ice_candidate(candidate)
                logger.debug(f"Added ICE candidate for pc_id: {pc_id}")
            except Exception as e:
                await _record_signaling_error(f"Failed to add ICE candidate: {e}", e)
        else:
            logger.debug(f"End of ICE candidates for pc_id: {pc_id}")

    async def _handle_renegotiation(
        self, ws: WebSocket, payload: dict, connection_key: str
    ):
        """Handle a renegotiation request."""
        pc_id = payload.get("pc_id")
        sdp = payload.get("sdp")
        type_ = payload.get("type")
        restart_pc = payload.get("restart_pc", False)

        pc = self._peer_connections.get(pc_id) if pc_id else None
        if not pc:
            await ws.send_json(
                {"type": "error", "payload": {"message": "Peer connection not found"}}
            )
            return
        if self._peer_connection_owners.get(pc_id) != connection_key:
            await ws.send_json(
                {"type": "error", "payload": {"message": "Peer connection not found"}}
            )
            return

        await pc.renegotiate(sdp=sdp, type=type_, restart_pc=restart_pc)
        answer = pc.get_answer()
        await ws.send_json(
            {
                "type": "answer",
                "payload": {
                    "sdp": filter_outbound_sdp(answer["sdp"]),
                    "type": "answer",
                    "pc_id": pc_id,
                },
            }
        )


signaling_manager = SignalingManager()


@router.websocket("/signaling/{session_id}")
async def signaling_websocket(websocket: WebSocket, session_id: int):
    """WebSocket signaling endpoint used by the browser page."""
    await signaling_manager.handle_websocket(websocket, session_id)
