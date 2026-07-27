"""Confirmed, field-preserving schedule enabled-state control."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from narwal_client.client import NarwalClient, NarwalCommandError
from narwal_client.config import CleanMode
from narwal_client.const import (
    TOPIC_CMD_GET_CLEAN_SCHEDULES,
    TOPIC_CMD_UPDATE_CLEAN_SCHEDULE,
)
from narwal_client.models import CommandResponse
from narwal_client.schedule import (
    CleanSchedule,
    CleanScheduleParam,
    Crontab,
    GetCleanSchedulesResponse,
    RawProtobufField,
    ScheduleError,
    ScheduleErrorCode,
    UpdateCleanScheduleResponse,
    decode_update_clean_schedule_request,
    encode_get_clean_schedules_response,
    encode_update_clean_schedule_response,
)


def _schedule(
    *,
    enabled: bool,
    cron: str = "0 30 9 * * 1",
    reminding_time: int = -15,
    clean_plan_id: int = 7,
    custom_name: str = "Morning",
    crontab_unknown: tuple[RawProtobufField, ...] = (
        RawProtobufField(90, 0, 17),
    ),
    parameter_unknown: tuple[RawProtobufField, ...] = (
        RawProtobufField(91, 2, b"parameter"),
    ),
    schedule_unknown: tuple[RawProtobufField, ...] = (
        RawProtobufField(92, 5, b"\x01\x02\x03\x04"),
    ),
) -> CleanSchedule:
    return CleanSchedule(
        task_id=42,
        clean_schedule_param=CleanScheduleParam(
            crontab=Crontab(
                cron=cron,
                reminding_time=reminding_time,
                enabled=enabled,
                unknown_fields=crontab_unknown,
            ),
            clean_plan_id=clean_plan_id,
            clean_mode=CleanMode.SWEEP_AND_MOP_SYNC,
            is_custom_plan=True,
            custom_name=custom_name,
            unknown_fields=parameter_unknown,
        ),
        unknown_fields=schedule_unknown,
    )


def _inventory(schedule: CleanSchedule | None) -> bytes:
    return encode_get_clean_schedules_response(
        GetCleanSchedulesResponse(
            error_code=ScheduleErrorCode(code=ScheduleError.SUCCESS),
            clean_schedules=(schedule,) if schedule is not None else (),
        )
    )


def _update_response(error: ScheduleError) -> bytes:
    return encode_update_clean_schedule_response(
        UpdateCleanScheduleResponse(
            error_code=ScheduleErrorCode(code=error),
        )
    )


async def test_toggle_uses_a_fresh_schedule_and_preserves_every_field() -> None:
    client = NarwalClient("127.0.0.1")
    stale_cached = _schedule(enabled=True)
    fresh = _schedule(
        enabled=True,
        cron="15 45 6 * * 2",
        reminding_time=30,
        clean_plan_id=88,
        custom_name="Fresh schedule from app",
        crontab_unknown=(RawProtobufField(100, 0, 99),),
        parameter_unknown=(RawProtobufField(101, 2, b"fresh parameter"),),
        schedule_unknown=(RawProtobufField(102, 5, b"\x05\x06\x07\x08"),),
    )
    expected = _schedule(
        enabled=False,
        cron="15 45 6 * * 2",
        reminding_time=30,
        clean_plan_id=88,
        custom_name="Fresh schedule from app",
        crontab_unknown=(RawProtobufField(100, 0, 99),),
        parameter_unknown=(RawProtobufField(101, 2, b"fresh parameter"),),
        schedule_unknown=(RawProtobufField(102, 5, b"\x05\x06\x07\x08"),),
    )
    client.state.clean_schedules = (stale_cached,)
    client.send_command = AsyncMock(
        side_effect=[
            CommandResponse(raw_payload=_inventory(fresh)),
            CommandResponse(raw_payload=_update_response(ScheduleError.SUCCESS)),
            CommandResponse(raw_payload=_inventory(expected)),
        ]
    )

    result = await client.set_clean_schedule_enabled(42, False)

    fresh_get_call, update_call, readback_call = client.send_command.await_args_list
    assert fresh_get_call.args[0] == TOPIC_CMD_GET_CLEAN_SCHEDULES
    assert update_call.args[0] == TOPIC_CMD_UPDATE_CLEAN_SCHEDULE
    decoded = decode_update_clean_schedule_request(update_call.kwargs["payload"])
    assert decoded.clean_schedule is not None
    updated = decoded.clean_schedule
    assert updated == expected
    assert updated != stale_cached
    assert readback_call.args[0] == TOPIC_CMD_GET_CLEAN_SCHEDULES
    assert result.clean_schedules == client.state.clean_schedules
    assert result.clean_schedules == (expected,)


async def test_toggle_rejects_a_missing_or_noneditable_schedule() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(
        return_value=CommandResponse(raw_payload=_inventory(None))
    )

    with pytest.raises(NarwalCommandError, match="missing or has no editable"):
        await client.set_clean_schedule_enabled(42, False)

    client.send_command.assert_awaited_once_with(TOPIC_CMD_GET_CLEAN_SCHEDULES)


async def test_toggle_rejects_an_unsuccessful_update_without_readback() -> None:
    client = NarwalClient("127.0.0.1")
    client.state.clean_schedules = (_schedule(enabled=True),)
    client.send_command = AsyncMock(
        side_effect=[
            CommandResponse(raw_payload=_inventory(_schedule(enabled=True))),
            CommandResponse(
                raw_payload=_update_response(ScheduleError.PARAMETER_ERROR)
            ),
        ]
    )

    with pytest.raises(NarwalCommandError, match="update was not confirmed"):
        await client.set_clean_schedule_enabled(42, False)

    assert [
        call.args[0] for call in client.send_command.await_args_list
    ] == [TOPIC_CMD_GET_CLEAN_SCHEDULES, TOPIC_CMD_UPDATE_CLEAN_SCHEDULE]


async def test_toggle_rejects_a_readback_mismatch() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(
        side_effect=[
            CommandResponse(raw_payload=_inventory(_schedule(enabled=True))),
            CommandResponse(raw_payload=_update_response(ScheduleError.SUCCESS)),
            CommandResponse(
                raw_payload=_inventory(
                    _schedule(
                        enabled=False,
                        custom_name="Changed outside this transaction",
                    )
                )
            ),
        ]
    )

    with pytest.raises(NarwalCommandError, match="readback did not match"):
        await client.set_clean_schedule_enabled(42, False)


async def test_concurrent_toggles_are_serialized_as_full_transactions() -> None:
    client = NarwalClient("127.0.0.1")
    server_schedule = _schedule(enabled=True)
    first_update_started = asyncio.Event()
    release_first_update = asyncio.Event()
    calls: list[str] = []
    updates: list[CleanSchedule] = []

    async def send_command(
        short_topic: str,
        payload: bytes = b"",
        **_kwargs: object,
    ) -> CommandResponse:
        nonlocal server_schedule
        calls.append(short_topic)
        if short_topic == TOPIC_CMD_GET_CLEAN_SCHEDULES:
            return CommandResponse(raw_payload=_inventory(server_schedule))
        if short_topic != TOPIC_CMD_UPDATE_CLEAN_SCHEDULE:
            raise AssertionError(f"unexpected topic: {short_topic}")

        decoded = decode_update_clean_schedule_request(payload)
        assert decoded.clean_schedule is not None
        updates.append(decoded.clean_schedule)
        if len(updates) == 1:
            first_update_started.set()
            await release_first_update.wait()
        server_schedule = decoded.clean_schedule
        return CommandResponse(raw_payload=_update_response(ScheduleError.SUCCESS))

    client.send_command = AsyncMock(side_effect=send_command)
    first = asyncio.create_task(client.set_clean_schedule_enabled(42, False))
    await first_update_started.wait()

    second = asyncio.create_task(client.set_clean_schedule_enabled(42, True))
    await asyncio.sleep(0)
    assert calls == [TOPIC_CMD_GET_CLEAN_SCHEDULES, TOPIC_CMD_UPDATE_CLEAN_SCHEDULE]

    release_first_update.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert calls == [
        TOPIC_CMD_GET_CLEAN_SCHEDULES,
        TOPIC_CMD_UPDATE_CLEAN_SCHEDULE,
        TOPIC_CMD_GET_CLEAN_SCHEDULES,
        TOPIC_CMD_GET_CLEAN_SCHEDULES,
        TOPIC_CMD_UPDATE_CLEAN_SCHEDULE,
        TOPIC_CMD_GET_CLEAN_SCHEDULES,
    ]
    assert [
        update.clean_schedule_param.crontab.enabled
        for update in updates
        if update.clean_schedule_param is not None
        and update.clean_schedule_param.crontab is not None
    ] == [False, True]
    assert first_result.clean_schedules == (_schedule(enabled=False),)
    assert second_result.clean_schedules == (_schedule(enabled=True),)
    assert server_schedule == _schedule(enabled=True)
