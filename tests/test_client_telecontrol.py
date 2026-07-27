"""Safety and orchestration tests for Narwal telecontrol."""

from __future__ import annotations

import asyncio
from itertools import pairwise
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, call, patch

import pytest

import narwal_client.client as client_module
from narwal_client.client import NarwalClient, NarwalCommandError
from narwal_client.const import (
    TOPIC_CMD_CANCEL,
    TOPIC_CMD_POINT_NAVI,
    TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
    TOPIC_CMD_VELOCITY_CONTROL,
    CommandResult,
    ManualControlMode,
    TelecontrolStatus,
)
from narwal_client.models import CommandResponse

_JOYSTICK = b"\x08\x01"
_OFF = b"\x08\x00"
_ZERO_VELOCITY = b"\x08\x00\x10\x00"
_POINT_REQUEST = bytes.fromhex(
    "10 00 "
    "20 02 "
    "2a 11 "
    "0a 0a "
    "0d 00 00 c0 3f "
    "15 00 00 20 c0 "
    "15 00 00 00 00"
)


def _success() -> CommandResponse:
    return CommandResponse(
        result_code=CommandResult.SUCCESS,
        result_known=True,
    )


def _failed() -> CommandResponse:
    return CommandResponse(
        result_code=CommandResult.NOT_APPLICABLE,
        result_known=True,
    )


def test_set_manual_control_mode_exact_command() -> None:
    client = NarwalClient("127.0.0.1")
    response = _success()
    client.send_command = AsyncMock(return_value=response)

    result = asyncio.run(
        client.set_manual_control_mode(ManualControlMode.JOYSTICK)
    )

    assert result is response
    client.send_command.assert_awaited_once_with(
        TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
        payload=_JOYSTICK,
        timeout=10.0,
    )


@pytest.mark.parametrize(
    ("response", "expected_active"),
    [
        (_success(), True),
        (_failed(), False),
        (
            CommandResponse(
                result_code=CommandResult.SUCCESS,
                result_known=False,
            ),
            False,
        ),
    ],
)
def test_point_navigation_exact_command_and_result_gating(
    response: CommandResponse,
    expected_active: bool,
) -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(return_value=response)

    result = asyncio.run(client.start_point_navigation(1.5, -2.5))

    assert result is response
    assert client.point_navigation_active is expected_active
    client.send_command.assert_awaited_once_with(
        TOPIC_CMD_POINT_NAVI,
        payload=_POINT_REQUEST,
        timeout=10.0,
        before_send=ANY,
    )


def test_point_navigation_trajectory_is_retained_as_world_coordinates() -> None:
    client = NarwalClient("127.0.0.1")

    client._update_point_navigation_trajectory(
        bytes.fromhex(
            "0a 0a "
            "0d 00 00 c0 3f "
            "15 00 00 20 c0"
        )
    )

    assert client.point_navigation_path == ((1.5, -2.5),)


@pytest.mark.parametrize(
    "field3",
    [
        {"19": int(TelecontrolStatus.POINT_NAVI)},
        [{"19": int(TelecontrolStatus.POINT_NAVI)}],
    ],
)
def test_explicit_point_navigation_status_does_not_adopt_ownership(
    field3: object,
) -> None:
    client = NarwalClient("127.0.0.1")

    client._update_from_base_status_broadcast({"3": field3}, now=10.0)

    assert client.telecontrol_status == TelecontrolStatus.POINT_NAVI
    assert client.state.telecontrol_status == TelecontrolStatus.POINT_NAVI
    assert not client.point_navigation_active


def test_point_navigation_natural_completion_requires_seen_active_status() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(return_value=_success())

    asyncio.run(client.start_point_navigation(1.5, -2.5))
    client._point_navigation_path = ((0.0, 0.0), (1.5, -2.5))
    client.state.point_navigation_path = list(client._point_navigation_path)

    client._update_from_base_status_broadcast(
        {"3": {"19": int(TelecontrolStatus.UNSPECIFIED)}},
        now=10.0,
    )

    assert client.point_navigation_active
    assert client.state.point_navigation_target == (1.5, -2.5)
    assert client.point_navigation_path

    client._update_from_base_status_broadcast(
        {"3": {"19": int(TelecontrolStatus.POINT_NAVI)}},
        now=11.0,
    )

    assert client.point_navigation_active

    client._update_from_base_status_broadcast(
        {"3": {"19": int(TelecontrolStatus.UNSPECIFIED)}},
        now=12.0,
    )

    assert not client.point_navigation_active
    assert client.point_navigation_path == ()
    assert client.state.point_navigation_path == []
    assert client.state.point_navigation_target is None


