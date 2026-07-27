# Narwal app parity status

This document separates five different claims: inherited compatibility,
Home Assistant exposure, read-only diagnostics, protocol decoding, and
physical validation. The long-term goal is broad Narwal app parity without
turning APK symbols or a successful protocol response into an unsupported
safety claim.

## Status terms

- **Supported**: exercised on the stated product and firmware, with the
  physical result checked.
- **Compatibility path**: inherited behavior used by the integration today.
  It may work on several local-WebSocket models, but is not a new parity claim.
- **Exposed**: available as a Home Assistant entity/action and covered by
  automated protocol and guard tests, but not yet physically validated on the
  stated robot.
- **Diagnostic**: queried by the integration and surfaced read-only in Home
  Assistant. It does not authorize a related write.
- **Codec only**: the wire structure can be decoded or encoded in the Python
  library, but the integration does not currently query or expose it.
- **Withheld**: intentionally absent because the transport, semantics, recovery
  behavior, or physical safety boundary is not established.

Product identity, advertised capabilities, the live response shape, and robot
state determine which controls are shown. A capability bit is an advertisement,
not proof that a command has the expected physical effect. The current AX15
profile gates are based on product key and capabilities, not a completed
firmware-validation whitelist.

## Current parity matrix

No new AX15 write added in this parity pass is marked **Supported** yet. The
tests verify framing, payloads, capability/profile gates, response handling,
read-back, and cleanup paths; a supervised physical AX15 validation is still
required.

| Area | Current Home Assistant surface | Status and boundary |
| --- | --- | --- |
| Basic vacuum control | Start, pause, resume, stop, return to dock, locate, state, battery, and cleaning statistics | **Compatibility path** |
| Parameterized cleaning | AX15 modes, suction, water, scrub, passes, capability-gated route controls, `narwal.clean_rooms`, and mapped-room selection in the bundled Lovelace card | **Exposed** when AX15 advertises multi-zone cleaning; physical parameter behavior still needs checking |
| Dock actions | AX15 dust empty, mop wash/dry, combined wash/dry, and capability-gated bag-dry actions | **Exposed** while docked; no claim for lower-level maintenance or plumbing |
| Persistent settings | Typed select/switch/number entities backed by one-field `config/set` plus exact `config/get` read-back | **Exposed** for AX15 with upload-configuration capability and a matching live field; supervised physical validation pending |
| Cleaning plans | Current and saved plan metadata diagnostic sensor | **Diagnostic**, capability-gated and read-only |
| Schedules | Schedule metadata diagnostic sensor plus `narwal.set_schedule_enabled` for an existing task | Inventory is **Diagnostic**; the narrow enable toggle is **Exposed** with exact read-back; create/delete/timing/cron edits are **Withheld** |
| Consumables | Maintenance and replacement category diagnostic sensor | **Diagnostic**; local remaining-life values are not established |
| Active map | Rendered map camera, rooms, dock, robot trail, revision metadata, exact-frame room markers, and the bundled Lovelace map card | **Compatibility path** plus exposed map interaction UI; physical navigation result still needs checking |
| Saved/editable map inventory | Map inventory diagnostic with saved-map summaries, editable-map metadata, and supplementary-update state | **Diagnostic**, capability-gated and read-only; no map geometry is changed |
| Firmware/language/voice metadata | Device metadata diagnostic with component firmware hierarchy, configured/supported languages, and current voice-package metadata | **Diagnostic**, with each query capability-gated and read-only |
| Local timeline/report | Recent robot-local timeline diagnostic plus a strict clean-report decoder | Timeline is **Diagnostic**; richer clean-report parsing is **Codec only**; neither is Narwal cloud history |
| Manual drive and point navigation | Bounded `drive`, revision-locked `go_to`, stop actions, plus a hold-to-drive/click-to-go Lovelace card | **Exposed** on AX15 with telecontrol-heartbeat capability; no supervised motion result has been recorded |
| Physical camera and patrol | None; the camera entity above is only a map rendering | **Withheld** |
| Destructive map writes | None | **Withheld** |
| Pump/plumbing, firmware writes, factory reset | None | **Withheld** |

The clean-report decoder remains codec-only until incoming reports are safely
connected to coordinator state and a compact Home Assistant diagnostic. Merely
storing a field on `NarwalState` is not enough.

## Implemented milestone details

### Existing compatibility behavior

The normal Home Assistant controls keep the established local-WebSocket paths:

