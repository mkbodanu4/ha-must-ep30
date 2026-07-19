# Repository Guidelines

## Project Structure & Module Organization

The Home Assistant custom integration lives in `custom_components/must_ep30/`. Generic lifecycle and entity code belongs in `__init__.py`, `coordinator.py`, `sensor.py`, and `binary_sensor.py`. Keep device-specific decoding and entity descriptions in `devices/`; transport implementations belong in `protocol/`. User-facing strings are in `translations/en.json`, while integration metadata is in `manifest.json` and `hacs.json`.

Tests are under `tests/` and generally mirror source modules, for example `protocol/modbus.py` is covered by `tests/test_protocol_modbus.py`. Branding assets are in `custom_components/must_ep30/brand/`; documentation images belong in `docs/screenshots/`.

## Build, Test, and Development Commands

Create a Python 3.14 virtual environment and install development dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
```

Run the same core checks used by CI:

```sh
ruff check custom_components tests
black --check custom_components tests
pytest --cov=custom_components/must_ep30 tests
```

Use `black custom_components tests` to apply formatting. CI additionally runs Home Assistant `hassfest` and HACS validation.

## Coding Style & Naming Conventions

Use four-space indentation, type hints, `from __future__ import annotations`, and a 100-character line limit. Ruff enforces imports and common correctness rules; Black controls formatting. Use `snake_case` for modules, functions, entity keys, and translation keys; use `PascalCase` for classes.

Comments should explain protocol quirks, Home Assistant constraints, or design decisions—not restate the code. Keep coordinator and platform modules device-agnostic. Add model behavior through a `devices/epXXXX.py` profile and protocol behavior through `protocol/`.

## Testing Guidelines

Pytest uses `pytest-homeassistant-custom-component` with automatic asyncio mode. Name files `test_*.py` and tests `test_<behavior>`. Mock serial and Modbus transports; tests must not require physical hardware or network access. Add regression coverage for parsing failures, connection cleanup, config flows, entity identity, and derived values.

## Commit & Pull Request Guidelines

History currently uses short imperative subjects such as `Fix tests`; keep commits focused and descriptive. PRs should explain behavior changes, identify tested device models/transports, link relevant issues, and include diagnostics or sanitized raw registers for protocol changes. Include screenshots when config-flow or entity presentation changes. Run all local checks before requesting review.

## Security & Diagnostics

Never commit credentials, private host details, or device paths. Preserve diagnostics redaction and sanitize hardware captures before attaching them to issues.