def test_point_navigation_can_complete_while_start_ack_is_pending() -> None:
    client = NarwalClient("127.0.0.1")

    async def send_command(*args, **kwargs) -> CommandResponse:
        client._update_from_base_status_broadcast(
            {"3": {"19": int(TelecontrolStatus.POINT_NAVI)}},
            now=10.0,
        )
        client._update_from_base_status_broadcast(
            {"3": {"19": int(TelecontrolStatus.UNSPECIFIED)}},
            now=11.0,
        )
        return _success()

    client.send_command = AsyncMock(side_effect=send_command)

    asyncio.run(client.start_point_navigation(1.5, -2.5))

    assert not client.point_navigation_active
    assert client.state.point_navigation_target is None


def test_base_status_updates_manual_control_ack_before_state_overlay() -> None:
    client = NarwalClient("127.0.0.1")

    client._update_from_base_status_broadcast({"31": 1}, now=10.0)

    assert client.manual_control_state == ManualControlMode.JOYSTICK


def test_get_status_synchronizes_manual_and_telecontrol_observations() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(
        return_value=CommandResponse(
            data={
                "2": {
                    "31": int(ManualControlMode.JOYSTICK),
                    "3": {"19": int(TelecontrolStatus.POINT_NAVI)},
                }
            }
        )
    )

    asyncio.run(client.get_status(full_update=True))

    assert client.manual_control_state == ManualControlMode.JOYSTICK
    assert client.telecontrol_status == TelecontrolStatus.POINT_NAVI
    assert client.state.manual_control_state == ManualControlMode.JOYSTICK
    assert client.state.telecontrol_status == TelecontrolStatus.POINT_NAVI
    assert not client.point_navigation_active


def test_cancel_point_navigation_uses_typed_task_cancel() -> None:
    client = NarwalClient("127.0.0.1")
    client._point_navigation_active = True
    response = _success()
    client.send_command = AsyncMock(return_value=response)

    result = asyncio.run(client.cancel_point_navigation())

    assert result is response
    assert not client.point_navigation_active
    assert client.telecontrol_stop_generation == 1
    client.send_command.assert_awaited_once_with(
        TOPIC_CMD_CANCEL,
        payload=b"\x08\x03",
        timeout=10.0,
    )


def test_cancel_point_navigation_clears_ownership_on_command_error() -> None:
    client = NarwalClient("127.0.0.1")
    client._point_navigation_active = True
    client.send_command = AsyncMock(side_effect=RuntimeError("socket lost"))

    with pytest.raises(RuntimeError, match="socket lost"):
        asyncio.run(client.cancel_point_navigation())

    assert not client.point_navigation_active


@pytest.mark.parametrize(
    ("operation", "manual_active", "point_active", "telecontrol_status"),
    [
        ("pulse", False, True, TelecontrolStatus.UNSPECIFIED),
        ("pulse", False, False, TelecontrolStatus.POINT_NAVI),
        ("navigation", True, False, TelecontrolStatus.UNSPECIFIED),
        ("navigation", False, True, TelecontrolStatus.UNSPECIFIED),
        ("navigation", False, False, TelecontrolStatus.POINT_NAVI),
    ],
)
def test_client_motion_rejects_existing_ownership_or_observed_navigation(
    operation: str,
    manual_active: bool,
    point_active: bool,
    telecontrol_status: TelecontrolStatus,
) -> None:
    client = NarwalClient("127.0.0.1")
    client._manual_control_active = manual_active
    client._point_navigation_active = point_active
    client._telecontrol_status = int(telecontrol_status)
    client.send_command = AsyncMock()
    client._publish_command = AsyncMock()

    with pytest.raises(NarwalCommandError, match="already active"):
        if operation == "pulse":
            asyncio.run(client.manual_control_pulse(1, 0))
        else:
            asyncio.run(client.start_point_navigation(1.0, 2.0))

    client.send_command.assert_not_awaited()
    client._publish_command.assert_not_awaited()


