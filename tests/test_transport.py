"""tv.transport (app 0.6 key route) in the config schema."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.astrion_remote.const import TV_TRANSPORTS
from custom_components.astrion_remote.default_config import DEFAULT_CONFIG
from custom_components.astrion_remote.schema import build_published_config, validate_config


def _with_tv(tv: dict) -> dict:
    return {**DEFAULT_CONFIG, "tv": tv}


@pytest.mark.parametrize("transport", TV_TRANSPORTS)
def test_transport_accepted_and_published(transport):
    config = validate_config(_with_tv({"transport": transport}))
    assert config["tv"]["transport"] == transport
    assert build_published_config(config)["tv"]["transport"] == transport


def test_transport_absent_means_auto_and_is_not_added():
    config = validate_config(_with_tv({}))
    assert "transport" not in config["tv"]


@pytest.mark.parametrize("bad", ["usb", "", "ATV", 1, None])
def test_transport_rejected(bad):
    with pytest.raises(vol.Invalid):
        validate_config(_with_tv({"transport": bad}))


def test_panel_key_route_matches_schema():
    """The panel's Key route options are exactly the schema's, with the Bluetooth Wi-Fi warning."""
    import re
    from pathlib import Path

    js = (Path(__file__).parents[1] / "custom_components/astrion_remote/frontend/astrion-panel.js").read_text()
    block = re.search(r"const TV_TRANSPORTS = \[(.*?)\n\];", js, re.S).group(1)
    assert tuple(re.findall(r'\["(\w+)",', block)) == TV_TRANSPORTS
    assert "Bluetooth slows the remote's Wi-Fi while connected" in js
    assert "this._renderRemoteSettings()" in js
