# Narwal app parity status

This document records what this fork can safely claim today, what has only
been decoded, and what still requires physical validation. The goal is broad
Narwal app parity without turning reverse-engineered message names into
unreviewed writes to a robot, station, map, or firmware.

## Status terms

- **Supported**: exercised on the stated product and firmware, with the
  physical result checked.
- **Compatibility path**: inherited behavior used by the integration today.
  It may work on several local-WebSocket models, but is not a new parity claim.
- **Decoded**: the wire structure can be parsed and retained for diagnostics.
  This does not prove that a related write is supported or safe.
- **Unvalidated**: a topic or payload is known or suspected, but this fork does
  not expose it as a normal control.

Capability bits are advertisements, not authorization. A bit alone never
enables a write. Write support must also be tied to an exact product key and
firmware validation record.

## First safe parity milestone

### Existing compatibility behavior

The normal Home Assistant controls keep the established local-WebSocket paths:

- start, pause, resume, stop, return to dock, and locate;
- room/segment cleaning through the existing compatibility sender;
- local status, battery, cleaning statistics, map, rooms, and live updates;
- reconnect, wake, heartbeat, and polling behavior.

Normal whole-house start is not translated into a guessed parameterized
all-rooms task. Room cleaning uses the compatibility payload unless an exact
device profile has a completed physical validation record.

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

The milestone adds conservative decoders for:

- the feature/capability response, including exact raw field values;
- `config/get`, mapping only known fields to typed values and retaining
  unknown or malformed fields as raw diagnostics;
- `clean/current_clean_task/get`, including known room, order, mode, fan, mop,
  pass, and overlap fields while retaining the full raw task.

These queries populate the client/coordinator's read-only state. Advertised
capabilities are also available through a Home Assistant diagnostic sensor.
Configuration and task decoders are foundations for inspection and testing;
they are not configuration controls and do not make corresponding setters safe.

### Supervised AX15 parameterized-clean validation

There is one deliberately narrow experimental path for investigating the Freo
X10 Pro:

1. The live identity must resolve to product key `CNbforyZWI` (AX15).
2. Firmware must be exactly `v01.03.10.03`.
3. The robot must advertise the required multi-zone capability.
4. The integration option for experimental parameterized cleaning must be
   enabled.
5. Every `narwal.validate_parameterized_clean` call must set
   `confirm_unverified: true`.

The service is for a person standing near the robot with Stop available. It is
not supported for unattended automations. A protocol response such as
`ACCEPTED` only means the message was accepted; it does not establish that the
requested route, suction, water, mop strength, pass count, or room order was
physically followed.

No exact Flow 2 product-and-firmware pair is marked as physically validated by
this milestone.

## Not exposed as supported writes

| Area | Current position |
| --- | --- |
| Station actions | Washing, drying, dust collection, station lighting, and other station writes remain hidden until each action has a model/firmware-specific physical validation record. |
| Configuration | `config/get` is decoded read-only. `config/set` is not exposed through Home Assistant; each setting needs read/write/read-back/rollback validation. |
| Map mutation | No-go zones, virtual walls, room split/merge, furniture, floor material, map selection, restore, delete, and boundary/safety-distance edits are not implemented as supported writes. |
| Camera and patrol | Snapshot, video, LED, obstacle-media, patrol, cruise, and telecontrol paths are not supported. Protocol names or APK code are not sufficient evidence. |
| Pump and plumbing | Water exchange, pump, drain, detergent, and related station maintenance writes are not supported. Incorrect commands can have physical consequences. |
| Firmware | Download, upgrade, rollback, and firmware-management writes are not supported. |
| Cloud account operations | Account, device binding, sharing, remote notification, and cloud history operations are outside the local milestone. |

### Map safety-distance request

The current integration reads and renders the robot's map; it does not safely
edit navigation clearance. Increasing a “safe area” by one inch at selected
locations first requires identifying whether the app stores a no-go polygon,
an obstacle margin, a room boundary, or a firmware navigation parameter. The
coordinate system, units, map revision checks, and rollback behavior must be
confirmed before any map write is attempted.

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
writes remain profile-gated per product key and firmware.

The Freo X Plus/BX1 is a separate boundary. Available evidence points to a
cloud-backed transport rather than this local WebSocket protocol. It cannot
reach app parity by adding more AX15 topics to the current client. Supporting
it requires a separate transport/provider layer, regional cloud endpoint and
authentication research, secure credential handling, and its own validation
matrix. Local AX15 work must not silently fall back to the cloud.

## Roadmap to app parity

1. **Build the evidence matrix.** Record product key, hardware model, firmware,
   app version, capability response, request topic, response shape, and
   observed physical result for every test.
2. **Complete read-only parity.** Decode station state, consumables, cleaning
   history, richer task/progress data, map metadata, and all unknown fields
   before adding setters.
3. **Validate commands one at a time.** Require a supervised fixture, expected
   motion or station behavior, timeout behavior, read-back, Stop/rollback, and
   a captured validation record.
4. **Promote validated controls.** Expose a control only for exact profiles
   proven to support it; keep unknown firmware fail-closed.
5. **Handle map edits as transactions.** Preserve the original map and revision,
   validate geometry and units, write once, read back, and provide rollback.
6. **Add a separate BX1/cloud provider if viable.** Keep cloud authentication,
   rate limits, regional behavior, and privacy separate from the local client.
7. **Harden release behavior.** Add interleaved-response fixtures, replay tests,
   migration tests, diagnostics redaction, and per-profile regression coverage.

## Validation record checklist

Before changing an operation from *unvalidated* to *supported*, record:

- product key, displayed model, firmware, dock/station model, and app version;
- capability fields and complete raw response;
- exact request and response with identifiers or secrets removed;
- robot and station preconditions;
- expected and observed physical behavior;
- read-back result, failure/timeout behavior, and recovery procedure;
- confirmation that a different model or unknown firmware remains fail-closed.

This project is unofficial and reverse-engineered. Firmware updates can change
behavior without notice, so older validation must not automatically authorize a
new firmware version.
