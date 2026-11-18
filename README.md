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
| `voice/start` | app → HA | no | `{"run","rate":16000}`: starts an Assist run on `assist_satellite.astrion_remote` (a new run cancels the old one) |
| `voice/audio/<run>` | app → HA | no | binary PCM16 mono 16 kHz chunks; unknown/finished runs ignored |
| `voice/end` | app → HA | no | `{"run","reason"}`: end of audio (HA also ends it 10 s after start) |
| `voice/stop` | HA → app | no | `{"run"}`: HA stopped listening (VAD end) |
| `voice/event` | HA → app | no | `{"run","stage":"listening/processing/responding/done/error","text"?,"tts_url"?,"error"?}` |

Telemetry JSON (partial updates merge): `{"battery":87,"charging":true,"screen":true,"page":"now","app_version":"0.3.1","version_code":9,"update_state":"idle","wifi_rssi":-61,"last_key":"red","ts":...}`.
Accepted aliases: `battery_level`, `version`, `rssi`, `screen_on`; booleans may be `true/false`, `on/off`, `1/0`.

## Allowlist
Computed on every publish, never stored:
- every `ha` action in keys, key contexts and pages → `action:entity_id` (or bare `action` when it has no target);
- natural actions of entities rendered by sections: tiles with an `entity`, `segmented`, `slider`, `now_playing`
  (all natural services of the domain), `rocker`/`switch` (`turn_on`/`turn_off`/`toggle`).
`ha` actions may only target `entity_id`s (no area/device/label). `data.entity_id` is treated as a target.

## Editor panel (sidebar "Astrion Remote", admins only)
- **Buttons**: the remote drawn as a grid of key chips (top row, voice, D-pad, menu, page, volume, colour keys,
  shortcut keys), each showing its tap action. Click a chip to set Tap / Double tap / Hold (TV key, Home Assistant
  action, go to page, event only, nothing, app command) and per-app overrides for values of `tv.context_entity`.
- **Pages**: add, rename, reorder and delete pages; add/reorder/delete sections and edit them per type.
- **YAML**: the whole config for import/export.
- Changes are validated live; **Save** validates, stores in the entry options and republishes (same path as the
  options flow). The panel works even while MQTT is down; the config is published once the remote is set up.
- If someone else saved in the meantime (another tab, a dashboard card), Save is refused and the footer shows
  "Changed elsewhere: Reload". Lint warnings (see below) show as an amber line under the key or section.

## Websocket API (stable contract for the panel and dashboard cards)
All commands are admin-only. `entry_id` is the Astrion Remote config entry; unknown ids fail with `not_found`.

| Command | Request | Result |
|---|---|---|
| `astrion_remote/config/get` | `entry_id` | `config`, `version`, `schema_version`, `keys` (`[{id, label, group}]`), `context_values`, `can_undo`, `warnings` |
| `astrion_remote/config/validate` | `entry_id`, `config` | `ok`, `errors` (`[{path, msg}]`), `warnings` (`[{path, msg}]`); stores nothing |
| `astrion_remote/config/set` | `entry_id`, `config`, optional `version` | `config` (as stored, normalised), `version` |
| `astrion_remote/config/reset` | `entry_id`, `parts` (any of `pages`, `keys`, `timings`, `theme`; default `["pages"]`) | `config`, `version`, `can_undo` |
| `astrion_remote/config/undo_reset` | `entry_id` | `config`, `version`, `can_undo` |
| `astrion_remote/tv_keys` | | `keys` (TV key names for pickers) |

**Version / optimistic concurrency.** `version` is the first 16 hex digits of the sha256 of the stored config's
canonical JSON (keys sorted, no whitespace); the same content always has the same version. Send the `version` you
loaded with `config/set`: if the stored config has changed since, the save fails with error code `stale_config`
("Someone else saved the remote config; reload and try again") and nothing is stored or published; reload with
`config/get` and reapply. Without `version` the save is last-write-wins (pre-0.6 behaviour). An invalid config
fails with `invalid_format` (call `config/validate` first for per-path errors).

**Event `astrion_remote_config_changed`** `{entry_id, version}` is fired on the HA event bus whenever an entry's
stored config changes, by any path: `config/set`, reset, undo, the services and the options flow (a save that
changes nothing fires nothing). Dashboard cards can subscribe (`subscribe_events` with that `event_type`) and
re-fetch with `config/get` when `version` differs from theirs.

