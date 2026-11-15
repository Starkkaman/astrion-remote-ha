"""Config flow tests."""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.astrion_remote.const import CONF_APK_DIR, CONF_CONFIG, DOMAIN


async def test_user_flow_defaults(hass, mqtt_mock):
    """Defaults create one entry with the shipped config."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": "ha100", "base_topic": "astrion/ha100/"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"device_id": "ha100", "base_topic": "astrion/ha100"}
    assert result["options"][CONF_APK_DIR] == ""
    config = result["options"][CONF_CONFIG]
    assert [p["id"] for p in config["pages"]] == ["now", "watch", "room", "music"]
    assert "allow" not in config  # computed at publish time
    await hass.async_block_till_done()


async def test_user_flow_duplicate(hass, mqtt_mock, config_entry):
    """Same device id twice aborts."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": "ha100", "base_topic": "astrion/other"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_invalid_input(hass, mqtt_mock):
    """Wildcards and bad ids are rejected."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": "ha100", "base_topic": "astrion/#"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base_topic": "invalid_topic"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": "HA 100!", "base_topic": "astrion/ha100"}
    )
    assert result["errors"] == {"device_id": "invalid_device_id"}


async def test_user_flow_requires_mqtt(hass):
    """Without MQTT the flow aborts."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "mqtt_not_configured"
