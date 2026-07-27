"""Tests for model and capability operation profiles."""

from __future__ import annotations

from types import SimpleNamespace

import tests.ha_stubs

tests.ha_stubs.install()

from custom_components.narwal.profile import profile_for_client  # noqa: E402
from narwal_client.capabilities import Capability  # noqa: E402
from narwal_client.models import DeviceInfo, NarwalState  # noqa: E402


def _client(
    product_key: str,
    firmware: str,
    capabilities: dict[int, int] | None = None,
) -> SimpleNamespace:
    state = NarwalState(
        device_info=DeviceInfo(
            product_key=product_key,
            firmware_version=firmware,
        ),
        capabilities=capabilities or {},
    )
    return SimpleNamespace(state=state, topic_prefix=f"/{product_key}")


def test_x10_parameterized_clean_is_enabled_by_default() -> None:
    client = _client(
        "CNbforyZWI",
        "v01.03.10.03",
        {int(Capability.MULTI_ZONE_CLEAN): 1},
    )

    profile = profile_for_client(client)

    assert profile.display_model == "Narwal Freo X10 Pro"
    assert profile.hardware_model == "AX15"
    assert profile.parameterized_clean_enabled


def test_x10_parameterized_clean_is_not_firmware_locked() -> None:
    client = _client(
        "CNbforyZWI",
        "v99.99.99.99",
        {int(Capability.MULTI_ZONE_CLEAN): 1},
    )

    assert profile_for_client(client).parameterized_clean_enabled


def test_x10_telecontrol_is_capability_gated_but_not_firmware_locked() -> None:
    client = _client(
        "CNbforyZWI",
        "v99.99.99.99",
        {int(Capability.TELECONTROL_HEARTBEAT): 1},
    )

    profile = profile_for_client(client)

    assert profile.telecontrol_enabled


def test_x10_config_writes_are_capability_gated_not_firmware_locked() -> None:
    client = _client(
        "CNbforyZWI",
        "v99.99.99.99",
        {int(Capability.UPLOAD_CONFIGURATION): 1},
    )

    assert profile_for_client(client).config_writes_enabled


def test_config_writes_do_not_leak_to_other_product_profiles() -> None:
    client = _client(
        "QxMSPG6VSO",
        "v01.07.23.00",
        {int(Capability.UPLOAD_CONFIGURATION): 1},
    )

    assert not profile_for_client(client).config_writes_enabled


def test_telecontrol_does_not_leak_to_other_product_profiles() -> None:
    client = _client(
        "QxMSPG6VSO",
        "v01.07.23.00",
        {int(Capability.TELECONTROL_HEARTBEAT): 1},
    )

    assert not profile_for_client(client).telecontrol_enabled


def test_capability_is_required() -> None:
    client = _client("CNbforyZWI", "v01.03.10.03")

    assert not profile_for_client(client).parameterized_clean_enabled
    assert not profile_for_client(client).telecontrol_enabled
    assert not profile_for_client(client).config_writes_enabled


def test_flow2_without_an_exact_validation_record_stays_closed() -> None:
    client = _client(
        "QxMSPG6VSO",
        "v01.07.23.00",
        {int(Capability.MULTI_ZONE_CLEAN): 1},
    )

    profile = profile_for_client(client)

    assert not profile.parameterized_clean_enabled


def test_x10_station_actions_are_exposed() -> None:
    client = _client(
        "CNbforyZWI",
        "v01.03.10.03",
        {
            int(Capability.WASH_MOP_BY_ROBOT_STATUS): 1,
            int(Capability.AVOID_MODE_CONFIG): 1,
        },
    )

    profile = profile_for_client(client)

    assert profile.station_actions == frozenset(
        {
            "empty_dustbin",
            "wash_mop",
            "dry_mop",
            "wash_and_dry_mop",
            "dry_dust_bag",
            "dry_station_bag",
        }
    )
    assert not profile.config_writes_enabled


def test_x10_read_only_inventory_surfaces_are_capability_gated() -> None:
    client = _client(
        "CNbforyZWI",
        "v01.03.10.03",
        {
            int(Capability.MULTIMAP_CUSTOM_CLEAN_ORDER_CONFIGURE): 1,
            int(Capability.SCHEDULED_TASK_EXECUTE_ONCE): 1,
            int(Capability.MULTI_MAP): 1,
            int(Capability.FLOOR_PLAN_EDIT): 1,
            int(Capability.APP_UPDATE_MAP): 1,
            int(Capability.CONSUMABLES_ON_CLOUD): 1,
            int(Capability.GET_FIRMWARE_VERSION): 1,
            int(Capability.OPERATE_LANGUAGE): 1,
            int(Capability.SET_CUSTOM_VOICE): 1,
        },
    )

    profile = profile_for_client(client)

    assert profile.clean_plan_inventory_enabled
    assert profile.schedule_inventory_enabled
    assert profile.saved_map_inventory_enabled
    assert profile.editable_map_inventory_enabled
    assert profile.map_update_inventory_enabled
    assert profile.consumable_inventory_enabled
    assert profile.firmware_inventory_enabled
    assert profile.language_inventory_enabled
    assert profile.voice_inventory_enabled
    assert profile.history_inventory_enabled


def test_inventory_capabilities_do_not_leak_to_other_models() -> None:
    client = _client(
        "QxMSPG6VSO",
        "v01.07.23.00",
        {int(capability): 1 for capability in Capability},
    )

    profile = profile_for_client(client)

    assert not profile.clean_plan_inventory_enabled
    assert not profile.schedule_inventory_enabled
    assert not profile.saved_map_inventory_enabled
    assert not profile.editable_map_inventory_enabled
    assert not profile.map_update_inventory_enabled
    assert not profile.consumable_inventory_enabled
    assert not profile.firmware_inventory_enabled
    assert not profile.language_inventory_enabled
    assert not profile.voice_inventory_enabled
    assert not profile.history_inventory_enabled
