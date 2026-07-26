# Narwal Robot Vacuum — Home Assistant Integration

A local-first, unofficial [Home Assistant](https://www.home-assistant.io/)
integration for Narwal robot vacuums that expose the Narwal WebSocket service
on the local network. It provides the established vacuum controls, sensors,
rooms, and live map without requiring a Narwal cloud login.

> **App parity is in progress, not complete.** This fork is adding protocol and
> read-only diagnostic coverage first, then enabling writes only after
> model-and-firmware-specific physical validation. See
> [App parity status](docs/PARITY_STATUS.md) for the evidence boundary and
> roadmap.

## Device compatibility

The local client connects to WebSocket port 9002. Models using another local
protocol or the Narwal cloud need a separate transport.

| Model | Local integration status | Parity status |
| --- | --- | --- |
| **Narwal Flow** (AX12) | Existing local-WebSocket integration | Baseline controls and map; advanced app writes are not assumed from other models. |
| **Narwal Flow 2** | Existing local-WebSocket integration | Read/protocol work can be tested, but no exact product-and-firmware pair is marked physically validated for parameterized writes in this milestone. |
| **Freo Z10 Ultra** (CX4) | Community-reported local-WebSocket compatibility | Advanced writes remain unvalidated and fail-closed. |
| **Freo X10 Pro** (AX15) | Local-WebSocket baseline, community confirmed in [upstream #12](https://github.com/sjmotew/NarwalIntegration/issues/12) | Read-only discovery plus a narrowly gated, supervised parameterized-clean validation service on one exact firmware. |
| **Freo Z Ultra** (CX7) | Not compatible with this local client | Port 9002 alone is insufficient; local broadcasts were not observed in [upstream #5](https://github.com/sjmotew/NarwalIntegration/issues/5). |
| **Freo X Ultra** (AX18/AX19) | Not compatible with this local client | Uses a different transport; see [upstream #4](https://github.com/sjmotew/NarwalIntegration/issues/4). |
| **Freo X Plus** (BX1) | Not compatible with this local client | Cloud-backed transport boundary; requires a separate provider, authentication, and validation effort. |
| **Narwal J-series** | Not compatible with this local client | Different local protocol or cloud transport, depending on model. |

Compatibility is determined by more than a model name. Product key, firmware,
capability response, and the observed physical result all matter. If port 9002
is open on another model, collect read-only diagnostics before testing writes.

## What works today

### Existing compatibility controls

- Start, pause, resume, stop, return to dock, and locate
- Room/segment cleaning through the established compatibility path
- Battery, charging, cleaning area/time, firmware, task, and station-state
  sensors
- Local map, room labels, dock marker, and live cleaning trail
- WebSocket push updates, reconnect, wake, heartbeat, and polling fallback

Normal whole-house start stays on its compatibility command. This fork does not
convert it into a guessed “all rooms” parameterized task.

### Read-only parity foundation

- Full Narwal frame/header parsing, including multi-byte lengths and recovered
  response-routing metadata
- Topic-aware response matching when the robot supplies routing metadata, while
  retaining unrelated routed responses
- Capability decoding with named and raw field diagnostics
- Conservative `config/get` and current-clean-task decoders that retain unknown
  fields
- Dynamic model/profile resolution used to keep unvalidated writes fail-closed

These decoders are code and diagnostic foundations. A decoded field, command
name, or advertised capability does not prove that a corresponding write is
safe.

### Supervised Freo X10 Pro validation

The `narwal.validate_parameterized_clean` service can send an app-derived parameterized room
clean only when all of these conditions hold:

- the robot identifies as AX15 product key `CNbforyZWI`;
- firmware is exactly `v01.03.10.03`;
- the required multi-zone capability is advertised;
- **Experimental parameterized cleaning** is enabled in the integration
  options; and
- that individual service call sets `confirm_unverified: true`.

This is a supervised validation tool, not a supported automation surface. Stay
near the robot with Stop available and verify its physical behavior. An
`ACCEPTED` response does not prove that every requested parameter was followed.
Unknown firmware remains disabled by default.

Example:

```yaml
action: narwal.validate_parameterized_clean
target:
  entity_id: vacuum.narwal
data:
  rooms: [1]
  mode: vacuum_and_mop
  suction: standard
  water: normal
  mop_strength: normal
  passes: 1
  confirm_unverified: true
```

## Installation

### HACS

1. Open **HACS** > three-dot menu > **Custom repositories**.
2. Add `https://github.com/sudhanshug16/NarwalIntegration` as an
   **Integration** repository.
3. Find **Narwal Robot Vacuum** and select **Download**.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/narwal/` into
   `config/custom_components/narwal/`.
2. Restart Home Assistant.

### Setup

1. Assign the vacuum a stable IP address in the router.
2. In Home Assistant, open **Settings > Devices & Services > Add Integration**.
3. Search for **Narwal**, enter the vacuum IP, and select its model.
4. Keep the Narwal mobile app closed while Home Assistant is connected; some
   devices permit only one active connection.

## Requirements

- A compatible vacuum and Home Assistant on the same local network
- WebSocket port 9002 reachable from Home Assistant
- Home Assistant 2025.1.0+ / Python 3.12+

## Deliberately unsupported parity areas

This milestone does not expose the following as supported writes:

- station washing, drying, dust collection, lighting, or maintenance actions;
- `config/set` settings;
- map mutation, virtual walls/no-go zones, boundary or safety-distance edits;
- camera, obstacle media, patrol, cruise, or telecontrol;
- pumps, drain/water exchange, detergent, or plumbing controls;
- firmware download, upgrade, or rollback; or
- cloud account, sharing, binding, notification, or history operations.

The Freo X Plus/BX1 cannot be supported by adding AX15 WebSocket topics. It
needs a separate cloud provider with secure credential handling and an
independent validation matrix.

For the complete implementation table, the planned map-edit safety workflow,
and the route toward app parity, read
[docs/PARITY_STATUS.md](docs/PARITY_STATUS.md).

## Known limitations

- Deep-sleep wake-up can be unreliable. Briefly opening the Narwal app may wake
  the robot; close it again before Home Assistant reconnects.
- The robot may allow only one WebSocket client at a time.
- Some reported values and commands vary by product key and firmware.
- A capability bit describes firmware advertisement, not validated behavior.
- Maps can be stale until a new cleaning cycle refreshes them.
- Firmware updates may change the reverse-engineered protocol without notice.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Cannot connect during setup | Confirm the vacuum IP, power state, and reachability of port 9002 from Home Assistant. |
| Entities are unavailable | Wake the robot, close the Narwal app, and wait for Home Assistant to reconnect. |
| Map is missing or stale | Wake the robot; a new clean often refreshes the stored map. |
| Command receives conflict/not applicable | Wait until the robot and station are idle, then retry a supported compatibility action. |
| Experimental service is unavailable | Confirm exact AX15 identity/firmware, capability advertisement, and the integration option. Do not bypass the profile gate. |

## Reporting issues

Open an issue in
[this fork](https://github.com/sudhanshug16/NarwalIntegration/issues) with:

- displayed model, product key, firmware, and dock/station model;
- Home Assistant and integration versions;
- whether the Narwal app was connected at the same time;
- relevant debug logs with device identifiers, tokens, account data, and map
  coordinates redacted; and
- the expected and observed physical behavior.

Do not post cloud credentials, access tokens, complete packet captures, or
unredacted home maps.

## Disclaimer

This project is unofficial, community-developed, and not affiliated with or
endorsed by Narwal. The protocol was reverse-engineered from local traffic and
the mobile application.

- Use it at your own risk; there is no warranty.
- Local-compatible models do not require a cloud account for this integration.
- Experimental validation must be supervised.
- A Narwal firmware update may break or change behavior at any time.

## Contributing

Testing reports and carefully redacted captures are welcome. Before promoting a
write to supported status, use the validation record checklist in
[docs/PARITY_STATUS.md](docs/PARITY_STATUS.md#validation-record-checklist).

## License

MIT
