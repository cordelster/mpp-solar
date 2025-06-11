# Using MQTT Commands with mpp-solar (Daemon Mode)

mpp-solar now supports **bidirectional MQTT commands** when running in daemon mode. This allows external systems like Home Assistant, Node-RED, or MQTT Explorer to send commands to your inverter and receive responses in real-time over MQTT.

---

## 🧹 Feature Overview

- Each inverter/device configured in your `.conf` file can expose a dedicated **command topic** and **response topic**.
- Commands are validated against a **regex whitelist** (`mqtt_allowed_cmds`) to ensure safety.
- Only available in **daemon mode** with a proper `configfile`.

---

## ⚙️ Configuration

Example `mpp-solar.conf` section:

```ini
[Inverter_1]
protocol = PI30
port = /dev/hidraw0
baud = 2400
outputs = mqtt
command = QPIRI
mqtt_allowed_cmds = ^(QPI|QPIRI|QPIGS|POP[0-9]{2})$
tag = Inverter_1
```

In `[SETUP]` section:

```ini
[SETUP]
mqtt_broker = localhost
mqtt_port = 1883
mqtt_user = user
mqtt_pass = pass
```

---

## 🚀 Running mpp-solar in MQTT Daemon Mode

```bash
./mpp-solar -C /path/to/mpp-solar.conf --daemon
```

If set up correctly, you will see:

```
MQTT Command Handlers configured:
  Device: Inverter_1
    Command Topic: mpp-solar/Inverter_1/commands
    Response Topic: mpp-solar/Inverter_1/responses
    Allowed Commands: QPI, QPIRI, QPIGS, POP[0-9]{2}
```

---

## 📬 Sending Commands

Use a tool like **MQTT Explorer** or **mosquitto\_pub**:

- **Topic:** `mpp-solar/Inverter_1/commands`
- **Payload:** `QPIGS` (or any allowed command)

```bash
mosquitto_pub -t mpp-solar/Inverter_1/commands -m QPIRI
```

---

## 📥 Receiving Responses

The response will be published to:

- **Topic:** `mpp-solar/Inverter_1/responses`
- **Payload:** (raw inverter response as JSON)

---

## 🛡️ Security & Filtering

- Commands are **regex-filtered** via `mqtt_allowed_cmds`.
- Any message not matching the filter will be ignored and logged.
- Commands are processed **only for the associated device section** in your config.

---

## 🧪 Testing

You can use the following tools to test MQTT functionality:

- [MQTT Explorer](https://mqtt-explorer.com/)
- `mosquitto_pub` / `mosquitto_sub`
- Home Assistant MQTT automation
- Node-RED with MQTT nodes

---

## 🐞 Troubleshooting

- Make sure daemon mode is active (`--daemon`) and the config file is correctly parsed.
- Watch logs for connection and command validation errors.
- If nothing happens:
  - Confirm your device’s name matches the topic.
  - Ensure the command matches the regex whitelist.
  - Check that MQTT broker credentials are correct.

---

## 🧼 Cleanup

All MQTT handlers are automatically unregistered on shutdown.

---

## 🧹 Related Features

- MQTT Output for regular telemetry (`outputs = mqtt`)
- Prometheus push and file output
- Home Assistant integrations via MQTT auto-discovery

---

## 📟 Example MQTT Command Flow

```
📈 MQTT Client (e.g. MQTT Explorer)
    ↓ sends QPIGS command
📢 mpp-solar daemon
    ✔ validates command
    ✔ runs on inverter
    ✔ publishes response
      → mpp-solar/Inverter_1/responses
```

---

## ✨ Summary

- One daemon process can expose multiple inverters over MQTT.
- MQTT topics are deterministic and clean.
- Safe command handling via regex.
- Real-time command/response over MQTT.

Enjoy full remote control over your inverter — safely and efficiently.