@pytest.mark.parametrize("operation", ["pulse", "navigation"])
async def test_motion_fails_fast_while_generic_command_lock_is_held(
    operation: str,
) -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock()
    client._publish_command = AsyncMock()
    await client._command_lock.acquire()
    try:
        with pytest.raises(NarwalCommandError, match="command is already"):
            if operation == "pulse":
                await client.manual_control_pulse(1, 0)
            else:
                await client.start_point_navigation(1.0, 2.0)
    finally:
        client._command_lock.release()

    client.send_command.assert_not_awaited()
    client._publish_command.assert_not_awaited()


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        (TOPIC_CMD_POINT_NAVI, _POINT_REQUEST),
        (TOPIC_CMD_SET_MANUAL_CONTROL_MODE, _JOYSTICK),
    ],
)
async def test_before_send_generation_guard_runs_inside_command_lock(
    topic: str,
    payload: bytes,
) -> None:
    client = NarwalClient("127.0.0.1")
    client._ws = AsyncMock()
    client._connected.set()
    generation = client.telecontrol_stop_generation
    await client._command_lock.acquire()
    task = asyncio.create_task(
        client.send_command(
            topic,
            payload=payload,
            before_send=lambda: client._require_telecontrol_generation(
                generation
            ),
        )
    )
    await asyncio.sleep(0)

    client._telecontrol_stop_generation += 1
    client._command_lock.release()

    with pytest.raises(NarwalCommandError, match="invalidated"):
        await task
    client._ws.send.assert_not_awaited()


@pytest.mark.parametrize("operation", ["pulse", "navigation"])
async def test_stop_generation_invalidates_prepared_motion(
    operation: str,
) -> None:
    client = NarwalClient("127.0.0.1")
    expected_generation = client.telecontrol_stop_generation
    client._telecontrol_stop_generation += 1
    client.send_command = AsyncMock()
    client._publish_command = AsyncMock()

    with pytest.raises(NarwalCommandError, match="invalidated"):
        if operation == "pulse":
            await client.manual_control_pulse(
                1,
                0,
                expected_generation=expected_generation,
            )
        else:
            await client.start_point_navigation(
                1.0,
                2.0,
                expected_generation=expected_generation,
            )

    client.send_command.assert_not_awaited()
    client._publish_command.assert_not_awaited()


async def test_second_point_navigation_does_not_queue_or_emit_motion() -> None:
    client = NarwalClient("127.0.0.1")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def send_command(*args, **kwargs) -> CommandResponse:
        entered.set()
        await release.wait()
        return _success()

    client.send_command = AsyncMock(side_effect=send_command)
    first = asyncio.create_task(client.start_point_navigation(1.0, 2.0))
    await entered.wait()

    with pytest.raises(NarwalCommandError, match="already in progress"):
        await client.start_point_navigation(3.0, 4.0)

    assert client.send_command.await_count == 1
    release.set()
    await first


async def test_second_manual_pulse_does_not_queue_or_emit_motion() -> None:
    client = NarwalClient("127.0.0.1")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def send_command(*args, **kwargs) -> CommandResponse:
        if not entered.is_set():
            entered.set()
            await release.wait()
        return _success()

    client.send_command = AsyncMock(side_effect=send_command)
    client._wait_for_manual_control_state = AsyncMock(return_value=True)
    client._publish_command = AsyncMock()

    with patch(
        "narwal_client.client.asyncio.sleep",
        new=AsyncMock(),
    ):
        first = asyncio.create_task(
            client.manual_control_pulse(1, 0, duration=0.01)
        )
        await entered.wait()

        with pytest.raises(NarwalCommandError, match="already in progress"):
            await client.manual_control_pulse(2, 0, duration=0.01)

        assert client.send_command.await_count == 1
        client._publish_command.assert_not_awaited()
        release.set()
        await first


