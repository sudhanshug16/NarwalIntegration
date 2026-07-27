# Narwal Lovelace control card

`custom:narwal-control-card` is bundled with this integration from version
`1.1.0-beta.4`. It uses Home Assistant service calls only; the browser never
connects to port 9002 or directly controls the robot.

The integration registers the JavaScript resource automatically on startup.
Create a separate **Narwal** dashboard or add a **Manual** card to an existing
dashboard, then use the following configuration. Replace the entity IDs if
Home Assistant generated different ones in your installation.

```yaml
type: custom:narwal-control-card
title: Freo X10 Pro
vacuum_entity: vacuum.narwal_freo_x10_pro_vacuum
map_entity: camera.narwal_freo_x10_pro_map
mode_entity: select.living_room_narwal_freo_x10_pro_mode
suction_entity: select.living_room_narwal_freo_x10_pro_suction
water_entity: select.living_room_narwal_freo_x10_pro_water
scrub_entity: select.living_room_narwal_freo_x10_pro_scrub
route_entity: select.living_room_narwal_freo_x10_pro_route
passes_entity: select.living_room_narwal_freo_x10_pro_passes
```

The optional select entities let the card pass the same normal cleaning
settings shown elsewhere in Home Assistant to `narwal.clean_rooms`. Put native
Entity cards beside this one if you want to change those settings from the same
dashboard.

## Controls and safeguards

| UI control | Home Assistant action | Guard |
| --- | --- | --- |
| Tap map, then **Go to selected point** | `narwal.go_to` | The image must load for the current map revision. A new rendered map clears the pending point. The backend then re-fetches/validates the map, target cell, one-cell clearance, furniture, and live robot state. |
| **Stop navigation** | `narwal.stop_navigation` | Always visible; it is a safe cancel path even when the last UI update is stale. |
| Room labels/chips, then **Clean selected rooms** | `narwal.clean_rooms` | The card sends known Narwal room IDs, not drawn geometry. The backend checks model, capabilities, rooms, and live action state. |
| Hold an arrow | repeated `narwal.drive` calls | Each request is a 100 ms bounded pulse. The card does not queue overlapping drive calls. |
| Release arrow, pointer cancel/loss, tab hide, blur, card removal, **Emergency stop** | `narwal.stop_telecontrol` | The server performs the raw zero-velocity/manual-off cleanup and point-navigation cancellation. |

The joystick only enables when Home Assistant reports the vacuum as `idle`,
undocked, and free of manual or point navigation. Click-to-go and room cleaning
enable only while the vacuum is idle/docked and free of an active manual/point
task. Those are UI hints; the server repeats the safety checks and remains the
source of truth.

## Deliberate boundary: arbitrary rectangles

The card does not turn a drawn rectangle into a cleaning command. The recovered
AX15 path uses room IDs, while the shared mobile APK includes generic zone
structures whose exact bounds, coordinate system, and AX15 acceptance are not
established. A rectangle action will be added only after a real AX15
official-app request is captured, decoded, and validated under supervision.

## First physical validation

No UI load or dashboard setup moves the robot. Before using motion for the
first time, keep someone beside it and verify in this order:

1. Confirm the map is current and the red **Emergency stop** is visible.
2. With the robot idle and off dock, hold a joystick direction for the shortest
   practical moment, release it, and verify it stops.
3. Verify an unfocused/tab-hidden browser also leaves it stopped.
4. Select a nearby, clear point; confirm the point-navigation request and test
   **Stop navigation**.
5. Test one mapped room before relying on a multi-room plan.

The robot's own obstacle avoidance and arrival tolerance remain active; tap-to-
go is not centimeter-accurate positioning.
