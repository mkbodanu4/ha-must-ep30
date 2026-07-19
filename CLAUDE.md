# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A native Home Assistant custom integration (HACS-distributable) for MUST EP30 Pro and EP3000 Plus inverter/chargers. It is the successor to a standalone MQTT-bridge script, [`ep30_pro_mqtt`](https://github.com/mkbodanu4/ep30_pro_mqtt) — that predecessor's protocol parsing and register maps are the validated ground truth this integration's decoding logic is ported from (see file-level docstrings in `protocol/` and `devices/` for exact provenance and the two bug fixes applied during the port).

The integration domain is `must_ep30`; all code lives under `custom_components/must_ep30/`.

## Commands

Set up the dev environment once:
```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements_test.txt
```

Run the full test suite (from repo root — `pyproject.toml`'s `testpaths` is `tests/`):
```sh
pytest
```

Run a single test file or test:
```sh
pytest tests/test_protocol_ascii_serial.py
pytest tests/test_protocol_ascii_serial.py::test_parse_q1_temperature_bcd_decode
```

Lint / format:
```sh
ruff check custom_components tests
black custom_components tests        # add --check to verify without rewriting
```

There is no local `hassfest` — it's a dev-only script that lives in the `home-assistant/core` git repo, not the `homeassistant` PyPI package. CI runs it via `home-assistant/actions/hassfest@master` (see `.github/workflows/validate.yml`); don't try to install/run it locally.

Tests use [`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component), which blocks real network sockets during tests (`pytest_socket`). Any test that exercises a full config-entry setup will fail with `SocketBlockedError` unless the protocol client classes are monkeypatched at **both** their import sites — see "Testing gotcha" below.

## Architecture

One `DataUpdateCoordinator` per config entry, talking to whichever device through a shared protocol-client interface — the coordinator, and both entity platforms, have zero knowledge of which underlying protocol is in use:

```
protocol/base.py        MustDeviceClient ABC (async_connect / async_fetch / async_close),
                         MustPollResult dataclass (values dict + raw dict)
protocol/ascii_serial.py  AsciiSerialClient — EP30 Pro, serialx AsyncSerial, 5-command
                           sequence (F/Q1/G?/D/X)
protocol/modbus.py         ModbusClient — EP3000 Plus, pymodbus async client, one of
                            AsyncModbusSerialClient/TcpClient/UdpClient chosen by
                            connection_kind, single 26-register holding-register read
                            at address 30000

devices/models.py       DeviceProfile dataclass, MustSensorEntityDescription /
                         MustBinarySensorEntityDescription (EntityDescription + value_fn),
                         shared battery_level_curve() pure function
devices/ep30_pro.py      EP30 Pro's DeviceProfile: 21 sensors + 8 binary sensors
devices/ep3000_plus.py   EP3000 Plus's DeviceProfile: 24 sensors
devices/__init__.py      PROFILE_REGISTRY: dict[profile_key -> DeviceProfile]

coordinator.py           MustEp30DataUpdateCoordinator — calls client.async_fetch(),
                          maps I/O errors to UpdateFailed, then runs the active
                          profile's optional compute_values(result, entry.options) hook
entity.py                MustEp30Entity base — has_entity_name, unique_id, DeviceInfo
sensor.py / binary_sensor.py   Fully generic platforms: entities are created directly
                                from coordinator.profile.sensors /
                                coordinator.profile.binary_sensors — never edit these
                                to add device-specific behavior, that belongs in devices/
config_flow.py           Model+connection selection -> serial/tcp/udp step -> real-read
                          validation -> unique_id assignment -> entry creation.
                          Also the reconfigure flow and the options flow
                          (poll interval + battery-calibration steps)
```

**Adding a new device model** (e.g. EP3300) means: a new `devices/epXXXX.py` with a `DeviceProfile`, a `PROFILE_REGISTRY` entry, a `MODEL_CHOICES` entry in `config_flow.py`, and translations — never changes to `coordinator.py`, `sensor.py`, or `binary_sensor.py`. See `CONTRIBUTING.md` for the full checklist.

**Why `compute_values` exists on `DeviceProfile`**: some sensors (`battery_level`, `output_power`, `charger_battery_voltage`) need config-entry *options* (user-configurable battery-curve thresholds) that a plain `value_fn: Callable[[MustPollResult], StateType]` can't see. The coordinator runs `profile.compute_values(result, entry.options)` after every successful fetch and merges the result into `result.values`, so `value_fn` for those sensors ends up being a plain dict lookup like everything else.

**Error handling model**: protocol clients never let transport-library exceptions escape — they catch pymodbus/serialx exceptions and re-raise as `protocol/exceptions.py`'s `MustConnectionError`/`MustProtocolError`. The coordinator catches those (plus a defensive `OSError`/`TimeoutError`/`ModbusException`) and raises `UpdateFailed`, so a disconnected device shows as `unavailable` entities rather than crashing the integration; the connection self-heals on the next poll.

**EP30 Pro's partial-failure tolerance**: the ASCII protocol issues 5 separate commands per poll. If a secondary command (`F`/`G?`/`D`/`X`) fails, only its keys are missing from that cycle's values (those entities read `None` for one cycle). If `Q1` (which carries most sensors, including all binary sensors) fails, or all 5 fail, the whole poll raises `MustProtocolError`. EP3000 Plus's Modbus read is a single atomic block, so any failure there fails the whole poll — see `protocol/ascii_serial.py`'s `_fetch` docstring/comments for the exact accounting.

## Testing gotcha: two import sites per client class

`config_flow.py` imports `AsciiSerialClient`/`ModbusClient` directly (for setup-time validation), and `devices/ep30_pro.py` / `devices/ep3000_plus.py` import them separately again (for the `client_factory` used by real entry setup). Creating a config entry via the flow manager in a test also triggers real `async_setup_entry`, which uses the *second* import site. Monkeypatching only `custom_components.must_ep30.config_flow.AsciiSerialClient` will pass config-flow-only assertions but then blow up with `pytest_socket.SocketBlockedError` during the automatic post-creation setup. `tests/test_config_flow.py` has `_patch_ascii_client()`/`_patch_modbus_client()` helpers that patch both sites — use them for any test that expects a `CREATE_ENTRY` result to actually finish loading.

## `manifest.json` requirements must respect HA's package_constraints.txt

Home Assistant installs a custom integration's `requirements` under its own [`package_constraints.txt`](https://github.com/home-assistant/core/blob/dev/homeassistant/package_constraints.txt), which pins some libraries to an *exact* version regardless of what a newer `pip install` would resolve on its own — `pymodbus` is one of these (HA pins it exactly, because pymodbus doesn't follow semver). A requirement lower bound that excludes HA's pinned version (e.g. `pymodbus>=3.14.0` when HA pins `3.13.1`) makes `pip install` fail under that constraint file, and HA reports this as a generic `RequirementsNotFound` at config-flow time — not an obvious "version conflict" message. Before bumping a lower bound in `requirements`, check the current `package_constraints.txt` for that package and keep the floor at or below whatever HA pins, then verify against that *exact* pinned version locally (not just "some version `>=X`") since a passing test run against a newer version doesn't prove compatibility with the one HA will actually install.

## Known-unverified protocol details

A few decoding choices are ported from decompiled vendor reference sources rather than confirmed against live hardware — see the README's "Known-unverified details" section and the `WORKING_STATUS_MAP` comment in `protocol/ascii_serial.py` before "completing" partial enum tables (e.g. EP30 Pro `working_status` has codes `30`/`31` mapped -- `30` decompiled-reference-confirmed, `31` field-report-based; don't invent the other four state codes without similar evidence).
