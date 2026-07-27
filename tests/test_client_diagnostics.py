"""Tests for read-only discovery methods cached in NarwalState."""

from unittest.mock import AsyncMock

from narwal_client.client import NarwalClient
from narwal_client.config import AvoidMode, SetConfigField
from narwal_client.const import (
    TOPIC_CMD_CHECK_MAP_UPDATE_INFO,
    TOPIC_CMD_GET_CLEAN_TIMELINE,
    TOPIC_CMD_GET_CURRENT_VOICE_INFO,
    TOPIC_CMD_GET_EDITABLE_MAP,
    TOPIC_CMD_GET_FIRMWARE_VERSION,
    TOPIC_CMD_GET_LANGUAGE,
    TOPIC_CMD_GET_SUPPORTED_LANGUAGES,
)
from narwal_client.consumables import (
    ConsumableMaintainItem,
    ConsumableReplaceItem,
)
from narwal_client.models import CommandResponse, MapData
from narwal_client.schedule import (
    CleanSchedule,
    CleanScheduleParam,
    Crontab,
    GetCleanSchedulesResponse,
    ScheduleError,
    ScheduleErrorCode,
    encode_get_clean_schedules_response,
)


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


async def test_clean_plan_reads_cache_current_and_saved_plans() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(
        side_effect=[
            CommandResponse(
                data={"1": 1, "2": {"1": 7, "2": 99, "5": b"Current"}}
            ),
            CommandResponse(
                data={
                    "1": 1,
                    "2": [
                        {"1": 7, "2": 99, "5": b"Current"},
                        {"1": 8, "2": 99, "5": b"Night"},
                    ],
                }
            ),
        ]
    )

    current = await client.get_current_clean_plan()
    saved = await client.get_clean_plans()

    assert current.plan is client.state.current_clean_plan
    assert current.plan is not None
    assert current.plan.custom_name == "Current"
    assert client.state.clean_plans == saved.plans
    assert [plan.plan_id for plan in saved.plans] == [7, 8]


async def test_schedule_read_caches_schema_decoded_inventory() -> None:
    client = NarwalClient("127.0.0.1")
    payload = encode_get_clean_schedules_response(
        GetCleanSchedulesResponse(
            error_code=ScheduleErrorCode(code=ScheduleError.SUCCESS),
            clean_schedules=(
                CleanSchedule(
                    task_id=42,
                    clean_schedule_param=CleanScheduleParam(
                        crontab=Crontab(
                            cron="0 30 9 * * 1",
                            reminding_time=15,
                            enabled=True,
                        ),
                        clean_plan_id=7,
                    ),
                ),
            ),
        )
    )
    client.send_command = AsyncMock(
        return_value=CommandResponse(raw_payload=payload)
    )

    result = await client.get_clean_schedules()

    assert client.state.clean_schedules == result.clean_schedules
    assert client.state.clean_schedules[0].task_id == 42
    parameter = client.state.clean_schedules[0].clean_schedule_param
    assert parameter is not None
    assert parameter.crontab is not None
    assert parameter.crontab.cron == "0 30 9 * * 1"


async def test_consumable_read_caches_local_category_inventory() -> None:
    client = NarwalClient("127.0.0.1")
    # Response.field1 -> payload; packed maintain [1,7], packed replace [2,8].
    payload = bytes.fromhex("0a080a02010712020208")
    client.send_command = AsyncMock(
        return_value=CommandResponse(raw_payload=payload)
    )

    result = await client.get_consumable_info()

    assert client.state.consumable_info is result.consumable_info
    assert result.consumable_info is not None
    assert result.consumable_info.maintain_items == (
        ConsumableMaintainItem.DUST_BOX,
        ConsumableMaintainItem.CLIFF_SENSOR,
    )
    assert result.consumable_info.replace_items == (
        ConsumableReplaceItem.MOP,
        ConsumableReplaceItem.DUST_BAG,
    )


async def test_map_inventory_reads_cache_saved_editable_and_update_metadata() -> None:
    client = NarwalClient("127.0.0.1")
    client.state.map_data = MapData(map_id=7)
    client.send_command = AsyncMock(
        side_effect=[
            CommandResponse(data={"1": 1, "2": {"1": 7, "2": 4}}),
            CommandResponse(
                data={"1": 1, "2": {"1": 7, "33": 9}, "3": 9, "4": {"1": 32}}
            ),
            CommandResponse(data={"1": 1, "2": {"1": 7, "2": 5}}),
        ]
    )

    saved = await client.get_saved_maps()
    editable = await client.get_editable_map()
    updated = await client.check_map_update_info()

    assert saved.maps is client.state.saved_maps
    assert client.state.saved_maps_fetched
    assert saved.maps[0].map_data.map_id == 7
    assert editable is client.state.editable_map
    assert client.state.editable_map_fetched
    assert editable.edit_config is not None
    assert editable.edit_config.max_room_nums == 32
    assert updated is client.state.map_update_info
    assert client.state.map_update_info_fetched
    assert updated.result is True
    assert client.send_command.await_args_list[1].args[0] == TOPIC_CMD_GET_EDITABLE_MAP
    assert client.send_command.await_args_list[1].kwargs["payload"] == bytes.fromhex(
        "0807100118012000"
    )
    assert client.send_command.await_args_list[2].args[0] == TOPIC_CMD_CHECK_MAP_UPDATE_INFO


async def test_firmware_language_and_voice_reads_cache_strict_metadata() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(
        side_effect=[
            CommandResponse(raw_payload=b"\x08\x07\x12\x05AX15!"),
            CommandResponse(raw_payload=b"\x08\x01\x10\x01"),
            CommandResponse(raw_payload=b"\x08\x01\x12\x02\x01\x02"),
            CommandResponse(
                raw_payload=b"\x08\x01\x12\x11\x0a\x05en-IN\x12\x04v1.0\x22\x02t1"
            ),
        ]
    )

    firmware = await client.get_firmware_metadata()
    language = await client.get_language_metadata()
    supported = await client.get_supported_languages()
    voice = await client.get_current_voice_info()

    assert firmware is client.state.firmware_metadata
    assert firmware.firmware_version_text == "AX15!"
    assert language is client.state.configured_language
    assert int(language.language) == 1
    assert supported is client.state.supported_languages
    assert [int(item) for item in supported.languages] == [1, 2]
    assert voice is client.state.current_voice_info
    assert voice.voice_info is not None
    assert voice.voice_info.language == "en-IN"
    assert [call.args[0] for call in client.send_command.await_args_list] == [
        TOPIC_CMD_GET_FIRMWARE_VERSION,
        TOPIC_CMD_GET_LANGUAGE,
        TOPIC_CMD_GET_SUPPORTED_LANGUAGES,
        TOPIC_CMD_GET_CURRENT_VOICE_INFO,
    ]


async def test_clean_timeline_uses_official_all_window_and_caches_events() -> None:
    client = NarwalClient("127.0.0.1")
    client.send_command = AsyncMock(
        return_value=CommandResponse(
            data={
                "1": 0,
                "2": {
                    "1": {
                        "1": 1_700_000_000,
                        "2": 4,
                        "5": 1,
                        "7": 1,
                        "8": 99,
                    }
                },
            }
        )
    )

    response = await client.get_clean_timeline()

    assert response is client.state.clean_timeline
    assert response.timeline_status is not None
    assert response.timeline_status.event_nodes[0].node_key == 99
    client.send_command.assert_awaited_once_with(
        TOPIC_CMD_GET_CLEAN_TIMELINE,
        payload=b"\x08\x03",
    )