def test_manual_pulse_waits_for_mode_ack_then_triple_zeros_and_off() -> None:
    client = NarwalClient("127.0.0.1")
    events: list[tuple[str, object]] = []

    async def send_command(
        topic: str,
        *,
        payload: bytes,
        timeout: float,
        before_send=None,
    ) -> CommandResponse:
        if before_send is not None:
            before_send()
        events.append(("command", (topic, payload, timeout)))
        return _success()

    async def wait_for_state(expected: int, *, timeout: float = 2.0) -> bool:
        events.append(("ack", expected))
        return True

    async def publish(topic: str, payload: bytes) -> None:
        events.append(("publish", (topic, payload)))
        if payload != _ZERO_VELOCITY:
            client._manual_control_abort.set()

    client.send_command = AsyncMock(side_effect=send_command)
    client._wait_for_manual_control_state = AsyncMock(
        side_effect=wait_for_state
    )
    client._publish_command = AsyncMock(side_effect=publish)

    with patch(
        "narwal_client.client.asyncio.sleep",
        new=AsyncMock(),
    ):
        response = asyncio.run(
            client.manual_control_pulse(5, -1, duration=0.25)
        )

    assert response.success
    assert events[:3] == [
        (
            "command",
            (TOPIC_CMD_SET_MANUAL_CONTROL_MODE, _JOYSTICK, 10.0),
        ),
        ("ack", int(ManualControlMode.JOYSTICK)),
        (
            "publish",
            (
                TOPIC_CMD_VELOCITY_CONTROL,
                bytes.fromhex(
                    "08 05 "
                    "10 ff ff ff ff ff ff ff ff ff 01"
                ),
            ),
        ),
    ]
    zero_publishes = [
        event
        for event in events
        if event == (
            "publish",
            (TOPIC_CMD_VELOCITY_CONTROL, _ZERO_VELOCITY),
        )
    ]
    assert len(zero_publishes) == 3
    assert events[-2:] == [
        (
            "command",
            (TOPIC_CMD_SET_MANUAL_CONTROL_MODE, _OFF, 10.0),
        ),
        ("ack", int(ManualControlMode.OFF)),
    ]
    assert not client.manual_control_active


def test_manual_pulse_is_capped_at_ten_hertz() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(side_effect=(_success(), _success()))
    client._wait_for_manual_control_state = AsyncMock(
        side_effect=(True, True)
    )
    clock = SimpleNamespace(value=0.0)
    nonzero_publish_times: list[float] = []

    async def publish(_topic: str, payload: bytes) -> None:
        if payload != _ZERO_VELOCITY:
            nonzero_publish_times.append(clock.value)

    async def wait_for(awaitable, timeout: float):
        awaitable.close()
        clock.value += timeout
        raise TimeoutError

    async def sleep(delay: float) -> None:
        clock.value += delay

    client._publish_command = AsyncMock(side_effect=publish)
    fake_time = SimpleNamespace(monotonic=lambda: clock.value)

    with (
        patch.object(client_module, "time", fake_time),
        patch(
            "narwal_client.client.asyncio.wait_for",
            new=wait_for,
        ),
        patch(
            "narwal_client.client.asyncio.sleep",
            new=sleep,
        ),
    ):
        asyncio.run(client.manual_control_pulse(1, 0, duration=0.24))

    assert nonzero_publish_times == pytest.approx([0.0, 0.1, 0.2])
    assert all(
        later - earlier >= 0.1
        for earlier, later in pairwise(nonzero_publish_times)
    )


def test_manual_pulse_still_triple_zeros_and_turns_off_after_send_error() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(side_effect=(_success(), _success()))
    client._wait_for_manual_control_state = AsyncMock(
        side_effect=(True, True)
    )
    payloads: list[bytes] = []

    async def publish(_topic: str, payload: bytes) -> None:
        payloads.append(payload)
        if payload != _ZERO_VELOCITY:
            raise RuntimeError("velocity publish failed")

    client._publish_command = AsyncMock(side_effect=publish)

    with (
        patch(
            "narwal_client.client.asyncio.sleep",
            new=AsyncMock(),
        ),
        pytest.raises(RuntimeError, match="velocity publish failed"),
    ):
        asyncio.run(client.manual_control_pulse(1, 0, duration=0.25))

    assert payloads[1:] == [_ZERO_VELOCITY] * 3
    assert client.send_command.await_args_list[-1] == call(
        TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
        payload=_OFF,
        timeout=10.0,
    )
    assert not client.manual_control_active


