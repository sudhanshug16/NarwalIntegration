# Narwal direct WebSocket command laboratory

`tools/narwal_ws_lab.py` is a standalone, one-command-at-a-time harness for
supervised protocol testing. It connects directly to the robot on port 9002;
Home Assistant is not involved.

## Safety rules

- Stop Home Assistant before connecting. Narwal robots normally accept only
  one WebSocket client.
- Run only one command per capture.
- Keep the robot in view for movement, cleaning, dock, and maintenance tests.
- State-changing commands require the exact confirmation `SEND <recipe>`.
- High-risk commands are blocked unless the command is explicitly marked as
  implemented and `--allow-high-risk` is supplied.
- Unknown topics appear in `catalog`, but the lab does not guess their payload.
- Before/after status queries are opt-in with `--snapshots`; leaving that flag
  off ensures the capture isolates one tested command.
- The harness does not treat a transport response as proof of physical success.
  It records before/after state and broadcasts; the operator documents what
  actually happened.

## Offline preparation

These commands never connect:

```shell
python tools/narwal_ws_lab.py catalog
python tools/narwal_ws_lab.py --help
```

## Supervised workflow

Stop Home Assistant immediately before a test session:

```shell
ssh sudhanshu@everafter.local 'sudo docker stop homeassistant'
```

First collect a passive baseline:

```shell
python tools/narwal_ws_lab.py observe \
  --host ROBOT_IP --product-key CNbforyZWI --seconds 30
```

Then run one read-only command:

```shell
python tools/narwal_ws_lab.py query base-status \
  --host ROBOT_IP --product-key CNbforyZWI
```

Run a state-changing command only while supervising the robot:

```shell
python tools/narwal_ws_lab.py action locate \
  --host ROBOT_IP --product-key CNbforyZWI
```

The prompt requires `SEND locate`. Each invocation prints its JSONL capture
path. Add the observed physical result afterward:

```shell
python tools/narwal_ws_lab.py annotate CAPTURE.jsonl \
  "Robot played its locate sound once; no movement."
```

For a payload recovered from the APK but not yet promoted to a named recipe,
use guarded raw mode. It is always classified high-risk:

```shell
python tools/narwal_ws_lab.py raw telecontrol/example \
  --payload-hex 0801 --host ROBOT_IP --product-key CNbforyZWI \
  --allow-high-risk
```

The exact prompt for that example is `SEND raw:telecontrol/example`. Do not use
raw mode until the topic, protobuf payload, and safe recovery command have been
reviewed.

Render one or more captures to Markdown:

```shell
python tools/narwal_ws_lab.py report .narwal-lab/*.jsonl \
  --output NARWAL_COMMAND_TEST_LOG.md
```

Always restart Home Assistant when the direct session ends:

```shell
ssh sudhanshu@everafter.local 'sudo docker start homeassistant'
```

## Capture contents

Each JSONL line includes UTC and monotonic timing. Captures contain connection
metadata, exact command topic, payload hex, decoded command response, raw
response payload, before/after status snapshots, every subscribed broadcast,
errors, disconnect outcome, and operator observations.

The JSONL file is the evidence source. Markdown is a generated field notebook,
not a replacement for the raw capture.

## AX15 live findings

Validated on Freo X10 Pro AX15 firmware `v01.03.10.03`:

- `map/display_map` positions are map-grid coordinates. Multiply displacement
  by the active map resolution (`60 mm/pixel` on the tested map), not by an
  assumed decimetre scale.
- A bounded `0.5s` joystick pulse measured approximately:
  - linear `3`: `0.0809` grid units, about `0.49 cm`;
  - linear `5`: `0.1363` grid units, about `0.82 cm`;
  - linear `10`: `0.2766` grid units, about `1.66 cm`;
  - angular `10`: about `5.4–6.1°`.
- Positive linear moves forward. Positive angular turns left/counter-clockwise
  physically, though map-heading and compass signs can use different frames.
- A body-edge tape mark includes displacement caused by rotation; map telemetry
  measures the robot centre.
- AX15 can omit manual-control fields rather than broadcasting explicit zero
  after OFF. Fresh standby with omitted telecontrol fields confirms OFF.
- If OFF is rejected or mode setup aborts, `task/force_end` is the dependable
  recovery. Never disconnect while AX15 still reports working state 21,
  manual-control field 31 = 1, or telecontrol field 19 = 1.
- Point navigation silently performs a localization rotation before movement.
  A cached idle pose can jump substantially during that rotation, so relative
  targets computed before localization are unsafe.
- Point targets and trajectories are quantized to map-grid coordinates and
  have arrival tolerance. Use an absolute point on the current map, not a
  relative distance from stale pose.