- start, pause, resume, stop, return to dock, and locate;
- AX15 room/segment cleaning with explicit mode, water, scrub, suction, route,
  and pass settings;
- local status, battery, cleaning statistics, map, rooms, and live updates;
- reconnect, wake, heartbeat, and polling behavior.

On AX15, normal whole-house Start applies the visible parameters to all mapped
rooms. Other models continue to use the established compatibility command.

### Protocol foundation

The client now understands the recovered WebSocket envelope:

```text
0x01 | protobuf-varint header length | protobuf Header | protobuf body
```

The header codec handles URL, UUID, source, URL ID, and nested response routing
properties. When a response includes routing metadata, the client can compare
its response URL with the expected topic and retain routed responses that do
not match the command currently waiting.

This is correlation infrastructure, not a claim that every robot or endpoint
supplies a usable correlation value. Legacy responses without routing metadata
still require the serialized compatibility behavior.

### Read-only discovery and diagnostics

Home Assistant currently exposes diagnostic sensors for:

- advertised features/capabilities with exact raw field values;
- the resolved product/firmware capability profile;
- the `config/get` snapshot;
- the cached current clean task;
- current and saved cleaning-plan metadata;
- existing schedule metadata, leaving cron text uninterpreted;
- locally advertised consumable maintenance/replacement categories;
- saved/editable map summaries and supplementary-update state;
- robot, station, and vision firmware component metadata;
- configured/supported languages and current voice-package metadata; and
- up to 20 recent, compact robot-local timeline events.

Unknown fields are retained by the underlying conservative codecs where their
schema permits it. Diagnostics are deliberately compact and may omit opaque
geometry or nested protocol objects. Consumable remaining life appears to be a
separate cloud-backed surface; this local query only proves category
availability. The local timeline does not establish Narwal cloud-history
retention or API semantics.

### AX15 cleaning and dock controls

Freo X10 Pro product key `CNbforyZWI` exposes the recovered clean parameter
surface whenever multi-zone cleaning is advertised:

- vacuum, mop, vacuum-then-mop, and vacuum-and-mop;
- suction, water, scrub strength, route, and pass count;
- selected-room or all-room cleaning through `narwal.clean_rooms`;
- dust emptying and mop wash/dry station actions.

Flow 2 retains its compatibility path until its distinct payload behavior is
implemented.

### Persistent AX15 configuration

The integration creates only entities that satisfy all applicable gates:

1. product key is `CNbforyZWI` (AX15);
2. the robot advertises upload-configuration support;
3. the field exists in the live `config/get` snapshot; and
4. a field-specific capability is advertised where the official app defines
   one.

The current typed entity set covers every field accepted by the conservative
`config/set` codec: robot volume/language; mop drying strength and wash
frequency; robot/station cleaning modes; carpet and corner behavior; obstacle
avoidance (**Smart** or **Safer**, not **Off**); child/pet/smart-clean settings;
moisture-pad protection; normal, smart, and quiet dust collection; robot-bag
drying; hot-water and massive-dirty cleaning; off-dock auto power-off;
return-to-main-map; AI/speech settings; object-recognition guards; and station
lighting.

Each operation sends one field under a client write lock. Before the write, the
coordinator wakes the robot, refreshes status, and rejects cleaning, pause,
return-to-dock, or active station work. The client requires a known success
result, performs a fresh `config/get`, and compares the exact typed value. A
read-back error does not imply automatic rollback; the caller should inspect the
new diagnostic snapshot before retrying.

Configuration, schedule, cleaning, dock, and motion startups also share one
fail-fast coordinator action slot. The status refresh, state guard, and command
remain inside it so a competing startup cannot slip between them. Once a
point-navigation startup succeeds and releases that short slot, later physical
or persistent actions still refresh status and reject both client-owned and
robot-reported telecontrol until navigation is explicitly stopped. Emergency
stop/cancel paths intentionally bypass the slot rather than wait behind it.

Capability/config-backed entities are added once per platform when discovery
first proves their gates. If an asleep robot misses the initial capability or
`config/get` request, later coordinator retries add newly discovered entities
without an integration reload.

### Bounded telecontrol and point navigation

These actions require AX15 identity plus the advertised
telecontrol-heartbeat capability and exactly one authorized Narwal target.
They refresh live status and reject unknown/error state, cleaning, pause,
return-to-dock, and station activity.

