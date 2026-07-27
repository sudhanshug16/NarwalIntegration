"""Tests for capability- and snapshot-backed persistent config entities."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import tests.ha_stubs

tests.ha_stubs.install()

from homeassistant.exceptions import HomeAssistantError

from custom_components.narwal.narwal_client import Capability
from custom_components.narwal.narwal_client.config import (
    SET_CONFIG_FIELD_SPECS,
    AvoidMode,
    CleanMode,
    CleanMopFrequency,
    ConfigSnapshot,
    DryMopStrength,
    Language,
    SetConfigField,
    StationLightCtrlType,
)
from custom_components.narwal.number import NarwalVolumeNumber
from custom_components.narwal.select import (
    CONFIG_SELECT_DESCRIPTIONS,
    NarwalConfigSelect,
)
from custom_components.narwal.switch import (
    SWITCH_DESCRIPTIONS,
    NarwalConfigSwitch,
)


def _coordinator(
    values: dict,
    *,
    capabilities: dict[int, int] | None = None,
):
    state = SimpleNamespace(
        config_snapshot=ConfigSnapshot(values=values, raw_fields={}),
        capabilities=capabilities or {},
        firmware_version="v01.03.10.03",
    )
    return SimpleNamespace(
        config_entry=SimpleNamespace(
            data={"device_id": "ax15-id"},
            title="Freo X10 Pro",
        ),
        client=SimpleNamespace(state=state),
        data=state,
        last_update_success=True,
        device_profile=SimpleNamespace(
            config_writes_enabled=True,
            display_model="Narwal Freo X10 Pro",
            hardware_model="AX15",
        ),
        async_set_config=AsyncMock(),
    )


def _config_select(key: str):
    return next(
        description
        for description in CONFIG_SELECT_DESCRIPTIONS
        if description.key == key
    )


def _config_switch(key: str):
    return next(
        description
        for description in SWITCH_DESCRIPTIONS
        if description.key == key
    )


def test_persistent_select_reads_and_writes_exact_enum() -> None:
    coordinator = _coordinator(
        {SetConfigField.LANGUAGE: Language.ENGLISH},
        capabilities={int(Capability.OPERATE_LANGUAGE): 1},
    )
    entity = NarwalConfigSelect(coordinator, _config_select("robot_language"))

    assert entity.available
    assert entity.current_option == "English"

    asyncio.run(entity.async_select_option("French"))

    coordinator.async_set_config.assert_awaited_once_with(
        SetConfigField.LANGUAGE,
        Language.FRENCH,
    )


def test_avoidance_select_does_not_offer_unsafe_off_mode() -> None:
    coordinator = _coordinator(
        {SetConfigField.AVOID_MODE: AvoidMode.SMART},
        capabilities={int(Capability.AVOID_MODE_CONFIG): 1},
    )
    entity = NarwalConfigSelect(
        coordinator,
        _config_select("obstacle_avoidance"),
    )

    assert entity.options == ["Smart", "Safer"]
    assert "Disabled" not in entity.options


@pytest.mark.parametrize(
    ("key", "field", "initial", "option", "expected"),
    [
        (
            "dry_mop_strength",
            SetConfigField.DRY_MOP_STRENGTH,
            DryMopStrength.QUIET,
            "Smart",
            DryMopStrength.SMART,
        ),
        (
            "mop_wash_frequency",
            SetConfigField.CLEAN_MOP_FREQUENCY,
            CleanMopFrequency.NORMAL,
            "Deep",
            CleanMopFrequency.DEEP,
        ),
        (
            "robot_clean_mode",
            SetConfigField.ROBOT_CLEAN_MODE,
            CleanMode.SMART,
            "Vacuum then mop",
            CleanMode.SWEEP_THEN_MOP,
        ),
        (
            "station_light",
            SetConfigField.STATION_LIGHT_CTRL_TYPE,
            StationLightCtrlType.OFF,
            "On",
            StationLightCtrlType.ON,
        ),
    ],
)
def test_new_persistent_selects_write_exact_enums(
    key: str,
    field: SetConfigField,
    initial: IntEnum,
    option: str,
    expected: IntEnum,
) -> None:
    description = _config_select(key)
    capabilities = (
        {int(description.required_feature): 1}
        if description.required_feature is not None
        else {}
    )
    coordinator = _coordinator(
        {field: initial},
        capabilities=capabilities,
    )
    entity = NarwalConfigSelect(coordinator, description)

    assert entity.available
    assert entity.current_option != option
    asyncio.run(entity.async_select_option(option))

    coordinator.async_set_config.assert_awaited_once_with(field, expected)


def test_every_typed_config_enum_has_one_select_entity() -> None:
    enum_fields = {
        field
        for field, spec in SET_CONFIG_FIELD_SPECS.items()
        if issubclass(spec.value_type, IntEnum)
    }
    description_fields = [
        description.config_field for description in CONFIG_SELECT_DESCRIPTIONS
    ]

    assert set(description_fields) == enum_fields
    assert len(description_fields) == len(enum_fields)


def test_persistent_switch_reads_and_writes_boolean() -> None:
    coordinator = _coordinator(
        {SetConfigField.PET_MODE: True},
        capabilities={int(Capability.PET_MODE): 1},
    )
    entity = NarwalConfigSwitch(coordinator, _config_switch("pet_mode"))

    assert entity.available
    assert entity.is_on is True

    asyncio.run(entity.async_turn_off())

    coordinator.async_set_config.assert_awaited_once_with(
        SetConfigField.PET_MODE,
        False,
    )


def test_every_typed_boolean_config_has_one_switch_entity() -> None:
    boolean_fields = {
        field
        for field, spec in SET_CONFIG_FIELD_SPECS.items()
        if spec.value_type is bool
    }
    description_fields = [
        description.config_field for description in SWITCH_DESCRIPTIONS
    ]

    assert set(description_fields) == boolean_fields
    assert len(description_fields) == len(boolean_fields)


EXPECTED_NEW_SWITCH_CAPABILITIES = {
    "smart_clean_detection": None,
    "smart_deep_clean": None,
    "moisture_proof_mop_pad": None,
    "dust_collection": None,
    "smart_dust_collection": Capability.DUST_SENSOR,
    "dry_robot_bag": Capability.TEMP_HUMIDITY_DETECTION_FOR_DRY_DUST_BAG,
    "hot_water_wash": Capability.HOT_WATER_WASH,
    "massive_dirty_deep_clean": Capability.CLEAN_TASK_MASSIVE_DIRTY_CLEAN,
    "speech_control": Capability.SPEECH,
    "all_things_recognition": Capability.ALL_THINGS_RECOGNITION,
    "precious_item_guard": Capability.PRECIOUS_ITEM_GUARD,
}


@pytest.mark.parametrize(
    ("key", "required_feature"),
    EXPECTED_NEW_SWITCH_CAPABILITIES.items(),
)
def test_new_switches_have_exact_capability_gates(
    key: str,
    required_feature: Capability | None,
) -> None:
    assert _config_switch(key).required_feature == required_feature


@pytest.mark.parametrize(
    "key",
    [
        key
        for key, capability in EXPECTED_NEW_SWITCH_CAPABILITIES.items()
        if capability is not None
    ],
)
def test_capability_gated_switch_is_unavailable_without_feature(key: str) -> None:
    description = _config_switch(key)
    coordinator = _coordinator({description.config_field: True})
    entity = NarwalConfigSwitch(coordinator, description)

    assert not entity.available
    with pytest.raises(HomeAssistantError, match="not currently available"):
        asyncio.run(entity.async_turn_on())
    coordinator.async_set_config.assert_not_awaited()

    coordinator.client.state.capabilities[
        int(description.required_feature)
    ] = 1
    assert entity.available


@pytest.mark.parametrize(
    ("key", "required_feature"),
    [
        ("robot_clean_mode", Capability.CUSTOMIZE_SMART_CLEAN_PARAM),
        ("station_light", Capability.STATION_LIGHT_CTRL),
    ],
)
def test_new_capability_gated_selects_require_exact_feature(
    key: str,
    required_feature: Capability,
) -> None:
    description = _config_select(key)
    initial = description.option_values[0][1]
    coordinator = _coordinator({description.config_field: initial})
    entity = NarwalConfigSelect(coordinator, description)

    assert description.required_feature == required_feature
    assert not entity.available
    with pytest.raises(HomeAssistantError, match="not currently available"):
        asyncio.run(entity.async_select_option(entity.options[0]))
    coordinator.async_set_config.assert_not_awaited()

    coordinator.client.state.capabilities[int(required_feature)] = 1
    assert entity.available


def test_new_selects_and_switches_are_filtered_by_live_capabilities() -> None:
    from custom_components.narwal.select import async_setup_entry as setup_selects
    from custom_components.narwal.switch import async_setup_entry as setup_switches

    select_values = {
        SetConfigField.DRY_MOP_STRENGTH: DryMopStrength.SMART,
        SetConfigField.CLEAN_MOP_FREQUENCY: CleanMopFrequency.NORMAL,
        SetConfigField.ROBOT_CLEAN_MODE: CleanMode.SMART,
        SetConfigField.STATION_LIGHT_CTRL_TYPE: StationLightCtrlType.ON,
    }
    select_coordinator = _coordinator(select_values)
    select_coordinator.parameterized_clean_enabled = False
    select_entities = MagicMock()
    asyncio.run(
        setup_selects(
            MagicMock(),
            SimpleNamespace(runtime_data=select_coordinator),
            select_entities,
        )
    )
    assert {
        entity.entity_description.key
        for entity in select_entities.call_args.args[0]
    } == {
        "dry_mop_strength",
        "mop_wash_frequency",
    }

    switch_values = {
        _config_switch(key).config_field: True
        for key in EXPECTED_NEW_SWITCH_CAPABILITIES
    }
    switch_coordinator = _coordinator(
        switch_values,
        capabilities={
            int(Capability.DUST_SENSOR): 1,
            int(Capability.HOT_WATER_WASH): 1,
        },
    )
    switch_entities = MagicMock()
    asyncio.run(
        setup_switches(
            MagicMock(),
            SimpleNamespace(runtime_data=switch_coordinator),
            switch_entities,
        )
    )
    assert {
        entity.entity_description.key
        for entity in switch_entities.call_args.args[0]
    } == {
        "smart_clean_detection",
        "smart_deep_clean",
        "moisture_proof_mop_pad",
        "dust_collection",
        "smart_dust_collection",
        "hot_water_wash",
    }


def test_new_config_entities_have_strings_and_en_fr_translations() -> None:
    repository = Path(__file__).resolve().parents[1]
    files = (
        repository / "custom_components" / "narwal" / "strings.json",
        repository
        / "custom_components"
        / "narwal"
        / "translations"
        / "en.json",
        repository
        / "custom_components"
        / "narwal"
        / "translations"
        / "fr.json",
    )
    expected = {
        "select": {
            description.translation_key
            for description in CONFIG_SELECT_DESCRIPTIONS
        },
        "switch": {
            description.translation_key for description in SWITCH_DESCRIPTIONS
        },
    }

    for path in files:
        document = json.loads(path.read_text())
        for platform, keys in expected.items():
            assert keys <= document["entity"][platform].keys()


def test_config_entity_is_unavailable_when_snapshot_field_disappears() -> None:
    coordinator = _coordinator(
        {SetConfigField.PET_MODE: True},
        capabilities={int(Capability.PET_MODE): 1},
    )
    entity = NarwalConfigSwitch(coordinator, _config_switch("pet_mode"))
    coordinator.client.state.config_snapshot = ConfigSnapshot(
        values={},
        raw_fields={},
    )

    assert not entity.available
    assert entity.is_on is None
    with pytest.raises(HomeAssistantError, match="not currently available"):
        asyncio.run(entity.async_turn_off())
    coordinator.async_set_config.assert_not_awaited()


def test_volume_is_integer_percent_and_uses_exact_field() -> None:
    coordinator = _coordinator(
        {SetConfigField.VOLUME_PERCENTAGE: 29},
    )
    entity = NarwalVolumeNumber(coordinator)

    assert entity.available
    assert entity.native_value == 29.0

    asyncio.run(entity.async_set_native_value(35.0))

    coordinator.async_set_config.assert_awaited_once_with(
        SetConfigField.VOLUME_PERCENTAGE,
        35,
    )


def test_volume_write_is_blocked_when_live_field_disappears() -> None:
    coordinator = _coordinator(
        {SetConfigField.VOLUME_PERCENTAGE: 29},
    )
    entity = NarwalVolumeNumber(coordinator)
    coordinator.client.state.config_snapshot = ConfigSnapshot(
        values={},
        raw_fields={},
    )

    assert not entity.available
    with pytest.raises(HomeAssistantError, match="not currently available"):
        asyncio.run(entity.async_set_native_value(35.0))
    coordinator.async_set_config.assert_not_awaited()


def test_platform_setup_filters_missing_capabilities_and_fields() -> None:
    from custom_components.narwal.select import async_setup_entry

    coordinator = _coordinator(
        {
            SetConfigField.LANGUAGE: Language.ENGLISH,
            SetConfigField.AVOID_MODE: AvoidMode.SMART,
        },
        capabilities={int(Capability.OPERATE_LANGUAGE): 1},
    )
    coordinator.parameterized_clean_enabled = False
    entry = SimpleNamespace(runtime_data=coordinator)
    add_entities = MagicMock()

    asyncio.run(async_setup_entry(MagicMock(), entry, add_entities))

    entities = add_entities.call_args.args[0]
    assert [entity.entity_description.key for entity in entities] == [
        "robot_language"
    ]
