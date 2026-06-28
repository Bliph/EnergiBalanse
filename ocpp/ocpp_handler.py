"""
OCPP 1.6 ChargePoint handler with MQTT publishing callbacks.

Extends the base ChargePoint class to publish status, measurements,
and transaction events to MQTT topics via a callback function.
"""

import logging
from datetime import datetime, timezone

from ocpp.routing import on
from ocpp.v16 import ChargePoint, call, call_result
from ocpp.v16.enums import (
    Action,
    AuthorizationStatus,
    ChargePointErrorCode,
    ChargePointStatus,
    DiagnosticsStatus,
    RegistrationStatus,
)

logger = logging.getLogger(__name__)


class ChargePointHandler(ChargePoint):
    """
    OCPP 1.6 charge point handler that forwards events to a publish callback.

    The publish callback signature is:
        publish(charge_point_id: str, topic_type: str, payload: dict)
    where topic_type is one of "status" (retained state), "event" (transient),
    or "measurements".
    """

    def __init__(self, charge_point_id, websocket, publish_callback=None):
        super().__init__(charge_point_id, websocket)
        self._publish = publish_callback
        self._transaction_id = 0

    def _publish_event(self, topic_type: str, payload: dict):
        """Publish an event via the registered callback."""
        if self._publish:
            try:
                self._publish(self.id, topic_type, payload)
            except Exception as e:
                logger.error(f"Error publishing {topic_type} for {self.id}: {e}")

    # ─── UPLINK (charge point → server) ───────────────────────────

    @on(Action.boot_notification)
    def on_boot_notification(
        self, charge_point_vendor: str, charge_point_model: str, **kwargs
    ):
        logger.info(
            f"BootNotification from {self.id}: vendor={charge_point_vendor}, model={charge_point_model}"
        )
        self._publish_event(
            "event",
            {
                "event": "boot_notification",
                "vendor": charge_point_vendor,
                "model": charge_point_model,
                **{k: str(v) for k, v in kwargs.items()},
            },
        )
        return call_result.BootNotification(
            current_time=datetime.now(timezone.utc).isoformat(),
            interval=10,
            status=RegistrationStatus.accepted,
        )

    @on(Action.heartbeat)
    def on_heartbeat(self, **kwargs):
        self._publish_event(
            "event",
            {
                "event": "heartbeat",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
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
        logger.info(
            f"StatusNotification from {self.id}: connector={connector_id}, "
            f"status={status}, error_code={error_code}"
        )
        self._publish_event(
            "status",
            {
                "event": "status_notification",
                "connector_id": connector_id,
                "status": str(status),
                "error_code": str(error_code),
                **{k: str(v) for k, v in kwargs.items()},
            },
        )
        return call_result.StatusNotification()

    @on(Action.diagnostics_status_notification)
    def on_diagnostics_status_notification(
        self,
        status: DiagnosticsStatus,
        **kwargs,
    ):
        self._publish_event(
            "event",
            {
                "event": "diagnostics_status",
                "status": str(status),
            },
        )
        return call_result.DiagnosticsStatusNotification()

    @on(Action.start_transaction)
    def on_start_transaction(
        self,
        connector_id: int,
        id_tag: str,
        meter_start: int,
        timestamp: str,
        **kwargs,
    ):
        self._transaction_id += 1
        logger.info(
            f"StartTransaction from {self.id}: connector={connector_id}, "
            f"id_tag={id_tag}, meter_start={meter_start}"
        )
        self._publish_event(
            "event",
            {
                "event": "start_transaction",
                "connector_id": connector_id,
                "id_tag": id_tag,
                "meter_start": meter_start,
                "timestamp": timestamp,
                "transaction_id": self._transaction_id,
            },
        )
        return call_result.StartTransaction(
            id_tag_info={"status": AuthorizationStatus.accepted},
            transaction_id=self._transaction_id,
        )

    @on(Action.meter_values)
    def on_meter_values(
        self,
        connector_id: int,
        meter_value: list,
        **kwargs,
    ):
        measurements = []
        for mv in meter_value:
            timestamp = mv.get("timestamp", "unknown")
            sampled_values = mv.get("sampled_value", [])
            for sv in sampled_values:
                value = sv.get("value")
                measurand = sv.get("measurand", "Energy.Active.Import.Register")
                unit = sv.get("unit", "Wh")
                phase = sv.get("phase", None)
                entry = {
                    "measurand": measurand,
                    "value": value,
                    "unit": unit,
                    "timestamp": timestamp,
                }
                if phase:
                    entry["phase"] = phase
                measurements.append(entry)
                logger.info(
                    f"MeterValue from {self.id}: connector={connector_id}, "
                    f"{measurand}={value} {unit} @ {timestamp}"
                )
        self._publish_event(
            "measurements",
            {
                "connector_id": connector_id,
                "meter_values": measurements,
            },
        )
        return call_result.MeterValues()

    @on(Action.stop_transaction)
    def on_stop_transaction(
        self,
        meter_stop: int,
        timestamp: str,
        transaction_id: int,
        **kwargs,
    ):
        reason = kwargs.get("reason", "Local")
        id_tag = kwargs.get("id_tag", "unknown")
        logger.info(
            f"StopTransaction from {self.id}: transaction_id={transaction_id}, "
            f"meter_stop={meter_stop}, reason={reason}"
        )
        self._publish_event(
            "event",
            {
                "event": "stop_transaction",
                "transaction_id": transaction_id,
                "meter_stop": meter_stop,
                "timestamp": timestamp,
                "reason": reason,
                "id_tag": id_tag,
            },
        )
        return call_result.StopTransaction(
            id_tag_info={"status": AuthorizationStatus.accepted},
        )

    # ─── DOWNLINK (server → charge point) ─────────────────────────

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
        result = await self.call(request)
        logger.info(f"RemoteStartTransaction result for {self.id}: {result}")
        return result

    async def remote_stop_transaction(self, transaction_id: int):
        """Stop a charging transaction remotely."""
        request = call.RemoteStopTransaction(transaction_id=transaction_id)
        result = await self.call(request)
        logger.info(f"RemoteStopTransaction result for {self.id}: {result}")
        return result

    async def set_charging_profile(
        self,
        connector_id: int,
        charging_profile: dict,
    ):
        """Set a charging profile (used to adjust charging current)."""
        request = call.SetChargingProfile(
            connector_id=connector_id,
            cs_charging_profiles=charging_profile,
        )
        result = await self.call(request)
        logger.info(f"SetChargingProfile result for {self.id}: {result}")
        return result

    async def change_configuration(self, key: str, value: str):
        """Change a configuration key on the charge point."""
        request = call.ChangeConfiguration(key=key, value=value)
        result = await self.call(request)
        logger.info(f"ChangeConfiguration result for {self.id}: {result}")
        return result

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
