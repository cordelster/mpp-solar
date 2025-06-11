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
        self._isConnected = False

        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)


    def set(self, key, value):
        setattr(self, key, value)
        
    def update(self, key, value):
        if value is not None:
            setattr(self, key, value)

    def on_connect(self, client, userdata, flags, rc):
        log.info(f"[MQTT] Connected to broker {self.broker}:{self.port} with result code {rc}")
        # 0: Connection successful
        # 1: Connection refused - incorrect protocol version
        # 2: Connection refused - invalid client identifier
        # 3: Connection refused - server unavailable
        # 4: Connection refused - bad username or password
        # 5: Connection refused - not authorised
        # 6-255: Currently unused.
        connection_result = [
            "Connection successful",
            "Connection refused - incorrect protocol version",
            "Connection refused - invalid client identifier",
            "Connection refused - server unavailable",
            "Connection refused - bad username or password",
            "Connection refused - not authorised",
        ]
        log.debug(f"MqttBroker connection returned result: {rc} {connection_result[rc]}")
        for topic in self.command_handlers:
            self.client.subscribe(topic)
            log.info(f"[MQTT] Subscribed to: {topic}")
        if rc == 0:
            self._isConnected = True
            return
        self._isConnected = False

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

    def publishMultiple(self, data):
        """
        Publishes multiple messages to the MQTT broker.
        Expects a list of dictionaries, where each dictionary has a 'topic', 'payload', and optionally 'retain'.
        """
        if not self.client.is_connected():
            log.error("[MQTT] Cannot publish multiple, client not connected.")
            return

        for msg in data:
            topic = msg.get("topic")
            payload = msg.get("payload")
            retain = msg.get("retain", True)

            if topic and payload is not None:
                log.debug(f"[MQTT] Publishing to {topic}: {payload}")
                self.client.publish(topic, payload, retain=retain)
            else:
                log.warning(f"[MQTT] Skipping invalid message in multi-publish: {msg}")

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
        self._isConnected = False
        log.info("Disconnected from MQTT broker.")# mqttbrokerc.py
