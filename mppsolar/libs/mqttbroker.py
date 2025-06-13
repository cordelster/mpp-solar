import paho.mqtt.client as mqtt
import json
import logging
import re
import time
import threading
from typing import Dict, List, Callable, Optional, Any
from queue import Queue, Empty
import uuid

log = logging.getLogger(__name__)

# Module-level singleton instances
_output_manager_instance = None
_command_manager_instance = None
_manager_lock = threading.Lock()


class MQTTOutputManager:
    """
    Handles MQTT output publishing with automatic reconnection and thread safety.
    Purpose: Forward output data to MQTT broker (QoS 0, no retention by default)
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.broker = config.get("name", "localhost")
        self.port = int(config.get("port", 1883))
        self.username = config.get("user")
        self.password = config.get("pass")
        self.results_topic = config.get("results_topic", "mpp-solar")
        
        self.client = None
        self._connected = False
        self._connection_lock = threading.Lock()
        self._reconnect_interval = 5
        self._max_reconnect_attempts = 10
        self._reconnect_attempts = 0
        
        self.logger = logging.getLogger(f"{__name__}.OutputManager")
        
        # Message queue for when disconnected (limited size to prevent memory issues)
        self._message_queue = Queue(maxsize=1000)
        self._setup_client()
    
    def _setup_client(self):
        """Initialize MQTT client with callbacks"""
        self.client = mqtt.Client(client_id=f"mpp-solar-output-{uuid.uuid4().hex[:8]}")
        
        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
        
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback for successful connection"""
        with self._connection_lock:
            if rc == 0:
                self._connected = True
                self._reconnect_attempts = 0
                self.logger.info(f"Connected to MQTT broker {self.broker}:{self.port}")
                
                # Process queued messages
                self._process_queued_messages()
            else:
                self._connected = False
                self.logger.error(f"Failed to connect to MQTT broker: {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback for disconnection"""
        with self._connection_lock:
            self._connected = False
            if rc != 0:
                self.logger.warning(f"Unexpected disconnection from MQTT broker: {rc}")
    
    def _on_publish(self, client, userdata, mid):
        """Callback for successful publish"""
        self.logger.debug(f"Message published successfully: {mid}")
    
    def _process_queued_messages(self):
        """Process messages that were queued while disconnected"""
        processed = 0
        while not self._message_queue.empty() and processed < 100:  # Limit batch size
            try:
                topic, payload, retain = self._message_queue.get_nowait()
                self.client.publish(topic, payload, qos=0, retain=retain)
                processed += 1
            except Empty:
                break
        
        if processed > 0:
            self.logger.info(f"Processed {processed} queued messages")
    
    def connect(self):
        """Connect to MQTT broker with automatic reconnection"""
        try:
            self.logger.info(f"Connecting to MQTT broker at {self.broker}:{self.port}")
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to MQTT broker: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from MQTT broker"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            with self._connection_lock:
                self._connected = False
            self.logger.info("Disconnected from MQTT broker")
    
    def is_connected(self):
        """Check if connected to broker"""
        with self._connection_lock:
            return self._connected
    
    def publish(self, topic: str, payload: str, retain: bool = False):
        """
        Publish single message with automatic queuing if disconnected
        
        Args:
            topic: MQTT topic
            payload: Message payload
            retain: Whether to retain message on broker
        """
        if self.is_connected():
            try:
                result = self.client.publish(topic, payload, qos=0, retain=retain)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    self.logger.warning(f"Failed to publish to {topic}: {result.rc}")
                    self._queue_message(topic, payload, retain)
                else:
                    self.logger.debug(f"Published to {topic}: {payload[:100]}...")
            except Exception as e:
                self.logger.error(f"Error publishing to {topic}: {e}")
                self._queue_message(topic, payload, retain)
        else:
            self._queue_message(topic, payload, retain)
            self._attempt_reconnect()
    
    def publishMultiple(self, data: List[Dict[str, Any]]):
        """
        Publish multiple messages (legacy compatibility)
        
        Args:
            data: List of dicts with 'topic', 'payload', and optional 'retain'
        """
        if not data:
            return
        
        for msg in data:
            topic = msg.get("topic")
            payload = msg.get("payload")
            retain = msg.get("retain", False)
            
            if topic and payload is not None:
                self.publish(topic, payload, retain)
            else:
                self.logger.warning(f"Skipping invalid message: {msg}")
    
    def _queue_message(self, topic: str, payload: str, retain: bool):
        """Queue message for later delivery"""
        try:
            self._message_queue.put_nowait((topic, payload, retain))
            self.logger.debug(f"Queued message for {topic}")
        except:
            self.logger.warning(f"Message queue full, dropping message for {topic}")
    
    def _attempt_reconnect(self):
        """Attempt to reconnect if not already connected"""
        if not self.is_connected() and self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1
            self.logger.info(f"Attempting reconnection {self._reconnect_attempts}/{self._max_reconnect_attempts}")
            threading.Timer(self._reconnect_interval, self.connect).start()
    
    def set(self, key: str, value: Any):
        """Legacy compatibility method"""
        setattr(self, key, value)
    
    def update(self, key: str, value: Any):
        """Legacy compatibility method"""
        if value is not None:
            setattr(self, key, value)


class MQTTCommandManager:
    """
    Handles MQTT command subscription and response publishing.
    Purpose: Listen for commands and execute them (QoS 1, with retention for responses)
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.broker = config.get("name", "localhost")
        self.port = int(config.get("port", 1883))
        self.username = config.get("user")
        self.password = config.get("pass")
        
        self.client = None
        self._connected = False
        self._connection_lock = threading.Lock()
        
        self.command_handlers: Dict[str, 'DeviceCommandHandler'] = {}
        self.logger = logging.getLogger(f"{__name__}.CommandManager")
        
        # Command execution timeout
        self._command_timeout = 30  # seconds
        
        self._setup_client()
    
    def _setup_client(self):
        """Initialize MQTT client for command handling"""
        client_id = f"mpp-solar-cmd-{uuid.uuid4().hex[:8]}"
        
        # Use clean_session=False for persistent subscriptions if username/password provided
        clean_session = not (self.username and self.password)
        self.client = mqtt.Client(client_id=client_id, clean_session=clean_session)
        
        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
        
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback for connection"""
        with self._connection_lock:
            if rc == 0:
                self._connected = True
                self.logger.info(f"Command manager connected to MQTT broker {self.broker}:{self.port}")
                
                # Re-subscribe to all command topics
                for handler in self.command_handlers.values():
                    self._subscribe_to_handler(handler)
            else:
                self._connected = False
                self.logger.error(f"Command manager failed to connect: {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback for disconnection"""
        with self._connection_lock:
            self._connected = False
            if rc != 0:
                self.logger.warning(f"Command manager unexpected disconnection: {rc}")
    
    def _on_message(self, client, userdata, msg):
        """Handle incoming command messages"""
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8")
            self.logger.info(f"Received command on {topic}: {payload}")
            
            # Find matching handler
            for handler in self.command_handlers.values():
                if handler.matches_topic(topic):
                    threading.Thread(
                        target=handler.handle_command_with_timeout,
                        args=(payload, self._command_timeout),
                        daemon=True
                    ).start()
                    break
            else:
                self.logger.warning(f"No handler found for topic: {topic}")
                
        except Exception as e:
            self.logger.error(f"Error processing message on {topic}: {e}")
    
    def _subscribe_to_handler(self, handler: 'DeviceCommandHandler'):
        """Subscribe to a handler's command topic"""
        if self.is_connected():
            try:
                result = self.client.subscribe(handler.command_topic, qos=1)
                if result[0] == mqtt.MQTT_ERR_SUCCESS:
                    self.logger.info(f"Subscribed to: {handler.command_topic}")
                else:
                    self.logger.error(f"Failed to subscribe to {handler.command_topic}: {result[0]}")
            except Exception as e:
                self.logger.error(f"Error subscribing to {handler.command_topic}: {e}")
    
    def connect(self):
        """Connect to MQTT broker"""
        try:
            self.logger.info(f"Connecting command manager to {self.broker}:{self.port}")
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect command manager: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from MQTT broker"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            with self._connection_lock:
                self._connected = False
            self.logger.info("Command manager disconnected")
    
    def is_connected(self):
        """Check if connected"""
        with self._connection_lock:
            return self._connected
    
    def add_device(self, device, allowed_cmds: str, device_name: str):
        """Add a device for command handling"""
        handler_name = device_name or getattr(device, '_name', 'unknown')
        
        if handler_name in self.command_handlers:
            self.logger.warning(f"Handler for device '{handler_name}' already exists")
            return
        
        self.logger.info(f"Adding command handler for device: {handler_name}")
        handler = DeviceCommandHandler(device, self, allowed_cmds, handler_name)
        self.command_handlers[handler_name] = handler
        
        # Subscribe if already connected
        if self.is_connected():
            self._subscribe_to_handler(handler)
    
    def publish_response(self, topic: str, payload: str):
        """Publish command response with QoS 1 and retention"""
        if self.is_connected():
            try:
                result = self.client.publish(topic, payload, qos=1, retain=True)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    self.logger.debug(f"Published response to {topic}")
                else:
                    self.logger.error(f"Failed to publish response to {topic}: {result.rc}")
            except Exception as e:
                self.logger.error(f"Error publishing response to {topic}: {e}")
        else:
            self.logger.error("Cannot publish response, not connected to broker")
    
    def get_device_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about registered devices"""
        info = {}
        for name, handler in self.command_handlers.items():
            info[name] = {
                "command_topic": handler.command_topic,
                "response_topic": handler.response_topic,
                "allowed_commands": [p.pattern for p in handler.allowed_patterns]
            }
        return info


class DeviceCommandHandler:
    """Handles MQTT commands for a single device with timeout protection"""
    
    def __init__(self, device, command_manager: MQTTCommandManager, allowed_commands: str, device_name: str):
        self.device = device
        self.device_name = device_name
        self.command_manager = command_manager
        self.logger = logging.getLogger(f"{__name__}.{self.device_name}")
        
        # Support MQTT wildcards in device names
        self.command_topic = f"mpp-solar/{self.device_name}/cmd"
        self.response_topic = f"mpp-solar/{self.device_name}/cmd_response"
        
        self.allowed_patterns = self._parse_allowed_commands(allowed_commands)
        
        if not self.allowed_patterns:
            self.logger.info(f"No allowed commands for {self.device_name}")
    
    def _parse_allowed_commands(self, commands_str: str) -> List[re.Pattern]:
        """Parse allowed commands into regex patterns"""
        patterns = []
        if not commands_str:
            return patterns
            
        commands = [cmd.strip() for cmd in commands_str.split(',')]
        for cmd in commands:
            try:
                # Convert wildcard to regex
                regex_pattern = cmd.replace('*', '.*')
                patterns.append(re.compile(f"^{regex_pattern}$"))
                self.logger.info(f"Added allowed command pattern: '{cmd}'")
            except re.error as e:
                self.logger.error(f"Invalid regex for command '{cmd}': {e}")
        
        return patterns
    
    def matches_topic(self, topic: str) -> bool:
        """Check if topic matches this handler (supports MQTT wildcards)"""
        # Simple implementation - could be enhanced for full MQTT wildcard support
        return topic == self.command_topic
    
    def is_command_allowed(self, command: str) -> bool:
        """Check if command is allowed"""
        if not self.allowed_patterns:
            return False
        
        for pattern in self.allowed_patterns:
            if pattern.match(command):
                return True
        return False
    
    def handle_command_with_timeout(self, payload: str, timeout: int):
        """Handle command with timeout protection"""
        command = payload.strip()
        
        if not self.is_command_allowed(command):
            error_msg = f"Command '{command}' not allowed for {self.device_name}"
            self.logger.warning(error_msg)
            self._send_response(error_msg, "error")
            return
        
        # Execute command with timeout
        result_queue = Queue()
        
        def execute_command():
            try:
                result = self.device.run_command(command=command)
                result_queue.put(("success", result))
            except Exception as e:
                result_queue.put(("error", str(e)))
        
        thread = threading.Thread(target=execute_command, daemon=True)
        thread.start()
        
        try:
            status, result = result_queue.get(timeout=timeout)
            
            if status == "success":
                # Handle JSON vs plaintext
                if isinstance(result, dict):
                    result_payload = json.dumps(result, indent=2)
                else:
                    result_payload = str(result)
                
                self._send_response(result_payload, "success")
                self.logger.info(f"Successfully executed: {command}")
            else:
                self._send_response(result, "error")
                self.logger.error(f"Command failed: {command} - {result}")
                
        except Empty:
            error_msg = f"Command '{command}' timed out after {timeout} seconds"
            self.logger.error(error_msg)
            self._send_response(error_msg, "timeout")
    
    def _send_response(self, result: str, status: str):
        """Send response back via MQTT"""
        response = {
            "device": self.device_name,
            "status": status,
            "result": result,
            "timestamp": time.time()
        }
        
        response_payload = json.dumps(response, indent=2)
        self.command_manager.publish_response(self.response_topic, response_payload)


# Singleton management functions
def get_output_manager(config: dict = None) -> Optional[MQTTOutputManager]:
    """Get or create MQTT output manager singleton"""
    global _output_manager_instance
    
    with _manager_lock:
        if _output_manager_instance is None and config is not None:
            _output_manager_instance = MQTTOutputManager(config)
        return _output_manager_instance


def get_command_manager(config: dict = None) -> Optional[MQTTCommandManager]:
    """Get or create MQTT command manager singleton"""
    global _command_manager_instance
    
    with _manager_lock:
        if _command_manager_instance is None and config is not None:
            _command_manager_instance = MQTTCommandManager(config)
        return _command_manager_instance


def reset_managers():
    """Reset singleton instances (for testing/cleanup)"""
    global _output_manager_instance, _command_manager_instance
    
    with _manager_lock:
        if _output_manager_instance:
            _output_manager_instance.disconnect()
            _output_manager_instance = None
        
        if _command_manager_instance:
            _command_manager_instance.disconnect()
            _command_manager_instance = None


# High-level setup functions
def setup_mqtt_output_manager(args, prog_name: str) -> Optional[MQTTOutputManager]:
    """
    Setup MQTT output manager from arguments
    CLI arguments take precedence over config file
    """
    # Check if MQTT output is requested
    outputs = getattr(args, 'output', '').split(',')
    if 'mqtt' not in outputs:
        return None
    
    # Build config from args (CLI takes precedence)
    config = {
        "name": getattr(args, 'mqttbroker', 'localhost'),
        "port": getattr(args, 'mqttport', 1883),
        "user": getattr(args, 'mqttuser', None),
        "pass": getattr(args, 'mqttpass', None),
        "results_topic": getattr(args, 'mqtttopic', None) or prog_name
    }
    
    # Validate required fields
    if not config["name"]:
        log.warning("MQTT output requested but no broker specified")
        return None
    
    output_manager = get_output_manager(config)
    if output_manager:
        log.info("MQTT output manager configured")
        if not getattr(args, 'daemon', False):  # Connect immediately for non-daemon runs
            output_manager.connect()
    
    return output_manager


def setup_mqtt_command_manager(config: dict) -> Optional[MQTTCommandManager]:
    """Setup MQTT command manager from config"""
    # Validate required fields for command manager
    required_fields = ["name", "user", "pass"]
    if not all(config.get(field) for field in required_fields):
        log.debug("MQTT command manager not configured (missing broker, user, or password)")
        return None
    
    command_manager = get_command_manager(config)
    if command_manager:
        log.info("MQTT command manager configured")
    
    return command_manager


def setup_device_mqtt_commands(device, allowed_cmds: str, device_name: str):
    """Setup MQTT commands for a device"""
    command_manager = get_command_manager()
    if command_manager and allowed_cmds:
        command_manager.add_device(device, allowed_cmds, device_name)
    elif not allowed_cmds:
        log.debug(f"No MQTT commands configured for device {device_name}")
    else:
        log.warning("MQTT command manager not initialized, cannot setup device commands")


def cleanup_mqtt_managers():
    """Cleanup all MQTT managers"""
    log.info("Cleaning up MQTT managers")
    reset_managers()


def get_mqtt_command_info() -> Dict[str, Dict[str, Any]]:
    """Get information about configured MQTT commands"""
    command_manager = get_command_manager()
    if command_manager:
        return command_manager.get_device_info()
    return {}


# Legacy compatibility functions
def get_mqtt_command_info():
    """Legacy compatibility - get command info"""
    return get_mqtt_command_info()


def cleanup_mqtt_commands():
    """Legacy compatibility - cleanup commands"""
    cleanup_mqtt_managers()


# Backward compatibility exports
__all__ = [
    "MQTTOutputManager",
    "MQTTCommandManager", 
    "get_output_manager",
    "get_command_manager",
    "setup_mqtt_output_manager",
    "setup_mqtt_command_manager",
    "setup_device_mqtt_commands",
    "cleanup_mqtt_managers",
    "get_mqtt_command_info",
    # Legacy compatibility
    "cleanup_mqtt_commands",
]