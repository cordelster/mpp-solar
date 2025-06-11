import paho.mqtt.client as mqtt
import json
import logging
import re
import time
from typing import Dict, List

# This global variable will hold our single manager instance.
mqtt_command_manager = None

log = logging.getLogger(__name__)

class DeviceCommandHandler:
    """Handles MQTT commands for a single device."""
    def __init__(self, device, mqtt_transport, allowed_commands: str, device_name: str):
        self.device = device
        self.device_name = device_name
        self.mqtt_transport = mqtt_transport
        self.logger = logging.getLogger(f"{__name__}.{self.device_name}")
        
        self.command_topic = f"mpp-solar/{self.device_name}/cmd"
        self.response_topic = f"mpp-solar/{self.device_name}/cmd_response"
        
        self.allowed_patterns = self._parse_allowed_commands(allowed_commands)

        if self.allowed_patterns:
            self.logger.info(f"Registering MQTT handler for command topic: {self.command_topic}")
            self.mqtt_transport.register_handler(self.command_topic, self.handle_command)
        else:
            self.logger.info(f"No allowed MQTT commands for {self.device_name}, handler not registered.")

    def _parse_allowed_commands(self, commands_str: str) -> List[re.Pattern]:
        patterns = []
        if not commands_str:
            return patterns
        commands = [cmd.strip() for cmd in commands_str.split(',')]
        for cmd in commands:
            try:
                # Convert wildcard to regex and ensure it matches the full command
                regex_pattern = cmd.replace('*', '.*')
                patterns.append(re.compile(f"^{regex_pattern}$"))
                self.logger.info(f"Added allowed command pattern: '{cmd}'")
            except re.error as e:
                self.logger.error(f"Invalid regex for command '{cmd}': {e}")
        return patterns

    def is_command_allowed(self, command: str) -> bool:
        if not self.allowed_patterns:
            return False
        for pattern in self.allowed_patterns:
            if pattern.match(command):
                return True
        return False

    def handle_command(self, payload: str):
        command = payload.strip()
        self.logger.info(f"Received command: '{command}'")

        if not self.is_command_allowed(command):
            error_msg = f"Command '{command}' is not in the allowed list for {self.device_name}."
            self.logger.warning(error_msg)
            self.send_response(result=error_msg, status="error")
            return

        try:
            self.logger.info(f"Executing command: '{command}'")
            result = self.device.run_command(command=command)
            
            # Ensure result is JSON serializable
            if isinstance(result, dict):
                 result_payload = json.dumps(result, indent=2)
            else:
                 result_payload = str(result)
            
            self.send_response(result=result_payload, status="success")
            self.logger.info(f"Successfully executed command '{command}'.")

        except Exception as e:
            error_msg = f"Error executing command '{command}': {e}"
            self.logger.error(error_msg, exc_info=True)
            self.send_response(result=error_msg, status="error")

    def send_response(self, result: str, status: str):
        response = {
            "device": self.device_name,
            "status": status,
            "result": result,
            "timestamp": time.time()
        }
        self.mqtt_transport.publish(self.response_topic, json.dumps(response, indent=2))
        self.logger.debug(f"Published response to {self.response_topic}")


class MQTTCommandManager:
    """Manages MQTT command handlers for multiple devices using a single transport."""
    def __init__(self, mqtt_transport):
        self.mqtt_transport = mqtt_transport
        self.command_handlers: Dict[str, DeviceCommandHandler] = {}
        self.logger = logging.getLogger(f"{__name__}.Manager")

    def add_device(self, device, allowed_cmds: str, device_name: str):
        handler_name = device_name or device._name
        if handler_name in self.command_handlers:
            self.logger.warning(f"Handler for device '{handler_name}' already exists.")
            return

        self.logger.info(f"Adding MQTT command handler for device: {handler_name}")
        handler = DeviceCommandHandler(device, self.mqtt_transport, allowed_cmds, handler_name)
        self.command_handlers[handler_name] = handler

    def get_device_info(self) -> Dict:
        info = {}
        for name, handler in self.command_handlers.items():
            info[name] = {
                "command_topic": handler.command_topic,
                "response_topic": handler.response_topic,
                "allowed_commands": [p.pattern for p in handler.allowed_patterns]
            }
        return info

    def connect(self):
        self.logger.info("Starting MQTT transport for command manager.")
        self.mqtt_transport.connect()

    def disconnect_all(self):
        if self.mqtt_transport and self.mqtt_transport.client.is_connected():
            self.logger.info("Disconnecting MQTT transport.")
            self.mqtt_transport.disconnect()
        self.command_handlers.clear()


def get_manager(mqtt_transport=None):
    """Singleton pattern to get or create the MQTTCommandManager."""
    global mqtt_command_manager
    if mqtt_command_manager is None and mqtt_transport is not None:
        mqtt_command_manager = MQTTCommandManager(mqtt_transport)
    return mqtt_command_manager


def setup_device_mqtt_commands(device, allowed_cmds: str, device_name: str):
    manager = get_manager()
    if manager and allowed_cmds:
        manager.add_device(device, allowed_cmds, device_name)
    elif not allowed_cmds:
        log.info(f"No MQTT commands configured for device {device_name or device._name}")
    else:
        log.error("MQTTCommandManager not initialized. Cannot set up device.")


def cleanup_mqtt_commands():
    manager = get_manager()
    if manager:
        log.info("Cleaning up MQTT command handlers.")
        manager.disconnect_all()


def get_mqtt_command_info():
    manager = get_manager()
    if manager:
        return manager.get_device_info()
    return {}

__all__ = [
    "get_manager",
    "setup_device_mqtt_commands",
    "get_mqtt_command_info",
    "cleanup_mqtt_commands",
]