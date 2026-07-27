"""Fail-closed transport tests for persistent Narwal config writes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from narwal_client.client import NarwalClient, NarwalCommandError
from narwal_client.config import (
    AvoidMode,
    ConfigSnapshot,
    SetConfigField,
    SetConfigPatch,
)
from narwal_client.const import TOPIC_CMD_SET_CONFIG, CommandResult
from narwal_client.models import CommandResponse


def _response(
    result_code: int = CommandResult.SUCCESS,
    *,
    result_known: bool = True,
) -> CommandResponse:
    return CommandResponse(
        result_code=result_code,
        result_known=result_known,
    )


def _snapshot(
    values: dict[SetConfigField, object],
) -> ConfigSnapshot:
    return ConfigSnapshot(values=values, raw_fields={})


async def test_set_config_sends_exact_payload_then_reads_back() -> None:
    client = NarwalClient("127.0.0.1")
    patch = SetConfigPatch(
        SetConfigField.AVOID_MODE,
        AvoidMode.SAFER,
    )
    snapshot = _snapshot(
        {SetConfigField.AVOID_MODE: AvoidMode.SAFER}
    )
    events: list[str] = []

    async def send_command(
        topic: str,
        *,
        payload: bytes,
    ) -> CommandResponse:
        events.append("set")
        assert topic == TOPIC_CMD_SET_CONFIG
        assert payload == bytes.fromhex("90 02 02")
        return _response()

    async def get_config() -> ConfigSnapshot:
        events.append("get")
        return snapshot

    client.send_command = AsyncMock(side_effect=send_command)
    client.get_config = AsyncMock(side_effect=get_config)

    result = await client.set_config_patch(patch)

    assert result is snapshot
    assert events == ["set", "get"]


@pytest.mark.parametrize(
    "response",
    [
        _response(CommandResult.NOT_APPLICABLE),
        _response(CommandResult.SUCCESS, result_known=False),
    ],
)
async def test_set_config_rejects_failed_or_unconfirmed_response(
    response: CommandResponse,
) -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(return_value=response)
    client.get_config = AsyncMock()

    with pytest.raises(NarwalCommandError, match="config/set failed"):
        await client.set_config_patch(
            SetConfigPatch(
                SetConfigField.CHILD_LOCK_ENABLED,
                True,
            )
        )

    client.get_config.assert_not_awaited()


@pytest.mark.parametrize(
    ("snapshot", "match"),
    [
        (
            _snapshot({}),
            "omitted requested field",
        ),
        (
            _snapshot({SetConfigField.CHILD_LOCK_ENABLED: False}),
            "readback mismatch",
        ),
    ],
)
async def test_set_config_rejects_absent_or_mismatched_readback(
    snapshot: ConfigSnapshot,
    match: str,
) -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(return_value=_response())
    client.get_config = AsyncMock(return_value=snapshot)

    with pytest.raises(NarwalCommandError, match=match):
        await client.set_config_patch(
            SetConfigPatch(
                SetConfigField.CHILD_LOCK_ENABLED,
                True,
            )
        )

    client.get_config.assert_awaited_once_with()
