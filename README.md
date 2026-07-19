# MUST EP30 / EP3000 for Home Assistant

[![Validate](https://github.com/mkbodanu4/ha-must-ep30/actions/workflows/validate.yml/badge.svg)](https://github.com/mkbodanu4/ha-must-ep30/actions/workflows/validate.yml)
[![Test](https://github.com/mkbodanu4/ha-must-ep30/actions/workflows/test.yml/badge.svg)](https://github.com/mkbodanu4/ha-must-ep30/actions/workflows/test.yml)
[![HACS Custom Repository](https://img.shields.io/badge/HACS-Custom%20Repository-41BDF5.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/mkbodanu4/ha-must-ep30)](https://github.com/mkbodanu4/ha-must-ep30/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A native Home Assistant custom integration for **MUST EP30 Pro** and **EP3000 Plus** inverter/chargers. It talks to the device directly over serial (ASCII protocol or Modbus RTU) or Modbus TCP/UDP and exposes its readings as first-class HA entities with UI-based setup, a proper device card, and automatic reconnect handling.

This project is the native-integration successor to [`ep30_pro_mqtt`](https://github.com/mkbodanu4/ep30_pro_mqtt), a standalone Python script that polled the same hardware and republished readings over MQTT Discovery. If you're currently running that script, see [Migrating from `ep30_pro_mqtt`](#migrating-from-ep30_pro_mqtt) below.

> **Status:** early release. The EP30 Pro (ASCII) and EP3000 Plus (Modbus RTU over USB) protocols are ported from a project with real field history, but this integration itself is new and has not yet been broadly field-tested. Please open an issue with a diagnostics dump if something looks wrong -- see [Troubleshooting](#troubleshooting).

---

## Table of contents

- [Supported hardware](#supported-hardware)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entity reference](#entity-reference)
- [Automations](#automations)
- [Troubleshooting](#troubleshooting)
- [Migrating from `ep30_pro_mqtt`](#migrating-from-ep30_pro_mqtt)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)
- [Credits](#credits)

---

## Supported hardware

| Model | Connection | Status |
|---|---|---|
| MUST EP30 Pro | USB serial (2400 baud, proprietary ASCII protocol) | **Verified** -- protocol ported from a script with real field usage |
| MUST EP3000 Plus | USB serial (Modbus RTU, 9600 baud) | **Verified** -- register map (holding registers 30000-30026) ported from a script with real field usage |
| MUST EP3000 Plus | Modbus TCP (RS485-to-Ethernet/WiFi gateway) | Implemented, **not yet field-tested** against real gateway hardware |
| MUST EP3000 Plus | Modbus UDP (RS485-to-Ethernet/WiFi gateway) | Implemented, **not yet field-tested** against real gateway hardware |
| MUST EP3300 / EP3300 TLV / full EP2000 Pro register set | -- | **Not implemented.** Register maps exist (reverse-engineered from the vendor's own monitoring software) but no device profile ships yet -- see [Contributing](#contributing) if you have one of these and want to help add it |

This integration deliberately does **not** reuse the register map from the otherwise excellent [`mukaschultze/ha-must-inverter`](https://github.com/mukaschultze/ha-must-inverter) project -- its own issue tracker ([#112](https://github.com/mukaschultze/ha-must-inverter/issues/112)) documents garbled/misaligned Modbus reads against a real EP3000 Plus, meaning its PV1800/PV1900 register layout is not compatible with this hardware. The register map used here is independently re-derived from a field-tested predecessor script instead. See [Credits](#credits).

### Known-unverified details

A handful of protocol details are ported from decompiled vendor reference sources rather than confirmed against live hardware by this project. None of these block normal use, but they're worth knowing about:

- **EP30 Pro `working_status`**: ASCII code `30` (`battery_priority`) is confirmed against the decompiled vendor reference; code `31` (`bypass`) is backed by a field report (observed with utility power present and output voltage tracking input voltage, both characteristic of bypass/pass-through mode) plus the predecessor project's own "anything other than 30 is Bypass" fallback heuristic -- reasonably confident, but not decompiled-reference-confirmed like `30`. The other four documented states (invert-only, grid-fail-and-invert, grid-and-invert-fail, fail) will show up as `unknown_code_N` if your hardware reports one -- please [open an issue](https://github.com/mkbodanu4/ha-must-ep30/issues) with the code you see (and what the inverter's own display showed, if you know) so the table can be completed.
- **EP30 Pro temperature decode**: the protocol encodes temperature in a BCD-like format with no checksum, so a mis-synced read is possible in principle. The integration logs a warning if a decoded value falls outside a plausible range (-10°C to 120°C).
- **EP3000 Plus serial number**: registers 31200/31201 are documented for the EP3300 variants but unconfirmed on plain EP3000 Plus firmware. The integration probes for it opportunistically and falls back to a connection-string-based device identity if it's not populated.

---

## Architecture

```
             ┌───────────────────────────┐
             │        MUST device        │
             │ (EP30 Pro or EP3000 Plus) │
             └───────────────────────────┘
                            │
            serial / Modbus RTU / TCP / UDP
                            ▼
           ┌───────────────────────────────┐
           │        Protocol client        │
           │ ascii_serial.py  /  modbus.py │
           └───────────────────────────────┘
                            │
             MustDeviceClient.async_fetch()
                            ▼
         ┌───────────────────────────────────┐
         │       DataUpdateCoordinator       │
         │      polls every N seconds,       │
         │ raises UpdateFailed on I/O errors │
         └───────────────────────────────────┘
                            │
             ┌──────────────┴──────────────┐
             ▼                             ▼
  ┌────────────────────┐        ┌────────────────────┐
  │     sensor.py      │        │  binary_sensor.py  │
  │ generic, driven by │        │ generic, driven by │
  │   DeviceProfile    │        │   DeviceProfile    │
  └────────────────────┘        └────────────────────┘
```

- One config entry = one physical device = one `DataUpdateCoordinator`.
- Both protocols implement the same `MustDeviceClient` interface (`async_connect` / `async_fetch` / `async_close`), so the coordinator, entity platforms, and config flow don't know or care whether they're talking to the ASCII protocol or Modbus.
- Entities are generated from a declarative per-model `DeviceProfile` (a table of sensor/binary_sensor descriptions with a `value_fn`), not hand-written per entity -- adding a new model is a new profile module, not a rewrite.
- A failed poll raises `UpdateFailed`, which HA turns into entities going `unavailable` -- the connection self-heals on the next poll cycle rather than crashing the integration.

## Installation

### Via HACS (recommended)

This integration is not yet in the HACS default store. Add it as a custom repository:

1. HACS → the "⋮" menu (top right) → **Custom repositories**.
2. Repository: `https://github.com/mkbodanu4/ha-must-ep30`, Category: **Integration**.
3. Find "MUST EP30/EP3000" in HACS and install it.
4. Restart Home Assistant.
5. Settings → Devices & Services → **Add Integration** → search "MUST EP30/EP3000".

### Manual

1. Copy `custom_components/must_ep30/` from this repository into your Home Assistant config's `custom_components/` directory.
2. Restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → search "MUST EP30/EP3000".

## Configuration

Setup is entirely UI-driven (no YAML). All steps below run inside **Settings → Devices & Services → Add Integration → MUST EP30/EP3000**.

### 1. Choose your device and connection

![Model selection step](docs/screenshots/step1-model.png)

| Choice | When to use it |
|---|---|
| MUST EP30 Pro (Serial, ASCII protocol) | You have an EP30 Pro connected via USB-to-serial |
| MUST EP3000 Plus (Serial, Modbus RTU) | You have an EP3000 Plus connected via USB-to-serial |
| MUST EP3000 Plus (Modbus TCP gateway) | Your EP3000 Plus's RS485 bus goes through an Ethernet/WiFi Modbus gateway using TCP |
| MUST EP3000 Plus (Modbus UDP gateway) | Same, but your gateway uses UDP |

You can also give the device a friendly name here; it becomes both the config entry title and the device name.

### 2a. Serial connection

![Serial port selection step](docs/screenshots/step2-serial.png)

Pick the serial port from the dropdown, or enter a path manually. **Prefer a stable path** like `/dev/serial/by-id/usb-...` over a raw `/dev/ttyUSB0` -- USB enumeration order can change across reboots or replugging, and since this device's unique ID is derived from the connection path for serial setups, a changed path means Home Assistant treats it as a different device. See [Troubleshooting](#troubleshooting) for how to find the stable path.

### 2b. Modbus TCP/UDP connection

![Gateway connection step](docs/screenshots/step2-network.png)

Enter the gateway's host/IP, port (default `502`), and the Modbus slave/device ID (default `10`, matching the EP3000 Plus's factory default).

### Validation

Whichever path you take, the integration performs a **real read** against the device before letting you finish setup. If it fails, you'll see an error on the form rather than a half-configured device -- double check wiring, the port/host, and that nothing else (like the vendor's own monitoring software) is holding the serial port open.

### Options

After setup, **Configure** on the integration's entry gives you:

- **Poll interval** (5-300s, default 10s). The original script polled every 2s; 10s is a friendlier default for a poll cycle now sharing Home Assistant's event loop, but you can go as low as 5s.
- **Battery calibration** (advanced). Neither protocol reports a true battery state-of-charge on these particular models (the EP3000 Plus's `battery_soc` register is exposed as-is, for what it's worth, but the computed `Battery Level` sensor uses a voltage curve instead). The defaults are picked from the device's own reported nominal/nameplate battery voltage (12V and 24V lead-acid reference curves are built in; other bank sizes are linearly scaled from whichever is closer) -- adjust the six threshold values here if you have a different chemistry (e.g. LiFePO4) or want to fine-tune for your specific bank. EP30 Pro also exposes an ADC scaling max here, used only for the `Charger Battery Voltage` sensor.

### Reconfigure

If your serial port path or gateway host/port changes, use **Reconfigure** on the integration entry rather than deleting and re-adding it -- this re-validates the new connection details and updates the existing entry (and its entities) in place. The device model itself can't be changed this way, since it determines which entities exist; remove and re-add the integration if you need to switch device models.

## Entity reference

All entities are grouped under one device per config entry (Settings → Devices & Services → MUST EP30/EP3000 → your device).

### EP30 Pro

<details>
<summary><strong>Sensors (21)</strong></summary>

| Entity | Device class | Unit | Notes |
|---|---|---|---|
| Rating Voltage | voltage | V | Nameplate rating, from the `F` command |
| Rating Current | current | A | Nameplate rating |
| Nominal Battery Voltage | voltage | V | Nameplate rating |
| Nominal Frequency | frequency | Hz | Nameplate rating |
| Input Voltage | voltage | V | Live grid input |
| Last Fault Voltage | voltage | V | Voltage at last input fault |
| Output Voltage | voltage | V | Live inverter output |
| Load | -- | % | Load level |
| Output Frequency | frequency | Hz | Live output |
| Battery Voltage | voltage | V | Live battery voltage |
| Inverter Temperature | temperature | °C | BCD-decoded (see [Known-unverified details](#known-unverified-details)) |
| Working Status | -- | -- | `battery_priority`/`bypass` known; other states may show as `unknown_code_N` |
| Fault State | -- | -- | Raw fault/message string from the `G?` command |
| Battery Charging Current | current | A | 0 when not charging |
| Charger Battery Voltage | voltage | V | ADC-scaled, see Battery calibration options |
| Charger Value 1-4 | -- | -- | Raw diagnostic values from the `X` command; **disabled by default** |
| Battery Level | battery | % | Computed from voltage + charge state, see Battery calibration options |
| Output Power | power | W | Computed: `rating_current × (load/100) × output_voltage` |

</details>

<details>
<summary><strong>Binary sensors (8)</strong></summary>

| Entity | Device class | On means |
|---|---|---|
| Utility Power Present | power | Grid power is present |
| Battery Low | battery | Battery is low |
| UPS Failed | problem | A fault is active |
| Line-interactive Type | -- | Device reports as line-interactive |
| Test in Progress | -- | Self-test running |
| Shutdown Active | -- | A scheduled shutdown is pending |
| Beeper On | -- | Audible alarm is enabled |
| Charger Action | battery_charging | Currently charging |

</details>

### EP3000 Plus

<details>
<summary><strong>Sensors (24)</strong></summary>

| Entity | Device class | Unit | Notes |
|---|---|---|---|
| Machine Type | enum | -- | e.g. `ep2000_pro`, `ep3300` |
| Software Version | -- | -- | |
| Work State | enum | -- | `self_check`, `backup`, `line`, `stop`, `charger`, `soft_start`, `power_off`, `standby`, `debug` |
| Battery Class | voltage | V | Nameplate battery class (e.g. 24V, 48V) |
| Rated Power | power | W | |
| Grid Voltage | voltage | V | |
| Grid Frequency | frequency | Hz | |
| Output Voltage | voltage | V | |
| Output Frequency | frequency | Hz | |
| Load Current | current | A | |
| Load Power | power | W | |
| Load | -- | % | |
| Battery Voltage | voltage | V | |
| Battery Charging Current | current | A | Forced to 0 while discharging (`work_state = backup`) |
| Battery Temperature | temperature | °C | |
| Battery State of Charge | battery | % | Raw device-reported SoC register |
| Inverter Temperature | temperature | °C | |
| Buzzer State | enum | -- | `normal` / `silence` |
| System Fault | enum | -- | 16-value vendor fault table, e.g. `over_load`, `main_relay_failed` |
| System Alarm | enum | -- | Vendor alarm table |
| Charge Stage | enum | -- | `cc` / `cv` / `fv` |
| Grid Charge Flag | enum | -- | Whether currently charging from grid |
| Grid State | enum | -- | `disconnected` / `connected` / `warning` |
| Battery Level | battery | % | Computed from voltage + charge state, see Battery calibration options |

</details>

No binary sensors are defined for EP3000 Plus (matching the original project, which didn't expose any for this model either -- everything comes through as enumerated/numeric sensors instead).

## Automations

The original `ep30_pro_mqtt` script could shut down its host machine directly (`subprocess.run(['shutdown', 'now'])`) when battery voltage dropped too low. **This integration does not replicate that** -- a HACS-distributed integration silently invoking arbitrary shell commands on your host is exactly the kind of thing HACS's security guidance warns against. Instead, wire it up yourself with a normal HA automation, so the trust boundary is explicit and under your control:

```yaml
# configuration.yaml
shell_command:
  shutdown_ep30_host: "ssh user@your-host-running-ha 'sudo shutdown now'"
  # or, if HA itself runs on the machine you want to shut down:
  # shutdown_ep30_host: "sudo shutdown now"
```

```yaml
# automation
automation:
  - alias: "MUST EP30 - shut down host on critically low battery"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.must_ep30_battery_voltage
        below: 20.0
        for: "00:00:30"
    actions:
      - action: shell_command.shutdown_ep30_host
```

A couple of other useful starting points:

```yaml
automation:
  - alias: "MUST EP30 - notify on low battery"
    triggers:
      - trigger: state
        entity_id: binary_sensor.must_ep30_battery_low
        to: "on"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "Battery low"
          message: "Battery voltage: {{ states('sensor.must_ep30_battery_voltage') }} V"

  - alias: "MUST EP30 - notify when utility power is lost"
    triggers:
      - trigger: state
        entity_id: binary_sensor.must_ep30_utility_power_present
        to: "off"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "Utility power lost"
          message: "Running on battery."
```

(Adjust entity IDs to match what Home Assistant actually assigned to your device -- check Settings → Devices & Services → Entities.)

## Troubleshooting

**"Could not read from the device" during setup / `cannot_connect` error**
- Serial: confirm the port path is correct and not in use by another process (e.g. the old `ep30_pro_mqtt` script, or the vendor's monitoring software, both hold the port exclusively).
- Serial: on Linux, your Home Assistant user needs permission to access the serial device -- typically membership in the `dialout` group, or a udev rule granting access.
- Modbus TCP/UDP: confirm the gateway's host/port are reachable from the HA host (`ping`, or `nc -zv host port` for TCP), and that the slave/device ID matches your gateway's configuration (factory default is usually `10` for these devices, but gateways can remap it).

**Serial port path keeps changing / device shows as newly discovered after a reboot**
- Use a stable path instead of `/dev/ttyUSBx`. On Linux: `ls -l /dev/serial/by-id/` to find a path like `/dev/serial/by-id/usb-...-if00-port0`, then use Reconfigure to switch to it.

**A generic USB-to-serial adapter isn't auto-detected**
- This is deliberate. Common bridge chips (Silicon Labs CP210x, WCH CH340, FTDI) are shared by dozens of unrelated devices, so this integration doesn't ship a USB auto-discovery matcher that could pop up a misleading "MUST EP30/EP3000 discovered" prompt for someone's Arduino or 3D printer. Add the device manually and pick the correct port.

**EP30 Pro sensors show odd/garbled values occasionally**
- The ASCII protocol has no checksum, so a byte-misaligned read is possible (especially at 2400 baud on a noisy/long cable run). The integration logs a warning for implausible temperature readings; if you see this often, check your cable/adapter quality. A single bad reading self-corrects on the next poll.

**EP3000 Plus sensors show completely wrong-looking values (not just occasional noise)**
- This usually means register misalignment, not a transient glitch. Double-check the slave/device ID. If you're coming from a different MUST-family integration, note that this project's register table was independently re-derived from a field-tested predecessor script rather than reused from other MUST integrations -- see [Supported hardware](#supported-hardware) for why.

**Filing a bug report**
- Please include a diagnostics download: the device's page in Settings → Devices & Services → MUST EP30/EP3000 → the "⋮" menu → **Download diagnostics**. It includes the last raw poll result (decoded ASCII fields or raw Modbus registers), which is usually the fastest way to spot a decoding bug remotely. Host/serial paths are redacted automatically.

## Migrating from `ep30_pro_mqtt`

If you're currently running the predecessor [`ep30_pro_mqtt`](https://github.com/mkbodanu4/ep30_pro_mqtt) script:

1. **Stop and disable the old service:**
   ```sh
   sudo systemctl stop ep30
   sudo systemctl disable ep30
   sudo rm /etc/systemd/system/ep30.service
   sudo systemctl daemon-reload
   ```
2. **Install and configure this integration** as described above.
3. **Clean up old entities.** The old script never set a `unique_id` in its MQTT discovery payloads, so its `sensor.ep30_*` / `binary_sensor.ep30_*` entities have no stable registry identity. Once the old service is stopped they'll go `unavailable`; remove them from Settings → Devices & Services → Entities (filter by "unavailable" or search "ep30").
4. **Expect new entity IDs.** This integration groups entities under a proper device with `has_entity_name`, so IDs look like `sensor.must_ep30_pro_battery_voltage` rather than `sensor.ep30_battery_voltage`. Review and update any dashboards or automations referencing the old IDs.
5. **If you were using the `retain`-less MQTT discovery topics and want to be thorough,** purge any stale retained config topics from your broker (usually unnecessary, since the old script never set `retain: True`):
   ```sh
   mosquitto_pub -h <broker> -t 'homeassistant/sensor/ep30_<id>/config' -n -r
   mosquitto_pub -h <broker> -t 'homeassistant/binary_sensor/ep30_<id>/config' -n -r
   ```
6. **If you used the InfluxDB backend** for Grafana dashboards, point HA's own core [`influxdb`](https://www.home-assistant.io/integrations/influxdb/) integration at this integration's new entities instead -- it can filter/include specific entities and write to the same InfluxDB instance. The old `grafana/telegraf.conf` and dashboard JSON in the predecessor repo can still be adapted, but that's outside this integration's scope.

### Config value mapping

| Old `configuration.yaml` key | New location |
|---|---|
| `serial.port` | Config flow → Serial connection step |
| `run.sleep_time` | Options → Poll interval (default changed from 2s to 10s) |
| `run.calculation_trusted_delay` | Dropped (was unused in the original code) |
| `backend`, `mqtt.*`, `influx.*` | Dropped -- HA entities are the data path now; see above for InfluxDB |
| `adc.battery_voltage_max` | Options → Battery calibration (EP30 Pro only) |
| `discharge_config.*`, `charge_config.*` | Options → Battery calibration |
| `trigger.*` | Dropped -- see [Automations](#automations) for the replacement pattern |

## Development

```sh
git clone https://github.com/mkbodanu4/ha-must-ep30.git
cd ha-must-ep30
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements_test.txt
```

Run the test suite:

```sh
pytest
```

Lint/format:

```sh
ruff check custom_components tests
black custom_components tests
```

Validate the manifest/translations locally the same way CI does:

```sh
pip install homeassistant
python -m script.hassfest --integration-path custom_components/must_ep30
```

Tests use [`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) and mock the serial/Modbus transport -- no real hardware is touched by the test suite or CI.

## Contributing

Issues and PRs welcome. A few things that would particularly help:

- **Field reports for the [known-unverified details](#known-unverified-details)** above -- especially the remaining EP30 Pro `working_status` codes, and whether your EP3000 Plus populates the serial-number registers.
- **New device profiles.** If you have an EP3300, EP3300 TLV, or the fuller EP2000 Pro register set, a real register dump against your hardware (see the predecessor project's `ep3000_plus_debug.py` for the idea, or capture the vendor monitoring software's own Modbus traffic) is the fastest path to adding a `devices/epXXXX.py` profile -- the architecture is designed so this is additive, not a rewrite.
- **Modbus TCP/UDP gateway testing** against real hardware, since that path is implemented but not yet field-verified.
- **Brand assets** (`custom_components/must_ep30/brand/` is currently a placeholder -- see the README in that folder for exact requirements).

CI runs `hassfest`, HACS validation, ruff/black, and the pytest suite on every PR.

## License

MIT -- see [LICENSE](LICENSE). Copyright (c) 2020-2026 Bohdan Manko.

## Credits

- [`ep30_pro_mqtt`](https://github.com/mkbodanu4/ep30_pro_mqtt) -- the predecessor MQTT-bridge project this integration replaces. Its protocol parsing and register maps (including reverse-engineered reference files decompiled from the vendor's own monitoring software) are the ground truth this integration is built from.
- [`mukaschultze/ha-must-inverter`](https://github.com/mukaschultze/ha-must-inverter) -- an architectural inspiration for several patterns used here (async Modbus client design, config-flow connection-mode branching). No code is shared or forked from that project; its register map targets different MUST models and is documented as incompatible with the EP3000 Plus (see [Supported hardware](#supported-hardware)).
