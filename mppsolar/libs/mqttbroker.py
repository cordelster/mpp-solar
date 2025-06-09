#!/usr/bin/python3
"""
Integrated MQTT command handler
"""

import paho.mqtt.client as mqtt
import json
import logging
import re
import time
import threading
from typing import Dict, List, Optional, Callable

class DeviceCommandHandler:
    """Handles MQTT commands for a specific device"""
    
    def __init__(self, device, mqtt_broker, allowed_commands: str = "", device_name: str = ""):
        self.device = device
        self.mqtt_broker = mqtt_broker
        self.device_name = device_name or device._name
        self.allowed_commands = []
        self.command_regex_patterns = []
        self.mqtt_client = None
        self.logger = logging.getLogger(f"{__name__}.{self.device_name}")
        
        # Topics - use device name to avoid conflicts
        self.command_topic = f"mpp-solar/{self.device_name}/commands"
        self.response_topic = f"mpp-solar/{self.device_name}/responses"
        self.status_topic = f"mpp-solar/{self.device_name}/status"
        
        self.parse_allowed_commands(allowed_commands)
        self.setup_mqtt()
    
    def parse_allowed_commands(self, commands_str: str):
        """Parse comma-separated allowed commands and create regex patterns"""
        if not commands_str:
            self.logger.info(f"No MQTT commands configured for device {self.device_name}")
            return
        
        # Split by comma and clean up whitespace
        commands = [cmd.strip() for cmd in commands_str.split(',')]
        self.allowed_commands = commands
        
        # Convert each command pattern to regex
        self.command_regex_patterns = []
        for cmd in commands:
            try:
                # Convert to proper regex pattern
                # Handle brackets notation like POP0[0-2] -> POP0[0-2]
                # Handle asterisk notation like MCHGC[0-5][0-9]* -> MCHGC[0-5][0-9]*
                regex_pattern = cmd.replace('*', '.*')  # Convert * to .*
                
                # Compile to test validity
                compiled_pattern = re.compile(f"^{regex_pattern}$")
                self.command_regex_patterns.append(compiled_pattern)
                self.logger.info(f"Device {self.device_name}: Added command pattern: {cmd} -> {regex_pattern}")
                
            except re.error as e:
                self.logger.error(f"Device {self.device_name}: Invalid regex pattern for command '{cmd}': {e}")
    
    def is_command_allowed(self, command: str) -> bool:
        """Check if a command matches any of the allowed patterns"""
        if not self.command_regex_patterns:
            return False
            
        for pattern in self.command_regex_patterns:
            if pattern.match(command):
                return True
        return False
    
    def setup_mqtt(self):
        """Setup MQTT client for this device"""
        if not self.mqtt_broker or not self.mqtt_broker.config.get("name"):
            self.logger.warning(f"Device {self.device_name}: No MQTT broker configured")
            return
        
        if not self.command_regex_patterns:
            self.logger.info(f"Device {self.device_name}: No command patterns, skipping MQTT command setup")
            return
        
        try:
            self.mqtt_client = mqtt.Client(client_id=f"mpp-solar-{self.device_name}")
            
            # Set credentials if provided
            if self.mqtt_broker.config.get("username") and self.mqtt_broker.config.get("password"):
                self.mqtt_client.username_pw_set(
                    self.mqtt_broker.config["username"], 
                    self.mqtt_broker.config["password"]
                )
            
            self.mqtt_client.on_connect = self.on_connect
            self.mqtt_client.on_message = self.on_message
            self.mqtt_client.on_disconnect = self.on_disconnect
            
            # Connect to broker
            broker_host = self.mqtt_broker.config["name"]
            broker_port = self.mqtt_broker.config.get("port", 1883)
            
            self.logger.info(f"Device {self.device_name}: Connecting to MQTT broker {broker_host}:{broker_port}")
            self.mqtt_client.connect(broker_host, broker_port, 60)
            
            # Start the network loop in a separate thread
            self.mqtt_client.loop_start()
            
        except Exception as e:
            self.logger.error(f"Device {self.device_name}: Failed to setup MQTT: {e}")
            self.mqtt_client = None
    
    def on_connect(self, client, userdata, flags, rc):
        """Callback for when the client receives a CONNACK response from the server"""
        if rc == 0:
            self.logger.info(f"Device {self.device_name}: Connected to MQTT broker successfully")
            # Subscribe to command topic
            client.subscribe(self.command_topic)
            self.logger.info(f"Device {self.device_name}: Subscribed to command topic: {self.command_topic}")
            
            # Publish device status
            self.publish_status("online", f"Device {self.device_name} ready for commands")
            
        else:
            self.logger.error(f"Device {self.device_name}: Failed to connect to MQTT broker, return code {rc}")
    
    def on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects"""
        self.logger.warning(f"Device {self.device_name}: Disconnected from MQTT broker")
    
    def on_message(self, client, userdata, msg):
        """Callback for when a PUBLISH message is received from the server"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            
            self.logger.info(f"Device {self.device_name}: Received message on topic '{topic}': {payload}")
            
            if topic == self.command_topic:
                self.handle_command(payload)
                
        except Exception as e:
            self.logger.error(f"Device {self.device_name}: Error processing received message: {e}")
    
    def handle_command(self, command_payload: str):
        """Process received command"""
        try:
            # Try to parse as JSON first
            try:
                command_data = json.loads(command_payload)
                command = command_data.get('command', '')
                request_id = command_data.get('id', None)
            except json.JSONDecodeError:
                # Treat as plain text command
                command = command_payload.strip()
                request_id = None
            
            self.logger.info(f"Device {self.device_name}: Processing command: {command}")
            
            # Check if command is allowed
            if not self.is_command_allowed(command):
                error_msg = f"Command '{command}' not allowed for device {self.device_name}"
                self.logger.warning(error_msg)
                self.send_command_response(error_msg, "error", request_id)
                return
            
            # Execute the command using the device
            try:
                self.logger.info(f"Device {self.device_name}: Executing command: {command}")
                result = self.device.run_command(command=command)
                
                # Convert result to string if it's a dict
                if isinstance(result, dict):
                    result_str = json.dumps(result, indent=2)
                else:
                    result_str = str(result)
                
                self.send_command_response(result_str, "success", request_id)
                self.logger.info(f"Device {self.device_name}: Command '{command}' executed successfully")
                
            except Exception as e:
                error_msg = f"Command execution failed: {str(e)}"
                self.logger.error(f"Device {self.device_name}: {error_msg}")
                self.send_command_response(error_msg, "error", request_id)
                
        except Exception as e:
            self.logger.error(f"Device {self.device_name}: Error handling command: {e}")
            self.send_command_response(f"Command processing error: {str(e)}", "error")
    
    def send_command_response(self, result: str, status: str = "success", request_id: str = None):
        """Send command execution result back via MQTT"""
        if not self.mqtt_client:
            return
        
        response = {
            "device": self.device_name,
            "status": status,
            "result": result,
            "timestamp": time.time()
        }
        
        if request_id:
            response["id"] = request_id
        
        try:
            self.mqtt_client.publish(self.response_topic, json.dumps(response, indent=2))
            self.logger.info(f"Device {self.device_name}: Sent command response: {status}")
        except Exception as e:
            self.logger.error(f"Device {self.device_name}: Failed to send command response: {e}")
    
    def publish_status(self, status: str, message: str = ""):
        """Publish device status"""
        if not self.mqtt_client:
            return
        
        status_data = {
            "device": self.device_name,
            "status": status,
            "message": message,
            "timestamp": time.time(),
            "allowed_commands": self.allowed_commands
        }
        
        try:
            self.mqtt_client.publish(self.status_topic, json.dumps(status_data, indent=2))
        except Exception as e:
            self.logger.error(f"Device {self.device_name}: Failed to publish status: {e}")
    
    def disconnect(self):
        """Disconnect from MQTT broker"""
        if self.mqtt_client:
            self.publish_status("offline", f"Device {self.device_name} going offline")
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            self.logger.info(f"Device {self.device_name}: Disconnected from MQTT broker")


