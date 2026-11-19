"""IR (0.8.0): tv.transport ir, tv.wake_via, the ir action and the Hisense IR code table."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.astrion_remote.const import HISENSE_IR, TV_TRANSPORTS, TV_WAKE_VIA
from custom_components.astrion_remote.default_config import DEFAULT_CONFIG
from custom_components.astrion_remote.schema import ACTION, DECORATED_ACTION, build_published_config, validate_config


def _with_tv(tv: dict) -> dict:
    return {**DEFAULT_CONFIG, "tv": tv}


def _with_key(action: dict) -> dict:
    return {**DEFAULT_CONFIG, "keys": {**DEFAULT_CONFIG.get("keys", {}), "sc1": {"tap": action}}}


def test_transport_ir_accepted():
    assert "ir" in TV_TRANSPORTS
    assert validate_config(_with_tv({"transport": "ir"}))["tv"]["transport"] == "ir"


@pytest.mark.parametrize("wake", TV_WAKE_VIA)
def test_wake_via_accepted_and_published(wake):
    config = validate_config(_with_tv({"wake_via": wake}))
    assert config["tv"]["wake_via"] == wake
    assert build_published_config(config)["tv"]["wake_via"] == wake


def test_wake_via_absent_is_not_added():
    assert "wake_via" not in validate_config(_with_tv({}))["tv"]


@pytest.mark.parametrize("bad", ["wifi", "", "IR", 1, None])
def test_wake_via_rejected(bad):
    with pytest.raises(vol.Invalid, match="wake_via"):
        validate_config(_with_tv({"wake_via": bad}))


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            {"type": "ir", "protocol": "nec", "address": "0xBF00", "command": "0x16"},
            {"type": "ir", "protocol": "nec", "address": "0xBF00", "command": "0x16"},
        ),
        (
            {"type": "ir", "protocol": "NEC", "address": 0xBF00, "command": 13, "hold": "repeat"},
            {"type": "ir", "protocol": "nec", "address": "0xBF00", "command": "0x0D", "hold": "repeat"},
        ),
        (
            {"type": "ir", "protocol": "nec", "address": "0x0", "command": "0xff", "hold": "none"},
            {"type": "ir", "protocol": "nec", "address": "0x0000", "command": "0xFF", "hold": "none"},
        ),
        (
            {"type": "ir", "protocol": "nec", "address": 0xFFFF, "command": 0},
            {"type": "ir", "protocol": "nec", "address": "0xFFFF", "command": "0x00"},
        ),
    ],
)
def test_ir_nec_accepted_and_normalised(given, expected):
    assert ACTION(given) == expected
    config = validate_config(_with_key(given))
    assert config["keys"]["sc1"]["tap"] == expected
    assert build_published_config(config)["keys"]["sc1"]["tap"] == expected


def test_ir_raw_accepted():
    pattern = [9000, 4500] + [562, 1688] * 32 + [562]
    action = {"type": "ir", "carrier": 38000, "pattern": pattern}
    assert ACTION(action) == action
    assert ACTION({"type": "ir", "carrier": 30000, "pattern": [1_000_000, 1_000_000]})["carrier"] == 30000
    assert ACTION({"type": "ir", "carrier": 60000, "pattern": [1]})["pattern"] == [1]


def test_ir_decorated_keeps_label():
    out = DECORATED_ACTION({"type": "ir", "protocol": "nec", "address": 1, "command": 2, "label": "Amp", "icon": "mdi:amp"})
    assert out["label"] == "Amp" and out["icon"] == "mdi:amp"
    with pytest.raises(vol.Invalid):
        ACTION({"type": "ir", "protocol": "nec", "address": 1, "command": 2, "label": "Amp"})


@pytest.mark.parametrize(
    ("bad", "match"),
    [
        ({"type": "ir"}, "needs protocol"),
        ({"type": "ir", "protocol": "nec", "address": 1}, "command"),
        ({"type": "ir", "protocol": "nec", "command": 1}, "address"),
        ({"type": "ir", "protocol": "rc5", "address": 1, "command": 1}, "protocol must be one of nec"),
        ({"type": "ir", "protocol": "nec", "address": 0x10000, "command": 1}, "out of range"),
        ({"type": "ir", "protocol": "nec", "address": -1, "command": 1}, "out of range"),
        ({"type": "ir", "protocol": "nec", "address": "BF00", "command": 1}, "hex string"),
        ({"type": "ir", "protocol": "nec", "address": "0xZZ", "command": 1}, "hex string"),
        ({"type": "ir", "protocol": "nec", "address": True, "command": 1}, "boolean"),
        ({"type": "ir", "protocol": "nec", "address": 1, "command": 0x100}, "out of range"),
        ({"type": "ir", "protocol": "nec", "address": 1, "command": 1.5}, "command"),
        ({"type": "ir", "protocol": "nec", "address": 1, "command": 1, "hold": "passthrough"}, "hold must be"),
        ({"type": "ir", "protocol": "nec", "address": 1, "command": 1, "extra": 1}, "extra"),
        ({"type": "ir", "carrier": 38000}, "pattern"),
        ({"type": "ir", "pattern": [1]}, "carrier"),
        ({"type": "ir", "carrier": 29999, "pattern": [1]}, "out of range"),
        ({"type": "ir", "carrier": 60001, "pattern": [1]}, "out of range"),
        ({"type": "ir", "carrier": "38000", "pattern": [1]}, "integer frequency"),
        ({"type": "ir", "carrier": 38000, "pattern": []}, "non-empty"),
        ({"type": "ir", "carrier": 38000, "pattern": "9000,4500"}, "non-empty list"),
        ({"type": "ir", "carrier": 38000, "pattern": [9000, 0]}, r"pattern\[1\]"),
        ({"type": "ir", "carrier": 38000, "pattern": [9000, -5]}, "positive"),
        ({"type": "ir", "carrier": 38000, "pattern": [9000, "x"]}, "positive"),
        ({"type": "ir", "carrier": 38000, "pattern": [1_000_000, 1_000_001]}, "2000001"),
        ({"type": "ir", "carrier": 38000, "pattern": [1], "protocol": "nec"}, "not both"),
        ({"type": "ir", "carrier": 38000, "pattern": [1], "hold": "repeat"}, "not both"),
    ],
)
def test_ir_rejected(bad, match):
    with pytest.raises(vol.Invalid, match=match):
        ACTION(bad)
    with pytest.raises(vol.Invalid):
        validate_config(_with_key(bad))


def test_hisense_table_matches_ir_md():
    codes = dict(HISENSE_IR)
    assert len(codes) == len(HISENSE_IR)  # unique names
    assert codes["Power"] == 0x0D and codes["OK"] == 0x15 and codes["Up"] == 0x16 and codes["Home"] == 0x94
    assert codes["Volume up"] == 0x44 and codes["Mute"] == 0x0E and codes["Input"] == 0x12 and codes["9"] == 0x09
    assert 0x1A not in codes.values()  # KEY_SLEEP stays out
    assert all(0 <= cmd <= 0xFF for cmd in codes.values())


def test_panel_offers_ir():
    import re
    from pathlib import Path

    js = (Path(__file__).parents[1] / "custom_components/astrion_remote/frontend/astrion-panel.js").read_text()
    block = re.search(r"const TV_WAKE_VIA = \[(.*?)\n\];", js, re.S).group(1)
    assert tuple(re.findall(r'\["(\w+)",', block)) == TV_WAKE_VIA
    assert '["ir", "IR code"]' in js and '["ir", "IR (point at the TV)"]' in js
    assert "ir_codes" in js and "Wake TV via" in js
