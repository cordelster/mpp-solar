# !/usr/bin/python3
import os
import logging
import time
import sys
import atexit
from argparse import ArgumentParser
from platform import python_version

from mppsolar.version import __version__  # noqa: F401

from mppsolar.helpers import get_device_class

from mppsolar.daemon.pyinstaller_runtime import (
    spawn_pyinstaller_subprocess,
    is_pyinstaller_bundle,
    has_been_spawned,
    is_spawned_pyinstaller_process,
  )
from mppsolar.daemon import get_daemon, detect_daemon_type
from mppsolar.daemon import DaemonType
from mppsolar.daemon.daemon import (
    setup_daemon_logging,
    daemonize,
)
from mppsolar.libs.mqttbrokerc import MqttTransport
from mppsolar.libs.mqttbroker import (
    get_manager,
    setup_device_mqtt_commands,
    get_mqtt_command_info,
    cleanup_mqtt_commands,
)
from mppsolar.outputs import get_outputs, list_outputs
from mppsolar.protocols import list_protocols

# Set-up logger
log = logging.getLogger("")
FORMAT = "%(asctime)-15s:%(levelname)s:%(module)s:%(funcName)s@%(lineno)d: %(message)s"
logging.basicConfig(format=FORMAT)


def main():
    description = f"Solar Device Command Utility, version: {__version__}, python version: {python_version()}"
    parser = ArgumentParser(description=description)
    parser.add_argument(
        "-n",
        "--name",
        help="Specifies the device name - used to differentiate different devices",
        default="unnamed",
    )
    parser.add_argument(
        "-p",
        "--port",
        help="Specifies the device communications port (/dev/ttyUSB0 [default], /dev/hidraw0, test, ...)",
        default="/dev/ttyUSB0",
    )
    parser.add_argument(
        "--porttype",
        help="overrides the device communications port type",
        default=None,
    )
    parser.add_argument(
        "--dev",
        help="Device identifier for prometheus output labeling for complex installations (default: None)",
        default=None,
    )
    if parser.prog == "jkbms":
        parser.add_argument(
            "-P",
            "--protocol",
            nargs="?",
            const="help",
            help="Specifies the device command and response protocol, (default: JK04)",
            default="JK04",
        )
    else:
        parser.add_argument(
            "-P",
            "--protocol",
            nargs="?",
            const="help",
            help="Specifies the device command and response protocol, (default: PI30)",
            default="PI30",
        )
    parser.add_argument(
        "-T",
        "--tag",
        help="Override the command name and use this instead (for mqtt and influx type output processors)",
    )
    parser.add_argument(
        "-b",
        "--baud",
        type=int,
        help="Baud rate for serial communications (default: 2400)",
        default=2400,
    )
    parser.add_argument(
        "-o",
        "--output",
        nargs="?",
        help="Specifies the output processor(s) to use [comma separated if multiple] (screen [default]) leave blank to give list",
        const="help",
        default="screen",
    )
    parser.add_argument(
        "--keepcase",
        action="store_true",
        help="Do not convert the field names to lowercase",
    )
    parser.add_argument(
        "--filter",
        help="Specifies the filter to reduce the output - only those fields that match will be output (uses re.search)",
        default=None,
    )
    parser.add_argument(
        "--exclfilter",
        help="Specifies the filter to reduce the output - any fields that match will be excluded from the output (uses re.search)",
        default=None,
    )
    parser.add_argument(
        "-q",
        "--mqttbroker",
        help="Specifies the mqtt broker to publish to if using a mqtt output (localhost [default], hostname, ip.add.re.ss ...)",
        default="localhost",
    )
    parser.add_argument(
        "--mqttport",
        type=int,
        help="Specifies the mqtt broker port if needed (default: 1883)",
        default=1883,
    )
    parser.add_argument(
        "--mqtttopic",
        help="provides an override topic (or prefix) for mqtt messages (default: None)",
        default=None,
    )
    parser.add_argument(
        "--mqttuser",
        help="Specifies the username to use for authenticated mqtt broker publishing",
        default=None,
    )
    parser.add_argument(
        "--mqttpass",
        help="Specifies the password to use for authenticated mqtt broker publishing",
        default=None,
    )
    parser.add_argument(
        "--udpport",
        type=int,
        help="Specifies the UDP port if needed (default: 5555)",
        default="5555",
    )
    parser.add_argument(
        "--postgres_url",
        help="PostgresSQL connection url, example postgresql://user:password@server:5432/postgres",
    )
    parser.add_argument(
        "--mongo_url",
        help="Mongo connection url, example mongodb://user:password@ip:port/admindb",
    )
    parser.add_argument(
        "--mongo_db",
        help="Mongo db name (default: mppsolar)",
        default="mppsolar",
    )
    parser.add_argument(
        "--pushurl",
        help=(
            "Any server used to send data to (PushGateway for Prometheus, for instance), "
            "(default: http://localhost:9091/metrics/job/pushgateway)"
        ),
        default="http://localhost:9091/metrics/job/pushgateway",
    )
    parser.add_argument(
        "--prom_output_dir",
        help=(
            "Output directory where Prometheus metrics are written as .prom files"
            "(default: /var/lib/node_exporter)"
        ),
        default="/var/lib/node_exporter",
    )
    parser.add_argument(
        "-c",
        "--command",
        nargs="?",
        const="help",
        help="Command to run; or list of hash separated commands to run",
    )
    if parser.prog == "jkbms":
        parser.add_argument(
            "-C",
            "--configfile",
            nargs="?",
            help="Full location of config file (default None, /etc/jkbms/jkbms.conf if -C supplied)",
            const="/etc/jkbms/jkbms.conf",
            default=None,
        )
    else:
        parser.add_argument(
            "-C",
            "--configfile",
            nargs="?",
            help="Full location of config file (default None, /etc/mpp-solar/mpp-solar.conf if -C supplied)",
            const="/etc/mpp-solar/mpp-solar.conf",
            default=None,
        )
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--getstatus", action="store_true", help="Get Inverter Status")
    parser.add_argument("--getsettings", action="store_true", help="Get Inverter Settings")
    parser.add_argument("--getDeviceId", action="store_true", help="Generate Device ID")

    parser.add_argument("-v", "--version", action="store_true", help="Display the version")
    parser.add_argument("--getVersion", action="store_true", help="Output the software version via the supplied output")
    parser.add_argument(
        "-D",
        "--debug",
        action="store_true",
        help="Enable Debug and above (i.e. all) messages",
    )
    parser.add_argument(
        "--pidfile",
        help="Specifies the PID file location for daemon mode (default: /var/run/mpp-solar.pid, /tmp/mpp-solar.pid for PyInstaller)",
        default=None,
    )
    parser.add_argument(
        "--daemon-stop",
        action="store_true",
        help="Stop a running daemon (requires --pidfile if using non-default location)"
    )
    parser.add_argument("-I", "--info", action="store_true", help="Enable Info and above level messages")


    atexit.register(cleanup_mqtt_commands)

    args = parser.parse_args()
    prog_name = parser.prog
    if prog_name is None:
        prog_name = "mpp-solar"
    s_prog_name = prog_name.replace("-", "")
    log_file_path = "/var/log/mpp-solar.log"


    # logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    # Turn on debug if needed
    if args.debug:
        log.setLevel(logging.DEBUG)
    elif args.info:
        log.setLevel(logging.INFO)
    else:
        # set default log level
        log.setLevel(logging.WARNING)


    # Display version if asked
    log.info(description)
    if args.version:
        print(description)
        return None

    # List available protocols if asked
    if args.protocol == "help":
        op = get_outputs("screen")[0]
        op.output(data=list_protocols())
        return None

    # List outputs if asked
    if args.output == "help":
        keep_case = True
        op = get_outputs("screen")[0]
        op.output(data=list_outputs())
        # print("Available output modules:")
        # for result in results:
        #    print(result)
        return None

    ##### Extra Logging - All daemon setup functions 
    #(log_process_info, setup_daemon_if_requested, etc)
    def log_process_info(label, log_func=None):
        """Log detailed process information for debugging"""
        if log_func is None:
            log_func = print
        pid = os.getpid()
        ppid = os.getppid()
        # Get process group and session info
        try:
            pgid = os.getpgid(0)
            sid = os.getsid(0)
        except:
            pgid = "unknown"
            sid = "unknown"

        # Check if we're the process group leader
        is_leader = (pid == pgid)
        log_func(f"[{label}] PID: {pid}, PPID: {ppid}, PGID: {pgid}, SID: {sid}, Leader: {is_leader}")

        # Log command line that started this process
        try:
            with open(f'/proc/{pid}/cmdline', 'r') as f:
                cmdline = f.read().replace('\0', ' ').strip()
            log_func(f"[{label}] Command: {cmdline}")
        except:
            log_func(f"[{label}] Command: {' '.join(sys.argv)}")

    def log_debug_context(label, args):
        log.debug(f"[{label}] sys.argv = {sys.argv}")
        log.debug(f"[{label}] args.daemon = {args.daemon}")
        log.debug(f"[{label}] args.debug = {args.debug}")

    if args.debug:
        if is_spawned_pyinstaller_process():
            log_debug_context("CHILD", args)
        elif is_pyinstaller_bundle():
            log_debug_context("PARENT", args)
        else:
            log_debug_context("SYSTEM", args)

    def setup_daemon_if_requested(args, log_file_path="/var/log/mpp-solar.log"):
        if args.daemon:
            os.environ["MPP_SOLAR_DAEMON"] = "1"
            log.info("Daemon mode requested")
            try:
                daemon_type = detect_daemon_type()
                log.info(f"Detected daemon type: {daemon_type}")
            except Exception as e:
                log.warning(f"Failed to detect daemon type: {e}, falling back to OpenRC")
                daemon_type = DaemonType.OPENRC
            daemon = get_daemon(daemontype=daemon_type)
            
            # Properly set PID file path
            if args.pidfile:
                if hasattr(daemon, 'set_pid_file_path'):
                    daemon.set_pid_file_path(args.pidfile)
                elif hasattr(daemon, 'pid_file_path'):
                    daemon.pid_file_path = args.pidfile
                log.info(f"Using custom PID file: {args.pidfile}")
            elif hasattr(daemon, 'pid_file_path'):
                daemon.pid_file_path = "/tmp/mpp-solar.pid" if os.geteuid() != 0 else "/var/run/mpp-solar.pid"
                log.info(f"Using default PID file: {daemon.pid_file_path}")
                
            daemon.keepalive = 60
            log.info("Attempting traditional daemonization...")
            try:
                # daemonize()
                log.info("Daemonized successfully")
                # Re-setup logging for the daemonized process
                if not setup_daemon_logging(log_file_path):
                    sys.stderr.write("CRITICAL: Failed to setup file logging for daemon. Check permissions.\n")
                else:
                    log.info("Daemon file logging successfully re-initialized.")
            except Exception as e:
                log.error(f"Failed to daemonize process: {e}")
                log.info("Continuing in foreground mode")
            return daemon
        else:
            log.info("Daemon mode NOT requested. Using DISABLED daemon.")
            daemon = get_daemon(daemontype=DaemonType.DISABLED)
            log_process_info("DAEMON_DISABLED_CREATED", log.info)
            return daemon


    # --- Optional PyInstaller bootstrap cleanup ---
    # To enable single-process daemon spawn logic (avoids PyInstaller parent):
    #################################################################
