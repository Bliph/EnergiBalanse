import json
import sys
import time
import paho.mqtt.client as mqtt_client
from log_handler import create_logger

###################################################################
#
#
class MQTTClient:
    def __init__(self, client_id, host, port, username, password, root_topic, keepalive, log_dir, log_level='DEBUG'):
        self.client_id = client_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.root_topic = root_topic
        self.keepalive = keepalive
        self.logger = create_logger(name='mqtt_client', level=log_level, log_dir=log_dir)
        self.client = mqtt_client.Client()

        self.client.on_message = self.on_message
        self.client.on_connect = self.on_connect

        self.client.username_pw_set(
            self.username,
            self.password)

        # Configure Last Will and Testament ("death message")
        topic = f'{self.root_topic}/{self.client_id}/$connected'
        self.logger.info('Setting LWT "death message"...')
        self.client.will_set(
            topic,
            payload="False",
            qos=0,
            retain=True)

        self.connected = False

    ###################################################################
    #
    #
    def set_input(self, input, topics):
        self.input = input
        self.topics = topics

    ###################################################################
    #
    #
    def start(self):
        self.client.connect(
            host=self.host,
            port=self.port,
            keepalive=self.keepalive)

        self.client.loop_start()

    ###################################################################
    #
    #
    def on_message(self, client, userdata, message):
        try:
            payload = json.loads(message.payload.decode('utf-8'))
        except json.JSONDecodeError:
            self.logger.warning("Invalid JSON in message payload")
            return

        new_message = {
            'topic': message.topic,
            'payload': payload,
            'timestamp': int(time.time() * 1000)
        }

        self.input(new_message)

    ###################################################################
    #
    #
    def publish(self, topic, payload):

        if self.connected:
            qos = 0
            retain = False
            # self.logger.info("Publishing message...")
            # self.logger.info(" > topic   : {}".format(topic))
            # self.logger.info(" > payload : {}".format(payload))
            # self.logger.info(" > qos     : {}".format(qos))
            # self.logger.info(" > retain  : {}".format(retain))

            result = self.client.publish(
                topic=f'{self.root_topic}/{self.client_id}/{topic}',
                payload=json.dumps(payload, allow_nan=False),
                qos=qos,
                retain=retain)

            if result.rc != 0:
                self.logger.warning("FAILED")

    ###################################################################
    #
    #
    def on_connect(self, client, userdata, flags, rc):

        if rc == 0:
            self.connected = True
            self.logger.info("Connected to MQTT broker, rc={}".format(rc))

            # Last Will and Testament ("birth message")
            topic = f'{self.root_topic}/{self.client_id}/$connected'
            payload = 'True'
            qos = 0
            retain = True

            result = self.client.publish(
                topic=topic,
                payload=payload,
                qos=qos,
                retain=retain)
            if result.rc != 0:
                self.logger.warning("FAILED")
        else:
            self.logger.warning("Connection failed, rc={}".format(rc))

        if self.connected:

            # Subscribe
            for topic in self.topics:
                qos = 0

                (result, _) = self.client.subscribe(
                    topic=topic,
                    qos=qos)
                if result != mqtt_client.MQTT_ERR_SUCCESS:
                    self.logger.warning("FAILED")
