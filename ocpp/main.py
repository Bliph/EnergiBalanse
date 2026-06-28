#!/usr/bin/env python3
"""
OCPP-MQTT Bridge — Main entry point.

Starts:
  1. OCPP WebSocket server in a background thread
  2. MQTT client (paho loop) in a background thread

OCPP callbacks publish to MQTT topics:
    ocpp/<charge_point_id>/status
    ocpp/<charge_point_id>/measurements

MQTT commands on:
    ocpp/<charge_point_id>/commands
are forwarded to the OCPP server.

Usage:
    python main.py                  # run standalone
    python main.py --host 0.0.0.0 --port 8180 --mqtt-host localhost

Environment variables (override defaults in config.py):
    OCPP_HOST, OCPP_PORT, MQTT_HOST, MQTT_PORT, MQTT_USERNAME,
    MQTT_PASSWORD, MQTT_CLIENT_ID, LOG_LEVEL
"""
import argparse
import logging
import os
import signal
import sys
import time

# Ensure the ocpp folder is on the path when run as a script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from mqtt_client import OcppMqttClient
from ocpp_server import OcppServer

logger = logging.getLogger("ocpp_bridge")

_shutdown = False


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="OCPP-MQTT Bridge Service",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"OCPP WebSocket listen address (default: {config.OCPP_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"OCPP WebSocket listen port (default: {config.OCPP_PORT})",
    )
    parser.add_argument(
        "--mqtt-host",
        default=None,
        help=f"MQTT broker host (default: {config.MQTT_HOST})",
    )
    parser.add_argument(
        "--mqtt-port",
        type=int,
        default=None,
        help=f"MQTT broker port (default: {config.MQTT_PORT})",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help=f"Log level (default: {config.LOG_LEVEL})",
    )
    return parser.parse_args()


def apply_args(args):
    """Apply CLI arguments as overrides to config module."""
    if args.host:
        config.OCPP_HOST = args.host
    if args.port:
        config.OCPP_PORT = args.port
    if args.mqtt_host:
        config.MQTT_HOST = args.mqtt_host
    if args.mqtt_port:
        config.MQTT_PORT = args.mqtt_port
    if args.log_level:
        config.LOG_LEVEL = args.log_level


def signal_handler(signum, frame):
    global _shutdown
    logger.info(f"Received signal {signum}, shutting down...")
    _shutdown = True


def main():
    global _shutdown
    args = parse_args()
    apply_args(args)
    setup_logging(config.LOG_LEVEL)

    logger.info("=" * 60)
    logger.info("  OCPP-MQTT Bridge Service starting")
    logger.info(f"  OCPP server: ws://{config.OCPP_HOST}:{config.OCPP_PORT}")
    logger.info(f"  MQTT broker: {config.MQTT_HOST}:{config.MQTT_PORT}")
    logger.info("=" * 60)

    # --- Create components ---

    # MQTT client (created first so we can wire the publish callback)
    mqtt = OcppMqttClient()

    # OCPP server — publishes events via the MQTT client
    ocpp = OcppServer(publish_callback=mqtt.on_ocpp_callback)

    # Wire MQTT commands → OCPP server
    mqtt._command_callback = ocpp.dispatch_command

    # Give MQTT client a reference to the OCPP server for bridge status
    mqtt._ocpp_server = ocpp

    # --- Register signal handlers for graceful shutdown ---
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # --- Start services ---
    try:
        mqtt.start()
        logger.info("MQTT client started.")
    except Exception as e:
        logger.error(f"Failed to start MQTT client: {e}")
        logger.warning("Continuing without MQTT — OCPP server will still run.")

    ocpp.start()
    logger.info("OCPP server started.")
    logger.info("Bridge is running. Press Ctrl+C to stop.")

    # --- Main loop (keeps the process alive) ---
    try:
        while not _shutdown:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    # --- Shutdown ---
    logger.info("Shutting down...")
    ocpp.stop()
    mqtt.stop()
    logger.info("OCPP-MQTT Bridge stopped.")


if __name__ == "__main__":
    main()