def test_failed_joystick_result_never_sends_nonzero_velocity() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(side_effect=(_failed(), _success()))
    client._wait_for_manual_control_state = AsyncMock(return_value=True)
    client._publish_command = AsyncMock()

    with patch(
        "narwal_client.client.asyncio.sleep",
        new=AsyncMock(),
    ):
        result = asyncio.run(
            client.manual_control_pulse(1, 0, duration=0.25)
        )

    assert not result.success
    assert [
        one_call.args[1]
        for one_call in client._publish_command.await_args_list
    ] == [_ZERO_VELOCITY] * 3


async def test_emergency_stop_publishes_raw_safety_frames_before_command_lock() -> None:
    client = NarwalClient("127.0.0.1")
    raw_ready = asyncio.Event()
    raw_frames: list[tuple[str, bytes]] = []

    async def publish(topic: str, payload: bytes) -> None:
        raw_frames.append((topic, payload))
        if len(raw_frames) == 5:
            raw_ready.set()

    async def send_command(*args, **kwargs) -> CommandResponse:
        async with client._command_lock:
            return _success()

    client._publish_command = AsyncMock(side_effect=publish)
    client.send_command = AsyncMock(side_effect=send_command)
    client._wait_for_manual_control_state = AsyncMock(return_value=True)
    await client._command_lock.acquire()

    with patch(
        "narwal_client.client.asyncio.sleep",
        new=AsyncMock(),
    ):
        stop = asyncio.create_task(client.emergency_stop_telecontrol())
        await asyncio.wait_for(raw_ready.wait(), timeout=1.0)

        assert not stop.done()
        assert raw_frames[:5] == [
            (TOPIC_CMD_CANCEL, b"\x08\x03"),
            (TOPIC_CMD_VELOCITY_CONTROL, _ZERO_VELOCITY),
            (TOPIC_CMD_VELOCITY_CONTROL, _ZERO_VELOCITY),
            (TOPIC_CMD_VELOCITY_CONTROL, _ZERO_VELOCITY),
            (TOPIC_CMD_SET_MANUAL_CONTROL_MODE, _OFF),
        ]

        client._command_lock.release()
        await stop

    assert [one_call.args[0] for one_call in client.send_command.await_args_list] == [
        TOPIC_CMD_CANCEL,
        TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
    ]


def test_emergency_stop_attempts_manual_stop_and_typed_navigation_cancel() -> None:
    client = NarwalClient("127.0.0.1")
    client._manual_control_active = True
    client._point_navigation_active = True
    client._stop_manual_control_locked = AsyncMock()
    client.send_command = AsyncMock(return_value=_success())

    asyncio.run(client.emergency_stop_telecontrol())

    assert client.telecontrol_stop_generation == 1
    client._stop_manual_control_locked.assert_awaited_once_with()
    client.send_command.assert_awaited_once_with(
        TOPIC_CMD_CANCEL,
        payload=b"\x08\x03",
        timeout=10.0,
    )
    assert not client.point_navigation_active


def test_emergency_stop_still_cancels_navigation_after_manual_failure() -> None:
    client = NarwalClient("127.0.0.1")
    client._stop_manual_control_locked = AsyncMock(
        side_effect=RuntimeError("manual cleanup failed")
    )
    client.send_command = AsyncMock(return_value=_success())

    with pytest.raises(
        NarwalCommandError,
        match="manual cleanup failed",
    ):
        asyncio.run(client.emergency_stop_telecontrol())

    client.send_command.assert_awaited_once_with(
        TOPIC_CMD_CANCEL,
        payload=b"\x08\x03",
        timeout=10.0,
    )


@pytest.mark.parametrize(
    ("connected", "manual_active", "point_active", "cleanup_count"),
    [
        (True, False, False, 0),
        (True, True, False, 1),
        (True, False, True, 1),
        (False, True, True, 0),
    ],
)
def test_disconnect_cleans_up_only_connected_client_owned_telecontrol(
    connected: bool,
    manual_active: bool,
    point_active: bool,
    cleanup_count: int,
) -> None:
    client = NarwalClient("127.0.0.1")
    websocket = AsyncMock()
    client._ws = websocket
    if connected:
        client._connected.set()
    client._manual_control_active = manual_active
    client._point_navigation_active = point_active
    client.emergency_stop_telecontrol = AsyncMock()

    asyncio.run(client.disconnect())

    assert (
        client.emergency_stop_telecontrol.await_count == cleanup_count
    )
    websocket.close.assert_awaited_once_with()
    assert client._ws is None


