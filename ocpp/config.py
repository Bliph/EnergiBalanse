"""
Configuration for the OCPP-MQTT bridge service.
"""

import os

# OCPP WebSocket server settings
OCPP_HOST = os.environ.get("OCPP_HOST", "0.0.0.0")
OCPP_PORT = int(os.environ.get("OCPP_PORT", "8180"))
OCPP_SUBPROTOCOL = "ocpp1.6"

# MQTT broker settings
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "ocpp_bridge")
MQTT_KEEPALIVE = int(os.environ.get("MQTT_KEEPALIVE", "60"))

# MQTT topic structure
# Base prefix for all energy consumers (protocol-agnostic)
MQTT_TOPIC_PREFIX = "consumers"

# Gateway identifier — used in gateway status topic and as consumer ID prefix
GATEWAY_TYPE = "ocpp"

# Gateway status topic: consumers/gateways/ocpp
TOPIC_GATEWAY_STATUS = f"gateways/{GATEWAY_TYPE}"

# Per-consumer sub-topics (appended to consumers/ocpp_<charge_point_id>/...)
# Published topics (retained):
#   consumers/ocpp_<cp_id>/status            — latest connector state
# Published topics (non-retained):
#   consumers/ocpp_<cp_id>/event             — transient events
#   consumers/ocpp_<cp_id>/measurements      — meter values
#   consumers/ocpp_<cp_id>/commands/response  — command result feedback
# Subscribed topics:
#   consumers/+/commands                      — inbound commands
TOPIC_STATUS = "status"
TOPIC_EVENT = "event"
TOPIC_MEASUREMENTS = "measurements"
TOPIC_COMMANDS = "commands"
TOPIC_COMMAND_RESPONSE = "commands/response"

# Logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