- `narwal.drive` accepts non-zero linear/angular values from -10 to 10 for a
  100–500 ms pulse. It is blocked while docked. The client confirms joystick
  mode, publishes at no more than 10 Hz, then attempts three zero-velocity
  sends and manual mode off even after failure.
- `narwal.go_to` refreshes the active map, requires the exact
  `navigation_map_revision` from the map camera, converts normalized unrotated
  image coordinates back to robot-world coordinates, and rejects out-of-map,
  non-floor, occupied, furniture-marked, or one-cell-clearance failures.
- `narwal.stop_navigation` immediately sends raw NAVI-cancel/zero/manual-off
  safety frames, then sends the typed point-navigation cancel. If the client or
  robot confirms point navigation (or AX15's observed stuck-go-to recovery
state), it uses the mobile app laboratory tool's `task/force_end` recovery
and confirms manual mode off plus a fresh non-telecontrol status snapshot. It
never force-ends ordinary cleaning merely because the Stop navigation button
was clicked.
- `narwal.stop_telecontrol` attempts the manual dead-man cleanup immediately.
  It uses force-end only for client-owned or robot-reported point navigation;
  a joystick release alone cannot force-end an unrelated task. Disconnect
  cleanup also covers client-owned motion.

Do not rely on the vacuum entity's normal Stop action for telecontrol: it sends
the cleaning-stop command. Use `narwal.stop_telecontrol` for the combined
emergency path, or `narwal.stop_navigation` for point navigation specifically.

The bundled `custom:narwal-control-card` now provides a revision-aware
click-to-go map, mapped-room selection, and a hold-to-drive dead-man joystick
on top of these actions. It holds a map click until an explicit confirmation,
invalidates it when the rendered map revision changes, and never sends a
browser-to-robot connection. The joystick sends only 100 ms service pulses;
pointer release/cancel/lost capture, window blur, tab hiding, card teardown,
and its permanent Emergency stop all invoke `narwal.stop_telecontrol`.
It is not a gamepad or unbounded-motion surface, and point-navigation accuracy
remains subject to the robot's obstacle avoidance and arrival tolerance.

Mapped rooms are inferred from exact room-floor cells in the cached map frame.
The integration deliberately does not offer arbitrary drawn cleaning rectangles:
the AX15 payload and coordinate convention for those official-app controls have
not been recovered or physically validated.

### Narrow schedule update

The schedule sensor exposes the existing task ID and raw cron text. The only
schedule write is `narwal.set_schedule_enabled`: it starts from a mandatory
fresh inventory fetch, copies the complete decoded schedule, changes only its
enabled Boolean, preserves unknown fields, requires a known schedule-success
response, refetches the inventory, and verifies full-object equality against
the expected schedule. Creating, deleting, retiming, changing plan contents,
or authoring cron remains withheld.

### Room-cleaning compatibility details

The route preset entity and the optional `narwal.clean_rooms` route value both
require the `OVERLAP_ADJUST` capability; calls with a route fail closed when the
robot does not advertise it. Home Assistant's native clean-area/segment feature
is available only when the installed Home Assistant version provides its
Segment API; `narwal.clean_rooms` remains the portable room-cleaning action.

## Intentionally withheld areas

| Area | Current position |
| --- | --- |
| Station actions | AX15 dust emptying and mop wash/dry are exposed. Station lighting is a live-snapshot- and capability-gated persistent setting; lower-level maintenance controls remain unimplemented. |
| Other configuration | Every field in the conservative typed config codec now has an entity. Untyped fields, missing live fields, and fields without required advertised capabilities remain unexposed. |
| Schedule CRUD/cron | Create, delete, plan/timing edits, and cron authoring are not exposed. Only an existing schedule's enabled Boolean has the bounded path above. |
| Map mutation | No-go zones, virtual walls, room split/merge, furniture, floor material, map selection, restore, delete, and boundary/safety-distance edits are not implemented as writes. |
| Camera and patrol | Physical snapshot/video, LED, obstacle media, patrol, cruise, and remote-camera controls are absent. Protocol names or APK code are not sufficient evidence. |
| Other app controls | Saved-plan execution/editing, live mop-humidity control, easy-clean, consumable remaining-life/reset, and several lower-level client commands remain unwired. |
| Pump and plumbing | Water exchange, pump, drain, detergent, and related station maintenance writes are not supported. Incorrect commands can have physical consequences. |
| Firmware and reset | Download, install, upgrade, rollback, factory reset, and other firmware-management writes are not supported. |
| Cloud account operations | Account, device binding, sharing, remote notification, and cloud history operations are outside the local milestone. |

