"""Tests for read-only discovery methods cached in NarwalState."""

from unittest.mock import AsyncMock

from narwal_client.client import NarwalClient
from narwal_client.config import AvoidMode, SetConfigField
from narwal_client.models import CommandResponse


async def test_feature_fetch_distinguishes_known_empty_from_not_fetched() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(return_value=CommandResponse(data={}))

    assert not client.state.capabilities_fetched
    assert await client.get_feature_list() == {}
    assert client.state.capabilities_fetched


async def test_get_config_caches_typed_and_raw_read_only_snapshot() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(
        return_value=CommandResponse(
            data={"1": {"1": 1}, "2": {"1": 45, "34": 2, "120": 9}}
        )
    )

    snapshot = await client.get_config()

    assert client.state.config_snapshot is snapshot
    assert snapshot.values[SetConfigField.VOLUME_PERCENTAGE] == 45
    assert snapshot.values[SetConfigField.AVOID_MODE] is AvoidMode.SAFER
    assert snapshot.raw_fields[120] == 9


async def test_get_current_task_caches_structured_diagnostics() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(
        return_value=CommandResponse(
            data={
                "1": {"1": 1},
                "2": {
                    "1": 4,
                    "2": {"1": {"1": 1, "2": 7}, "2": {"1": 4}, "3": 1},
                    "5": 4,
                },
            }
        )
    )

    task = await client.get_current_task()

    assert client.state.current_clean_task is task
    assert task.map_id == 4
    assert task.task_type == 4
    assert task.items[0].zone.zone_id == 7


async def test_get_device_info_updates_profile_firmware_source() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(
        return_value=CommandResponse(
            data={
                "1": b"CNbforyZWI",
                "2": b"device-1",
                "3": b"v01.03.10.03",
            }
        )
    )

    await client.get_device_info()

    assert client.state.firmware_version == "v01.03.10.03"