class MQTTCommandManager:
    """Manages MQTT command handlers for multiple devices"""
    
    def __init__(self):
        self.command_handlers: Dict[str, DeviceCommandHandler] = {}
        self.logger = logging.getLogger(f"{__name__}.Manager")
    
    def add_device(self, device, mqtt_broker, mqtt_cmds: str = "", device_name: str = ""):
        """Add a device for MQTT command handling"""
        handler_name = device_name or device._name
        
        if handler_name in self.command_handlers:
            self.logger.warning(f"Device {handler_name} already has a command handler")
            return
        
        handler = DeviceCommandHandler(device, mqtt_broker, mqtt_cmds, handler_name)
        self.command_handlers[handler_name] = handler
        
        self.logger.info(f"Added MQTT command handler for device: {handler_name}")
    
    def get_device_info(self) -> Dict:
        """Get information about all managed devices"""
        info = {}
        for name, handler in self.command_handlers.items():
            info[name] = {
                "allowed_commands": handler.allowed_commands,
                "command_topic": handler.command_topic,
                "response_topic": handler.response_topic,
                "status_topic": handler.status_topic,
                "mqtt_connected": handler.mqtt_client is not None
            }
        return info
    
    def disconnect_all(self):
        """Disconnect all device handlers"""
        for handler in self.command_handlers.values():
            handler.disconnect()
        self.command_handlers.clear()
        self.logger.info("Disconnected all MQTT command handlers")


# Global instance to be used by the main application
mqtt_command_manager = MQTTCommandManager()


def setup_device_mqtt_commands(device, mqtt_broker, mqtt_cmds: str = "", device_name: str = ""):
    """
    Setup MQTT command handling for a device
    This function should be called from the main application after device creation
    """
    global mqtt_command_manager
    
    if mqtt_cmds:
        mqtt_command_manager.add_device(device, mqtt_broker, mqtt_cmds, device_name)
    else:
        logging.getLogger(__name__).info(f"No MQTT commands configured for device {device_name or device._name}")


def cleanup_mqtt_commands():
    """
    Cleanup all MQTT command handlers
    This should be called when the application shuts down
    """
    global mqtt_command_manager
    mqtt_command_manager.disconnect_all()


def get_mqtt_command_info():
    """Get information about all MQTT command handlers"""
    global mqtt_command_manager
    return mqtt_command_manager.get_device_info()