Every currently typed `config/set` field has a matching select, switch, or
number entity, but entities are created only after the corresponding live field
and any direct capability gate are present. Obstacle-avoidance **Off** remains
deliberately omitted.

### Map safety-distance request

The current integration reads and renders the robot's map; it does not safely
edit navigation clearance. Increasing a “safe area” by one inch at selected
locations first requires identifying whether the app stores a no-go polygon,
an obstacle margin, a room boundary, or a firmware navigation parameter. The
coordinate system, units, map revision checks, and rollback behavior must be
confirmed before any map write is attempted.

The one-cell clearance check used by `narwal.go_to` is only a fail-closed
destination-selection guard. It neither changes the saved map nor represents a
one-inch configurable safety margin.

The safe validation sequence is:

1. capture the map and app request before the edit;
2. make one reversible edit in the official app;
3. capture the request and the returned map revision;
4. decode coordinates and units without transmitting from this client;
5. add backup, read-back, and rollback support;
6. perform a supervised one-point validation before exposing any UI.

## Model and transport boundaries

AX15 and other compatible models expose the local WebSocket service on port
9002. Shared topic names do not imply shared payload meanings, so advanced
writes currently remain profile-gated by AX15 product key plus advertised
capabilities. There is no completed firmware-validation whitelist.

The Freo X Plus/BX1 is a separate boundary. Available evidence points to a
cloud-backed transport rather than this local WebSocket protocol. It cannot
reach app parity by adding more AX15 topics to the current client. Supporting
it requires a separate transport/provider layer, regional cloud endpoint and
authentication research, secure credential handling, and its own validation
matrix. Local AX15 work must not silently fall back to the cloud.

## Roadmap to app parity

1. **Build the protocol matrix.** Record product key, hardware model, firmware,
   app version, capability response, request topic, response shape, and
   observed physical result for every test.
2. **Validate the new AX15 controls one at a time.** Start with a benign
   configuration field, then schedule enable/disable, emergency stop, one
   minimum-duration drive pulse, and one nearby point-navigation target.
3. **Promote only recorded product/firmware pairs.** Keep new writes marked
   Exposed until their physical result, timeout behavior, read-back, and
   Stop/recovery path have been observed.
4. **Validate and extend read-only parity.** Exercise the new map,
   firmware/language/voice, and local-timeline queries on AX15 fixtures and
   hardware; then connect the clean-report decoder without implying
   cloud-history parity.
5. **Validate deliberate motion UI.** Supervise the bundled revision-aware
   click-to-go map and hold-to-drive dead-man joystick on an AX15, then consider
   gamepad support only after its browser disconnect/release behavior is tested.
6. **Capture schedule CRUD before implementing it.** Preserve unknown fields and
   do not infer cron semantics from one locale or app version.
7. **Handle map edits as transactions.** Preserve the original map and revision,
   validate geometry and units, write once, read back, and provide rollback.
8. **Research withheld physical systems separately.** Camera/patrol, pumps,
   plumbing, firmware, and reset paths need independent safety and recovery
   plans.
9. **Add a separate BX1/cloud provider if viable.** Keep cloud authentication,
   rate limits, regional behavior, and privacy separate from the local client.
10. **Harden release behavior.** Add replay fixtures, migration tests,
    diagnostics redaction, and per-profile regression coverage.

## Validation record checklist

Before changing an operation from **Exposed** to **Supported**, record:

- product key, displayed model, firmware, dock/station model, and app version;
- capability fields and complete raw response;
- exact request and response with identifiers or secrets removed;
- robot and station preconditions;
- expected and observed physical behavior;
- read-back result, failure/timeout behavior, and recovery procedure;
- confirmation that unrelated product keys do not receive the command.

For the first telecontrol validation, use an open floor with the robot undocked
and a person beside it. Verify emergency stop before sending motion, use the
smallest non-zero velocity and 100 ms duration, confirm that release stops the
robot, and then test a nearby clear go-to target with
`narwal.stop_telecontrol` immediately available. Do not begin with unattended
automation or a dashboard that repeats drive pulses.

This project is unofficial and reverse-engineered. Firmware updates can change
behavior without notice, so older validation must not automatically authorize a
new firmware version.