def test_disconnect_does_not_adopt_unsolicited_point_navigation() -> None:
    client = NarwalClient("127.0.0.1")
    websocket = AsyncMock()
    client._ws = websocket
    client._connected.set()
    client._telecontrol_status = int(TelecontrolStatus.POINT_NAVI)
    client.emergency_stop_telecontrol = AsyncMock()

    asyncio.run(client.disconnect())

    client.emergency_stop_telecontrol.assert_not_awaited()
    websocket.close.assert_awaited_once_with()


@pytest.mark.parametrize("motion", ["manual", "point"])
async def test_disconnect_stops_motion_start_waiting_for_ack(
    motion: str,
) -> None:
    client = NarwalClient("127.0.0.1")
    websocket = AsyncMock()
    client._ws = websocket
    client._connected.set()
    command_started = asyncio.Event()
    release_command = asyncio.Event()
    raw_ready = asyncio.Event()
    raw_frames: list[tuple[str, bytes]] = []
    start_topic = (
        TOPIC_CMD_SET_MANUAL_CONTROL_MODE
        if motion == "manual"
        else TOPIC_CMD_POINT_NAVI
    )

    async def send_command(
        topic: str,
        *args: object,
        **kwargs: object,
    ) -> CommandResponse:
        if topic == start_topic and not command_started.is_set():
            command_started.set()
            await release_command.wait()
        return _success()

    async def publish(topic: str, payload: bytes) -> None:
        raw_frames.append((topic, payload))
        if len(raw_frames) == 5:
            raw_ready.set()

    client.send_command = AsyncMock(side_effect=send_command)
    client._publish_command = AsyncMock(side_effect=publish)
    client._wait_for_manual_control_state = AsyncMock(return_value=True)

    if motion == "manual":
        motion_task = asyncio.create_task(
            client.manual_control_pulse(1, 0, duration=0.25)
        )
    else:
        motion_task = asyncio.create_task(
            client.start_point_navigation(1.5, -2.5)
        )
    await asyncio.wait_for(command_started.wait(), timeout=1.0)

    with patch(
        "narwal_client.client.asyncio.sleep",
        new=AsyncMock(),
    ):
        disconnect_task = asyncio.create_task(client.disconnect())
        await asyncio.wait_for(raw_ready.wait(), timeout=1.0)

        assert not disconnect_task.done()
        assert raw_frames[:5] == [
            (TOPIC_CMD_CANCEL, b"\x08\x03"),
            (TOPIC_CMD_VELOCITY_CONTROL, _ZERO_VELOCITY),
            (TOPIC_CMD_VELOCITY_CONTROL, _ZERO_VELOCITY),
            (TOPIC_CMD_VELOCITY_CONTROL, _ZERO_VELOCITY),
            (TOPIC_CMD_SET_MANUAL_CONTROL_MODE, _OFF),
        ]

        release_command.set()
        with pytest.raises(
            NarwalCommandError,
            match="invalidated by a stop command",
        ):
            await motion_task
        await disconnect_task

    websocket.close.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("linear", "angular", "duration", "error_type", "match"),
    [
        (True, 0, 0.1, TypeError, "linear_velocity"),
        (0, False, 0.1, TypeError, "angular_velocity"),
        (11, 0, 0.1, ValueError, "between -10 and 10"),
        (0, -11, 0.1, ValueError, "between -10 and 10"),
        (0, 0, 0.1, ValueError, "non-zero"),
        (1, 0, True, TypeError, "duration"),
        (1, 0, 0.0, ValueError, "at most 0.5"),
        (1, 0, 0.5001, ValueError, "at most 0.5"),
    ],
)
def test_manual_pulse_validation(
    linear: int,
    angular: int,
    duration: float,
    error_type: type[Exception],
    match: str,
) -> None:
    client = NarwalClient("127.0.0.1")

    with pytest.raises(error_type, match=match):
        asyncio.run(
            client.manual_control_pulse(
                linear,
                angular,
                duration=duration,
            )
        )
