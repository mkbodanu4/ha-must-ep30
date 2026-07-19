"""Integration tests for the config flow and options flow.

Protocol clients are replaced with fakes. Creating a config entry via the
flow manager also triggers real entry setup (async_setup_entry), which
constructs its client via devices/ep30_pro.py or devices/ep3000_plus.py --
a separate import site from config_flow.py's own client references used
during the validation step -- so both sites need patching for a full
create-entry flow to run without touching real serial/network I/O.
"""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.must_ep30.const import DOMAIN
from custom_components.must_ep30.protocol.base import MustPollResult
from custom_components.must_ep30.protocol.exceptions import MustConnectionError


class _FakeAsciiClient:
    def __init__(self, *args, **kwargs) -> None:
        self.closed = False

    async def async_connect(self) -> None:
        pass

    async def async_fetch(self) -> MustPollResult:
        return MustPollResult(values={}, raw={})

    async def async_close(self) -> None:
        self.closed = True


class _FailingAsciiClient(_FakeAsciiClient):
    last_instance = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        type(self).last_instance = self

    async def async_connect(self) -> None:
        raise MustConnectionError("simulated failure")


class _FakeModbusClient:
    probe_serial_number: str | None = None

    def __init__(self, *args, **kwargs) -> None:
        self.closed = False

    async def async_connect(self) -> None:
        pass

    async def async_fetch(self) -> MustPollResult:
        return MustPollResult(values={}, raw={})

    async def async_close(self) -> None:
        self.closed = True

    async def async_probe_serial_number(self) -> str | None:
        return self.probe_serial_number


def _patch_ascii_client(monkeypatch, client_cls) -> None:
    monkeypatch.setattr("custom_components.must_ep30.config_flow.AsciiSerialClient", client_cls)
    monkeypatch.setattr(
        "custom_components.must_ep30.devices.ep30_pro.AsciiSerialClient", client_cls
    )


def _patch_modbus_client(monkeypatch, client_cls) -> None:
    monkeypatch.setattr("custom_components.must_ep30.config_flow.ModbusClient", client_cls)
    monkeypatch.setattr("custom_components.must_ep30.devices.ep3000_plus.ModbusClient", client_cls)


async def test_user_step_shows_form(hass) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_full_flow_ep30_pro_serial_creates_entry(hass, monkeypatch) -> None:
    _patch_ascii_client(monkeypatch, _FakeAsciiClient)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model_choice": "ep30_pro_serial", "name": "My EP30"}
    )
    assert result["step_id"] == "serial"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "/dev/ttyUSB0"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "My EP30"
    assert result["data"]["profile"] == "ep30_pro"
    assert result["data"]["connection_kind"] == "serial"
    assert result["data"]["device"] == "/dev/ttyUSB0"


async def test_serial_step_cannot_connect_shows_error(hass, monkeypatch) -> None:
    _patch_ascii_client(monkeypatch, _FailingAsciiClient)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model_choice": "ep30_pro_serial"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "/dev/ttyUSB0"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert _FailingAsciiClient.last_instance.closed is True


async def test_full_flow_ep3000_plus_tcp_prefers_serial_number_unique_id(hass, monkeypatch) -> None:
    class _ClientWithSerialNumber(_FakeModbusClient):
        probe_serial_number = "1234567890"

    _patch_modbus_client(monkeypatch, _ClientWithSerialNumber)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model_choice": "ep3000_plus_tcp"}
    )
    assert result["step_id"] == "tcp"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "10.0.0.5", "port": 502, "slave_id": 10}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == "modbus-serialnum://1234567890"


async def test_full_flow_ep3000_plus_udp_falls_back_to_connection_unique_id(
    hass, monkeypatch
) -> None:
    _patch_modbus_client(monkeypatch, _FakeModbusClient)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model_choice": "ep3000_plus_udp"}
    )
    assert result["step_id"] == "udp"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "10.0.0.5", "port": 502, "slave_id": 10}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == "modbus-udp://10.0.0.5:502/10"


async def test_duplicate_device_path_aborts(hass, monkeypatch) -> None:
    _patch_ascii_client(monkeypatch, _FakeAsciiClient)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model_choice": "ep30_pro_serial"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "/dev/ttyUSB0"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model_choice": "ep30_pro_serial"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "/dev/ttyUSB0"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_updates_connection_unique_id(hass, monkeypatch) -> None:
    _patch_ascii_client(monkeypatch, _FakeAsciiClient)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model_choice": "ep30_pro_serial"}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {"device": "/dev/ttyUSB0"})
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "/dev/ttyUSB1"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["device"] == "/dev/ttyUSB1"
    assert entry.unique_id == "ascii-serial:///dev/ttyUSB1"


async def test_options_flow_general_step_updates_poll_interval(hass, monkeypatch) -> None:
    _patch_ascii_client(monkeypatch, _FakeAsciiClient)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model_choice": "ep30_pro_serial"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "/dev/ttyUSB0"}
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "general"}
    )
    assert result["step_id"] == "general"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"poll_interval": 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["poll_interval"] == 30


async def test_options_flow_battery_calibration_includes_adc_field_for_ep30_pro(
    hass, monkeypatch
) -> None:
    _patch_ascii_client(monkeypatch, _FakeAsciiClient)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model_choice": "ep30_pro_serial"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "/dev/ttyUSB0"}
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "battery_calibration"}
    )

    assert result["step_id"] == "battery_calibration"
    field_names = {str(key) for key in result["data_schema"].schema}
    assert "adc_battery_voltage_max" in field_names


async def test_options_flow_rejects_reversed_battery_thresholds(hass, monkeypatch) -> None:
    _patch_ascii_client(monkeypatch, _FakeAsciiClient)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"model_choice": "ep30_pro_serial"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "/dev/ttyUSB0"}
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "battery_calibration"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "charge_float_current": 1.0,
            "charge_full_voltage": 27.2,
            "charge_boost_voltage": 28.8,
            "charge_empty_voltage": 29.0,
            "discharge_full_voltage": 25.6,
            "discharge_empty_voltage": 11.0,
            "adc_battery_voltage_max": 17.35,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_calibration"}