#     if spawn_pyinstaller_subprocess(args):
#       sys.exit(0)
# 
#     from daemon.pyinstaller_runtime import setup_spawned_environment
#     setup_spawned_environment()
    #################################################################


    # Handle daemon stop request
    if args.daemon_stop:
        pid_file_path = args.pidfile
        if pid_file_path is None:
            # Use default based on environment
            if os.geteuid() != 0:  # Non-root check
                pid_file_path = "/tmp/mpp-solar.pid"
            else:
                pid_file_path = "/var/run/mpp-solar.pid"

        log.info(f"Attempting to stop daemon using PID file: {pid_file_path}")
        try:
            daemon_type = detect_daemon_type()
            daemon_class = get_daemon(daemontype=daemon_type).__class__
            if hasattr(daemon_class, 'stop_daemon'):
                success = daemon_class.stop_daemon(pid_file_path)
                if success:
                    print("Daemon stopped successfully")
                else:
                    print("Failed to stop daemon")
                sys.exit(0 if success else 1)
            else:
                print("Daemon stop functionality not available for this daemon type")
                sys.exit(1)
        except Exception as e:
            print(f"Error stopping daemon: {e}")
            sys.exit(1)

    # Centralized mqtt_broker object. It's either built from args or from the config file.
    mqtt_broker = None
    log.debug(mqtt_broker)
    udp_port = args.udpport
    log.debug(f"udp port {udp_port}")
    postgres_url = args.postgres_url
    log.debug(f"Using Postgres {postgres_url}")
    mongo_url = args.mongo_url
    mongo_db = args.mongo_db
    log.debug(f"Using Mongo {mongo_url} with {mongo_db}")
    ##
    filter = args.filter
    excl_filter = args.exclfilter
    keep_case = args.keepcase
    mqtt_topic = args.mqtttopic
    push_url = args.pushurl
    prom_output_dir = args.prom_output_dir
    dev = args.dev
    _commands = []

    # If config file specified, process
    if args.configfile:
        import configparser
        log.debug(f"args.configfile is true: {args.configfile}")
        config = configparser.ConfigParser()
        try:
            config.read(args.configfile)
        except configparser.DuplicateSectionError as e:
            log.error(f"Config File '{args.configfile}' has duplicate sections: {e}")
            exit(1)

        # Check for SETUP section
        if "SETUP" not in config:
            log.error(f"Config File '{args.configfile}'  is missing the required 'SETUP' section or does not exist")
            exit(1)

        # Process setup section
        pause = config["SETUP"].getint("pause", fallback=60)
        log_file_path = config["SETUP"].get("log_file", fallback="/var/log/mpp-solar.log")

        ### Create MQTT config dict from file, then instantiate ONE transport and ONE manager
        mqtt_broker_config = {
            "name": config["SETUP"].get("mqtt_broker"),
            "port": config["SETUP"].getint("mqtt_port", 1883),
            "user": config["SETUP"].get("mqtt_user"),
            "pass": config["SETUP"].get("mqtt_pass"),
        }
        mqtt_transport = MqttTransport(config=mqtt_broker_config)
        get_manager(mqtt_transport=mqtt_transport) # This creates the singleton manager

        # Build a single mqtt_broker object for legacy output processors
        mqtt_broker = MqttTransport(config=mqtt_broker_config)
        mqtt_broker.set("results_topic", (args.mqtttopic if args.mqtttopic is not None else prog_name))

        sections = config.sections()
        sections.remove("SETUP")

        # Process 'command' sections
        for section in sections:
            name = section
            protocol = config[section].get("protocol", fallback=None)
            _type = config[section].get("type", fallback="mppsolar")
            port = config[section].get("port", fallback="/dev/ttyUSB0")
            baud = config[section].get("baud", fallback=2400)
            _command = config[section].get("command")
            tag = config[section].get("tag")
            outputs = config[section].get("outputs", fallback="screen")
            porttype = config[section].get("porttype", fallback=None)
            filter = config[section].get("filter", fallback=None)
            excl_filter = config[section].get("exclfilter", fallback=None)
            udp_port = config[section].get("udpport", fallback=None)
            postgres_url = config[section].get("postgres_url", fallback=None)
            mongo_url = config[section].get("mongo_url", fallback=None)
            mongo_db = config[section].get("mongo_db", fallback=None)
            push_url = config[section].get("push_url", fallback=push_url)
            prom_output_dir = config[section].get("prom_output_dir", fallback=prom_output_dir)
            mqtt_topic = config[section].get("mqtt_topic", fallback=mqtt_topic)
            section_dev = config[section].get("dev", fallback=None)
            # Get mqtt_cmds from config, this is the correct key
            mqtt_allowed_cmds = config[section].get("mqtt_cmds", fallback="")
            section_dev = config[section].get("dev", fallback=None)
            
            # Legacy output variables
            push_url = config[section].get("push_url", fallback=args.pushurl)
            prom_output_dir = config[section].get("prom_output_dir", fallback=args.prom_output_dir)

            device_class = get_device_class(_type)
            log.debug(f"device_class {device_class}")
            
            # The device class __init__ will instantiate the port communications and protocol classes
            device = device_class(
                name=name,
                port=port,
                protocol=protocol,
                outputs=outputs,
                baud=baud,
                porttype=porttype,
                mqtt_broker=mqtt_broker, # Pass legacy broker for old outputs
                udp_port=udp_port,
                postgres_url=postgres_url,
                mongo_url=mongo_url,
                mongo_db=mongo_db,
                push_url=push_url,
                prom_output_dir=prom_output_dir,
            )

            # Setup MQTT commands if defined for this device
            if mqtt_allowed_cmds:
                log.info(f"Setting up MQTT commands for device {name}: {mqtt_allowed_cmds}")
                setup_device_mqtt_commands(device, mqtt_allowed_cmds, name)

            # build array of commands for the main loop
            commands = _command.split("#")

            for command in commands:
                _commands.append((device, command, tag, outputs, args.filter, args.exclfilter, section_dev))
            log.debug(f"Commands from config file: {_commands}")
            log.debug(f"[DAEMON LOOP INIT] args.daemon={args.daemon}, pause={pause}, commands={_commands}")
            if args.daemon:
                print(f"Config file: {args.configfile}")
                print(f"Config setting - pause: {pause}")
                # print(f"Config setting - mqtt_broker: {mqtt_broker}, port: {mqtt_port}")
                print(f"Config setting - command sections found: {len(sections)}")
            else:
                log.info(f"Config file: {args.configfile}")
                log.info(f"Config setting - pause: {pause}")
                # log.info(f"Config setting - mqtt_broker: {mqtt_broker}, port: {mqtt_port}")
                log.info(f"Config setting - command sections found: {len(sections)}")

    else:
        # No configfile specified - build from args
        log.info(f'Creating device "{args.name}" (type: "{s_prog_name}") on port "{args.port} (porttype={args.porttype})" using protocol "{args.protocol}"')

        # Setup MQTT from args if needed for command listening (not just output)
