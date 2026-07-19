# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] - 2026-07-19

Initial release: native Home Assistant integration for MUST EP30 Pro (ASCII serial) and EP3000 Plus (Modbus RTU/TCP/UDP), replacing the standalone [`ep30_pro_mqtt`](https://github.com/mkbodanu4/ep30_pro_mqtt) MQTT-bridge project.

### Added
- UI-based config flow (no YAML) with real-device validation before entry creation.
- `DataUpdateCoordinator`-based polling with proper `unavailable`-on-error handling instead of crashing.
- EP30 Pro: 21 sensors + 8 binary sensors from the ASCII protocol (`F`/`Q1`/`G?`/`D`/`X` commands).
- EP3000 Plus: 24 sensors from the Modbus holding-register block 30000-30026, over serial, TCP, or UDP.
- Options flow: configurable poll interval, and an advanced battery-calibration step for the computed `Battery Level` sensor. Defaults are picked from the device's own reported nominal/nameplate battery voltage (12V and 24V lead-acid reference curves are built in; other bank sizes are linearly scaled from whichever is closer) instead of always assuming one fixed bank size.
- Reconfigure flow for changing connection details without deleting the entry.
- Diagnostics download support, including the last raw poll response (decoded ASCII fields or raw Modbus registers) for remote debugging.
- HACS packaging (`hacs.json`, CI validation workflows).

### Fixed (vs. the predecessor `ep30_pro_mqtt` project)
- EP30 Pro `ups_temperature`: corrected BCD-like decode (was a plain, incorrect float parse).
- EP30 Pro `working_status`: now decodes the full state space with a safe `unknown_code_N` fallback instead of a 2-value approximation. ASCII code `30` maps to `battery_priority` (decompiled-reference-confirmed); code `31` maps to `bypass`, backed by a real field report (observed with `utility_fail=0` and `output_voltage` tracking `input_voltage`, both characteristic of bypass/pass-through mode) plus the predecessor project's own `"BatteryPriority" if working_status == 30 else "Bypass"` fallback in `mqtt.py`, whose author had evidently already observed that "not 30" reliably means Bypass on this hardware. Mapped as its own explicit code rather than reviving that blanket fallback, so a genuinely different, still-unmapped state isn't mislabeled -- the remaining 4 documented states still fall back to `unknown_code_N`.
- EP30 Pro `ups_temperature` now carries `state_class: measurement` (previously omitted, so it wasn't included in HA long-term statistics).
- The battery-level curve's 24V reference `empty_voltage` was `11.0` in the predecessor project's own example config (used unchanged for both its 12V and 24V reference curves) -- correct for a 6-cell 12V bank (1.75V/cell x 6 = 10.5V) but wrong for a 12-cell 24V bank (1.75V/cell x 12 = 21V). Corrected to `21.0`.

### Fixed (internal, found during development)
- `manifest.json` initially required `pymodbus>=3.14.0`; Home Assistant core pins `pymodbus==3.13.1` exactly in its own `package_constraints.txt` (pymodbus doesn't follow semver, so HA locks it deliberately), which made every install fail with `RequirementsNotFound`. Pinned to `pymodbus>=3.13.1`, verified against that exact version -- no code changes needed, since all client APIs used are unchanged between 3.13.1 and 3.14.0.
- The ASCII serial client (`AsyncSerial`, unlike pyserial, has no `reset_input_buffer()`) could read stray bytes left over from a previous exchange as part of the fixed-size `D` command response, corrupting it and shifting the following `X` command's read by the same offset. Reproduced and confirmed via a real diagnostics capture plus a side-by-side reference capture from the predecessor project's `mqtt_debug.py`. Fixed with a bounded-timeout drain step before every command (mirroring the predecessor project's `reset_input_buffer()`) plus an explicit `flush()` after writing.
- EP30 Pro's `battery_voltage` sensor now displays with 2 decimal places (`suggested_display_precision=2`, matching `charger_battery_voltage`).

### Removed (vs. the predecessor project)
- MQTT Discovery and InfluxDB publishing -- HA entities are the data path now; see the README for the InfluxDB replacement path.
- The host-shutdown `subprocess` trigger -- replaced with a documented `shell_command:` + automation pattern (see README Automations section).
