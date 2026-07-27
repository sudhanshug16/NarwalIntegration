# Narwal Robot Vacuum — Home Assistant Integration

A local-first, unofficial [Home Assistant](https://www.home-assistant.io/)
integration for Narwal robot vacuums that expose the Narwal WebSocket service
on the local network. It provides the established vacuum controls, sensors,
rooms, and live map without requiring a Narwal cloud login.

> **App parity is in progress, not complete.** This fork exposes a bounded
> subset of recovered official-app controls through model and capability
> profiles. New AX15 settings, schedule control, and motion actions have
> automated protocol/safety coverage but have not yet been physically validated
> on the target robot. See
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
| **Freo X10 Pro** (AX15) | Local-WebSocket support, community confirmed in [upstream #12](https://github.com/sjmotew/NarwalIntegration/issues/12) | Existing cleaning/map support plus capability-gated persistent settings, diagnostics, and bounded drive/go-to actions. New writes still need supervised physical validation. |
| **Freo Z Ultra** (CX7) | Not compatible with this local client | Port 9002 alone is insufficient; local broadcasts were not observed in [upstream #5](https://github.com/sjmotew/NarwalIntegration/issues/5). |
| **Freo X Ultra** (AX18/AX19) | Not compatible with this local client | Uses a different transport; see [upstream #4](https://github.com/sjmotew/NarwalIntegration/issues/4). |
| **Freo X Plus** (BX1) | Not compatible with this local client | Cloud-backed transport boundary; requires a separate provider, authentication, and validation effort. |
| **Narwal J-series** | Not compatible with this local client | Different local protocol or cloud transport, depending on model. |

Compatibility is determined by more than a model name. Product key, firmware,
capability response, and the observed physical result all matter. If port 9002
is open on another model, collect read-only diagnostics before testing writes.

## What works today

### Vacuum, dock, and map controls

- Start, pause, resume, stop, return to dock, and locate
- AX15 vacuum, mop, vacuum-then-mop, and vacuum-and-mop modes
- AX15 water, scrub, suction, route, and pass controls
- Room/segment cleaning with the selected parameters
- AX15 dust emptying plus mop wash, dry, and combined wash/dry
- Battery, charging, cleaning area/time, firmware, task, and station-state
  sensors
- Local map, room labels, dock marker, and live cleaning trail
- WebSocket push updates, reconnect, wake, heartbeat, and polling fallback

On the AX15, normal whole-house Start applies the visible clean settings to all
rooms on the current map. Other models retain the compatibility command.

### Capability-gated AX15 parity preview

The six Narwal domain actions are registered globally so automations have a
stable schema, but each write fails closed at execution time unless the target
identifies as Freo X10 Pro product key `CNbforyZWI`, advertises the required
capability, and, where applicable, is in a permitted live state. Persistent
entities are added once those identity/capability checks and the required live
snapshot become available, including after late discovery from an asleep
startup:

- persistent configuration entities for every currently typed `config/set`
  field: robot volume/language; cleaning, carpet, mop drying/wash, and station
  modes; child/pet/smart-clean settings; pad protection; dust collection and
  bag drying; hot-water and massive-dirty cleaning; speech/AI effects and
  recognition guards; off-dock power-off; return-to-main-map; and station
  lighting;
- `narwal.set_schedule_enabled`, which only toggles an existing schedule while
  preserving its plan, timing, and unknown fields; and
- `narwal.drive`, `narwal.go_to`, `narwal.stop_navigation`, and
  `narwal.stop_telecontrol`.

Configuration writes are single-field patches. They are blocked while the
robot or station is busy, require a known success result, and are followed by a
fresh `config/get`; an absent, differently typed, or mismatched read-back is
reported as an error.

All robot-, dock-, schedule-, and configuration-start actions share one
fail-fast action slot. Each refreshes status while it owns that slot, and every
new physical action refuses a client-owned or robot-reported point-navigation
task until it is explicitly stopped. The two stop actions deliberately bypass
that slot so an emergency stop is never queued behind a startup request.

`narwal.drive` is a 100–500 ms dead-man pulse, not an unbounded joystick. The
client enters joystick mode, limits publication to 10 Hz, and always attempts
repeated zero-velocity commands followed by manual mode off. `narwal.go_to`
uses normalized coordinates on the unrotated map image, requires the current
map revision, and rejects destinations outside the map or on uncleared,
occupied, or furniture-marked cells. Stop actions and disconnect cleanup cover
client-owned joystick and point-navigation work. They first invalidate pending
motion and send raw dead-man cleanup without waiting for a busy command lock.
The navigation stop uses the scoped NAVI cancel by default; it uses the Narwal
app's global `task/force_end` recovery only for a confirmed point-navigation
task or the AX15's observed stuck-go-to recovery state, never merely because a
Stop button was clicked while cleaning. Joystick release uses
zero-velocity/manual-off cleanup and never force-ends an unrelated task. A
force-end recovery remains blocked until a fresh status snapshot confirms that
point navigation/telecontrol has ended.

These controls are **not yet marked supported**: their protocol and failure
paths are tested, but their physical results on the target AX15 have not been
checked. Test them with a person beside the robot and
`narwal.stop_telecontrol` immediately available.

### Read-only parity foundation

- Full Narwal frame/header parsing, including multi-byte lengths and recovered
  response-routing metadata
- Topic-aware response matching when the robot supplies routing metadata, while
  retaining unrelated routed responses
- Capability decoding with named and raw field diagnostics
- Conservative `config/get` and current-clean-task decoders that retain unknown
  fields
- Profile-gated diagnostic inventories for current/saved cleaning plans,
  schedules, locally advertised consumable categories, saved/editable map
  metadata, component firmware, language/voice metadata, and the robot-local
  cleaning timeline
- Dynamic model/profile resolution for model-appropriate control surfaces

These decoders are code and diagnostic foundations. A decoded field, command
name, or advertised capability does not prove that a corresponding write is
safe. The local timeline is not parity with Narwal's separate cloud history,
and the consumable query does not provide remaining-life values.

### Freo X10 Pro room cleaning

The `narwal.clean_rooms` action exposes explicit AX15 room-clean parameters
without an experimental option or per-call validation flag:

Example:

```yaml
action: narwal.clean_rooms
target:
  entity_id: vacuum.narwal
data:
  rooms: [1]
  mode: vacuum_and_mop
  suction: standard
  water: normal
  mop_strength: normal
  passes: 1
```

### Narwal Lovelace control card

Version `1.1.0-beta.5` bundles a dependency-free `custom:narwal-control-card`
resource. It layers a revision-locked map interaction surface on the existing
Home Assistant actions instead of allowing a browser to speak Narwal's local
WebSocket protocol directly. It provides:

- click-to-go with a visible destination marker and an explicit confirmation
  button;
- selectable mapped rooms, using room IDs and the currently visible mode,
  suction, water, scrub, pass, and route settings;
- a hold-to-drive joystick that emits 100 ms bounded pulses and calls the
  emergency stop path on release, pointer loss, tab change, or window blur;
  and
- persistent Stop navigation and Emergency stop buttons.

The card automatically registers its frontend resource when the integration
loads. Add it as a Manual card in a Lovelace dashboard; a ready-to-paste
configuration and its safety model are in
[the Lovelace card guide](docs/NARWAL_LOVELACE_CARD.md).

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

This milestone deliberately withholds the following official-app areas:

- persistent settings for fields that do not have an explicit, typed entity
  and exact read-back path;
- schedule creation, deletion, plan/timing edits, or authored cron expressions;
- destructive map mutation or deletion, including virtual walls/no-go zones,
  room split/merge, restore, and boundary or safety-distance edits;
- physical camera/video, obstacle media, patrol, cruise, or remote-camera
  controls (the Home Assistant camera entity is a rendered map);
- arbitrary rectangle cleaning and gamepad support; the bundled UI supports
  only revision-locked click-to-go, a bounded hold-to-drive joystick, and
  mapped-room selection;
- lower-level station maintenance actions;
- pumps, drain/water exchange, detergent, or plumbing controls;
- firmware download, installation, upgrade, rollback, or factory reset; or
- cloud account, device binding/sharing, remote notifications, or cloud history
  operations.

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
- A capability bit describes firmware advertisement and may still vary in
  behavior between firmware releases.
- Capability/config-backed entities are added dynamically when late discovery
  succeeds. If the robot slept through startup discovery, wake it and allow the
  next coordinator update to add them; no integration reload is required.
- The route preset entity and `clean_rooms` route field both require the
  overlap-adjust capability.
- On Home Assistant versions without the native vacuum Segment API, use
  `narwal.clean_rooms`; the native clean-area/segment surface is unavailable.
- The newly exposed AX15 configuration, schedule, drive, and go-to paths still
  require supervised physical validation before unattended automation.
- Point navigation remains subject to the robot's own obstacle avoidance and
  arrival tolerance; it is not centimeter-accurate positioning.
- Maps can be stale until a new cleaning cycle refreshes them.
- Firmware updates may change the reverse-engineered protocol without notice.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Cannot connect during setup | Confirm the vacuum IP, power state, and reachability of port 9002 from Home Assistant. |
| Entities are unavailable | Wake the robot, close the Narwal app, and wait for Home Assistant to reconnect. |
| Map is missing or stale | Wake the robot; a new clean often refreshes the stored map. |
| Command receives conflict/not applicable | Wait until the robot and station are idle, then retry a supported compatibility action. |
| Mop controls are missing | Wake the robot, confirm it identifies as AX15 and advertises multi-zone cleaning, then allow the next coordinator update to add the controls. |

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
- Test newly exposed controls while someone can stop the robot if needed.
- A Narwal firmware update may break or change behavior at any time.

## Contributing

Testing reports and carefully redacted captures are welcome. Before promoting a
write to supported status, use the validation record checklist in
[docs/PARITY_STATUS.md](docs/PARITY_STATUS.md#validation-record-checklist).

## License

MIT
