# Astrion Remote (Home Assistant integration)

The single place to configure the Astrion HA100 remote app (`com.isaac.astrion`). It speaks the MQTT
contract in `docs/ARCHITECTURE.md`; the remote holds no HA token.

Targets Home Assistant **2026.10+** (tested with `pytest-homeassistant-custom-component==0.13.375` → HA 2026.10.4,
Python 3.14). Requires the core **MQTT** integration.

## Install
- HACS (custom repository, category *Integration*) or copy `custom_components/astrion_remote` to `/config/custom_components/`.
  HACS expects `custom_components/` at the repository root, so publish this folder as its own repo (or move it to the root).
- Settings → Devices & services → Add integration → *Astrion Remote*. Device id `ha100`, base topic `astrion/ha100`.
  The shipped default config (pages Now/Watch/Room/Music and the key map) is published immediately.

## Topics (base `astrion/<device_id>`)
| Topic | Dir | Retained | Handled as |
|---|---|---|---|
| `status` | app → HA | yes (LWT) | `binary_sensor.*_connected`; `offline` makes telemetry entities unavailable |
| `config` | HA → app | yes | full config JSON (`schema_version` 1) incl. computed `allow` |
| `state/<entity_id>` | HA → app | yes | `{"s":state,"a":{subset}}`, ≤4 msg/s per entity, empty payload when no longer referenced |
| `event` | app → HA | no | fires `astrion_remote_button` `{device_id, remote_id, key, gesture, ctx}` + device triggers |
| `call` | app → HA | no | executed only if allowlisted; refusals are logged at WARNING; no reply |
| `cmd` | HA → app | no | `reload`, `page <id>`, `toast <text>`, `update <url> <sha256>` |
| `telemetry` | app → HA | yes | sensors (see below) |

Telemetry JSON (partial updates merge): `{"battery":87,"charging":true,"screen":true,"page":"now","app_version":"0.3.1","wifi_rssi":-61,"last_key":"red","ts":...}`.
Accepted aliases: `battery_level`, `version`, `rssi`, `screen_on`; booleans may be `true/false`, `on/off`, `1/0`.

## Allowlist
Computed on every publish, never stored:
- every `ha` action in keys, key contexts and pages → `action:entity_id` (or bare `action` when it has no target);
- natural actions of entities rendered by sections: tiles with an `entity`, `segmented`, `slider`, `now_playing`
  (all natural services of the domain), `rocker`/`switch` (`turn_on`/`turn_off`/`toggle`).
`ha` actions may only target `entity_id`s (no area/device/label). `data.entity_id` is treated as a target.

## Options (Configure)
- **Keys**: key → gesture (tap/double/hold) → action type; `ha` uses the action selector (hold: optional *repeat*).
- **Pages**: YAML editor, validated against the section schema.
- **Timings & theme**: hold/double/keepalive ms, theme, calm, TV key topic, context entity, APK sub directory.
- **Import/export**: the whole config as YAML (`allow` is ignored on import and recomputed).
Every change republishes `config` (retained) and resyncs the state mirror without reloading the entry.

## App updates
Put `astrion-<version>.apk` plus `astrion-<version>.apk.sha256` (or `astrion-<version>.sha256`; `sha256sum` output is fine)
in `/config/astrion_remote/` (or the configured sub directory). Install verifies the file hash, issues a one-time URL
`<internal_url>/api/astrion_remote/apk/<32-byte token>` (one download, 10 minutes) and publishes `update <url> <sha256>`.
Set an internal URL under Settings → System → Network.

## Services
`astrion_remote.toast` (`text`), `astrion_remote.page` (`id`), `astrion_remote.reload`; optional `device_id` to target one remote.

## Tests
```
python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```
