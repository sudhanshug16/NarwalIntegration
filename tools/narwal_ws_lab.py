"""Standalone, auditable Narwal local-WebSocket command laboratory.

This tool talks directly to the robot; it does not use Home Assistant.  It
intentionally runs one command per invocation and writes an append-only JSONL
transcript which can be rendered as Markdown.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import enum
import json
import math
import os
import sys
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from narwal_client import const
from narwal_client.client import NarwalClient
from narwal_client.const import ManualControlMode
from narwal_client.models import CommandResponse
from narwal_client.protocol import NarwalMessage
from narwal_client.telecontrol import encode_telecontrol_velocity

READ_TOPICS = {
    const.TOPIC_CMD_GET_DEVICE_INFO,
    const.TOPIC_CMD_GET_FEATURE_LIST,
    const.TOPIC_CMD_GET_BASE_STATUS,
    const.TOPIC_CMD_GET_CONFIG,
    const.TOPIC_CMD_GET_CURRENT_CLEAN_PLAN,
    const.TOPIC_CMD_GET_CLEAN_PLANS,
    const.TOPIC_CMD_GET_CLEAN_SCHEDULES,
    const.TOPIC_CMD_GET_CONSUMABLE_INFO,
    const.TOPIC_CMD_GET_FIRMWARE_VERSION,
    const.TOPIC_CMD_GET_LANGUAGE,
    const.TOPIC_CMD_GET_SUPPORTED_LANGUAGES,
    const.TOPIC_CMD_GET_CURRENT_VOICE_INFO,
    const.TOPIC_CMD_GET_CLEAN_TIMELINE,
    const.TOPIC_CMD_GET_CURRENT_TASK,
    const.TOPIC_CMD_GET_CLEAN_PROGRESS_INFO,
    const.TOPIC_CMD_GET_DRY_MOP_REMAIN_TIME,
    const.TOPIC_CMD_GET_ROBOT_TASK_STATUS,
    const.TOPIC_CMD_GET_MAP,
    const.TOPIC_CMD_GET_ALL_MAPS,
    const.TOPIC_CMD_GET_EDITABLE_MAP,
    const.TOPIC_CMD_CHECK_MAP_UPDATE_INFO,
}

HIGH_RISK_NAMES = {"REBOOT", "SHUTDOWN", "SET_CONFIG", "UPDATE_CLEAN_SCHEDULE"}
HIGH_RISK_WORDS = ("DELETE", "RESET", "UPGRADE", "FACTORY", "PUMP", "PLUMB")


def topic_catalog() -> list[dict[str, str]]:
    """Return every command constant with a conservative safety classification."""
    rows = []
    for name in sorted(n for n in dir(const) if n.startswith("TOPIC_CMD_")):
        topic = getattr(const, name)
        suffix = name.removeprefix("TOPIC_CMD_")
        if topic in READ_TOPICS:
            risk = "read-only"
        elif suffix in HIGH_RISK_NAMES or any(word in suffix for word in HIGH_RISK_WORDS):
            risk = "high"
        elif suffix in {"ACTIVE_ROBOT", "APP_HEARTBEAT", "NOTIFY_APP_EVENT", "PING"}:
            risk = "protocol"
        else:
            risk = "state-changing"
        rows.append({"name": name, "topic": topic, "risk": risk})
    return rows


def jsonable(value: Any) -> Any:
    """Convert decoded protocol and dataclass values to lossless JSON values."""
    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value), "hex": value.hex()}
    if dataclasses.is_dataclass(value):
        return {
            field.name: jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, enum.Enum):
        return {"name": value.name, "value": value.value}
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


class Transcript:
    """Append-only JSONL event writer."""

    def __init__(self, path: Path, session_id: str) -> None:
        self.path = path
        self.session_id = session_id
        self.started = time.monotonic()
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, kind: str, **data: Any) -> None:
        event = {
            "schema": 1,
            "session_id": self.session_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "elapsed_ms": round((time.monotonic() - self.started) * 1000, 3),
            "kind": kind,
            **jsonable(data),
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")


def decode_payload(client: NarwalClient, payload: bytes) -> Any:
    if not payload:
        return {}
    try:
        return client._decode_protobuf(payload)  # noqa: SLF001 - protocol lab
    except Exception as error:
        return {"decode_error": f"{type(error).__name__}: {error}"}


def record_broadcast(log: Transcript, client: NarwalClient, message: NarwalMessage) -> None:
    log.write(
        "broadcast",
        topic=message.topic,
        short_topic=message.short_topic,
        header=message.header,
        payload_hex=message.payload.hex(),
        decoded=decode_payload(client, message.payload),
    )


QUERY_RECIPES: dict[str, tuple[str, str]] = {
    "device-info": ("get_device_info", const.TOPIC_CMD_GET_DEVICE_INFO),
    "features": ("get_feature_list", const.TOPIC_CMD_GET_FEATURE_LIST),
    "base-status": ("get_status", const.TOPIC_CMD_GET_BASE_STATUS),
    "config": ("get_config", const.TOPIC_CMD_GET_CONFIG),
    "current-task": ("get_current_task", const.TOPIC_CMD_GET_CURRENT_TASK),
    "current-plan": ("get_current_clean_plan", const.TOPIC_CMD_GET_CURRENT_CLEAN_PLAN),
    "plans": ("get_clean_plans", const.TOPIC_CMD_GET_CLEAN_PLANS),
    "schedules": ("get_clean_schedules", const.TOPIC_CMD_GET_CLEAN_SCHEDULES),
    "consumables": ("get_consumable_info", const.TOPIC_CMD_GET_CONSUMABLE_INFO),
    "firmware": ("get_firmware_metadata", const.TOPIC_CMD_GET_FIRMWARE_VERSION),
    "language": ("get_language_metadata", const.TOPIC_CMD_GET_LANGUAGE),
    "languages": ("get_supported_languages", const.TOPIC_CMD_GET_SUPPORTED_LANGUAGES),
    "voice": ("get_current_voice_info", const.TOPIC_CMD_GET_CURRENT_VOICE_INFO),
    "timeline": ("get_clean_timeline", const.TOPIC_CMD_GET_CLEAN_TIMELINE),
    "progress": ("get_clean_progress_info", const.TOPIC_CMD_GET_CLEAN_PROGRESS_INFO),
    "drying-time": ("get_dry_mop_remain_time", const.TOPIC_CMD_GET_DRY_MOP_REMAIN_TIME),
    "task-status": ("get_robot_task_status", const.TOPIC_CMD_GET_ROBOT_TASK_STATUS),
    "map": ("get_map", const.TOPIC_CMD_GET_MAP),
    "saved-maps": ("get_saved_maps", const.TOPIC_CMD_GET_ALL_MAPS),
    "map-update": ("check_map_update_info", const.TOPIC_CMD_CHECK_MAP_UPDATE_INFO),
}

ACTION_RECIPES: dict[str, tuple[str, str, str]] = {
    "locate": ("locate", const.TOPIC_CMD_YELL, "state-changing"),
    "pause": ("pause", const.TOPIC_CMD_PAUSE, "state-changing"),
    "resume": ("resume", const.TOPIC_CMD_RESUME, "state-changing"),
    "stop-task": ("stop", const.TOPIC_CMD_FORCE_END, "high"),
    "cancel-task": ("cancel", const.TOPIC_CMD_CANCEL, "state-changing"),
    "recall": ("return_to_base", const.TOPIC_CMD_RECALL, "state-changing"),
    "wash-mop": ("wash_mop", const.TOPIC_CMD_WASH_MOP, "state-changing"),
    "wash-mop-auto": (
        "wash_mop_by_robot_status",
        const.TOPIC_CMD_WASH_MOP_BY_ROBOT_STATUS,
        "state-changing",
    ),
    "dry-mop": ("dry_mop", const.TOPIC_CMD_DRY_MOP, "state-changing"),
    "empty-dustbin": ("empty_dustbin", const.TOPIC_CMD_DUST_GATHERING, "state-changing"),
    "wash-and-dry": (
        "wash_and_dry_mop",
        const.TOPIC_CMD_WASH_AND_DRY_MOP,
        "state-changing",
    ),
    "dry-dust-bag": ("dry_dust_bag", const.TOPIC_CMD_DRY_DUST_BAG, "state-changing"),
    "dry-station-bag": (
        "dry_station_bag",
        const.TOPIC_CMD_DRY_STATION_BAG,
        "state-changing",
    ),
    "whole-house-clean": ("start", const.TOPIC_CMD_PLAN_START, "state-changing"),
    "easy-clean": (
        "start_easy_clean",
        const.TOPIC_CMD_EASY_CLEAN,
        "state-changing",
    ),
}


def require_confirmation(recipe: str, supplied: str | None, risk: str, allow_high: bool) -> None:
    if risk == "high" and not allow_high:
        raise SystemExit("High-risk command blocked; review it, then add --allow-high-risk.")
    expected = f"SEND {recipe}"
    if supplied is None and sys.stdin.isatty():
        supplied = input(f"Type exactly '{expected}' to transmit: ")
    if supplied != expected:
        raise SystemExit(f"Not sent. Exact confirmation required: {expected}")


async def connect_client(
    args: argparse.Namespace,
    log: Transcript,
) -> tuple[NarwalClient, asyncio.Task[None]]:
    client = NarwalClient(
        args.host,
        port=args.port,
        device_id=args.device_id or "",
        topic_prefix=f"/{args.product_key}" if args.product_key else None,
    )
    log.write("connection_attempt", host=args.host, port=args.port)
    await client.connect()
    if not client.device_id:
        await client.discover_device_id(timeout=args.timeout)
        await client.drain_ws_buffer()
    client.on_message = lambda message: record_broadcast(log, client, message)
    listener = asyncio.create_task(client.start_listening())
    await asyncio.sleep(0)
    log.write(
        "connected",
        device_id=client.device_id,
        topic_prefix=client.topic_prefix,
    )
    return client, listener


async def snapshot(client: NarwalClient, log: Transcript, phase: str) -> None:
    for label, method in (
        ("base-status", client.get_status),
        ("current-task", client.get_current_task),
        ("task-status", client.get_robot_task_status),
    ):
        try:
            value = await method()
            log.write("snapshot", phase=phase, query=label, value=value)
        except Exception as error:
            log.write(
                "snapshot_error",
                phase=phase,
                query=label,
                error=f"{type(error).__name__}: {error}",
            )


async def wait_for_fresh_map_at_zero(
    client: NarwalClient,
    *,
    after_timestamp: int,
    timeout: float = 4.0,
) -> tuple[float, float, float, int]:
    """Hold zero velocity until a newer display-map position arrives."""
    deadline = time.monotonic() + timeout
    zero = encode_telecontrol_velocity(0, 0)
    while time.monotonic() < deadline:
        await client._publish_command(  # noqa: SLF001
            const.TOPIC_CMD_VELOCITY_CONTROL,
            zero,
        )
        current = client.state.map_display_data
        if current is not None and current.timestamp > after_timestamp:
            return (
                current.robot_x,
                current.robot_y,
                current.robot_heading,
                current.timestamp,
            )
        await asyncio.sleep(0.2)
    raise RuntimeError("No fresh display-map position arrived while holding zero")


async def measured_joystick_pulse(
    client: NarwalClient,
    *,
    linear: int,
    angular: int,
    duration: float,
) -> tuple[CommandResponse, tuple[float, float, float, int], tuple[float, float, float, int]]:
    """Run one pulse bracketed by zero-velocity map samples."""
    async with client._telecontrol_lock:  # noqa: SLF001
        response = await client.set_manual_control_mode(ManualControlMode.JOYSTICK)
        if not response.success:
            return response, (0.0, 0.0, 0.0, 0), (0.0, 0.0, 0.0, 0)
        if not await client._wait_for_manual_control_state(  # noqa: SLF001
            int(ManualControlMode.JOYSTICK),
            timeout=5.0,
        ):
            raise RuntimeError("Robot did not report JOYSTICK state")
        client._manual_control_active = True  # noqa: SLF001
        existing = client.state.map_display_data
        existing_timestamp = existing.timestamp if existing is not None else 0
        before = await wait_for_fresh_map_at_zero(
            client,
            after_timestamp=existing_timestamp,
        )
        payload = encode_telecontrol_velocity(linear, angular)
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            await client._publish_command(  # noqa: SLF001
                const.TOPIC_CMD_VELOCITY_CONTROL,
                payload,
            )
            await asyncio.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
        after = await wait_for_fresh_map_at_zero(
            client,
            after_timestamp=before[3],
        )
        await client._stop_manual_control_locked()  # noqa: SLF001
        return response, before, after


async def invoke_recipe(
    client: NarwalClient,
    log: Transcript,
    name: str,
    method_name: str,
    topic: str,
) -> None:
    if log.snapshots:
        await snapshot(client, log, "before")
    log.write("command_send", recipe=name, topic=topic, payload_hex="")
    started = time.monotonic()
    try:
        result = await getattr(client, method_name)()
        event: dict[str, Any] = {
            "recipe": name,
            "topic": topic,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "result": result,
        }
        if isinstance(result, CommandResponse):
            event.update(
                result_code=result.result_code,
                result_known=result.result_known,
                success=result.success,
                response_payload_hex=result.raw_payload.hex(),
                response_decoded=result.data,
            )
        log.write("command_response", **event)
    except BaseException as error:
        log.write(
            "command_error",
            recipe=name,
            topic=topic,
            duration_ms=round((time.monotonic() - started) * 1000, 3),
            error=f"{type(error).__name__}: {error}",
        )
        raise
    await client.subscribe_to_topics(duration=max(60, int(log.observe_after) + 30))
    await asyncio.sleep(args_observe_after := float(getattr(log, "observe_after", 0)))
    if log.snapshots:
        await snapshot(client, log, "after")
    if args_observe_after:
        log.write("observation_window_complete", seconds=args_observe_after)


async def run_network(args: argparse.Namespace, log: Transcript) -> None:
    client: NarwalClient | None = None
    listener: asyncio.Task[None] | None = None
    try:
        client, listener = await connect_client(args, log)
        if args.mode == "observe":
            await client.subscribe_to_topics(duration=max(60, int(args.seconds) + 30))
            log.write("observation_started", seconds=args.seconds)
            await asyncio.sleep(args.seconds)
            log.write("observation_complete", seconds=args.seconds)
            return
        if args.mode == "query":
            method, topic = QUERY_RECIPES[args.recipe]
            await invoke_recipe(client, log, args.recipe, method, topic)
            return
        if args.mode == "telecontrol-stop":
            recipe = "telecontrol-stop"
            require_confirmation(
                recipe,
                args.confirm,
                "state-changing",
                False,
            )
            await client.subscribe_to_topics(
                duration=max(60, int(args.observe_after) + 30)
            )
            await asyncio.sleep(1.5)
            client._discard_pre_command_responses()  # noqa: SLF001
            log.write(
                "command_send",
                recipe=recipe,
                topic=const.TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
            )
            started = time.monotonic()
            try:
                await client.emergency_stop_telecontrol()
                status = await client.get_status(full_update=True)
                log.write(
                    "command_response",
                    recipe=recipe,
                    topic=const.TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
                    duration_ms=round((time.monotonic() - started) * 1000, 3),
                    response_payload_hex=status.raw_payload.hex(),
                    response_decoded=status.data,
                )
            except BaseException as error:
                log.write(
                    "command_error",
                    recipe=recipe,
                    topic=const.TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
                    duration_ms=round((time.monotonic() - started) * 1000, 3),
                    error=f"{type(error).__name__}: {error}",
                )
                try:
                    recovery = await client.stop(timeout=15.0)
                    recovery_status = await client.get_status(full_update=True)
                    log.write(
                        "telecontrol_recovery",
                        strategy="task/force_end",
                        result_code=recovery.result_code,
                        result_known=recovery.result_known,
                        status=recovery_status.data,
                    )
                except BaseException as recovery_error:
                    log.write(
                        "telecontrol_recovery_error",
                        strategy="task/force_end",
                        error=(
                            f"{type(recovery_error).__name__}: "
                            f"{recovery_error}"
                        ),
                    )
                raise
            await asyncio.sleep(args.observe_after)
            return
        if args.mode == "point":
            recipe = "point-navigation"
            require_confirmation(
                recipe,
                args.confirm,
                "state-changing",
                False,
            )
            await client.subscribe_to_topics(
                duration=max(60, int(args.seconds) + 30)
            )
            await asyncio.sleep(1.5)
            client._discard_pre_command_responses()  # noqa: SLF001
            log.write(
                "command_send",
                recipe=recipe,
                topic=const.TOPIC_CMD_POINT_NAVI,
                x=args.x,
                y=args.y,
                theta=args.theta,
            )
            started = time.monotonic()
            primary_error: BaseException | None = None
            try:
                response = await client.start_point_navigation(
                    args.x,
                    args.y,
                    theta=args.theta,
                )
                log.write(
                    "command_response",
                    recipe=recipe,
                    topic=const.TOPIC_CMD_POINT_NAVI,
                    duration_ms=round((time.monotonic() - started) * 1000, 3),
                    result_code=response.result_code,
                    result_known=response.result_known,
                    success=response.success,
                    response_payload_hex=response.raw_payload.hex(),
                    response_decoded=response.data,
                )
                await asyncio.sleep(args.seconds)
            except BaseException as error:
                primary_error = error
                log.write(
                    "command_error",
                    recipe=recipe,
                    topic=const.TOPIC_CMD_POINT_NAVI,
                    duration_ms=round((time.monotonic() - started) * 1000, 3),
                    error=f"{type(error).__name__}: {error}",
                )
            finally:
                try:
                    stop_response = await client.stop_point_navigation()
                    stop_status = await client.get_status(full_update=True)
                    log.write(
                        "point_navigation_cleanup",
                        result_code=stop_response.result_code,
                        result_known=stop_response.result_known,
                        status=stop_status.data,
                    )
                except BaseException as stop_error:
                    log.write(
                        "point_navigation_cleanup_error",
                        error=f"{type(stop_error).__name__}: {stop_error}",
                    )
                    try:
                        fallback = await client.stop(timeout=15.0)
                        fallback_status = await client.get_status(full_update=True)
                        log.write(
                            "telecontrol_recovery",
                            strategy="task/force_end",
                            result_code=fallback.result_code,
                            result_known=fallback.result_known,
                            status=fallback_status.data,
                        )
                    except BaseException as fallback_error:
                        log.write(
                            "telecontrol_recovery_error",
                            strategy="task/force_end",
                            error=(
                                f"{type(fallback_error).__name__}: "
                                f"{fallback_error}"
                            ),
                        )
            if primary_error is not None:
                raise primary_error
            return
        if args.mode == "joystick":
            recipe = "joystick-pulse"
            require_confirmation(
                recipe,
                args.confirm,
                "state-changing",
                False,
            )
            log.write(
                "command_send",
                recipe=recipe,
                topic=const.TOPIC_CMD_VELOCITY_CONTROL,
                linear=args.linear,
                angular=args.angular,
                duration_seconds=args.duration,
            )
            await client.subscribe_to_topics(
                duration=max(60, int(args.observe_after) + 30)
            )
            # Manual-control safety requires robot-reported mode transitions.
            # Let the subscription acknowledgement arrive before the guarded
            # set-mode command so it cannot be mistaken for that response.
            await asyncio.sleep(1.5)
            client._discard_pre_command_responses()  # noqa: SLF001
            started = time.monotonic()
            before_position = None
            after_position = None
            try:
                response, before_sample, after_sample = await measured_joystick_pulse(
                    client,
                    linear=args.linear,
                    angular=args.angular,
                    duration=args.duration,
                )
                before_position = before_sample[:3]
                after_position = after_sample[:3]
                log.write(
                    "command_response",
                    recipe=recipe,
                    topic=const.TOPIC_CMD_VELOCITY_CONTROL,
                    duration_ms=round((time.monotonic() - started) * 1000, 3),
                    result_code=response.result_code,
                    result_known=response.result_known,
                    success=response.success,
                    response_payload_hex=response.raw_payload.hex(),
                    response_decoded=response.data,
                )
            except BaseException as error:
                log.write(
                    "command_error",
                    recipe=recipe,
                    topic=const.TOPIC_CMD_VELOCITY_CONTROL,
                    duration_ms=round((time.monotonic() - started) * 1000, 3),
                    error=f"{type(error).__name__}: {error}",
                )
                try:
                    recovery = await client.stop(timeout=15.0)
                    recovery_status = await client.get_status(full_update=True)
                    log.write(
                        "telecontrol_recovery",
                        strategy="task/force_end",
                        result_code=recovery.result_code,
                        result_known=recovery.result_known,
                        status=recovery_status.data,
                    )
                except BaseException as recovery_error:
                    log.write(
                        "telecontrol_recovery_error",
                        strategy="task/force_end",
                        error=(
                            f"{type(recovery_error).__name__}: "
                            f"{recovery_error}"
                        ),
                    )
                raise
            await asyncio.sleep(args.observe_after)
            if before_position is not None and after_position is not None:
                delta_x = after_position[0] - before_position[0]
                delta_y = after_position[1] - before_position[1]
                displacement = math.hypot(delta_x, delta_y)
                log.write(
                    "map_displacement",
                    before={
                        "x": before_position[0],
                        "y": before_position[1],
                        "heading_degrees": before_position[2],
                    },
                    after={
                        "x": after_position[0],
                        "y": after_position[1],
                        "heading_degrees": after_position[2],
                    },
                    delta_x=delta_x,
                    delta_y=delta_y,
                    displacement_map_units=displacement,
                    heading_delta_degrees=(
                        after_position[2] - before_position[2]
                    ),
                )
                print(
                    "Map displacement: "
                    f"{displacement:.6f} raw units "
                    f"(dx={delta_x:.6f}, dy={delta_y:.6f})"
                )
            return
        if args.mode == "raw":
            recipe = f"raw:{args.topic}"
            require_confirmation(
                recipe,
                args.confirm,
                "high",
                args.allow_high_risk,
            )
            if log.snapshots:
                await snapshot(client, log, "before")
            payload = bytes.fromhex(args.payload_hex)
            log.write(
                "command_send",
                recipe=recipe,
                topic=args.topic,
                payload_hex=payload.hex(),
            )
            started = time.monotonic()
            try:
                if args.no_response:
                    await client._publish_command(args.topic, payload)  # noqa: SLF001
                    log.write(
                        "command_published",
                        recipe=recipe,
                        topic=args.topic,
                        duration_ms=round((time.monotonic() - started) * 1000, 3),
                    )
                else:
                    response = await client.send_command(
                        args.topic,
                        payload,
                        timeout=args.timeout,
                    )
                    log.write(
                        "command_response",
                        recipe=recipe,
                        topic=args.topic,
                        duration_ms=round((time.monotonic() - started) * 1000, 3),
                        result_code=response.result_code,
                        result_known=response.result_known,
                        success=response.success,
                        response_payload_hex=response.raw_payload.hex(),
                        response_decoded=response.data,
                    )
            except BaseException as error:
                log.write(
                    "command_error",
                    recipe=recipe,
                    topic=args.topic,
                    duration_ms=round((time.monotonic() - started) * 1000, 3),
                    error=f"{type(error).__name__}: {error}",
                )
                raise
            await client.subscribe_to_topics(
                duration=max(60, int(args.observe_after) + 30)
            )
            await asyncio.sleep(args.observe_after)
            if log.snapshots:
                await snapshot(client, log, "after")
            return
        method, topic, risk = ACTION_RECIPES[args.recipe]
        require_confirmation(args.recipe, args.confirm, risk, args.allow_high_risk)
        await invoke_recipe(client, log, args.recipe, method, topic)
    finally:
        if client is not None:
            try:
                await client.disconnect()
                log.write("disconnected")
            except Exception as error:
                log.write("disconnect_error", error=f"{type(error).__name__}: {error}")
        if listener is not None and not listener.done():
            listener.cancel()


def render_report(paths: list[Path], output: Path) -> None:
    events = []
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            events.extend(json.loads(line) for line in stream if line.strip())
    sessions: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        sessions.setdefault(event["session_id"], []).append(event)
    lines = [
        "# Narwal direct WebSocket command test log",
        "",
        "> Generated from append-only JSONL captures. Physical observations are operator-supplied.",
        "",
    ]
    for session_id, group in sessions.items():
        start = group[0]
        meta = next((event for event in group if event["kind"] == "session"), {})
        command = next(
            (event for event in group if event["kind"] in {"command_send", "observation_started"}),
            {},
        )
        response = next(
            (event for event in group if event["kind"] in {"command_response", "command_error"}),
            {},
        )
        observations = [event for event in group if event["kind"] == "operator_observation"]
        lines.extend(
            [
                f"## {command.get('recipe', 'observe')} — {start['timestamp']}",
                "",
                f"- Session: `{session_id}`",
                f"- Robot: `{meta.get('host', 'unknown')}:{meta.get('port', 'unknown')}`",
                f"- Topic: `{command.get('topic', 'broadcast-only')}`",
                f"- Result: `{response.get('result_code', response.get('error', 'n/a'))}`",
                f"- Broadcasts captured: {sum(e['kind'] == 'broadcast' for e in group)}",
                "",
                "### Physical observation",
                "",
            ]
        )
        if observations:
            for observation in observations:
                lines.append(f"- {observation['text']}")
        else:
            lines.append("- _Not documented yet._")
        lines.extend(["", "### Caveats", "", "- _Add after supervised test._", ""])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def append_annotation(path: Path, text: str) -> None:
    with path.open(encoding="utf-8") as stream:
        first = json.loads(next(line for line in stream if line.strip()))
    transcript = Transcript(path, first["session_id"])
    transcript.write("operator_observation", text=text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("catalog", help="List known command topics without connecting")
    network_parent = argparse.ArgumentParser(add_help=False)
    network_parent.add_argument("--host", required=True)
    network_parent.add_argument("--port", type=int, default=9002)
    network_parent.add_argument("--device-id")
    network_parent.add_argument("--product-key")
    network_parent.add_argument("--timeout", type=float, default=15)
    network_parent.add_argument("--observe-after", type=float, default=10)
    network_parent.add_argument(
        "--snapshots",
        action="store_true",
        help="Send three status queries before and after the tested command",
    )
    network_parent.add_argument("--output-dir", type=Path, default=Path(".narwal-lab"))
    observe = sub.add_parser("observe", parents=[network_parent], help="Capture broadcasts only")
    observe.add_argument("--seconds", type=float, default=30)
    query = sub.add_parser("query", parents=[network_parent], help="Run one read-only recipe")
    query.add_argument("recipe", choices=sorted(QUERY_RECIPES))
    action = sub.add_parser(
        "action",
        parents=[network_parent],
        help="Run one state-changing recipe",
    )
    action.add_argument("recipe", choices=sorted(ACTION_RECIPES))
    action.add_argument("--confirm", help="Exact non-interactive phrase: SEND <recipe>")
    action.add_argument("--allow-high-risk", action="store_true")
    joystick = sub.add_parser(
        "joystick",
        parents=[network_parent],
        help="Run one bounded dead-man joystick pulse",
    )
    joystick.add_argument("--linear", type=int, required=True)
    joystick.add_argument("--angular", type=int, required=True)
    joystick.add_argument("--duration", type=float, default=0.25)
    joystick.add_argument("--confirm", help="Exact phrase: SEND joystick-pulse")
    telecontrol_stop = sub.add_parser(
        "telecontrol-stop",
        parents=[network_parent],
        help="Send acknowledged zero/OFF telecontrol recovery",
    )
    telecontrol_stop.add_argument(
        "--confirm",
        help="Exact phrase: SEND telecontrol-stop",
    )
    point = sub.add_parser(
        "point",
        parents=[network_parent],
        help="Run bounded point navigation, then always stop it",
    )
    point.add_argument("--x", type=float, required=True)
    point.add_argument("--y", type=float, required=True)
    point.add_argument("--theta", type=float, default=0.0)
    point.add_argument("--seconds", type=float, default=15)
    point.add_argument("--confirm", help="Exact phrase: SEND point-navigation")
    raw = sub.add_parser(
        "raw",
        parents=[network_parent],
        help="Send one reviewed topic/payload pair (always high-risk)",
    )
    raw.add_argument("topic", help="Short topic, without product/device prefix")
    raw.add_argument(
        "--payload-hex",
        default="",
        help="Exact protobuf payload as hexadecimal bytes",
    )
    raw.add_argument("--confirm", help="Exact phrase: SEND raw:<topic>")
    raw.add_argument("--allow-high-risk", action="store_true")
    raw.add_argument(
        "--no-response",
        action="store_true",
        help="Publish once without waiting for an acknowledgement",
    )
    annotate = sub.add_parser("annotate", help="Append a physical observation to a capture")
    annotate.add_argument("capture", type=Path)
    annotate.add_argument("text")
    report = sub.add_parser("report", help="Render captures as Markdown")
    report.add_argument("captures", nargs="+", type=Path)
    report.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.mode == "catalog":
        print("RISK             CONSTANT                              TOPIC")
        for row in topic_catalog():
            print(f"{row['risk']:<16} {row['name']:<37} {row['topic']}")
        return
    if args.mode == "annotate":
        append_annotation(args.capture, args.text)
        return
    if args.mode == "report":
        render_report(args.captures, args.output)
        return
    session_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    capture = args.output_dir / f"{session_id}.jsonl"
    log = Transcript(capture, session_id)
    log.observe_after = args.observe_after
    log.snapshots = args.snapshots
    log.write(
        "session",
        mode=args.mode,
        recipe=getattr(args, "recipe", None),
        host=args.host,
        port=args.port,
        operator=os.environ.get("USER", "unknown"),
    )
    try:
        asyncio.run(run_network(args, log))
    finally:
        print(f"Capture: {capture}")


if __name__ == "__main__":
    main()
