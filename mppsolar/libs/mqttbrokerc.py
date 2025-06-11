import logging
import paho.mqtt.client as mqtt
from typing import Callable, Dict, Any

log = logging.getLogger(__name__)

class MqttTransport:
    # MODIFICATION: Changed __init__ to accept a config dictionary for flexibility.
    def __init__(self, config: dict = None, broker: str = "localhost", port: int = 1883, username: str = None, password: str = None):
        if config:
            self.broker = config.get("name", broker)
            self.port = int(config.get("port", port))
            self.username = config.get("user", username)
            self.password = config.get("pass", password)
        else:
            self.broker = broker
            self.port = port
            self.username = username
            self.password = password

        self.client = mqtt.Client()
        self.command_handlers: Dict[str, Callable[[str], None]] = {}

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
            
    # Keep the rest of the file as-is...
    def set(self, key, value):
        setattr(self, key, value)
        
    def update(self, key, value):
        if value is not None:
            setattr(self, key, value)

    def on_connect(self, client, userdata, flags, rc):
        log.info(f"[MQTT] Connected to broker {self.broker}:{self.port} with result code {rc}")
        for topic in self.command_handlers:
            self.client.subscribe(topic)
            log.info(f"[MQTT] Subscribed to: {topic}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        log.info(f"[MQTT] Message received on topic '{topic}': {payload}")
        handler = self.command_handlers.get(topic)
        if handler:
            handler(payload)
        else:
            log.warning(f"[MQTT] No handler found for topic: {topic}")

    def register_handler(self, topic: str, handler: Callable[[str], None]):
        self.command_handlers[topic] = handler
        # If already connected, subscribe immediately
        if self.client.is_connected():
            self.client.subscribe(topic)
        log.debug(f"[MQTT] Registered handler for topic: {topic}")

    def publish(self, topic: str, payload: str, retain=False):
        self.client.publish(topic, payload, retain=retain)
        log.debug(f"[MQTT] Published to {topic}: {payload}")

    def connect(self):
        try:
            log.info(f"Connecting to MQTT broker at {self.broker}:{self.port}")
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
        except Exception as e:
            log.error(f"Failed to connect to MQTT broker: {e}")

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        log.info("Disconnected from MQTT broker.")# mqttbrokerc.py

import logging
import paho.mqtt.client as mqtt
from typing import Callable, Dict, Any

log = logging.getLogger(__name__)

class MqttTransport:
    # MODIFICATION: Changed __init__ to accept a config dictionary for flexibility.
    def __init__(self, config: dict = None, broker: str = "localhost", port: int = 1883, username: str = None, password: str = None):
        if config:
            self.broker = config.get("name", broker)
            self.port = int(config.get("port", port))
            self.username = config.get("user", username)
            self.password = config.get("pass", password)
        else:
            self.broker = broker
            self.port = port
            self.username = username
            self.password = password

        self.client = mqtt.Client()
        self.command_handlers: Dict[str, Callable[[str], None]] = {}

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
            
    # Keep the rest of the file as-is...
    def set(self, key, value):
        setattr(self, key, value)
        
    def update(self, key, value):
        if value is not None:
            setattr(self, key, value)

    def on_connect(self, client, userdata, flags, rc):
        log.info(f"[MQTT] Connected to broker {self.broker}:{self.port} with result code {rc}")
        for topic in self.command_handlers:
            self.client.subscribe(topic)
            log.info(f"[MQTT] Subscribed to: {topic}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        log.info(f"[MQTT] Message received on topic '{topic}': {payload}")
        handler = self.command_handlers.get(topic)
        if handler:
            handler(payload)
        else:
            log.warning(f"[MQTT] No handler found for topic: {topic}")

    def register_handler(self, topic: str, handler: Callable[[str], None]):
        self.command_handlers[topic] = handler
        # If already connected, subscribe immediately
        if self.client.is_connected():
            self.client.subscribe(topic)
        log.debug(f"[MQTT] Registered handler for topic: {topic}")

    def publish(self, topic: str, payload: str, retain=False):
        self.client.publish(topic, payload, retain=retain)
        log.debug(f"[MQTT] Published to {topic}: {payload}")

    def connect(self):
        try:
            log.info(f"Connecting to MQTT broker at {self.broker}:{self.port}")
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
        except Exception as e:
            log.error(f"Failed to connect to MQTT broker: {e}")

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        log.info("Disconnected from MQTT broker.")