**Warnings** are non-blocking hints (a config with warnings still saves), each `{path, msg}` like `errors`:
- an `ha` action calling a service that needs a target (HA's service description declares a target selector or an
  `entity_id` field; if HA has no description: `scene.turn_on`, `script.turn_on`, `light.*`, `switch.*`,
  `media_player.*`, `select.*`, `input_select.*` except `reload`) with no `target.entity_id` and no
  `data.entity_id`; `path` is the action, e.g. `["keys", "sc1", "tap"]`;
- a `segmented` / `slider` / `rocker` / `switch` section or a `choose` action whose entity is not in
  `hass.states`; `path` ends in `"entity"`, e.g. `["pages", 0, "sections", 2, "entity"]`.

## Options (Configure)
The options flow stays available as a fallback editor.

- **Keys**: key → gesture (tap/double/hold) → action type; `ha` uses the action selector (hold: optional *repeat*).
- **Pages**: YAML editor, validated against the section schema.
- **Timings & theme**: hold/double/keepalive ms, theme, calm, TV key topic, context entity, app update source
  (`github`/`folder`), GitHub repository, auto-install, APK sub directory, Home Assistant URL reachable from the remote (`base_url`, default `http://192.168.5.166:8123`).
- **Import/export**: the whole config as YAML (`allow` is ignored on import and recomputed).
Every change republishes `config` (retained) and resyncs the state mirror without reloading the entry.

## App updates
**GitHub (default source).** The update entity lists `GET /repos/<github_repo>/releases?per_page=20` every 6 hours and
on demand (`homeassistant.update_entity`), unauthenticated, with `If-None-Match` (ETag); on the 60/hour rate limit it
waits for `X-RateLimit-Reset` / `Retry-After` and keeps the last listing. It uses releases tagged `app-v*` (prereleases
included; drafts and other tags ignored) with an asset `astrion-<versionName>-<versionCode>.apk` **and** a matching
`.apk.sha256` asset; the highest versionCode wins. Versions show as `<name> (<code>)` and compare by versionCode (the
remote's telemetry `version_code`). Install downloads the APK to `/config/astrion_remote/`, checks it against the
`.sha256` asset, then continues as below. With **auto-install** on, a newer release is sent once per versionCode as soon
as the remote is online and idle. App releases are published by the app repo's `scripts/release-apk.sh` as
prereleases that are never "Latest", so HACS keeps offering only the integration's own releases.

**Folder.** Put `astrion-<version>.apk` plus `astrion-<version>.apk.sha256` (or `astrion-<version>.sha256`; `sha256sum` output is fine)
in `/config/astrion_remote/` (or the configured sub directory). Install verifies the file hash, issues a one-time URL
`<base_url>/api/astrion_remote/apk/<32-byte token>` (one download, 10 minutes) and publishes `update <url> <sha256>`.
`base_url` is the *Home Assistant URL reachable from the remote* option (Timings & theme; `http(s)://host[:port]`, no
path). Leave it empty to fall back to Home Assistant's internal URL (Settings → System → Network).

## Voice
The `voice` action (`{"type":"voice","target":"ha"|"tv"}`; default: voice key tap = `ha`, hold = `tv`). For `ha` the
remote streams its mic over MQTT to the **Assist satellite** "Astrion Remote"; pick the pipeline with the device's
"Assistant" select (or Settings → Voice assistants). `tts_url` is `base_url` (option) + HA's `/api/tts_proxy/<token>`,
requested as mp3. Upgrading from 0.2.x moves the voice key to the new default only if it was still the old default
(TV `SEARCH` on tap).

## Services
`astrion_remote.toast` (`text`), `astrion_remote.page` (`id`), `astrion_remote.reload`; optional `device_id` to target one remote.

`astrion_remote.reset_to_defaults` (`parts`: any of `pages`, `keys`, `timings`, `theme`; default `pages`) replaces those parts with the current defaults, stores and publishes; the previous config is kept in the entry options (`previous_config`, last one only) and `astrion_remote.undo_reset` restores it. Both take `entry_id` (optional with a single remote). The panel's Pages and Buttons tabs have the same "Reset … to default" / "Undo reset" buttons.

## Tests
```
python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```
