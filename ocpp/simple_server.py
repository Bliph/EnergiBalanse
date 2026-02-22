import asyncio
import logging
from datetime import datetime, timezone


# https://github.com/mobilityhouse/ocpp

try:
    import websockets
except ModuleNotFoundError:
    print("This example relies on the 'websockets' package.")
    print("Please install it by running: ")
    print()
    print(" $ pip install websockets")
    import sys

    sys.exit(1)

from ocpp.routing import on
from ocpp.v16 import ChargePoint
from ocpp.v16 import call, call_result
from ocpp.v16.enums import (
    Action,
    RegistrationStatus,
    ChargePointErrorCode,
    ChargePointStatus,
    DiagnosticsStatus,
)

logging.basicConfig(level=logging.INFO)
# Store connected charge points for interactive access
connected_charge_points = list()


def cp() -> "ChargePointInstance":
    """Convenience function to get the last connected charge point for debugging."""
    return connected_charge_points[-1] if connected_charge_points else None


class ChargePointInstance(ChargePoint):

    #####################################################
    # UPLINK
    @on(Action.boot_notification)
    def on_boot_notification(
        self, charge_point_vendor: str, charge_point_model: str, **kwargs
    ):
        return call_result.BootNotification(
            current_time=datetime.now(timezone.utc).isoformat(),
            interval=10,
            status=RegistrationStatus.accepted,
        )

    @on(Action.heartbeat)
    def on_heartbeat(self, **kwargs):
        return call_result.Heartbeat(
            current_time=datetime.now(timezone.utc).isoformat(),
        )

    @on(Action.status_notification)
    def on_status_notification(
        self,
        connector_id: int,
        error_code: ChargePointErrorCode,
        status: ChargePointStatus,
        **kwargs,
    ):
        return call_result.StatusNotification()

    @on(Action.diagnostics_status_notification)
    def on_diagnostics_status_notification(
        self,
        status: DiagnosticsStatus,
        **kwargs,
    ):
        return call_result.DiagnosticsStatusNotification()

    #####################################################
    # DOWNLINK
    async def get_diagnostics(
        self,
        location: str,
        retries: int = None,
        retry_interval: int = None,
        start_time: str = None,
        stop_time: str = None,
    ):
        """Request diagnostics from the charge point."""
        request = call.GetDiagnostics(
            location=location,
            retries=retries,
            retry_interval=retry_interval,
            start_time=start_time,
            stop_time=stop_time,
        )
        return await self.call(request)

    async def remote_start_transaction(
        self,
        id_tag: str,
        connector_id: int = None,
        charging_profile: dict = None,
    ):
        """Start a charging transaction remotely."""
        request = call.RemoteStartTransaction(
            id_tag=id_tag,
            connector_id=connector_id,
            charging_profile=charging_profile,
        )
        return await self.call(request)

    async def remote_stop_transaction(self, transaction_id: int):
        """Stop a charging transaction remotely."""
        request = call.RemoteStopTransaction(transaction_id=transaction_id)
        return await self.call(request)


#####################################################
#
async def on_connect(websocket):
    """For every new charge point that connects, create a ChargePoint
    instance and start listening for messages.
    """
    try:
        requested_protocols = websocket.request.headers["Sec-WebSocket-Protocol"]
    except KeyError:
        logging.error("Client hasn't requested any Subprotocol. Closing Connection")
        return await websocket.close()
    if websocket.subprotocol:
        logging.info("Protocols Matched: %s", websocket.subprotocol)
    else:
        # In the websockets lib if no subprotocols are supported by the
        # client and the server, it proceeds without a subprotocol,
        # so we have to manually close the connection.
        logging.warning(
            "Protocols Mismatched | Expected Subprotocols: %s,"
            " but client supports  %s | Closing connection",
            websocket.available_subprotocols,
            requested_protocols,
        )
        return await websocket.close()

    charge_point_id = websocket.request.path.strip("/")
    cp = ChargePointInstance(charge_point_id, websocket)

    # Store reference for interactive access
    connected_charge_points.append(cp)
    logging.info(
        f"Charge point '{charge_point_id}' connected. Total: {len(connected_charge_points)}"
    )

    try:
        await cp.start()
    finally:
        # Clean up when disconnected
        logging.info(f"Charge point '{charge_point_id}' disconnected.")


async def start_server():
    server = await websockets.serve(
        on_connect, "0.0.0.0", 8180, subprotocols=["ocpp1.6"]
    )

    logging.info("Server Started listening to new connections...")
    return server


async def main():
    server = await start_server()
    await server.wait_closed()


if __name__ == "__main__":
    # asyncio.run() is used when running this example with Python >= 3.7v
    asyncio.run(main())

    pass

"""
from simple_server import *
server = await start_server()
connected_charge_points
connected_charge_points[0]
connected_charge_points[-1]
await cp().remote_start_transaction("E6F00CCF", connector_id=1)
"""

########################
# Repl debugging:
# Run python -m asyncio
# >>> from simple_server import *
# >>> server = await start_server()
# >>> connected_charge_points
# >>> connected_charge_points[0]
# >>> await connected_charge_points[0].get_diagnostics("HHH")
#
