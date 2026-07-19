# Contributing

Thanks for considering a contribution.

## Setup

```sh
git clone https://github.com/mkbodanu4/ha-must-ep30.git
cd ha-must-ep30
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements_test.txt
```

## Before opening a PR

```sh
ruff check custom_components tests
black custom_components tests
pytest
```

CI additionally runs `hassfest` and the HACS validation action -- both operate on the full manifest/translations structure and are easiest to trust via CI rather than trying to fully replicate locally.

## Adding a new device profile (e.g. EP3300, EP3300 TLV, full EP2000 Pro)

The architecture is designed so this is additive:

1. Add `custom_components/must_ep30/devices/epXXXX.py` modeled on `ep3000_plus.py` (Modbus) or `ep30_pro.py` (ASCII) -- a register/field table of `MustSensorEntityDescription`/`MustBinarySensorEntityDescription` entries, each with a `value_fn`.
2. Register it in `devices/__init__.py`'s `PROFILE_REGISTRY`.
3. Add a `MODEL_CHOICES` entry in `config_flow.py` so it's selectable during setup.
4. Add translations for any new `translation_key`s in `translations/en.json`.
5. Add tests mirroring `tests/test_devices_ep3000_plus.py`.

You'll need a real register map for your model. If you have hardware access, the predecessor project's `ep3000_plus_debug.py` (see [`ep30_pro_mqtt`](https://github.com/mkbodanu4/ep30_pro_mqtt)) shows the idea for dumping raw registers; the `mapping/modbus/*.txt` files in that repo (decompiled from the vendor's own monitoring software) are also a starting reference, though as noted in the README, register maps decompiled from vendor software should still be verified against real hardware before shipping -- they've been wrong before (see this project's two documented bug fixes to the EP30 Pro protocol).

## Reporting protocol/decoding bugs

Please attach a diagnostics download (Settings → Devices & Services → MUST EP30/EP3000 → ⋮ → Download diagnostics) to bug reports where possible -- it includes the last raw poll result, which is usually the fastest way to diagnose a decoding issue without hardware access.

## Code style

- Type hints throughout; `from __future__ import annotations` at the top of every module.
- No comments explaining *what* code does -- only *why*, when non-obvious (a protocol quirk, a HA API constraint, a deliberate deviation from the predecessor project).
- Keep `coordinator.py`, `sensor.py`, and `binary_sensor.py` generic -- device-specific logic belongs in `devices/*.py` and `protocol/*.py`.