#         if args.daemon: # Assuming commands are only needed in daemon mode
        mqtt_broker_config = {
            "name": args.mqttbroker,
            "port": args.mqttport,
            "user": args.mqttuser,
            "pass": args.mqttpass,
        }
        mqtt_transport = MqttTransport(config=mqtt_broker_config)
        get_manager(mqtt_transport=mqtt_transport)
        ###########
        # Create legacy mqtt_broker for outputs
        mqtt_broker = MqttTransport(config={
            "name": args.mqttbroker, "port": args.mqttport, "user": args.mqttuser, "pass": args.mqttpass,
        })
        mqtt_broker.set("results_topic", (args.mqtttopic if args.mqtttopic is not None else prog_name))


        device_class = get_device_class(s_prog_name)
        device = device_class(
            name=args.name,
            port=args.port,
            protocol=args.protocol,
            baud=args.baud,
            porttype=args.porttype,
            mqtt_broker=mqtt_broker,
            udp_port=udp_port,
            mongo_url=mongo_url,
            mongo_db=mongo_db,
            push_url=push_url,
            prom_output_dir=prom_output_dir,
        )

        # Determine commands from args
        commands = []
        if args.command == "help":
            keep_case = True
            commands.append("list_commands")
        elif args.getstatus:
            commands.append("get_status")
        elif args.getsettings:
            # use get_settings helper
            commands.append("get_settings")
        elif args.getDeviceId:
            # use get_settings helper
            commands.append("get_device_id")
        elif args.getVersion:
            # use get_version helper
            commands.append("get_version")
        elif args.command is None:
            # run the command
            commands.append("")
        else:
            commands = (args.command or "").split("#")

        outputs = args.output
        for command in commands:
            tag = args.tag or command
            _commands.append((device, command, tag, outputs, args.filter, args.exclfilter, args.dev))
        log.debug(f"Commands from args: {_commands}")

    # ------------------------
    # Daemon setup and logging
    # ------------------------
    daemon = setup_daemon_if_requested(args, log_file_path=log_file_path)
    log.info(daemon)
    DAEMON_MODE = args.daemon
    # Notify systemd/init
    daemon.initialize()
    log.debug("AFTER_DAEMON_INITIALIZE")
    daemon.notify("Service Initializing ...")
    log.debug("AFTER_DAEMON_NOTIFY")

    # Connect the legacy mqtt_broker for output processors  
    if mqtt_broker:
        log.info("Connecting legacy MQTT broker for output processors...")
        mqtt_broker.connect()
        
    # If in daemon mode, print MQTT info and connect the manager
    if DAEMON_MODE:
        mqtt_info = get_mqtt_command_info()
        if mqtt_info:
            print("MQTT Command Handlers configured:")
            for device_name, info in mqtt_info.items():
                print(f"  Device: {device_name}")
                print(f"    Command Topic: {info['command_topic']}")
                print(f"    Response Topic: {info['response_topic']}")
                print(f"    Allowed Commands: {info['allowed_commands']}")

            manager = get_manager()
            if manager:
                print("Connecting MQTT Command Manager...")
                manager.connect()
        else:
            print("No MQTT command handlers configured.")

    # MAIN EXECUTION LOOP
    while True:
        if not DAEMON_MODE:
            log.info(f"Looping {len(_commands)} commands")
        for _device, _command, _tag, _outputs, filter, excl_filter, dev in _commands:
            daemon.watchdog()
            daemon.notify(f"Executing command: {_command} on device: {_device._name}")
            log.info(f"Getting results for command '{_command}' from device '{_device._name}'")
            results = _device.run_command(command=_command)

            # Send to output processors
            outputs = get_outputs(_outputs)
            for op in outputs:
                op.output(
                    data=results.copy(),
                    tag=_tag,
                    name=_device._name,
                    mqtt_broker=mqtt_broker,
                    udp_port=udp_port,
                    postgres_url=postgres_url,
                    mongo_url=mongo_url,
                    mongo_db=mongo_db,
                    push_url=push_url,
                    prom_output_dir=prom_output_dir,
                    # mqtt_port=mqtt_port,
                    # mqtt_user=mqtt_user,
                    # mqtt_pass=mqtt_pass,
                    mqtt_topic=mqtt_topic,
                    filter=filter,
                    excl_filter=excl_filter,
                    keep_case=keep_case,
                    dev=dev,
                )

        try:
                # Tell systemd watchdog we are still alive
            if DAEMON_MODE:
                daemon.watchdog()
                log.info(f"Sleeping for {pause} sec")
                time.sleep(pause)
            else:
                log.debug("Not in daemon mode, exiting.")
                break
        except Exception as e:
            log.error(f"[LOOP ERROR] Exception in daemon loop: {e}", exc_info=True)
            time.sleep(5)  # Prevent tight loop in case of recurring errors

if __name__ == "__main__":
    main()