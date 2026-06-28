"""
MQTT client for the OCPP-MQTT bridge.

Handles:
- Publishing OCPP events (status, measurements) to MQTT topics
- Subscribing to command topics and forwarding commands to the OCPP server
"""

import json
import logging
import time
from datetime import datetime, timezone

import paho.mqtt.client as paho_mqtt

import config

logger = logging.getLogger(__name__)


class OcppMqttClient:
    """
    MQTT client that bridges OCPP events to MQTT topics.

    Published topics (retained):
        consumers/ocpp_<cp_id>/status              — latest connector state
        consumers/gateways/ocpp                     — bridge/gateway status
    Published topics (non-retained):
        consumers/ocpp_<cp_id>/event               — transient events
        consumers/ocpp_<cp_id>/measurements        — meter values
        consumers/ocpp_<cp_id>/commands/response    — command feedback

    Subscribed topics:
        consumers/+/commands   (wildcard for all consumers)

    Command message format (JSON):
        Start charging:   {"command": "start", "id_tag": "...", "connector_id": 1}
        Stop charging:    {"command": "stop", "transaction_id": 1}
        Set current:      {"command": "set_current", "connector_id": 1, "current": 16}
    """

    def __init__(self, command_callback=None):
        """
        Args:
            command_callback: Function called when a command is received.
                Signature: callback(charge_point_id: str, command: dict)
        """
        self._command_callback = command_callback
        self._connected = False

        self._client = paho_mqtt.Client(client_id=config.MQTT_CLIENT_ID)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        if config.MQTT_USERNAME:
            self._client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)

        # Reference to the OCPP server for building status payloads
        self._ocpp_server = None

        # LWT: mark gateway as offline when connection drops
        lwt_topic = f"{config.MQTT_TOPIC_PREFIX}/{config.TOPIC_GATEWAY_STATUS}"
        lwt_payload = json.dumps(
            {
                "connected": False,
                "consumers": [],
            }
        )
        self._client.will_set(lwt_topic, payload=lwt_payload, qos=1, retain=True)

    def start(self):
        """Connect to MQTT broker and start the network loop in a background thread."""
        logger.info(
            f"Connecting to MQTT broker at {config.MQTT_HOST}:{config.MQTT_PORT}"
        )
        try:
            self._client.connect(
                host=config.MQTT_HOST,
                port=config.MQTT_PORT,
                keepalive=config.MQTT_KEEPALIVE,
            )
            self._client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def stop(self):
        """Disconnect from the MQTT broker."""
        if self._connected:
            # Publish offline gateway status before disconnecting
            self._publish(
                f"{config.MQTT_TOPIC_PREFIX}/{config.TOPIC_GATEWAY_STATUS}",
                {"connected": False, "consumers": []},
                retain=True,
            )
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("MQTT client disconnected.")

    @property
    def connected(self):
        return self._connected

    # ─── Publishing ───────────────────────────────────────────────

    def publish_cp_status(self, consumer_id: str, payload: dict):
        """Publish retained connector state for a consumer."""
        topic = f"{config.MQTT_TOPIC_PREFIX}/{consumer_id}/{config.TOPIC_STATUS}"
        self._publish(topic, payload, retain=True)

    def publish_cp_event(self, consumer_id: str, payload: dict):
        """Publish a transient event for a consumer."""
        topic = f"{config.MQTT_TOPIC_PREFIX}/{consumer_id}/{config.TOPIC_EVENT}"
        self._publish(topic, payload)

    def publish_measurements(self, consumer_id: str, payload: dict):
        """Publish measurement data for a consumer."""
        topic = f"{config.MQTT_TOPIC_PREFIX}/{consumer_id}/{config.TOPIC_MEASUREMENTS}"
        self._publish(topic, payload)

    def publish_command_response(self, consumer_id: str, payload: dict):
        """Publish command result feedback for a consumer."""
        topic = (
            f"{config.MQTT_TOPIC_PREFIX}/{consumer_id}/{config.TOPIC_COMMAND_RESPONSE}"
        )
        self._publish(topic, payload)

    def on_ocpp_callback(self, charge_point_id: str, topic_type: str, payload: dict):
        """
        Generic dispatcher matching the callback signature used by
        ChargePointHandler and OcppServer.

        Args:
            charge_point_id: The charge point identifier
            topic_type: One of "status", "event", "measurements", "command_response"
            payload: The event data dict
        """
        if topic_type == "status":
            self.publish_cp_status(charge_point_id, payload)
            self.publish_bridge_status()
        elif topic_type == "event":
            self.publish_cp_event(charge_point_id, payload)
        elif topic_type == "measurements":
            self.publish_measurements(charge_point_id, payload)
        elif topic_type == "command_response":
            self.publish_command_response(charge_point_id, payload)
        else:
            logger.warning(f"Unknown topic type: {topic_type}")

    def publish_bridge_status(self):
        """Publish the gateway status to consumers/gateways/ocpp (retained).

        Payload includes:
            connected: bool — whether the gateway is online
            consumers: list — consumer IDs of connected charge points
        """
        cp_list = []
        if self._ocpp_server:
            cp_list = list(self._ocpp_server.charge_points.keys())

        topic = f"{config.MQTT_TOPIC_PREFIX}/{config.TOPIC_GATEWAY_STATUS}"
        self._publish(
            topic,
            {"connected": True, "consumers": cp_list},
            retain=True,
        )

    def _publish(self, topic: str, payload: dict, retain: bool = False):
        """Publish a JSON payload to a topic."""
        if not self._connected:
            logger.warning(f"MQTT not connected; dropping message on {topic}")
            return

        payload["_timestamp"] = datetime.now(timezone.utc).isoformat()
        try:
            msg = json.dumps(payload, default=str, allow_nan=False)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize payload for {topic}: {e}")
            return

        result = self._client.publish(topic, payload=msg, qos=0, retain=retain)
        if result.rc != paho_mqtt.MQTT_ERR_SUCCESS:
            logger.warning(f"MQTT publish failed on {topic}: rc={result.rc}")

    # ─── Callbacks ────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            logger.info("Connected to MQTT broker")

            # Publish bridge online status
            self.publish_bridge_status()

            # Subscribe to command topics for all charge points
            command_topic = f"{config.MQTT_TOPIC_PREFIX}/+/{config.TOPIC_COMMANDS}"
            client.subscribe(command_topic, qos=1)
            logger.info(f"Subscribed to {command_topic}")
        else:
            logger.error(f"MQTT connection failed: rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnect: rc={rc}")
        else:
            logger.info("MQTT disconnected cleanly")

    def _on_message(self, client, userdata, message):
        """Handle incoming MQTT command messages."""
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Invalid message on {message.topic}: {e}")
            return

        # Extract charge_point_id from topic: ocpp/<charge_point_id>/commands
        parts = message.topic.split("/")
        if len(parts) < 3:
            logger.warning(f"Unexpected topic format: {message.topic}")
            return

        charge_point_id = parts[1]
        logger.info(f"Command received for {charge_point_id}: {payload}")

        if self._command_callback:
            try:
                self._command_callback(charge_point_id, payload)
            except Exception as e:
                logger.error(f"Error handling command for {charge_point_id}: {e}")
