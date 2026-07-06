"""
OCPP WebSocket server running in a dedicated thread with its own asyncio event loop.

Manages connected charge points and provides thread-safe methods to dispatch
commands from the MQTT client to individual charge points.
"""

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

import websockets

import config
from ocpp_handler import ChargePointHandler

logger = logging.getLogger(__name__)


class OcppServer:
    """
    Runs an OCPP 1.6 WebSocket server in a background thread.

    The server maintains a registry of connected charge points and exposes
    thread-safe methods to send commands to them.
    """

    def __init__(self, publish_callback: Callable = None):
        """
        Args:
            publish_callback: Called when OCPP events occur.
                Signature: callback(consumer_id, topic_type, payload)
        """
        self._publish_callback = publish_callback
        self._charge_points: Dict[str, ChargePointHandler] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._lock = threading.Lock()

    @staticmethod
    def _consumer_id(charge_point_id: str) -> str:
        """Convert an OCPP charge point ID to a consumer ID for MQTT topics."""
        return f"{config.GATEWAY_TYPE}_{charge_point_id}"

    @staticmethod
    def _cp_id_from_consumer(consumer_id: str) -> str:
        """Extract the OCPP charge point ID from a consumer ID."""
        prefix = f"{config.GATEWAY_TYPE}_"
        if consumer_id.startswith(prefix):
            return consumer_id[len(prefix) :]
        return consumer_id

    @property
    def charge_points(self) -> Dict[str, ChargePointHandler]:
        """Return connected charge points keyed by consumer ID."""
        with self._lock:
            return {self._consumer_id(k): v for k, v in self._charge_points.items()}

    def start(self):
        """Start the OCPP server in a background thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ocpp-server",
            daemon=True,
        )
        self._thread.start()
        logger.info("OCPP server thread started.")

    def stop(self):
        """Shut down the OCPP server and its event loop."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("OCPP server thread stopped.")

    def _run_loop(self):
        """Entry point for the server thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        """Start the WebSocket server and run forever."""
        self._server = await websockets.serve(
            self._on_connect,
            config.OCPP_HOST,
            config.OCPP_PORT,
            subprotocols=[config.OCPP_SUBPROTOCOL],
        )
        logger.info(
            f"OCPP WebSocket server listening on ws://{config.OCPP_HOST}:{config.OCPP_PORT}"
        )
        try:
            await asyncio.Future()  # run forever
        except asyncio.CancelledError:
            pass
        finally:
            self._server.close()
            await self._server.wait_closed()
            logger.info("OCPP WebSocket server shut down.")

    async def _on_connect(self, websocket):
        """Handle a new charge point connection."""
        try:
            requested_protocols = websocket.request.headers["Sec-WebSocket-Protocol"]
        except KeyError:
            logger.error("Client hasn't requested any Subprotocol. Closing connection.")
            return await websocket.close()

        if websocket.subprotocol:
            logger.info("Protocols Matched: %s", websocket.subprotocol)
        else:
            logger.warning(
                "Protocols Mismatched | Expected: %s, Client: %s | Closing",
                websocket.protocol.available_subprotocols,
                requested_protocols,
            )
            return await websocket.close()

        charge_point_id = websocket.request.path.strip("/")
        consumer_id = self._consumer_id(charge_point_id)
        cp = ChargePointHandler(
            charge_point_id,
            websocket,
            publish_callback=self._make_cp_publish(consumer_id),
        )

        with self._lock:
            self._charge_points[charge_point_id] = cp

        logger.info(f"Charge point '{charge_point_id}' connected.")

        # Publish connected state (retained) and event (transient)
        if self._publish_callback:
            self._publish_callback(
                consumer_id,
                "status",
                {
                    "available": True,
                    "connector_status": "Unknown",
                },
            )
            self._publish_callback(
                consumer_id,
                "event",
                {
                    "event": "connected",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        try:
            await cp.start()
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Charge point '{charge_point_id}' connection closed.")
        except Exception as e:
            logger.error(f"Charge point '{charge_point_id}' error: {e}")
        finally:
            with self._lock:
                self._charge_points.pop(charge_point_id, None)

            if self._publish_callback:
                self._publish_callback(
                    consumer_id,
                    "status",
                    {
                        "available": False,
                        "connector_status": "Unavailable",
                    },
                )
                self._publish_callback(
                    consumer_id,
                    "event",
                    {
                        "event": "disconnected",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            logger.info(
                f"Charge point '{charge_point_id}' disconnected and cleaned up."
            )

    def _make_cp_publish(self, consumer_id: str) -> Callable:
        """Create a publish callback that maps charge_point_id to consumer_id."""

        def publish(cp_id: str, topic_type: str, payload: dict):
            if self._publish_callback:
                self._publish_callback(consumer_id, topic_type, payload)

        return publish

    # ─── Thread-safe command dispatch ─────────────────────

    def dispatch_command(self, consumer_id: str, command: dict):
        """
        Dispatch a command to a charge point (thread-safe).

        Called from the MQTT thread; schedules async work on the OCPP
        event loop. Accepts consumer_id (e.g. 'ocpp_CHARGER01') and
        strips the gateway prefix to find the charge point.

        Command format:
            {"command": "start", "id_tag": "...", "connector_id": 1}
            {"command": "stop", "transaction_id": 1}
            {"command": "set_current", "connector_id": 1, "current": 16}
        """
        charge_point_id = self._cp_id_from_consumer(consumer_id)

        with self._lock:
            cp = self._charge_points.get(charge_point_id)

        if cp is None:
            logger.warning(
                f"Command for unknown charge point '{charge_point_id}': {command}"
            )
            return

        cmd = command.get("command", "").lower()

        if cmd == "start":
            coro = self._cmd_start(cp, command)
        elif cmd == "stop":
            coro = self._cmd_stop(cp, command)
        elif cmd == "set_current":
            coro = self._cmd_set_current(cp, command)
        else:
            logger.warning(f"Unknown command '{cmd}' for {charge_point_id}")
            return

        # Schedule the coroutine on the OCPP event loop from this thread
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _publish_command_response(
        self, consumer_id: str, command: str, status: str, detail: str = None
    ):
        """Publish a command response via the MQTT callback."""
        if self._publish_callback:
            payload = {"command": command, "status": status}
            if detail:
                payload["detail"] = detail
            self._publish_callback(consumer_id, "command_response", payload)

    async def _cmd_start(self, cp: ChargePointHandler, command: dict):
        """Handle a start charging command."""
        consumer_id = self._consumer_id(cp.id)
        id_tag = command.get("id_tag", "REMOTE")
        connector_id = command.get("connector_id", 1)
        try:
            result = await cp.remote_start_transaction(
                id_tag=id_tag, connector_id=connector_id
            )
            logger.info(f"Start command result for {cp.id}: {result}")
            self._publish_command_response(
                consumer_id, "start", str(getattr(result, "status", result))
            )
        except Exception as e:
            logger.error(f"Start command failed for {cp.id}: {e}")
            self._publish_command_response(consumer_id, "start", "error", str(e))

    async def _cmd_stop(self, cp: ChargePointHandler, command: dict):
        """Handle a stop charging command."""
        consumer_id = self._consumer_id(cp.id)
        transaction_id = command.get("transaction_id", 1)
        try:
            result = await cp.remote_stop_transaction(transaction_id=transaction_id)
            logger.info(f"Stop command result for {cp.id}: {result}")
            self._publish_command_response(
                consumer_id, "stop", str(getattr(result, "status", result))
            )
        except Exception as e:
            logger.error(f"Stop command failed for {cp.id}: {e}")
            self._publish_command_response(consumer_id, "stop", "error", str(e))

    async def _cmd_set_current(self, cp: ChargePointHandler, command: dict):
        """
        Handle a set charging current command.

        Builds a TxDefaultProfile with the desired current limit and sends
        it via SetChargingProfile.
        """
        consumer_id = self._consumer_id(cp.id)
        connector_id = command.get("connector_id", 1)
        current = command.get("current", 16)

        charging_profile = {
            "chargingProfileId": 1,
            "stackLevel": 0,
            "chargingProfilePurpose": "TxDefaultProfile",
            "chargingProfileKind": "Absolute",
            "chargingSchedule": {
                "chargingRateUnit": "A",
                "chargingSchedulePeriod": [
                    {"startPeriod": 0, "limit": float(current)},
                ],
            },
        }

        try:
            result = await cp.set_charging_profile(
                connector_id=connector_id,
                charging_profile=charging_profile,
            )
            logger.info(f"SetCurrent({current}A) result for {cp.id}: {result}")
            self._publish_command_response(
                consumer_id,
                "set_current",
                str(getattr(result, "status", result)),
                f"{current}A",
            )
        except Exception as e:
            logger.error(f"SetCurrent command failed for {cp.id}: {e}")
            self._publish_command_response(consumer_id, "set_current", "error", str(e))
